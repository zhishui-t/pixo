"""t93 门禁·三适配器掩码质量冒烟（真实权重，可用则实跑）。

用法: python scripts/t93_segmenter_smoke.py
输出: stdout 每图每 prompt 的形状/二值/覆盖占比/bbox；越界与异常报 FAIL。
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from pixo.render.api import Renderer
from pixo.vision.segmenters.multi_router import MultiModelSegmenter

RAWS = [
    Path(r'K:/data/photo/0711/raw/DSC_5236.NEF'),
    Path(r'K:/data/photo/0711/raw/DSC_5241.NEF'),
]
PROMPTS = ['face', 'person', 'sky']

def main():
    dcp = sorted((ROOT / 'resources/dcp').glob('*.dcp'))[0]
    renderer = Renderer(dcp)
    seg = MultiModelSegmenter()
    failures = []
    for raw in RAWS:
        img = renderer.render_preview_full(raw, long_edge=512)
        h, w = img.shape[:2]
        print()
        print('== %s rendered %dx%d' % (raw.name, w, h))
        for p in PROMPTS:
            try:
                out = seg.segment(img, [p])
                m = out.get(p)
                if m is None:
                    failures.append('%s/%s: missing key' % (raw.name, p))
                    print('  %s: FAIL missing key' % p)
                    continue
                if m.shape != (h, w) or m.dtype != np.uint8:
                    failures.append('%s/%s: bad shape/dtype %s/%s' % (raw.name, p, m.shape, m.dtype))
                    print('  %s: FAIL shape %s dtype %s' % (p, m.shape, m.dtype))
                    continue
                uniq = set(np.unique(m).tolist())
                if not uniq <= {0, 255}:
                    failures.append('%s/%s: non-binary %s' % (raw.name, p, sorted(uniq)[:8]))
                    print('  %s: FAIL non-binary %s' % (p, sorted(uniq)[:8]))
                    continue
                frac = float((m > 0).mean())
                ys, xs = np.where(m > 0)
                bbox = ('[%d,%d,%d,%d]' % (xs.min(), ys.min(), xs.max(), ys.max())) if len(xs) else '[]'
                status = 'OK' if 0 < frac < 1 else 'WARN(zero/full)'
                if not (0 < frac < 1):
                    failures.append('%s/%s: coverage %.4f' % (raw.name, p, frac))
                print('  %s: %s coverage=%.4f bbox=%s' % (p, status, frac, bbox))
            except Exception as e:
                failures.append('%s/%s: EXC %s: %s' % (raw.name, p, type(e).__name__, e))
                print('  %s: FAIL EXC %s: %s' % (p, type(e).__name__, e))
    print()
    print('=== SMOKE SUMMARY ===')
    if failures:
        print('FAILED: %d' % len(failures))
        for f in failures:
            print('  -', f)
        return 1
    print('ALL OK')
    return 0

if __name__ == '__main__':
    sys.exit(main())
