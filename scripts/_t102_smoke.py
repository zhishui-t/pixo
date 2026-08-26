# -*- coding: utf-8 -*-
"""t102 真机冒烟：person 掩码 + detect_boxes 原生框（首次自动下载 rfdetr 权重）。"""
import io, json, os, sys, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np
import cv2

PIXO_ROOT = r"K:/work/project/pixo"
sys.path.insert(0, os.path.join(PIXO_ROOT, "src"))

from pixo.vision.segmenters.multi_router import MultiModelSegmenter
from pixo.vision.segmenters.rfdetr_person import RFDetrPersonSegmenter

IMG = r"K:/data/photo/0711/jpeg/DSC_5236.jpg"

report = {"status": "running", "steps": []}

def step(name, fn):
    t0 = time.perf_counter()
    try:
        r = fn()
        report["steps"].append({"name": name, "ok": True,
                                "ms": round((time.perf_counter()-t0)*1000, 1),
                                "detail": r})
        print(f"[OK] {name} in {report['steps'][-1]['ms']} ms -> {r}", flush=True)
    except Exception as e:
        report["steps"].append({"name": name, "ok": False, "error": repr(e)})
        print(f"[FAIL] {name}: {e!r}", flush=True)
        raise

def load_img():
    img = cv2.imread(IMG)
    assert img is not None, "imread failed"
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

img = load_img()
h, w = img.shape[:2]
report["image"] = {"path": IMG, "h": h, "w": w}
print(f"img {w}x{h}", flush=True)

step("direct._load_construct", lambda: str(RFDetrPersonSegmenter()._model is None))
seg = RFDetrPersonSegmenter()

def do_segment():
    masks = seg.segment(img, ["person"])
    m = masks["person"]
    nz = int((m > 0).sum())
    assert nz > 0, f"person mask all-zero ({nz})"
    return {"shape": list(m.shape), "nonzero_px": nz,
            "ratio": round(nz / (h * w), 4)}

step("segment_person", do_segment)

def do_boxes():
    boxes = seg.detect_boxes(img, ["person"])
    assert "person" in boxes and boxes["person"], f"no native boxes: {boxes}"
    b = boxes["person"][0]
    assert len(b) == 4 and 0.0 <= b[0] <= b[2] <= 1.0 and 0.0 <= b[1] <= b[3] <= 1.0
    return {"boxes": boxes}

step("detect_boxes", do_boxes)

# MultiModelSegmenter end-to-end (默认实例化真实 rfdetr 后端)
router = MultiModelSegmenter()
def do_router_seg():
    out = router.segment(img, ["person"])
    m = out["person"]
    nz = int((m > 0).sum())
    assert nz > 0, "router person mask all-zero"
    return {"nonzero_px": nz, "shape": list(m.shape)}
step("router.segment_person", do_router_seg)

def do_router_boxes():
    boxes = router.detect_boxes(img, ["person"])
    return boxes
step("router.detect_boxes", do_router_boxes)

# 落盘证据
with open(r"exports/_t102_smoke_report.json", "w", encoding="utf-8") as f:
    json.dump(report, f, ensure_ascii=False, indent=1)
report["status"] = "passed"
print("==SMOKE_RESULT==", flush=True)
print(json.dumps(report, ensure_ascii=False, indent=1), flush=True)
