"""R22 / F01+F06 —— 端到端探针（一次性；输出重定向到文件再读）。

验证四件事（对应用户验收）：
  ① 4 层路径 `global.detail.sharpness.noise_ratio/detail_score` 展平进扁平键；
  ② 键宇宙（metric_universe）含两新键；
  ③ F06 软告警在真实 `VisionMeasure.measure` 报告上可组装（非门禁）；
  ④ 装配层 `_load_auto_loop_rules` 加载面含新规则且 enabled=False（生产零影响）。
另打印被测模块路径（证明吃的是 src 而非 build/lib 旧副本）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pixo.pipeline.metrics as metrics_mod              # noqa: E402
from pixo.pipeline.loop import _qc_soft_warnings          # noqa: E402
from pixo.pipeline.metrics import (                       # noqa: E402
    METRIC_KEYS,
    metric_universe,
    metrics_for_decide,
)
from pixo.service.runtime import _load_auto_loop_rules    # noqa: E402
from pixo.vision.measure import VisionMeasure, compute_proxy_metrics  # noqa: E402

img = np.random.default_rng(20260910).integers(0, 256, (96, 128, 3), dtype=np.uint8)
report = VisionMeasure().measure(img, {"face": np.ones((96, 128), dtype=bool)})
flat = metrics_for_decide(report)

print("[module]", metrics_mod.__file__)
print("[① 4-layer flatten] sharpness =",
      report["global"]["detail"]["sharpness"])
print("[① flat keys]", {k: flat.get(k) for k in ("noise_ratio", "detail_score")})
print("[① negative] fft_high_ratio leaked:", "fft_high_ratio" in flat)

universe = metric_universe(("face", "sky", "plant"))
print("[② METRIC_KEYS]", sorted(METRIC_KEYS))
print("[② universe] n =", len(universe),
      "| has noise keys =", {"noise_ratio", "detail_score"} <= set(universe))

report.update(compute_proxy_metrics(img))
print("[③ proxies] colorfulness_proxy =", report.get("colorfulness_proxy"))
print("[③ soft_warnings] ", _qc_soft_warnings(report))

rules = _load_auto_loop_rules(("face", "sky", "plant"))
noise = [r for r in rules if r.get("rule_id") == "noise_luminance_rule_040"]
print("[④ auto-loop rules] n =", len(rules), "| ids =",
      [r.get("rule_id") for r in rules])
print("[④ noise rule]", [(r["rule_id"], r["enabled"],
                          r["condition"]["metric"], r["action"]["param"])
                         for r in noise])
