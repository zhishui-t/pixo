"""Gray-Edge 光照估计 (Minkowski p=1/2, 经典法, 纯 numpy) —— 阶段三 §2。

假设 (van de Weijer & Gevers 2005): 场景边缘 ( ≥p 阶导数) 的 Minkowski 范数
在通道间应相等 → 对梯度幅值图做逐通道 Minkowski p 范数即光源色。一阶
(p=1) 对纹理敏感, 二阶 (p=2) 抑制高频噪声 —— 本模块 est_cct(rgb, prof, p)
支持两种阶, 评估脚本按 p=1/p=2 出两条轨道。

平坦图 (梯度全零) 经典定义退化 → 回退 Gray-World 均值 (结果记入返回注释;
评估口径不受影响: 渲染图恒有纹理)。
确定性: 纯 numpy 差分 + 幂运算, 无随机。
"""
from __future__ import annotations

import numpy as np

from wb_inverse import cam_light_to_temp_tint

from gray_world import estimate_light as _gray_world_light


def estimate_light(rgb_linear: np.ndarray, p: float = 1.0) -> np.ndarray:
    """线性 sRGB 图 → 一阶梯度 Minkowski-p 光源色向量。"""
    img = np.maximum(np.asarray(rgb_linear, dtype=np.float64), 0.0)
    gx = np.abs(np.diff(img, axis=0)) ** p
    gy = np.abs(np.diff(img, axis=1)) ** p
    e = gx.sum(axis=(0, 1)) + gy.sum(axis=(0, 1))
    if not np.all(e > 0):            # 平坦图: 梯度信息为空, 回退 Gray-World
        return _gray_world_light(rgb_linear)
    return np.maximum(e, 1e-30) ** (1.0 / p)


def est_cct(rgb_linear: np.ndarray, dcp_profile, p: float = 1.0
            ) -> tuple[float, float]:
    """渲染图 → 估计光源 (Minkowski-p) → (temp K, tint) (pixo WB 参数域)。"""
    return cam_light_to_temp_tint(estimate_light(rgb_linear, p=p), dcp_profile)
