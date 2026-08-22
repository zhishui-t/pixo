"""Build final summary combining all auto-edit reports, refinements and full scans."""
from __future__ import annotations

import json
import glob
from pathlib import Path

REPORT_GLOB = "exports/auto/report/auto_report_*.json"
REFINED_GLOB = "exports/auto/refined/refined_*.json"
FULL_SCAN_GLOB = "exports/auto/full_scan/full_scan_*.json"
MANUAL_FALLBACK_GLOB = "exports/auto/full_scan/manual_fallback_*.json"
OUT_JSON = Path("exports/auto/final_assessment.json")
OUT_MD = Path("exports/auto/SUMMARY.md")


def evaluate(fm):
    g = fm.get("global") or {}
    regs = fm.get("regions") or {}
    face = regs.get("face") or {}
    mean = g.get("mean_luminance")
    hi = g.get("highlight_clip_ratio") or 0
    sh = g.get("shadow_clip_ratio") or 0
    contrast = g.get("contrast") or 0
    motion = (g.get("detail") or {}).get("motion_blur") or {}
    issues = []
    notes = []
    if hi > 0.03:
        issues.append(f"高光裁切 {hi:.1%}")
    elif hi > 0.01:
        notes.append(f"高光接近阈值 {hi:.1%}")
    if sh > 0.08:
        issues.append(f"阴影裁切 {sh:.1%}")
    elif sh > 0.03:
        notes.append(f"阴影偏大 {sh:.1%}")
    if face.get("reliable"):
        fl = face.get("mean_luminance")
        if fl is not None:
            if fl < 75:
                issues.append(f"人脸过暗 {fl:.0f}")
            elif fl > 160:
                issues.append(f"人脸过亮 {fl:.0f}")
            else:
                notes.append(f"人脸 L={fl:.0f}")
    else:
        if mean is not None:
            if mean < 75:
                issues.append(f"全图偏暗 {mean:.0f}")
            elif mean > 170:
                issues.append(f"全图偏亮 {mean:.0f}")
            else:
                notes.append(f"全图 L={mean:.0f}")
    if contrast < 0.2:
        issues.append(f"对比度偏低 {contrast:.2f}")
    ms = motion.get("strength")
    if ms is not None and ms > 0.8:
        notes.append(f"疑似运动模糊 {ms:.2f}")
    return issues, notes


def main():
    merged = {}
    for f in sorted(glob.glob(REPORT_GLOB)):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for p in d.get("photos", []):
            merged[p["photo_id"]] = p

    best = {}
    # full_scan is authoritative (full-resolution decisions from scratch)
    for f in glob.glob(FULL_SCAN_GLOB):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for p in d.get("photos", []):
            best[p["photo_id"]] = p
    # manual fallback is authoritative for photos it covers
    for f in glob.glob(MANUAL_FALLBACK_GLOB):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for p in d.get("photos", []):
            best[p["photo_id"]] = p
    # refined is second-best
    for f in glob.glob(REFINED_GLOB):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for p in d.get("photos", []):
            best.setdefault(p["photo_id"], p)

    rows = []
    for pid in sorted(set(merged) | set(best)):
        p = merged.get(pid, {})
        r = best.get(pid)
        if not r and not p:
            continue
        fm = (r or p).get("final_measurement") or {}
        params = (r or p).get("params")
        after_path = (r or p).get("after_path") or p.get("after_path")
        issues, notes = evaluate(fm)
        g = fm.get("global") or {}
        rows.append({
            "photo_id": pid,
            "state": "ACCEPTED" if not issues else "MANUAL_REVIEW",
            "params": params,
            "after_path": after_path,
            "before_path": str(Path("exports/auto/full_scan") / f"{pid}_before.jpg")
                if (Path("exports/auto/full_scan") / f"{pid}_before.jpg").exists() else None,
            "mean_luminance": g.get("mean_luminance"),
            "highlight_clip_ratio": g.get("highlight_clip_ratio"),
            "shadow_clip_ratio": g.get("shadow_clip_ratio"),
            "contrast": g.get("contrast"),
            "qualified": not issues,
            "issues": issues,
            "notes": notes,
            "refined": pid in best,
        })

    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Pixo 真实照片自动修图结果", ""]
    lines.append(f"- 处理照片: {len(rows)}")
    lines.append(f"- 合格: {sum(r['qualified'] for r in rows)}")
    lines.append(f"- 待人工/不可自动修复: {sum(not r['qualified'] for r in rows)}")
    lines.append("")
    for r in rows:
        mark = "✅" if r["qualified"] else "⚠️"
        lines.append(f"## {mark} {r['photo_id']}")
        lines.append(f"- 输出: `{r['after_path']}`")
        if r.get("before_path"):
            lines.append(f"- 处理前预览: `{r['before_path']}`")
        lines.append(f"- 参数: `{r['params']}`")
        lines.append(f"- L={r['mean_luminance']:.0f} 高光={r['highlight_clip_ratio']:.2%} "
                     f"阴影={r['shadow_clip_ratio']:.2%} 对比={r['contrast']:.2f}")
        if r["issues"]:
            lines.append(f"- 问题: {', '.join(r['issues'])}")
        if r["notes"]:
            lines.append(f"- 备注: {', '.join(r['notes'])}")
        lines.append("")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT_JSON}")
    print(f"wrote {OUT_MD}")


if __name__ == "__main__":
    main()
