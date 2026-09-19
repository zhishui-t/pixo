"""fit_tone_curve —— 基座影调曲线 (recipe) 拟合工具: 我们的线性 → 相机内嵌 JPEG。

血统与教训 (承自 rawlab/tools/fit_lr_tone_v2.py v4, 迁移中被删、R24 找回改造):
  - v1 逐通道 CDF 曲线把拟合照片的 WB 烘焙进曲线, 跨图发蓝 —— **必须共享曲线**;
  - v3 固定增益 + 共享曲线修复跨图色偏; v4 双图联合拟合约束暗部端点。
  - 本工具把 v4 方法论泛化到**语料级** (N 张采样) 并把目标从 LR 导出改为
    相机内嵌 JPEG (R23 §5.1: recipe 匹配度才用相机 JPEG 作参照)。

方法 (分布级, 无需几何对齐):
  1. 中性链渲染 (R23 后默认) 输出 = sRGB 编码 ⇒ srgb_decode 精确反解回线性
     (tone 是链上唯一非线性步, 之前全线性: baseline 曝光增益 / WB / 色矩阵)。
  2. 共享影调曲线: 合并 (pooled) 亮度 CDF 匹配 linear Y → 相机 gamma Y
     (quantile-quantile, np.maximum.accumulate 保证单调)。旋转/裁切不改变
     合并分布 ⇒ 无需朝向对齐。
  3. 逐通道增益 k: 联合网格搜索, 目标 = 相机 Lab(a*, b*) 中位 + HSV 饱和度均值
     (与 v4 同判据; 增益吸收我们与相机管线的全局色差)。
  4. 留出集评估 (分布级 A = 整图均值 ΔE76 + dL/da/db + 黑白端点), 不达标
     则不该接线 —— 失败路径合法 (R18 先例)。

输出 v3 兼容 JSON (tone_map lrfit/recipe 加载器按 gains/curve 解析):
  {"version": 4, "target": "camera_thumb", "gains": [r,g,b],
   "curve": [1024 点 0..255], "provenance": {...}}

已知限定: 双方高光均可能 clip (u8 端点), CDF 顶端由此轻微失真; 拟合目标是
"相机默认观感" (含机内 auto-bright), 不是物理真值 —— 引擎准度用中性参照另测
(R24 两分参照集)。

用法:
  python src/pixo/render/tools/fit_tone_curve.py --n 120 --sessions 0711,西安
  python src/pixo/render/tools/fit_tone_curve.py --n 0        # 全量
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import rawpy

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from pixo.render.api import Renderer  # noqa: E402

CORPUS = Path("K:/data/photo")
PREVIEW_LONG_EDGE = 1024
N_PTS = 1024
N_QUANT = 65536


# ---------------------------------------------------------------- 采样
def discover(sessions: list[str] | None) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = defaultdict(list)
    for sess_dir in sorted(CORPUS.iterdir()):
        if not sess_dir.is_dir() or (sessions and sess_dir.name not in sessions):
            continue
        for p in sess_dir.rglob("*"):
            if p.is_file() and p.suffix.upper() == ".NEF" \
                    and not p.name.startswith("._"):
                groups[sess_dir.name].append(p)
    for k in groups:
        groups[k].sort()
    return groups


def sample(groups: dict[str, list[Path]], n: int, seed: int) -> list[Path]:
    rng = random.Random(seed)
    allp = [p for v in groups.values() for p in v]
    if n <= 0 or n >= len(allp):
        return allp
    quota: dict[str, list[Path]] = defaultdict(list)
    total = len(allp)
    for s, v in groups.items():
        quota[s] = rng.sample(v, min(max(1, int(round(len(v) / total * n))), len(v)))
    out = [p for v in quota.values() for p in v]
    rng.shuffle(out)
    return sorted(out[:n])


# ---------------------------------------------------------------- 单张
def read_thumb(p: Path) -> np.ndarray:
    """RAW 内嵌 JPEG 预览 (= 相机屏幕所见), 原样不转 (分布级拟合无需朝向)。"""
    with rawpy.imread(str(p)) as raw:
        t = raw.extract_thumb()
        if t.format == rawpy.ThumbFormat.JPEG:
            bgr = cv2.imdecode(np.frombuffer(t.data, np.uint8), cv2.IMREAD_COLOR)
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        return np.asarray(t.data)[..., :3].copy()


def labsat(x_u8: np.ndarray) -> tuple[float, float, float]:
    """(median a*, median b*, mean HSV 饱和度), v4 同判据。"""
    lab = cv2.cvtColor(x_u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    hsv = cv2.cvtColor(x_u8, cv2.COLOR_RGB2HSV)
    return (float(np.median(lab[..., 1]) - 128.0),
            float(np.median(lab[..., 2]) - 128.0),
            float(hsv[..., 1].mean()))


def lab_mean(x_u8: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(x_u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    lab[..., 0] *= 100.0 / 255.0
    lab[..., 1] -= 128.0
    lab[..., 2] -= 128.0
    return lab.reshape(-1, 3).mean(axis=0)


def lum(rgb: np.ndarray) -> np.ndarray:
    return (0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2])


def decode_ch(ch_u8: np.ndarray) -> np.ndarray:
    """u8 sRGB 通道 → 线性 (向量化 srgb_decode; 中性链精确反解)。"""
    y = ch_u8.astype(np.float32) / 255.0
    return np.where(y <= 0.04045, y / 12.92,
                    np.power(np.clip((y + 0.055) / 1.055, 0.0, None), 2.4))


# ---------------------------------------------------------------- 拟合
def fit_curve(y_lin_all: list[np.ndarray],
              y_cam_all: list[np.ndarray]) -> np.ndarray:
    """合并亮度 CDF 匹配: linear Y → 相机 gamma Y, 1024 点单调曲线。

    各图画幅不一 (横/竖拍) ⇒ 先 ravel 再合并 (分布级, 尺寸无关)。"""
    Y1 = np.concatenate([y.ravel() for y in y_lin_all])
    Y2 = np.concatenate([y.ravel() for y in y_cam_all])
    qs = np.linspace(0.0, 1.0, N_QUANT)
    xs = np.quantile(Y1, qs)
    ys = np.quantile(Y2, qs)
    grid = np.linspace(0.0, 1.0, N_PTS)
    curve = np.clip(np.maximum.accumulate(np.interp(grid, xs, ys)), 0.0, 1.0)
    return curve


def apply_kcurve(linear: np.ndarray, k: np.ndarray, curve: np.ndarray,
                 grid: np.ndarray) -> np.ndarray:
    """gains × 线性 → 曲线 → u8 (与 tone lrfit/recipe 分支同数学)。"""
    y = np.empty_like(linear)
    for c in range(3):
        y[..., c] = np.interp(np.clip(linear[..., c] * k[c], 0.0, 1.0), grid, curve)
    return (np.clip(y, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def fit_gains(lins: list[np.ndarray], targets: list[tuple[float, float, float]],
              curve: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """联合网格搜索逐通道增益 (v4 同款范围; 判据 a/b/S 分布级统计)。"""
    lins_s = [L[::4, ::4] for L in lins]
    best, best_err = None, float("inf")
    for kr in np.linspace(0.70, 1.00, 7):
        for kg in np.linspace(1.00, 1.30, 7):
            for kb in np.linspace(1.00, 1.40, 9):
                k = np.array([kr, kg, kb], np.float32)
                err = 0.0
                for Ls, (a_t, b_t, S_t) in zip(lins_s, targets):
                    a, b, S = labsat(apply_kcurve(Ls, k, curve, grid))
                    err += ((a - a_t) ** 2 + (b - b_t) ** 2 + 0.5 * (S - S_t) ** 2)
                if err < best_err:
                    best, best_err = k, err
    return best


# ---------------------------------------------------------------- 评估
def evaluate(pairs: list[tuple[np.ndarray, np.ndarray]], k: np.ndarray,
             curve: np.ndarray, grid: np.ndarray) -> dict:
    """分布级评估: A = 整图均值 Lab ΔE76 (无几何对齐依赖) + 端点。"""
    As, dLs, das, dbs, p05s, p995s = [], [], [], [], [], []
    for lin, cam in pairs:
        ours = apply_kcurve(lin, k, curve, grid)
        m_o, m_c = lab_mean(ours), lab_mean(cam)
        As.append(float(np.linalg.norm(m_o - m_c)))
        dLs.append(float(m_o[0] - m_c[0]))
        das.append(float(m_o[1] - m_c[1]))
        dbs.append(float(m_o[2] - m_c[2]))
        g = cv2.cvtColor(ours, cv2.COLOR_RGB2GRAY)
        p05s.append(float(np.percentile(g, 0.5)))
        p995s.append(float(np.percentile(g, 99.5)))
    return {
        "n": len(pairs),
        "A_med": round(float(np.median(As)), 2),
        "A_p90": round(float(np.percentile(As, 90)), 2),
        "dL_med": round(float(np.median(dLs)), 2),
        "da_med": round(float(np.median(das)), 2),
        "db_med": round(float(np.median(dbs)), 2),
        "our_p05_med": round(float(np.median(p05s)), 1),
        "our_p995_med": round(float(np.median(p995s)), 1),
    }


# ---------------------------------------------------------------- 主流程
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=120, help="采样张数, 0=全量")
    ap.add_argument("--sessions", type=str, default="")
    ap.add_argument("--seed", type=int, default=20260919)
    ap.add_argument("--holdout-frac", type=float, default=0.3)
    ap.add_argument("--dcp", type=str, default=str(
        ROOT / "resources" / "dcp" / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"))
    ap.add_argument("--out", type=str,
                    default=str(ROOT / ".artifacts" / "r24_recipe_tone_curve.json"))
    args = ap.parse_args()

    sessions = [s.strip() for s in args.sessions.split(",") if s.strip()] or None
    groups = discover(sessions)
    files = sample(groups, args.n, args.seed)
    rng = random.Random(args.seed + 1)
    rng.shuffle(files)
    n_hold = max(1, int(round(len(files) * args.holdout_frac)))
    holdout, train = files[:n_hold], files[n_hold:]
    print(f"语料 {sum(len(v) for v in groups.values())} 张 → 采样 {len(files)}"
          f" (train {len(train)} / holdout {len(holdout)})\n", flush=True)

    r = Renderer(args.dcp)
    grid = np.linspace(0.0, 1.0, N_PTS)

    def collect(paths: list[Path]):
        pairs = []
        for i, p in enumerate(paths, 1):
            try:
                preview = r.render_preview_full(p, long_edge=PREVIEW_LONG_EDGE)
                thumb = read_thumb(p)
            except Exception as e:  # noqa: BLE001  (已知 LibRaw 坏文件)
                print(f"  skip {p.name}: {type(e).__name__}")
                continue
            preview = np.asarray(preview)
            if preview.ndim != 3 or preview.shape[2] < 3:
                continue
            if preview.dtype != np.uint8:
                preview = (np.clip(preview, 0, 1) * 255 + 0.5).astype(np.uint8)
            # 中性链 sRGB 编码精确反解回线性 (tone 前全线性)
            lin = np.stack([decode_ch(preview[..., c]) for c in range(3)],
                           axis=-1).astype(np.float32)
            # 相机 thumb 统一到预览分辨率 (分布级, 仅降采样减负)
            s = PREVIEW_LONG_EDGE / max(thumb.shape[:2])
            thumb_s = cv2.resize(thumb, (max(8, int(round(thumb.shape[1] * s))),
                                         max(8, int(round(thumb.shape[0] * s)))),
                                 interpolation=cv2.INTER_AREA)
            pairs.append((lin, thumb_s))
            if i % 20 == 0 or i == len(paths):
                print(f"  [{i}/{len(paths)}] {p.name}", flush=True)
        return pairs

    t0 = time.time()
    print("== train 集采集 ==", flush=True)
    train_pairs = collect(train)
    print("== holdout 集采集 ==", flush=True)
    hold_pairs = collect(holdout)
    print(f"采集完成 ({time.time() - t0:.0f}s): train {len(train_pairs)}"
          f" / holdout {len(hold_pairs)}\n", flush=True)

    # ---- 曲线: train 集合并 CDF 匹配 ----
    # 注意量纲: 我方线性 ∈[0,1]; 相机 thumb 是 u8 ⇒ 先 /255 归一
    # (v4 原工具即此口径, 漏归一会把曲线拟成恒 1 全白)
    y_lin = [lum(lin) for lin, _ in train_pairs]
    y_cam = [lum(cam.astype(np.float32) / 255.0) for _, cam in train_pairs]
    curve = fit_curve(y_lin, y_cam)
    print(f"曲线低段 {np.round(curve[[8, 32, 128, 512]], 3)} "
          f"(0.008/0.03/0.125/0.5 → cam Y)")

    # ---- 增益: train 集联合网格搜索 ----
    targets = [labsat(cam) for _, cam in train_pairs]
    gains = fit_gains([lin for lin, _ in train_pairs], targets, curve, grid)
    print(f"gains: R={gains[0]:.3f} G={gains[1]:.3f} B={gains[2]:.3f}")

    # ---- 评估: train / holdout 分布级 ----
    ev_train = evaluate(train_pairs, gains, curve, grid)
    ev_hold = evaluate(hold_pairs, gains, curve, grid)
    print(f"\ntrain  : {ev_train}")
    print(f"holdout: {ev_hold}")

    out = Path(args.out)
    out.write_text(json.dumps({
        "version": 4,
        "target": "camera_thumb",
        "gains": [round(float(g), 6) for g in gains],
        "curve": [round(float(v) * 255.0, 4) for v in curve],
        "provenance": {
            "tool": "src/pixo/render/tools/fit_tone_curve.py",
            "dcp": Path(args.dcp).name,
            "n_train": len(train_pairs), "n_holdout": len(hold_pairs),
            "seed": args.seed, "sessions": sessions or "all",
            "eval_train": ev_train, "eval_holdout": ev_hold,
        },
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n已写 {out}")


if __name__ == "__main__":
    main()
