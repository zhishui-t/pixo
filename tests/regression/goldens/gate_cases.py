"""gate golden 用例定义：生成器与校验测试共享，保证输入与计算口径一致。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from pixo.render.core.color import temp_tint_to_wb
from pixo.render.core.curves import apply_lut1d, make_base_curve_lut
from pixo.render.core.enhance import clarity
from pixo.render.core.hsl import hsl_adjust_rgb
from pixo.render.core.hsl_oklch import DEFAULT_BANDS_OKLCH, oklch_adjust_rgb
from pixo.render.core.huesat import apply_local_warm_sat
from pixo.render.core.lut3d import LUT3D
from pixo.render.core.skin import skin_mask, skin_mask_oklab
from pixo.render.core.split_tone import split_tone_rgb
from pixo.render.core.split_tone_oklab import split_tone_oklab_rgb
from pixo.render.core.usercal import apply_usercal_rgb
from pixo.render.modules.exposure import soft_highlight_rolloff
from pixo.render.modules.refine import RefineStage

FEATURES = (
    "exposure", "whitebalance", "curves", "huesat", "clarity", "colorcal",
    "calibration", "hsl", "hsl_oklch", "split_tone", "split_tone_oklab",
    "skin", "skin_oklch", "skin_oklch_softband", "stylize", "refine",
    # 标定数据敏感 case (t36 §5 门禁缺口关闭): 触达正式标定表的 auto 路径,
    # 换表即漂移 (前置 15 case 均为纯函数+显式参数, 对表替换零敏感)。
    "exposure_cal_auto", "warmth_cal_auto",
    # 缺省分派 + 存量卡全管线 case (F08, oklch 前置修补 b): 堵 t52 §3.1
    # 点名的盲区 —— 前置 17 case 全部直调内核/显式参数, 不经 Stage 分派,
    # 翻转 default_params 的 color_domain 后金样本零敏感性 (t52 翻转实验
    # 全绿即证)。两 case 经 build_default_pipeline 全管线 (DEFAULT_STAGES
    # 真实链序), 分派语义在金样本层可观测。
    "default_dispatch", "card_portra_400",
    # region_adjust 全管线 case (F15, M1 验收): enabled=True + 合成软掩码
    # (F13 契约) 经真实 DEFAULT_STAGES 链序快照 —— M1 stage 的像素语义
    # (gamma 域增益曝光 + HSV S 缩放饱和 + 羽化软混合) 在金样本层可观测。
    "region_adjust",
)

_DCP_PATH = (Path(__file__).resolve().parents[3] / "resources" / "dcp"
                     / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp")


class _CalAutoRaw:
    """标定 auto case 的最小 raw 桩: _auto_ev 经 state["camera_wb"] 取 wb_B,
    raw 仅需满足 _subject_box 的 getattr 探测 (无 subject box → 全图探针)。"""

    camera_whitebalance = [2.0, 1.0, 1.5, 1.0]


def _color_steps():
    colors = np.array([
        [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0],
        [0, 1, 1], [1, 0, 1], [0.5, 0.5, 0.5], [0, 0, 0],
    ], dtype=np.float32)
    return np.repeat(np.repeat(colors.reshape(8, 1, 3), 8, axis=1), 1, axis=0)


def _gray_ramp():
    return np.linspace(0.0, 1.0, 256, dtype=np.float32).reshape(256, 1, 1)


def _warm_highlight():
    img = np.full((64, 64, 3), 0.05, dtype=np.float32)
    img[28:36, 28:36] = (0.9, 0.3, 0.05)
    return img


def _skin_patch():
    img = np.full((64, 64, 3), 128, dtype=np.uint8)
    img[16:48, 16:48] = (210, 155, 130)
    return img


def _skin_softband_probe():
    """skin_oklch_softband case 输入 (r12 观察窗清偿): OKLab 椭圆**软边带探针**。

    背景: skin/skin_oklch case 输入为饱和经典肤色 (210,155,130, 核内 d≈0.85,
    mask≡1) + 远外灰底 (mask≡0) —— R10 椭圆重拟合改了半轴与软带
    (SKIN_OKLAB_SOFT_BAND 0.25→0.31), 两 case 输出零变化 = 软边带盲区
    (qa .r10b_ok 观察窗项)。

    设计: 以经典肤色 sRGB 为**固定锚** (常数无关 —— 若探针色从椭圆常数推导,
    常数变更时输入随之平移、掩码恒定, 盲区重现), 沿两条色相射线扫色度:
    射线 A = 肤色色相方向 (45.5°), 射线 B = 肤色色相 −30° (15.5°);
    C ∈ [0.3, 1.8]×C_skin 共 32 步 × 2 射线 = 64 行 (行内均匀纯色)。
    实测 (r10 修后常数): 射线 A d∈[0.67,1.76] (核内20/软带5/核外7),
    射线 B d∈[1.16,2.39] (软带11/核外21) —— 椭圆五常数或软带宽度任一漂移,
    过渡带行的掩码值即移动 (软带行掩码梯度实测 0.94→0.01)。
    纯函数确定性 (无随机); 全部探针色已验证 sRGB 色域内无 clip
    (色域塌缩会使不同 d 的像素同色, 锁死掩码)。
    """
    import math

    from pixo.render.core.oklab import oklab_to_srgb, srgb_to_oklab

    skin01 = np.array([210, 155, 130], dtype=np.float64) / 255.0
    l0, a0, b0 = srgb_to_oklab(skin01)
    c0 = math.hypot(a0, b0)
    n = 32
    rows = []
    for hue in (math.atan2(b0, a0), math.atan2(b0, a0) - math.radians(30.0)):
        cs = np.linspace(0.3 * c0, 1.8 * c0, n)
        rgb = oklab_to_srgb(np.stack([
            np.full(n, l0),
            cs * math.cos(hue),
            cs * math.sin(hue),
        ], axis=-1))
        rows.append(np.clip(rgb, 0.0, 1.0))
    # (2×32, 3) → 每行颜色铺满 64 列 → (64, 64, 3)
    return np.repeat(np.concatenate(rows, axis=0), 64, axis=0).reshape(
        64, 64, 3).astype(np.float32)


def _random_small():
    return np.random.default_rng(20260820).random((64, 64, 3), dtype=np.float32)


class _FullPipeRaw:
    """全管线 case 的最小 raw 桩: whitebalance as_shot 经
    camera_neutral_wb 仅消费 camera_whitebalance (G=1 归一)。"""

    camera_whitebalance = [1.05, 1.0, 0.96, 1.0]


def _fullpipe_input():
    """全管线 case 共用合成输入 (64×64): 种子随机图 (沿 _random_small 模式,
    独立种子 20260907 与其他 case 输入解耦) + 大块经典肤色补丁 (gate skin
    case 同款 (210,155,130) 的 float 归一 + 微纹理) —— skin wants 的掩码
    占比门限需肤色过阈 (portrait 门限 0.5%), 否则磨皮段直通、缺省分派在
    skin 内核上不可观测。"""
    rng = np.random.default_rng(20260907)
    img = rng.random((64, 64, 3), dtype=np.float32) * 0.30 + 0.30
    patch = np.full((32, 48, 3), (0.82, 0.61, 0.51), dtype=np.float32)
    patch += (rng.random((32, 48, 1)).astype(np.float32) - 0.5) * 0.05
    img[8:40, 8:56] = np.clip(patch, 0.0, 1.0)
    return img


def _run_full_pipeline(params: dict,
                       region_masks: dict | None = None) -> np.ndarray:
    """params 注入 DEFAULT_STAGES 全链 (api.py:103 卡集成真实路径),
    linear_cam 域喂入 (run_file 解码后同域), 返回最终 gamma 图。
    ctx.state["scene"]="portrait" 显式钉死 (skin wants 的场景门控入参,
    不依赖 analyze 步骤, 保证纯函数式确定)。
    region_masks 非空时注入 ctx.state["region_masks"] (F12/F13 消费契约,
    prompt → float32 0..1 软掩码; region_adjust case 专用, 缺省 None 时
    既有 case 行为逐位不变)。"""
    from pixo.render.core.calibration import load_dcp
    from pixo.render.pipeline.context import DOMAIN_LINEAR_CAM, StageContext
    from pixo.render.pipeline.presets import build_default_pipeline
    prof = load_dcp(_DCP_PATH)
    pipe = build_default_pipeline(params=params, prof=prof)
    ctx = StageContext("gate_fullpipe.nef", raw=_FullPipeRaw(), prof=prof,
                       config={"stages": params})
    ctx.set_image(_fullpipe_input(), DOMAIN_LINEAR_CAM)
    ctx.state["scene"] = "portrait"
    if region_masks is not None:
        ctx.state["region_masks"] = region_masks
    return np.clip(pipe.run(ctx), 0.0, 1.0).astype(np.float32)


def _region_soft_mask(h: int = 64, w: int = 64) -> np.ndarray:
    """region_adjust case 的合成软掩码 (F13 契约同款 float32 0..1):
    顶部 50% 高度全 1 → 12.5% 高度 smoothstep 过渡到 0 (禁硬边纪律,
    F12 羽化前的掩码本身即软)。确定性纯函数, 无随机。"""
    y = np.linspace(0.0, 1.0, h, dtype=np.float32).reshape(h, 1)
    t = np.clip((y - 0.5) / 0.125, 0.0, 1.0)
    smooth = t * t * (3.0 - 2.0 * t)            # smoothstep (C1 连续)
    return np.repeat(1.0 - smooth, w, axis=1).astype(np.float32)


# default_dispatch case 的 hsl bands: HSV 色相中心 + 典型偏移量, 8 带,
# **无 band 级 domain 键** —— 分组归属完全落在 Stage 级缺省 color_domain
# (hsl.py:73 band.get("domain", default_domain)), 这正是本 case 的观测点。
_DISPATCH_BANDS = [
    {"name": "red", "hue_center": 0, "width": 45.0, "hue_shift": 5.0,
     "saturation": 10.0, "luminance": 0.0},
    {"name": "orange", "hue_center": 30, "width": 45.0, "hue_shift": 0.0,
     "saturation": 6.0, "luminance": 3.0},
    {"name": "yellow", "hue_center": 60, "width": 45.0, "hue_shift": 0.0,
     "saturation": 0.0, "luminance": 0.0},
    {"name": "green", "hue_center": 120, "width": 45.0, "hue_shift": -4.0,
     "saturation": 8.0, "luminance": 0.0},
    {"name": "aqua", "hue_center": 180, "width": 45.0, "hue_shift": 0.0,
     "saturation": 0.0, "luminance": 0.0},
    {"name": "blue", "hue_center": 240, "width": 45.0, "hue_shift": 6.0,
     "saturation": 5.0, "luminance": -3.0},
    {"name": "purple", "hue_center": 270, "width": 45.0, "hue_shift": 0.0,
     "saturation": 0.0, "luminance": 0.0},
    {"name": "magenta", "hue_center": 300, "width": 45.0, "hue_shift": 0.0,
     "saturation": 4.0, "luminance": 0.0},
]


def compute(feature: str) -> np.ndarray:
    if feature == "exposure":
        return soft_highlight_rolloff(_gray_ramp() * 2.0, knee=0.9)
    if feature == "whitebalance":
        from pixo.render.core.calibration import load_dcp
        prof = load_dcp(_DCP_PATH)
        return temp_tint_to_wb(prof, 5000.0, 10.0).astype(np.float32)
    if feature == "curves":
        lut = make_base_curve_lut(eotf="srgb", gamma=2.2, n=4096)
        return apply_lut1d(_color_steps(), lut)
    if feature == "huesat":
        return apply_local_warm_sat(
            _warm_highlight(), sat_scale=2.0, spot_sat_scale=2.0,
            hue_center=22.5, hue_halfwidth=17.5, sat_min=0.05, val_min=0.6,
            coverage_max=0.0015)
    if feature == "clarity":
        return clarity(_color_steps(), strength=0.3)
    if feature == "colorcal":
        from pixo.render import _native as native
        if not native.available():
            raise RuntimeError("native DLL 缺失，无法生成 colorcal golden")
        u8 = (_color_steps() * 255.0 + 0.5).astype(np.uint8)
        lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
        params = native.PixoRenderColorCalParams(
            saturation=0.2, vibrance=0.1, hueDeg=5.0, skinProtect=0.5)
        return native.colorcal_apply_lab(lab, params).astype(np.float32)
    if feature == "calibration":
        return apply_usercal_rgb(
            _color_steps(), shadow_tint=20.0, red_hue=5.0, red_sat=15.0,
            green_hue=-4.0, green_sat=10.0, blue_hue=3.0, blue_sat=-10.0)
    if feature == "hsl":
        bands = [{"name": "red", "hue_center": 0.0, "width": 40.0,
                  "hue_shift": 5.0, "saturation": 20.0, "luminance": 0.0}]
        return hsl_adjust_rgb(_color_steps(), bands)
    if feature == "hsl_oklch":
        # OKLCh 域 8 带典型参数（设计 §2.5）：DEFAULT_BANDS_OKLCH 骨架
        # （感知色相角中心 + domain:"oklch" 戳）+ 红带 hue/sat、绿带 sat、
        # 蓝带 hue/lum 典型量（与 hsv 版 hsl case 同量级），三条参数路径
        # （hue_shift/saturation 软限幅/luminance）各至少一条被触达。
        # 输入用种子随机图而非 _color_steps()：纯色是 sRGB 色域顶点，
        # 软限幅在包络处渐近 + clip 精确拉回，色阶图上多数行会"巧合地"
        # 逐位不动，锁不住掩码形状；随机图覆盖全色相/色度平面。
        bands = [dict(b) for b in DEFAULT_BANDS_OKLCH]
        bands[0]["hue_shift"] = 5.0    # red 29°
        bands[0]["saturation"] = 20.0
        bands[3]["saturation"] = 15.0  # green 145°
        bands[5]["hue_shift"] = -8.0   # blue 264°
        bands[5]["luminance"] = 10.0
        return oklch_adjust_rgb(_random_small(), bands)
    if feature == "split_tone":
        return split_tone_rgb(_color_steps(), 30.0, 30.0, 210.0, 40.0)
    if feature == "split_tone_oklab":
        # 与 hsv 版 split_tone case 完全同参（30/30/210/40），供 reviewer
        # 在同一输入上做 hsv↔oklch 域 A/B 对照（语义对齐验证）。
        return split_tone_oklab_rgb(_color_steps(), 30.0, 30.0, 210.0, 40.0)
    if feature == "skin":
        return skin_mask(_skin_patch()).astype(np.float32)
    if feature == "skin_oklch":
        # OKLab 域肤色掩码（终审 G-1）：与 hsv 版 skin case 同一 _skin_patch()
        # 输入构造，走 skin_mask_oklab（float [0,1] 契约，显式 /255；uint8 直传
        # 在函数内同为 /255，逐位等价）。锁定 SKIN_OKLAB_* 椭圆几何：经典肤色块
        # (210,155,130) 应在核内（d≈0.85 → 全量 1），128 灰底应在核外（d≈1.43 → 0），
        # 常数漂移使 d 越过 1±band 边界即翻红。
        return skin_mask_oklab(_skin_patch() / 255.0).astype(np.float32)
    if feature == "skin_oklch_softband":
        # 软边带探针 (r12 观察窗清偿, 设计见 _skin_softband_probe): 直接捕获
        # OKLab 掩码 —— 椭圆五常数或软带宽度任一漂移, 过渡带行掩码即移动。
        # 与 skin_oklch (核内饱和锚) 互补, 关闭「改软带/半轴金样本零敏感」盲区
        # (R10 实证: 重拟合改半轴+软带, skin/skin_oklch 两 case 输出零变化)。
        return skin_mask_oklab(_skin_softband_probe()).astype(np.float32)
    if feature == "stylize":
        g = np.linspace(0.0, 1.0, 2, dtype=np.float32)
        r, gg, b = np.meshgrid(g, g, g, indexing="ij")
        lut = LUT3D(np.stack([1.0 - r, 1.0 - gg, 1.0 - b], axis=-1))
        u8 = (_color_steps() * 255.0 + 0.5).astype(np.uint8)
        return lut.apply(u8, strength=0.5).astype(np.float32)
    if feature == "refine":
        img = _random_small()
        gray = RefineStage._gray(img)
        return RefineStage._sharpen_gray(img, 0.25, gray)
    if feature == "exposure_cal_auto":
        # 正式曝光标定表敏感 case (t36 §5): 走 ExposureStage._auto_ev 完整
        # auto 决策链 —— 固定网格 med 探针 (真 DCP cam→sRGB) → 二维表
        # (src/pixo/render/target_offset.json) med 主键 + wb_B 邻域二次插值
        # (ctx.state["camera_wb"] 驱动)。平坦场亮度定标使探针 med ≈ −4.54,
        # 落在表结点密集段 (−4.632/−4.555/−4.478…, 非端点钳位); wb_B = 1.5
        # 落在 1.371~1.506 插值段 —— 换表即漂移。ev 应用与现有 exposure case
        # 同式 (线性增益 + soft_highlight_rolloff)。
        from pixo.render.core.calibration import load_dcp
        from pixo.render.pipeline.graph import DOMAIN_LINEAR_CAM, StageContext
        from pixo.render.modules.exposure import ExposureStage
        prof = load_dcp(_DCP_PATH)
        rng = np.random.default_rng(20260904)
        img = np.full((64, 64, 3), 0.04, dtype=np.float32)
        img += (rng.random((64, 64, 1)).astype(np.float32) - 0.5) * 0.004
        ctx = StageContext(
            "cal_auto.nef", raw=_CalAutoRaw(), prof=prof,
            config={"stages": {"exposure": {"target_offset": 0.0}}})
        ctx.set_image(img, DOMAIN_LINEAR_CAM)
        ctx.state["camera_wb"] = np.array([2.0, 1.0, 1.5], dtype=np.float32)
        ev = ExposureStage()._auto_ev(ctx)
        return soft_highlight_rolloff(img * np.float32(2.0 ** ev), knee=0.9)
    if feature == "warmth_cal_auto":
        # 正式 warmth 分桶曲线敏感 case (t36 §5): _load_warm_cal 读
        # configs/calibration/warmth_curve.json (缺失/非法即 raise —— 不允许
        # 静默回退制造"仍在锁表"假象) → apply_warmth 曲线分支 (优先于内置
        # 斜率模型) 得三通道增益, 乘种子线性 cam RGB (运行时同式)。
        # wb_B = 2.0 取结点 1.8027~2.3984 插值段 (增益非恒等, 对结点值敏感)。
        from pixo.render.modules.white_balance import (
            DEFAULT_WARM_CAL_FILE, _load_warm_cal, apply_warmth)
        cal = _load_warm_cal(DEFAULT_WARM_CAL_FILE)
        if cal is None or cal.get("curve") is None:
            raise RuntimeError(
                "正式 warmth 曲线缺失/非法: warmth_cal_auto case 依赖 "
                "configs/calibration/warmth_curve.json")
        wb = np.array([1.244, 1.0, 2.0], dtype=np.float32)
        gain = apply_warmth(wb, None, warmth=1.0,
                            cal={"curve": cal["curve"]})
        return _random_small() * gain
    if feature == "default_dispatch":
        # 缺省分派 case (F08, 前置修补 b) —— 双重用途之「观测点」:
        # hsl/split_tone/skin/colorcal 四 stage 带非零典型参数但 **全部不传
        # color_domain** (Stage 级无、band 级亦无), 域分派完全由
        # default_params() 决定 (现 hsv, F10 切 hsl+split_tone 后 oklch)。
        # 契约: **F10 落地后本 case 输出必须变化** (hsl bands 经
        # hsl.py:73 改道 oklch 内核 + split_tone 拨盘改道 split_tone_oklab_rgb
        # —— 这是切默认在金样本层的可观测证据, 也是「缺省分派零敏感性」
        # 盲区 (t52 §3.1/§3.2) 的关闭点); 届时基线 v2 由队长单点重生成,
        # 留 v1→v2 对比证据。若 F10 后本 case 不变 = 分派切换未生效, 阻断。
        # skin 缺省 enabled=True (skin.py:67) 且本 case 不传 enabled ——
        # 未来 skin 缺省翻转同样被本 case 观测。
        params = {
            "hsl": {"enabled": True, "smooth": 0.8,
                    "bands": json.dumps(_DISPATCH_BANDS)},
            # split_tone 拨盘与 split_tone/split_tone_oklab case 同参
            # (30/30/210/40), 供 reviewer 三方对照。
            "split_tone": {"enabled": True, "highlights_hue": 30,
                           "highlights_sat": 30, "shadows_hue": 210,
                           "shadows_sat": 40, "balance": 0.3, "strength": 0.6},
            "skin": {"strength": 0.5},
            "colorcal": {"vibrance": 0.2, "saturation": 0.1,
                         "skin_protect": 0.5},
        }
        return _run_full_pipeline(params)
    if feature == "card_portra_400":
        # 存量卡全管线 golden (F08, 前置修补 b) —— 双重用途之「A1 证明」:
        # kodak_portra_400 (F07 已显式钉四 stage color_domain:"hsv") 经
        # build_default_pipeline 全管线快照。参数单一直接来源 = 卡 JSON
        # (configs/styles/films/kodak_portra_400.json, 不复制参数) ——
        # 卡参数被误改同样在金样本层可观测。契约: **F10 切换前后本 case
        # 必须逐位不变** (卡级锚定使存量卡语义不依赖 Stage 缺省, A1
        # 「存量卡零迁移、逐位不变」在金样本层的可观测证明, 补 t52 §3.2
        # 「没有任何存量卡渲染快照级金样本」缺口)。F10 后本 case 漂移 =
        # 存量卡 A1 被破坏, 阻断切换。
        card_path = (Path(__file__).resolve().parents[3] / "configs"
                     / "styles" / "films" / "kodak_portra_400.json")
        card = json.loads(card_path.read_text(encoding="utf-8"))
        return _run_full_pipeline(card.get("params") or {})
    if feature == "region_adjust":
        # region_adjust 全管线 golden (F15, M1 验收) —— enabled=True +
        # 合成软掩码 (F13 契约: prompt → float32 0..1) 经 _run_full_pipeline
        # 真实 DEFAULT_STAGES 链序 (skin 后 stylize 前) 快照。双内核同图
        # 触达: sky 区域 exposure=-0.6 (gamma 域增益 2^(-0.6/2.2)) +
        # saturation=-0.15 (HSV S 缩放)。负向选型避开两处 clip 分量
        # (V≤1 与 S≤1 的饱和段会让"参数→像素"映射变平, 削弱对内核常数
        # 的敏感度)。羽化 (sigma=clip(长边/512,1,8)) 与软混合
        # out = out*(1-m) + adjusted*m 在快照内可观测。
        # 契约: region_adjust 内核常数/羽化宽度/enabled 耦合任一漂移,
        # 本 case 即翻红; ctx.state["region_masks"] 是该 stage 的唯一注入面
        # (wants 门控: 掩码缺失即静默直通)。
        params = {
            "region_adjust": {"enabled": True,
                              "regions": {"sky": {"exposure": -0.6,
                                                  "saturation": -0.15}}},
        }
        return _run_full_pipeline(params, region_masks={
            "sky": _region_soft_mask(),
        })
    raise KeyError(f"未知 golden feature: {feature}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
