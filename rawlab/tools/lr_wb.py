"""tools/lr_wb.py —— Lightroom 色温/色调读数 → 相机 WB 系数换算工具。

用途:把 LR「修改照片」面板的 Temperature(K)/Tint(-150..+150)读数换算成
rawlab 引擎可用的手动白平衡系数 [r, g, b](G=1),用于与 LR 观感对齐标定。

换算链:
  1. 色温 K → CIE 黑体轨迹 xy (Kim et al. 近似公式)。
  2. Tint → uv 空间沿等温线偏移 (±150 ≈ ±0.010 uv)。
  3. xy → XYZ → inv(ColorMatrix) → 相机对该光源的中性响应。
  4. WB = 1/响应, 归一化 G=1 (白平衡=响应的倒数)。

注意:LR 自身的 Temp/Tint→相机系数映射是 Adobe 每机标定的私有模型,
本工具用 DCP ColorMatrix 反推,同一读数下与 LR 渲染可能有小幅差异;
对色温方向的影响为主, tint 方向为近似。精确对齐最终以成片对照为准。

用法: python rawlab/tools/lr_wb.py <temp_k> <tint>
"""
from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from rawlab.dcp import load_dcp
from rawlab.engine.color import temp_to_xy, temp_tint_to_wb

DEFAULT_DCP = (r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera"
               r"\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp")


def lr_temp_tint_to_wb(prof, temp_k: float, tint: float) -> np.ndarray:
    """LR 读数 → 相机 WB 系数 [r, g, b] (G=1)。

    正解实现见 engine.color.temp_tint_to_wb (temp_to_xy 亦从 engine.color 导入,
    此处仅保留工具入口与 CLI)。
    """
    return temp_tint_to_wb(prof, temp_k, tint)


if __name__ == "__main__":
    prof = load_dcp(DEFAULT_DCP)
    temp_k = float(sys.argv[1]) if len(sys.argv) > 1 else 2971.0
    tint = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    wb = lr_temp_tint_to_wb(prof, temp_k, tint)
    print(f"LR {temp_k:.0f}K tint {tint:+.0f} -> wb = "
          f"[{wb[0]:.4f}, 1.0, {wb[2]:.4f}]")
