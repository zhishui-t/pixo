"""Stage region_adjust (order=57) —— M1 掩码驱动的分区调整 (gamma_rgb → gamma_rgb)。

位置: skin(55) 之后、stylize(60) 之前 (56-59 槽位空闲, skin 磨皮后、
风格化 LUT 前施加分区意图, LUT/精修保持全图统一口径)。

参数 (F12, 设计 §2; R13 扩展 warmth):
  enabled       是否启用 (默认 **False** —— 基座零影响, 沿 dehaze t108 先例)
  regions       dict: prompt → {"exposure": float EV [-2,2] (默认 0),
                               "saturation": float [-1,1] (默认 0),
                               "warmth": float [-1,1] (默认 0, 负=冷调正=暖调)}

掩码契约 (ctx.state["region_masks"], F13 通道注入):
  dict: prompt → float 0..1 软掩码 (HxW 或 HxWx1; 分辨率可与图不同, 自动缩放)。
  掩码缺失 (state 键不存在 / 空 / 区域 prompt 无掩码) → wants=False 静默跳过
  (无掩码 = 无区域效果, 不报错)。本 Stage 只消费该键, 不生产 (生产归 F13)。

调整内核 (设计 §2 首版口径, oklch 域演进留下轮避免与 stream-2 战场重叠):
  - 曝光 = gamma 域增益近似: gain = 2^(ev/2.2)。线性域等效增益 gain^2.2 = 2^ev
    (纯幂近似): 中间调 (gamma ≈0.3..0.6) 线性增益相对误差 <4%, 深阴影偏差
    增大 (sRGB 分段幂 2.4 段), 高光由 clip 兜底 —— 意图级软区域可接受。
    二选一取 a) 快路径 (单次乘法), 弃 b) 线性化往返 (精确但全图两次幂运算)。
  - 饱和度 = HSV S 缩放: S' = clip(S*(1+sat), 0, 1) (中性像素 S=0 不受影响)。
  - 暖色 (R13) = gamma 域 RGB 通道增益近似 (白平衡 warmth 标定链的意图级
    近似, 见 _warmth_gains): G 上 / B 下为暖 (标定暖黄方向), 负 warmth 对称
    反向为冷。精度纪律与 exposure 的 2^(ev/2.2) 同级 (意图级近似, 不做
    色温线性化往返)。
  - 同区域施加序: 先曝光 → 再暖色 → 后饱和; 多区域按 regions 声明序顺序软合成:
    out = out*(1-m) + adjusted*m (与 skin_smooth 同一线性混合纪律)。
  - 掩码羽化沿 skin stage 软掩码纪律 (禁硬边): 应用前做尺度相对的高斯羽化
    (sigma 随长边缩放; 相对过渡带仅在长边 512..4096 区间近似分辨率无关,
    clamp 边界见 _FEATHER_REF 注释) —— F13 的 masks_cache 为二值
    0/255 转浮点, 羽化保证二值掩码也不产生硬边。

启用条件 (wants):
  - enabled=False / regions 缺失或空 → False;
  - ctx.state 无 "region_masks" (非 dict 或空) → False (静默);
  - 无任一区域同时满足「掩码存在 + 参数有实际效果 (exposure/saturation/warmth
    非全零)」→ False。
"""
from __future__ import annotations

import logging

import cv2
import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_GAMMA_RGB

_LOGGER = logging.getLogger(__name__)

# gamma 域增益近似的幂常数 (见模块 docstring: gain^2.2 ≈ 线性域 2^ev)
_GAMMA = 2.2

# 掩码羽化: sigma = clip(长边/512, 1, 8)。注意 (S-1, M1 评审): "相对过渡带
# 宽度与分辨率无关"仅在长边 512..4096 区间近似成立 —— 区间内 sigma 随长边
# 线性缩放, 相对宽度恒 ≈1/512; <512 被 clamp 到下限 1px (核再小羽化退化为
# 亚像素噪声, 无几何意义), >4096 被 clamp 到上限 8px (核成本与过渡带平衡),
# 两端相对宽度随分辨率反向变化 (48px 图相对宽 1.562% vs 6000px 0.133%)。
# 预览/导出典型工作区 (1024/2048 预览, 3000-6000 导出) 处于或近该区间。
_FEATHER_REF = 512.0
_FEATHER_SIGMA_MIN = 1.0
_FEATHER_SIGMA_MAX = 8.0

