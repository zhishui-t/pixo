"""Assess auto-edit results from exports/auto/report/*.json.

Uses the Pixo Vision final full-resolution measurements to judge whether a
photo is qualified, and writes a JSON + Markdown summary.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

OUT = Path("exports/auto")


def judge(p: dict) -> tuple[bool, list[str], list[str]]:
    fm = p.get("final_measurement") or {}
    g = fm.get("global") or {}
    regs = (fm.get("regions") or {}).get("face") or {}
    face = regs if regs.get("reliable") else None
    mean = g.get("mean_luminance")
    hi = g.get("highlight_clip_ratio") or 0.0
    sh = g.get("shadow_clip_ratio") or 0.0
    contrast = g.get("contrast") or 0.0
    detail = g.get("detail") or {}
    motion = (detail.get("motion_blur") or {})
    haze = (detail.get("haze") or {})

    issues: list[str] = []
    notes: list[str] = []
    if hi > 0.03:
        issues.append(f"高光裁切 {hi:.1%} > 3%")
    elif hi > 0.01:
        notes.append(f"高光接近阈值 {hi:.1%}")
    if sh > 0.03:
        issues.append(f"阴影裁切 {sh:.1%} > 3%")
    elif sh > 0.01:
        notes.append(f"阴影偏大 {sh:.1%}")
    if face is not None:
        fl = face.get("mean_luminance")
        if fl is not None:
            if fl < 85:
                issues.append(f"人脸过暗 L={fl:.0f}")
            elif fl > 160:
                issues.append(f"人脸过亮 L={fl:.0f}")
            else:
                notes.append(f"人脸 L={fl:.0f}")
    else:
        if mean is not None:
            if mean < 75:
                issues.append(f"全图偏暗 L={mean:.0f}")
            elif mean > 170:
                issues.append(f"全图偏亮 L={mean:.0f}")
            else:
                notes.append(f"全图 L={mean:.0f}")
    if contrast < 0.2:
        issues.append(f"对比度偏低 {contrast:.2f}")
    ms = motion.get("strength")
    if ms is not None and ms > 0.8:
        notes.append(f"疑似运动模糊 strength={ms:.2f}")
    hs = haze.get("haze_density")
    if hs is not None and hs > 0.45:
        notes.append(f"雾霾/朦胧 {hs:.2f}")
    return (not issues, issues, notes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=OUT / "assessment.json")
    args = parser.parse_args()

    reports = sorted(OUT.glob("report/*.json")) if args.report is None else [args.report]
    rows = []
    for rp in reports:
        d = json.loads(rp.read_text(encoding="utf-8"))
        for p in d.get("photos", []):
            ok, issues, notes = judge(p)
            fm = p.get("final_measurement") or {}
            g = fm.get("global") or {}
            rows.append({
                "photo_id": p.get("photo_id"),
                "raw": p.get("raw"),
                "state": p.get("state"),
                "params": p.get("params"),
                "after_path": p.get("after_path"),
                "before_path": p.get("before_path"),
                "mean_luminance": g.get("mean_luminance"),
                "highlight_clip_ratio": g.get("highlight_clip_ratio"),
                "shadow_clip_ratio": g.get("shadow_clip_ratio"),
                "contrast": g.get("contrast"),
                "qualified": ok,
                "issues": issues,
                "notes": notes,
                "run_time_sec": p.get("run_time_sec"),
            })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    md = ["# Pixo 自动修图评估", ""]
    md.append(f"- 照片数: {len(rows)}")
    md.append(f"- 合格: {sum(r['qualified'] for r in rows)}")
    md.append(f"- 待人工/需再修: {sum(not r['qualified'] for r in rows)}")
    md.append("")
    for r in rows:
        mark = "✅" if r["qualified"] else "⚠️"
        md.append(f"## {mark} {r['photo_id']} ({r['state']})")
        md.append(f"- 输出: `{r['after_path']}`")
        md.append(f"- 参数: `{r['params']}`")
        md.append(f"- L={r['mean_luminance']:.0f} 高光={r['highlight_clip_ratio']:.2%} "
                  f"阴影={r['shadow_clip_ratio']:.2%} 对比={r['contrast']:.2f}")
        if r["issues"]:
            md.append(f"- 问题: {', '.join(r['issues'])}")
        if r["notes"]:
            md.append(f"- 备注: {', '.join(r['notes'])}")
        md.append("")
    md_path = args.out.with_suffix(".md")
    md_path.write_text("\n".join(md), encoding="utf-8")
    print(f"assessment saved: {args.out}")
    print(f"markdown saved: {md_path}")


if __name__ == "__main__":
    main()
