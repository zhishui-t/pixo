"""YOLOE 主体检测集成 (阶段2) —— 复用 guanlan 资产。

将 guanlan 的 yoloe_det 作为可独立调用的检测器封装。
检测输入: 8bit BGR 图 → 输出主体框 (归一化) + 人脸框。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

# guanlan 项目路径 (复用其模型与模块; 环境变量 RAWLAB_GUANLAN_ROOT 优先, 旧值仅作回退)
_GUANLAN_ROOT = os.environ.get("RAWLAB_GUANLAN_ROOT", r"K:\work\project\guanlan")
if _GUANLAN_ROOT not in sys.path:
    sys.path.insert(0, _GUANLAN_ROOT)
if str(Path(_GUANLAN_ROOT) / "src") not in sys.path:
    sys.path.insert(0, str(Path(_GUANLAN_ROOT) / "src"))

_detector = None


def get_detector():
    """懒加载 guanlan YoloeDetector (GPU)。

    强制 guanlan 的模型路径解析到其 models/ 目录 (不依赖 cwd)。
    """
    global _detector
    if _detector is None:
        import os
        os.chdir(_GUANLAN_ROOT)  # yoloe_det 按 cwd 相对路径找 models/
        from vision.yoloe_det import get_yoloe_detector
        _detector = get_yoloe_detector()
    return _detector


def detect_subjects(bgr8: np.ndarray,
                    person_labels=("person", "face")) -> Tuple[List[List[float]], List[List[float]]]:
    """检测主体框 (归一化 [l,t,r,b]) 与人脸框。

    Returns: (subject_boxes, face_boxes)
    主体框: 全部检出框 (面积排序, 供曝光分析选最大);
    人脸框: label 含 face/person 的框 (曝光优先)。
    """
    try:
        det = get_detector()
        dets = det.detect(bgr8)
    except Exception as e:
        print(f"[yoloe] 检测失败, 回退无主体: {e}")
        return [], []

    subject_boxes: List[List[float]] = []
    face_boxes: List[List[float]] = []
    for o in dets:
        label = str(o.get("label", ""))
        box = o.get("box")
        if not box or len(box) != 4:
            continue
        box = [float(v) for v in box]
        subject_boxes.append(box)
        if any(k in label for k in ("person", "face", "human")):
            face_boxes.append(box)
    return subject_boxes, face_boxes


def detect_from_raw(raw_path: str, wb_bgr: Optional[np.ndarray] = None) -> Tuple[List[List[float]], List[List[float]]]:
    """从 RAW 路径检测 (用传入的已渲染 BGR 图, 不重复解码)。"""
    if wb_bgr is None:
        raise ValueError("需传入已渲染的 BGR 图 (检测输入=渲染图)")
    return detect_subjects(wb_bgr)
