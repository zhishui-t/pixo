"""geometry.smart_crop —— 主体感知智能裁剪建议 (纯算法核心, 无 IO)。

接口::

    best_rect, candidates = suggest_crop(img_small, boxes,
                                         ratios=DEFAULT_RATIOS, scorer=None)

坐标约定 (与 exposure._subject_box 的 subject_boxes 口径一致):
- ``boxes`` 输入与 ``rect`` 输出一律为**归一化 [x0,y0,x1,y1] ∈ [0,1] 相对
  全幅**，分辨率无关; 像素换算仅在 compose 边界进行。
- ``img_small`` 仅用于长宽比与 scorer 打分，不承载坐标语义。

其余约定:
- ``boxes`` 接受 ``{"faces": [...], "subjects": [...]}``；列表项可为纯
  [x1,y1,x2,y2]，也可为 {"box": [...], "source": "native_box"|"mask_bbox"}
  —— vision 层现状只出掩码时由调用方以 mask 外接框派生并带 source 标注。
- ``ratios``: 每项 None(原比例) / "w:h" / 数值宽高比。
- 返回 ``(best_rect, candidates)``：candidates 按 score 降序，元素含
  rect/ratio/score/parts 明细。任何输入下保证非空结果：全部候选被硬
  约束过滤时回退全幅窗（candidates 带 ``fallback=True``）。
"""
from __future__ import annotations

from typing import Any, Callable, Iterator

import numpy as np

from .crop_rotate import parse_ratio

__all__ = ["suggest_crop", "DEFAULT_RATIOS"]

DEFAULT_RATIOS = (None, "1:1", "4:5", "16:9")
WINDOW_SCALES = (1.0, 0.95, 0.90, 0.85)  # 大窗优先: 同分下保留更多语境
STEP_FRACTION = 0.05                     # 滑窗步长 ≤5% 画面 (规格约束)
HEADROOM_MIN = 0.10                      # 头顶留白 ≥ 人脸框高 10% (硬约束)
# 主体保留阈值按来源分级: native_box 精准故出画≤5%; mask_bbox 由掩码外接
# 派生、边缘天然偏松, 放宽到出画≤8% 防止真框本可满足的窗口被误杀。
SUBJECT_KEEP_NATIVE = 0.95
SUBJECT_KEEP_MASK = 0.92
DEFAULT_BOX_SOURCE = "native_box"
PRESREEN_TOPK = 24                       # 注入 scorer 时每比例预筛名额 (成本护栏)

# 软评分权重 (集中定义)。无 scorer 时四项规则分加权:
#   center 0.45 —— 视觉重心居中最稳, 裁剪质量的一阶因素;
#   thirds 0.35 —— 三分法交点是经典构图引力点, 作为次级引导;
#   headroom 0.12 —— 头顶留白适度 (0.10~0.30 脸高) 加分;
#   coverage 0.08 —— 同分下偏向更大窗口, 多保留语境。
WEIGHTS_RULE = {"center": 0.45, "thirds": 0.35, "headroom": 0.12, "coverage": 0.08}
WEIGHTS_SCORER = {"scorer": 0.70, "center": 0.15, "thirds": 0.15}


def _boxes_view(boxes: Any):
    """解析 boxes → (faces, subjects)；subjects 为 (rect, keep阈值) 列表。"""
    faces: list = []
    subjects: list = []
    if not boxes:
        return faces, subjects

    def _emit(kind: str, rect, source: str | None):
        if len(rect) != 4:
            return
        rect = [float(v) for v in rect]
        if kind in ("face", "faces"):
            faces.append(rect)          # 人脸硬全含, 无面积容忍度
            return
        keep = (SUBJECT_KEEP_MASK if source == "mask_bbox"
                else SUBJECT_KEEP_NATIVE)
        subjects.append((rect, keep))   # 主体携带来源分级阈值

    if isinstance(boxes, dict):
        default_src = boxes.get("source", DEFAULT_BOX_SOURCE)
        for b in boxes.get("faces") or []:
            _emit("face", b.get("box", b) if isinstance(b, dict) else b,
                  b.get("source") if isinstance(b, dict) else None)
        for b in boxes.get("subjects") or []:
            src = (b.get("source") if isinstance(b, dict)
                   else default_src)
            _emit("subject", b.get("box", b) if isinstance(b, dict) else b, src)
    elif isinstance(boxes, (list, tuple)):
        for item in boxes:
            if isinstance(item, dict):
                _emit(str(item.get("type", "subject")).lower(),
                      item.get("box") or item.get("rect"),
                      item.get("source"))
            else:
                _emit("subject", item, DEFAULT_BOX_SOURCE)
    return faces, subjects


