"""T6 单元测试: CLI --preset 绑定 DCP (preset → DCP 运行时链路, F-05)。

覆盖 (验收 / 任务 T6):
  - --preset 分支: 加载 preset JSON 后若含 'dcp' 字段 → load_dcp 并用该
    profile 构建 pipeline (pipeline_from_config(cfg, prof=prof)), 输出 JSON
    带 dcp 字段;
  - 缺 'dcp' 字段 (旧 preset): 回退默认 profile, 兼容不改;
  - dcp 字段指向的文件不存在 / 解析失败: 明确错误 JSON (ok=False, error 含路径);
  - e2e: 临时 preset (含指向现有 Camera Standard v2 的 dcp 字段) 走 CLI
    渲染合成小图 (decode 打桩) 与 0711 半尺寸真实 NEF, 断言输出文件存在且
    为合法 JPEG (魔数 FFD8 + cv2.imread 可解码);
  - --preset 亦接受直接 JSON 文件路径 (临时 preset 无需写入 presets/ 目录)。

约定: 渲染测试优先打桩 decode_raw 喂合成小图 (无 NEF 依赖, CI 可跑);
真实 NEF 测试在无数据时 pytest.skip (同 test_e2e 约定)。
运行: python -m pytest rawlab/tests/test_preset_cli.py rawlab/tests/test_retouch_cli.py -q
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

import cv2
import numpy as np
import pytest

import rawlab.rawlab_cli as cli
from rawlab.dcp import load_dcp

REPO_ROOT = Path(__file__).resolve().parents[2]
PRESETS_DIR = REPO_ROOT / "rawlab" / "presets"
PROFILES_DIR = REPO_ROOT / "rawlab" / "profiles"

PREVIEW_BASELINE_DCP = PROFILES_DIR / "Nikon Z 5 2 RawLab Preview Baseline.dcp"

DEFAULT_DCP = (r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera"
               r"\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp")

# 临时 preset 模板参数 (与 lr_baseline.json 同构: exposure baseline + 暖度
# 标定常数 + trim 恒等 + tone profile_curve + colorcal + refine)
_PRESET_PARAMS = {
    "exposure": {"mode": "baseline"},
    "whitebalance": {"mode": "as_shot", "warmth": 0.9,
                     "warmth_b0": 1.79, "warmth_b1": 2.287,
                     "warmth_r_slope": 0.0, "warmth_g_slope": 0.1,
                     "warmth_b_slope": 0.26, "trim": [1.0, 1.0, 1.0]},
    "huesat": {"enabled": False},
    "tone": {"profile_curve": True, "eotf": "srgb"},
    "colorcal": {"neutral_mode": "off", "saturation": -0.12,
                 "skin_protect": 0.0},
    "refine": {"highlight_desat": 0.25},
}
_PRESET_STAGES = ["exposure", "whitebalance", "huesat", "tone",
                  "colorcal", "stylize", "refine"]


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _camera_standard_dcp() -> str | None:
    """可用相机 DCP: RAWLAB_DCP 环境变量 → 默认 Camera Standard v2 → 仓库 Preview 基准。"""
    cands = [os.environ.get("RAWLAB_DCP"), DEFAULT_DCP,
             str(PROFILES_DIR / "Nikon Z 5 2 RawLab Preview Baseline.dcp")]
    for cand in cands:
        if cand and Path(cand).is_file():
            return str(Path(cand).resolve())
    return None


def _write_preset(tmp_path: Path, name: str = "tmp_preset.json",
                  dcp: str | None = "PLACEHOLDER", **extra) -> Path:
    """写一个临时 preset JSON; dcp 缺省填 Camera Standard v2 (T6 验收场景)。"""
    cfg = {"stages": list(_PRESET_STAGES), "params": dict(_PRESET_PARAMS),
           "output": {"quality": 95}}
    if dcp is not None:
        if dcp == "PLACEHOLDER":
            dcp = _camera_standard_dcp()
        cfg["dcp"] = dcp
    cfg.update(extra)
    p = tmp_path / name
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return p


def _run_pipeline(args_list, capsys) -> dict:
    """走真实 CLI 解析 + cmd_pipeline, 返回 stdout JSON。"""
    args = cli.build_parser().parse_args(args_list)
    cli.cmd_pipeline(args)
    return json.loads(capsys.readouterr().out)


def _resolve_nef() -> list[str]:
    dirs = []
    env = os.environ.get("RAWLAB_RAW_DIRS")
    if env:
        dirs = [d for d in env.split(";") if d]
    else:
        d = r"K:\data\photo\0711\raw"
        if os.path.isdir(d):
            dirs = [d]
    files = []
    for d in dirs:
        files.extend(glob.glob(os.path.join(d, "*.NEF")))
    return sorted(files)


@pytest.fixture
def synthetic_decode(monkeypatch):
    """打桩 engine.decode.decode_raw: 喂合成小图 (64×64 渐变), 免真实 NEF。"""
    import rawlab.engine.decode as dec

    class _MockRaw:
        camera_whitebalance = [1.0, 1.0, 1.0, 1.0]

        def close(self):
            pass

    def _fake_decode(raw_path, half_size=False, demosaic="AHD"):
        yy, xx = np.mgrid[0:64, 0:64]
        img = np.stack([xx / 127.0, yy / 127.0,
                        (xx + yy) / 254.0], axis=-1).astype(np.float32)
        img = np.clip(img * 0.6, 0.0, 1.0)
        return img, _MockRaw()

    monkeypatch.setattr(dec, "decode_raw", _fake_decode)
    return _fake_decode


def _assert_valid_jpeg(path: Path):
    assert path.exists(), f"输出文件不存在: {path}"
    data = path.read_bytes()
    assert len(data) > 100
    assert data[:2] == b"\xff\xd8", "JPEG SOI 魔数缺失"
    img = cv2.imread(str(path))
    assert img is not None and img.size > 0, "cv2.imread 无法解码 (非法 JPEG)"


# ---------------------------------------------------------------------------
# 1) build_parser(): pipeline 子命令 --preset / --config
# ---------------------------------------------------------------------------

def test_parser_pipeline_preset_flags():
    p = cli.build_parser()
    a = p.parse_args(["pipeline", "x.NEF", "--preset", "lr_baseline",
                      "--out", "out.jpg", "--half"])
    assert a.raw == "x.NEF"
    assert a.preset == "lr_baseline"
    assert a.out == "out.jpg"
    assert a.half is True
    assert a.scene is None


# ---------------------------------------------------------------------------
# 2) _load_prof_from_cfg: dcp 字段绑定 / 回退 / 错误
# ---------------------------------------------------------------------------

def test_load_prof_from_cfg_default_when_no_dcp(monkeypatch):
    monkeypatch.setattr(cli, "_load_prof", lambda: "DEFAULT_PROF")
    prof, dcp_path, err = cli._load_prof_from_cfg({"stages": []})
    assert prof == "DEFAULT_PROF"       # 旧 preset 回退默认 profile
    assert dcp_path is None
    assert err is None


def test_load_prof_from_cfg_binds_dcp(tmp_path):
    dcp = _camera_standard_dcp()
    if dcp is None:
        pytest.skip("无可用相机 DCP")
    cfg = {"dcp": dcp, "stages": []}
    prof, dcp_path, err = cli._load_prof_from_cfg(cfg)
    assert err is None
    assert prof is not None and prof.name
    assert Path(dcp_path) == Path(dcp).resolve()


def test_load_prof_from_cfg_relative_path_resolves():
    """相对 dcp 路径 (fit_camera_profile 产物风格, 仓库根相对) 从任意 cwd 可解析。"""
    if not PREVIEW_BASELINE_DCP.is_file():
        pytest.skip("缺仓库 Preview 基准 DCP")
    rel = os.path.relpath(PREVIEW_BASELINE_DCP, REPO_ROOT)  # 同盘相对路径
    prof, dcp_path, err = cli._load_prof_from_cfg({"dcp": rel, "stages": []})
    assert err is None
    assert Path(dcp_path) == PREVIEW_BASELINE_DCP.resolve()


def test_load_prof_from_cfg_missing_file_error(tmp_path):
    cfg = {"dcp": str(tmp_path / "nope.dcp"), "stages": []}
    prof, dcp_path, err = cli._load_prof_from_cfg(cfg)
    assert prof is None
    assert "不存在" in err and "nope.dcp" in err


def test_load_prof_from_cfg_invalid_dcp_error(tmp_path):
    bad = tmp_path / "not_a_dcp.txt"
    bad.write_text("hello, not a TIFF", encoding="utf-8")
    prof, dcp_path, err = cli._load_prof_from_cfg({"dcp": str(bad), "stages": []})
    assert prof is None
    assert "解析失败" in err or "不存在" in err


# ---------------------------------------------------------------------------
# 3) CLI e2e: 临时 preset (dcp=Camera Standard v2) 渲染合成小图
# ---------------------------------------------------------------------------

def test_preset_with_dcp_renders_synthetic_jpeg(tmp_path, capsys, synthetic_decode):
    dcp = _camera_standard_dcp()
    if dcp is None:
        pytest.skip("无可用相机 DCP")
    preset = _write_preset(tmp_path, dcp=dcp)
    out = tmp_path / "synthetic.jpg"

    data = _run_pipeline(["pipeline", "x.NEF", "--preset", str(preset),
                          "--out", str(out)], capsys)

    assert data["ok"] is True, data
    assert data["dcp"] == dcp              # 已绑定 preset 的 dcp
    assert data["profile"]
    assert "tone" in [s["name"] for s in data["stages"]]
    _assert_valid_jpeg(Path(data["output"]))
    _assert_valid_jpeg(out)


def test_preset_legacy_no_dcp_compat(tmp_path, capsys, synthetic_decode, monkeypatch):
    """旧 preset (无 dcp 字段) 兼容: 回退默认 profile 正常渲染。"""
    dcp = _camera_standard_dcp()
    if dcp is None:
        pytest.skip("无可用相机 DCP")
    preset = _write_preset(tmp_path, name="legacy.json", dcp=None)
    out = tmp_path / "legacy.jpg"
    # 默认 profile 用可用相机 DCP (避免依赖 Adobe 固定路径)
    monkeypatch.setattr(cli, "_load_prof", lambda: load_dcp(dcp))

    data = _run_pipeline(["pipeline", "x.NEF", "--preset", str(preset),
                          "--out", str(out)], capsys)

    assert data["ok"] is True, data
    assert data["dcp"] is None             # 未绑定
    _assert_valid_jpeg(Path(data["output"]))


def test_preset_lr_baseline_binds_and_renders(tmp_path, capsys, synthetic_decode):
    """产品预设 lr_baseline.json: --preset 按名加载 + dcp 绑定 + 渲染。"""
    preset_file = PRESETS_DIR / "lr_baseline.json"
    if not preset_file.exists():
        pytest.skip("缺 presets/lr_baseline.json")
    cfg = json.loads(preset_file.read_text(encoding="utf-8"))
    if not cfg.get("dcp") or not cli._resolve_dcp_path(cfg["dcp"]).is_file():
        pytest.skip("lr_baseline 的 dcp 指向文件不存在 (T9 产物未就绪)")
    out = tmp_path / "lr_baseline.jpg"

    data = _run_pipeline(["pipeline", "x.NEF", "--preset", "lr_baseline",
                          "--out", str(out)], capsys)

    assert data["ok"] is True, data
    assert data["dcp"] is not None
    assert Path(data["dcp"]).is_file()
    _assert_valid_jpeg(Path(data["output"]))


# ---------------------------------------------------------------------------
# 4) CLI 错误路径: dcp 缺失 / 非法
# ---------------------------------------------------------------------------

def test_preset_dcp_missing_file_clear_error(tmp_path, capsys):
    preset = _write_preset(tmp_path, dcp=str(tmp_path / "missing.dcp"))
    data = _run_pipeline(["pipeline", "x.NEF", "--preset", str(preset),
                          "--out", str(tmp_path / "x.jpg")], capsys)
    assert data["ok"] is False
    assert "dcp" in data["error"] and "missing.dcp" in data["error"]
    assert not (tmp_path / "x.jpg").exists()   # 未渲染


def test_preset_dcp_invalid_file_clear_error(tmp_path, capsys):
    bad = tmp_path / "bad.dcp"
    bad.write_text("this is not a TIFF/DCP file", encoding="utf-8")
    preset = _write_preset(tmp_path, dcp=str(bad))
    data = _run_pipeline(["pipeline", "x.NEF", "--preset", str(preset),
                          "--out", str(tmp_path / "x.jpg")], capsys)
    assert data["ok"] is False
    assert "bad.dcp" in data["error"]


def test_preset_name_not_found_clear_error(tmp_path, capsys):
    data = _run_pipeline(["pipeline", "x.NEF", "--preset", "no_such_preset",
                          "--out", str(tmp_path / "x.jpg")], capsys)
    assert data["ok"] is False
    assert "preset 不存在" in data["error"]


# ---------------------------------------------------------------------------
# 4b) manifest 一致性校验 (问题清单 C: 禁止 preset/dcp 交叉混用)
# ---------------------------------------------------------------------------

def _tmp_manifest(tmp_path: Path, preset: Path, dcp: str) -> Path:
    """写最小 manifest, 把临时 preset/dcp 登记为 product target。"""
    mf = tmp_path / "manifest.json"
    mf.write_text(json.dumps({
        "camera": "test",
        "targets": {"product": {"preset": str(preset), "dcp": str(dcp)}},
        "policy": {"no_profile_mixing": True},
    }, ensure_ascii=False), encoding="utf-8")
    return mf


def test_validate_preset_manifest_matching(tmp_path):
    preset = tmp_path / "p.json"
    preset.write_text("{}", encoding="utf-8")
    dcp = tmp_path / "p.dcp"
    dcp.write_bytes(b"x")
    monkeypatch_manifest = tmp_path / "manifest.json"
    monkeypatch_manifest.write_text(json.dumps({
        "targets": {"product": {"preset": str(preset), "dcp": str(dcp)}}},
        ensure_ascii=False), encoding="utf-8")
    old = cli.MANIFEST_FILE
    cli.MANIFEST_FILE = monkeypatch_manifest
    try:
        assert cli.validate_preset_manifest(preset, {"dcp": str(dcp)}) is None
    finally:
        cli.MANIFEST_FILE = old


def test_validate_preset_manifest_rejects_dcp_mismatch(tmp_path):
    preset = tmp_path / "p.json"
    preset.write_text("{}", encoding="utf-8")
    good_dcp, bad_dcp = tmp_path / "good.dcp", tmp_path / "bad.dcp"
    good_dcp.write_bytes(b"x")
    bad_dcp.write_bytes(b"x")
    old = cli.MANIFEST_FILE
    cli.MANIFEST_FILE = _tmp_manifest(tmp_path, preset, str(good_dcp))
    try:
        err = cli.validate_preset_manifest(preset, {"dcp": str(bad_dcp)})
    finally:
        cli.MANIFEST_FILE = old
    assert err is not None and "manifest 校验失败" in err and "product" in err


def test_validate_preset_manifest_rejects_custom_preset_with_product_dcp(tmp_path):
    product_preset = tmp_path / "product.json"
    product_preset.write_text("{}", encoding="utf-8")
    custom_preset = tmp_path / "custom.json"
    custom_preset.write_text("{}", encoding="utf-8")
    dcp = tmp_path / "p.dcp"
    dcp.write_bytes(b"x")
    old = cli.MANIFEST_FILE
    cli.MANIFEST_FILE = _tmp_manifest(tmp_path, product_preset, str(dcp))
    try:
        err = cli.validate_preset_manifest(custom_preset, {"dcp": str(dcp)})
    finally:
        cli.MANIFEST_FILE = old
    assert err is not None and str(product_preset) in err


def test_validate_preset_manifest_custom_pair_passes(tmp_path):
    preset = tmp_path / "custom.json"
    preset.write_text("{}", encoding="utf-8")
    dcp = tmp_path / "custom.dcp"
    dcp.write_bytes(b"x")
    assert cli.validate_preset_manifest(preset, {"dcp": str(dcp)}) is None


def test_pipeline_manifest_mismatch_blocks_render(tmp_path, capsys, synthetic_decode,
                                                  monkeypatch):
    """CLI 启动即校验: preset/dcp 与 manifest 不一致 → ok=False 且不渲染。"""
    dcp = _camera_standard_dcp()
    if dcp is None:
        pytest.skip("无可用相机 DCP")
    import shutil
    good = Path(dcp)
    bad = tmp_path / "bad.dcp"
    shutil.copyfile(good, bad)          # 合法 DCP, 但不是 manifest 中该 preset 的 dcp
    preset = _write_preset(tmp_path, dcp=str(bad))
    old_manifest = cli.MANIFEST_FILE
    monkeypatch.setattr(cli, "MANIFEST_FILE",
                        _tmp_manifest(tmp_path, preset, str(good)))
    out = tmp_path / "blocked.jpg"

    data = _run_pipeline(["pipeline", "x.NEF", "--preset", str(preset),
                          "--out", str(out)], capsys)

    assert data["ok"] is False
    assert "manifest 校验失败" in data["error"]
    assert not out.exists()


# ---------------------------------------------------------------------------
# 5) CLI e2e: 真实 NEF (0711 半尺寸), 无数据时 skip
# ---------------------------------------------------------------------------

@pytest.mark.e2e
def test_preset_with_dcp_renders_real_nef_half(tmp_path, capsys):
    files = _resolve_nef()
    if not files:
        pytest.skip("无 NEF 测试数据 (RAWLAB_RAW_DIRS)")
    dcp = _camera_standard_dcp()
    if dcp is None:
        pytest.skip("无可用相机 DCP")
    preset = _write_preset(tmp_path, name="nef_preset.json", dcp=dcp)
    out = tmp_path / "nef_half.jpg"

    data = _run_pipeline(["pipeline", files[0], "--preset", str(preset),
                          "--out", str(out), "--half"], capsys)

    assert data["ok"] is True, data
    assert data["dcp"] == dcp
    _assert_valid_jpeg(Path(data["output"]))
