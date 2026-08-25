"""Stage compose (order=22) —— 构图前置 (linear_rgb → linear_rgb)。

管线位置: whitebalance(order=20) 之后、huesat(order=25) 之前。
此时已完成 WB+DCP 色彩链路，后续影调/色彩调整全部作用于构图后的像素，
vision/mask 几何与最终画面保持一致。

支持参数:
  mode            "ratio" | "free" | "auto_level"
  ratio           "3:2" / "16:9" / 数字宽高比 (mode=ratio)
  center          [x, y] 归一化裁剪中心 (0..1, 默认 [0.5, 0.5])
  rotation        旋转角度 (°)，通过 cv2.warpAffine + INTER_LANCZOS4 实现
  horizontal_flip 水平翻转
  vertical_flip   垂直翻转
  x / y / width / height  自由裁剪矩形 (像素, mode=free)

实现约束:
  - 纯整数裁剪/翻转走 numpy 切片 / np.flip，禁止插值，必须逐位一致。
  - 旋转固定使用 cv2.warpAffine + INTER_LANCZOS4，边界策略固定为
    cv2.BORDER_REFLECT_101 (写入 ctx.state / 元数据)。
  - 输出几何元数据 (原始尺寸 / 最终尺寸 / crop 矩形 / 仿射矩阵) 写入
    ctx.state['compose']，供 Vision 绑定 mask 坐标。
"""
from __future__ import annotations

from typing import Any, Sequence

import cv2
import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_LINEAR_RGB

_BORDER_MODE = cv2.BORDER_REFLECT_101
_BORDER_NAME = "reflect101"
_INTERPOLATION = cv2.INTER_LANCZOS4


def parse_ratio(ratio: float | str | None) -> float | None:
    """解析 ratio 参数为宽高比 (width/height)。

    支持 "3:2"、"16:9"、纯数字字符串或数值；空 / "original" / "full" / None
    表示不按比例裁剪。
    """
    if ratio is None:
        return None
    if isinstance(ratio, str):
        s = ratio.strip()
        if not s or s.lower() in ("none", "original", "full", "auto"):
            return None
        if ":" in s:
            parts = s.split(":")
            if len(parts) != 2:
                raise ValueError(f"ratio 格式应为 '宽:高'，实际: {ratio!r}")
            a = float(parts[0])
            b = float(parts[1])
            if b == 0:
                raise ValueError("ratio 高度不能为 0")
            return a / b
        return float(s)
    return float(ratio)


def compute_crop_rect(h: int, w: int, mode: str,
                      ratio: float | str | None = None,
                      center: Sequence[float] = (0.5, 0.5),
                      x: float = 0.0, y: float = 0.0,
                      width: float = 0.0, height: float = 0.0
                      ) -> tuple[int, int, int, int]:
    """计算裁剪矩形 (x, y, width, height)。

    - mode=free: 使用 x/y/width/height 像素矩形，越界自动裁剪到图像内。
    - mode=ratio: 以最大内接指定宽高比的矩形、围绕 center 定位。
    - mode=auto_level: 当前无 horizon 检测强改; 返回全幅 (仅旋转可生效)。
    """
    if mode == "free":
        if width is None or height is None or width <= 0 or height <= 0:
            return 0, 0, w, h
        x0 = int(round(float(x)))
        y0 = int(round(float(y)))
        cw = int(round(float(width)))
        ch = int(round(float(height)))
        x0 = int(np.clip(x0, 0, max(w - 1, 0)))
        y0 = int(np.clip(y0, 0, max(h - 1, 0)))
        cw = int(np.clip(cw, 1, max(w - x0, 1)))
        ch = int(np.clip(ch, 1, max(h - y0, 1)))
        return x0, y0, cw, ch

    if mode == "ratio":
        aspect = parse_ratio(ratio)
        if aspect is None or aspect <= 0:
            return 0, 0, w, h
        if w / h >= aspect:
            # 图更宽: 用满高度，宽度按目标比例收窄
            ch = h
            cw = max(1, int(round(h * aspect)))
        else:
            # 图更窄: 用满宽度，高度按目标比例收窄
            cw = w
            ch = max(1, int(round(w / aspect)))
        cw = min(cw, w)
        ch = min(ch, h)
        cx = float(center[0]) * w
        cy = float(center[1]) * h
        x0 = int(round(cx - cw / 2.0))
        y0 = int(round(cy - ch / 2.0))
        x0 = int(np.clip(x0, 0, max(w - cw, 0)))
        y0 = int(np.clip(y0, 0, max(h - ch, 0)))
        return x0, y0, cw, ch

    # auto_level（占位）: 不自动改构图，只允许显式 rotation
    return 0, 0, w, h


def apply_flips(img: np.ndarray, horizontal: bool, vertical: bool) -> np.ndarray:
    """纯整数轴翻转: np.flip, 无插值。"""
    if horizontal:
        img = np.flip(img, axis=1)
    if vertical:
        img = np.flip(img, axis=0)
    return img


