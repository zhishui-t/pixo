"""R22 dev-2 F08 只读复核探针 (仓库零改动)。

运行: python .agent-team/tmp-r22d2-f08-probe.py > .agent-team/tmp-r22d2-f08-probe-out.txt
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "regression" / "goldens"))
sys.path.insert(0, str(ROOT / "tests" / "unit"))

import numpy as np  # noqa: E402

# ---- A) 六常数 ↔ configs/color/skin_oklab.json IEEE754 逐位 == ----
from pixo.render.core import skin as skin_mod  # noqa: E402

cfg = json.loads((ROOT / "configs" / "color" / "skin_oklab.json")
                 .read_text(encoding="utf-8"))
print("== A) 六常数 ↔ skin_oklab.json (IEEE754 逐位) ==")
print("schema =", cfg.get("schema"))
consts = cfg["constants"]
pairs = [
    ("SKIN_OKLAB_A", skin_mod.SKIN_OKLAB_A),
    ("SKIN_OKLAB_B", skin_mod.SKIN_OKLAB_B),
    ("SKIN_OKLAB_MAJOR", skin_mod.SKIN_OKLAB_MAJOR),
    ("SKIN_OKLAB_MINOR", skin_mod.SKIN_OKLAB_MINOR),
    ("SKIN_OKLAB_ANGLE", skin_mod.SKIN_OKLAB_ANGLE),
    ("SKIN_OKLAB_SOFT_BAND", skin_mod.SKIN_OKLAB_SOFT_BAND),
]
all_ok = True
for name, code_val in pairs:
    j = float(consts[name])
    ok = (j == code_val)
    all_ok &= ok
    print(f"  {name:22s} code={code_val!r:22s} hex={float(code_val).hex():24s} "
          f"json={j!r:22s} 逐位== {ok}")
print("  六常数逐位一致 =", all_ok)

# ---- B) angle ↔ angle_deg ----
deg_json = float(cfg["new_ellipse_fit"]["angle_deg"])
deg_code = float(np.degrees(skin_mod.SKIN_OKLAB_ANGLE))
print("== B) angle↔rad ==")
print(f"  degrees(SKIN_OKLAB_ANGLE) = {deg_code:.6f}  json angle_deg = {deg_json}  "
      f"|Δ| = {abs(deg_code - deg_json):.2e} (容差 1e-3)")

# ---- C) gate_cases: skin_oklch / skin_oklch_softband 真实存在且与基线一致 ----
import gate_cases  # noqa: E402
import generate_gate_goldens  # noqa: E402

print("== C) gate_cases ==")
print("  FEATURES 含 skin_oklch =", "skin_oklch" in gate_cases.FEATURES,
      "| skin_oklch_softband =", "skin_oklch_softband" in gate_cases.FEATURES,
      "| FEATURES 总数 =", len(gate_cases.FEATURES))
golden_dir = ROOT / "tests" / "regression" / "goldens" / "gate"
manifest = json.loads((golden_dir / "manifest.json").read_text(encoding="utf-8"))
print("  manifest schema =", manifest.get("schema"),
      "| features =", len(manifest["features"]),
      "| reviewer =", manifest.get("reviewer"))
for feat in ("skin", "skin_oklch", "skin_oklch_softband"):
    meta = manifest["features"][feat]
    cur = np.asarray(gate_cases.compute(feat))
    exp = np.load(golden_dir / meta["file"])
    err = float(np.abs(cur.astype(np.float64) - exp.astype(np.float64)).max())
    print(f"  {feat:20s} file={meta['file']:34s} shape={meta['shape']} "
          f"dtype={meta['dtype']} max|Δ|={err:.3e} <=1e-6 {err <= 1e-6}")
print("  generate_gate_goldens.run_check(rc) =", generate_gate_goldens.run_check(golden_dir))

# ---- D) 两个一致性测试真实存在 ----
import inspect  # noqa: E402
import test_skin_oklab as tso  # noqa: E402

print("== D) 一致性测试存在性 ==")
for fname in ("test_skin_oklab_constants_bitwise_locked_to_fit_json",
              "test_skin_oklab_json_angle_deg_consistent_with_constant"):
    fn = getattr(tso, fname, None)
    print(f"  {fname}: 定义于 {inspect.getsourcefile(fn).split('pixo')[-1]}:"
          f"{inspect.getsourcelines(fn)[1]}")
print("F08-PROBE-DONE")
