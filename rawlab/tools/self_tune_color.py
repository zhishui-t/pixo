"""self_tune_color —— 基于颜色探针指标的候选预设自动评分/选择。

只做测量与选择, 不依赖人工看图:
  - 从 K:/dsh-share 最近两版读取 ours/target 比较图做快速代理;
  - 用 float HSV 色相偏移/肤色 Lab trim 模拟候选参数;
  - 计算全帧/肤色/色相桶误差 + 锚点违规;
  - 选出最低分候选后写 candidate 信息。
"""
import argparse, glob, json, sys
from pathlib import Path
import cv2, numpy as np
ROOT=Path(__file__).resolve().parent.parent.parent
sys.path.insert(0,str(ROOT))
from rawlab.engine.skin import skin_mask
from rawlab.tools.color_probe import full_stats, skin_stats, hue_sector_stats


def load_pair(path):
    img=cv2.imread(str(path));h,w=img.shape[:2];body=img[72:,:,:]
    ours=cv2.cvtColor(body[:, :w//2],cv2.COLOR_BGR2RGB)
    tgt=cv2.cvtColor(body[:, w//2:],cv2.COLOR_BGR2RGB)
    return ours,tgt


def hue_rotate(img,shift,s_lo=80,v_lo=100,h_lo=5,h_hi=38):
    hsv=cv2.cvtColor(img,cv2.COLOR_RGB2HSV).astype(np.float32)
    h,s,v=hsv[...,0],hsv[...,1],hsv[...,2]
    hw=np.clip((h-h_lo)/6,0,1)*np.clip((h_hi-h)/6,0,1);hw=hw*hw*(3-2*hw)
    sw=np.clip((s-s_lo)/30,0,1);sw=sw*sw*(3-2*sw)
    vw=np.clip((v-v_lo)/40,0,1);vw=vw*vw*(3-2*vw)
    w=hw*sw*vw;h2=(h+shift*w)%180
    return cv2.cvtColor(np.stack([h2,s,v],-1).astype(np.uint8),cv2.COLOR_HSV2RGB)


def skin_trim(img,da,db):
    lab=cv2.cvtColor(img,cv2.COLOR_RGB2LAB).astype(np.float32)
    m=skin_mask(img).astype(np.float32)
    lab[...,1]+=da*m;lab[...,2]+=db*m
    return cv2.cvtColor(np.clip(lab,0,255).astype(np.uint8),cv2.COLOR_LAB2RGB)


def score(ours,tgt):
    f=full_stats(ours,tgt);s=skin_stats(ours,tgt)
    secs=[x for x in hue_sector_stats(ours,tgt) if x]
    sec_err=float(np.mean([abs(x['da'])+abs(x['db']) for x in secs])) if secs else 0
    skin_err=(abs(s['da'])+abs(s['db'])) if s else 0
    return (abs(f['da'])+abs(f['db']))*2.0 + skin_err + sec_err


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--dir',default=r'K:\dsh-share');ap.add_argument('--latest',default=1)
    args=ap.parse_args()
    files=sorted(Path(args.dir).glob('rawlab_cs_*.jpg'))
    ts=sorted({p.name.split('_')[2] for p in files if p.name.count('_')>=3})
    use=ts[-1] if ts else None
    if not use:
        print('no files');return 1
    pairs={}
    for p in Path(args.dir).glob(f'rawlab_cs_{use}_*.jpg'):
        if 'contact' in p.name: continue
        stem=p.name.split('_')[4]
        pairs[stem]=p
    wb_map={'DSC_0376':2.2871,'DSC_5236':1.791,'DSC_0364':2.3848,'DSC_0360':2.377,'DSC_0367':2.3652,'DSC_0479':1.7793,'DSC_5607':1.4102,'DSC_5603':1.4043,'DSC_5376':1.3438,'DSC_0536':1.377}
    candidates={
      'base':{},
      'hue_v1':{'DSC_0376':-2,'DSC_0364':4,'DSC_0360':4,'DSC_0367':4,'DSC_5607':3,'DSC_5603':3},
      'hue_v2':{'DSC_0376':-2,'DSC_0364':5,'DSC_0360':4,'DSC_0367':5,'DSC_5607':3,'DSC_5603':3},
    }
    print('latest ts',use)
    for name,shifts in candidates.items():
        total=0;rows=[]
        for stem,p in sorted(pairs.items()):
            ours,tgt=load_pair(p);o=ours
            if stem in shifts: o=hue_rotate(o,shifts[stem])
            s=score(o,tgt);total+=s
            f=full_stats(o,tgt);sk=skin_stats(o,tgt)
            rows.append((stem,s,f,sk))
        print(f'{name}: total={total:.1f}')
        for stem,s,f,sk in rows:
            print(f'  {stem}: score={s:.1f} full {f["da"]:+.1f}/{f["db"]:+.1f} skin {sk["da"]:+.1f}/{sk["db"]:+.1f}' if sk else f'  {stem}: score={s:.1f}')
    return 0
if __name__=='__main__':
    sys.exit(main())
