"""视觉语义报告 (阶段4) —— 轻量化, <2s/张。

来源:
  - YOLOE 主体检测 (GPU 0.5s, guanlan 资产复用)
  - OpenCV 像素统计 (色彩场/影调场/构图/质量, 确定性)
  - 可选 chinese-clip 场景枚举 (需预加载, 较重)

输出结构化 JSON (计划书 §5.2 数据契约)。
"""
from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

import cv2
import numpy as np

from .vision_bridge import detect_subjects


def _to_jsonable(obj):
    """递归转换 numpy 标量 → Python 原生 (JSON 可序列化)。"""
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def _region_stats(mask: np.ndarray, chan: np.ndarray) -> float:
    if mask.sum() < 50:
        return 0.0
    return float(chan[mask].mean())


def build_vision_report(bgr8: np.ndarray,
                        use_clip: bool = False,
                        subject_boxes=None, face_boxes=None) -> Dict:
    """生成视觉语义报告 (bgr8: 渲染后的 BGR 图)。

    subject_boxes / face_boxes: 预检测的归一化 [l,t,r,b] 框 (注入时跳过内部
    YOLOE 检测 —— RetouchAgent 反馈轮复用会话框, 避免每轮重复检测)。
    Returns: 结构化 dict, 字段见计划书 §5.2。
    """
    t0 = time.time()
    h, w = bgr8.shape[:2]
    rgb = cv2.cvtColor(bgr8, cv2.COLOR_BGR2RGB)
    lab = cv2.cvtColor(bgr8, cv2.COLOR_BGR2LAB)
    gray = cv2.cvtColor(bgr8, cv2.COLOR_BGR2GRAY).astype(np.float32)

    report: Dict = {}

    # ── 主体 (YOLOE; 或注入的预检测框) ──
    t1 = time.time()
    subjects = []
    if subject_boxes is not None or face_boxes is not None:
        subj = list(subject_boxes or [])
        faces = list(face_boxes or [])
        subjects = [{
            "box": [round(v, 4) for v in b] if b else [],
            "type": "person" if i < len(faces) else "object",
        } for i, b in enumerate(subj[:5])]
        if faces:
            subjects = [{"box": [round(v, 4) for v in b], "type": "person"}
                        for b in faces[:3]]
    else:
        try:
            subj, faces = detect_subjects(bgr8)
            subjects = [{
                "box": [round(v, 4) for v in b] if b else [],
                "type": "person" if i < len(faces) else "object",
            } for i, b in enumerate(subj[:5])]
            # YOLOE 只给 box, 需 label; 简化: 人脸框优先
            if faces:
                subjects = [{"box": [round(v, 4) for v in b], "type": "person"}
                            for b in faces[:3]]
        except Exception:
            subjects = []
    report["subject"] = {
        "count": len(subjects),
        "persons": len(faces),
        "items": subjects,
    }

    # ── 色彩场 (Lab 分区) ──
    L, a, b = lab[:, :, 0].astype(np.float32), lab[:, :, 1].astype(np.float32), \
        lab[:, :, 2].astype(np.float32)
    # 肤色区 (暖色+饱和)
    hsv = cv2.cvtColor(bgr8, cv2.COLOR_BGR2HSV)
    skin = ((rgb[:, :, 0].astype(int) - rgb[:, :, 2].astype(int) >= 25)
            & (hsv[:, :, 1] >= 40) & (hsv[:, :, 2] >= 60))
    # 天空 (上半区偏蓝) / 绿植
    sky = (b > a + 8) & (b > 60) & (np.arange(h)[:, None] < h * 0.5)
    r_, g_, bl_ = rgb[:, :, 0].astype(int), rgb[:, :, 1].astype(int), rgb[:, :, 2].astype(int)
    green = (g_ > r_ + 6) & (g_ > bl_ + 6) & (g_ > 45)

    report["color"] = {
        "skin_lab": {
            "a": round(_region_stats(skin, a) - 128, 2),
            "b": round(_region_stats(skin, b) - 128, 2),
        } if skin.sum() > 50 else None,
        "sky_dominant": bool(sky.sum() > 0.05 * h * w),
        "green_ratio": round(float(green.mean()), 3),
        "saturation": round(float(hsv[:, :, 1].mean()), 1),
    }

    # ── 影调场 ──
    report["tone"] = {
        "brightness": round(float(gray.mean()), 1),
        "contrast": round(float(gray.std()), 1),
        "hist_shape": _hist_shape(gray),
        "highlight_clip": round(float((gray > 250).mean()), 4),
        "shadow_clip": round(float((gray < 5).mean()), 4),
    }

    # ── 构图 ──
    report["composition"] = {
        "type": _composition_type(gray, subjects),
        "balance": round(_balance_score(gray), 2),
    }

    # ── 质量 ──
    report["quality"] = {
        "sharpness": round(_sharpness(gray), 2),
        "noise": _noise_level(gray),
    }

    report["timing_ms"] = round((time.time() - t0) * 1000)
    return _to_jsonable(report)


def _hist_shape(gray: np.ndarray) -> str:
    hist = cv2.calcHist([gray.astype(np.uint8)], [0], None, [32], [0, 256]).flatten()
    hist = hist / max(hist.sum(), 1)
    peaks = int((hist[1:-1] > hist[:-2]).sum())  # 粗略峰数
    if peaks >= 3:
        return "多峰"
    if peaks == 2:
        return "双峰"
    return "单峰"


def _composition_type(gray: np.ndarray, subjects: List[Dict]) -> str:
    if not subjects:
        return "无主体"
    box = subjects[0]["box"]
    if not box:
        return "无主体"
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    if abs(cx - 0.5) < 0.08 and abs(cy - 0.5) < 0.08:
        return "中心"
    if abs(cx - 1 / 3) < 0.1 or abs(cx - 2 / 3) < 0.1:
        return "三分法"
    return "偏置"


def _balance_score(gray: np.ndarray) -> float:
    h, w = gray.shape
    left = gray[:, : w // 2].mean()
    right = gray[:, w // 2:].mean()
    return 1.0 - abs(left - right) / max(left + right, 1e-6)


def _sharpness(gray: np.ndarray) -> float:
    lap = cv2.Laplacian(gray.astype(np.uint8), cv2.CV_32F)
    return float(np.abs(lap).mean())


def _noise_level(gray: np.ndarray) -> str:
    """用边缘外区域的标准差估计噪声。"""
    edges = cv2.Canny(gray.astype(np.uint8), 100, 200)
    flat = gray[edges == 0]
    if len(flat) < 100:
        return "低"
    std = float(flat.std())
    if std < 8:
        return "低"
    if std < 16:
        return "中"
    return "高"
