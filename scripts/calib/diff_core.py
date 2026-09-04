"""可微渲染代理 (surrogate) —— torch 复刻中性渲染链 (阶段二 M-D1, 设计 §1)。

链路 (逐像素色彩链, 对齐 Renderer.render_preview_full 中性参数口径):
    decode(cfa_half/native 回退, 复用 pixo) → INTER_AREA 缩放
    → exposure(ev 增益 + tanh 高光软滚降)
    → whitebalance(camera_wb × warmth 增益 × cam→线性sRGB 矩阵 + 饱和高光中性化)
    → [RP-CCM 并联, 可选, 线性 sRGB 域]
    → tone(brightness 预乘 + sRGB EOTF LUT 线性插值)
    → colorcal 中性快速路径(CCT 分桶曲线 → u8 Lab tint, L 带混合)
    → gamma 量化 u8

θ (全部 nn.Parameter, 见 SurrogateParams; 设计 §0):
    warmth_gains    (K,3) warmth 曲线结点**等效**增益 (warmth=0.9 标量已折入,
                    对分段线性插值仿射可交换, 与真实链逐位等价, 见 load_warmth_curve)
    ev              ()    曝光 EV (中性 = 0)
    brightness      ()    tone 显示亮度 EV (中性 = 0.25, tone Stage 默认)
    neutral_a/b     (Kb,7) colorcal 中性轴 a/b 曲线 (CCT 分桶, 即
                    resources/camera_profiles/z5ii_neutral_trim.json 的 by_cct;
                    单桶/无标定退化为单行 fixed)
    rp_matrix       (3,6) RP-CCM 根多项式系数 (默认恒等, use_rp_ccm=False 不进链)

torch 只进 scripts/ (隔离纪律同 vision 栈); src/pixo/render 零改动零依赖。

可微策略 —— "前向逐位复刻, 反向平滑近似" (量化感知代理 / STE):
  真实链有三类不可微环节, 处理各不同 (与设计 §1 "线性插值近似 + soft-clip"
  的对应关系):
  1. tone LUT: 真实链是 16384 级**最近邻**查表 (native PixoRenderToneApplyLut1D
     实测与 core.curves.apply_lut1d_fast 逐位一致); 代理按设计用**线性插值**
     (apply_lut1d 同式), 前向偏差 ≤ 半格 (深阴影 ΔE ~0.03-0.12, 中高调 <0.01)
     —— 这层代价正是保真门要量化的对象。
  2. clip: 真实链硬 clip (WB 后负值钳 0 / tone 与 colorcal 出口 [0,1] / u8
     量化)。代理前向**硬 clip** (与真实链逐位一致, 保真门因此可过), 反向 tanh
     软梯度 (soft-clip(tanh) 语义落在反向, 见 soft_clip)。设计原文的"前向
     soft-clip 近似"会使高光/越域像素 ΔE 达数个单位, 保真门 (median ≤0.05)
     必然失败 —— 故前向必须保真, 近似移入反向。
  3. colorcal tint: 真实链把 (a,b) 偏移 clip→u8 截断后过 cv2 u8 Lab2RGB,
     tint 是**整数** (对 θ 分段常数, 精确梯度恒 0)。代理前向直接调同一 cv2
     路径 (逐位一致), 反向走 float Lab→RGB 平滑雅可比 (detached 修正技巧,
     见 PhotoSurrogate._neutral_tints)。cv2 u8 输出的软浮点摆动 (实测 ≤0.36
     RGB 单位) 无法解析复刻, 直调 cv2 是唯一逐位手段。

静态冻结 (ChainStatic): θ 无关的量 (解码图 / 饱和掩码 / colorcal 权重与 L
混合索引 / 基 tint / CCT 分桶选择) 在 θ0 构建期用与真实链**相同的 cv2/numpy
调用**计算一次后冻结 —— 保真门在 θ0 下成立; 优化期 (θ≠θ0) 这些低频量不随 θ
变化, 是标准近似 (BN 冻结统计同类), θ 梯度经其余路径照常回传。

保真门 (设计 §1, 硬前置): 同输入同 θ 下 surrogate vs render_preview_full 的
ΔE2000 median ≤ 0.05 / p95 ≤ 0.3 (校准抽样 ≥10 张, 语料窗口口径 [0.01,0.90]
线性域, 复用 fit_rp_ccm.sample_linear_pairs)。真实链中性参数下 clarity /
refine / skin 三个 **θ 无关的空间观感 stage** 默认开启 (实测对逐像素链贡献
ΔE median ~2.1, 门不可达), 保真门对照口径将其显式关闭 (见
surrogate_fidelity.py GATE_PARAMS) —— 与设计 §1 代理链 (逐像素色彩链) 自洽。

用法 (单张):
    sur = PhotoSurrogate.build(raw_path, dcp_path, long_edge=512)
    gamma = sur()                 # f64 gamma [0,1] (θ 相关, 可 backward)
    u8 = sur.quantize(gamma)      # 与 render_preview_full 同式量化
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as TF
from torch import nn

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from pixo.render.core.calibration import BRADFORD_D50_TO_D65, XYZ_D65_TO_SRGB, \
    load_dcp
from pixo.render.core.color import D50_XY, illuminant_cct
from pixo.render.core.curves import make_base_curve_lut
from pixo.render.core.io import camera_neutral_wb, decode_cfa_half

__all__ = [
    "ChainStatic", "SurrogateParams", "PhotoSurrogate", "DcpChainConsts",
    "NeutralTrimConsts", "WarmthCurveConsts", "NeutralSelect",
    "RP_DEGREE2_TERMS", "cam_to_linear_srgb_matrix_t", "neutral_to_xy_t",
    "soft_clip", "quantize_u8", "tone_lut_interp", "load_warmth_curve",
    "load_neutral_trim", "rp_features_t", "apply_rp_ccm_t",
    "TONE_BRIGHTNESS_NEUTRAL", "TONE_LUT_N", "EXPOSURE_MAX_EV",
]

# tone Stage 中性默认 (modules.tone_map.default_params) —— θ0 初值来源;
# 阶段二标定只动 EV/亮度/曲线/系数, eotf 基座不变。
TONE_BRIGHTNESS_NEUTRAL = 0.25
TONE_LUT_N = 16384           # modules.tone_map._N_FAST
EXPOSURE_MAX_EV = 2.5        # modules.exposure 默认 max_ev (真实链 ev 钳界)

# cv2 u8 Lab (L 0..255, a/b 中心 128) —— colorcal 中性快速路径的亮度带中心
# (modules.color_cal._NEUTRAL_CENTERS) 与其平台/高斯常数。
NEUTRAL_L_CENTERS_U8 = np.array([8, 32, 72, 128, 184, 224, 248], dtype=np.float32)
NEUTRAL_PLATEAU = 12.0
NEUTRAL_SIGMA = 14.0

RP_DEGREE2_TERMS = ("r", "g", "b", "sqrt(rg)", "sqrt(rb)", "sqrt(gb)")

# cv2 float Lab (L∈[0,100], a/b 中心 0) 的 sRGB(D65) 正逆矩阵 —— 正向与
# eval_rp_ccm_ab.linear_srgb_to_lab 同一方阵 (行=XYZ 基); 实测与 cv2 float
# cvtColor 一致到 ~1e-3 RGB/255 单位 (tests/unit/test_diff_core.py)。
_SRGB_TO_XYZ_D65_F = np.array([[0.4124564, 0.3575761, 0.1804375],
                               [0.2126729, 0.7151522, 0.0721750],
                               [0.0193339, 0.1191920, 0.9503041]],
                              dtype=np.float64)
_XYZ_D65_TO_SRGB_F = np.linalg.inv(_SRGB_TO_XYZ_D65_F)


# ---------------------------------------------------------------------------
# WB 矩阵链 (torch, 对齐 core.color.cam_to_linear_srgb_matrix)
# ---------------------------------------------------------------------------

def _xyz_to_xy_t(xyz: torch.Tensor) -> torch.Tensor:
    s = xyz.sum()
    safe = torch.where(s > 0, xyz / s, torch.tensor(1.0 / 3.0, dtype=xyz.dtype))
    return safe[:2]


def wb_to_neutral_t(wb: torch.Tensor) -> torch.Tensor:
    """对齐 core.color.wb_to_neutral (wb 归一 G=1 → 中性向量, f64)。"""
    wb = torch.where(wb[1:2] > 0, wb / wb[1:2], torch.ones_like(wb))
    neutral = 1.0 / torch.clamp(wb, min=1e-9)
    return neutral / neutral[1:2]


def _mccamy_t(xy: torch.Tensor) -> torch.Tensor:
    """CIE xy → CCT (McCamy 三次近似, 对齐 core.color.xy_to_cct)。"""
    n = (xy[0] - 0.3320) / (xy[1] - 0.1858)
    return -449.0 * n ** 3 + 3525.0 * n ** 2 - 6823.3 * n + 5520.33


def _bradford_adapt_t(src_xy: torch.Tensor, dst_xy, mb_inv: torch.Tensor) -> torch.Tensor:
    """Bradford 色适应 (对齐 core.color.bradford_adapt; dst 白点为常量)。"""
    one = torch.tensor(1.0, dtype=torch.float64)
    xyz_src = torch.stack([src_xy[0] / src_xy[1], one,
                           (one - src_xy[0] - src_xy[1]) / src_xy[1]])
    xyz_dst = torch.tensor([dst_xy[0] / dst_xy[1], 1.0,
                            (1.0 - dst_xy[0] - dst_xy[1]) / dst_xy[1]],
                           dtype=torch.float64)
    mb = torch.tensor([[0.8951, 0.2664, -0.1614],
                       [-0.7502, 1.7135, 0.0367],
                       [0.0389, -0.0685, 1.0296]], dtype=torch.float64)
    w1 = torch.clamp(mb @ xyz_src, min=0.0)
    w2 = torch.clamp(mb @ xyz_dst, min=0.0)
    a = torch.diag(w2 / torch.where(w1 > 0, w1, torch.ones_like(w1)))
    return mb_inv @ a @ mb


_MB_INV = torch.linalg.inv(torch.tensor([[0.8951, 0.2664, -0.1614],
                                         [-0.7502, 1.7135, 0.0367],
                                         [0.0389, -0.0685, 1.0296]],
                                        dtype=torch.float64))


@dataclass(frozen=True)
class DcpChainConsts:
    """WB 矩阵链的 DCP 常量 (构建期从 DcpProfile 提取, 不可变)。"""

    cm1: np.ndarray            # (3,3) ColorMatrix1
    cm2: np.ndarray | None     # ColorMatrix2 (与 cm1 全同时置 None → 恒用 cm1)
    cc1: np.ndarray            # CameraCalibration1 (缺省单位阵)
    cc2: np.ndarray | None
    t1: float                  # 校准照明体 1 色温 K (core.color._calibration_temperatures)
    t2: float
    name: str = ""

    @classmethod
    def from_profile(cls, prof) -> "DcpChainConsts":
        def _m3(v):
            return None if v is None else np.asarray(v, dtype=np.float64).reshape(3, 3)

        cm1 = _m3(getattr(prof, "color_matrix1", None))
        if cm1 is None:
            raise ValueError("DCP 缺少 ColorMatrix1, 代理链无法建立 WB 矩阵")
        cm2 = _m3(getattr(prof, "color_matrix2", None))
        if cm2 is not None and np.allclose(cm1, cm2):
            cm2 = None
        cc1 = _m3(getattr(prof, "camera_calibration1", None))
        if cc1 is None:
            cc1 = np.eye(3)
        cc2 = _m3(getattr(prof, "camera_calibration2", None))
        if cc2 is not None and np.allclose(cc1, cc2):
            cc2 = None
        ill1 = int(getattr(prof, "calibration_illuminant1", None) or 17)
        ill2 = int(getattr(prof, "calibration_illuminant2", None) or 21)
        t1 = illuminant_cct(ill1) or 2850.0
        t2 = illuminant_cct(ill2) or 6500.0
        if t1 == t2:
            t2 = t1 + 1.0
        return cls(cm1=cm1, cm2=cm2, cc1=cc1, cc2=cc2, t1=float(t1), t2=float(t2),
                   name=str(getattr(prof, "name", "")))


def _blend_1_over_t(m1: torch.Tensor, m2: torch.Tensor | None, cct: torch.Tensor,
                    t1: float, t2: float) -> torch.Tensor:
    """对齐 core.color._interp_1_over_t 的插值式 (m2 缺失/全同由常量侧保证)。"""
    blend = ((1.0 / cct - 1.0 / t1) / (1.0 / t2 - 1.0 / t1)).clamp(0.0, 1.0)
    return (1.0 - blend) * m1 + blend * m2


def neutral_to_xy_t(neutral: torch.Tensor, dc: DcpChainConsts) -> torch.Tensor:
    """相机中性 RGB → 场景白点 xy (对齐 core.color.neutral_to_xy 不动点迭代;
    收敛判据在 detached 值上判断 —— 中断时机与原实现一致, 梯度只经已执行
    分支回传)。"""
    dt = torch.float64
    cm1 = torch.tensor(dc.cm1, dtype=dt)
    cm2 = torch.tensor(dc.cm2, dtype=dt) if dc.cm2 is not None else None
    last = torch.tensor(D50_XY, dtype=dt)
    nxt = last.clone()
    for _ in range(30):
        cm = _blend_1_over_t(cm1, cm2, _mccamy_t(last), dc.t1, dc.t2) \
            if cm2 is not None else cm1
        nxt = _xyz_to_xy_t(torch.linalg.inv(cm) @ neutral)
        with torch.no_grad():
            if float((nxt - last).abs().sum()) < 1e-7:
                break
        last = nxt
    return nxt


def cam_to_linear_srgb_matrix_t(wb: torch.Tensor, dc: DcpChainConsts) -> torch.Tensor:
    """WB 后相机 RGB → 线性 sRGB(D65) 3×3 (torch, θ 经 wb 可微)。

    与 core.color.cam_to_linear_srgb_matrix 逐式对应:
      XYZ65→sRGB @ Bradford(D50→D65) @ Bradford(场景白→D50)
      @ inv(CM_interp) @ inv(CC_interp) @ diag(1/wb)
    """
    neutral = wb_to_neutral_t(wb)
    scene_xy = neutral_to_xy_t(neutral, dc)
    cct = _mccamy_t(scene_xy)

    dt = torch.float64
    cm1 = torch.tensor(dc.cm1, dtype=dt)
    cm2 = torch.tensor(dc.cm2, dtype=dt) if dc.cm2 is not None else None
    cc1 = torch.tensor(dc.cc1, dtype=dt)
    cc2 = torch.tensor(dc.cc2, dtype=dt) if dc.cc2 is not None else None
    cm = _blend_1_over_t(cm1, cm2, cct, dc.t1, dc.t2) if cm2 is not None else cm1
    cc = _blend_1_over_t(cc1, cc2, cct, dc.t1, dc.t2) if cc2 is not None else cc1
    cam_to_xyz_scene = torch.linalg.inv(cm) @ torch.linalg.inv(cc)
    bradford_scene = _bradford_adapt_t(scene_xy, D50_XY, _MB_INV)
    m_xyz = bradford_scene @ cam_to_xyz_scene @ torch.diag(
        1.0 / torch.clamp(wb, min=1e-9))
    return (torch.tensor(np.asarray(XYZ_D65_TO_SRGB, dtype=np.float64), dtype=dt)
            @ torch.tensor(np.asarray(BRADFORD_D50_TO_D65, dtype=np.float64), dtype=dt)
            @ m_xyz)


def cct_k_t(wb: torch.Tensor, dc: DcpChainConsts) -> torch.Tensor:
    """白平衡 Stage 的 cct_k (= cct_from_wb, 钳 [1000,50000]; pre-warmth wb,
    静态量 —— 仅 θ0 构建期以 detached 值调用)。"""
    xy = neutral_to_xy_t(wb_to_neutral_t(wb), dc)
    return _mccamy_t(xy).clamp(1000.0, 50000.0)


# ---------------------------------------------------------------------------
# 可微原语: clip (前向硬/反向 tanh 软) 与 tone LUT (线性插值)
# ---------------------------------------------------------------------------

def soft_clip(x: torch.Tensor, lo: float = 0.0, hi: float = 1.0,
              tau: float = 0.05, outside_pass: float = 0.2) -> torch.Tensor:
    """前向硬 clip (与真实链逐位一致), 反向 tanh 软梯度 (soft-clip 在反向)。

    反向权重 m(v) = outside_pass + (1-outside_pass)·σ(v/tau),
    v = min(x-lo, hi-x) (带符号余量): 界内 m→1, 界外 m→outside_pass ——
    高光/越域像素保留衰减梯度, 优化器仍可将其拉回。
    """
    class _F(torch.autograd.Function):
        @staticmethod
        def forward(ctx, x):
            ctx.save_for_backward(x)
            return x.clamp(lo, hi)

        @staticmethod
        def backward(ctx, g):
            (x,) = ctx.saved_tensors
            v = torch.minimum(x - lo, hi - x)
            m = outside_pass + (1.0 - outside_pass) * 0.5 * (1.0 + torch.tanh(v / tau))
            return g * m
    return _F.apply(x)


def quantize_u8(gamma: torch.Tensor) -> torch.Tensor:
    """gamma [0,1] → u8 代码 (0..255), 与 pipeline.runner.finalize_gamma_output
    的 (clip·255+0.5) 截断式逐位一致。"""
    return torch.floor(soft_clip(gamma, 0.0, 1.0) * 255.0 + 0.5).long()


def tone_lut_interp(x: torch.Tensor, lut: torch.Tensor) -> torch.Tensor:
    """1D LUT 线性插值 (core.curves.apply_lut1d 同式; 真实链为最近邻 native
    内核 —— ≤半格偏差由保真门量化, 见模块 docstring §1)。"""
    n = lut.shape[0] - 1
    pos = torch.clamp(x, 0.0, 1.0) * n
    i0 = torch.floor(pos)
    frac = pos - i0
    i0 = i0.long()
    i1 = torch.minimum(i0 + 1, torch.tensor(n, dtype=i0.dtype))
    return lut[i0] * (1.0 - frac) + lut[i1] * frac


def exposure_rolloff_t(x: torch.Tensor, knee: float = 0.9) -> torch.Tensor:
    """高光软滚降 (对齐 modules.exposure.soft_highlight_rolloff / native 内核
    —— tanh 式, 前向即可微, 无需近似)。"""
    if knee >= 1.0 or knee < 0.0:
        return x
    return torch.minimum(
        torch.where(x <= knee, x,
                    knee + (1.0 - knee) * torch.tanh((x - knee) / (1.0 - knee))),
        torch.tensor(1.0, dtype=x.dtype))


# ---------------------------------------------------------------------------
# warmth 曲线 / 中性分桶曲线 的配置读取 (θ0 初值与常量)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WarmthCurveConsts:
    """warmth 分桶曲线常量 (configs/calibration/warmth_curve.json)。"""

    abscissae: np.ndarray     # (K,) wb_B 结点 (冻结, 不入 θ)
    gains: np.ndarray         # (K,3) 结点**等效**增益 (θ0; warmth 标量已折入)


def load_warmth_curve(path: str | Path, warmth: float = 0.9) -> WarmthCurveConsts:
    """读 warmth_curve.json; 等效增益 = 1 + warmth·(knot−1) 折入 —— 对齐
    apply_warmth 曲线分支 gain = 1+w·(np.interp(b)−1): 插值对仿射变换可交换,
    结点折算后与真实链逐位等价。"""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    knots = np.asarray(doc["knots"], dtype=np.float64)
    if knots.ndim != 2 or knots.shape[1] != 4 or knots.shape[0] < 2:
        raise ValueError(f"warmth_curve.knots 需 (≥2,4), 实际 {knots.shape}")
    if not np.all(np.diff(knots[:, 0]) > 0):
        raise ValueError("warmth_curve 结点 wb_B 必须严格递增")
    gains_eff = 1.0 + float(warmth) * (knots[:, 1:] - 1.0)
    return WarmthCurveConsts(abscissae=knots[:, 0].copy(), gains=gains_eff)


@dataclass(frozen=True)
class NeutralTrimConsts:
    """每机中性轴分桶标定 (resources/camera_profiles/z5ii_neutral_trim.json)。

    buckets: [(cct_center, a7|None, b7|None), ...] 按 cct 升序 (对齐
    core.calibration.camera_look_curves 的 by_cct 语义); default 为 by_cct
    缺失/全空时的回退曲线。
    """

    buckets: tuple = field(default_factory=tuple)
    default_a: np.ndarray | None = None
    default_b: np.ndarray | None = None

    @property
    def n_buckets(self) -> int:
        return len(self.buckets)

    def centers(self) -> np.ndarray:
        return np.array([c for c, _, _ in self.buckets], dtype=np.float64)


def load_neutral_trim(path: str | Path) -> NeutralTrimConsts:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))

    def _curve(entry, key):
        v = entry.get(key) if isinstance(entry, dict) else None
        if not v:
            return None
        arr = np.asarray(v, dtype=np.float64).reshape(-1)
        return arr if arr.size == 7 else None   # native 侧固定读 7 点

    rows = []
    for item in doc.get("by_cct") or []:
        try:
            center = float(item[0])
            entry = item[1] if isinstance(item[1], dict) else {}
        except (TypeError, IndexError, ValueError):
            continue
        a, b = _curve(entry, "neutral_a_curve"), _curve(entry, "neutral_b_curve")
        if a is None and b is None:
            continue
        rows.append((center, a, b))
    rows.sort(key=lambda r: r[0])
    dflt = doc.get("default") if isinstance(doc.get("default"), dict) else {}
    return NeutralTrimConsts(buckets=tuple(rows),
                             default_a=_curve(dflt, "neutral_a_curve"),
                             default_b=_curve(dflt, "neutral_b_curve"))


def _lerp_curve_np(c1, c2, t: float):
    """对齐 core.calibration._lerp_curve (单侧缺失回退另一侧, 不混合)。"""
    if c1 is None and c2 is None:
        return None
    if c1 is None:
        return np.asarray(c2, dtype=np.float64).copy()
    if c2 is None:
        return np.asarray(c1, dtype=np.float64).copy()
    return (1.0 - t) * np.asarray(c1, dtype=np.float64) + t * np.asarray(c2, dtype=np.float64)


@dataclass(frozen=True)
class NeutralSelect:
    """单照片的中性曲线来源 (θ0 CCT 定, 冻结):

    mode="buckets": 曲线 = (1−t_x)·bucket[i] + t_x·bucket[i+1], a/b 轴各有
    混合参数 t_a/t_b —— 单侧曲线缺失时该轴 t 钳到有效侧 (对齐
    _lerp_curve_np 回退语义); mode="fixed": 直接用给定曲线 (default 回退 /
    无标定 → None → 前向按全零曲线处理, colorcal 等效直通)。
    """

    mode: str
    i: int = 0
    j: int = 0
    t_a: float = 0.0
    t_b: float = 0.0
    fixed_a: np.ndarray | None = None
    fixed_b: np.ndarray | None = None


def select_neutral_curves(trim: NeutralTrimConsts | None,
                          cct: float) -> NeutralSelect:
    """按 CCT 选桶 (对齐 _interp_cct 的区间选择与桶外钳位; cct 已按
    cct_from_wb 口径钳 [1000,50000], 由调用方完成)。"""
    if trim is None:
        return NeutralSelect("fixed")
    if trim.n_buckets == 0:
        return NeutralSelect("fixed", fixed_a=trim.default_a, fixed_b=trim.default_b)
    if trim.n_buckets == 1:
        _, a, b = trim.buckets[0]
        return NeutralSelect("fixed", fixed_a=a, fixed_b=b)
    centers = trim.centers()
    if cct <= centers[0]:
        i, t = 0, 0.0
    elif cct >= centers[-1]:
        i, t = len(centers) - 2, 1.0
    else:
        i = int(np.searchsorted(centers, cct)) - 1
        i = max(0, min(i, len(centers) - 2))
        span = centers[i + 1] - centers[i]
        t = (cct - centers[i]) / span if span > 0 else 0.0
    _, a_i, b_i = trim.buckets[i]
    _, a_j, b_j = trim.buckets[i + 1]
    t_a = 1.0 if a_i is None else (0.0 if a_j is None else t)
    t_b = 1.0 if b_i is None else (0.0 if b_j is None else t)
    return NeutralSelect("buckets", i=i, j=i + 1, t_a=t_a, t_b=t_b)


# ---------------------------------------------------------------------------
# RP-CCM (torch, 对齐 core.rp_ccm.rp_features / apply_rp_ccm)
# ---------------------------------------------------------------------------

def _safe_sqrt(x: torch.Tensor) -> torch.Tensor:
    """sqrt(clip(x,0)) 前向逐位同 rp_features; 反向在零点置 0 (d√x/dx=0.5/√x
    在 x→0 发散, 会把 WB clip 到 0 的像素梯度污染成 NaN)。"""
    class _F(torch.autograd.Function):
        @staticmethod
        def forward(ctx, x):
            s = torch.sqrt(torch.clamp(x, min=0.0))
            ctx.save_for_backward(s)
            return s

        @staticmethod
        def backward(ctx, g):
            (s,) = ctx.saved_tensors
            return g * torch.where(s > 0, 0.5 / s, torch.zeros_like(s))
    return _F.apply(x)


def rp_features_t(linear_rgb: torch.Tensor, degree: int = 2) -> torch.Tensor:
    """线性 RGB (...,3) → 根多项式特征 (负输入 clip 0; degree=2:
    r,g,b,√rg,√rb,√gb) —— 对齐 core.rp_ccm.rp_features (√ 项走安全反向)。"""
    rgb = torch.clamp(linear_rgb, min=0.0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    if degree == 1:
        return torch.stack([r, g, b], dim=-1)
    return torch.stack([r, g, b, _safe_sqrt(r * g), _safe_sqrt(r * b),
                        _safe_sqrt(g * b)], dim=-1)


def apply_rp_ccm_t(linear_rgb: torch.Tensor, matrix: torch.Tensor,
                   degree: int = 2) -> torch.Tensor:
    """线性 sRGB 经 RP-CCM (对齐 apply_rp_ccm: 出口 clip [0,1]; 恒等快路径由
    调用方以 use_rp_ccm=False 表达, 不进链)。"""
    feats = rp_features_t(linear_rgb, degree)
    return soft_clip(feats @ matrix.T, 0.0, 1.0)


# ---------------------------------------------------------------------------
# 静态量 (θ 无关, 构建期冻结) 与单照片代理模块
# ---------------------------------------------------------------------------

@dataclass
class ChainStatic:
    """单照片 θ 无关静态量 (全部由与真实链相同的 cv2/numpy 调用构建)。"""

    img_cam: np.ndarray          # (H,W,3) f64 线性相机 RGB (decode+resize 后)
    camera_wb: np.ndarray        # (3,) f64 (f32 存储值, as-shot, G=1)
    wb_key_b: float              # warmth 插值键 b = wb_B/wb_G (真实链同式)
    cct_k: float                 # 白平衡 Stage 的 cct_k (pre-warmth, 钳 [1e3,5e4])
    sat_white: tuple[np.ndarray, np.ndarray] | None  # 饱和近中性像素索引 (静态)
    # colorcal 中性快速路径静态量 (θ0 gamma 图上按 _apply_neutral_fast 复刻):
    cc_w_up: np.ndarray | None   # (H,W,1) 低频平台权重 (INTER_LINEAR 上采样后)
    cc_li: np.ndarray | None     # (h2,w2) L 带下标
    cc_t: np.ndarray | None      # (h2,w2) L 带内混合比例
    cc_base_rgb: np.ndarray | None  # (7,3) 基 tint = cv2 u8 Lab2RGB(Lc,128,128)
    neutral_sel: NeutralSelect | None = None


class SurrogateParams(nn.Module):
    """θ 参数集 (设计 §0; 全部 nn.Parameter, 优化器可直接接管)。"""

    def __init__(self, warmth: WarmthCurveConsts | None,
                 trim: NeutralTrimConsts | None,
                 sel: NeutralSelect,
                 ev: float = 0.0,
                 brightness: float = TONE_BRIGHTNESS_NEUTRAL,
                 rp_matrix: np.ndarray | None = None,
                 use_rp_ccm: bool = False):
        super().__init__()
        K = 0 if warmth is None else len(warmth.abscissae)
        g0 = np.zeros((1, 3)) if K == 0 else warmth.gains
        self.warmth_gains = nn.Parameter(torch.tensor(g0, dtype=torch.float64))
        xs = np.zeros(1) if K == 0 else warmth.abscissae
        self.register_buffer("warmth_abscissae",
                             torch.tensor(xs, dtype=torch.float64))
        self.ev = nn.Parameter(torch.tensor(float(ev), dtype=torch.float64))
        self.brightness = nn.Parameter(torch.tensor(float(brightness),
                                                    dtype=torch.float64))

        # 中性曲线: buckets 模式 → θ = 分桶曲线值 (缺失桶行以 0 占位, 该侧
        # 混合权重已在 NeutralSelect 钳到有效侧, 占位行不进前向);
        # fixed 模式 → 单行 θ (无标定 → 全零, 等效 colorcal 直通)。
        if sel.mode == "buckets" and trim is not None:
            kb = trim.n_buckets
            a0 = np.zeros((kb, 7))
            b0 = np.zeros((kb, 7))
            for k, (_, a, b) in enumerate(trim.buckets):
                if a is not None:
                    a0[k] = a
                if b is not None:
                    b0[k] = b
        else:
            a0 = (sel.fixed_a if sel.fixed_a is not None else np.zeros(7)).reshape(1, 7)
            b0 = (sel.fixed_b if sel.fixed_b is not None else np.zeros(7)).reshape(1, 7)
        self.neutral_a = nn.Parameter(torch.tensor(a0, dtype=torch.float64))
        self.neutral_b = nn.Parameter(torch.tensor(b0, dtype=torch.float64))

        self.use_rp_ccm = bool(use_rp_ccm)
        rp0 = np.eye(3, 6) if rp_matrix is None else np.asarray(rp_matrix, np.float64)
        self.rp_matrix = nn.Parameter(torch.tensor(rp0, dtype=torch.float64))

    def neutral_curves_for(self, sel: NeutralSelect):
        """该照片实际生效的 7 点曲线 (θ 相关; 冻结的 CCT 选择/回退权重)。"""
        if sel.mode == "buckets":
            a = (1.0 - sel.t_a) * self.neutral_a[sel.i] + sel.t_a * self.neutral_a[sel.j]
            b = (1.0 - sel.t_b) * self.neutral_b[sel.i] + sel.t_b * self.neutral_b[sel.j]
            return a, b
        return self.neutral_a[0], self.neutral_b[0]


class PhotoSurrogate(nn.Module):
    """单照片可微代理: 静态量 (ChainStatic) + θ (SurrogateParams)。

    build() 流程:
      1. 复用 pixo decode (cfa_half, 失败回退 rawpy AHD half) + INTER_AREA
         缩放 —— 与 api.render_preview_full 解码段逐行同式;
      2. 饱和掩码/高光中性化索引 + cct_k + CCT 分桶选择 (静态);
      3. θ0 下无梯度跑 exposure→WB→[RP-CCM]→tone 得 gamma0, 在其 u8 图上以
         _apply_neutral_fast 原式 (cv2) 复刻 colorcal 静态权重/L 混合索引,
         并取基 tint (cv2 u8)。
    """

    def __init__(self, static: ChainStatic, params: SurrogateParams,
                 dc: DcpChainConsts, tone_lut: np.ndarray,
                 warmth: WarmthCurveConsts | None):
        super().__init__()
        self.static = static
        self.params = params
        self.sel = static.neutral_sel or NeutralSelect("fixed")
        self.dc = dc
        self.warmth = warmth
        self.register_buffer("tone_lut",
                             torch.tensor(np.asarray(tone_lut, dtype=np.float64)))

    # -- 前向链路 (torch) -------------------------------------------------

    def _exposure_wb_tone(self) -> torch.Tensor:
        """decode 图 → tone 出口 (clip 前); exposure→WB→[RP-CCM]→tone。"""
        st = self.static
        p = self.params
        img = torch.tensor(st.img_cam, dtype=torch.float64)
        ev = torch.clamp(p.ev, -EXPOSURE_MAX_EV, EXPOSURE_MAX_EV)
        x = img * torch.exp2(ev)
        x = exposure_rolloff_t(x, knee=0.9)

        wb0 = torch.tensor(st.camera_wb, dtype=torch.float64)
        xs = p.warmth_abscissae
        if self.warmth is not None and xs.numel() >= 2:
            b_key = torch.tensor(st.wb_key_b, dtype=torch.float64)
            k = torch.clamp(torch.searchsorted(xs, b_key), 1, len(xs) - 1)
            t = torch.clamp((b_key - xs[k - 1]) / (xs[k] - xs[k - 1]), 0.0, 1.0)
            gain = p.warmth_gains[k - 1] * (1.0 - t) + p.warmth_gains[k] * t
            wb = wb0 * gain
        else:
            wb = wb0
        m = cam_to_linear_srgb_matrix_t(wb, self.dc)
        cam_w = x * wb          # 白平衡输入 = exposure 输出 (真实链 ctx.image)
        if st.sat_white is not None:
            rows, cols = st.sat_white
            lum = cam_w[rows, cols, :].max(dim=1).values
            cam_w = cam_w.clone()
            cam_w[rows, cols, :] = lum[:, None]
        rgb = (cam_w.reshape(-1, 3) @ m.T).reshape(cam_w.shape)
        rgb = soft_clip(rgb, 0.0, float("inf"))      # 真实链: clip(rgb, 0, None)

        if p.use_rp_ccm:
            rgb = apply_rp_ccm_t(rgb, p.rp_matrix, degree=2)

        y = tone_lut_interp(rgb * torch.exp2(p.brightness), self.tone_lut)
        return y

    def _neutral_tints(self) -> torch.Tensor:
        """(7,3) tint: 前向 = cv2 u8 逐位 (真实链), 反向 = float 平滑雅可比。"""
        a_curve, b_curve = self.params.neutral_curves_for(self.sel)
        smooth = _lab_offset_to_rgb_smooth(a_curve, b_curve)      # 可微代理
        with torch.no_grad():
            exact = torch.tensor(_cv2_neutral_tints(
                a_curve.detach().cpu().numpy(), b_curve.detach().cpu().numpy(),
                base=self.static.cc_base_rgb), dtype=torch.float64)
        return smooth + (exact - smooth).detach()    # 前向=exact, 反向=∂smooth

    def forward(self) -> torch.Tensor:
        """θ → gamma [0,1] f64 (tone+colorcal 完成, 量化前; 可 backward)。"""
        st = self.static
        gamma = soft_clip(self._exposure_wb_tone(), 0.0, 1.0)     # tone 出口 clip
        if st.cc_w_up is None:
            return gamma
        tints = self._neutral_tints()                             # (7,3)
        li = torch.tensor(st.cc_li, dtype=torch.long)
        t = torch.tensor(st.cc_t, dtype=torch.float64)[..., None]
        tint_s = tints[li] * (1.0 - t) + tints[li + 1] * t        # (h2,w2,3)
        tint_up = TF.interpolate(tint_s.permute(2, 0, 1)[None],
                                 size=st.cc_w_up.shape[:2],
                                 mode="bilinear", align_corners=False
                                 )[0].permute(1, 2, 0)
        w_up = torch.tensor(st.cc_w_up, dtype=torch.float64)
        return soft_clip(gamma + w_up * tint_up / 255.0, 0.0, 1.0)

    def quantize(self, gamma: torch.Tensor) -> torch.Tensor:
        return quantize_u8(gamma)

    # -- 构建 -------------------------------------------------------------

    @classmethod
    def build(cls, raw_path: str | Path, dcp_path: str | Path,
              long_edge: int = 512,
              warmth_curve_path: str | Path | None = None,
              neutral_trim_path: str | Path | None = None,
              warmth: float = 0.9,
              use_rp_ccm: bool = False,
              rp_matrix: np.ndarray | None = None) -> "PhotoSurrogate":
        warmth_curve_path = warmth_curve_path or (
            _REPO / "configs" / "calibration" / "warmth_curve.json")
        neutral_trim_path = neutral_trim_path or (
            _REPO / "resources" / "camera_profiles" / "z5ii_neutral_trim.json")
        # 真实链缺 warmth 标定文件会回退内置斜率模型 (另一条数值路径) ——
        # 代理只复刻曲线分支, 文件缺失直接报错而非静默失配。
        if not Path(warmth_curve_path).is_file():
            raise FileNotFoundError(f"warmth 标定文件缺失: {warmth_curve_path}")

        prof = load_dcp(dcp_path)
        dc = DcpChainConsts.from_profile(prof)
        wc = load_warmth_curve(warmth_curve_path, warmth=warmth)
        trim = load_neutral_trim(neutral_trim_path) \
            if Path(neutral_trim_path).is_file() else None

        img_cam, camera_wb = _decode_preview(raw_path, long_edge)
        st = _build_static(img_cam, camera_wb, dc, trim)

        params = SurrogateParams(wc, trim, st.neutral_sel, ev=0.0,
                                 brightness=TONE_BRIGHTNESS_NEUTRAL,
                                 rp_matrix=rp_matrix, use_rp_ccm=use_rp_ccm)
        lut = make_base_curve_lut(eotf="srgb", gamma=2.2, n=TONE_LUT_N)
        sur = cls(st, params, dc, lut, wc)
        with torch.no_grad():
            gamma0 = sur._exposure_wb_tone().clamp(0.0, 1.0)
        u8 = (gamma0.cpu().numpy() * 255.0 + 0.5).astype(np.uint8)
        st.cc_w_up, st.cc_li, st.cc_t = _neutral_fast_statics(u8)
        st.cc_base_rgb = _cv2_base_tints()
        return sur


# ---------------------------------------------------------------------------
# 静态构建 (numpy/cv2, 与真实链逐式同源)
# ---------------------------------------------------------------------------

def _decode_preview(raw_path: str | Path,
                    long_edge: int) -> tuple[np.ndarray, np.ndarray]:
    """复刻 api.render_preview_full 解码段: cfa_half 优先, rawpy AHD half 回退;
    INTER_AREA 缩放到长边。返回 (f64 图, f64 camera_wb)。"""
    import rawpy

    raw_path = Path(raw_path)
    raw = rawpy.imread(str(raw_path))
    try:
        img = None
        try:
            img = decode_cfa_half(raw, raw_path=raw_path)
        except Exception:
            img = None
        if img is None:
            rgb16 = raw.postprocess(
                use_camera_wb=False, output_bps=16,
                output_color=rawpy.ColorSpace.raw, no_auto_bright=True,
                half_size=True, user_wb=[1.0, 1.0, 1.0, 1.0],
                demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD)
            img = rgb16.astype(np.float32) / 65535.0
        wb = camera_neutral_wb(raw)
    finally:
        try:
            raw.close()
        except Exception:
            pass

    h, w = img.shape[:2]
    scale = float(long_edge) / max(h, w)
    if abs(scale - 1.0) > 1e-6:
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
    wb64 = np.asarray(wb, dtype=np.float64)
    return img.astype(np.float64), wb64


def _build_static(img_cam: np.ndarray, camera_wb: np.ndarray, dc: DcpChainConsts,
                  trim: NeutralTrimConsts | None) -> ChainStatic:
    """饱和掩码 + cct_k + CCT 分桶选择 (静态; colorcal 静态量在 θ0 前链后补)。"""
    sat_mask = (img_cam >= 0.985).any(axis=2)
    sat_white = None
    if sat_mask.any():
        idx = np.nonzero(sat_mask)
        cam_sat = img_cam[idx[0], idx[1], :]
        cmax = cam_sat.max(axis=1)
        cmin = cam_sat.min(axis=1)
        near = (cmax > 1e-6) & ((cmin / np.maximum(cmax, 1e-6)) >= 0.75)
        if near.any():
            sat_white = (idx[0][near], idx[1][near])

    # cct_k: 白平衡 Stage 口径 = cct_from_wb(pre-warmth wb) 钳 [1000,50000]
    # (同 dc 常量路径, 静态量)。
    with torch.no_grad():
        cct_k = float(cct_k_t(torch.tensor(camera_wb, dtype=torch.float64), dc))
    sel = select_neutral_curves(trim, cct_k)
    return ChainStatic(img_cam=img_cam, camera_wb=camera_wb,
                       wb_key_b=float(camera_wb[2] / max(camera_wb[1], 1e-9)),
                       cct_k=cct_k, sat_white=sat_white,
                       cc_w_up=None, cc_li=None, cc_t=None, cc_base_rgb=None,
                       neutral_sel=sel)


def _cv2_base_tints() -> np.ndarray:
    """基 tint: cv2 u8 Lab2RGB(Lc,128,128) —— 真实 _apply_neutral_fast 的
    rgb_base (u8 整数, θ 无关)。"""
    out = np.zeros((7, 3), dtype=np.float64)
    for k, lc in enumerate(NEUTRAL_L_CENTERS_U8):
        base = cv2.cvtColor(np.array([[[int(lc), 128, 128]]], dtype=np.uint8),
                            cv2.COLOR_LAB2RGB)
        out[k] = base[0, 0].astype(np.float64)
    return out


def _cv2_neutral_tints(off_a: np.ndarray, off_b: np.ndarray,
                       base: np.ndarray) -> np.ndarray:
    """真实 tint (前向): a/b 偏移 clip→u8 截断→cv2 u8 Lab2RGB−基 (整数)
    —— 对齐 _apply_neutral_fast 的 rgb_shift − rgb_base。"""
    out = np.zeros((7, 3), dtype=np.float64)
    for k, lc in enumerate(NEUTRAL_L_CENTERS_U8):
        a8 = int(np.clip(128.0 + float(off_a[k]), 0.0, 255.0))
        b8 = int(np.clip(128.0 + float(off_b[k]), 0.0, 255.0))
        shifted = cv2.cvtColor(np.array([[[int(lc), a8, b8]]], dtype=np.uint8),
                               cv2.COLOR_LAB2RGB)
        out[k] = shifted[0, 0].astype(np.float64) - base[k]
    return out


def _lab_offset_to_rgb_smooth(off_a: torch.Tensor,
                              off_b: torch.Tensor) -> torch.Tensor:
    """float Lab→RGB 平滑代理 (反向雅可比来源; 数值与 cv2 float 路径一致)。"""
    lc = torch.tensor(NEUTRAL_L_CENTERS_U8, dtype=torch.float64) * (100.0 / 255.0)
    fy = (lc + 16.0) / 116.0
    fx = fy + off_a / 500.0
    fz = fy - off_b / 200.0
    eps = 216.0 / 24389.0
    kappa = 24389.0 / 27.0

    def _finv(fv):
        f3 = fv ** 3
        return torch.where(f3 > eps, f3, (116.0 * fv - 16.0) / kappa)

    xyz = torch.stack([_finv(fx) * 0.95047, _finv(fy), _finv(fz) * 1.08883], dim=-1)
    lin = xyz @ torch.tensor(_XYZ_D65_TO_SRGB_F, dtype=torch.float64).T
    enc = torch.where(lin <= 0.0031308, 12.92 * lin,
                      1.055 * torch.pow(torch.clamp(lin, min=1e-12), 1.0 / 2.4) - 0.055)
    return enc.clamp(0.0, 1.0) * 255.0


def _neutral_fast_statics(u8: np.ndarray,
                          sigma: float = NEUTRAL_SIGMA) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """复刻 modules.color_cal._apply_neutral_fast 的 θ 无关静态量:
    (w_up, li, t) —— u8→1/2 降采样→Lab→平台权重→上采样 与 L 带混合索引。"""
    h, w = u8.shape[:2]
    small = cv2.resize(u8, (max(w // 2, 4), max(h // 2, 4)),
                       interpolation=cv2.INTER_AREA)
    lab_s = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
    ls, as_, bs = lab_s[:, :, 0], lab_s[:, :, 1], lab_s[:, :, 2]
    cs = np.sqrt((as_ - 128.0) ** 2 + (bs - 128.0) ** 2)
    tail = np.maximum(cs - NEUTRAL_PLATEAU, 0.0)
    w_s = np.exp(-(tail ** 2) / (2.0 * sigma * sigma)).astype(np.float32)
    w_up = cv2.resize(w_s, (w, h), interpolation=cv2.INTER_LINEAR)[:, :, None]

    lc = NEUTRAL_L_CENTERS_U8
    li = np.clip(np.searchsorted(lc, ls) - 1, 0, len(lc) - 2)
    t = np.clip((ls - lc[li]) / (lc[li + 1] - lc[li]), 0.0, 1.0)
    return w_up, li.astype(np.int64), t.astype(np.float64)
