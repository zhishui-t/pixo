"""R22 dev-2 F03 自检探针: 语法/导入/L1+L2 联通 (只读, 不改仓库).

运行: python .agent-team/tmp-r22d2-probe.py > .agent-team/tmp-r22d2-probe.txt 2>&1
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from pixo.render import degradation as deg  # noqa: E402
from pixo.render.modules.white_balance import _load_warm_cal, _reset_caches  # noqa: E402
from pixo.vision.health import vision_health  # noqa: E402

print("== 1) classify_native_failure 判定 ==")
cases = [
    RuntimeError("native colorcal oklch F32 kernel unavailable (需 DLL >= 1.6.0, 实际 (1, 5, 0))"),
    RuntimeError("native clarity kernel unavailable (DLL 未导出)"),
    RuntimeError("native DLL unavailable: native DLL not found: X.dll"),
    ValueError("boom"),
    None,
]
for c in cases:
    print(f"  {deg.classify_native_failure(c)!r:22} <- {c!r}")

print("== 2) 写坏 warmth_curve 副本 -> degraded + health 暴露 ==")
deg.clear_render_degradations()
with tempfile.TemporaryDirectory() as td:
    broken = Path(td) / "warmth_curve.json"
    broken.write_text('{"knots": [[1.0, 1.0, 1.0, 1.0],', encoding="utf-8")
    _reset_caches()
    out = _load_warm_cal(broken)
    print(f"  _load_warm_cal(corrupt) -> {out}")
    entries = deg.render_degraded_entries()
    print(f"  degraded entries = {len(entries)}")
    if entries:
        e = dict(entries[0])
        e["detail"] = e["detail"][:24]
        print("  entry:", json.dumps(e, ensure_ascii=False))

health = vision_health()
print("== 3) vision_health 增量键 ==")
for k in ("render_degraded_count", "render_status", "render_version_gate_count"):
    print(f"  {k} = {health.get(k)!r}")
print(f"  render_degraded sources = {[e['source'] for e in health['render_degraded']]}")
print(f"  status/ready 未变 = {health['status']!r}/{health['ready']!r}")

print("== 4) 版本门合法拒绝 -> 不进 degraded ==")
deg.clear_render_degradations()
deg.record_degradation(
    "render.color_cal.native_f32",
    RuntimeError("native colorcal oklch F32 kernel unavailable (需 DLL >= 1.6.0, 实际 (1, 5, 0))"),
    reason="version_gate", detail="探针")
print(f"  degraded = {len(deg.render_degraded_entries())}, "
      f"version_gate = {len(deg.version_gate_rejections())}")
deg.clear_render_degradations()
print("PROBE-OK")
