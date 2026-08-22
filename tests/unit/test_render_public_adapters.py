"""Phase C 单元测试：render 规划公开文件结构。

验证新增的 pixo.render 公开适配层可导入，并与旧 core/modules/pipeline
路径指向同一对象；同时确认规划资源路径已写入 pyproject。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from pixo.render.adjustments.clarity_dehaze import ClarityStage, DehazeStage
from pixo.render.adjustments.color_calibration import ColorCalStage
from pixo.render.adjustments.exposure import ExposureStage
from pixo.render.adjustments.highlights_shadows import ToneStage as HighlightsShadowsTone
from pixo.render.adjustments.hsl import HslStage
from pixo.render.adjustments.noise_reduction import DenoiseStage
from pixo.render.adjustments.sharpening import SharpenStage
from pixo.render.adjustments.split_toning import SplitToneStage
from pixo.render.adjustments.tone_curve import ToneStage
from pixo.render.adjustments.white_balance import WhiteBalanceStage
from pixo.render.color_transform import (
    cam_wb_to_prophoto,
    linear_prophoto_to_srgb,
    srgb_decode,
    srgb_encode,
)
from pixo.render.dcp import DcpProfile, load_dcp
from pixo.render.geometry.crop_rotate import ComposeStage, compute_crop_rect
from pixo.render.modules import (
    ColorCalStage as OldColorCalStage,
    ComposeStage as OldComposeStage,
    DenoiseStage as OldDenoiseStage,
    ExposureStage as OldExposureStage,
    HslStage as OldHslStage,
    SharpenStage as OldSharpenStage,
    SplitToneStage as OldSplitToneStage,
    ToneStage as OldToneStage,
    WhiteBalanceStage as OldWhiteBalanceStage,
)
from pixo.render.raw_loader import decode_raw, load_raw
from pixo.render.params import PARAM_SCHEMAS, get_param_schema


def test_planned_public_files_exist():
    """规划文件/目录确实存在。"""
    render_dir = Path(__file__).resolve().parents[2] / "src" / "pixo" / "render"
    for rel in [
        "pipeline.py",
        "raw_loader.py",
        "dcp.py",
        "color_transform.py",
        "params.py",
        "adjustments/__init__.py",
        "adjustments/exposure.py",
        "adjustments/highlights_shadows.py",
        "geometry/__init__.py",
        "geometry/crop_rotate.py",
    ]:
        assert (render_dir / rel).exists(), f"缺少规划文件: {rel}"


def test_raw_loader_and_dcp_shims():
    """raw_loader/dcp 公开层可导入。"""
    assert callable(decode_raw)
    assert load_raw is decode_raw
    assert DcpProfile is not None
    assert callable(load_dcp)


def test_color_transform_and_params_shims():
    """color_transform/params 公开层可导入。"""
    assert callable(srgb_encode)
    assert callable(srgb_decode)
    assert callable(linear_prophoto_to_srgb)
    assert callable(cam_wb_to_prophoto)
    assert "exposure" in PARAM_SCHEMAS
    assert "whitebalance" in PARAM_SCHEMAS
    assert get_param_schema("exposure") == PARAM_SCHEMAS["exposure"]


def test_adjustment_shims_are_same_objects_as_old_modules():
    """调整层 re-export 与旧模块类是同一对象。"""
    assert ExposureStage is OldExposureStage
    assert WhiteBalanceStage is OldWhiteBalanceStage
    assert ToneStage is OldToneStage
    assert HighlightsShadowsTone is OldToneStage
    assert HslStage is OldHslStage
    assert ColorCalStage is OldColorCalStage
    assert SplitToneStage is OldSplitToneStage
    assert DenoiseStage is OldDenoiseStage
    assert SharpenStage is OldSharpenStage
    assert ClarityStage is not None
    assert DehazeStage is not None


def test_geometry_crop_rotate_is_same_as_compose():
    """geometry.crop_rotate 与原 compose Stage 同一对象。"""
    assert ComposeStage is OldComposeStage
    assert callable(compute_crop_rect)


def test_pyproject_lists_phase_c_resource_paths():
    """pyproject 已声明 configs/resources/data 作为数据路径。"""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    for token in [
        "configs/styles",
        "resources/dcp",
        "resources/camera_profiles",
        "resources/models",
        "data/golden",
    ]:
        assert token in text, f"pyproject 缺少资源路径: {token}"
