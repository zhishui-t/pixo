"""色彩消融: 逐项开关 trim/warmth/HSM/refine 暖色, 定位红色来源。"""
import argparse, copy, json, sys, time
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


def render_variant(cfg, params, raw_path, img, raw, prof):
    c = copy.deepcopy(cfg)
    for st, ov in params.items():
        c['params'].setdefault(st, {}).update(ov)
    ctx = StageContext(raw_path, raw=raw, prof=prof, config={'stages': c['params']})
    ctx.set_image(img, DOMAIN_LINEAR_CAM)
    for name in c['stages']:
        st = STAGE_REGISTRY[name]()
        if st.wants(ctx):
            st.run(ctx)
    return (np.clip(ctx.image, 0, 1) * 255 + .5).astype(np.uint8)


def stats(o, t):
    lo = cv2.cvtColor(o, cv2.COLOR_RGB2LAB).astype(np.float32)
    lt = cv2.cvtColor(t, cv2.COLOR_RGB2LAB).astype(np.float32)
    m = skin_mask(t) > .5
    full = (float(np.median(lo[...,1])-np.median(lt[...,1])), float(np.median(lo[...,2])-np.median(lt[...,2])))
    sk = (float(np.median(lo[...,1][m])-np.median(lt[...,1][m])), float(np.median(lo[...,2][m])-np.median(lt[...,2][m]))) if m.sum()>100 else None
    return full, sk


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stems',default='5603,0367,5236,0376')
    ap.add_argument('--preset',default=str(ROOT/'rawlab/presets/lr_baseline.json'))
    ap.add_argument('--lr-dir',default=str(ROOT/'rawlab/out/profile_fit/lr_corpus_camera_standard'))
    args=ap.parse_args()
    cfg=json.load(open(args.preset,encoding='utf-8'))
    prof=load_dcp(cfg['dcp'])
    variants={
      'current':{},
      'trim_identity':{'whitebalance':{'trim':[1,1,1]}},
      'no_warmth':{'whitebalance':{'warmth':0.0,'warmth_curve':None,'warmth_b0':None,'warmth_b1':None,'warmth_r_slope':None,'warmth_g_slope':None,'warmth_b_slope':None,'warmth_r_day':None}},
      'no_hsm':{'huesat':{'enabled':False}},
      'no_refine_warm':{'refine':{'warm_sat_curve':None,'warm_sat_spot':None,'warm_hue_curve':None}},
      'no_clarity':{'clarity':{'enabled':False}},
      'no_refine':{'refine':{'highlight_desat':0.0,'sharpen':0.0,'chroma_denoise':0.0}},
    }
    for stem in args.stems.split(','):
        stemf=f'DSC_{stem}'
        meta=json.load(open(Path(args.lr_dir)/f'{stemf}.meta.json',encoding='utf-8'))
        raw_path=meta['path']
        img,raw=decode_raw(raw_path,half_size=True);img=crop_active_oriented(img,raw)
        tgt=cv2.cvtColor(cv2.imread(str(Path(args.lr_dir)/f'{stemf}.jpg')),cv2.COLOR_BGR2RGB)
        print(f'\n===== {stemf} =====')
        for name,params in variants.items():
            o=render_variant(cfg,params,raw_path,img,raw,prof)
            t=cv2.resize(tgt,(o.shape[1],o.shape[0]),interpolation=cv2.INTER_AREA)
            full,sk=stats(o,t)
            sktxt=f' skin {sk[0]:+.1f}/{sk[1]:+.1f}' if sk else ''
            gray=cv2.cvtColor(o,cv2.COLOR_RGB2GRAY).astype(np.float32)
            clip=float((o>=254).mean()*100)
            lap=float(cv2.Laplacian(gray,cv2.CV_32F).std())
            print(f'{name:16s} full da/db {full[0]:+.1f}/{full[1]:+.1f}{sktxt} clip% {clip:.2f} lapstd {lap:.1f}')
        raw.close()


if __name__=='__main__':
    main()
