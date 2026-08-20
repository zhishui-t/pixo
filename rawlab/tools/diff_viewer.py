"""diff_viewer —— 像素级差异热力图 + OpenSeadragon 深度缩放查看器。

为 ours/target 两张 RGB 图生成:
  - DZI 图像金字塔 (PIL 自建, 无 pyvips 依赖)
  - ΔL / Δa / Δb / ΔE 热力图 DZI
  - 自动化异常区域 (肤色 ΔE、高光 ΔL、中性 ΔE)
  - index.html (OpenSeadragon 图层切换 + 异常框 overlay)
输出目录浏览器直接打开。
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import cv2, numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rawlab.engine.skin import skin_mask
from rawlab.tools.regress_anchors import align_target

TILE = 256
TILE_FORMAT = 'jpeg'


def lab_of(rgb):
    u8 = np.asarray(rgb, dtype=np.uint8)
    return cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)


def delta_arrays(ours_u8, target_u8):
    lo, lt = lab_of(ours_u8), lab_of(target_u8)
    dL = lo[..., 0] - lt[..., 0]
    da = lo[..., 1] - lt[..., 1]
    db = lo[..., 2] - lt[..., 2]
    de = np.sqrt(dL * dL + da * da + db * db)
    return {'dL': dL, 'da': da, 'db': db, 'dE': de}


def signed_heatmap(diff, vmax):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import colormaps as _cmaps
    norm = np.clip(diff.astype(np.float32) / float(vmax), -1.0, 1.0)
    rgb01 = _cmaps['coolwarm']((norm + 1.0) / 2.0)[..., :3]
    return (rgb01 * 255.0 + 0.5).astype(np.uint8)


def abs_heatmap(diff, vmax):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import colormaps as _cmaps
    norm = np.clip(diff.astype(np.float32) / float(vmax), 0.0, 1.0)
    rgb01 = _cmaps['turbo'](norm)[..., :3]
    return (rgb01 * 255.0 + 0.5).astype(np.uint8)


def write_dzi(base_dir, name, arr):
    img = Image.fromarray(np.asarray(arr, dtype=np.uint8), 'RGB')
    dzi = base_dir / f'{name}.dzi'
    files = base_dir / f'{name}_files'
    files.mkdir(parents=True, exist_ok=True)
    w, h = img.size
    levels = max(1, int(np.ceil(np.log2(max(w, h) / TILE))) + 1)
    for level in range(levels):
        scale = 2 ** (levels - 1 - level)
        tw, th = int(np.ceil(w / scale)), int(np.ceil(h / scale))
        small = img.resize((tw, th), Image.Resampling.LANCZOS)
        ldir = files / str(level)
        ldir.mkdir(parents=True, exist_ok=True)
        for r in range(0, th, TILE):
            for c in range(0, tw, TILE):
                box = (c, r, min(c + TILE, tw), min(r + TILE, th))
                small.crop(box).save(ldir / f'{c}_{r}.jpg', quality=85)
    dzi.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Image TileSize="{TILE}" Overlap="0" Format="{TILE_FORMAT}" '
        f'xmlns="http://schemas.microsoft.com/deepzoom/2008">\n'
        f'<Size Width="{w}" Height="{h}"/>\n</Image>\n', encoding='utf-8')


def anomaly_boxes(ours_u8, target_u8, de, dL, max_boxes=20):
    target_lab = lab_of(target_u8)
    C = np.sqrt((target_lab[..., 1] - 128) ** 2 + (target_lab[..., 2] - 128) ** 2)
    skin = skin_mask(target_u8) > 0.5
    masks = {
        'skin_dE>5': skin & (de > 5),
        'highlight_dL>10': (target_lab[..., 0] > 200) & (np.abs(dL) > 10),
        'neutral_dE>3': (C < 12) & (de > 3),
    }
    h, w = de.shape
    boxes = []
    for typ, mask in masks.items():
        if mask.sum() < 64:
            continue
        n, labels, stats, _ = cv2.connectedComponentsWithStats(
            mask.astype(np.uint8), 8)
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area < max(256, int(w * h * 0.0001)):
                continue
            sub = labels[y:y + bh, x:x + bw] == i
            if sub.sum() < 64:
                continue
            boxes.append({
                'type': typ,
                'box': [x / w, y / h, (x + bw) / w, (y + bh) / h],
                'area': int(sub.sum()),
                'dE_p95': round(float(np.percentile(de[y:y + bh, x:x + bw][sub], 95)), 2),
                'dL_med': round(float(np.median(dL[y:y + bh, x:x + bw][sub])), 2),
            })
    boxes.sort(key=lambda b: -b['dE_p95'])
    return boxes[:max_boxes]


def build_viewer(ours_path, target_path, out_dir, vmax=20.0):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ours = cv2.cvtColor(cv2.imread(str(ours_path)), cv2.COLOR_BGR2RGB)
    target = cv2.cvtColor(cv2.imread(str(target_path)), cv2.COLOR_BGR2RGB)
    target = align_target(target, ours.shape[:2])
    deltas = delta_arrays(ours, target)
    write_dzi(out_dir, 'ours', ours)
    write_dzi(out_dir, 'target', target)
    write_dzi(out_dir, 'dL', signed_heatmap(deltas['dL'], vmax))
    write_dzi(out_dir, 'da', signed_heatmap(deltas['da'], vmax / 2))
    write_dzi(out_dir, 'db', signed_heatmap(deltas['db'], vmax / 2))
    write_dzi(out_dir, 'dE', abs_heatmap(deltas['dE'], vmax))
    boxes = anomaly_boxes(ours, target, deltas['dE'], deltas['dL'])
    (out_dir / 'anomalies.json').write_text(
        json.dumps(boxes, ensure_ascii=False, indent=2), encoding='utf-8')
    html = _html(boxes, vmax)
    (out_dir / 'index.html').write_text(html, encoding='utf-8')
    return out_dir / 'index.html'


def _html(boxes, vmax):
    overlays = []
    colors = {'skin_dE>5': '#ff5555', 'highlight_dL>10': '#ffcc00',
              'neutral_dE>3': '#55aaff'}
    for b in boxes:
        c = colors.get(b['type'], '#ffffff')
        overlays.append(
            f"addBox({b['box'][0]},{b['box'][1]},{b['box'][2]},{b['box'][3]},"
            f"'{b['type']} dE95={b['dE_p95']} dL={b['dL_med']}','{c}');")
    return f'''<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>diff viewer</title>
<style>
html,body{{margin:0;height:100%;background:#111;font-family:system-ui}}
#bar{{position:fixed;top:0;left:0;right:0;z-index:10;background:#1c1c1c;
color:#eee;padding:6px 10px;font-size:13px}}
#bar label{{margin-right:10px;cursor:pointer}}
#viewer{{position:absolute;top:34px;left:0;right:0;bottom:0}}
.box{{border:2px solid #f55;background:rgba(255,0,0,.08);color:#fff;
font-size:12px;padding:2px 4px;white-space:nowrap}}
</style>
<script src="https://cdn.jsdelivr.net/npm/openseadragon@4.1.0/build/openseadragon/openseadragon.min.js"></script>
</head><body>
<div id="bar">
<label><input type="checkbox" id="chk_ours" checked>ours</label>
<label><input type="checkbox" id="chk_target">target</label>
<label><input type="checkbox" id="chk_dE" checked>ΔE heat</label>
<label><input type="checkbox" id="chk_dL">ΔL heat</label>
<label><input type="checkbox" id="chk_da">Δa heat</label>
<label><input type="checkbox" id="chk_db">Δb heat</label>
<span id="info" style="margin-left:12px"></span>
</div>
<div id="viewer"></div>
<script>
const prefix='https://cdn.jsdelivr.net/npm/openseadragon@4.1.0/build/openseadragon/images/';
let viewer=OpenSeadragon({{id:'viewer',prefixUrl:prefix,showNavigator:true,
navigatorPosition:'BOTTOM_RIGHT',tileSources:['ours.dzi','target.dzi']}});
viewer.addTiledImage({{tileSource:'dE.dzi',opacity:0.55,index:2}});
viewer.addTiledImage({{tileSource:'dL.dzi',opacity:0,index:3}});
viewer.addTiledImage({{tileSource:'da.dzi',opacity:0,index:4}});
viewer.addTiledImage({{tileSource:'db.dzi',opacity:0,index:5}});
function set(i,on){{viewer.world.getItemAt(i).setOpacity(on?1:0)}}
document.getElementById('chk_ours').onchange=e=>set(0,e.target.checked);
document.getElementById('chk_target').onchange=e=>set(1,e.target.checked);
document.getElementById('chk_dE').onchange=e=>set(2,e.target.checked?0.55:0);
document.getElementById('chk_dL').onchange=e=>set(3,e.target.checked?0.55:0);
document.getElementById('chk_da').onchange=e=>set(4,e.target.checked?0.55:0);
document.getElementById('chk_db').onchange=e=>set(5,e.target.checked?0.55:0);
function addBox(l,t,r,b,text,color){{
let el=document.createElement('div');el.className='box';el.textContent=text;
el.style.borderColor=color;
viewer.addOverlay({{element:el,location:new OpenSeadragon.Rect(l,t,r-l,b-t)}});
}}
{chr(10).join(overlays)}
</script></body></html>'''


def build_parser():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ours', required=True)
    ap.add_argument('--target', required=True)
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--vmax', type=float, default=20.0)
    return ap




def main(argv=None):
    args = build_parser().parse_args(argv)
    t0 = time.perf_counter()
    html = build_viewer(args.ours, args.target, args.out_dir, vmax=args.vmax)
    print(f'[diff-viewer] {time.perf_counter()-t0:.1f}s -> {html}')


if __name__ == '__main__':
    sys.exit(main())
