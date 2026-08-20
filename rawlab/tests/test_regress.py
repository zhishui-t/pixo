"""test_regress —— regress_anchors 锚点回归脚本 (T7) 单元测试。

覆盖 (全部合成数据, **不含真实 DCP/RAW 依赖**):
  - rule_for_stem / evaluate_photo: 规则匹配与阈值判定 (0376 全帧 ≤3/≤3,
    5236 高光区 ≤4/≤5; 无规则仅报告; 口径掩码空 → 失败)
  - align_target / load_target_jpeg: 对齐与目标读取 (tmp JPEG)
  - resolve_anchors: 路径直通 / 关键字定位 / 找不到报错
  - run_regression 端到端: 注入 render_fn/load_target_fn (渲染自身作为目标
    → 全零差), 验证输出 JSON 结构与退出码逻辑 (pass → 0, 违反 → 1)
  - main: CLI 接线, 退出码正确

运行: python -m pytest rawlab/tests/test_regress.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from rawlab.tools.regress_anchors import (  # noqa: E402
    ANCHOR_THRESHOLDS,
    DEFAULT_ANCHORS,
    align_target,
    build_parser,
    evaluate_photo,
    load_target_jpeg,
    main,
    resolve_anchors,
    rule_for_stem,
    run_regression,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _img(seed: int = 0, size: int = 96) -> np.ndarray:
    """确定性合成 RGB uint8 图 (含中性/彩色/明暗像素)。"""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, (size, size, 3), dtype=np.uint8)


def _img_highlight(size: int = 64) -> tuple[np.ndarray, np.ndarray]:
    """合成高光图对: (ours, target), 差异只发生在高光区 (L>160)。

    ours: 暗底 + 亮块; target: 仅亮块 a/b 大幅偏移 (暗区完全一致)。
    高光掩码 (目标 L>160) 覆盖亮块 → 高光口径检出大 Δ, 全帧中位不受影响。
    """
    ours = np.full((size, size, 3), 40, np.uint8)
    ours[8:40, 8:40] = (235, 235, 235)
    target = ours.copy()
    target[8:40, 8:40] = (250, 160, 120)          # 亮块品红偏移
    return ours, target


def _stats_of(report: dict, idx: int = 0) -> dict:
    return report["reports"][idx]


# ---------------------------------------------------------------------------
# 规则匹配与判定
# ---------------------------------------------------------------------------

def test_rule_for_stem():
    r = rule_for_stem("DSC_0376.NEF")
    assert r is not None and r["key"] == "0376" and r["caliber"] == "full"
    assert r["da"] == 3.0 and r["db"] == 3.0
    r = rule_for_stem("DSC_5236.NEF")
    assert r is not None and r["key"] == "5236" and r["caliber"] == "highlight"
    assert r["da"] == 4.0 and r["db"] == 5.0
    assert rule_for_stem("DSC_9999.NEF") is None
    assert rule_for_stem("0376") is not None                 # 关键字即 stem
    assert rule_for_stem("dsc_5236.nef")["key"] == "5236"    # 不区分大小写


def test_rule_for_stem_custom_thresholds():
    custom = {"A1": {"caliber": "full", "da": 1.0, "db": 2.0}}
    r = rule_for_stem("XX_A1_YY.NEF", custom)
    assert r["da"] == 1.0 and r["db"] == 2.0
    assert rule_for_stem("XX_0376_YY.NEF", custom) is None   # 覆盖后默认规则不再匹配


def test_evaluate_photo():
    stats = {"full": {"da": 2.9, "db": 2.9},
             "highlight": {"da": 3.9, "db": 4.9}}
    assert evaluate_photo(stats, rule_for_stem("DSC_0376.NEF")) == (True, "ok")
    assert evaluate_photo(stats, rule_for_stem("DSC_5236.NEF")) == (True, "ok")
    assert evaluate_photo({}, None) == (True, "no_rule")

    # 违反: 全帧超 3
    bad_full = {"full": {"da": 3.5, "db": 1.0}, "highlight": None}
    assert evaluate_photo(bad_full, rule_for_stem("DSC_0376.NEF"))[0] is False
    # 违反: 高光超 5
    bad_hi = {"full": {"da": 0.1, "db": 0.1}, "highlight": {"da": 1.0, "db": 5.4}}
    assert evaluate_photo(bad_hi, rule_for_stem("DSC_5236.NEF"))[0] is False
    # 口径数据缺失 (高光掩码空) → 失败
    empty = {"full": {"da": 0.0, "db": 0.0}, "highlight": None}
    assert evaluate_photo(empty, rule_for_stem("DSC_5236.NEF")) == \
        (False, "empty_caliber")


# ---------------------------------------------------------------------------
# 对齐与目标读取
# ---------------------------------------------------------------------------

def test_align_target():
    a = _img(1, size=48)
    b = _img(2, size=96)
    aligned = align_target(b, a.shape[:2])
    assert aligned.shape[:2] == a.shape[:2]
    assert align_target(a, a.shape[:2]) is a                 # 同尺寸直通
    assert aligned.dtype == np.uint8


def test_load_target_jpeg(tmp_path):
    stem = "DSC_0376"
    # 平滑渐变图 (JPEG 往返近无损; 随机噪声图是 JPEG 最坏情况, 不用于往返校验)
    yy, xx = np.mgrid[0:96, 0:96]
    img = np.stack([np.clip(xx * 2.0, 0, 255),
                    np.clip(yy * 2.0, 0, 255),
                    np.clip((xx + yy) * 1.0, 0, 255)], -1).astype(np.uint8)
    cv2.imwrite(str(tmp_path / f"{stem}.jpg"),
                cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    loaded = load_target_jpeg(tmp_path, stem)
    assert loaded is not None and loaded.shape == img.shape
    assert loaded.dtype == np.uint8
    # JPEG 有损: 平滑图容差收紧
    diff = np.abs(loaded.astype(np.int16) - img.astype(np.int16))
    assert float(diff.max()) <= 8.0
    assert load_target_jpeg(tmp_path, "DSC_5236") is None    # 缺失
    assert load_target_jpeg(tmp_path / "nope", stem) is None


# ---------------------------------------------------------------------------
# 锚点解析
# ---------------------------------------------------------------------------

def test_resolve_anchors(tmp_path):
    p = tmp_path / "DSC_0376.NEF"
    p.write_bytes(b"x")
    assert resolve_anchors([str(p)], None) == [str(p)]       # 路径直通
    with pytest.raises(SystemExit):
        resolve_anchors(["0376"], None)                      # 无 --raw-dirs → 报错
    with pytest.raises(SystemExit):
        resolve_anchors(["9999"], [str(tmp_path)])           # 找不到 → 报错
    raw = tmp_path / "sub"
    raw.mkdir()
    (raw / "DSC_5236.NEF").write_bytes(b"x")
    got = resolve_anchors(["5236"], [str(tmp_path)])
    assert len(got) == 1 and got[0].endswith("DSC_5236.NEF")


def test_resolve_anchors_skips_dotfiles(tmp_path):
    """AppleDouble (._*) 等隐藏副本不得被关键字命中 (实拍库存在此类文件)。"""
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "._DSC_0376.NEF").write_bytes(b"x")               # 隐藏副本 (排序在前)
    (raw / "DSC_0376.NEF").write_bytes(b"x")
    got = resolve_anchors(["0376"], [str(tmp_path)])
    assert len(got) == 1 and got[0].endswith("DSC_0376.NEF")
    assert "._" not in got[0]


# ---------------------------------------------------------------------------
# run_regression 端到端 (渲染自身作为目标 → 全零差)
# ---------------------------------------------------------------------------

def test_run_regression_identity_all_zero(tmp_path):
    """注入 render/load: 渲染自身作为目标 → 四口径全零差 → 全 PASS, 报告结构完整。"""
    img = _img(4)
    anchors = [str(tmp_path / "DSC_0376.NEF"), str(tmp_path / "DSC_5236.NEF")]
    report = run_regression(
        anchors, tmp_path, tmp_path, name="t_identity",
        render_fn=lambda raw, prof, pipe: img,
        load_target_fn=lambda targets, stem: img)
    assert report["name"] == "t_identity"
    assert report["summary"]["pass"] is True
    assert report["summary"]["n"] == 2 and report["summary"]["n_pass"] == 2
    for entry in report["reports"]:
        assert entry["pass"] is True and entry["error"] is None
        assert entry["full"]["da"] == 0.0 and entry["full"]["db"] == 0.0
        assert entry["full"]["dS"] == 0.0 and entry["full"]["dp50"] == 0.0
        assert entry["highlight"]["da"] == 0.0 and entry["highlight"]["db"] == 0.0
        assert len(entry["bands"]) == 4
        assert entry["neutral"] is not None
        assert entry["rule"]["key"] in ("0376", "5236")
    # JSON 落盘且结构完整
    out = tmp_path / "regression_t_identity.json"
    assert out.exists()
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert set(saved) >= {"name", "dcp", "preset", "targets", "out",
                          "thresholds", "summary", "reports"}
    assert saved["thresholds"]["0376"] == {"caliber": "full", "da": 3.0, "db": 3.0}
    assert saved["thresholds"]["5236"] == {"caliber": "highlight",
                                           "da": 4.0, "db": 5.0}
    assert saved["summary"]["pass"] is True


def test_run_regression_full_frame_violation_exit1(tmp_path):
    """0376 全帧 |Δa|/|Δb| 超 3 → 该锚点 FAIL → 退出码 1。"""
    ours = _img(5)
    target = np.clip(ours.astype(np.int16) + [40, -30, -30], 0, 255).astype(np.uint8)
    anchors = [str(tmp_path / "DSC_0376.NEF")]
    report = run_regression(
        anchors, tmp_path, tmp_path, name="t_full_fail",
        render_fn=lambda raw, prof, pipe: ours,
        load_target_fn=lambda targets, stem: target)
    assert report["summary"]["pass"] is False
    entry = _stats_of(report)
    assert entry["pass"] is False and entry["reason"] == "threshold"
    assert entry["full"]["da"] > 3.0 or entry["full"]["db"] > 3.0
    assert (0 if report["summary"]["pass"] else 1) == 1        # 退出码语义


def test_run_regression_highlight_rule_5236(tmp_path):
    """5236 只判高光区: 高光 Δ 大但全帧中位不变 → FAIL (高光规则)。"""
    ours, target = _img_highlight()
    anchors = [str(tmp_path / "DSC_5236.NEF")]
    report = run_regression(
        anchors, tmp_path, tmp_path, name="t_hi_fail",
        render_fn=lambda raw, prof, pipe: ours,
        load_target_fn=lambda targets, stem: target)
    entry = _stats_of(report)
    assert entry["rule"]["caliber"] == "highlight"
    assert entry["highlight"]["da"] > 4.0 or entry["highlight"]["db"] > 5.0
    assert entry["pass"] is False
    assert report["summary"]["pass"] is False
    # 同一对图用 0376 (全帧规则): 全帧中位几乎不变 → 通过
    anchors2 = [str(tmp_path / "DSC_0376.NEF")]
    report2 = run_regression(
        anchors2, tmp_path, tmp_path, name="t_hi_0376",
        render_fn=lambda raw, prof, pipe: ours,
        load_target_fn=lambda targets, stem: target)
    assert report2["summary"]["pass"] is True


def test_run_regression_highlight_identity_pass(tmp_path):
    ours, _ = _img_highlight()
    anchors = [str(tmp_path / "DSC_5236.NEF")]
    report = run_regression(
        anchors, tmp_path, tmp_path, name="t_hi_ok",
        render_fn=lambda raw, prof, pipe: ours,
        load_target_fn=lambda targets, stem: ours)
    assert report["summary"]["pass"] is True
    assert _stats_of(report)["highlight"]["da"] == 0.0


def test_run_regression_missing_target_exit1(tmp_path):
    """目标 JPEG 缺失 → 该锚点 FAIL (error), 退出码 1。"""
    img = _img(6)
    anchors = [str(tmp_path / "DSC_0376.NEF")]
    report = run_regression(
        anchors, tmp_path, tmp_path, name="t_no_target",
        render_fn=lambda raw, prof, pipe: img,
        load_target_fn=lambda targets, stem: None)
    assert report["summary"]["pass"] is False
    entry = _stats_of(report)
    assert entry["pass"] is False and entry["error"] is not None
    assert entry["reason"] == "no_target"


def test_run_regression_no_render_fn_requires_runtime():
    with pytest.raises(ValueError):
        run_regression(["a.NEF"], "t", "o", "x")            # 未注入 render 且无 dcp/preset


def test_run_regression_custom_thresholds(tmp_path):
    """自定义阈值表可覆盖默认规则。"""
    ours = _img(7)
    target = np.clip(ours.astype(np.int16) + [40, -30, -30], 0, 255).astype(np.uint8)
    anchors = [str(tmp_path / "DSC_0376.NEF")]
    lenient = {"0376": {"caliber": "full", "da": 100.0, "db": 100.0}}
    report = run_regression(
        anchors, tmp_path, tmp_path, name="t_custom",
        render_fn=lambda raw, prof, pipe: ours,
        load_target_fn=lambda targets, stem: target,
        thresholds=lenient)
    assert report["summary"]["pass"] is True
    assert _stats_of(report)["rule"]["da"] == 100.0


# ---------------------------------------------------------------------------
# CLI (main) 接线与退出码
# ---------------------------------------------------------------------------

def _fake_report(pass_: bool) -> dict:
    return {"name": "x", "dcp": None, "preset": None, "targets": "t",
            "out": "o", "thresholds": {}, "reports": [],
            "summary": {"n": 0, "n_pass": 0, "pass": pass_, "thresholds": {}}}


def test_main_exit_codes(tmp_path, monkeypatch):
    preset = tmp_path / "p.json"
    preset.write_text(json.dumps({"params": {}, "stages": []}),
                      encoding="utf-8")
    raw = tmp_path / "DSC_0376.NEF"
    raw.write_bytes(b"x")
    import rawlab.tools.regress_anchors as ra
    monkeypatch.setattr(ra, "run_regression",
                        lambda *a, **k: _fake_report(True))
    assert main(["--preset", str(preset), "--targets", str(tmp_path),
                 "--anchors", str(raw), "--out-dir", str(tmp_path),
                 "--name", "cli_ok"]) == 0
    monkeypatch.setattr(ra, "run_regression",
                        lambda *a, **k: _fake_report(False))
    assert main(["--preset", str(preset), "--targets", str(tmp_path),
                 "--anchors", str(raw), "--out-dir", str(tmp_path),
                 "--name", "cli_fail"]) == 1


def test_main_missing_preset(tmp_path):
    assert main(["--preset", str(tmp_path / "nope.json"),
                 "--anchors", "x"]) == 1


def test_build_parser_defaults():
    args = build_parser().parse_args(["--preset", "p.json"])
    assert args.anchors == DEFAULT_ANCHORS == ["0376", "5236"]
    assert args.targets is None                      # 缺省走 lr_corpus
    assert args.dcp is None


def test_anchors_thresholds_constant_shape():
    assert set(ANCHOR_THRESHOLDS) == {"0376", "5236"}
    assert ANCHOR_THRESHOLDS["0376"] == {"caliber": "full", "da": 3.0, "db": 3.0}
    assert ANCHOR_THRESHOLDS["5236"] == {"caliber": "highlight",
                                         "da": 4.0, "db": 5.0}
