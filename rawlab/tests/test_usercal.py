"""T2.2 用户 RGB 校准 (shadow tint + 三原色 hue/sat) 单元测试。

验证: 全 0/禁用逐位 no-op、中性灰不变、shadow_tint 只显著改暗部且 G 不变、
正负方向、red hue/sat 只影响红像素、hue 模 360 等价、clip[0,1] 无 NaN、
暗部→中灰连续无硬边、stage schema 越界拒绝。
"""
from __future__ import annotations

import numpy as np
import pytest

from rawlab.engine.core import StageContext, DOMAIN_GAMMA_RGB
from rawlab.engine.usercal import apply_usercal_rgb
from rawlab.engine.stages.calibration import CalibrationStage


def _run_stage(img, params):
    ctx = StageContext("t", prof=None, config={})
    ctx.set_image(img.astype(np.float32), DOMAIN_GAMMA_RGB)
    CalibrationStage(params).run(ctx)
    return ctx.image


def test_all_zero_noop():
    rng = np.random.default_rng(0)
    img = rng.random((16, 16, 3), dtype=np.float32)
    out = apply_usercal_rgb(img)
    assert out.dtype == np.float32
    assert np.array_equal(out, img.astype(np.float32))


def test_disabled_stage_noop():
    img = np.full((8, 8, 3), 0.5, dtype=np.float32)
    ctx = StageContext("t", config={})
    ctx.set_image(img, DOMAIN_GAMMA_RGB)
    st = CalibrationStage()          # enabled=False
    assert st.wants(ctx) is False
    out = _run_stage(img, {})
    assert np.array_equal(out, img)


def test_mid_gray_unchanged_shadow_tint():
    mid = np.full((4, 4, 3), 0.5, dtype=np.float32)
    assert np.array_equal(apply_usercal_rgb(mid, shadow_tint=80), mid)
    assert np.array_equal(apply_usercal_rgb(mid, shadow_tint=-80), mid)


def test_neutral_gray_unchanged_primaries():
    gray = np.full((4, 4, 3), 0.5, dtype=np.float32)
    assert np.array_equal(apply_usercal_rgb(gray, red_hue=40, red_sat=80,
                                            green_hue=-20, blue_hue=30), gray)


def test_shadow_tint_only_dark_and_g_unchanged():
    dark = np.full((4, 4, 3), 0.05, dtype=np.float32)   # 深暗部
    mid = np.full((4, 4, 3), 0.5, dtype=np.float32)
    od = apply_usercal_rgb(dark, shadow_tint=60)
    # G 通道完全不变
    assert np.array_equal(od[..., 1], dark[..., 1])
    # 暗部 R/B 改变显著
    assert float(np.abs(od[..., 0] - dark[..., 0]).max()) > 0.005
    assert float(np.abs(od[..., 2] - dark[..., 2]).max()) > 0.005
    # 中灰基本不受影响
    om = apply_usercal_rgb(mid, shadow_tint=60)
    assert float(np.abs(om - mid).max()) < 1e-5


def test_shadow_tint_positive_warm_magenta():
    dark = np.full((4, 4, 3), 0.05, dtype=np.float32)
    o = apply_usercal_rgb(dark, shadow_tint=60)
    assert float(o[0, 0, 0]) > dark[0, 0, 0], "正=暖: R 应升"
    assert float(o[0, 0, 2]) < dark[0, 0, 2], "正=暖: B 应降"


def test_shadow_tint_negative_green():
    dark = np.full((4, 4, 3), 0.05, dtype=np.float32)
    o = apply_usercal_rgb(dark, shadow_tint=-60)
    assert float(o[0, 0, 0]) < dark[0, 0, 0], "负=绿: R 应降"
    assert float(o[0, 0, 2]) > dark[0, 0, 2], "负=绿: B 应升"


def test_red_hue_affects_red_not_blue():
    red = np.array([[[0.9, 0.1, 0.1]]], dtype=np.float32)    # H≈0
    blue = np.array([[[0.1, 0.1, 0.9]]], dtype=np.float32)   # H≈240
    or_ = apply_usercal_rgb(red, red_hue=30.0)
    ob = apply_usercal_rgb(blue, red_hue=30.0)
    assert float(np.abs(or_ - red).max()) > 0.1, "红段 hue 应显著改红像素"
    assert float(np.abs(ob - blue).max()) < 0.01, "红段 hue 不应改蓝像素"


