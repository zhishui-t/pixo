"""相机内嵌 JPEG 预览提取 —— 自研渲染 vs 相机预览验收的公共工具。

从 rawlab/debug/batch_iter.py 升格 (2026-08 审核): tools/verify_engine.py 与
tools/make_contact_sheet.py 生产依赖 camera_preview, debug/ 属一次性脚本不应被依赖。
原小批量曝光迭代主流程保留在 debug/batch_iter.py (历史验收, 不入库)。
"""
from __future__ import annotations

import numpy as np
import rawpy


def camera_preview(raw_path):
    """相机内嵌 JPEG 预览, 旋转回传感器方向 (与 rawpy 渲染对齐)。

    flip=5 → 缩略图逆时针 90°; flip=6 → 顺时针 90°; flip=3 → 180°。
    2026-08-15 修复: 竖构图照片 (flip≠0) 之前对位全错, 残差虚高。
    """
    import cv2
    with rawpy.imread(raw_path) as raw:
        thumb = raw.extract_thumb()
        flip = raw.sizes.flip
    if thumb.format == rawpy.ThumbFormat.JPEG:
        arr = cv2.imdecode(np.frombuffer(thumb.data, np.uint8), cv2.IMREAD_COLOR)
        arr = cv2.cvtColor(arr, cv2.COLOR_BGR2RGB)
        if flip == 5:
            arr = np.rot90(arr)
        elif flip == 6:
            arr = np.rot90(arr, -1)
        elif flip == 3:
            arr = np.rot90(arr, 2)
        return arr
    return None
