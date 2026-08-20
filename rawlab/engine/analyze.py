"""engine.analyze —— 主体感知分析接线 (阶段2, T1)。

职责 (软件设计 §2 模块划分):
  - run_analysis(ctx, rgb8=None, detect=True, classify=False):
    * detect=True : 用 vision_bridge.detect_subjects (复用 guanlan YOLOE,
      路径由 RAWLAB_GUANLAN_ROOT 控制, 已去硬编码) 检测主体/人脸框,
      写入 ctx.state['subject_boxes'] / ['face_boxes']; 检测异常静默回退 (空框)。
    * classify=True: 场景分类接线 (engine.scenes 由 T3 提供; 模块未就绪时
      静默跳过, 不影响检测路径)。
    * rgb8 缺省时按 ctx.state['probe_rgb8'] → 渲染半尺寸 probe 顺序解析;
      都无法获得 → 空框回退 (不抛)。
  检测输入 = 半尺寸渲染 probe (测量=渲染: 与最终画面同链路)。

  曝光 Stage 读取 ctx.state['subject_boxes'] / ['face_boxes'] 做主体加权
  (face 优先, 框面积 <1% 忽略, 见 stages/exposure.py)。
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np

from .core import StageContext

_BOX_MIN_AREA = 0.01  # 归一化框面积下限 (1%), 与 exposure Stage 一致


def _as_uint8_bgr(img: np.ndarray) -> np.ndarray:
    """任意 8bit RGB / float 图 → 8bit BGR (vision_bridge.detect_subjects 输入)。"""
    import cv2

    arr = np.asarray(img)
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0.0, 1.0)
        arr = (arr * 255.0 + 0.5).astype(np.uint8)
    if arr.ndim == 2:
        arr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _sanitize_boxes(boxes) -> List[List[float]]:
    """归一化 [l, t, r, b] 列表清洗: 只保留 4 个有限数值的框。"""
    out: List[List[float]] = []
    for b in boxes or []:
        try:
            v = [float(x) for x in b]
        except (TypeError, ValueError):
            continue
        if len(v) == 4 and all(np.isfinite(v)):
            out.append(v)
    return out


def _resolve_probe(ctx: StageContext, rgb8) -> np.ndarray | None:
    """分析输入图: 显式 rgb8 → ctx.state['probe_rgb8'] → 渲染半尺寸 probe。

    全部不可得 → None (调用方静默回退空框)。
    """
    if rgb8 is not None:
        return np.asarray(rgb8)
    probe = ctx.state.get("probe_rgb8")
    if probe is not None:
        return np.asarray(probe)
    try:
        from rawlab.render import render
        return render(ctx.raw_path, ctx.prof, half_size=True)
    except Exception:
        return None


def _detect(ctx: StageContext, rgb8) -> None:
    """YOLOE 主体/人脸框检测 → 写 ctx.state; 任何异常静默回退空框。"""
    boxes: List[List[float]] = []
    faces: List[List[float]] = []
    probe = _resolve_probe(ctx, rgb8)
    if probe is not None:
        try:
            # 模块级引用 (调用时取属性), 便于测试 monkeypatch vision_bridge.detect_subjects
            from rawlab import vision_bridge
            boxes, faces = vision_bridge.detect_subjects(_as_uint8_bgr(probe))
            boxes = _sanitize_boxes(boxes)
            faces = _sanitize_boxes(faces)
        except Exception as e:
            # 无 guanlan / 无 CUDA / 坏图 → 回退无主体 (曝光走全图中位)
            print(f"[analyze] 主体检测失败, 回退无主体: {e}")
            boxes, faces = [], []
    ctx.state["subject_boxes"] = boxes
    ctx.state["face_boxes"] = faces


def _classify(ctx: StageContext, rgb8) -> None:
    """场景分类接线 (engine.scenes 由 T3 提供; 未就绪静默跳过)。

    写入 ctx.state['scene'] = {"id": scene_id, "confidence": conf}。
    """
    try:
        from rawlab.engine import scenes  # T3 提供; 未就绪 → ImportError 跳过
    except Exception:
        return
    probe = _resolve_probe(ctx, rgb8)
    if probe is None:
        return
    try:
        scene_id, conf = scenes.classify_scene(
            probe, vision_report=ctx.state.get("vision_report"),
            subjects=ctx.state.get("subject_boxes"))
        ctx.state["scene"] = {"id": scene_id, "confidence": float(conf)}
    except Exception as e:
        print(f"[analyze] 场景分类失败, 跳过: {e}")


def run_analysis(ctx: StageContext, rgb8=None, detect: bool = True,
                 classify: bool = False) -> Tuple[List[List[float]], List[List[float]]]:
    """主体检测 (+可选场景分类) 接线, 结果写 ctx.state。

    Args:
        ctx:      StageContext (raw_path/prof 用于缺省 probe 渲染)。
        rgb8:     8bit RGB 分析图 (渲染 probe)。None → 用 ctx.state['probe_rgb8']
                  → 渲染半尺寸 probe (均不可得 → 空框回退, 不抛)。
        detect:   是否跑 YOLOE 主体/人脸检测 (异常静默回退空框)。
        classify: 是否跑场景分类 (T3 engine.scenes; 未就绪静默跳过)。

    Returns:
        (subject_boxes, face_boxes): 归一化 [l, t, r, b] 列表 (与 ctx.state 一致)。
    """
    if detect:
        _detect(ctx, rgb8)
    if classify:
        _classify(ctx, rgb8)
    return (ctx.state.get("subject_boxes", []),
            ctx.state.get("face_boxes", []))
