"""R22 标定后处理：解析 tmp-r22-calib-out.txt 逐行结果 → 分组分位表。

可对**部分完成**的运行出表（逐行解析，不依赖脚本跑完）。
命令：python .agent-team/tmp-r22-calib-report.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import numpy as np

LOG = Path(__file__).resolve().parent / "tmp-r22-calib-out.txt"
LINE = re.compile(
    r"^(DSC_\d+\.NEF)\tiso=(\S+)\t(\d+)x(\d+)\tnoise=([\d.]+)\t"
    r"detail=([\d.]+)\tcolorful=(\S+)\t"
)


def pct(values: list[float], q: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))


def _read_log_text() -> str:
    """读日志文本（PowerShell `>` 重定向可能是 UTF-16LE，按 BOM/NUL 嗅探）。"""
    raw = LOG.read_bytes()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    if raw[:200].count(b"\x00") > 20:
        return raw.decode("utf-16-le", errors="replace")
    return raw.decode("utf-8", errors="replace")


def main() -> int:
    if not LOG.exists():
        print("NO LOG:", LOG)
        return 2
    rows = []
    for line in _read_log_text().splitlines():
        m = LINE.match(line.strip())
        if not m:
            continue
        name, iso, w, h, noise, detail, colorful = m.groups()
        try:
            iso_i = int(iso)
        except ValueError:
            iso_i = None
        try:
            colorful_f = float(colorful)
        except ValueError:
            colorful_f = None
        rows.append({
            "file": name, "iso": iso_i, "w": int(w), "h": int(h),
            "noise": float(noise), "detail": float(detail),
            "colorful": colorful_f,
        })
    print(f"parsed rows = {len(rows)}")
    if not rows:
        return 1

    def report(label: str, subset: list[dict]) -> None:
        print(f"\n[{label}] n={len(subset)}")
        if not subset:
            return
        for key, name in (("noise", "noise_ratio"),
                          ("detail", "detail_score"),
                          ("colorful", "colorfulness_proxy")):
            vals = [r[key] for r in subset if r[key] is not None]
            if not vals:
                continue
            print(f"  {name}: min={min(vals):.4f} p05={pct(vals,5):.4f} "
                  f"p10={pct(vals,10):.4f} p25={pct(vals,25):.4f} "
                  f"p50={pct(vals,50):.4f} p75={pct(vals,75):.4f} "
                  f"p90={pct(vals,90):.4f} p95={pct(vals,95):.4f} "
                  f"max={max(vals):.4f}")

    known = [r for r in rows if r["iso"] is not None]
    hi = [r for r in known if r["iso"] >= 3200]
    lo = [r for r in known if r["iso"] <= 1600]
    report("ALL(iso known)", known)
    report("ISO>=3200", hi)
    report("ISO<=1600", lo)
    print("\nper-file:")
    for r in rows:
        print(f"  {r['file']} iso={r['iso']:>6} noise={r['noise']:.4f} "
              f"detail={r['detail']:>7} colorful={r['colorful']}")

    # 落地逐行 TSV（loop.py / noise_rules.yaml 注释引用的证据文件）
    tsv = Path(__file__).resolve().parent / "tmp-r22-calib-rows.tsv"
    lines = ["file\tiso\twidth\theight\tnoise_ratio\tdetail_score\t"
             "colorfulness_proxy"]
    for r in rows:
        lines.append(f"{r['file']}\t{r['iso']}\t{r['w']}\t{r['h']}\t"
                     f"{r['noise']}\t{r['detail']}\t{r['colorful']}")
    tsv.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nwrote {tsv} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