def _iter_windows(w_img: int, h_img: int, ratio_wh: float | None) -> Iterator[tuple]:
    """每尺度下按 ≤5% 步长的网格滑窗 + 居中位, 产出像素窗口 (内部量)。"""
    for scale in WINDOW_SCALES:
        if ratio_wh is None:
            w_win, h_win = w_img, h_img
        else:
            w_win = int(round(min(w_img, h_img * ratio_wh) * scale))
            h_win = int(round(w_win / ratio_wh))
            if h_win > h_img:
                h_win = h_img
                w_win = int(round(h_win * ratio_wh))
        w_win = max(1, min(w_win, w_img))
        h_win = max(1, min(h_win, h_img))
        step_x = max(1, int(round(w_img * STEP_FRACTION)))
        step_y = max(1, int(round(h_img * STEP_FRACTION)))
        xs = list(range(0, w_img - w_win + 1, step_x))
        ys = list(range(0, h_img - h_win + 1, step_y))
        cx, cy = (w_img - w_win) // 2, (h_img - h_win) // 2
        if xs[-1] != cx:
            xs.append(cx)
        if ys[-1] != cy:
            ys.append(cy)
        seen = set()
        for y in ys:
            for x in xs:
                if (x, y) not in seen:
                    seen.add((x, y))
                    yield (x, y, x + w_win, y + h_win)


def _passes_hard(win_norm, faces, subjects) -> bool:
    """硬约束 (全归一化域): 人脸全含+头顶留白≥脸高10%; 主体按来源分级容忍出画。"""
    nx1, ny1, nx2, ny2 = win_norm
    for fx1, fy1, fx2, fy2 in faces:
        if not (nx1 <= fx1 and fx2 <= nx2 and ny1 <= fy1 and fy2 <= ny2):
            return False
        fh = max(fy2 - fy1, 1e-6)
        if (fy1 - ny1) < HEADROOM_MIN * fh:
            return False
    for (sx1, sy1, sx2, sy2), keep in subjects:
        ix = max(0.0, min(nx2, sx2) - max(nx1, sx1))
        iy = max(0.0, min(ny2, sy2) - max(ny1, sy1))
        area = max((sx2 - sx1) * (sy2 - sy1), 1e-9)
        if (ix * iy) / area < keep:
            return False
    return True


def _clip01(v: float) -> float:
    return float(min(max(v, 0.0), 1.0))


def _rule_parts(win_norm, faces, subjects) -> dict:
    """0~1 规则子分: center / thirds / headroom / coverage。

    全归一化域计算 (win_norm 与 faces/subjects 同口径), 禁止像素混算。
    """
    nx1, ny1, nx2, ny2 = win_norm
    wcx, wcy = (nx1 + nx2) / 2.0, (ny1 + ny2) / 2.0
    if faces:
        fx = sum(b[0] + b[2] for b in faces) / (2 * len(faces))
        fy = sum(b[1] + b[3] for b in faces) / (2 * len(faces))
    elif subjects:
        fx = sum(b[0][0] + b[0][2] for b in subjects) / (2 * len(subjects))
        fy = sum(b[0][1] + b[0][3] for b in subjects) / (2 * len(subjects))
    else:
        fx, fy = wcx, wcy
    diag = max(((nx2 - nx1) ** 2 + (ny2 - ny1) ** 2) ** 0.5 / 2.0, 1e-6)
    dist = ((fx - wcx) ** 2 + (fy - wcy) ** 2) ** 0.5
    center = _clip01(1.0 - dist / diag)

    tx = (nx1 + (nx2 - nx1) / 3.0, nx1 + 2.0 * (nx2 - nx1) / 3.0)
    ty = (ny1 + (ny2 - ny1) / 3.0, ny1 + 2.0 * (ny2 - ny1) / 3.0)
    best_thirds = 0.0
    for px in tx:
        for py in ty:
            d = ((fx - px) ** 2 + (fy - py) ** 2) ** 0.5
            best_thirds = max(best_thirds, _clip01(1.0 - d / 0.12))

    if faces:
        fh = max(faces[0][3] - faces[0][1], 1e-6)
        hr = (faces[0][1] - ny1) / fh
        if hr < 0.10:
            headroom = _clip01(hr / 0.10)
        elif hr <= 0.30:
            headroom = 1.0
        else:
            headroom = _clip01(1.0 - (hr - 0.30) / 0.30)
    else:
        headroom = 0.5

    coverage = _clip01((nx2 - nx1) * (ny2 - ny1))
    return {"center": center, "thirds": best_thirds,
            "headroom": headroom, "coverage": coverage}


