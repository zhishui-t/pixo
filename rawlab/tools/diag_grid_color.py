"""6x6/9x9 网格 RGB/Lab 对比诊断: ours vs LR (从 review_10 比较图读取)。"""
import argparse, glob, os, sys
from pathlib import Path
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def load_pair(path):
    img = cv2.imread(str(path))
    h, w = img.shape[:2]
    body = img[72:, :, :]
    ours = cv2.cvtColor(body[:, :w // 2], cv2.COLOR_BGR2RGB)
    tgt = cv2.cvtColor(body[:, w // 2:], cv2.COLOR_BGR2RGB)
    return ours, tgt


def cell_medians(img, n):
    h, w = img.shape[:2]
    rows = []
    for i in range(n):
        y0, y1 = i * h // n, (i + 1) * h // n
        for j in range(n):
            x0, x1 = j * w // n, (j + 1) * w // n
            patch = img[y0:y1, x0:x1].reshape(-1, 3).astype(np.float32)
            rgb = np.median(patch, axis=0)
            lab = cv2.cvtColor(np.uint8([[rgb]]), cv2.COLOR_RGB2LAB)[0, 0].astype(np.float32)
            rows.append((i, j, rgb, lab))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--grid', type=int, default=6)
    ap.add_argument('--top', type=int, default=12)
    ap.add_argument('--dir', default=str(ROOT / 'rawlab' / 'out' / 'review_10'))
    ap.add_argument('--stems', default='0376,5236,0364,0360,0367,0479,5607,5603,5376,0536')
    args = ap.parse_args()

    for stem in args.stems.split(','):
        files = glob.glob(str(Path(args.dir) / f'*{stem}_cmp.jpg'))
        if not files:
            print(stem, 'NO FILE')
            continue
        ours, tgt = load_pair(files[0])
        cells_o = cell_medians(ours, args.grid)
        cells_t = cell_medians(tgt, args.grid)
        print(f'\n===== {stem} ({args.grid}x{args.grid}) =====')
        for (i, j, ro, lo), (_, _, rt, lt) in zip(cells_o, cells_t):
            d_rgb = ro - rt
            d_lab = lo - lt
            # 只报较大的色偏格, 亮度差单独标出
            if abs(d_lab[1]) >= 2.0 or abs(d_lab[2]) >= 2.0 or abs(d_rgb).max() >= 8.0:
                print(f'[{i},{j}] dR={d_rgb[0]:+6.1f} dG={d_rgb[1]:+6.1f} dG?={d_rgb[2]:+6.1f} '
                      f'dL={d_lab[0]:+5.1f} da={d_lab[1]:+5.1f} db={d_lab[2]:+5.1f}')
        # 全局汇总
        ro_all = np.median(ours.reshape(-1, 3), axis=0)
        rt_all = np.median(tgt.reshape(-1, 3), axis=0)
        lo_all = cv2.cvtColor(np.uint8([[ro_all]]), cv2.COLOR_RGB2LAB)[0, 0].astype(np.float32)
        lt_all = cv2.cvtColor(np.uint8([[rt_all]]), cv2.COLOR_RGB2LAB)[0, 0].astype(np.float32)
        print(f'GLOBAL dRGB={ro_all - rt_all} dLab={lo_all - lt_all}')


if __name__ == '__main__':
    main()