_ALLOWED_REGION_KEYS = ("exposure", "saturation", "warmth")
_EXPOSURE_LIMIT = 2.0     # EV ∈ [-2, 2]
_SATURATION_LIMIT = 1.0   # saturation ∈ [-1, 1]
_WARMTH_LIMIT = 1.0       # warmth ∈ [-1, 1] (负=冷调, 正=暖调)

# warmth 意图级近似 (R13): 满档 |warmth|=1 的通道增益幅度, 锚定白平衡
# warmth 标定的暖方向通道斜率 (white_balance.apply_warmth 缺省斜率
# g_slope=0.10 / b_slope=0.26 —— 冻结锚点 wb_B∈[1.79, 2.287] 的暖黄方向;
# r_slope 缺省 0, R 通道不动, R 增益由 WB 链负责)。gamma 域直接乘增益,
# 不做色温线性化往返 (与 exposure 的 2^(ev/2.2) 同级意图近似纪律)。
_WARMTH_GAIN_G = 0.10
_WARMTH_GAIN_B = 0.26

# 区域参数域单源 (S-3, M1 评审): loop._apply_decide_params 对 decide 写出的
# region.* 值做映射侧钳制时复用本表, 防双份常量漂移。
REGION_PARAM_LIMITS = {"exposure": _EXPOSURE_LIMIT,
                       "saturation": _SATURATION_LIMIT,
                       "warmth": _WARMTH_LIMIT}


class MaskContentError(ValueError):
    """掩码内容违约 (含 NaN/Inf 等非有限值)。

    与形态违约 (非 HxW, 直接 ValueError 显式失败便于排查) 区分: 内容坏
    由 process 捕获走 warn+跳过降级 —— 与 "掩码内容坏→跳过不炸链" 的
    声明意图一致 (I-3, M1 评审: NaN 会经 clip/GaussianBlur 污染整帧)。
    """


def _gamma_gain(ev: float) -> float:
    """EV → gamma 域增益 2^(ev/2.2) (线性域等效 ≈ 2^ev, 纯幂近似)。"""
    return float(2.0 ** (float(ev) / _GAMMA))


def _warmth_gains(warmth: float) -> np.ndarray:
    """区域暖色意图 → gamma 域 RGB 通道增益 (float32 (3,))。

    正 = 暖调: G 上 / B 下 (白平衡 warmth 标定的暖黄方向, 幅度锚
    _WARMTH_GAIN_G/_B); 负 = 冷调 (对称反向); 0 = 恒等 [1,1,1]。
    意图级近似 (R13): 不做色温线性化往返, 与 exposure 同级纪律。
    """
    w = max(-1.0, min(1.0, float(warmth)))
    return np.array([1.0,
                     1.0 + _WARMTH_GAIN_G * w,
                     1.0 - _WARMTH_GAIN_B * w], dtype=np.float32)


