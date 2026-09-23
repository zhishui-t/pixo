"""R22 F02 spike 语料选片: rawpy.extract_thumb 毫秒级预检, 挑 ISO>=3200。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import rawpy

RAW_DIR = Path(r"K:\data\photo\0711\raw")


def iso_of(path: Path):
    import exifread
    with path.open("rb") as f:
        tags = exifread.process_file(f, details=False)
    for key in ("EXIF ISOSpeedRatings", "Image ISOSpeedRatings",
                "EXIF ISOSpeed", "MakerNote ISO"):
        if key in tags:
            try:
                return int(str(tags[key]))
            except Exception:
                pass
    return None


def ev_of(path: Path):
    import exifread
    with path.open("rb") as f:
        tags = exifread.process_file(f, details=False)
    et = tags.get("EXIF ExposureTime")
    fn = tags.get("EXIF FNumber")
    try:
        et_v = float(str(et).split("/")[0]) / float(str(et).split("/")[1]) \
            if "/" in str(et) else float(str(et))
    except Exception:
        et_v = None
    try:
        fn_v = float(str(fn))
    except Exception:
        fn_v = None
    return et_v, fn_v


def main():
    files = sorted(RAW_DIR.glob("*.NEF"))
    rows = []
    for p in files:
        iso = iso_of(p)
        if iso is None or iso < 3200:
            continue
        et, fn = ev_of(p)
        thumb_ok = False
        shape = None
        t0 = __import__("time").perf_counter()
        try:
            with rawpy.imread(str(p)) as raw:
                t = raw.extract_thumb()
            thumb_ok = True
            shape = (t.data.shape if hasattr(t.data, "shape") else None)
        except Exception as exc:  # noqa: BLE001
            thumb_ok = f"ERR:{type(exc).__name__}"
        dt = (__import__("time").perf_counter() - t0) * 1000.0
        rows.append({"name": p.name, "iso": iso, "exp_s": et, "f": fn,
                     "thumb_ok": thumb_ok, "thumb_ms": round(dt, 1),
                     "path": str(p)})
    rows.sort(key=lambda r: (-r["iso"], r["name"]))
    print(json.dumps({"count": len(rows), "rows": rows},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
