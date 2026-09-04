"""M-O2 单元测试: OKLab 皮肤椭圆 (core/skin.py 新增部分) + color_domain 双轨分派。

覆盖 (设计 §3):
  - SKIN_OKLAB_* 常数与 skin_mask_oklab: 肤色高 / 中性灰与绿蓝低 / 软边界中间值;
    float [0,1] 契约; uint8 输入自动归一 (与 float /255 精确一致); 形状校验;
    黑白/原色无 NaN。
  - 旧函数不动: skin_mask 在同一输入上保持原行为 (与旧椭圆常数一致)。
  - SkinStage: color_domain 缺省 hsv 时 process 与旧手算链路逐位一致; oklch
    域走 OKLab 掩码 (动态找新/旧掩码分歧探针色, 断言两域输出确实分叉);
    非法域 raise。
  - colorcal: color_domain 显式 hsv 与缺省逐位一致; oklch 域 skin_trim 用
    OKLab 掩码 (与 SkinStage 同源); 非法域 raise。
  - scripts/fit_skin_oklch.py 椭圆拟合数学: 已知椭圆采样点回收参数;
    scripts/convert_hsm_to_oklch.py 合成 HSM 表 → OKLCh 控制点语义正确。

运行: python -m pytest tests/unit/test_skin_oklab.py -q
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from pixo.render.core.oklab import oklab_to_srgb, srgb_to_oklab
from pixo.render.core.skin import (
    SKIN_LAB_A,
    SKIN_MAJOR,
    skin_mask,
    skin_mask_oklab,
    skin_smooth,
    SKIN_OKLAB_A,
    SKIN_OKLAB_ANGLE,
    SKIN_OKLAB_B,
    SKIN_OKLAB_MAJOR,
    SKIN_OKLAB_MINOR,
    SKIN_OKLAB_SOFT_BAND,
)
from pixo.render.modules.color_cal import ColorCalStage
from pixo.render.modules.skin import SkinStage, _mask_fn
from pixo.render.pipeline.graph import DOMAIN_GAMMA_RGB, StageContext

# 经典测试肤色 (test_skin.py 同款): 旧 cv2-Lab 椭圆内; 拟合样本即语料肤色,
# 新椭圆必须覆盖同类肤色 (验收下限 0.5, 收紧留给语料对照报告)
_SKIN_RGB = (210, 155, 130)
_GRAY_RGB = (128, 128, 128)
_GREEN_RGB = (60, 160, 80)


def _solid(h, w, rgb, dtype=np.uint8):
    if dtype == np.uint8:
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:, :] = rgb
    else:
        img = np.zeros((h, w, 3), dtype=np.float64)
        img[:, :] = np.asarray(rgb) / 255.0
    return img


# ---------------------------------------------------------------------------
# 常数与 skin_mask_oklab
# ---------------------------------------------------------------------------

def test_constants_sane():
    assert SKIN_OKLAB_MAJOR >= SKIN_OKLAB_MINOR > 0.0
    assert -np.pi / 2 <= SKIN_OKLAB_ANGLE <= np.pi / 2
    assert SKIN_OKLAB_SOFT_BAND > 0.0
    assert SKIN_OKLAB_A > 0.0 and SKIN_OKLAB_B > 0.0
    # 中性原点必须落在椭圆软边界之外 (mask 严格 0) —— 中性灰不得被判肤
    cos_a, sin_a = np.cos(SKIN_OKLAB_ANGLE), np.sin(SKIN_OKLAB_ANGLE)
    u = -SKIN_OKLAB_A * cos_a - SKIN_OKLAB_B * sin_a
    v = SKIN_OKLAB_A * sin_a - SKIN_OKLAB_B * cos_a
    d0 = np.hypot(u / SKIN_OKLAB_MAJOR, v / SKIN_OKLAB_MINOR)
    assert d0 > 1.0 + SKIN_OKLAB_SOFT_BAND, \
        f"中性原点距椭圆 d={d0:.3f}, 应 > 1+soft_band"


def test_skin_mask_oklab_basic():
    m_skin = skin_mask_oklab(_solid(8, 8, _SKIN_RGB, np.float64))
    assert m_skin.dtype == np.float32 and m_skin.shape == (8, 8)
    assert float(m_skin.min()) > 0.5, "拟合椭圆应覆盖经典测试肤色"
    for rgb in (_GRAY_RGB, _GREEN_RGB):
        m = skin_mask_oklab(_solid(8, 8, rgb, np.float64))
        assert float(m.max()) == 0.0, f"非肤色 {rgb} 应为 0"


def test_skin_mask_oklab_noop_extremes_no_nan():
    for rgb in ((0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0),
                (0, 0, 255)):
        m = skin_mask_oklab(_solid(4, 4, rgb, np.float64))
        assert np.isfinite(m).all() and float(m.max()) <= 1.0


def test_skin_mask_oklab_uint8_equals_float():
    u8 = _solid(6, 6, _SKIN_RGB)
    a = skin_mask_oklab(u8)
    b = skin_mask_oklab(u8.astype(np.float64) / 255.0)
    assert np.array_equal(a, b), "uint8 输入应精确等于 float /255 路径"


def test_skin_mask_oklab_soft_boundary_intermediate():
    # 从椭圆中心沿"过肤色点"射线外扫 → d 线性增, 掩码单调下降且存在 (0,1)
    # 中间值 (软边)。注意 (N,3) 批量 OKLab 不是合法图像入参, 须整形 (N,1,3)。
    base = np.asarray(_SKIN_RGB, dtype=np.float64) / 255.0
    lab0 = srgb_to_oklab(base)
    center_ab = np.array([SKIN_OKLAB_A, SKIN_OKLAB_B])
    dir_ab = np.array([lab0[1], lab0[2]]) - center_ab
    ts = np.linspace(0.0, 2.2, 128)          # t=1 处 d≈0.85, 软带在 t≈1.2-1.5
    ab_path = center_ab[None, :] + ts[:, None] * dir_ab[None, :]
    lch = np.stack([np.full_like(ts, lab0[0]), ab_path[:, 0], ab_path[:, 1]],
                   axis=-1)
    rgbs = oklab_to_srgb(lch).astype(np.float64)
    m = skin_mask_oklab(rgbs.reshape(-1, 1, 3)).ravel()
    assert np.all(np.diff(m) <= 1e-6), "沿射线外扫掩码应单调不升"
    assert m[0] > 0.99 and m[-1] == 0.0, "端点应为全量 1 → 0"
    assert np.any((m > 0.0) & (m < 1.0)), "软过渡带应存在中间值"


def test_skin_mask_oklab_input_validation():
    with pytest.raises(ValueError):
        skin_mask_oklab(np.zeros((4, 4, 2)))
    gray = np.zeros((4, 4))
    assert skin_mask_oklab(gray).shape == (4, 4), "2D 灰度输入扩 3 通道"


def test_old_skin_mask_untouched():
    """旧 Lab 椭圆行为不变 (双轨回退保证): 经典肤色内、灰/绿外、中心 d=0。"""
    assert float(skin_mask(_solid(4, 4, _SKIN_RGB)).min()) >= 1.0
    assert float(skin_mask(_solid(4, 4, _GRAY_RGB)).max()) == 0.0
    from pixo.render.core.skin import SKIN_LAB_B, _ellipse_mahalanobis
    lab = np.zeros((1, 1, 3), dtype=np.uint8)
    lab[0, 0] = (128, int(SKIN_LAB_A), int(SKIN_LAB_B))  # u8 域椭圆中心
    d = _ellipse_mahalanobis(lab)
    assert float(d[0, 0]) == pytest.approx(0.0), \
        f"u8 域椭圆中心马氏距离应为 0 (got {float(d[0, 0])})"


# ---------------------------------------------------------------------------
# 分派: _mask_fn / SkinStage / colorcal
# ---------------------------------------------------------------------------

def test_mask_fn_dispatch():
    from pixo.render.core.skin import skin_mask_oklab as _sm
    assert _mask_fn("hsv") is skin_mask
    assert _mask_fn("oklch") is _sm
    assert _mask_fn(" OKLCH ") is _sm
    with pytest.raises(ValueError):
        _mask_fn("lab")


def _probe_divergent_rgb():
    """动态找两域掩码分歧最大的探针色 (肤色 a-b 邻域网格, 确定性)。

    注: M-O2 拟合独立复现了旧椭圆的判定几何 (对照报告 fp_bg 0.258 vs 0.271),
    两域在软边带的分歧为 ~0.1 量级, 无 >0.9/<0.1 的强分歧色 —— 用最大分歧
    口径而非阈值分域。
    """
    grid = np.stack(np.meshgrid(
        np.linspace(0.55, 0.85, 40),                      # L
        np.linspace(-0.06, 0.14, 80),                     # a
        np.linspace(-0.02, 0.14, 80),                     # b
    ), axis=-1).reshape(-1, 3)
    cand = np.clip(np.asarray(oklab_to_srgb(grid), dtype=np.float64), 0.0, 1.0)
    m_new = skin_mask_oklab(cand.reshape(-1, 1, 3)).ravel()
    m_old = skin_mask((cand.reshape(-1, 1, 3) * 255.0 + 0.5).astype(np.uint8)).ravel()
    disagree = np.abs(m_new - m_old)
    idx = int(np.argmax(disagree))
    assert float(disagree[idx]) >= 0.02, \
        f"两域掩码最大分歧 {float(disagree[idx]):.4f} 过小: 拟合常数可疑"
    px = cand[idx]
    return px, float(m_new[idx]), float(m_old[idx])


def test_skin_stage_hsv_default_bit_identical_to_legacy():
    img = np.clip(_solid(32, 32, _SKIN_RGB) / 255.0, 0, 1).astype(np.float32)
    ctx = StageContext("x.NEF", config={"stages": {"skin": {
        "enabled": True, "strength": 0.6, "scene": None}}})
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    SkinStage().run(ctx)
    rgb8 = (img * 255.0 + 0.5).astype(np.uint8)
    expect = skin_smooth(rgb8, skin_mask(rgb8), 0.6).astype(np.float32) / 255.0
    assert np.array_equal(np.clip(ctx.image, 0, 1), expect), \
        "缺省 hsv 域 process 必须与旧手算链路逐位一致"


def test_skin_stage_oklch_uses_oklab_mask():
    probe01, m_new0, _m_old0 = _probe_divergent_rgb()
    # 纯色块上引导滤波恒等于原值, 掩码差异不会进入输出; 加 ±15/255 棋盘
    # 微纹理使 smoothed≠img, 掩码权重差才能体现到混合结果
    checker = ((np.add.outer(np.arange(32), np.arange(32)) % 2) * 2 - 1) \
        * (15.0 / 255.0)
    img = np.clip(probe01[None, None, :] + checker[:, :, None],
                  0.0, 1.0).astype(np.float32)
    outs = {}
    for domain in ("hsv", "oklch"):
        ctx = StageContext("x.NEF", config={"stages": {"skin": {
            "enabled": True, "strength": 0.6, "color_domain": domain}}})
        ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
        SkinStage().run(ctx)
        outs[domain] = np.clip(ctx.image, 0, 1)
    assert not np.array_equal(outs["hsv"], outs["oklch"]), \
        "分歧探针色上两域磨皮输出必须不同"
    # 掩码占比门控在 oklch 域同样生效 (探针色掩码均值过门限则放行)
    ctx = StageContext("x.NEF", config={"stages": {"skin": {
        "enabled": True, "color_domain": "oklch"}}})
    ctx.set_image(img.copy(), DOMAIN_GAMMA_RGB)
    assert SkinStage().wants(ctx) is (m_new0 >= 0.005)


def test_skin_stage_invalid_domain_raises():
    img = np.clip(_solid(16, 16, _SKIN_RGB) / 255.0, 0, 1).astype(np.float32)
    ctx = StageContext("x.NEF", config={"stages": {"skin": {
        "enabled": True, "color_domain": "lab"}}})
    ctx.set_image(img, DOMAIN_GAMMA_RGB)
    with pytest.raises(ValueError):
        SkinStage().run(ctx)


_COLORCAL_SKIN_TRIM = {
    "saturation": 0.0, "vibrance": 0.0, "hue": 0.0,
    "neutral_a": 0.0, "neutral_b": 0.0, "neutral_mode": "off",
    "skin_protect": 0.0, "gamut_soft": 0.0, "skin_trim": [6.0, -6.0],
}


def _run_colorcal(img01, extra=None):
    cfg = dict(_COLORCAL_SKIN_TRIM)
    if extra:
        cfg.update(extra)
    ctx = StageContext("x.NEF", config={"stages": {"colorcal": cfg}})
    ctx.set_image(np.asarray(img01, dtype=np.float32), DOMAIN_GAMMA_RGB)
    ColorCalStage().run(ctx)
    return np.clip(ctx.image, 0, 1)


def test_colorcal_explicit_hsv_matches_default():
    img = np.clip(_solid(32, 32, _SKIN_RGB) / 255.0, 0, 1).astype(np.float32)
    a = _run_colorcal(img)
    b = _run_colorcal(img, {"color_domain": "hsv"})
    assert np.array_equal(a, b), "显式 hsv 与缺省必须逐位一致"


def test_colorcal_oklch_domain_switches_skin_trim_mask():
    probe01, m_new0, _m_old0 = _probe_divergent_rgb()
    img = np.full((32, 32, 3), probe01, dtype=np.float32)
    out_hsv = _run_colorcal(img.copy(), {"color_domain": "hsv"})
    out_oklch = _run_colorcal(img.copy(), {"color_domain": "oklch"})
    assert not np.array_equal(out_hsv, out_oklch), \
        "分歧探针色上 skin_trim 两域结果必须不同 (掩码联动生效)"
    # oklch 掩码与 SkinStage 同源: 新掩码内像素才有 trim 作用
    if m_new0 > 0.05:
        assert not np.array_equal(out_oklch, img), "新掩码内 trim 应生效"
    else:
        assert np.array_equal(out_oklch, img), "新掩码外 trim 不应作用"


def test_colorcal_invalid_domain_raises():
    img = np.clip(_solid(8, 8, _SKIN_RGB) / 255.0, 0, 1).astype(np.float32)
    with pytest.raises(ValueError):
        _run_colorcal(img, {"color_domain": "lab"})


# ---------------------------------------------------------------------------
# scripts 数学 (不依赖语料)
# ---------------------------------------------------------------------------

def _load_script(name: str):
    path = Path(__file__).resolve().parents[2] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _synthetic_ellipse_pts(cx=0.03, cy=0.10, major=0.08, minor=0.04,
                           angle=0.5, n=40000, seed=3):
    rng = np.random.default_rng(seed)
    r = np.sqrt(rng.uniform(0.0, 0.90, n))     # 面积均匀 (留 10% 边缘外样)
    th = rng.uniform(0.0, 2.0 * np.pi, n)
    u, v = r * major * np.cos(th), r * minor * np.sin(th)
    ca, sa = np.cos(angle), np.sin(angle)
    return np.column_stack([cx + u * ca - v * sa, cy + u * sa + v * ca])


def test_fit_script_recovers_known_ellipse():
    mod = _load_script("fit_skin_oklch.py")
    pts = _synthetic_ellipse_pts()
    ell = mod.fit_skin_ellipse(pts, coverage=0.99)
    assert abs(ell["center_a"] - 0.03) < 3e-3
    assert abs(ell["center_b"] - 0.10) < 3e-3
    ratio = ell["major"] / ell["minor"]
    assert ratio == pytest.approx(2.0, rel=0.15)
    ang = np.radians(ell["angle_deg"])
    assert abs(((ang - 0.5) + np.pi / 2) % np.pi - np.pi / 2) < np.radians(3), \
        f"倾角回收偏差过大: {ell['angle_deg']}°"
    # 覆盖定标: 拟合椭圆对同分布样本召回 >= coverage-0.01
    d = mod.ellipse_mahalanobis(
        pts, ell["center_a"], ell["center_b"], ell["major"], ell["minor"],
        float(np.radians(ell["angle_deg"])))
    assert float((d <= 1.0).mean()) >= 0.98


def test_hsm_convert_semantics():
    from pixo.render.core.huesat import make_hue_sat_map
    mod = _load_script("convert_hsm_to_oklch.py")
    dims = (24, 5, 3)
    flat = make_hue_sat_map([(30.0, 5.0, 1.2)], h_divs=dims[0],
                            s_divs=dims[1], v_divs=dims[2], val_min=0.6)
    # DCP 扁平布局 (s 最快) → (H,S,V,3), 解包口径同 huesat.decode_table
    table = np.asarray(flat, dtype=np.float32).reshape(
        dims[2], dims[0], dims[1], 3).transpose(1, 2, 0, 3)
    assert table[2, 1, 2, 1] == pytest.approx(1.2), "带中心 sat_scale 应=1.2"
    points = mod.convert(table, dims, encoding=0)
    # 值域守卫 (防 L/C/h 列错位): h∈[0,360), C≤~0.33 (sRGB 包络), L∈[0,1.01]
    # (黑格 L=0 合法; V 缩放>1 的 L 上溢由真表数据承载, 合成表无)
    for p in points:
        assert 0.0 <= p["h"] < 360.0, p
        assert 0.0 <= p["c"] <= 0.4, p
        assert 0.0 <= p["l"] <= 1.01, p

    def at(i, j, k):
        return next(p for p in points if p["grid"] == [i, j, k])

    # 带中心 (hue=30°, S=0.25, V=1): 表 sat_scale=1.2 → OKLCh 色度增益 >1
    hit = at(2, 1, 2)
    # 纯 sat 带无 hue_shift 平面, 但 ProPhoto→sRGB→OKLCh 域转换会让色相
    # 漂移 ~0.7° (实测) —— 控制点记录的是含交叉泄漏的等效作用量, 容差取 2°
    assert abs(hit["dh"]) < 2.0, f"纯 sat 带色相漂移应仅来自域转换: {hit}"
    assert hit["c_gain"] > 1.1, f"带中心色度增益应显著 >1: {hit}"
    assert hit["l_gain"] == pytest.approx(1.0, abs=5e-2)
    # 恒等节点 (带外 + V 窗口外): 三个作用量均为恒等
    idle = at(14, 0, 0)
    assert abs(idle["dh"]) < 1e-2
    assert idle["c_gain"] == pytest.approx(1.0, abs=1e-3)
    assert idle["l_gain"] == pytest.approx(1.0, abs=1e-3)    # 剪除口径: 恒等节点数 > 0 且非恒等节点被保留
    n_idle = sum(1 for p in points
                 if abs(p["dh"]) < mod.EPS_DH
                 and abs(p["c_gain"] - 1.0) < mod.EPS_GAIN
                 and abs(p["l_gain"] - 1.0) < mod.EPS_GAIN)
    assert n_idle > 0 and n_idle < len(points)


# ---------------------------------------------------------------------------
# 常数逐位锁定 (终审 G-1): core/skin.py ↔ configs/color/skin_oklab.json
# ---------------------------------------------------------------------------

_SKIN_OKLAB_JSON = (Path(__file__).resolve().parents[2] / "configs" / "color"
                    / "skin_oklab.json")


def test_skin_oklab_constants_bitwise_locked_to_fit_json():
    """SKIN_OKLAB_* 六常数与拟合产物 skin_oklab.json 逐位一致 (G-1)。

    "逐位" = IEEE 754 double 精确相等 (==), 非 approx: JSON 十进制字面量与
    skin.py 字面量必须解析到同一位型。任一方漂移 (重拟合回填遗漏 / 手改常数
    绕过拟合产物) 即翻红, 且断言消息给出 float.hex() 位型证据。
    """
    import json
    assert _SKIN_OKLAB_JSON.exists(), f"拟合产物缺失: {_SKIN_OKLAB_JSON}"
    cfg = json.loads(_SKIN_OKLAB_JSON.read_text(encoding="utf-8"))
    assert cfg.get("schema") == "pixo.skin_oklab.v1", (
        f"schema 漂移: {cfg.get('schema')!r} (读错文件?)")
    consts = cfg.get("constants") or {}
    locked = {
        "SKIN_OKLAB_A": SKIN_OKLAB_A,
        "SKIN_OKLAB_B": SKIN_OKLAB_B,
        "SKIN_OKLAB_MAJOR": SKIN_OKLAB_MAJOR,
        "SKIN_OKLAB_MINOR": SKIN_OKLAB_MINOR,
        "SKIN_OKLAB_ANGLE": SKIN_OKLAB_ANGLE,
        "SKIN_OKLAB_SOFT_BAND": SKIN_OKLAB_SOFT_BAND,
    }
    assert set(consts) == set(locked), (
        f"JSON constants 键集漂移: json={sorted(consts)} code={sorted(locked)}")
    for key, code_val in locked.items():
        json_val = float(consts[key])
        assert json_val == code_val, (
            f"{key} 常数与拟合产物漂移: code={code_val!r} json={json_val!r} "
            f"(位型 {float(code_val).hex()} vs {json_val.hex()}); 若为重拟合回填, "
            f"须同步 core/skin.py 与 configs/color/skin_oklab.json, 并重跑金样本"
            f"(skin_oklch) 与本测试")


def test_skin_oklab_json_angle_deg_consistent_with_constant():
    """JSON 的 angle_deg (度) 与 SKIN_OKLAB_ANGLE (弧度) 换算一致 (防双表示漂移)。

    angle_deg 在产物中为 4 位小数舍入, 容差 1e-3°; 换算本身用精确浮点。
    """
    import json
    cfg = json.loads(_SKIN_OKLAB_JSON.read_text(encoding="utf-8"))
    deg = float(cfg["new_ellipse_fit"]["angle_deg"])
    assert np.degrees(SKIN_OKLAB_ANGLE) == pytest.approx(deg, abs=1e-3), (
        f"SKIN_OKLAB_ANGLE={SKIN_OKLAB_ANGLE!r} rad (= {np.degrees(SKIN_OKLAB_ANGLE):.6f}°) "
        f"与 JSON angle_deg={deg!r} 不一致: 拟合产物的两种表示漂移")