def apply_rotation(img: np.ndarray, angle: float) -> tuple[np.ndarray, np.ndarray | None]:
    """固定口径旋转: cv2.warpAffine + INTER_LANCZOS4 + BORDER_REFLECT_101。

    返回 (输出图像, 2x3 仿射矩阵或 None)。尺寸保持不变，旋转在裁剪后的
    同尺寸画布内进行，避免旋转引出的额外画幅造成同一位置比较失真。
    """
    angle = float(angle or 0.0)
    if abs(angle) < 1e-9:
        return img, None
    # cv2.warpAffine 要求内存连续; 纯复制不改像素，翻转后的视图先归一化再旋转。
    img = np.ascontiguousarray(img)
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    out = cv2.warpAffine(img, m, (w, h), flags=_INTERPOLATION,
                         borderMode=_BORDER_MODE)
    return out, m


# ---- auto_level 地平线检测 (t28) ----
AUTO_LEVEL_MAX_ANGLE = 8.0   # |校正角| 钳制: 超过视为无可靠地平线 -> 回退 0
_AUTO_LEVEL_STEP = 0.25      # 角度扫描步长 (°)
_AUTO_LEVEL_DS = 256         # 检测用下采样长边
_AUTO_LEVEL_MARGIN = 4.0     # 扫描范围超出钳制的余量: 端点钉死可判"超角"
AUTO_LEVEL_DEFAULT_MIN_CONFIDENCE = 0.35


def detect_horizon_angle(img: np.ndarray,
                         max_angle: float = AUTO_LEVEL_MAX_ANGLE,
                         step: float = _AUTO_LEVEL_STEP,
                         ds_long: int = _AUTO_LEVEL_DS) -> tuple[float, float]:
    """行梯度投影统计估计主导地平线滚转角 (方法选型见 t28 实测, 备选 HoughLinesP)。

    流程: 灰度下采样 (INTER_AREA) -> Sobel 横向梯度幅值 -> 对 theta ∈
    [-max_angle, +max_angle] 扫描旋转幅值图, 行和方差最大的 theta 即把
    地平线转到水平所需的角度。

    扫描范围 [-max_angle-MARGIN, +max_angle+MARGIN]: 真实倾角超过钳制时
    峰会钉死在 ±max_angle 附近之外, 由调用方据返回值判"超角回退",
    避免把 20° 斜线误校成 8° 残斜。

    返回 (phi, confidence):
      phi         把画面摆平应施加的旋转角 (°), 直接可喂 apply_rotation;
                  符号约定与 cv2.getRotationMatrix2D 一致。
      confidence  峰突出度 (smax-smed)/(smax-smin+eps) ∈ [0,1]; 无地平线
                  场景 (人像特写/静物) 各角度得分接近, 置信度趋 0。
    """
    gray = img if img.ndim == 2 else (
        0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2])
    gray = np.clip(np.asarray(gray, dtype=np.float32), 0.0, None)
    h, w = gray.shape[:2]
    scale = float(ds_long) / float(max(h, w))
    if scale < 1.0:
        gray = cv2.resize(gray, (max(1, int(round(w * scale))),
                                 max(1, int(round(h * scale)))),
                          interpolation=cv2.INTER_AREA)
    mag = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)).astype(np.float32)
    hh, ww = mag.shape[:2]
    center = (ww / 2.0, hh / 2.0)
    lim = float(max_angle) + float(_AUTO_LEVEL_MARGIN)
    angles = np.arange(-lim, lim + 1e-9, float(step))
    scores = np.empty(len(angles), dtype=np.float64)
    for i, th in enumerate(angles):
        m = cv2.getRotationMatrix2D(center, float(th), 1.0)
        rot = cv2.warpAffine(mag, m, (ww, hh), flags=cv2.INTER_LINEAR,
                             borderMode=cv2.BORDER_REPLICATE)
        scores[i] = float(rot.sum(axis=1).var())
    imax = int(np.argmax(scores))
    smax = float(scores[imax])
    smin = float(scores.min())
    smed = float(np.median(scores))
    conf = (smax - smed) / max(smax - smin, 1e-9)
    return float(angles[imax]), float(np.clip(conf, 0.0, 1.0))


@register_stage("compose", order=22,
                domain_in=DOMAIN_LINEAR_RGB, domain_out=DOMAIN_LINEAR_RGB)
