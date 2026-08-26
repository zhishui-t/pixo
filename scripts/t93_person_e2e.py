"""t93 终版·person/detect_boxes 端到端验证（依赖 t102 rfdetr 修复）。

口径与 test_crop_wiring 对齐：
- A) MultiModelSegmenter.detect_boxes 真实路由（rfdetr 修复后应出归一化框）
- B) segmenter.detect_boxes 原生通道 _build_crop_suggestion source=native_box
- C) 显式 box_provider 优先 _build_crop_suggestion source=native_box
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from pixo.pipeline.loop import SinglePhotoLoop
from pixo.vision.segmenters.multi_router import MultiModelSegmenter

def _img():
    img = np.full((128, 128, 3), 0.08, dtype=np.float32)
    img[32:96, 32:96] = 0.3
    return img

def _make_loop(seg, **kw):
    base = dict(
        render_backend=None,
        segmenter=seg,
        crop_suggest=True,
        max_iterations=1,
        preview_long_edge=64,
        prompts=['face', 'person', 'sky'],
    )
    base.update(kw)
    return SinglePhotoLoop(**base)

def main():
    failures = []
    img = _img()

    # A) 真实多模型路由 detect_boxes
    seg = MultiModelSegmenter()
    det = seg.detect_boxes(img, ['person'])
    print('A detect_boxes:', det)
    if not det or 'person' not in det or not det['person']:
        failures.append('A: detect_boxes no person rect (rfdetr 修复后应非空)')
    else:
        x0, y0, x1, y1 = det['person'][0]
        if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
            failures.append('A: out-of-range rect %s' % (det['person'][0],))

    # B) segmenter.detect_boxes 原生通道（loop L681 分支）
    class FakeSeg:
        def segment(self, image_rgb, prompts):
            h, w = image_rgb.shape[:2]
            m = np.zeros((h, w), dtype=np.uint8)
            m[h//4:3*h//4, w//4:3*w//4] = 255
            return {p: m.copy() for p in prompts}
        def detect_boxes(self, image_rgb, prompts):
            return {'person': [[0.25, 0.25, 0.75, 0.75]]}

    loop_b = _make_loop(FakeSeg())
    masks_b = loop_b.segmenter.segment(img, list(loop_b.prompts))
    sugg_b = loop_b._build_crop_suggestion(img, masks_b)
    print('B source:', sugg_b.get('source') if sugg_b else None)
    print('B rect:', sugg_b.get('rect') if sugg_b else None)
    if sugg_b is None:
        failures.append('B: no suggestion')
    elif sugg_b.get('source') != 'native_box':
        failures.append('B: source=%s' % sugg_b.get('source'))

    # C) 显式 box_provider 优先（loop L674 分支）
    def provider(image_rgb):
        return {'faces': [[0.3, 0.2, 0.6, 0.6]], 'subjects': [],
                'source': 'native_box'}
    loop_c = _make_loop(FakeSeg(), box_provider=provider)
    masks_c = loop_c.segmenter.segment(img, list(loop_c.prompts))
    sugg_c = loop_c._build_crop_suggestion(img, masks_c)
    print('C source:', sugg_c.get('source') if sugg_c else None)
    if sugg_c is None:
        failures.append('C: no suggestion')
    elif sugg_c.get('source') != 'native_box':
        failures.append('C: source=%s' % sugg_c.get('source'))

    print('=== E2E SUMMARY ===')
    if failures:
        print('FAILED: %d' % len(failures))
        for f in failures:
            print('  -', f)
        return 1
    print('ALL OK')
    return 0

if __name__ == '__main__':
    sys.exit(main())
