"""路径自检 + 汇总 spike_report.json。"""
from __future__ import annotations

import json
import pathlib

print("cwd    =", pathlib.Path.cwd())
print("__file__ =", __file__)
print("file   =", pathlib.Path(__file__).resolve())
print("p0     =", pathlib.Path(__file__).resolve().parents[0])
print("p1     =", pathlib.Path(__file__).resolve().parents[1])
print("p2     =", pathlib.Path(__file__).resolve().parents[2])

for cand in (pathlib.Path(__file__).resolve().parents[1] / ".artifacts" / "r22-f02-spike" / "spike_report.json",
             pathlib.Path(__file__).resolve().parents[2] / ".artifacts" / "r22-f02-spike" / "spike_report.json",
             pathlib.Path.cwd() / ".artifacts" / "r22-f02-spike" / "spike_report.json"):
    print("cand", cand, cand.exists())
    if cand.exists():
        P = cand
        break
else:
    raise SystemExit("spike_report.json 未找到")

r = json.loads(P.read_text(encoding="utf-8"))
print("decode_full_ms", r["decode_full_ms"], "full_shape", r["full_shape"])
for tier, e in r["tiers"].items():
    print(f"== tier {tier} shape={e['shape']} timing_ms={e['timing_ms']}")
    b = e["baseline"]
    print(f"   baseline                 noise={b['noise_ratio']:.4f}  detail={b['detail_score']:.2f}")
    for k, v in e["variants"].items():
        print(f"   {k:24s} noise={v['noise_ratio']:.4f} ({v['noise_ratio_drop_pct']:6.2f}%) "
              f"detail={v['detail_score']:8.2f} ({v['detail_score_drop_pct']:7.2f}%)")
e2 = r.get("second_image_1024")
if e2:
    print(f"== second(ISO8000) 1024 shape={e2['shape']} timing_ms={e2['timing_ms']}")
    b = e2["baseline"]
    print(f"   baseline                 noise={b['noise_ratio']:.4f}  detail={b['detail_score']:.2f}")
    for k, v in e2["variants"].items():
        print(f"   {k:24s} noise={v['noise_ratio']:.4f} ({v['noise_ratio_drop_pct']:6.2f}%) "
              f"detail={v['detail_score']:8.2f} ({v['detail_score_drop_pct']:7.2f}%)")