class ComposeStage(Stage):
    """构图预处理 Stage: 裁剪 / 翻转 / 旋转 (linear_rgb → linear_rgb)。"""

    name = "compose"

    param_schema = {
        "mode": {"type": "str", "choices": ["ratio", "free", "auto_level"]},
        "ratio": {"type": "float_or_str"},
        "center": {"type": "float_or_str"},
        "rotation": {"type": "float", "min": -360.0, "max": 360.0},
        "horizontal_flip": {"type": "bool"},
        "vertical_flip": {"type": "bool"},
        "x": {"type": "float"},
        "y": {"type": "float"},
        "width": {"type": "float"},
        "height": {"type": "float"},
        # auto_level: 地平线置信度门限 (低于则回退恒等, 不动构图)
        "min_confidence": {"type": "float", "min": 0.0, "max": 1.0},
    }

    def default_params(self) -> dict[str, Any]:
        # 默认不改变画面: free + 全幅 + 无旋转/翻转。
        return {
            "mode": "free",
            "ratio": None,
            "center": [0.5, 0.5],
            "rotation": 0.0,
            "horizontal_flip": False,
            "vertical_flip": False,
            "x": 0.0,
            "y": 0.0,
            "width": 0.0,
            "height": 0.0,
            "min_confidence": AUTO_LEVEL_DEFAULT_MIN_CONFIDENCE,
        }

    def process(self, ctx: StageContext) -> None:
        img = ctx.image
        if img is None or img.ndim != 3 or img.shape[2] != 3:
            raise ValueError("compose Stage 需要 HxWx3 的 linear_rgb 图像")
        h, w = img.shape[:2]

        mode = self.p(ctx, "mode", "free")
        rotation = float(self.p(ctx, "rotation", 0.0) or 0.0)
        horizontal_flip = bool(self.p(ctx, "horizontal_flip", False))
        vertical_flip = bool(self.p(ctx, "vertical_flip", False))

        # auto_level (t28): 地平线检测自动摆平。|校正角|>8° 或置信度不足
        # (含人像特写/静物等无地平线场景) 时回退 theta=0 不动构图。
        al_meta = None
        if mode == "auto_level":
            min_conf = float(self.p(ctx, "min_confidence",
                                    AUTO_LEVEL_DEFAULT_MIN_CONFIDENCE))
            phi, conf = detect_horizon_angle(img)
            reliable = (abs(phi) <= AUTO_LEVEL_MAX_ANGLE
                        and conf >= min_conf)
            if reliable:
                rotation += phi
                tag = "high"
            else:
                tag = "low"
            al_meta = {
                "auto_level": True,
                "auto_level_detected_angle": round(float(phi), 3),
                "auto_level_applied": round(float(rotation), 3),
                "auto_level_confidence": tag,
                "auto_level_confidence_value": round(float(conf), 4),
            }

        x0, y0, cw, ch = compute_crop_rect(
            h, w,
            mode=mode,
            ratio=self.p(ctx, "ratio", None),
            center=self.p(ctx, "center", [0.5, 0.5]),
            x=float(self.p(ctx, "x", 0.0) or 0.0),
            y=float(self.p(ctx, "y", 0.0) or 0.0),
            width=float(self.p(ctx, "width", 0.0) or 0.0),
            height=float(self.p(ctx, "height", 0.0) or 0.0),
        )

        out = img[y0:y0 + ch, x0:x0 + cw]
        out = apply_flips(out, horizontal_flip, vertical_flip)
        matrix = None
        if abs(rotation) > 1e-9:
            out, matrix = apply_rotation(out, rotation)

        changed = (x0 != 0 or y0 != 0 or cw != w or ch != h
                   or horizontal_flip or vertical_flip or abs(rotation) > 1e-9)
        if changed:
            # 保持后续 Stage 拿到连续内存（纯复制，不改变像素值/不插值）。
            out = np.ascontiguousarray(out)
            ctx.set_image(out, DOMAIN_LINEAR_RGB)

        final_h, final_w = out.shape[:2]
        transform = (matrix.tolist() if matrix is not None
                     else [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        geom = {
            "mode": mode,
            "original_size": [h, w],
            "final_size": [final_h, final_w],
            "crop_rect": {"x": x0, "y": y0, "width": cw, "height": ch},
            "crop_rect_list": [x0, y0, cw, ch],
            "crop": [x0, y0, cw, ch],
            "rotation": rotation,
            "horizontal_flip": horizontal_flip,
            "vertical_flip": vertical_flip,
            "transform_matrix": transform,
            "affine_matrix": transform,
            "border_mode": _BORDER_NAME,
            "border_mode_id": int(_BORDER_MODE),
            "width": final_w,
            "height": final_h,
        }
        if al_meta is not None:
            geom.update(al_meta)
        ctx.state["compose"] = geom
        ctx.state["compose_geometry"] = geom
        metrics = {
            "changed": changed,
            "crop": [x0, y0, cw, ch],
            "rotation": rotation,
            "border_mode": _BORDER_NAME,
            "final_size": [final_h, final_w],
        }
        if al_meta is not None:
            metrics.update(al_meta)
        if ctx.results:
            ctx.results[-1].metrics = metrics
