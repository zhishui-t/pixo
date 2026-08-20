"""fit_lr_tone_v2 —— 从"我们的线性数据 → LR 渲染"拟合 LR 标定 (v4: 双图联合)。

历史 (2026-08, "一黄一蓝 → 黄绿" 系列问题的根因链):
  v1 逐通道 CDF 曲线把拟合照片的 WB 烘焙进曲线, 跨图发蓝。
  v3 共享曲线 + 固定增益修复跨图蓝, 但固定 warm 把 tint≈0 的 5236 也做成暖黄
    (用户报"黄绿"), 且曲线暗部无约束 (0376 是亮场景) 导致暗图亮度偏差。
  v4 修复:
    1. 暖度 tint 感知 (engine/color.wb_to_temp_tint + whitebalance.apply_warmth):
       0376 (tint+27) 全量暖, 5236 (tint 0) 零暖 —— 白平衡级按图自适应。
    2. 影调曲线: **双图合并**亮度 CDF 匹配 (0376 覆盖中高光 + 5236 覆盖暗部),
       暗部端点得到 LR 真值约束; 一条共享曲线, 中性像素保持中性。
    3. 增益 k: 双图联合网格搜索 (tone 层), 目标 = 各图 LR 渲染的 a/b/S
       (下游 colorcal/refine 的偏移预先补偿)。

输出 engine/lr_tone_curve.json v3 格式 {"version":3, "gains":[r,g,b], "curve":[1024]}。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from rawlab.dcp import load_dcp
from rawlab.engine import stages as _  # noqa: F401  触发注册
from rawlab.engine.core import StageContext, STAGE_REGISTRY, DOMAIN_LINEAR_CAM
from rawlab.engine.decode import decode_raw

DEFAULT_DCP = (r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera"
               r"\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp")
PHOTOS = [(r"K:\data\photo\2026春节\DSC_0376.NEF",
           r"K:\work\project\guanlan\output\_lr_hist_tmp\DSC_0376.jpg"),
          (r"K:\data\photo\0711\raw\DSC_5236.NEF",
           r"K:\work\project\guanlan\output\_lr_hist_tmp\DSC_5236.jpg")]
OUT_JSON = ROOT / "rawlab" / "engine" / "lr_tone_curve.json"
N_PTS = 1024
WARMTH = 0.9  # 管线默认 warmth (tint 感知, 各图自适应强度)


def linear_rgb_before_tone(raw_path: str, prof, wb_warmth: float) -> np.ndarray:
    """解码 → 曝光(baseline, 对标 LR As Shot) → 白平衡(as_shot+warmth,
    tint 感知), 返回 linear_rgb (tone 输入)。"""
    img, raw = decode_raw(raw_path)
    ctx = StageContext(raw_path, raw=raw, prof=prof, config={"stages": {
        "exposure": {"mode": "baseline"},
        "whitebalance": {"warmth": wb_warmth},
    }})
    ctx.set_image(img, DOMAIN_LINEAR_CAM)
    ctx.state["half_size"] = False
    STAGE_REGISTRY["exposure"]().run(ctx)
    STAGE_REGISTRY["whitebalance"]().run(ctx)
    raw.close()
    return ctx.image.astype(np.float32)


def labsat(x: np.ndarray):
    u8 = (np.clip(np.asarray(x, np.float32), 0.0, 1.0) * 255.0).astype(np.uint8)
    lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    hsv = cv2.cvtColor(u8, cv2.COLOR_RGB2HSV)
    return (float(np.median(lab[..., 1]) - 128.0),
            float(np.median(lab[..., 2]) - 128.0),
            float(hsv[..., 1].mean()))


def stats8(x: np.ndarray) -> dict:
    u8 = (np.clip(np.asarray(x, np.float32), 0.0, 1.0) * 255.0).astype(np.uint8)
    per = np.percentile(u8, [1, 5, 50, 95, 99], axis=(0, 1))
    return {"p1": [round(float(v), 1) for v in per[0]],
            "p50": [round(float(v), 1) for v in per[2]],
            "p95": [round(float(v), 1) for v in per[3]],
            "std": [round(float(v), 1) for v in u8.std(axis=(0, 1))]}


def lum(x):
    return (0.2126 * x[..., 0] + 0.7152 * x[..., 1] + 0.0722 * x[..., 2])


def main():
    prof = load_dcp(DEFAULT_DCP)
    from rawlab.engine.pipeline import pipeline_from_config
    # 最终 LR 对齐配置 (2026-08-16 标定: 0376 a+5/b+12/S85 vs LR a+6/b+12/S78;
    # 5236 a+1/b-2 vs LR 0/-1, 亮度 p50 一致)
    LR_PARAMS = {"exposure": {"mode": "baseline"},
                 "tone": {"eotf": "lrfit"},
                 "colorcal": {"neutral_mode": "off", "saturation": -0.12},
                 "refine": {"highlight_desat": 0.25}}

    # ---- 1) 读两张 LR 导出 + 我们的线性 ----
    lins, lrs8, tags = [], [], []
    for raw_path, lr_path in PHOTOS:
        tags.append(Path(raw_path).name[:9])
        L = linear_rgb_before_tone(raw_path, prof, WARMTH)
        lr8 = cv2.cvtColor(cv2.imread(lr_path), cv2.COLOR_BGR2RGB).astype(
            np.float32) / 255.0
        lr8 = cv2.resize(lr8, (L.shape[1], L.shape[0]),
                         interpolation=cv2.INTER_AREA)
        lins.append(L)
        lrs8.append(lr8)

    # ---- 2) 共享影调曲线: 双图合并亮度 CDF 匹配 (线性 Y → LR gamma Y) ----
    Y1 = np.concatenate([lum(L) for L in lins]).ravel()
    YLR = np.concatenate([lum(lr) for lr in lrs8]).ravel()
    qs = np.linspace(0.0, 1.0, 65536)
    xs = np.quantile(Y1, qs)
    ys = np.quantile(YLR, qs)
    grid = np.linspace(0.0, 1.0, N_PTS)
    curve = np.clip(np.maximum.accumulate(np.interp(grid, xs, ys)), 0.0, 1.0)
    print(f"曲线低段采样: {np.round(curve[[8,16,32,64,128,256]], 3)} "
          f"(0.02/0.04/0.067/0.08/0.10/0.15 → LR gamma Y "
          f"{np.round(YLR[np.searchsorted(qs, [0.01,0.03,0.05,0.07,0.09,0.12])], 3)})")

    def apply_kf(x, k):
        y = np.empty_like(x)
        for c in range(3):
            y[..., c] = np.interp(np.clip(x[..., c] * k[c], 0.0, 1.0),
                                  grid, curve)
        return y

    # ---- 3) 下游偏移: 先把 (curve, 旧k) 写入 JSON, 用管线自身测 tone 层 vs 成品 ----
    old_gains = None
    try:
        old_gains = np.asarray(
            json.loads(OUT_JSON.read_text(encoding="utf-8")).get("gains"),
            dtype=np.float32)
    except Exception:
        pass
    k0 = old_gains if old_gains is not None and len(old_gains) == 3 \
        else np.ones(3, np.float32)
    OUT_JSON.write_text(json.dumps(
        {"version": 3, "gains": [round(float(g), 6) for g in k0],
         "curve": [round(float(v) * 255.0, 4) for v in curve]},
        ensure_ascii=False), encoding="utf-8")

    TONE_PARAMS = {"exposure": {"mode": "baseline"},
                   "tone": {"eotf": "lrfit"}}
    deltas = []
    print("\n下游偏移 (tone→成品, 旧 gains):")
    for (raw_path, _), tag in zip(PHOTOS, tags):
        pipe_tone = pipeline_from_config(
            {"stages": ["exposure", "whitebalance", "tone"],
             "params": TONE_PARAMS}, prof=prof)
        tone_img = pipe_tone.run_file(raw_path, prof=prof)
        a0, b0, S0 = labsat(tone_img.astype(np.float32) / 255.0)
        full = pipeline_from_config({"params": LR_PARAMS}, prof=prof) \
            .run_file(raw_path, prof=prof)
        af, bf, Sf = labsat(full.astype(np.float32) / 255.0)
        da, db, ds = af - a0, bf - b0, Sf - S0
        deltas.append((da, db, ds))
        print(f"  {tag}: a{da:+.1f} b{db:+.1f} S{ds:+.1f}")

    # ---- 4) 双图联合 k 网格搜索 (tone 层, 目标 = LR - 下游偏移) ----
    targets = []
    for lr8 in lrs8:
        targets.append(labsat(lr8))
    print("\nLR 目标 (tone 层, 减偏移后):")
    for tag, (a, b, S), (da, db, ds) in zip(tags, targets, deltas):
        print(f"  {tag}: a={a-da:+.1f} b={b-db:+.1f} S={S-ds:.1f} "
              f"(LR 原始 a={a:+.1f} b={b:+.1f} S={S:.1f})")
    lins_s = [L[::4, ::4] for L in lins]
    best, best_err = None, float("inf")
    for kr in np.linspace(0.70, 1.00, 7):
        for kg in np.linspace(1.00, 1.30, 7):
            for kb in np.linspace(1.00, 1.40, 9):
                k = np.array([kr, kg, kb], np.float32)
                err = 0.0
                for Ls, (a_t, b_t, S_t), (da, db, ds) in \
                        zip(lins_s, targets, deltas):
                    a, b, S = labsat(apply_kf(Ls, k))
                    err += ((a - (a_t - da)) ** 2 + (b - (b_t - db)) ** 2
                            + 0.5 * (S - (S_t - ds)) ** 2)
                if err < best_err:
                    best, best_err = k, err
    gains = best
    print(f"\ngains: R={gains[0]:.3f} G={gains[1]:.3f} B={gains[2]:.3f} err={best_err:.1f}")
    print("tone 层 (1/4, 新 k):")
    for tag, Ls, (a_t, b_t, S_t) in zip(tags, lins_s, targets):
        a, b, S = labsat(apply_kf(Ls, gains))
        print(f"  {tag}: a={a:+.1f} b={b:+.1f} S={S:.1f} (LR {a_t:+.1f}/{b_t:+.1f}/{S_t:.1f})")

    # ---- 5) 落盘 v3 JSON ----
    out = {"version": 3,
           "note": "v4 fit: dual-photo pooled luminance curve + tint-aware "
                   "warmth + joint gains; fit_lr_tone_v2.py (0376+5236 vs LR)",
           "gains": [round(float(g), 6) for g in gains],
           "curve": [round(float(v) * 255.0, 4) for v in curve]}  # 0..255 口径
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"\n已写 {OUT_JSON}")


if __name__ == "__main__":
    main()
