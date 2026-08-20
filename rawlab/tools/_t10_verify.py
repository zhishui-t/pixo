"""_t10_verify —— T10 收尾: 应用域 HSM sat_scale 网格验证 5236/0376, 更新 LR 基准 DCP。"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(r"K:\work\project\RawFlow")
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np

from rawlab.dcp import load_dcp, write_dcp
from rawlab.engine import stages as _  # noqa
from rawlab.engine.core import StageContext, STAGE_REGISTRY, DOMAIN_LINEAR_CAM
from rawlab.engine.decode import decode_raw
from rawlab.engine.huesat import make_hue_sat_map
from rawlab.tools.fit_camera_profile import magenta_band_mask

LR_DCP = ROOT / "rawlab" / "profiles" / "Nikon Z 5 2 RawLab LR Baseline.dcp"
LR_PRESET = ROOT / "rawlab" / "presets" / "lr_baseline.json"
ANCHORS = [(r"K:\data\photo\2026春节\DSC_0376.NEF",
            r"K:\work\project\guanlan\output\_lr_hist_tmp\DSC_0376.jpg"),
           (r"K:\data\photo\0711\raw\DSC_5236.NEF",
            r"K:\work\project\guanlan\output\_lr_hist_tmp\DSC_5236.jpg")]
OUT = ROOT / "rawlab" / "out" / "profile_fit" / "t10_hsm_domain_verify.json"


def linear_with_warmth(raw_path, prof, warmth=0.9, trim=(1.0, 1.05, 0.9)):
    img, raw = decode_raw(raw_path)
    s = raw.sizes
    left, top = int(s.crop_left_margin), int(s.crop_top_margin)
    w, h = int(s.crop_width), int(s.crop_height)
    if left + w <= img.shape[1] and top + h <= img.shape[0]:
        img = img[top:top + h, left:left + w].copy()
    ctx = StageContext(raw_path, raw=raw, prof=prof, config={"stages": {
        "exposure": {"mode": "baseline"},
        "whitebalance": {"warmth": warmth, "trim": list(trim)}}})
    ctx.set_image(img, DOMAIN_LINEAR_CAM)
    ctx.state["half_size"] = False
    STAGE_REGISTRY["exposure"]().run(ctx)
    STAGE_REGISTRY["whitebalance"]().run(ctx)
    raw.close()
    return ctx.image.astype(np.float32)


def highlight_metrics(out, target):
    """高光区 (L*>160) 的 Δa/Δb 与 n; out/target 为 RGB uint8 同尺寸。"""
    lab = cv2.cvtColor(out, cv2.COLOR_RGB2LAB).astype(np.float32)
    lt = cv2.cvtColor(target, cv2.COLOR_RGB2LAB).astype(np.float32)
    m = lt[..., 0] > 160
    da = float(np.median(lab[m, 1]) - np.median(lt[m, 1]))
    db = float(np.median(lab[m, 2]) - np.median(lt[m, 2]))
    return da, db, int(m.sum())


def main():
    prof = load_dcp(LR_DCP)
    preset = json.loads(LR_PRESET.read_text(encoding="utf-8"))

    # 1) 应用域掩码 + sat_scale 数据拟合 (两锚点)
    ratios = []
    stats = {}
    for raw_path, lr_path in ANCHORS:
        name = Path(raw_path).name
        lin = linear_with_warmth(raw_path, prof)
        lin8 = cv2.resize(lin, (lin.shape[1] // 8, lin.shape[0] // 8),
                          interpolation=cv2.INTER_AREA)
        target = cv2.cvtColor(cv2.imread(lr_path), cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        target8 = cv2.resize(target, (lin8.shape[1], lin8.shape[0]),
                             interpolation=cv2.INTER_AREA)
        mask = magenta_band_mask(lin8, encoding=1)
        # gamma 渲染 (LR DCP 曲线) 用于 Lab C* 对比
        grid = np.linspace(0, 1, 1024)
        from rawlab.engine.curves import parse_profile_curve, curve_lut_from_points
        xs, ys = parse_profile_curve(prof.profile_tone_curve)
        lut = curve_lut_from_points(xs, ys, 1024)
        ours = np.empty_like(lin8)
        for c in range(3):
            ours[..., c] = np.interp(np.clip(lin8[..., c], 0, 1), grid, lut)
        ou8 = (np.clip(ours, 0, 1) * 255 + 0.5).astype(np.uint8)
        tu8 = (np.clip(target8, 0, 1) * 255 + 0.5).astype(np.uint8)
        lo = cv2.cvtColor(ou8, cv2.COLOR_RGB2LAB).astype(np.float32)
        lt = cv2.cvtColor(tu8, cv2.COLOR_RGB2LAB).astype(np.float32)
        Co = np.sqrt((lo[mask, 1] - 128) ** 2 + (lo[mask, 2] - 128) ** 2)
        Ct = np.sqrt((lt[mask, 1] - 128) ** 2 + (lt[mask, 2] - 128) ** 2)
        keep = Co > 1.0
        stats[name] = {"n_mask": int(mask.sum()), "n_keep": int(keep.sum())}
        if keep.any():
            ratios.append(Ct[keep] / Co[keep])
        print(f"{name}: 应用域品红掩码 {stats[name]['n_mask']} px, "
              f"C*>1 {stats[name]['n_keep']} px")
    data_sat = float(np.median(np.concatenate(ratios))) if ratios else None
    print(f"应用域数据拟合 sat_scale = {data_sat:.3f}" if data_sat else "无品红样本")

    # 2) sat_scale 网格渲染验证
    from rawlab.engine.pipeline import pipeline_from_config
    results = []
    for sat in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.55]:
        prof.hue_sat_map = make_hue_sat_map([(272.5, 37.5, sat)])
        prof.hue_sat_dims = [90, 16, 16]
        prof.hue_sat_encoding = 1
        pipe = pipeline_from_config({"params": preset["params"]}, prof=prof)
        err, row = 0.0, {"sat": sat}
        for raw_path, lr_path in ANCHORS:
            name = Path(raw_path).name
            out = pipe.run_file(raw_path, prof=prof)
            s = None
            import rawpy
            with rawpy.imread(raw_path) as r:
                s = r.sizes
            left, top = int(s.crop_left_margin), int(s.crop_top_margin)
            w, h = int(s.crop_width), int(s.crop_height)
            if left + w <= out.shape[1] and top + h <= out.shape[0]:
                out = out[top:top + h, left:left + w]
            tgt = cv2.cvtColor(cv2.imread(lr_path), cv2.COLOR_BGR2RGB)
            tgt = cv2.resize(tgt, (out.shape[1], out.shape[0]),
                             interpolation=cv2.INTER_AREA)
            da, db, n = highlight_metrics(out, tgt)
            row[name] = {"da": round(da, 1), "db": round(db, 1), "n": n}
            err += abs(da) + abs(db)
            print(f"  sat={sat:.2f} {name}: 高光区 Δa={da:+.1f} Δb={db:+.1f}")
        results.append((err, row))
    results.sort(key=lambda t: t[0])
    best = results[0][1]
    print(f"最优 sat={best['sat']:.2f} err={results[0][0]:.1f}")

    # 3) 写回 DCP + 验证 JSON
    prof = load_dcp(LR_DCP)
    prof.hue_sat_map = make_hue_sat_map([(272.5, 37.5, best["sat"])])
    prof.hue_sat_dims = [90, 16, 16]
    prof.hue_sat_encoding = 1
    write_dcp(LR_DCP, prof)
    out = {"t10_fixed": True, "data_sat": round(data_sat, 4) if data_sat else None,
           "best": best, "grid": [r for _, r in results], "anchor_stats": stats}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写 {OUT}")


if __name__ == "__main__":
    main()