def test_red_sat_affects_red_not_blue():
    red = np.array([[[0.8, 0.3, 0.3]]], dtype=np.float32)
    blue = np.array([[[0.3, 0.3, 0.8]]], dtype=np.float32)
    os_ = apply_usercal_rgb(red, red_sat=80)
    ob = apply_usercal_rgb(blue, red_sat=80)
    assert float(np.abs(os_ - red).max()) > 0.02, "红段 sat 应改红像素"
    assert float(np.abs(ob - blue).max()) < 0.01, "红段 sat 不应改蓝像素"


def test_hue_wrap_0_360_same_treatment():
    # 色相轴环状: 0° 与 360° 是同一色相 ⇒ 红段掩码对 hue≈1° 与 hue≈355° 像素
    # 给予相同处理 (mask 在 5° 与 355° 一致), red_sat 对两者效果对称。
    from rawlab.engine.hsl import _ring_mask
    m = _ring_mask(np.array([1.0, 359.0], dtype=np.float64), 0.0, 60.0, 1.0)
    assert float(m[0] - m[1]) < 1e-6, "0/360 色相环绕掩码应一致"
    a = apply_usercal_rgb(np.array([[[0.9, 0.2, 0.1]]], np.float32), red_sat=80)  # H≈5°
    b = apply_usercal_rgb(np.array([[[0.9, 0.1, 0.2]]], np.float32), red_sat=80)  # H≈355°
    # 两者 R 不变、G/B 对称下降 (同一色段对称处理)
    assert abs(float(a[0, 0, 0]) - float(b[0, 0, 0])) < 1e-5
    assert abs(float(a[0, 0, 1]) - float(b[0, 0, 2])) < 1e-5


def test_output_clip_no_nan():
    rng = np.random.default_rng(7)
    img = rng.random((32, 32, 3), dtype=np.float32)
    out = apply_usercal_rgb(img, shadow_tint=50, red_hue=20, red_sat=40,
                            green_hue=-15, blue_sat=-60)
    assert out.dtype == np.float32
    assert np.isfinite(out).all()
    assert float(out.min()) >= 0.0 and float(out.max()) <= 1.0


def test_shadow_transition_continuous():
    # 从深暗到中灰的 ramp: R/B 增益随亮度 smoothstep, 无硬跳
    x = np.linspace(0.0, 0.6, 512, dtype=np.float32)
    img = np.repeat(np.repeat(x[None, :, None], 4, axis=0), 3, axis=2)
    o = apply_usercal_rgb(img, shadow_tint=80)
    r = o[0, :, 0]
    # 相邻像素最大跳变足够小 (掩码 smoothstep 连续)
    assert float(np.abs(np.diff(r)).max()) < 0.02


def test_stage_wants_only_enabled_with_effect():
    img = np.full((4, 4, 3), 0.05, dtype=np.float32)
    off = CalibrationStage()                                # 默认禁
    on_no_effect = CalibrationStage({"enabled": True})      # 全 0
    on_effect = CalibrationStage({"enabled": True, "shadow_tint": 40})
    assert off.wants(_ctx(img)) is False
    assert on_no_effect.wants(_ctx(img)) is False
    assert on_effect.wants(_ctx(img)) is True


def _ctx(img):
    c = StageContext("t", config={})
    c.set_image(img.astype(np.float32), DOMAIN_GAMMA_RGB)
    return c


def test_stage_process_applies_shadow_tint():
    dark = np.full((4, 4, 3), 0.05, dtype=np.float32)
    out = _run_stage(dark, {"enabled": True, "shadow_tint": 60})
    assert not np.array_equal(out, dark)
    assert float(out[0, 0, 0]) > dark[0, 0, 0]      # R↑
    assert float(out[0, 0, 2]) < dark[0, 0, 2]      # B↓
    assert np.isfinite(out).all()


@pytest.mark.parametrize("key,val", [("shadow_tint", 150), ("shadow_tint", -120),
                                     ("red_hue", 200), ("green_hue", -190),
                                     ("blue_sat", 120), ("red_sat", -110)])
def test_stage_schema_rejects_out_of_range(key, val):
    ctx = StageContext("x", config={"stages": {"calibration": {key: val}}})
    st = CalibrationStage()
    with pytest.raises(ValueError, match=key):
        st.p(ctx, key)
