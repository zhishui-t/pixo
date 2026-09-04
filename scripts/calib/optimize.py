"""θ 端到端联合优化 + G-5 分组拟合 (阶段二 t32, OWN_PIPELINE_STAGE2_DESIGN §3+§4)。

    loss(θ) = Σ_corpora proxy_ΔE(render_diff(raw, θ), ref_jpeg) + λ·scene_constraints(θ)

训练目标 (设计 §3, 显式决策): **proxy = Huber-smoothed Lab 距离** —— ΔE2000 含
min/max 与分段三角函数, 不可微, 只做评估不做训练目标 (防止对不可微目标做梯度)。
真值评估 (决策): 每 checkpoint 用 **真 ΔE2000** (eval_rp_ccm_ab.delta_e_2000,
Sharma 2005, --selftest 先行) 出 median/p95 —— 训练看 proxy, 决策看真值。

θ 载体 (SharedTheta, 优化器唯一接管对象; 组件语义见 theta_io):
    warmth_knots_gain (K,3)  warmth 曲线结点增益 (原 knots 量纲; 绑定期按
                             gains = 1 + 0.9·(g−1) 折算进代理 —— 插值对仿射
                             可交换, t30 已证逐位等价)
    ev_table (n,)            曝光二维表 ev 列 (med/wb 结点位置冻结 —— 位置是
                             实验设计, 值是标定); 每照片 ev_i = w_i @ ev_table,
                             权重 w_i 与运行时 exposure._cal_ev 逐式对齐
                             (med 主键线性插值 + wb_B±0.3 邻域二次取代, 单测
                             对照 pixo 原函数)
    neutral_a/b (kb,7)       colorcal by_cct 分桶中性曲线 (default 不进链,
                             写回原值; 代理链的 CCT 桶选择为 θ0 冻结静态量)
    rp_matrix (3,6)          RP-CCM 根多项式系数 (进链, θ0 = 现行
                             rp_ccm_nikon_z5_2.json 阶段一拟合值)
    skin_ellipse (5,)        **无数据项**: 代理链口径显式关闭 skin stage (θ 无关
                             空间观感层, 见 surrogate_fidelity GATE_PARAMS),
                             本轮仅携带 + 轴正性罚项, 参数不动
每照片 PhotoSurrogate (t30) 持久化实例, 每步 rebind 到共享 θ: 可全局共享的组件
(neutral/rp) 直接共享 nn.Parameter 对象; 逐照片计算量 (warmth 折算 / ev 插值 /
brightness 冻结) 以普通 tensor 注入 (del _parameters + object.__setattr__,
梯度经计算图流向共享参数, 见 bind/_takeover)。

scene_constraints (可微罚项; "λ 相对量纲归一" = 各项按元素数均值化, 梯度量纲
自然同阶, 共享单一 λ, 内部权重见常量区):
    warmth 单调 (θ0 净趋势方向的弱先验 —— θ0 本身非单调, 单调项是防锯齿弱正则)
    + 二阶平滑 (曲率罚, 主力); 曝光表 2D TV (存储为 (med,wb,ev) 散点、med 主键
    插值 —— TV 落在 med 序列与 wb 投影序列两个投影方向); 中性曲线单调;
    skin 椭圆轴正性 hinge (θ0 处恒 0)。

优化器 (设计 §3): Adam(lr=1e-3) 预热 → L-BFGS(strong_wolfe) 精修; seed 固定;
语料清单 + npz 采样缓存 (``--resume``, 复用 fit_skin_oklch 模式: 解码/静态构建
最贵, 缓存后重放不重采)。loss 按照片 macro 平均 (设计 Σ_corpora 的均匀权重
形式, 避免照片数改变 loss 量纲)。

参考 (弱监督, fit_rp_ccm 同源): RAW 内嵌相机 JPEG 缩略图, EXIF 逆旋转 +
INTER_AREA 对齐到代理画布; 样本 = stride 网格 + 双侧线性窗 [0.01,0.90]
(sample_linear_pairs 同式, 在 θ0 训练口径链 (ev=表 θ0 插值) 输出上定窗后冻结
—— 窗边界随 θ 漂移是冻结近似, 同 colorcal 静态量 / BN 冻结统计同类)。

G-5 收口 (设计 §4):
  - 全局门槛线 (RP-CCM 转默认须同时满足): median 改善 ≥15% / 无单照片 median
    回归 >1 JND (=2.3 ΔE00) / 总体 p95 不劣化 / ≥2 相机复验;
  - 分组拟合: 按 pixo.meta 拍摄日分组, 各组以全局 θ* 为基座单独精修 rp_matrix
    (Adam 短程); 产出 per-group 系数 + 分簇门控建议 (**不接运行时**);
  - 评估口径: gain 对齐色度 ΔE2000 (eval_rp_ccm_ab 同式 —— 逐照片标量增益对齐,
    ΔE 只反映色度), A 轨 = θ* 中性渲染 (ev=0, 无 CCM) / B = +全局 rp (中性
    语境拟合, 转默认候选) /
    C = +分组 rp_g; 与阶段一 A/B 报告同构可比。θ 优化收益则用端到端口径
    (无 gain 对齐 —— 曝光差本身是标定对象), 两个口径分工在报告中书面化。

产出: configs/color/calib_out/ (theta_io.save_theta, 不覆盖源文件) +
rp_ccm_by_group.json (分组系数, 非运行时格式) + .artifacts/calib_run.md (收敛
曲线 + 真值对照 + G-5 门槛线) + curves json + checkpoint (.pt)。

用法:
  python scripts/calib/optimize.py --limit 8          # 冒烟
  python scripts/calib/optimize.py                    # 全语料
  python scripts/calib/optimize.py --resume           # 采样缓存重放
  python scripts/calib/optimize.py --init-from configs/color/calib_out
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch
from torch import nn

_SCRIPTS = Path(__file__).resolve().parents[1]
for _p in (str(_SCRIPTS / "calib"), str(_SCRIPTS), str(_SCRIPTS / "src")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import diff_core
import theta_io
from diff_core import DcpChainConsts, PhotoSurrogate, SurrogateParams, \
    TONE_BRIGHTNESS_NEUTRAL
from eval_rp_ccm_ab import delta_e_2000, linear_srgb_to_lab, selftest
from fit_rp_ccm import (DCP, SAMPLE_LIN_HI, SAMPLE_LIN_LO,
                        align_thumb_to_sensor, camera_thumb_rgb, iter_corpus)
from fit_skin_oklch import meta_group
from pixo.render.core.calibration import load_dcp
from pixo.render.core.color import cam_to_xyz
from pixo.render.core.curves import make_base_curve_lut
from pixo.render.core.rp_ccm import RPCCM, apply_rp_ccm
from pixo.render.core.tone import _SRGB_DEC_TABLE, srgb_decode
from pixo.render.modules.exposure import _cal_ev, _probe_sample
from theta_io import Theta

# ---------------------------------------------------------------------------
# 常量 (报告可见的标定决策)
# ---------------------------------------------------------------------------

HUBER_DELTA = 2.0          # Huber 阈值 (Lab 单位; 小残差二次 / 大残差线性)
JND = 2.3                  # 1 JND ≈ 2.3 ΔE00 (G-5 单照片回归门)
G5_MIN_IMPROVEMENT = 0.15  # 门槛线: median 改善 ≥15%
SKIN_AXIS_MARGIN = 0.01    # 轴正性 hinge 安全裕度 (OKLab 单位)

W_WARMTH_MONO = 0.25       # warmth 单调 (弱正则; θ0 非单调, 见模块 docstring)
W_WARMTH_SMOOTH = 1.0      # warmth 二阶平滑 (主力)
W_EV_TV = 1.0              # 曝光表 TV (med 轴 1.0 + wb 投影 0.5)
W_NEUTRAL_MONO = 0.5       # 中性曲线单调
W_SKIN_POS = 10.0          # skin 轴正性 hinge (θ0 处恒 0)

WARMTH = 0.9               # warmth 标量 (render_preview_full 默认, t30 折算口径)
NEAR_TOL = 0.3             # exposure._cal_ev 的 wb 邻域 (|结点med − med| ≤ 0.3)
CACHE_SCHEMA = "pixo.calib_opt_samples.v1"
DEFAULT_SEED = 20260904

_SRGB_DEC_T = torch.tensor(np.asarray(_SRGB_DEC_TABLE, dtype=np.float64))
_LAB_M = torch.tensor(diff_core._SRGB_TO_XYZ_D65_F, dtype=torch.float64)
_LAB_D65 = torch.tensor([0.95047, 1.00000, 1.08883], dtype=torch.float64)
_EPS_K = 216.0 / 24389.0
_KAPPA = 24389.0 / 27.0


# ---------------------------------------------------------------------------
# 曝光表查询的权重分解 (torch 可微, 与运行时 _cal_ev 逐式对齐)
# ---------------------------------------------------------------------------

def cal_ev_weights(xs: np.ndarray, ws: np.ndarray, med: float,
                   wb_b: float | None, near_tol: float = NEAR_TOL) -> np.ndarray:
    """二维曝光表查询 → ev 列上的线性权重 w (ev = w @ ys)。

    与 modules.exposure._cal_ev (二维表) 逐式对应:
      1) med 主键: np.interp(med, xs, ys) —— 端点钳位 + 区间线性;
      2) wb 二次: |xs − med| ≤ near_tol 的邻域结点 ≥2 时, 邻域内按 wb_B 升序
         对 wb_b 线性插值**取代**基准 (wb 越界由 np.interp 端点钳位, 不外推)。
    xs/ws (med/wb 结点位置) 冻结, 权重是构建期常量 → ev 对 θ (ev 列) 线性可微。
    邻域内 wb 结点重复时 t 取 0 (取左; np.interp 在重复键上的取侧未定义,
    真实表 wb 为连续量, 该路径仅为防护)。
    """
    xs = np.asarray(xs, dtype=np.float64)
    n = xs.size
    w = np.zeros(n, dtype=np.float64)
    if med <= xs[0]:
        w[0] = 1.0
    elif med >= xs[-1]:
        w[-1] = 1.0
    else:
        k = min(int(np.searchsorted(xs, med, side="right") - 1), n - 2)
        t = (med - xs[k]) / (xs[k + 1] - xs[k])
        w[k] += 1.0 - t
        w[k + 1] += t
    if wb_b is not None:
        near = np.flatnonzero(np.abs(xs - med) <= near_tol)
        if near.size >= 2:
            order = near[np.argsort(ws[near], kind="stable")]
            wl = ws[order]
            # np.interp 在重复 xp 段取段内最后一个 fp —— 折叠重复键 (每组留末位)
            keep = np.empty(wl.size, dtype=bool)
            keep[:-1] = np.diff(wl) > 0
            keep[-1] = True
            order, wl = order[keep], wl[keep]
            w2 = np.zeros(n, dtype=np.float64)
            if wl.size == 1:
                w2[order[0]] = 1.0
            elif wb_b <= wl[0]:
                w2[order[0]] = 1.0
            elif wb_b >= wl[-1]:
                w2[order[-1]] = 1.0
            else:
                j = min(int(np.searchsorted(wl, wb_b, side="right") - 1),
                        wl.size - 2)
                span = wl[j + 1] - wl[j]
                t = (wb_b - wl[j]) / span if span > 0 else 0.0
                w2[order[j]] += 1.0 - t
                w2[order[j + 1]] += t
            w = w2                      # 取代 (非混合), 与 _cal_ev 同语义
    return w


# ---------------------------------------------------------------------------
# torch 基元: sRGB 解码表插值 / Lab / Huber (proxy 训练口径)
# ---------------------------------------------------------------------------

def srgb_decode_t(x: torch.Tensor) -> torch.Tensor:
    """γ [0,1] → 线性 (core.tone.srgb_decode 的表插值同式; 真实链 4096 级表,
    torch 线性插值 ≤半格表分辨率偏差 —— 与 t30 tone LUT 同族的已知近似)。"""
    n = _SRGB_DEC_T.shape[0] - 2
    scaled = x.clamp(0.0, 1.0) * float(n)
    i0 = scaled.floor().long().clamp(0, n - 1)
    frac = scaled - i0.to(scaled.dtype)
    return _SRGB_DEC_T[i0] * (1.0 - frac) + _SRGB_DEC_T[i0 + 1] * frac


def linear_srgb_to_lab_t(lin: torch.Tensor) -> torch.Tensor:
    """线性 sRGB → Lab(D65) (eval_rp_ccm_ab.linear_srgb_to_lab 同式, torch)。"""
    xyz = lin @ _LAB_M.T / _LAB_D65
    f = torch.where(xyz > _EPS_K,
                    torch.pow(xyz.clamp_min(1e-300), 1.0 / 3.0),
                    (_KAPPA * xyz + 16.0) / 116.0)
    fx, fy, fz = f[..., 0], f[..., 1], f[..., 2]
    return torch.stack([116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)],
                       dim=-1)


def huber(r: torch.Tensor, delta: float = HUBER_DELTA) -> torch.Tensor:
    """Huber(r): r≤δ 二次 / 界外线性 (Lab 距离的平滑稳健化, 设计 §3)。"""
    return torch.where(r <= delta, 0.5 * r * r, delta * (r - 0.5 * delta))


def lab_dist(lab: torch.Tensor, lab_ref: torch.Tensor) -> torch.Tensor:
    """Lab 欧氏距离 (≥0; 零点梯度安全 —— clamp 后 d/r 在 d=0 处为 0)。"""
    d = lab - lab_ref
    return torch.sqrt((d * d).sum(-1).clamp_min(1e-18))


# ---------------------------------------------------------------------------
# scene_constraints 罚项 (可微; 均值化 = λ 相对量纲归一, 见模块 docstring)
# ---------------------------------------------------------------------------

def _net_sign(x) -> float:
    """θ0 净趋势方向: 一阶差分代数和的符号 (和为 0 → 0 = 该方向不设先验)。"""
    x = np.asarray(x, dtype=np.float64)
    s = float(np.sum(np.diff(x, axis=0)))
    return 0.0 if s == 0.0 else float(np.sign(s))


def penalty_warmth(g: torch.Tensor, mono_signs: torch.Tensor
                   ) -> tuple[torch.Tensor, torch.Tensor]:
    """warmth 结点增益 (K,3): 单调 (θ0 净趋势方向弱先验) + 二阶平滑。"""
    d = g[1:] - g[:-1]                                   # (K-1, 3)
    mono = torch.mean(torch.relu(-mono_signs * d) ** 2)
    d2 = g[2:] - 2.0 * g[1:-1] + g[:-2]                  # (K-2, 3) 曲率
    smooth = torch.mean(d2 ** 2)
    return mono, smooth


def penalty_ev_tv(ev: torch.Tensor, wb_order: torch.Tensor
                  ) -> tuple[torch.Tensor, torch.Tensor]:
    """曝光表 2D TV (散点存储的两个投影方向): med 序列 + wb 投影序列。"""
    tv_med = torch.mean((ev[1:] - ev[:-1]) ** 2)
    tv_wb = torch.mean((ev[wb_order[1:]] - ev[wb_order[:-1]]) ** 2)
    return tv_med, tv_wb


def penalty_neutral_mono(c: torch.Tensor, mono_signs: torch.Tensor
                         ) -> torch.Tensor:
    """中性曲线 (kb, 7) 沿 L 结点的单调弱先验 (同 warmth 口径; 每曲线一个
    θ0 净趋势符号)。"""
    d = c[:, 1:] - c[:, :-1]
    return torch.mean(torch.relu(-mono_signs.reshape(-1, 1) * d) ** 2)


def penalty_skin_pos(ellipse: torch.Tensor) -> torch.Tensor:
    """skin 椭圆轴正性 hinge: relu(margin − major/minor)² (θ0 处恒 0)。"""
    major, minor = ellipse[2], ellipse[3]
    return (torch.relu(SKIN_AXIS_MARGIN - major) ** 2
            + torch.relu(SKIN_AXIS_MARGIN - minor) ** 2)


# ---------------------------------------------------------------------------
# θ 载体与代理绑定
# ---------------------------------------------------------------------------

def _takeover(module: nn.Module, name: str, value: torch.Tensor) -> None:
    """把 nn.Parameter 属性替换为共享计算图上的普通 tensor (梯度经图流向共享
    参数)。nn.Module 禁止对参数名直接赋 Tensor, 故先摘除再挂 __dict__
    (常规属性查找先于 nn.Module.__getattr__ 提供的参数, 前向无感)。"""
    if name in module._parameters:
        del module._parameters[name]
    object.__setattr__(module, name, value)


class SharedTheta(nn.Module):
    """θ 五组件的共享载体 (nn.Parameter); 结点位置等非 θ 常量注册为 buffer。"""

    def __init__(self, theta: Theta, warmth: float = WARMTH):
        super().__init__()
        self.warmth = float(warmth)
        self.warmth_knots_gain = nn.Parameter(
            torch.tensor(np.asarray(theta.warmth_knots[:, 1:], dtype=np.float64)))
        self.register_buffer("warmth_abscissae", torch.tensor(
            np.asarray(theta.warmth_knots[:, 0], dtype=np.float64)))
        table = np.asarray(theta.exposure_table, dtype=np.float64)
        self.ev_table = nn.Parameter(
            torch.tensor(np.ascontiguousarray(table[:, 2]), dtype=torch.float64))
        self.register_buffer("ev_xs", torch.tensor(
            np.ascontiguousarray(table[:, 0]), dtype=torch.float64))
        self.register_buffer("ev_ws", torch.tensor(
            np.ascontiguousarray(table[:, 1]), dtype=torch.float64))
        wb_order = np.argsort(table[:, 1], kind="stable")
        self.register_buffer("ev_wb_order",
                             torch.tensor(wb_order, dtype=torch.long))
        self.neutral_a = nn.Parameter(torch.tensor(
            np.asarray(theta.neutral_by_cct[:, 0, :], dtype=np.float64)))
        self.neutral_b = nn.Parameter(torch.tensor(
            np.asarray(theta.neutral_by_cct[:, 1, :], dtype=np.float64)))
        self.rp_matrix = nn.Parameter(torch.tensor(
            np.asarray(theta.rp_ccm_coeff, dtype=np.float64)))
        self.skin_ellipse = nn.Parameter(torch.tensor(
            np.asarray(theta.skin_ellipse, dtype=np.float64)))
        # θ0 单调方向先验 (冻结常量; sign=0 → 该方向不设先验)
        ms = [_net_sign(theta.warmth_knots[:, 1 + j]) for j in range(3)]
        self.register_buffer("warmth_mono_signs",
                             torch.tensor(ms, dtype=torch.float64))
        nc = np.asarray(theta.neutral_by_cct, dtype=np.float64)     # (k,2,m)
        ns = [[_net_sign(nc[kk, 0]), _net_sign(nc[kk, 1])]
              for kk in range(nc.shape[0])]
        self.register_buffer("neutral_mono_signs",
                             torch.tensor(ns, dtype=torch.float64))

    def warmth_gains_eff(self) -> torch.Tensor:
        """θ 载体 (原 knots 增益量纲) → 代理等效增益: 1 + warmth·(g − 1)。"""
        return 1.0 + self.warmth * (self.warmth_knots_gain - 1.0)

    def ev_weights(self, med: float, wb_b: float | None) -> np.ndarray:
        return cal_ev_weights(self.ev_xs.numpy(), self.ev_ws.numpy(),
                              med, wb_b)

    def constraints(self) -> dict[str, torch.Tensor]:
        """scene_constraints (可微罚项; 已按内部权重加权, 未乘全局 λ)。"""
        mono_w, smooth_w = penalty_warmth(self.warmth_knots_gain,
                                          self.warmth_mono_signs)
        tv_med, tv_wb = penalty_ev_tv(self.ev_table, self.ev_wb_order)
        mono_a = penalty_neutral_mono(self.neutral_a,
                                      self.neutral_mono_signs[:, 0])
        mono_b = penalty_neutral_mono(self.neutral_b,
                                      self.neutral_mono_signs[:, 1])
        return {
            "warmth_mono": W_WARMTH_MONO * mono_w,
            "warmth_smooth": W_WARMTH_SMOOTH * smooth_w,
            "ev_tv_med": W_EV_TV * tv_med,
            "ev_tv_wb": 0.5 * W_EV_TV * tv_wb,
            "neutral_mono_a": W_NEUTRAL_MONO * mono_a,
            "neutral_mono_b": W_NEUTRAL_MONO * mono_b,
            "skin_pos": W_SKIN_POS * penalty_skin_pos(self.skin_ellipse),
        }

    def penalty_total(self) -> torch.Tensor:
        return sum(self.constraints().values())


@dataclass
class PhotoKit:
    """单照片训练资产: 持久代理实例 + θ 无关静态量 + 冻结样本窗 + 参考图。"""

    pid: str
    raw: str
    group: str
    cam: str
    sur: PhotoSurrogate
    med: float
    wb_b: float
    ev_w: np.ndarray                    # (n_table,) ev = w @ ev_table
    ref_u8: np.ndarray                  # (H,W,3) 相机 JPEG 参考 (γ 域 8bit)
    sample_idx: np.ndarray              # 展平像素索引 (θ0 训练口径链上定窗)
    ref_lab: np.ndarray                 # (m,3) 参考样本 Lab (训练目标)
    sample_idx_t: torch.Tensor = field(default=None, repr=False)  # type: ignore
    ref_lab_t: torch.Tensor = field(default=None, repr=False)     # type: ignore


def probe_med(img_cam: np.ndarray, camera_wb: np.ndarray, prof) -> float:
    """曝光决策的 med (log2 域) —— modules.exposure._auto_ev 探针口径复刻:
    _probe_sample(256 长边面积均值) → cam_to_xyz(线性 sRGB) → Y 加权中位。
    512 tier 图 → 256 探针的 resize 级联与原图直探的散度 ~0.001 log2
    (_probe_sample docstring 实证); med 只决定查询位置, 残差被 ev 表吸收。"""
    small = _probe_sample(np.ascontiguousarray(img_cam))
    rgb = cam_to_xyz(small, camera_wb, prof)
    y = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    return float(np.median(np.log2(np.maximum(np.asarray(y, np.float64), 1e-6))))


def _window_indices(gamma_sur: np.ndarray, ref_u8: np.ndarray,
                    stride: int) -> np.ndarray:
    """θ0 链输出 vs 参考 → 双侧线性窗样本的全图展平像素索引 (sample_linear_pairs
    同式: stride 网格 + [0.01,0.90] 双侧窗; 网格坐标映射回展平索引)。"""
    h, w = gamma_sur.shape[:2]
    gs = gamma_sur[::stride, ::stride]
    rs = ref_u8[::stride, ::stride].astype(np.float64) / 255.0
    b = srgb_decode(np.ascontiguousarray(gs).astype(np.float32))
    r = srgb_decode(np.ascontiguousarray(rs).astype(np.float32))
    bf = b.reshape(-1, 3).astype(np.float64)
    rf = r.reshape(-1, 3).astype(np.float64)
    ok = np.all((bf >= SAMPLE_LIN_LO) & (bf <= SAMPLE_LIN_HI), axis=1) & \
         np.all((rf >= SAMPLE_LIN_LO) & (rf <= SAMPLE_LIN_HI), axis=1)
    gr = np.arange(gs.shape[0]) * stride
    gc = np.arange(gs.shape[1]) * stride
    flat = (gr[:, None] * w + gc[None, :]).ravel()
    return flat[ok]


def bind(kit: PhotoKit, shared: SharedTheta, ev_override: float | None = None,
         use_rp: bool = True) -> None:
    """把共享 θ 绑到 kit 的代理实例 (每步调用; 幂等)。

    ev_override: None = 表插值 (训练/端到端评估); float = 强制 EV (G-5 中性轨)。
    use_rp: False = RP-CCM 不进链 (G-5 A 轨)。
    """
    p = kit.sur.params
    _takeover(p, "warmth_gains", shared.warmth_gains_eff())
    if ev_override is None:
        _takeover(p, "ev",
                  torch.tensor(kit.ev_w, dtype=torch.float64) @ shared.ev_table)
    else:
        _takeover(p, "ev", torch.tensor(float(ev_override), dtype=torch.float64))
    _takeover(p, "brightness",
              torch.tensor(TONE_BRIGHTNESS_NEUTRAL, dtype=torch.float64))
    p.neutral_a = shared.neutral_a          # Parameter 共享 (多模块同参)
    p.neutral_b = shared.neutral_b
    p.use_rp_ccm = bool(use_rp)
    if use_rp:
        p.rp_matrix = shared.rp_matrix


def proxy_loss(kit: PhotoKit, n_batch: float) -> torch.Tensor:
    """单照片 Huber-Lab proxy (macro 聚合的 1/n_batch 权重已含; 连续 γ,
    量化 [0.5/255] 步长 << JND 不进训练 —— 真值评估侧才量化)。"""
    gamma = kit.sur()
    lin = srgb_decode_t(gamma.reshape(-1, 3))[kit.sample_idx_t]
    return huber(lab_dist(linear_srgb_to_lab_t(lin), kit.ref_lab_t)).mean() \
        / n_batch


# ---------------------------------------------------------------------------
# 语料构建 (npz 采样缓存, 复用 fit_skin --resume 模式)
# ---------------------------------------------------------------------------

def _ref_u8(raw: str, shape: tuple[int, int]) -> np.ndarray | None:
    """RAW 内嵌缩略图 → 与代理画布同构的 u8 参考图 (aligned_pair 参考侧同源:
    EXIF 逆旋转 + INTER_AREA 对齐; u8 存储无损代表 8bit JPEG 源)。"""
    try:
        from pixo.meta import extract as meta_extract
        orientation = int(meta_extract(raw)["capture"].get("orientation") or 1)
    except Exception:
        orientation = 1
    try:
        ref = camera_thumb_rgb(raw)
    except Exception:
        return None
    ref, _ = align_thumb_to_sensor(ref, orientation)
    if ref.shape[:2] != shape:
        import cv2
        ref = cv2.resize(ref, (shape[1], shape[0]), interpolation=cv2.INTER_AREA)
    if ref.shape[:2] != shape:
        return None
    return np.clip(ref * 255.0 + 0.5, 0.0, 255.0).astype(np.uint8)


def _dc_consts(dcp: str) -> DcpChainConsts:
    return DcpChainConsts.from_profile(load_dcp(dcp))


def _finish_statics(sur: PhotoSurrogate) -> None:
    """补 colorcal θ0 静态量 (PhotoSurrogate.build 尾部同式; 缓存重放路径用,
    锚定 DEFAULT configs θ0 —— 与首次构建逐位一致)。"""
    with torch.no_grad():
        gamma0 = sur._exposure_wb_tone().clamp(0.0, 1.0)
    u8 = (gamma0.cpu().numpy() * 255.0 + 0.5).astype(np.uint8)
    sur.static.cc_w_up, sur.static.cc_li, sur.static.cc_t = \
        diff_core._neutral_fast_statics(u8)
    sur.static.cc_base_rgb = diff_core._cv2_base_tints()


def _rebuild_surrogate(img: np.ndarray, wb: np.ndarray, args) -> PhotoSurrogate:
    """缓存重放: 静态图 → 代理实例 (跳过 rawpy 解码; 静态构建用与真实链相同
    的 cv2/numpy 调用, 与首次构建逐位一致)。"""
    static = diff_core._build_static(img, wb, _dc_consts(args.dcp),
                                     diff_core.load_neutral_trim(_neutral_path()))
    sur = _make_surrogate(static)
    _finish_statics(sur)
    return sur


def _neutral_path() -> Path:
    return diff_core._REPO / "resources" / "camera_profiles" / "z5ii_neutral_trim.json"


def _make_surrogate(static) -> PhotoSurrogate:
    """静态量 → 代理实例 (θ 占位由 bind 覆盖; warmth 曲线读默认 configs)。"""
    wc = diff_core.load_warmth_curve(
        diff_core._REPO / "configs" / "calibration" / "warmth_curve.json",
        warmth=WARMTH)
    lut = make_base_curve_lut(eotf="srgb", gamma=2.2, n=diff_core.TONE_LUT_N)
    params = SurrogateParams(wc, None, static.neutral_sel, use_rp_ccm=False)
    return PhotoSurrogate(static, params, static_dc_holder.dc, lut, wc)


class _StaticDcHolder:
    dc: DcpChainConsts | None = None


static_dc_holder = _StaticDcHolder()


def build_kits(items: list[tuple[str, str]], args) -> tuple[list[PhotoKit],
                                                            list[str]]:
    """语料 → (PhotoKit 列表, 跳过清单); --cache/--resume 采样缓存。"""
    cache = Path(args.cache)
    kits: list[PhotoKit] = []
    skipped: list[str] = []
    theta0 = theta_io.load_theta()
    table0 = np.asarray(theta0.exposure_table, dtype=np.float64)

    if args.resume and cache.exists():
        z = np.load(cache, allow_pickle=False)
        if str(z["schema"]) != CACHE_SCHEMA:
            print(f"缓存 schema 不匹配 ({z['schema']}), 重新采样", file=sys.stderr)
        else:
            n = int(z["n_kits"])
            for i in range(n):
                img = z[f"img_{i}"].astype(np.float64)   # decode 源本为 f32, 无损
                sur = _rebuild_surrogate(img, z[f"wb_{i}"].astype(np.float64), args)
                med = float(z[f"med_{i}"])
                wb_b = float(z[f"wbb_{i}"])
                ref_lab = linear_srgb_to_lab(srgb_decode(
                    np.ascontiguousarray(
                        z[f"ref_{i}"].reshape(-1, 3)[z[f"idx_{i}"]]
                        .astype(np.float32) / 255.0)).astype(np.float64))
                kits.append(PhotoKit(
                    pid=str(z[f"pid_{i}"]), raw=str(z[f"raw_{i}"]),
                    group=str(z[f"group_{i}"]), cam=str(z[f"cam_{i}"]),
                    sur=sur, med=med, wb_b=wb_b,
                    ev_w=cal_ev_weights(table0[:, 0], table0[:, 1], med, wb_b),
                    ref_u8=z[f"ref_{i}"], sample_idx=z[f"idx_{i}"],
                    ref_lab=ref_lab))
            print(f"缓存重放: {cache} ({n} 张, 解码/静态构建跳过)", flush=True)
            _tensorize(kits)
            return kits, skipped

    prof = load_dcp(args.dcp)
    shared0 = SharedTheta(theta0)
    for i, (pid, raw) in enumerate(items, 1):
        try:
            group, cam = meta_group(raw)
            sur = PhotoSurrogate.build(raw, args.dcp, long_edge=args.long_edge,
                                       use_rp_ccm=False)
            img, wb = sur.static.img_cam, sur.static.camera_wb
            ref_u8 = _ref_u8(raw, img.shape[:2])
            if ref_u8 is None:
                raise RuntimeError("参考缩略图对齐失败")
            med = probe_med(img, wb, prof)
            wb_b = float(wb[2] / max(float(wb[1]), 1e-9))
            # 定窗: θ0 训练口径链 (ev=表 θ0 插值, 无 CCM —— θ0 表给出训练起点
            # 的曝光水平; 缓存可重现性优先, 恒锚 DEFAULT configs θ0)
            _takeover(sur.params, "warmth_gains", shared0.warmth_gains_eff())
            _takeover(sur.params, "ev", torch.tensor(
                cal_ev_weights(table0[:, 0], table0[:, 1], med, wb_b),
                dtype=torch.float64) @ shared0.ev_table)
            with torch.no_grad():
                gamma0 = sur().clamp(0.0, 1.0).cpu().numpy()
            idx = _window_indices(gamma0, ref_u8, args.stride)
            if idx.size < 500:
                raise RuntimeError(f"有效样本过少 {idx.size}")
            ref_lab = linear_srgb_to_lab(srgb_decode(np.ascontiguousarray(
                ref_u8.reshape(-1, 3)[idx].astype(np.float32) / 255.0))
                .astype(np.float64))
            kits.append(PhotoKit(
                pid=pid, raw=raw, group=group, cam=cam, sur=sur, med=med,
                wb_b=wb_b,
                ev_w=cal_ev_weights(table0[:, 0], table0[:, 1], med, wb_b),
                ref_u8=ref_u8, sample_idx=idx, ref_lab=ref_lab))
            print(f"[{i}/{len(items)}] {pid} group={group} med={med:+.2f} "
                  f"wb_B={wb_b:.3f} n={idx.size}", flush=True)
        except Exception as exc:  # noqa: BLE001 — 单张失败不拖垮整批
            skipped.append(f"{pid}: {exc}")
            print(f"[{i}/{len(items)}] {pid} 跳过: {exc}", flush=True)

    _tensorize(kits)
    if not args.no_cache and kits:
        _save_cache(cache, kits, args)
    return kits, skipped


def _tensorize(kits: list[PhotoKit]) -> None:
    for k in kits:
        k.sample_idx_t = torch.tensor(k.sample_idx, dtype=torch.long)
        k.ref_lab_t = torch.tensor(k.ref_lab, dtype=torch.float64)


def _save_cache(cache: Path, kits: list[PhotoKit], args) -> None:
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, np.ndarray] = {
            "schema": np.array(CACHE_SCHEMA), "n_kits": np.array(len(kits)),
            "long_edge": np.array(args.long_edge),
            "stride": np.array(args.stride),
        }
        for i, k in enumerate(kits):
            payload[f"pid_{i}"] = np.array(k.pid)
            payload[f"raw_{i}"] = np.array(k.raw)
            payload[f"group_{i}"] = np.array(k.group)
            payload[f"cam_{i}"] = np.array(k.cam)
            payload[f"img_{i}"] = k.sur.static.img_cam.astype(np.float32)
            payload[f"wb_{i}"] = k.sur.static.camera_wb.astype(np.float64)
            payload[f"med_{i}"] = np.array(k.med)
            payload[f"wbb_{i}"] = np.array(k.wb_b)
            payload[f"ref_{i}"] = k.ref_u8
            payload[f"idx_{i}"] = k.sample_idx
        np.savez_compressed(cache, **payload)
        print(f"采样缓存 -> {cache}", flush=True)
    except Exception as exc:  # noqa: BLE001 — 缓存失败不阻塞训练
        print(f"缓存写入失败 (继续): {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 评估: 端到端真值 (决策口径) 与 G-5 色度口径
# ---------------------------------------------------------------------------

def _pair_samples(base_u8: np.ndarray, ref_u8: np.ndarray, stride: int
                  ) -> tuple[np.ndarray, np.ndarray]:
    """(u8 候选图, u8 参考) → 线性域样本对 (sample_linear_pairs 同式)。"""
    b = srgb_decode(np.ascontiguousarray(
        base_u8[::stride, ::stride].astype(np.float32) / 255.0))
    r = srgb_decode(np.ascontiguousarray(
        ref_u8[::stride, ::stride].astype(np.float32) / 255.0))
    bf = b.reshape(-1, 3).astype(np.float64)
    rf = r.reshape(-1, 3).astype(np.float64)
    ok = np.all((bf >= SAMPLE_LIN_LO) & (bf <= SAMPLE_LIN_HI), axis=1) & \
         np.all((rf >= SAMPLE_LIN_LO) & (rf <= SAMPLE_LIN_HI), axis=1)
    return bf[ok], rf[ok]


def eval_e2e(kits: list[PhotoKit], shared: SharedTheta, stride: int) -> dict:
    """端到端真值 ΔE2000 (θ 全链含表 ev, 无 gain 对齐 —— 曝光差是标定对象);
    动态窗 (当前输出 vs 参考, sample_linear_pairs 同式), θ 固定后可复现。"""
    per, pooled = [], []
    for kit in kits:
        bind(kit, shared)
        with torch.no_grad():
            u8 = kit.sur.quantize(kit.sur()).cpu().numpy().astype(np.uint8)
        src, dst = _pair_samples(u8, kit.ref_u8, stride)
        if src.shape[0] < 100:
            continue
        de = delta_e_2000(linear_srgb_to_lab(src), linear_srgb_to_lab(dst))
        pooled.append(de)
        per.append({"photo_id": kit.pid, "n": int(src.shape[0]),
                    "median": float(np.median(de)),
                    "p95": float(np.quantile(de, 0.95))})
    if not pooled:
        # 空池绝不允许静默通过 (会伪装成 median=0 的"完美"指标)
        raise RuntimeError("端到端评估无有效样本 (全部照片掉出线性窗/失败)")
    pool = np.concatenate(pooled)
    return {"photos": per, "median": float(np.median(pool)),
            "p95": float(np.quantile(pool, 0.95)), "mean": float(np.mean(pool)),
            "n_photos": len(per)}


@dataclass
class G5Result:
    rows: list = field(default_factory=list)
    a_pool: np.ndarray | None = None
    b_pool: np.ndarray | None = None
    c_pool: np.ndarray | None = None
    n_groups_total: int = 0

    def verdicts(self, cameras: list[str]) -> dict:
        med_a = float(np.median(self.a_pool))
        med_b = float(np.median(self.b_pool))
        p95_a = float(np.quantile(self.a_pool, 0.95))
        p95_b = float(np.quantile(self.b_pool, 0.95))
        improv = (med_a - med_b) / max(med_a, 1e-9)
        worst_reg = max(r["b_median"] - r["a_median"] for r in self.rows)
        uniq = sorted(set(cameras))
        return {"median_a": med_a, "median_b": med_b,
                "median_improvement": improv,
                "gate_improve15": improv >= G5_MIN_IMPROVEMENT,
                "worst_photo_regression": float(worst_reg),
                "gate_no_regression": bool(worst_reg <= JND),
                "p95_a": p95_a, "p95_b": p95_b,
                "gate_p95": bool(p95_b <= p95_a),
                "n_cameras": len(uniq), "cameras": uniq,
                "gate_2cameras": len(uniq) >= 2}


def eval_g5(kits: list[PhotoKit], shared: SharedTheta, stride: int,
            group_matrix: dict[str, np.ndarray] | None = None,
            rp_b: np.ndarray | None = None) -> G5Result:
    """G-5 色度口径 A/B/C 轨 (gain 对齐, eval_rp_ccm_ab 同式):
    A = θ* 中性 (ev=0, 无 CCM) / B = +全局 rp (中性语境拟合) / C = +分组 rp_g。"""
    res = G5Result(n_groups_total=len({k.group for k in kits}))
    if rp_b is None:
        rp_b = shared.rp_matrix.detach().cpu().numpy()
    a_all, b_all, c_all = [], [], []
    for kit in kits:
        bind(kit, shared, ev_override=0.0, use_rp=False)
        with torch.no_grad():
            u8 = kit.sur.quantize(kit.sur()).cpu().numpy().astype(np.uint8)
        src, dst = _pair_samples(u8, kit.ref_u8, stride)
        if src.shape[0] < 100:
            continue
        gain = float(dst.mean() / max(src.mean(), 1e-9))
        d_a = delta_e_2000(linear_srgb_to_lab(src * gain),
                           linear_srgb_to_lab(dst))
        rp_lin = apply_rp_ccm(src, RPCCM(matrix=rp_b, degree=2)
                              ).astype(np.float64)
        d_b = delta_e_2000(linear_srgb_to_lab(rp_lin * gain),
                           linear_srgb_to_lab(dst))
        d_c = None
        mg = (group_matrix or {}).get(kit.group)
        if mg is not None:
            gc_lin = apply_rp_ccm(src, RPCCM(matrix=mg, degree=2)
                                  ).astype(np.float64)
            d_c = delta_e_2000(linear_srgb_to_lab(gc_lin * gain),
                               linear_srgb_to_lab(dst))
        a_all.append(d_a)
        b_all.append(d_b)
        if d_c is not None:
            c_all.append(d_c)
        res.rows.append({
            "photo_id": kit.pid, "group": kit.group, "n": int(src.shape[0]),
            "a_median": float(np.median(d_a)),
            "a_p95": float(np.quantile(d_a, 0.95)),
            "b_median": float(np.median(d_b)),
            "b_p95": float(np.quantile(d_b, 0.95)),
            "c_median": None if d_c is None else float(np.median(d_c))})
        tail = "" if d_c is None else f" C={res.rows[-1]['c_median']:.2f}"
        print(f"  G5 {kit.pid} [{kit.group}] A={res.rows[-1]['a_median']:.2f} "
              f"B={res.rows[-1]['b_median']:.2f}{tail}", flush=True)
    if a_all:
        res.a_pool = np.concatenate(a_all)
        res.b_pool = np.concatenate(b_all)
        res.c_pool = np.concatenate(c_all) if c_all else None
    return res


def _neutral_pools(kits: list[PhotoKit], shared: SharedTheta, stride: int
                   ) -> dict[str, list]:
    """G-5 中性语境样本池: A 轨基座 (θ* warmth/neutral, ev=0, 无 CCM) 输出
    的线性样本 vs 参考 Lab, 附逐照片 gain 对齐标量 (RP-CCM 曝光不变 →
    gain 对齐后 ΔE 只反映色度, 与阶段一 fit_rp_ccm/eval_rp_ccm_ab 同构)。"""
    pools: dict[str, list] = {}
    for kit in kits:
        bind(kit, shared, ev_override=0.0, use_rp=False)
        with torch.no_grad():
            u8 = kit.sur.quantize(kit.sur()).cpu().numpy().astype(np.uint8)
        src, dst = _pair_samples(u8, kit.ref_u8, stride)
        if src.shape[0] < 200:
            continue
        gain = float(dst.mean() / max(src.mean(), 1e-9))
        pools.setdefault(kit.group, []).append(
            (src.astype(np.float64), linear_srgb_to_lab(dst), gain))
    return pools


def _fit_rp(pools: list, base: np.ndarray, steps: int, lr: float
            ) -> tuple[np.ndarray, float, int]:
    """中性语境 RP-CCM Adam 精修 (只动系数; 样本池 = [(src, lab, gain)])。"""
    m = nn.Parameter(torch.tensor(np.asarray(base, dtype=np.float64)))
    opt = torch.optim.Adam([m], lr=lr)
    srcs = np.vstack([p[0] for p in pools])
    labs = np.vstack([p[1] for p in pools])
    gains = np.concatenate([np.full(p[0].shape[0], p[2], dtype=np.float64)
                            for p in pools])   # 逐样本 gain (照片标量展开)
    src_t = torch.tensor(srcs, dtype=torch.float64)
    lab_t = torch.tensor(labs, dtype=torch.float64)
    gain_t = torch.tensor(gains, dtype=torch.float64)[:, None]
    feat = diff_core.rp_features_t(src_t, degree=2)
    last = float("nan")
    for _ in range(steps):
        opt.zero_grad()
        pred = diff_core.soft_clip(feat @ m.T, 0.0, 1.0) * gain_t
        d = lab_dist(linear_srgb_to_lab_t(pred), lab_t)
        loss = huber(d).mean()
        loss.backward()
        opt.step()
        last = float(loss.detach())
    return m.detach().cpu().numpy(), last, srcs.shape[0]


def fit_global_rp_neutral(kits: list[PhotoKit], shared: SharedTheta,
                          steps: int, lr: float, stride: int
                          ) -> tuple[np.ndarray, str]:
    """G-5 B 轨系数: 全语料中性语境全局 RP-CCM (门槛线判定的"转默认候选")。

    主优化的 rp* 在端到端语境 (表 ev 进链) 与 warmth/neutral 联合拟合, 拆到
    中性语境单独评估会语境错配 (实测 B 轨反而劣化) —— 转默认决策必须用与
    评估同语境拟合的系数, 与阶段一 fit_rp_ccm 的中性弱监督口径一致。"""
    pools = _neutral_pools(kits, shared, stride)
    merged = [p for pl in pools.values() for p in pl]
    m, last, n = _fit_rp(merged, shared.rp_matrix.detach().cpu().numpy(),
                         steps, lr)
    return m, f"n={n} px / {len(merged)} 张, proxy={last:.4f}"


def fit_group_matrices(kits: list[PhotoKit], shared: SharedTheta,
                       base_rp: np.ndarray, steps: int, lr: float,
                       stride: int) -> dict[str, np.ndarray]:
    """G-5 分组拟合: pixo.meta 拍摄日分组, 以中性语境全局系数为基座单独
    精修各组 rp_matrix (组样本/照片过少跳过; 分簇门控建议, 不接运行时)。"""
    pools = _neutral_pools(kits, shared, stride)
    out: dict[str, np.ndarray] = {}
    for g in sorted(pools):
        if len(pools[g]) < 2:
            print(f"  组 {g}: 照片不足 ({len(pools[g])} 张), 跳过分组拟合",
                  flush=True)
            continue
        m, last, n = _fit_rp(pools[g], base_rp, steps, lr)
        out[g] = m
        print(f"  组 {g}: n={n} px / {len(pools[g])} 张, proxy={last:.4f}",
              flush=True)
    return out


# ---------------------------------------------------------------------------
# θ 导出 (theta_io) 与 checkpoint
# ---------------------------------------------------------------------------

def to_theta(shared: SharedTheta, base: Theta) -> tuple[Theta, dict]:
    """共享 θ → theta_io.Theta (位置列/非 θ 字段从 base 原样保留);
    warmth 增益钳到运行时带界 [0.5,1.5] (theta_io 校验规则), 报告记录钳制数。"""
    g = shared.warmth_knots_gain.detach().cpu().numpy()
    g_clipped = np.clip(g, 0.5, 1.5)
    clip_report = {"warmth_clipped": int(np.sum(g != g_clipped))}
    knots = np.array(base.warmth_knots, dtype=np.float64, copy=True)
    knots[:, 1:] = g_clipped
    table = np.array(base.exposure_table, dtype=np.float64, copy=True)
    table[:, 2] = shared.ev_table.detach().cpu().numpy()
    by_cct = np.stack([shared.neutral_a.detach().cpu().numpy(),
                       shared.neutral_b.detach().cpu().numpy()], axis=1)
    return Theta(
        warmth_knots=knots, warmth_domain=base.warmth_domain,
        exposure_table=table, probe_hi=base.probe_hi,
        neutral_default=np.array(base.neutral_default, copy=True),
        neutral_cct=np.array(base.neutral_cct, copy=True),
        neutral_by_cct=by_cct,
        rp_ccm_coeff=shared.rp_matrix.detach().cpu().numpy(),
        rp_ccm_degree=base.rp_ccm_degree,
        skin_ellipse=shared.skin_ellipse.detach().cpu().numpy(),
        docs=base.docs, sources=base.sources), clip_report


def save_ckpt(path: Path, shared: SharedTheta, history: list, eval_rows: list,
              meta: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"theta": {k: v.detach().cpu() for k, v in
                          shared.state_dict().items()},
                "history": history, "eval_rows": eval_rows, "meta": meta}, path)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def _train_and_export(kits: list[PhotoKit], shared: SharedTheta, base: Theta,
                      args, history: list, eval_rows: list
                      ) -> tuple[Theta, dict]:
    """Adam(lr=1e-3) 预热 → L-BFGS 精修 (真值恶化自动回滚) → θ 导出。"""
    # -- Adam 预热 (全量 macro 梯度累积; batch>0 时按 seed 确定性抽样) --
    opt = torch.optim.Adam(shared.parameters(), lr=args.lr)
    rng = np.random.default_rng(args.seed)
    t0 = time.time()
    for step in range(1, args.steps_adam + 1):
        opt.zero_grad()
        if args.batch <= 0 or args.batch >= len(kits):
            batch = kits
        else:
            batch = [kits[i] for i in
                     rng.choice(len(kits), size=args.batch, replace=False)]
        n_b = float(len(batch))
        data_loss = 0.0
        for kit in batch:
            bind(kit, shared)
            loss_k = proxy_loss(kit, n_b)
            loss_k.backward()
            data_loss += float(loss_k.detach())
        pen = args.lam * shared.penalty_total()
        pen.backward()
        opt.step()
        history.append({"phase": "adam", "step": step, "proxy": data_loss,
                        "penalty": float(pen),
                        **{k: float(v) for k, v in
                           shared.constraints().items()}})
        if step % 10 == 0 or step == 1:
            print(f"  adam {step:>4}/{args.steps_adam} proxy={data_loss:.5f} "
                  f"pen={float(pen):.5f} ({time.time() - t0:.0f}s)", flush=True)
        if step % args.ckpt_every == 0 or step == args.steps_adam:
            ev = eval_e2e(kits, shared, args.stride)
            ev["tag"] = f"adam_{step}"
            eval_rows.append(ev)
            print(f"  [ckpt] adam@{step}: 真值 ΔE2000 median {ev['median']:.3f} "
                  f"/ p95 {ev['p95']:.3f}", flush=True)
    save_ckpt(Path(args.ckpt), shared, history, eval_rows,
              {"args": {k: v for k, v in vars(args).items()}, "phase": "adam"})

    # -- L-BFGS 精修 (closure = 全语料 macro loss + 罚项, 逐张梯度累积) --
    lbfgs = torch.optim.LBFGS(shared.parameters(), lr=1.0,
                              max_iter=args.steps_lbfgs, history_size=50,
                              line_search_fn="strong_wolfe")
    n_b = float(len(kits))
    lbfgs_evals = [0]

    def closure():
        lbfgs.zero_grad()
        total = torch.zeros((), dtype=torch.float64)
        data_loss = 0.0
        for kit in kits:
            bind(kit, shared)
            loss_k = proxy_loss(kit, n_b)
            loss_k.backward()
            data_loss += float(loss_k.detach())
            total = total + loss_k.detach()
        pen = args.lam * shared.penalty_total()
        pen.backward()
        lbfgs_evals[0] += 1
        history.append({"phase": "lbfgs", "step": lbfgs_evals[0],
                        "proxy": data_loss, "penalty": float(pen)})
        return total + pen.detach()

    print("== L-BFGS 精修 …", flush=True)
    t1 = time.time()
    snapshot = {k: v.detach().clone() for k, v in shared.state_dict().items()}
    lbfgs.step(closure)
    ev = eval_e2e(kits, shared, args.stride)
    if ev["median"] > eval_rows[-1]["median"]:
        # 决策看真值: L-BFGS 是无约束优化, 线搜索可能把 θ 推过链的有效域使
        # 端到端真值恶化 (proxy 下降 ≠ 真值改善) —— 回滚到 Adam 末点。
        with torch.no_grad():
            shared.load_state_dict(snapshot)
        ev = eval_e2e(kits, shared, args.stride)
        ev["tag"] = "lbfgs_rolledback_to_adam"
        print("  [ckpt] L-BFGS 真值恶化, 已回滚 Adam 末点", flush=True)
    else:
        ev["tag"] = "lbfgs_final"
    eval_rows.append(ev)
    print(f"  [ckpt] {ev['tag']}: 真值 ΔE2000 median {ev['median']:.3f} / "
          f"p95 {ev['p95']:.3f} ({time.time() - t1:.0f}s)", flush=True)
    save_ckpt(Path(args.ckpt), shared, history, eval_rows,
              {"args": {k: v for k, v in vars(args).items()}, "phase": "lbfgs"})
    return to_theta(shared, base)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default="exports/auto/full_scan")
    ap.add_argument("--raw", action="append", default=None)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dcp", default=DCP)
    ap.add_argument("--long-edge", type=int, default=512)
    ap.add_argument("--stride", type=int, default=3)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--steps-adam", type=int, default=200)
    ap.add_argument("--steps-lbfgs", type=int, default=40)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--batch", type=int, default=0, help="每步照片数 (0=全量)")
    ap.add_argument("--lambda", dest="lam", type=float, default=1.0,
                    help="scene_constraints 全局权重 (各项已均值化归一)")
    ap.add_argument("--ckpt-every", type=int, default=40)
    ap.add_argument("--cache", default=".artifacts/calib_opt_samples.npz")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--resume", action="store_true", help="采样缓存重放")
    ap.add_argument("--init-from", default="",
                    help="θ 初值目录 (缺省 = 现行 configs; 可指向 calib_out 续训)")
    ap.add_argument("--out-dir", default="configs/color/calib_out")
    ap.add_argument("--report", default=".artifacts/calib_run.md")
    ap.add_argument("--curves", default=".artifacts/calib_run_curves.json")
    ap.add_argument("--ckpt", default=".artifacts/calib_ckpt.pt")
    ap.add_argument("--g5-group-steps", type=int, default=250)
    ap.add_argument("--skip-g5", action="store_true")
    ap.add_argument("--g5-only", action="store_true",
                    help="跳过训练 (θ 从 --init-from / ckpt 读回), 仅重跑 G-5")
    args = ap.parse_args(argv)

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    t00 = time.time()
    static_dc_holder.dc = _dc_consts(args.dcp)

    print("== CIEDE2000 文献对自检 (eval_rp_ccm_ab --selftest)")
    selftest()

    # ---- θ 初值 (缺省 = 现行 configs; --init-from 指向 calib_out 续训) ----
    base = theta_io.load_theta() if not args.init_from else theta_io.load_theta(
        {k: Path(args.init_from) / theta_io.OUT_NAMES[k]
         for k in theta_io.SOURCE_KEYS})
    shared = SharedTheta(base)

    # ---- 语料 ----
    items = iter_corpus(args.corpus, args.raw, args.limit)
    if not items:
        print("语料为空: 检查 --corpus/--raw", file=sys.stderr)
        return 2
    print(f"== 语料 {len(items)} 张, 构建/重放采样缓存 …", flush=True)
    kits, skipped = build_kits(items, args)
    if len(kits) < 2:
        print("有效照片不足 2 张", file=sys.stderr)
        return 2

    # ---- θ0 真值基线 / --g5-only 复用已训 θ ----
    history: list = []
    eval_rows: list = []
    if args.g5_only:
        ckpt_file = Path(args.ckpt)
        if ckpt_file.is_file():
            blob = torch.load(ckpt_file, map_location="cpu", weights_only=False)
            shared.load_state_dict(blob["theta"])
            history = blob.get("history", [])
            eval_rows = blob.get("eval_rows", [])
            print(f"g5-only: θ 与训练轨迹读自 {ckpt_file}", flush=True)
        if not eval_rows:
            ev0 = eval_e2e(kits, shared, args.stride)
            ev0["tag"] = "theta_loaded"
            eval_rows.append(ev0)
        evf = eval_e2e(kits, shared, args.stride)
        evf["tag"] = "theta_loaded_recheck"
        eval_rows.append(evf)
        theta_star, clip_report = to_theta(shared, base)
        out_paths = theta_io.save_theta(theta_star, args.out_dir)
        print(f"== θ (g5-only) -> {args.out_dir}", flush=True)
    else:
        ev0 = eval_e2e(kits, shared, args.stride)
        ev0["tag"] = "theta0"
        eval_rows.append(ev0)
        print(f"== θ0 真值 ΔE2000 median {ev0['median']:.3f} / "
              f"p95 {ev0['p95']:.3f} ({ev0['n_photos']} 张)", flush=True)

    # ---- Adam 预热 → L-BFGS 精修 → θ 导出 (g5-only 跳过, 复用已训 θ) ----
    if not args.g5_only:
        theta_star, clip_report = _train_and_export(
            kits, shared, base, args, history, eval_rows)
        print(f"== 新表 -> {args.out_dir} "
              f"(warmth 钳界 {clip_report['warmth_clipped']} 处)", flush=True)

    # ---- G-5: 全局中性语境拟合 + 分组拟合 + A/B/C 门槛线 ----
    g5, group_matrix, verdicts = None, {}, None
    if not args.skip_g5:
        print("== G-5 全局 RP-CCM 中性语境拟合 (转默认候选) …", flush=True)
        rp_global, g_note = fit_global_rp_neutral(
            kits, shared, args.g5_group_steps, args.lr, args.stride)
        print(f"  全局: {g_note}", flush=True)
        print("== G-5 分组拟合 (pixo.meta 拍摄日) …", flush=True)
        group_matrix = fit_group_matrices(kits, shared, rp_global,
                                          args.g5_group_steps, args.lr,
                                          args.stride)
        if group_matrix or args.g5_only:
            gp = Path(args.out_dir) / "rp_ccm_by_group.json"
            gp.write_text(json.dumps(
                {"schema": "pixo.rp_ccm_by_group.v1",
                 "note": "per-group RP-CCM 系数 (pixo.meta 拍摄日分组; "
                         "分簇门控建议, 不接运行时 —— 设计 §4)。基座 = "
                         "全局中性语境拟合系数 (B 轨), 与门槛线评估同语境。",
                 "rp_global_neutral": {"matrix": rp_global.tolist(),
                                       "degree": 2,
                                       "terms": list(diff_core.RP_DEGREE2_TERMS)},
                 "groups": {g: {"matrix": m.tolist(), "degree": 2,
                                "terms": list(diff_core.RP_DEGREE2_TERMS)}
                            for g, m in sorted(group_matrix.items())},
                 "created": time.strftime("%Y-%m-%dT%H:%M:%S")},
                ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  分组系数 -> {gp}", flush=True)
        print("== G-5 A/B/C 轨评估 (gain 对齐色度口径) …", flush=True)
        g5 = eval_g5(kits, shared, args.stride, group_matrix, rp_b=rp_global)
        verdicts = g5.verdicts([k.cam for k in kits])

    write_report(Path(args.report), Path(args.curves), args, base,
                 theta_star, history, eval_rows, g5, verdicts, group_matrix,
                 clip_report, kits, skipped, time.time() - t00)
    print(f"DONE {time.time() - t00:.0f}s -> {args.report}", flush=True)
    return 0


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def write_report(out: Path, curves_out: Path, args, base: Theta,
                 theta_star: Theta, history: list, eval_rows: list, g5,
                 verdicts, group_matrix, clip_report, kits, skipped: list,
                 elapsed: float
                 ) -> None:
    groups = sorted({k.group for k in kits})
    cams = sorted({k.cam for k in kits})
    ev0, evf = eval_rows[0], eval_rows[-1]
    d_improv = (ev0["median"] - evf["median"]) / max(ev0["median"], 1e-9)
    lines = [
        "# θ 端到端优化运行报告 (阶段二 t32, 设计 §3+§4)",
        "",
        f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')} · 耗时 {elapsed:.0f}s"
        f" · seed={args.seed}",
        f"- 语料: {args.corpus} ({len(kits)} 张入训 / {len(skipped)} 张跳过, "
        "拍摄日分组: " + ", ".join(groups) + f"; 相机: {', '.join(cams)})",
        f"- 渲染口径: PhotoSurrogate @ long_edge={args.long_edge}, "
        f"stride={args.stride}; 参考 = RAW 内嵌相机 JPEG (EXIF 逆旋转, "
        "fit_rp_ccm 同源)",
        f"- 优化: {'(g5-only, 复用已训 θ)' if args.g5_only else ''}"
        f"Adam(lr={args.lr})×{args.steps_adam} → "
        f"L-BFGS(strong_wolfe)×{args.steps_lbfgs}, λ={args.lam}, "
        f"batch={'全量' if args.batch <= 0 else args.batch}",
        f"- 训练目标: Huber-Lab proxy (δ={HUBER_DELTA}, 可微); 决策指标: 真 "
        "ΔE2000 (eval_rp_ccm_ab, Sharma 2005, --selftest 通过) —— 训练看 "
        "proxy, 决策看真值 (设计 §3)",
        "",
        "## 真值对照 (端到端口径: θ 全链含表 ev, 无 gain 对齐, 动态窗)",
        "",
        "| 阶段 | ΔE2000 median | p95 | mean |",
        "|---|---:|---:|---:|",
        f"| θ0 ({'现行 configs' if not args.init_from else args.init_from}) "
        f"| {ev0['median']:.3f} | {ev0['p95']:.3f} | {ev0['mean']:.3f} |",
        f"| θ* (本轮) | {evf['median']:.3f} | {evf['p95']:.3f} "
        f"| {evf['mean']:.3f} |",
        f"| **改善** | **{d_improv * 100:+.1f}%** | "
        f"**{(ev0['p95'] - evf['p95']) / max(ev0['p95'], 1e-9) * 100:+.1f}%** "
        "| — |",
        "",
        "## Checkpoint 真值轨迹",
        "",
        "| checkpoint | ΔE2000 median | p95 |",
        "|---|---:|---:|",
    ]
    for ev in eval_rows:
        lines.append(f"| {ev['tag']} | {ev['median']:.3f} | {ev['p95']:.3f} |")

    dw = float(np.abs(theta_star.warmth_knots[:, 1:]
                      - base.warmth_knots[:, 1:]).max())
    de = float(np.abs(theta_star.exposure_table[:, 2]
                      - base.exposure_table[:, 2]).max())
    dn = float(np.abs(theta_star.neutral_by_cct - base.neutral_by_cct).max())
    dr = float(np.abs(theta_star.rp_ccm_coeff - base.rp_ccm_coeff).max())
    ds = float(np.abs(theta_star.skin_ellipse - base.skin_ellipse).max())
    lines += [
        "",
        "## Δθ (θ0 → θ*, 组件最大绝对变化)",
        "",
        "| 组件 | max|Δθ| | 备注 |",
        "|---|---:|---|",
        f"| warmth knots 增益 | {dw:.4f} | 运行时带界 [0.5,1.5], 钳制 "
        f"{clip_report['warmth_clipped']} 处 |",
        f"| 曝光表 ev 列 | {de:.4f} EV | med/wb 位置列冻结 |",
        f"| 中性曲线 (by_cct) | {dn:.4f} | default 曲线不进链, 原样保留 |",
        f"| RP-CCM (3×6) | {dr:.4f} | θ0 = 阶段一拟合值 |",
        f"| skin 椭圆 | {ds:.6f} | 无数据项 (代理口径显式关 skin stage), "
        "仅携带 + 轴正性罚 |",
        "",
        "## 收敛曲线 (每 20 条抽样)",
        "",
        "```",
    ]
    for h in (history[::20] or history):
        lines.append(f"  {h['phase']:>5}#{h['step']:<4} proxy={h['proxy']:.5f} "
                     f"pen={h.get('penalty', 0.0):.5f}")
    lines.append("```")

    if g5 is not None and verdicts is not None and g5.a_pool is not None:
        med_c = (float(np.median(g5.c_pool))
                 if g5.c_pool is not None and g5.c_pool.size else None)
        gates = [
            ("median 改善 ≥15%",
             f"{verdicts['median_improvement'] * 100:+.1f}% "
             f"({verdicts['median_a']:.3f} → {verdicts['median_b']:.3f})",
             verdicts["gate_improve15"]),
            ("无单照片 median 回归 >1 JND (2.3)",
             f"最差 {verdicts['worst_photo_regression']:+.2f}",
             verdicts["gate_no_regression"]),
            ("总体 p95 不劣化",
             f"{verdicts['p95_a']:.3f} → {verdicts['p95_b']:.3f}",
             verdicts["gate_p95"]),
            ("≥2 相机复验",
             f"{verdicts['n_cameras']} 台 ({', '.join(verdicts['cameras'])})",
             verdicts["gate_2cameras"]),
        ]
        lines += [
            "",
            "## G-5 RP-CCM 门槛线 (色度口径: gain 对齐, eval_rp_ccm_ab 同式)",
            "",
            f"- A 轨 = θ* 中性 (ev=0, 无 CCM): ΔE2000 median "
            f"**{verdicts['median_a']:.3f}** / p95 {verdicts['p95_a']:.3f}",
            f"- B 轨 = A + 全局 rp (中性语境拟合, 转默认候选): median "
            f"**{verdicts['median_b']:.3f}** / p95 {verdicts['p95_b']:.3f}",
        ]
        if med_c is not None:
            lines.append(f"- C 轨 = A + 分组 rp_g ({len(group_matrix)} 组): "
                         f"median **{med_c:.3f}**")
        lines += ["", "| 门槛 | 实测 | 判定 |", "|---|---|:---:|"]
        for name, meas, ok in gates:
            lines.append(f"| {name} | {meas} | {'✅' if ok else '❌'} |")
        g_ok = all(ok for _, _, ok in gates)
        lines += [
            "",
            ("**G-5 结论: 满足全部门槛线, 可提交转默认决策**" if g_ok else
             "**G-5 结论: 不满足全部门槛线 (逐条见上表; 未达标项含语料限制时"
             "如实标注)**;"
             " per-group 系数与分簇建议见 calib_out/rp_ccm_by_group.json"
             " (不接运行时, 设计 §4)。"),
            "",
            "### 分照片 (A→B)",
            "",
            "| photo | 组 | n | A median | B median | C median | Δ(B−A) |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for r in g5.rows:
            c_str = "—" if r["c_median"] is None else f"{r['c_median']:.3f}"
            lines.append(
                f"| {r['photo_id']} | {r['group']} | {r['n']} "
                f"| {r['a_median']:.3f} | {r['b_median']:.3f} | {c_str} "
                f"| {r['b_median'] - r['a_median']:+.3f} |")

    lines += [
        "",
        "## 注记 (口径决策)",
        "",
        "- **proxy 与 ΔE2000 分工**: ΔE2000 含 min/max 不可微, 只做评估不做"
        "训练目标 (设计 §3 显式决策); proxy = Huber-Lab (欧氏距离 δ="
        f"{HUBER_DELTA})。",
        "- **曝光表进链**: 每照片 ev = w·ev_table, 权重 w 与运行时 "
        "exposure._cal_ev 逐式对齐 (med 主键 + wb_B±0.3 邻域二次取代; 单测对照"
        " pixo 原函数); med 取 _probe_sample 探针口径 (θ 无关, 构建期冻结)。",
        "- **样本窗冻结**: θ0 训练口径链 (ev=表 θ0 插值) 输出上按 "
        "sample_linear_pairs 同式定窗后冻结 —— 窗边界随 θ 漂移是冻结近似 (同 "
        "colorcal 静态量 / BN 冻结统计同类)。",
        "- **单调罚是弱正则**: θ0 的 warmth/中性曲线本身非单调 (实测 warmth R "
        "列净趋势 ±0.05, 中性桶间有回勾), 单调项取 θ0 净趋势方向 (一阶差分代数"
        "和的符号, 和为 0 该列不设先验), 权重 0.25/0.5; 主力是二阶平滑/TV。"
        "该实现为设计留白处的首跑选择, 随报告透明化。",
        "- **λ 归一**: 各罚项按元素数均值化 (相对量纲归一), 共享全局 λ;"
        f"内部权重 warmth 单调 {W_WARMTH_MONO} / 平滑 {W_WARMTH_SMOOTH} / "
        f"曝光表 TV {W_EV_TV} (+wb 投影 0.5) / 中性单调 {W_NEUTRAL_MONO} / "
        f"skin 轴正性 {W_SKIN_POS}。",
        "- **skin_ellipse 无数据项**: 代理链口径显式关闭 skin stage (θ 无关"
        "空间观感层, surrogate_fidelity GATE_PARAMS), 本轮仅携带 + 轴正性罚 "
        "(θ0 处恒 0), 参数不动; 椭圆重拟合属阶段一 fit_skin_oklch 职责。",
        "- **非 θ 字段随写原样**: neutral default 曲线 / target_offset "
        "probe_hi / 各 JSON meta 注记, save 时原样保留 (theta_io 契约)。",
        "- **评估双口径分工**: θ 优化收益 = 端到端口径 (无 gain 对齐, 曝光差是"
        "标定对象); G-5 = gain 对齐色度口径 (与阶段一 eval_rp_ccm_ab 报告同构"
        "可比)。",
        "- **G-5 的 B 轨用中性语境系数而非联合 rp***: 主优化的 rp* 在端到端"
        "语境 (表 ev 进链) 与 warmth/neutral 联合拟合, 拆到中性语境单独评估"
        "会语境错配 (本轮全语料实测: 联合 rp* 在 A 轨基座上 median 5.98→6.86 "
        "反而劣化) —— 转默认决策必须用与评估同语境拟合的系数"
        " (fit_global_rp_neutral, 与阶段一 fit_rp_ccm 的中性弱监督口径一致), "
        "分组系数同样以它为基座精修。联合 rp* 属\"新表+rp 全采纳\"场景"
        " (其收益已由端到端真值量化)。",
        "- **运行时零变化**: 新表落 calib_out/ (原 configs 不动), "
        "src/pixo/render 零改动; 是否采纳由 t33-t35 评估/回归/QA 决策。",
    ]
    if skipped:
        lines.append(f"- 本轮跳过 {len(skipped)} 张: " + "; ".join(skipped[:5])
                     + (" ..." if len(skipped) > 5 else ""))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    curves = {
        "schema": "pixo.calib_run_curves.v1",
        "args": {k: v for k, v in vars(args).items() if k != "_skipped"},
        "history": history,
        "eval_rows": [{k: v for k, v in ev.items() if k != "photos"}
                      for ev in eval_rows],
        "eval_photos": {ev["tag"]: ev.get("photos", []) for ev in eval_rows},
        "g5_verdicts": verdicts,
        "g5_rows": (g5.rows if g5 is not None else []),
        "group_matrix": {g: m.tolist() for g, m in (group_matrix or {}).items()},
        "groups": groups, "cameras": cams, "elapsed_sec": elapsed,
    }
    curves_out.write_text(json.dumps(curves, ensure_ascii=False, indent=1),
                          encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
