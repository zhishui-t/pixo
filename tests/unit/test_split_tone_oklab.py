"""M-O1 OKLab 域分离色调单元测试 (OWN_PIPELINE_STAGE1_DESIGN §2.3)。

验证: 两区 sat=0 / strength<=0 快路径逐位 no-op、单区 sat=0 时另一区零权重
带逐位直通、balance 端点只染对应域 (balance=0 纯高光域 / balance=1 纯阴影域)、
纯白/纯黑任何满饱和逐位不变 (C_ref 端点趋 0)、染色构造精确性 (L 保持/h 落位/
C=sat/100·C_ref(L))、近白染色自然低 C (高光色相漂移根治点)、dtype f32/[0,1]
/批量与单像素逐位一致、SplitToneStage color_domain 分派 (缺省 hsv 与旧内核
逐位一致 = 存量预设零迁移)、非法 domain 报错、默认参数表零改动。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.render.pipeline.graph import StageContext, DOMAIN_GAMMA_RGB
from pixo.render.core.hsl_oklch import _cmax_of_l
from pixo.render.core.oklab import oklab_to_oklch, srgb_to_oklab
from pixo.render.core.split_tone import split_tone_rgb
from pixo.render.core.split_tone_oklab import split_tone_oklab_rgb
from pixo.render.modules.split_tone import SplitToneStage


def _run_stage(params, img):
    ctx = StageContext("t", prof=None, config={})
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    st = SplitToneStage(params={**params, "enabled": True})
    st.run(ctx)
    return ctx.image


def _gray_row(levels):
    """(len(levels), 1, 3) 灰阶图: 每行一个 Rec.709 Y=level 的中性灰。"""
    v = np.asarray(levels, dtype=np.float32)
    return np.stack([v, v, v], axis=-1)[:, None, :]


def _lch_of(rgb):
    return oklab_to_oklch(srgb_to_oklab(np.asarray(rgb, dtype=np.float64)))


# ---------------------------------------------------------------------------
# no-op 逐位纪律
# ---------------------------------------------------------------------------

def test_both_sat_zero_noop_bitwise():
    rng = np.random.default_rng(0)
    img = rng.random((16, 16, 3), dtype=np.float32)
    out = split_tone_oklab_rgb(img, 30.0, 0.0, 210.0, 0.0, balance=0.5, strength=1.0)
    assert out.dtype == np.float32
    assert np.array_equal(out, img), "两区 sat=0 必须逐位 no-op (不做域转换)"


def test_strength_zero_noop_bitwise():
    rng = np.random.default_rng(1)
    img = rng.random((12, 12, 3), dtype=np.float32)
    for strength in (0.0, -0.1):
        out = split_tone_oklab_rgb(img, 30.0, 90.0, 210.0, 60.0,
                                   balance=0.5, strength=strength)
        assert np.array_equal(out, img), f"strength={strength} 必须逐位 no-op"


def test_single_region_sat_zero_zero_weight_zone_bitwise():
    """shadows_sat>0 / highlights_sat=0 且 balance=0: 亮区 (ws=0) 像素逐位不变。"""
    img = _gray_row([0.25, 0.75])   # 行 0=暗 (过渡带内), 行 1=亮 (y>=0.5 → ws 恰为 0)
    out = split_tone_oklab_rgb(img, 30.0, 90.0, 210.0, 0.0, balance=0.0)
    assert np.array_equal(out[1], img[1]), \
        "亮区像素 (ws=0, 高光分支 sat=0 跳过) 逐位不变"
    assert not np.array_equal(out[0], img[0]), \
        "过渡带内暗区像素应被阴影染色改变"


def test_balance_zero_bright_domain_only_highlights():
    """balance=0 端点: y>=0.5 的像素恰落在纯高光域 (ws=0), 只接受高光染色。"""
    img = _gray_row([0.25, 0.75])
    full = split_tone_oklab_rgb(img, 30.0, 90.0, 210.0, 80.0, balance=0.0, strength=1.0)
    hi_only = split_tone_oklab_rgb(img, 30.0, 0.0, 210.0, 80.0, balance=0.0, strength=1.0)
    assert np.array_equal(full[1], hi_only[1]), \
        "纯高光域像素: 双区结果必须与只开高光逐位一致 (阴影权重恰为 0)"
    assert not np.array_equal(full[0], hi_only[0]), \
        "过渡带内暗区像素应叠加阴影成分, 与只开高光可区分"


def test_balance_one_dark_domain_only_shadows():
    """balance=1 端点: y<=0.5 的像素恰落在纯阴影域 (wh=0), 只接受阴影染色。"""
    img = _gray_row([0.25, 0.75])
    full = split_tone_oklab_rgb(img, 30.0, 90.0, 210.0, 80.0, balance=1.0, strength=1.0)
    sh_only = split_tone_oklab_rgb(img, 30.0, 90.0, 210.0, 0.0, balance=1.0, strength=1.0)
    assert np.array_equal(full[0], sh_only[0]), \
        "纯阴影域像素: 双区结果必须与只开阴影逐位一致 (高光权重恰为 0)"
    assert not np.array_equal(full[1], sh_only[1]), \
        "过渡带外亮区像素应叠加高光成分, 与只开阴影可区分"


def test_white_black_unchanged_at_full_sat():
    """端点亮度: 纯黑 (L=0 → C_ref=0) 逐位不变; 纯白近不变——正向矩阵下
    白像素 L=0.99999999 落在 C_ref 陡沿, 残余 ~2e-4 色度 → f32 出口偏差
    ≤4e-7 (感知不可见, 即"近白自然低 C"的设计行为)。"""
    img = _gray_row([0.0, 1.0])
    out = split_tone_oklab_rgb(img, 30.0, 100.0, 210.0, 100.0,
                               balance=0.5, strength=1.0)
    assert np.array_equal(out[0], img[0]), "纯黑 (L=0, C=0) 必须逐位不变"
    drift = float(np.abs(out[1].astype(np.float64) - img[1].astype(np.float64)).max())
    assert drift <= 4e-7, f"纯白近不变: 偏差 {drift:.2e} 应 ≤4e-7 (≤数 ulp)"


# ---------------------------------------------------------------------------
# 染色构造语义 (OKLab 域)
# ---------------------------------------------------------------------------

def test_shadow_tint_exact_construction():
    """纯阴影域 (balance=1, y<=0.5 → ws=1): out 即染色色。
    验证 L 保持、h 落位、C = sat/100·C_ref(L)。"""
    img = _gray_row([0.2])
    out = split_tone_oklab_rgb(img, 264.0, 80.0, 210.0, 0.0,
                               balance=1.0, strength=1.0)
    lch_in = _lch_of(img[0])[0]
    lch_out = _lch_of(out[0])[0]
    assert abs(float(lch_out[2]) - 264.0) < 2.0, f"h 应落在 264° 附近 (实际 {lch_out[2]:.2f})"
    assert abs(float(lch_out[0]) - float(lch_in[0])) < 0.02, "染色保持像素亮度 L"
    c_expect = 0.8 * float(_cmax_of_l(np.array([float(lch_in[0])]))[0])
    assert abs(float(lch_out[1]) - c_expect) < 0.02, \
        f"C 应为 sat/100·C_ref(L)={c_expect:.4f} (实际 {lch_out[1]:.4f})"


def test_highlight_chroma_naturally_low_near_white():
    """近白染色自然低 C (感知线性): 同 hue/sat, L 高的像素染色 C 显著更小;
    色域内时 hue 精确落位; 近白 (色域顶点) 任何 sat 的蓝向染色都被 clip
    收缩 → 只保证微小冷调, 不保证 hue 落位 (白点几何固有, 非 bug)。"""
    img = _gray_row([0.7, 0.995])
    out = split_tone_oklab_rgb(img, 30.0, 0.0, 264.0, 100.0,
                               balance=0.0, strength=1.0)
    lch_mid = _lch_of(out[0])[0]
    lch_near_white = _lch_of(out[1])[0]
    assert float(lch_near_white[1]) < 0.5 * float(lch_mid[1]), \
        f"近白 C={lch_near_white[1]:.4f} 应显著低于中灰 C={lch_mid[1]:.4f}"
    # 色域内 (sat=30, 中灰): hue 精确落位
    out30 = split_tone_oklab_rgb(img, 30.0, 0.0, 264.0, 30.0,
                                 balance=0.0, strength=1.0)
    assert abs(float(_lch_of(out30[0])[0, 2]) - 264.0) < 2.0, \
        "色域内染色 hue 应精确落位 264°"
    # 近白 (L→1 色域收缩为白点): 蓝向染色被 clip 收缩 → 染色量微小且保持
    # 冷色通道序 (b>=g>=r, hue264 的意图在通道空间成立), hue 角度本身无意义
    assert float(lch_near_white[1]) < 0.03, "近白染色量应微小"
    rgb_near_white = out[1, 0]
    assert bool(rgb_near_white[2] >= rgb_near_white[1] >= rgb_near_white[0]), \
        "hue=264 染色应保持冷色通道序 (b>=g>=r)"


# ---------------------------------------------------------------------------
# dtype / 数值契约
# ---------------------------------------------------------------------------

def test_dtype_range_and_batch_single_bitwise_consistency():
    rng = np.random.default_rng(3)
    img = rng.random((16, 16, 3), dtype=np.float32)
    out = split_tone_oklab_rgb(img, 30.0, 70.0, 210.0, 50.0,
                               balance=0.4, strength=0.8)
    assert out.dtype == np.float32
    assert np.isfinite(out).all()
    assert bool((out >= 0.0).all() and (out <= 1.0).all())
    # 批量与单像素逐位一致 (纯逐元素管线)
    single = np.stack([split_tone_oklab_rgb(img[i], 30.0, 70.0, 210.0, 50.0,
                                            balance=0.4, strength=0.8)
                       for i in range(img.shape[0])])
    assert np.array_equal(out, single), "批量与逐像素结果必须逐位一致"


def test_balance_endpoint_weights_exact():
    """亮度分域逐位复用旧内核: 新内核 import 同一 _shadow_weight/_RGB_WEIGHTS,
    端点 balance 下权重带外恰为 0/1 (零权重区逐位直通的根基)。"""
    from pixo.render.core.split_tone import _RGB_WEIGHTS, _shadow_weight
    rng = np.random.default_rng(5)
    img = rng.random((32, 32, 3), dtype=np.float32)
    y = np.clip(img.astype(np.float64) @ _RGB_WEIGHTS, 0.0, 1.0)
    ws_b0 = _shadow_weight(y, 0.0)   # 转型带 [-0.5, 0.5]
    assert float(ws_b0[y >= 0.5].max()) == 0.0, "balance=0: y>=0.5 阴影权重恰为 0"
    assert float(ws_b0.min()) >= 0.0
    ws_b1 = _shadow_weight(y, 1.0)   # 转型带 [0.5, 1.5]
    assert float(ws_b1[y <= 0.5].min()) == 1.0, "balance=1: y<=0.5 阴影权重恰为 1 (高光权重 0)"
    assert float(ws_b1.max()) <= 1.0


# ---------------------------------------------------------------------------
# SplitToneStage color_domain 分派
# ---------------------------------------------------------------------------

_P = {"shadows_hue": 30.0, "shadows_sat": 70.0,
      "highlights_hue": 210.0, "highlights_sat": 50.0,
      "balance": 0.45, "strength": 0.9}


def test_stage_default_hsv_bitwise_identical_to_old_kernel():
    """缺省 color_domain=hsv: Stage 输出与旧 split_tone_rgb 逐位一致 (A1 硬约束)。"""
    rng = np.random.default_rng(0)
    img = rng.random((16, 16, 3), dtype=np.float32)
    out = _run_stage(dict(_P), img)
    ref = split_tone_rgb(img.astype(np.float64), _P["shadows_hue"], _P["shadows_sat"],
                         _P["highlights_hue"], _P["highlights_sat"],
                         balance=_P["balance"], strength=_P["strength"])
    assert np.array_equal(out, ref)


def test_stage_color_domain_oklch_dispatch():
    """color_domain=oklch: 分派到 split_tone_oklab_rgb (逐位一致), 且与 hsv 可区分。"""
    rng = np.random.default_rng(0)
    img = rng.random((16, 16, 3), dtype=np.float32)
    out_hsv = _run_stage(dict(_P), img)
    out_oklch = _run_stage({**_P, "color_domain": "oklch"}, img)
    ref = split_tone_oklab_rgb(img.astype(np.float64), _P["shadows_hue"], _P["shadows_sat"],
                               _P["highlights_hue"], _P["highlights_sat"],
                               balance=_P["balance"], strength=_P["strength"])
    assert np.array_equal(out_oklch, ref)
    assert not np.array_equal(out_oklch, out_hsv), "两域染色结果应可区分"


def test_stage_default_params_preserved():
    """默认参数表: 原有键值零改动 (UI/胶片卡契约), 仅新增 color_domain=hsv。"""
    dp = SplitToneStage().default_params()
    assert dp == {"enabled": False,
                  "shadows_hue": 45.0, "shadows_sat": 0.0,
                  "highlights_hue": 210.0, "highlights_sat": 0.0,
                  "balance": 0.5, "strength": 1.0,
                  "color_domain": "hsv"}
    assert "color_domain" in SplitToneStage.param_schema


def test_stage_disabled_noop():
    img = np.full((8, 8, 3), 0.5, dtype=np.float32)
    ctx = StageContext("t", prof=None, config={})
    ctx.set_image(img, DOMAIN_GAMMA_RGB)
    st = SplitToneStage()
    assert st.wants(ctx) is False
    ctx2 = StageContext("t", prof=None, config={})
    ctx2.set_image(img, DOMAIN_GAMMA_RGB)
    st.run(ctx2)
    assert np.array_equal(ctx2.image, img)


def test_stage_sat_zero_noop_both_domains():
    """两区 sat=0: 任一 color_domain 下 Stage 输出逐位不变 (design §2.3)。"""
    rng = np.random.default_rng(2)
    img = rng.random((8, 8, 3), dtype=np.float32)
    for domain in ("hsv", "oklch"):
        out = _run_stage({"shadows_sat": 0.0, "highlights_sat": 0.0,
                          "color_domain": domain}, img)
        assert np.array_equal(out, img), f"domain={domain} sat=0 必须逐位 no-op"


@pytest.mark.parametrize("bad", ["lab", "OKLAB", "srgb"])
def test_stage_invalid_domain_raises(bad):
    rng = np.random.default_rng(4)
    img = rng.random((4, 4, 3), dtype=np.float32)
    with pytest.raises(ValueError):
        _run_stage({**_P, "color_domain": bad}, img)
