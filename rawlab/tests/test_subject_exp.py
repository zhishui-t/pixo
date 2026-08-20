"""T1 单元测试: 主体感知曝光接线 (rawlab/engine/analyze.py + exposure face 优先)。

覆盖 (验收: 主体框加权生效; face 优先; 无检测回退全图中位; CLI --no-detect):
  - run_analysis: detect=True 写 ctx.state['subject_boxes']/['face_boxes']
  - run_analysis: 检测异常静默回退 (空框, 不抛)
  - run_analysis: detect=False 不调检测; rgb8 缺省且无法渲染 probe → 空框
  - exposure: 主体区中位加权 (subject_mode='box')
  - exposure: face_boxes 优先于 subject_boxes
  - exposure: 框面积 <1% 忽略 (回退全图 / 取大框)
  - exposure: 无框回退全图中位
  - CLI: fix/batch 默认开启检测, --no-detect 关闭 (解析 + _detect_boxes 接线)

运行: python -m pytest rawlab/tests/test_subject_exp.py -q
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rawlab.dcp import DcpProfile
from rawlab.engine.core import StageContext, DOMAIN_LINEAR_CAM
from rawlab.engine.curves import curve_anchor_target
from rawlab.engine.stages.exposure import ExposureStage, _probe_linear_srgb
import rawlab.engine.stages.exposure as _exposure_mod


@pytest.fixture(autouse=True)
def _no_cal_file(monkeypatch):
    """单测不依赖每机标定文件 (同 test_exposure.py): 屏蔽之, 走锚点路径。

    标定文件 (engine/target_offset.json) 是环境数据, 存在会改走查表路径,
    使锚点类断言失效。
    """
    monkeypatch.setattr(_exposure_mod, "_CAL_FILE",
                        _exposure_mod._CAL_FILE.parent / "__nonexistent_cal__.json")
    monkeypatch.setattr(_exposure_mod, "_cached_table", None)
    monkeypatch.setattr(_exposure_mod, "_cached_offset", None)


# 真实 Nikon Z 5 II Camera Standard 矩阵 (确定性用例, 与 test_exposure.py 一致)
_NIKON_CM1 = [1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449, -0.0231, 0.0811, 0.7571]
_NIKON_CM2 = [0.9874, -0.3784, -0.0823, -0.4728, 1.2673, 0.2286, -0.0648, 0.1513, 0.6375]
_NIKON_FM1 = [0.7978, 0.1352, 0.0313, 0.288, 0.7119, 0.0001, 0.0, 0.0, 0.8251]


class _FakeRaw:
    def __init__(self, wb=(2.0, 1.0, 1.5)):
        self.camera_whitebalance = [wb[0], wb[1], wb[2], 1.0]


def _make_profile(baseline: float = 0.0) -> DcpProfile:
    return DcpProfile(
        path=Path("test.dcp"),
        color_matrix1=_NIKON_CM1,
        color_matrix2=_NIKON_CM2,
        forward_matrix1=_NIKON_FM1,
        forward_matrix2=_NIKON_FM1,
        baseline_exposure_offset=baseline,
    )


def _make_ctx(image, prof=None, wb_mode="off", subject_boxes=None,
              face_boxes=None) -> StageContext:
    """构造 StageContext (对齐 test_exposure._make_ctx; target_offset 钉 0.0)。"""
    prof = prof if prof is not None else _make_profile()
    ctx = StageContext(
        "test.nef",
        raw=_FakeRaw(),
        prof=prof,
        config={"stages": {"whitebalance": {"mode": wb_mode},
                           "exposure": {"target_offset": 0.0}}},
    )
    ctx.set_image(image.astype(np.float32), DOMAIN_LINEAR_CAM)
    if subject_boxes is not None:
        ctx.state["subject_boxes"] = subject_boxes
    if face_boxes is not None:
        ctx.state["face_boxes"] = face_boxes
    return ctx


def _neutral_image(h, w, value):
    return np.full((h, w, 3), value, dtype=np.float32)


def _expected_ev(prof, probe, region):
    """锚点路径预期 EV = anchor - log2(区域中位)。

    ⚠️ 仅当高光保护不触发时成立: 测试用亮度取 0.3/0.6 (中灰附近),
    提亮方向为负 EV (压暗), 不会撞 p98 高光上限 (cap=+0.64)。
    """
    med = float(np.median(np.log2(np.maximum(region, 1e-6))))
    return curve_anchor_target(prof) - med


# ---------------------------------------------------------------------------
# run_analysis 接线 (engine/analyze.py)
# ---------------------------------------------------------------------------

def test_run_analysis_writes_state(monkeypatch):
    from rawlab import vision_bridge
    from rawlab.engine.analyze import run_analysis

    def fake_detect(bgr8):
        assert bgr8.dtype == np.uint8 and bgr8.shape[2] == 3
        return ([[0.0, 0.0, 0.5, 1.0], [0.6, 0.0, 1.0, 0.4]],
                [[0.25, 0.0, 0.75, 0.5]])
    monkeypatch.setattr(vision_bridge, "detect_subjects", fake_detect)

    ctx = StageContext("test.nef", raw=_FakeRaw(), prof=_make_profile())
    rgb8 = np.zeros((32, 32, 3), dtype=np.uint8)
    subj, faces = run_analysis(ctx, rgb8=rgb8, detect=True, classify=False)
    assert ctx.state["subject_boxes"] == [[0.0, 0.0, 0.5, 1.0], [0.6, 0.0, 1.0, 0.4]]
    assert ctx.state["face_boxes"] == [[0.25, 0.0, 0.75, 0.5]]
    assert subj == ctx.state["subject_boxes"]
    assert faces == ctx.state["face_boxes"]


def test_run_analysis_detect_exception_falls_back(monkeypatch):
    from rawlab import vision_bridge
    from rawlab.engine.analyze import run_analysis

    def boom(bgr8):
        raise RuntimeError("no guanlan / no CUDA")
    monkeypatch.setattr(vision_bridge, "detect_subjects", boom)

    ctx = StageContext("test.nef", raw=_FakeRaw(), prof=_make_profile())
    subj, faces = run_analysis(ctx, rgb8=np.zeros((16, 16, 3), np.uint8), detect=True)
    assert subj == [] and faces == []
    assert ctx.state["subject_boxes"] == [] and ctx.state["face_boxes"] == []


def test_run_analysis_detect_false_skips(monkeypatch):
    from rawlab import vision_bridge
    from rawlab.engine.analyze import run_analysis

    calls = []

    def fake_detect(bgr8):
        calls.append(bgr8)
        return ([[0.0, 0.0, 1.0, 1.0]], [])
    monkeypatch.setattr(vision_bridge, "detect_subjects", fake_detect)

    ctx = StageContext("test.nef", raw=_FakeRaw(), prof=_make_profile())
    run_analysis(ctx, rgb8=np.zeros((16, 16, 3), np.uint8), detect=False)
    assert calls == [], "detect=False 不应调用 detect_subjects"


def test_run_analysis_no_probe_falls_back(monkeypatch):
    """rgb8=None 且无法渲染 probe (文件不存在) → 空框回退, 不抛。"""
    from rawlab import vision_bridge
    from rawlab.engine.analyze import run_analysis

    calls = []

    def fake_detect(bgr8):
        calls.append(bgr8)
        return ([], [])
    monkeypatch.setattr(vision_bridge, "detect_subjects", fake_detect)

    ctx = StageContext("__missing__.nef", raw=_FakeRaw(), prof=_make_profile())
    subj, faces = run_analysis(ctx, rgb8=None, detect=True)
    assert subj == [] and faces == []
    assert calls == [], "probe 不可得时不应调 detect_subjects"


# ---------------------------------------------------------------------------
# exposure: 主体区中位加权
# ---------------------------------------------------------------------------

def test_exposure_uses_subject_box_median():
    h = w = 128
    img = _neutral_image(h, w, 0.3)
    img[:, w // 2:, :] = 0.6  # 右半亮
    prof = _make_profile()
    ctx = _make_ctx(img, prof=prof, wb_mode="off",
                    subject_boxes=[(0.5, 0.0, 1.0, 1.0)])  # 右半
    stage = ExposureStage({"subject_mode": "box"})
    probe = _probe_linear_srgb(ctx, img)
    region = probe[:, probe.shape[1] // 2:]
    ev = stage._auto_ev(ctx)
    assert abs(ev - _expected_ev(prof, probe, region)) < 1e-3


def test_exposure_no_boxes_falls_back_full_frame():
    """无任何框 → 回退全图中位 (验收: 无检测回退全图中位)。"""
    h = w = 128
    img = _neutral_image(h, w, 0.3)
    img[:, w // 2:, :] = 0.6
    prof = _make_profile()
    ctx = _make_ctx(img, prof=prof, wb_mode="off")  # 无框
    stage = ExposureStage({"subject_mode": "box"})
    probe = _probe_linear_srgb(ctx, img)
    ev = stage._auto_ev(ctx)
    assert abs(ev - _expected_ev(prof, probe, probe)) < 1e-3


def test_exposure_subject_mode_full_ignores_boxes():
    """subject_mode='full' 时即使有框也走全图中位。"""
    h = w = 128
    img = _neutral_image(h, w, 0.3)
    img[:, w // 2:, :] = 0.6
    prof = _make_profile()
    ctx = _make_ctx(img, prof=prof, wb_mode="off",
                    subject_boxes=[(0.5, 0.0, 1.0, 1.0)])
    stage = ExposureStage({"subject_mode": "full"})
    probe = _probe_linear_srgb(ctx, img)
    ev = stage._auto_ev(ctx)
    assert abs(ev - _expected_ev(prof, probe, probe)) < 1e-3


# ---------------------------------------------------------------------------
# exposure: face 优先
# ---------------------------------------------------------------------------

def test_exposure_face_boxes_priority():
    h = w = 128
    img = _neutral_image(h, w, 0.3)
    img[:, w // 2:, :] = 0.6  # 右半亮
    prof = _make_profile()
    # subject 框 = 右半亮区; face 框 = 左半暗区 → 应取 face (暗区)
    ctx = _make_ctx(img, prof=prof, wb_mode="off",
                    subject_boxes=[(0.5, 0.0, 1.0, 1.0)],
                    face_boxes=[(0.0, 0.0, 0.5, 1.0)])
    stage = ExposureStage({"subject_mode": "box"})
    probe = _probe_linear_srgb(ctx, img)
    face_region = probe[:, :probe.shape[1] // 2]
    ev = stage._auto_ev(ctx)
    assert abs(ev - _expected_ev(prof, probe, face_region)) < 1e-3
    # 与仅 subject 框 (亮区) 的结果不同 → 证明 face 优先而非 subject
    subj_region = probe[:, probe.shape[1] // 2:]
    ev_subj = _expected_ev(prof, probe, subj_region)
    assert abs(ev - ev_subj) > 1e-3


def test_exposure_face_empty_falls_back_to_subject():
    """face_boxes 存在但为空列表 → 回退 subject_boxes。"""
    h = w = 128
    img = _neutral_image(h, w, 0.3)
    img[:, w // 2:, :] = 0.6
    prof = _make_profile()
    ctx = _make_ctx(img, prof=prof, wb_mode="off",
                    subject_boxes=[(0.5, 0.0, 1.0, 1.0)], face_boxes=[])
    stage = ExposureStage({"subject_mode": "box"})
    probe = _probe_linear_srgb(ctx, img)
    subj_region = probe[:, probe.shape[1] // 2:]
    ev = stage._auto_ev(ctx)
    assert abs(ev - _expected_ev(prof, probe, subj_region)) < 1e-3


# ---------------------------------------------------------------------------
# exposure: 框面积 <1% 忽略
# ---------------------------------------------------------------------------

def test_exposure_ignores_tiny_boxes():
    h = w = 128
    img = _neutral_image(h, w, 0.3)
    img[:, w // 2:, :] = 0.6
    prof = _make_profile()
    stage = ExposureStage({"subject_mode": "box"})

    # 唯一框面积 0.02*0.02=0.0004 < 1% → 忽略 → 回退全图中位
    ctx_tiny = _make_ctx(img, prof=prof, wb_mode="off",
                         subject_boxes=[(0.49, 0.49, 0.51, 0.51)])
    probe = _probe_linear_srgb(ctx_tiny, img)
    ev_tiny = stage._auto_ev(ctx_tiny)
    assert abs(ev_tiny - _expected_ev(prof, probe, probe)) < 1e-3

    # 小框 + 大框并存 → 小框被忽略, 取大框 (左半)
    ctx_mix = _make_ctx(img, prof=prof, wb_mode="off",
                        subject_boxes=[(0.49, 0.49, 0.51, 0.51),
                                       (0.0, 0.0, 0.5, 1.0)])
    ev_mix = stage._auto_ev(ctx_mix)
    left_region = probe[:, :probe.shape[1] // 2]
    assert abs(ev_mix - _expected_ev(prof, probe, left_region)) < 1e-3


# ---------------------------------------------------------------------------
# CLI: fix/batch 默认开启检测, --no-detect 关闭
# ---------------------------------------------------------------------------

def test_cli_no_detect_flag_parse():
    from rawlab.rawlab_cli import build_parser
    p = build_parser()
    assert p.parse_args(["fix", "x.nef"]).no_detect is False
    assert p.parse_args(["fix", "x.nef", "--no-detect"]).no_detect is True
    assert p.parse_args(["batch", "some_dir"]).no_detect is False
    assert p.parse_args(["batch", "some_dir", "--no-detect"]).no_detect is True


def test_cli_detect_boxes_helper(monkeypatch):
    """_detect_boxes: 默认接线 run_analysis → detect_subjects; --no-detect 返回空框。"""
    from rawlab import vision_bridge
    from rawlab.rawlab_cli import _detect_boxes

    def fake_detect(bgr8):
        assert bgr8.dtype == np.uint8
        return ([[0.0, 0.0, 1.0, 1.0]], [[0.1, 0.1, 0.4, 0.4]])
    monkeypatch.setattr(vision_bridge, "detect_subjects", fake_detect)

    rgb8 = np.zeros((16, 16, 3), dtype=np.uint8)
    prof = _make_profile()
    subj, faces = _detect_boxes(False, "test.nef", prof, rgb8)
    assert subj == [[0.0, 0.0, 1.0, 1.0]]
    assert faces == [[0.1, 0.1, 0.4, 0.4]]
    # --no-detect → 不检测, 直接空框
    subj2, faces2 = _detect_boxes(True, "test.nef", prof, rgb8)
    assert subj2 == [] and faces2 == []
