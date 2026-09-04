"""Gray-World 光照估计 (经典法, 纯 numpy) —— 阶段三 §2 评估原型。

假设: 场景平均反射率在中性 (灰) 附近 → 相机原生线性域逐通道均值即光源响应。
输出对齐 pixo WB 参数域: est_cct(rgb_linear, dcp_profile) → (cct_k, tint)
(经 wb_inverse.cam_light_to_temp_tint, wb_to_temp_tint 逆链)。

确定性: 纯 numpy 线性运算, 无随机、无权重。
"""
from __future__ import annotations

import numpy as np

from wb_inverse import cam_light_to_temp_tint


def estimate_light(rgb_linear: np.ndarray) -> np.ndarray:
    """线性 sRGB 图 (H,W,3) → 光源色向量 (逐通道均值, von Kries 中和 = 1/e)。"""
    img = np.asarray(rgb_linear, dtype=np.float64)
    m = img.reshape(-1, 3).mean(axis=0)
    return np.maximum(m, 1e-9)


def est_cct(rgb_linear: np.ndarray, dcp_profile) -> tuple[float, float]:
    """渲染图 → 相机域光源响应 → (temp K, tint) (pixo WB 参数域)。"""
    return cam_light_to_temp_tint(estimate_light(rgb_linear), dcp_profile)
