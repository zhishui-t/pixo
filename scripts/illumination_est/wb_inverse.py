"""估计光源色 (相机原生线性域) → pixo WB 参数域 (cct_k, tint) 的逆链。

口径 (阶段三 §2): 经典光照估计法直接作用在 **decode 后未白平衡的相机原生
线性域图** (与 as_shot 系数同域 —— camera_wb 本身就是相机域中和系数)。估
计出的光源响应 e_cam 的倒数即相机域 WB:

    wb_est = (1/e_cam) 归一 G=1  →  (temp K, tint) = wb_to_temp_tint(prof, wb_est)

wb_to_temp_tint 是 core.color.temp_tint_to_wb 的现成逆函数 (scipy
least_squares 多起点, 缺 scipy 回退网格) —— 正逆链参数域严格对齐 pixo
whitebalance manual/temp/tint。域一致性 (评估的变量隔离): as_shot 与估计
都表达为相机域 WB 系数, 无跨域换算误差。

恒等性 (tests/unit/test_illumination_est.py): 任取 (t0, ti0),
temp_tint_to_wb 的倒数即相机域光源响应, 喂回 cam_light_to_temp_tint 精确
还原 (t0, ti0) —— 线性往返, 无近似。

纯 numpy (scipy 仅经 wb_to_temp_tint 可选路径); torch 不进本目录。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_SCRIPTS = Path(__file__).resolve().parents[1]
_SRC = _SCRIPTS / "src"
for _p in (str(_SRC), str(_SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from pixo.render.core.color import (wb_to_temp_tint, xy_to_cct, xy_to_xyz,
                                    _calibration_temperatures,
                                    _interp_1_over_t)


def _interp_cm(prof, cct: float) -> np.ndarray:
    """DCP ColorMatrix 按 CCT 的 1/t 插值 (temp_tint_to_wb 内段同式; cm2 与
    cm1 全同时退化为恒用 cm1)。"""
    cm1 = np.asarray(getattr(prof, "color_matrix1"),
                     dtype=np.float64).reshape(3, 3)
    cm2 = getattr(prof, "color_matrix2", None)
    cm2 = None if cm2 is None else np.asarray(cm2,
                                              dtype=np.float64).reshape(3, 3)
    if cm2 is not None and np.allclose(cm1, cm2):
        cm2 = None
    t1, t2 = _calibration_temperatures(prof)
    return _interp_1_over_t(cm1, cm2, cct, t1, t2)


def scene_xy_to_neutral_wb(xy_scene: tuple[float, float], prof) -> np.ndarray:
    """场景白点 xy → 相机域中和 WB [r,1,b] (temp_tint_to_wb 内段逐式同构;
    供往返自洽验证与"场景白点已知"场景复用)。"""
    cct = xy_to_cct(*xy_scene)
    cm = _interp_cm(prof, cct)
    resp = np.maximum(cm @ xy_to_xyz(*xy_scene), 1e-6)
    wb = 1.0 / resp
    wb = wb / wb[1]
    return np.array([wb[0], 1.0, wb[2]], dtype=np.float64)


def cam_light_to_temp_tint(e_cam: np.ndarray, prof) -> tuple[float, float]:
    """相机域光源响应 (线性, G 可任取) → (temp K, tint) —— pixo whitebalance
    manual 参数域。中和系数 = 1/e_cam 归一 G (von Kries 对角模型)。"""
    e = np.maximum(np.asarray(e_cam, dtype=np.float64).reshape(3), 1e-9)
    wb = 1.0 / e
    wb = wb / wb[1]
    return wb_to_temp_tint(prof, wb)
