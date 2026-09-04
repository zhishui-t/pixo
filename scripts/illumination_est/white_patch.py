"""White-Patch (白斑点) 光照估计 (经典法, 纯 numpy) —— 阶段三 §2。

假设 (Land 1977 / Retinex): 场景中最亮的中性面 (白纸/高光) 反射全部光源 →
高亮度分位像素的通道均值即光源色。实现取亮度 (max 通道) 前 (1−q) 分位像素
的均值 (q 默认 0.995, 单 512 图 ~900 px) —— 逐通道 max 是原始定义但对噪声
与镜面高光过于敏感, 分位均值是标准稳健化 (评估口径注释)。

确定性: 分位 + 布尔掩码均值, 纯 numpy, 无随机 (同亮度并列由 np.percentile
确定性排序承载)。
"""
from __future__ import annotations

import numpy as np

from wb_inverse import cam_light_to_temp_tint


def estimate_light(rgb_linear: np.ndarray, quantile: float = 0.995,
                   clip_hi: float = 0.985) -> np.ndarray:
    """线性域图 → 高亮分位像素均值光源色向量。相机原生域输入时先排除贴顶
    饱和像素 (任一通道 ≥ clip_hi; 其通道比例失真会拉平光源方向)。"""
    img = np.asarray(rgb_linear, dtype=np.float64)
    if clip_hi is not None and img.size and img.max() > clip_hi:
        keep = img.max(axis=-1) < clip_hi        # (H,W) 或 (K,)
        img = img[keep]                          # 排除后可能变 (K,3) 二维
        if img.shape[0] == 0:
            return np.array([1.0, 1.0, 1.0])     # 全图饱和: 无信息, 返回中性
    lum = img.max(axis=-1)                       # 两种形状均得 2 维亮度图
    thr = float(np.quantile(lum, quantile))
    sel = lum >= thr
    if not sel.any():                # 理论不可达 (分位恒有定义), 防御兜底
        sel = lum >= lum.max()
    e = img[sel].mean(axis=0)
    return np.maximum(e, 1e-9)


def est_cct(rgb_linear: np.ndarray, dcp_profile, quantile: float = 0.995
            ) -> tuple[float, float]:
    """渲染图 → 估计光源 (白斑点) → (temp K, tint) (pixo WB 参数域)。"""
    return cam_light_to_temp_tint(estimate_light(rgb_linear, quantile=quantile),
                                   dcp_profile)
