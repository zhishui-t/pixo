#!/usr/bin/env python3
"""rawlab CLI —— 智能体调度入口 (阶段5).

封装渲染/曝光/LUT/视觉报告为命令行工具, 供智能体 (DSH/未来 agent) 调度:
    python rawlab_cli.py render   <raw> [--ev] [--style] [--out]
    python rawlab_cli.py analyze  <raw>            # 曝光分析
    python rawlab_cli.py fix      <raw>            # 曝光修正闭环 (输出最终 EV + 图)
    python rawlab_cli.py report   <raw>            # 视觉语义报告 JSON
    python rawlab_cli.py batch    <dir> [--n]      # 批量处理 (渲染+曝光+LUT+报告)

输出: 结构化 JSON (供智能体消费) + 产物文件。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from rawlab.dcp import load_dcp
from rawlab.render import render_to_jpeg, render, render_with_lut
from rawlab.exposure import analyze_exposure, compute_exposure_ev
from rawlab.lut import load_lut
from rawlab.vision_report import build_vision_report
from rawlab.vision_bridge import get_detector
import cv2

DCP = os.environ.get("RAWLAB_DCP",
                     r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp")
OUT_ROOT = Path(__file__).resolve().parent / "out"


def _load_prof():
    return load_dcp(DCP)


def _resolve_out(out_path, default_name):
    """输出路径统一绝对化 (防止 vision_bridge chdir 影响)。"""
    out = Path(out_path) if out_path else (OUT_ROOT / "cli" / default_name)
    if not out.is_absolute():
        out = OUT_ROOT / "cli" / out.name
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def cmd_render(args):
    prof = _load_prof()
    out = _resolve_out(args.out, f"{Path(args.raw).stem}.jpg")
    lut = load_lut(args.style) if args.style else None
    dt, path = render_to_jpeg(args.raw, prof, out, exposure_ev=args.ev,
                              half_size=args.half)
    result = {"ok": True, "ev": args.ev, "style": args.style,
              "time_s": round(dt, 2), "output": str(path.resolve())}
    if lut:
        img = render(args.raw, prof, exposure_ev=args.ev, half_size=args.half)
        out_lut = lut.apply(img)
        bgr = cv2.cvtColor(out_lut, cv2.COLOR_RGB2BGR)
        p2 = str(out).replace(".jpg", f"_{args.style}.jpg")
        cv2.imwrite(p2, bgr)
        result["styled"] = str(Path(p2).resolve())
    print(json.dumps(result, ensure_ascii=False))


def cmd_analyze(args):
    prof = _load_prof()
    img = render(args.raw, prof, half_size=True)
    st = analyze_exposure(img)
    print(json.dumps({
        "ok": True, "median": st.luma_median, "subject": st.subject_luma,
        "highlight_pct": st.highlight_pct, "shadow_pct": st.shadow_pct,
    }, ensure_ascii=False))


def cmd_fix(args):
    """曝光修正闭环 (可选挂 LUT): 基于挂 LUT 渲染测量, 返回最终 EV + 图。

    ⚠️ 测量=渲染: LUT 会改变亮度 (classic_neg +0.2EV 量级, astia -0.4EV),
    曝光闭环必须在套 LUT 后的画面上测量, 否则套 LUT 后曝光偏移/爆炸。
    """
    prof = _load_prof()
    lut = load_lut(args.style) if args.style else None
    subj, faces = [], []
    try:
        get_detector()
        img0 = render_with_lut(args.raw, prof, lut, half_size=True)
        from rawlab.vision_bridge import detect_subjects
        subj, faces = detect_subjects(cv2.cvtColor(img0, cv2.COLOR_RGB2BGR))
    except Exception:
        pass
    total_ev, history = 0.0, []
    for rnd in range(1, 4):
        rgb = render_with_lut(args.raw, prof, lut, exposure_ev=total_ev,
                              half_size=True)
        st = analyze_exposure(rgb, subj, faces)
        ev = compute_exposure_ev(st)
        history.append({"round": rnd, "ev": round(total_ev, 3),
                        "subject_luma": round(st.subject_luma, 1)})
        if abs(st.subject_luma - 115) < 8:
            break
        total_ev += ev
    suffix = f"_{args.style}" if args.style else ""
    out = _resolve_out(args.out, f"{Path(args.raw).stem}{suffix}_fixed.jpg")
    if args.style:
        # 挂 LUT 渲染输出
        rgb8 = render_with_lut(args.raw, prof, lut, exposure_ev=total_ev,
                               half_size=args.half)
        bgr = cv2.cvtColor(rgb8, cv2.COLOR_RGB2BGR)
        cv2.imwrite(str(out), bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
        dt = 0.0
        path = out
    else:
        dt, path = render_to_jpeg(args.raw, prof, out, exposure_ev=total_ev,
                                  half_size=args.half)
    print(json.dumps({"ok": True, "final_ev": round(total_ev, 3),
                      "style": args.style, "history": history,
                      "output": str(path.resolve()), "time_s": round(dt, 2)},
                     ensure_ascii=False))


def cmd_pipeline(args):
    """新引擎插件化管线: 六阶段全链 + JSON/preset 配置 + 逐级 probe 落盘。"""
    prof = _load_prof()
    cfg = {}
    if args.preset:
        p = Path(__file__).resolve().parent / "presets" / f"{args.preset}.json"
        if not p.exists():
            print(json.dumps({"ok": False, "error": f"preset 不存在: {args.preset}"}))
            return
        cfg = json.loads(p.read_text(encoding="utf-8"))
    if args.config:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    from rawlab.engine import pipeline_from_config
    pipe = pipeline_from_config(cfg, prof=prof)
    probe = OUT_ROOT / "probe" / Path(args.raw).stem if args.probe else None
    rgb8 = pipe.run_file(args.raw, half_size=args.half, probe_dir=probe)
    out = _resolve_out(args.out, f"{Path(args.raw).stem}_pipeline.jpg")
    cv2.imwrite(str(out), cv2.cvtColor(rgb8, cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, int(pipe.output.get("quality", 95))])
    print(json.dumps({"ok": True, "output": str(out.resolve()),
                      "stages": pipe.describe(),
                      "probe": str(probe) if probe else None}, ensure_ascii=False))


def cmd_report(args):
    prof = _load_prof()
    try:
        get_detector()
    except Exception:
        pass
    img = render(args.raw, prof, half_size=True)
    bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    rep = build_vision_report(bgr)
    rep["file"] = os.path.basename(args.raw)
    print(json.dumps(rep, ensure_ascii=False))


def cmd_batch(args):
    """批量: 每张 曝光修正 → 渲染 → 视觉报告, 输出汇总 JSON。"""
    prof = _load_prof()
    try:
        get_detector()
    except Exception:
        pass
    files = sorted(glob.glob(os.path.join(args.dir, "*.NEF")))[: args.n]
    t_start = time.time()
    results = []
    for f in files:
        name = os.path.basename(f)
        try:
            r = {}
            # 曝光修正
            img0 = render(f, prof, half_size=True)
            st = analyze_exposure(img0)
            ev = compute_exposure_ev(st)
            img = render(f, prof, exposure_ev=ev, half_size=True)
            bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            rep = build_vision_report(bgr)
            results.append({"file": name, "ev": round(ev, 3),
                            "subject_luma": round(st.subject_luma, 1),
                            "report": rep})
            print(f"  {name}: ev={ev:+.2f} L={st.subject_luma:.0f}")
        except Exception as e:
            results.append({"file": name, "error": str(e)})
    total = time.time() - t_start
    summary = {"n": len(results), "total_s": round(total, 1),
               "avg_s": round(total / max(len(results), 1), 2),
               "results": results}
    out = Path(args.out) if args.out else (OUT_ROOT / "cli" / "batch_report.json")
    if not out.is_absolute():
        out = OUT_ROOT / "cli" / out.name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps({"ok": True, "n": len(results),
                      "total_s": round(total, 1),
                      "report": str(out.resolve())}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="rawlab 智能修图 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("render"); p.add_argument("raw")
    p.add_argument("--ev", type=float, default=0.0)
    p.add_argument("--style"); p.add_argument("--out"); p.add_argument("--half", action="store_true")
    p = sub.add_parser("analyze"); p.add_argument("raw")
    p = sub.add_parser("fix"); p.add_argument("raw")
    p.add_argument("--style"); p.add_argument("--out"); p.add_argument("--half", action="store_true")
    p = sub.add_parser("pipeline"); p.add_argument("raw")
    p.add_argument("--config"); p.add_argument("--preset"); p.add_argument("--out")
    p.add_argument("--half", action="store_true"); p.add_argument("--probe", action="store_true")
    p = sub.add_parser("report"); p.add_argument("raw")
    p = sub.add_parser("batch"); p.add_argument("dir"); p.add_argument("--n", type=int, default=10)
    p.add_argument("--out")
    args = ap.parse_args()
    {"render": cmd_render, "analyze": cmd_analyze, "fix": cmd_fix,
     "report": cmd_report, "batch": cmd_batch, "pipeline": cmd_pipeline}[args.cmd](args)


if __name__ == "__main__":
    main()