def _score_scalar(scorer: Callable, crop) -> float | None:
    """鸭子类型提取标量分: float / dict(overall 或数值均值) / .overall 属性。

    scorer 契约 (宽容): callable(crop_rgb) → float | dict | 带 overall
    属性的对象 | None。None/异常一律返回 None (调用方退化规则分),
    裁剪建议永不因注入 scorer 故障而失败。
    """
    try:
        out = scorer(crop)
    except Exception:
        return None
    if out is None:
        return None
    if isinstance(out, (int, float)):
        return float(out)
    if isinstance(out, dict):
        if not out:
            return None
        val = out.get("overall")
        if not isinstance(val, (int, float)):
            vals = [v for v in out.values() if isinstance(v, (int, float))]
            val = sum(vals) / len(vals) if vals else None
        return float(val) if isinstance(val, (int, float)) else None
    attr = getattr(out, "overall", None)
    return float(attr) if isinstance(attr, (int, float)) else None


def suggest_crop(img_small, boxes, ratios=DEFAULT_RATIOS, scorer=None):
    """主体感知裁剪建议 —— 坐标与返回约定见模块 docstring。"""
    h_img, w_img = int(img_small.shape[0]), int(img_small.shape[1])
    faces, subjects = _boxes_view(boxes)

    scored: list = []
    fallback_rect = (0.0, 0.0, 1.0, 1.0)
    for ratio in ratios:
        ratio_wh = parse_ratio(ratio)
        tag = str(ratio) if ratio is not None else "original"
        passed = []
        for win in _iter_windows(w_img, h_img, ratio_wh):
            norm = (win[0] / w_img, win[1] / h_img,
                    win[2] / w_img, win[3] / h_img)
            if _passes_hard(norm, faces, subjects):
                passed.append((win, norm))
        prelim = []
        for win, norm in passed:
            parts = _rule_parts(norm, faces, subjects)
            total = sum(WEIGHTS_RULE[k] * v for k, v in parts.items())
            prelim.append((total, win, norm, parts))
        prelim.sort(key=lambda t: t[0], reverse=True)
        if scorer is not None:
            prelim = prelim[:PRESREEN_TOPK]
        for total, win, norm, parts in prelim:
            if scorer is not None:
                crop = img_small[win[1]:win[3], win[0]:win[2]]
                s = _score_scalar(scorer, crop)
                if s is None:
                    score = total
                    parts = dict(parts, scorer=None)
                else:
                    parts = dict(parts, scorer=_clip01(s))
                    score = sum(WEIGHTS_SCORER[k] *
                                parts.get(k, 0.0) for k in WEIGHTS_SCORER)
            else:
                score = total
            scored.append({"rect": tuple(round(v, 6) for v in norm),
                           "ratio": tag, "ratio_wh": ratio_wh,
                           "score": round(float(score), 6),
                           "parts": {k: (None if v is None
                                         else round(float(v), 4))
                                     for k, v in parts.items()}})

    if not scored:
        best = {"rect": fallback_rect, "ratio": "original", "ratio_wh": None,
                "score": 0.0, "parts": {}, "fallback": True}
        return fallback_rect, [best]
    scored.sort(key=lambda c: c["score"], reverse=True)
    return tuple(scored[0]["rect"]), scored
