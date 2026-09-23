# R32-T1 tester 复算: A/B 抽 3 片重跑 RCD/AHD 两臂, 对照 .artifacts/_r32_t1_ab.json 记录值。
# tester-whitebox, 2026-09-23。口径 = _r32_t1_ab.py 原函数直接 import (metrics/降采样/边缘带
# 与 dev 全量 A/B 完全同源, 零重写), 子采样索引同族 idx=floor(i*48/12)。
# 抽片: DSC_0352 (横拍基线), DSC_1319 (竖拍 flip=5, 方向 bug 案发片), DSC_5278 (记录值
# 最差 fc_ratio_ratio=1.9479, 复现误差最显眼)。
import json
import os
import sys
import time

import numpy as np

ROOT = r"K:/work/project/pixo"
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, ".artifacts"))

import _r32_t1_ab as ab  # noqa: E402  (原脚本函数: metrics/down512/edge_mask/hf)
from pixo.render import degradation  # noqa: E402
from pixo.render.core import io  # noqa: E402
from pixo.render.core.oklab import srgb_to_oklab  # noqa: E402

REFS = os.path.join(ROOT, ".artifacts", "_r31_refs")
RECORDED = json.load(open(os.path.join(ROOT, ".artifacts", "_r32_t1_ab.json"),
                          encoding="utf-8"))
PICK = ["DSC_0352.dng", "DSC_1319.dng", "DSC_5278.dng"]
# 容差: 解码链确定性 (同 DLL/rawpy/libraw/cv2), 记录值含 4-6 位舍入;
# 0.02 绝对容差覆盖舍入 + 浮点库版本漂移, 远小于判定语义距离。
TOL_FC = 0.02
TOL_DR = 0.02
TOL_DE = 0.01


def med(xs):
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else 0.5 * (xs[n // 2 - 1] + xs[n // 2])


def main():
    rec_rows = {r["file"]: r for r in RECORDED["rows"]}
    results, all_ok = [], True
    for name in PICK:
        path = os.path.join(REFS, name)
        assert os.path.exists(path), f"missing corpus file: {path}"
        rec = rec_rows[name]

        deg_before = len(degradation.render_degraded_entries())
        # ---- AHD 臂 (热身 1 + 计时 2, 同原口径) ----
        img_a, _ = io.decode_raw(path, demosaic="AHD")
        times_a = []
        for _ in range(2):
            t0 = time.perf_counter()
            img_a, _ = io.decode_raw(path, demosaic="AHD")
            times_a.append((time.perf_counter() - t0) * 1000.0)
        m_a = ab.metrics(img_a)
        a512 = ab.down512(img_a)

        # ---- RCD 臂 ----
        img_r, _ = io.decode_raw(path, demosaic="RCD")
        times_r = []
        for _ in range(2):
            t0 = time.perf_counter()
            img_r, _ = io.decode_raw(path, demosaic="RCD")
            times_r.append((time.perf_counter() - t0) * 1000.0)
        deg_after = len(degradation.render_degraded_entries())
        m_r = ab.metrics(img_r)
        r512 = ab.down512(img_r)

        lab_a = srgb_to_oklab(a512.astype(np.float32))
        lab_r = srgb_to_oklab(r512.astype(np.float32))
        deltae = float(np.sqrt(np.sum((lab_r - lab_a) ** 2, axis=-1)).mean())
        fc_rr = round(m_r["fc_ratio"] / max(m_a["fc_ratio"], 1e-12), 4)
        dr_rr = round(m_r["detail_rms"] / max(m_a["detail_rms"], 1e-12), 4)
        fallback = deg_after > deg_before

        # ---- 方向正确性 ----
        raw = __import__("rawpy").imread(path)
        flip = int(raw.sizes.flip)
        shape_a, shape_r = img_a.shape, img_r.shape
        same_shape = shape_a == shape_r
        rec_h, rec_w = rec["size"][1], rec["size"][0]
        orient_ok = shape_a[:2] == (rec_h, rec_w)
        portrait = shape_a[0] > shape_a[1]

        d_fc = abs(fc_rr - rec["fc_ratio_ratio"])
        d_dr = abs(dr_rr - rec["detail_rms_ratio"])
        d_de = abs(round(deltae, 5) - rec["deltae512_mean"])
        checks = {
            "shape_match_two_arms": same_shape,
            "orientation_matches_recorded": orient_ok,
            "no_fallback": not fallback,
            "fc_ratio_ratio_within_tol": d_fc <= TOL_FC,
            "detail_rms_ratio_within_tol": d_dr <= TOL_DR,
            "deltae_within_tol": d_de <= TOL_DE,
        }
        ok = all(checks.values())
        all_ok &= ok
        row = {
            "file": name,
            "flip": flip,
            "portrait": bool(portrait),
            "shape": [int(shape_a[1]), int(shape_a[0])],
            "rec_shape": rec["size"],
            "ahd_ms": round(sum(times_a) / 2, 1),
            "rcd_ms": round(sum(times_r) / 2, 1),
            "time_ratio": round((sum(times_r) / 2) / max(sum(times_a) / 2, 1e-9), 3),
            "rec_time_ratio": rec["time_ratio"],
            "fallback": fallback,
            "fc_ratio_ratio": fc_rr, "rec_fc_ratio_ratio": rec["fc_ratio_ratio"],
            "d_fc": round(d_fc, 4),
            "detail_rms_ratio": dr_rr, "rec_detail_rms_ratio": rec["detail_rms_ratio"],
            "d_dr": round(d_dr, 4),
            "deltae512_mean": round(deltae, 5),
            "rec_deltae512_mean": rec["deltae512_mean"],
            "d_de": round(d_de, 5),
            "checks": checks, "ok": ok,
        }
        results.append(row)
        print(f"[{name}] flip={flip} portrait={portrait} "
              f"fc_rr={fc_rr} (rec {rec['fc_ratio_ratio']}, d={d_fc:.4f}) "
              f"dr_rr={dr_rr} (rec {rec['detail_rms_ratio']}, d={d_dr:.4f}) "
              f"deltae={deltae:.5f} (rec {rec['deltae512_mean']}) "
              f"fallback={fallback} -> {'OK' if ok else 'FAIL'}", flush=True)
        del img_a, img_r, a512, r512, lab_a, lab_r

    fc_recs = [rec_rows[n]["fc_ratio_ratio"] for n in PICK]
    fc_news = [r["fc_ratio_ratio"] for r in results]
    summary = {
        "n": len(results),
        "median_fc_ratio_ratio_recomputed": med(fc_news),
        "median_fc_ratio_ratio_recorded": med(fc_recs),
        "median_time_ratio_recomputed": med([r["time_ratio"] for r in results]),
        "fallbacks": sum(1 for r in results if r["fallback"]),
        "all_checks_pass": all_ok,
        "tolerances": {"fc_ratio_ratio": TOL_FC, "detail_rms_ratio": TOL_DR,
                       "deltae512_mean": TOL_DE},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    json.dump({"summary": summary, "rows": results},
              open(os.path.join(ROOT, ".agent-team", "tmp-r32t1-ab-recompute.json"),
                   "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
