"""逐级色彩漂移诊断: 每个 gamma 阶段输出与 LR 目标的 Lab/肤色差。"""
import argparse, glob, json, os, sys
from pathlib import Path
import cv2, numpy as np, rawpy

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from rawlab.dcp import load_dcp
from rawlab.engine.core import StageContext, DOMAIN_LINEAR_CAM, STAGE_REGISTRY
from rawlab.engine import stages as _stages
from rawlab.engine.decode import decode_raw
from rawlab.engine.skin import skin_mask
from rawlab.tools.regress_anchors import crop_active_oriented


def stats(ours_u8, tgt_u8):
    lo = cv2.cvtColor(ours_u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    lt = cv2.cvtColor(tgt_u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    m = skin_mask(tgt_u8) > 0.5
    out = {
        'full_da': float(np.median(lo[..., 1]) - np.median(lt[..., 1])),
        'full_db': float(np.median(lo[..., 2]) - np.median(lt[..., 2])),
        'full_dL': float(np.median(lo[..., 0]) - np.median(lt[..., 0])),
    }
    if m.sum() > 100:
        out['skin_da'] = float(np.median(lo[..., 1][m]) - np.median(lt[..., 1][m]))
        out['skin_db'] = float(np.median(lo[..., 2][m]) - np.median(lt[..., 2][m]))
        out['skin_dL'] = float(np.median(lo[..., 0][m]) - np.median(lt[..., 0][m]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stems', default='0376,5236,5603,0367')
    ap.add_argument('--preset', default=str(ROOT / 'rawlab' / 'presets' / 'lr_baseline.json'))
    ap.add_argument('--lr-dir', default=str(ROOT / 'rawlab' / 'out' / 'profile_fit' / 'lr_corpus_camera_standard'))
    args = ap.parse_args()

    cfg = json.load(open(args.preset, encoding='utf-8'))
    prof = load_dcp(cfg['dcp'])
    gamma_stages = ['tone', 'clarity', 'colorcal', 'skin', 'stylize', 'refine']

    for stem in args.stems.split(','):
        stem_file = stem if stem.startswith('DSC_') else f'DSC_{stem}'
        meta = json.load(open(Path(args.lr_dir) / f'{stem_file}.meta.json', encoding='utf-8'))
        raw_path = meta['path']
        img, raw = decode_raw(raw_path, half_size=True)
        img = crop_active_oriented(img, raw)
        tgt = cv2.imread(str(Path(args.lr_dir) / f'{stem_file}.jpg'))
        tgt = cv2.cvtColor(tgt, cv2.COLOR_BGR2RGB)
        ctx = StageContext(raw_path, raw=raw, prof=prof, config={'stages': cfg['params']})
        ctx.set_image(img, DOMAIN_LINEAR_CAM)
        print(f'\n===== {stem} =====')
        for name in cfg['stages']:
            st = STAGE_REGISTRY[name]()
            if st.wants(ctx):
                st.run(ctx)
            if name in gamma_stages and ctx.domain == 'gamma_rgb':
                u8 = (np.clip(ctx.image, 0, 1) * 255 + .5).astype(np.uint8)
                t = cv2.resize(tgt, (u8.shape[1], u8.shape[0]), interpolation=cv2.INTER_AREA)
                s = stats(u8, t)
                print(f'[{name:9s}] ' + ' '.join(f'{k}={v:+.1f}' for k, v in s.items()))
        raw.close()


if __name__ == '__main__':
    main()