def _apply_saturation(img: np.ndarray, saturation: float) -> np.ndarray:
    """HSV S 缩放 (RGB float32 0..1 → HSV, S' = clip(S*(1+sat), 0, 1) → RGB)。

    中性像素 (S=0) 严格不受影响; 饱和度增方向有 clip 兜底 (S≤1)。
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    h, s, v = cv2.split(hsv)
    s = np.clip(s * (1.0 + float(saturation)), 0.0, 1.0)
    return cv2.cvtColor(cv2.merge([h, s, v]), cv2.COLOR_HSV2RGB)


@register_stage("region_adjust", order=57,
                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)
class RegionAdjustStage(Stage):
    """掩码驱动的分区曝光/暖色/饱和度调整 (M1 主体, 默认关)。"""

    param_schema = {
        "enabled": {"type": "bool"},
        # regions 为嵌套 dict (prompt → {exposure, saturation}); graph 的
        # 参数校验器只支持标量类型, 结构校验在 _regions() (非法抛 ValueError,
        # 沿 _curve_dict_check / skin._mask_fn 惯例)。
        "regions": {"type": "dict"},
    }

    def default_params(self):
        return {"enabled": False, "regions": {}}

    # ---- 参数规范化 ----

    def _regions(self, ctx: StageContext) -> dict:
        """regions 参数 → 规范化 {prompt: {"exposure": float, "saturation": float,
        "warmth": float}}。

        结构非法 (非 dict / 区域值非 dict / 未知键 / 数值非法或越界) 抛
        ValueError; regions 整体缺失或空 dict 返回 {} (wants 据此直通)。
        """
        raw = self.p(ctx, "regions", {})
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            return {}
        out: dict = {}
        for prompt, spec in raw.items():
            if not isinstance(spec, dict):
                raise ValueError(
                    f"[{self.name}] regions[{prompt!r}] 需为 dict, "
                    f"实际 {type(spec).__name__}")
            unknown = set(spec) - set(_ALLOWED_REGION_KEYS)
            if unknown:
                raise ValueError(
                    f"[{self.name}] regions[{prompt!r}] 含未知键 {sorted(unknown)}; "
                    f"合法键: {list(_ALLOWED_REGION_KEYS)}")
            adj = {key: 0.0 for key in _ALLOWED_REGION_KEYS}
            for key in _ALLOWED_REGION_KEYS:
                if key not in spec:
                    continue
                val = spec[key]
                if not isinstance(val, (int, float)) or isinstance(val, bool):
                    raise ValueError(
                        f"[{self.name}] regions[{prompt!r}].{key} 需为数值, "
                        f"实际 {val!r}")
                val = float(val)
                limit = REGION_PARAM_LIMITS[key]
                if not (-limit <= val <= limit):
                    raise ValueError(
                        f"[{self.name}] regions[{prompt!r}].{key}={val} "
                        f"越界 [-{limit}, {limit}]")
                adj[key] = val
            out[str(prompt)] = adj
        return out

    # ---- 门控 ----

    def wants(self, ctx: StageContext) -> bool:
        if not bool(self.p(ctx, "enabled", False)):
            return False
        regions = self._regions(ctx)
        if not regions:
            return False
        masks = ctx.state.get("region_masks")
        if not isinstance(masks, dict) or not masks:
            # 掩码通道缺失 (F13 未注入) → 静默跳过, 无掩码 = 无区域效果
            return False
        for prompt, adj in regions.items():
            if (adj["exposure"] == 0.0 and adj["saturation"] == 0.0
                    and adj["warmth"] == 0.0):
                continue
            if prompt in masks:
                return True
        return False

    # ---- 掩码准备 ----

    @staticmethod
    def _prepare_mask(mask, h: int, w: int) -> np.ndarray:
        """掩码 → float32 HxW 0..1 + 高斯羽化 (禁硬边, 见模块 docstring)。

        - 接受 HxW / HxWx1; 分辨率与图不同 → 缩放到 (h, w) (下采样
          INTER_AREA / 上采样 INTER_LINEAR, 与 F13 适配器同语义, S-2);
        - 非有限值 (NaN/Inf) 抛 MaskContentError (I-3, 由 process 降级跳过);
        - 羽化 sigma = clip(长边/512, 1, 8): 二值掩码也被平滑为软掩码,
          已软的掩码近似不变 (低频成分经高斯核几乎无衰减)。
        """
        m = np.asarray(mask, dtype=np.float32)
        if m.ndim == 3 and m.shape[2] == 1:
            m = m[:, :, 0]
        if m.ndim != 2 or m.size == 0:
            raise ValueError(
                f"[region_adjust] 掩码需为非空 HxW/HxWx1, 实际 shape {m.shape}")
        # I-3 (M1 评审): NaN/Inf 经 clip 不清除、GaussianBlur 空间扩散、
        # 且 NaN 比较恒 False 绕过 max<=0 守卫 → 单点 NaN 污染整帧。
        # 非有限值在此拦截, 由 process 走 warn+跳过降级 (MaskContentError)。
        if not np.isfinite(m).all():
            raise MaskContentError(
                "[region_adjust] 掩码含非有限值 (NaN/Inf), 按坏掩码降级")
        if m.shape != (h, w):
            # S-2 (M1 评审): 兜底 resize 核与 F13 适配器同语义 —— 下采样
            # INTER_AREA (面积平均, 保覆盖比例), 上采样 INTER_LINEAR。
            interp = (cv2.INTER_AREA if m.shape[0] > h else cv2.INTER_LINEAR)
            m = cv2.resize(m, (w, h), interpolation=interp)
        m = np.clip(m, 0.0, 1.0)
        long_edge = float(max(h, w))
        sigma = min(_FEATHER_SIGMA_MAX,
                    max(_FEATHER_SIGMA_MIN, long_edge / _FEATHER_REF))
        return cv2.GaussianBlur(m, (0, 0), sigma)

    # ---- 主体 ----

    def process(self, ctx: StageContext) -> None:
        regions = self._regions(ctx)
        masks = ctx.state.get("region_masks")
        if not isinstance(masks, dict) or not masks:
            return
        out = np.clip(np.asarray(ctx.image), 0.0, 1.0).astype(np.float32)
        h, w = out.shape[:2]
        applied: list = []
        coverage: dict = {}
        for prompt, adj in regions.items():
            ex, sat, wm = adj["exposure"], adj["saturation"], adj["warmth"]
            if ex == 0.0 and sat == 0.0 and wm == 0.0:
                continue          # 零效果区域: 不触碰像素
            raw_mask = masks.get(prompt)
            if raw_mask is None:
                continue          # 该区域无掩码: 静默跳过
            try:
                m = self._prepare_mask(raw_mask, h, w)
            except MaskContentError as exc:
                # I-3 (M1 评审): 掩码内容坏 (NaN/Inf) → warn+跳过该区域,
                # 不炸整链 (NaN 若穿透会污染整帧输出)
                _LOGGER.warning(
                    "[region_adjust] 区域 %r 掩码内容非法, 跳过: %s",
                    prompt, exc)
                continue
            except ValueError:
                raise             # 掩码形态违约 (非 HxW): 显式失败便于排查
            except Exception as exc:   # 其余掩码坏 → 该区域跳过, 不炸整链
                _LOGGER.warning(
                    "[region_adjust] 区域 %r 掩码不可用, 跳过: %s: %s",
                    prompt, type(exc).__name__, exc)
                continue
            if float(m.max()) <= 0.0:
                continue          # 全零掩码 = 无该区域
            adjusted = out
            if ex != 0.0:
                adjusted = adjusted * _gamma_gain(ex)
            if wm != 0.0:
                adjusted = adjusted * _warmth_gains(wm)
            if sat != 0.0:
                adjusted = _apply_saturation(adjusted, sat)
            adjusted = np.clip(adjusted, 0.0, 1.0).astype(np.float32)
            w3 = m[:, :, None]
            out = out * (1.0 - w3) + adjusted * w3
            applied.append(prompt)
            coverage[str(prompt)] = float(m.mean())
        if not applied:
            return                # 恒等直通: 不 set_image ("未写即未变")
        ctx.set_image(out.astype(np.float32), DOMAIN_GAMMA_RGB)
        # 指标 (F14 闭环验证用: decide 写 region 键 → 渲染结果可观测);
        # 直接调用 process (未经理 run 入链) 时无结果可挂, 静默略过
        if ctx.results:
            result = ctx.results[-1]
            result.metrics["regions_applied"] = applied
            result.metrics["mask_coverage"] = coverage
