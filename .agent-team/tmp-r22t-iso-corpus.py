"""R22 tester 独立复算：真 RAW 语料 ISO 分布（EXIF 头解析，不渲染）。

口径与 exploration-r22 §1.5 同源（同一生产 EXIF 路径 `pixo.meta.extract`，
底层 exifread details=False）；本脚本额外记录快门/光圈/曝光程序，供 A/B 报告记 EV。
输出：.artifacts/r22-noise-ab/corpus-iso.json + stdout 摘要。
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pixo.meta import extract  # noqa: E402

RAW_DIR = Path(r"K:\data\photo\0711\raw")
OUT_DIR = ROOT / ".artifacts" / "r22-noise-ab"

# 与 exploration §1.5 同口径的补充字段（生产 meta 已归一化，这里直读 exifread 原文）
import exifread  # noqa: E402

_EXTRA_KEYS = ("EXIF ExposureTime", "EXIF FNumber", "EXIF ExposureProgram",
               "EXIF ShutterSpeedValue", "EXIF ApertureValue", "EXIF ISOSpeedRatings",
               "Image ISOSpeedRatings")


def raw_extra(path: Path) -> dict:
    try:
        with open(path, "rb") as fh:
            tags = exifread.process_file(fh, details=False)
    except Exception as exc:  # noqa: BLE001
        return {"_error": f"{type(exc).__name__}: {exc}"}
    out = {}
    for k in _EXTRA_KEYS:
        if k in tags:
            out[k.split()[-1] if k.startswith("EXIF") else k] = str(tags[k])
    return out


def main() -> int:
    files = sorted(RAW_DIR.glob("*.NEF"))
    hist: Counter[int] = Counter()
    rows = []
    failed = 0
    for p in files:
        try:
            meta = extract(str(p))
        except Exception:  # noqa: BLE001
            failed += 1
            continue
        # 实测（tester 复算修正 exploration §1.5 措辞）：ISO 在 meta["exposure"]["iso"]，
        # 不在顶层 meta["iso"]（src/pixo/meta/exif.py:452-457）。
        iso = None
        if isinstance(meta, dict):
            iso = (meta.get("exposure") or {}).get("iso") or meta.get("iso")
        try:
            iso = int(iso)
        except (TypeError, ValueError):
            iso = -1
        hist[iso] += 1
        if iso >= 3200:
            ex = raw_extra(p)
            rows.append({"file": p.name, "iso": iso,
                         "shutter": ex.get("ExposureTime"),
                         "fnumber": ex.get("FNumber"),
                         "program": ex.get("ExposureProgram"),
                         "model": (meta.get("model") if isinstance(meta, dict) else None)})
    rows.sort(key=lambda r: (-r["iso"], r["file"]))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "raw_dir": str(RAW_DIR),
        "nef_total": len(files),
        "parse_failed": failed,
        "iso_hist": sorted(hist.items()),
        "iso_ge_1600": sum(n for k, n in hist.items() if k >= 1600),
        "iso_ge_3200": len(rows),
        "iso_ge_3200_files": rows,
    }
    (OUT_DIR / "corpus-iso.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"RAW_DIR              = {RAW_DIR}")
    print(f"NEF total            = {len(files)}  (parse_failed={failed})")
    print(f"ISO histogram        = {payload['iso_hist']}")
    print(f"ISO>=1600            = {payload['iso_ge_1600']}")
    print(f"ISO>=3200            = {payload['iso_ge_3200']}")
    for r in rows:
        print(f"  {r['file']:16s} ISO={r['iso']:6d} shutter={r['shutter']!s:8s} "
              f"f/{r['fnumber']!s:6s} prog={r['program']!s:4s} model={r['model']}")
    print(f"[wrote] {OUT_DIR / 'corpus-iso.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
