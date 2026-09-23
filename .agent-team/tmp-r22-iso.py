"""R22 dev-1：探 meta.extract 的 ISO 键形态（一次性）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from pixo.meta import extract  # noqa: E402

for name in ("DSC_5236.NEF", "DSC_5314.NEF"):
    p = Path(r"K:\data\photo\0711\raw") / name
    if not p.exists():
        print(name, "MISSING")
        continue
    try:
        meta = extract(str(p))
    except Exception as exc:  # noqa: BLE001
        print(name, "EXC", type(exc).__name__, exc)
        continue
    print(name, "type=", type(meta).__name__, "len=", len(meta))
    print("  keys:", sorted(meta)[:40])
    for k in ("iso", "ISO", "iso_speed", "Iso", "camera", "model"):
        if k in meta:
            print(f"  {k} = {meta[k]!r}")
