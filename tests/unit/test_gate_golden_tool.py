"""render/tools/gate_golden.py 多样本基线工具的单测 (t108)。

不依赖真实 RAW/DCP: monkeypatch Renderer 与 _render, 只验证 manifest
结构 / 增量合并 / flat 混用守卫 / compare 往返等工具层逻辑。真实语料的
基线生成与漂移校验是工具级 (render-gate-raw-v1), 不进 CI 硬门。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "pixo"
                       / "render" / "tools"))
import gate_golden as gg  # noqa: E402


class _DummyRenderer:
    def __init__(self, dcp_path):
        self.dcp_path = dcp_path


@pytest.fixture
def fake_render(monkeypatch):
    """确定性假渲染: 输出由 (params, bps) 决定, 与真实管线解耦。"""
    monkeypatch.setattr(gg, "Renderer", _DummyRenderer)

    def _render(renderer, raw_path, long_edge, params, output_bps):
        key = json.dumps(params, sort_keys=True, default=str)
        fill = (sum(ord(c) for c in key) * (7 if output_bps == 8 else 13)) % 200
        return np.full((4, 6, 3), fill,
                       dtype=np.uint8 if output_bps == 8 else np.uint16)

    monkeypatch.setattr(gg, "_render", _render)


def _write_samples(tmp_path: Path, n: int = 2) -> Path:
    samples = {}
    for i in range(n):
        raw = tmp_path / f"DSC_{1000 + i}.NEF"
        raw.write_bytes(b"fake")
        samples[f"s{i}"] = {
            "raw": str(raw), "ref": f"<corpus>/a/raw/DSC_{1000 + i}.NEF",
            "note": f"样本{i}", "exif": {"iso": 100 + i},
        }
    p = tmp_path / "samples.json"
    p.write_text(json.dumps({"samples": samples}, ensure_ascii=False),
                 encoding="utf-8")
    return p


def _run(capsys, *argv):
    args = gg.build_parser().parse_args(list(argv))
    rc = args.func(args)
    out = capsys.readouterr().out
    return rc, out


def test_multi_sample_generate_and_compare_roundtrip(
        tmp_path, fake_render, capsys):
    dcp = tmp_path / "fake.dcp"
    dcp.write_bytes(b"dcp")
    out = tmp_path / "gate_test"
    samples = _write_samples(tmp_path)
    rc, _ = _run(capsys, "generate", "--samples", str(samples),
                 "--dcp", str(dcp), "--out", str(out), "--long-edge", "512",
                 "--features", "clarity_default",
                 "--reviewer", "unit-test")
    assert rc == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == gg.SCHEMA
    assert manifest["reviewer"] == "unit-test"
    # 真实本机路径不入库 (anonymize 约定), manifest 只记 ref
    assert manifest["samples"]["s0"]["ref"].startswith("<corpus>/")
    feat = manifest["features"]["clarity_default"]
    assert feat["params"] == gg.FEATURES["clarity_default"]
    assert set(feat["samples"]) == {"s0", "s1"}
    entry = feat["samples"]["s0"]
    assert entry["raw"] == "<corpus>/a/raw/DSC_1000.NEF"
    assert entry["shape_u8"] == [4, 6, 3]
    u8 = np.load(out / "clarity_default" / "s0" / "output_u8.npy")
    assert gg._sha256(u8) == entry["sha256_u8"]
    # 基线文件路径按 goldens 根相对记录
    assert (out.parent / entry["files"]["u8"]).exists()

    # compare 往返: 全 PASS
    rc, out_txt = _run(capsys, "compare", "--samples", str(samples),
                       "--out", str(out), "--long-edge", "512")
    assert rc == 0, out_txt
    assert "RESULT: PASS" in out_txt
    assert "clarity_default/s0" in out_txt and "clarity_default/s1" in out_txt


def test_multi_sample_incremental_append_preserves_other_features(
        tmp_path, fake_render, capsys):
    dcp = tmp_path / "fake.dcp"
    dcp.write_bytes(b"dcp")
    out = tmp_path / "gate_test"
    samples = _write_samples(tmp_path)
    _run(capsys, "generate", "--samples", str(samples), "--dcp", str(dcp),
         "--out", str(out), "--features", "wb_as_shot_default",
         "--reviewer", "r1")
    rc, _ = _run(capsys, "generate", "--samples", str(samples),
                 "--dcp", str(dcp), "--out", str(out),
                 "--features", "compose_param", "--reviewer", "r2")
    assert rc == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["features"]) == {"wb_as_shot_default", "compose_param"}
    wb_sha = manifest["features"]["wb_as_shot_default"]["samples"]["s0"]["sha256_u8"]
    # 增量生成不得动其它 feature 的既有数值
    assert manifest["features"]["wb_as_shot_default"]["samples"]["s0"]["sha256_u8"] == wb_sha


def test_multi_sample_rejects_flat_manifest_and_bad_samples(
        tmp_path, fake_render, capsys):
    dcp = tmp_path / "fake.dcp"
    dcp.write_bytes(b"dcp")
    samples = _write_samples(tmp_path)

    flat_dir = tmp_path / "flat_gate"
    (flat_dir / "exposure").mkdir(parents=True)
    (flat_dir / "manifest.json").write_text(json.dumps({
        "schema": gg.SCHEMA, "long_edge": 512, "raw": "x.NEF", "dcp": str(dcp),
        "features": {"exposure": {"params": {}, "files": {},
                                  "sha256_u8": "x", "sha256_u16": "x"}}}),
        encoding="utf-8")
    rc, _ = _run(capsys, "generate", "--samples", str(samples),
                 "--dcp", str(dcp), "--out", str(flat_dir))
    assert rc == 2  # flat manifest 与多样本结构不兼容

    # 非法 sample_id (含路径分隔符) 与不存在的 raw 均拒绝
    bad = tmp_path / "bad_samples.json"
    bad.write_text(json.dumps({"samples": {"a/b": {"raw": str(dcp)}}}),
                   encoding="utf-8")
    rc, _ = _run(capsys, "generate", "--samples", str(bad), "--dcp", str(dcp),
                 "--out", str(tmp_path / "g2"))
    assert rc == 2
    bad2 = tmp_path / "bad2_samples.json"
    bad2.write_text(json.dumps({"samples": {"ok": {"raw": str(tmp_path / "nope.NEF")}}}),
                    encoding="utf-8")
    rc, _ = _run(capsys, "generate", "--samples", str(bad2), "--dcp", str(dcp),
                 "--out", str(tmp_path / "g3"))
    assert rc == 2

    rc, _ = _run(capsys, "generate", "--samples", str(samples),
                 "--dcp", str(dcp), "--out", str(tmp_path / "g4"),
                 "--features", "no_such_feature")
    assert rc == 2


def test_legacy_single_raw_mode_still_works(tmp_path, fake_render, capsys):
    """t35 单 RAW flat 口径回归: --raw 生成/compare 不因多样本扩展破坏。"""
    dcp = tmp_path / "fake.dcp"
    dcp.write_bytes(b"dcp")
    raw = tmp_path / "one.NEF"
    raw.write_bytes(b"fake")
    out = tmp_path / "gate_flat"
    rc, _ = _run(capsys, "generate", "--raw", str(raw), "--dcp", str(dcp),
                 "--out", str(out), "--long-edge", "512")
    assert rc == 0
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert "samples" not in manifest
    assert manifest["raw"] == str(raw)
    assert set(manifest["features"]) == set(gg.FEATURES)
    rc, out_txt = _run(capsys, "compare", "--raw", str(raw), "--dcp", str(dcp),
                       "--out", str(out), "--long-edge", "512")
    assert rc == 0, out_txt
    assert "RESULT: PASS" in out_txt

    # 缺 --raw 的单 RAW compare 应报错而非 KeyError
    rc, _ = _run(capsys, "compare", "--dcp", str(dcp), "--out", str(out))
    assert rc == 2
