"""engine.decode —— RAW 解码 (采集层, 非 Style 插件)。

原则:
  - output_color=raw 拿纯相机 RGB (不做任何色彩矩阵), 色彩交给 Stage2。
  - use_camera_wb=False, 白平衡系数由 Stage2 自行乘 (AsShot / auto 可控)。
  - AHD demosaic (质量优先); half_size=True 走半分辨率 (闭环诊断/快速预览)。
"""
from __future__ import annotations

from pathlib import Path
from typing import Tuple, Union

import numpy as np
import rawpy


def decode_raw(raw_path: Union[str, Path], half_size: bool = False,
               demosaic: str = "AHD") -> Tuple[np.ndarray, rawpy.RawPy]:
    """解码 RAW → 相机原始 RGB 线性图 (float32, 0-1 相对白电平, 高光可 >1)。"""
    algo = {"AHD": rawpy.DemosaicAlgorithm.AHD,
            "LINEAR": rawpy.DemosaicAlgorithm.LINEAR}.get(demosaic,
                                                          rawpy.DemosaicAlgorithm.AHD)
    raw = rawpy.imread(str(raw_path))
    rgb16 = raw.postprocess(
        use_camera_wb=False,
        output_bps=16,
        output_color=rawpy.ColorSpace.raw,
        no_auto_bright=True,
        half_size=half_size,
        user_wb=[1.0, 1.0, 1.0, 1.0],
        demosaic_algorithm=algo,
    )
    img = rgb16.astype(np.float32) / 65535.0
    return img, raw


def camera_neutral_wb(raw: rawpy.RawPy) -> np.ndarray:
    """相机 As Shot 白平衡系数 (R,G,B 乘数, 归一化 G=1)。

    rawpy.camera_whitebalance 与 Nikon MakerNote WhiteBalanceRBCoeff 一致。
    """
    wb = np.array(raw.camera_whitebalance[:3], dtype=np.float64)
    if wb[1] > 0:
        wb = wb / wb[1]
    return wb.astype(np.float32)
