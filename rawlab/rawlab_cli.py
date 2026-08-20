#!/usr/bin/env python3
"""rawlab CLI —— 智能体调度入口 (阶段5).

封装渲染/曝光/LUT/视觉报告为命令行工具, 供智能体 (DSH/未来 agent) 调度:
    python rawlab_cli.py render   <raw> [--ev] [--style] [--out]
    python rawlab_cli.py analyze  <raw>            # 曝光分析
    python rawlab_cli.py fix      <raw> [--no-detect] # 曝光修正闭环 (默认 YOLOE 主体检测, 输出最终 EV + 图)
    python rawlab_cli.py report   <raw>            # 视觉语义报告 JSON
    python rawlab_cli.py batch    <dir> [--n] [--no-detect]  # 批量处理 (渲染+曝光+LUT+报告)
    python rawlab_cli.py retouch  <raw> [--edit] [--edits] [--scene] [--out] [--no-detect]  # 修图会话首轮
    python rawlab_cli.py pipeline <raw> [--preset <name|path>] [--config <json>] [--scene <id|auto>] [--out] [--half]
                                  # 插件化管线: preset/config 携带 "dcp" 字段时
                                  # load_dcp 绑定该 DCP profile (缺字段回退默认, 兼容旧 preset)

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
from rawlab.engine.core import StageContext
from rawlab.engine.analyze import run_analysis
from rawlab.engine.retouch import RetouchAgent
from rawlab.engine.intents import parse_feedback
import cv2

DCP = os.environ.get("RAWLAB_DCP",
                     r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp")
OUT_ROOT = Path(__file__).resolve().parent / "out"


def _load_prof():
    return load_dcp(DCP)


def _resolve_dcp_path(dcp: str) -> Path:
    """preset['dcp'] 相对路径解析: 当前工作目录优先, 其次仓库根 (rawlab 包上级)。

    fit_camera_profile 产出的 preset 用仓库根相对路径 (如
    "rawlab\\out\\profile_fit\\xxx.dcp"), 从任意工作目录调用都需能解析。
    """
    p = Path(dcp)
    if p.is_absolute():
        return p
    for base in (Path.cwd(), Path(__file__).resolve().parent.parent):
        cand = base / p
        if cand.exists():
            return cand
    return Path.cwd() / p


def _load_prof_from_cfg(cfg: dict):
    """preset/config 携带 'dcp' 字段 → load_dcp 绑定该 DCP profile (T6, F-05)。

    - 缺 'dcp' 字段 (旧 preset): 回退默认 profile (_load_prof), 兼容不改;
    - dcp 字段指向的文件不存在 / 解析失败: 返回明确错误 (调用方输出
      {"ok": False, "error": ...} 并终止, 报错信息含 resolved 路径)。

    返回 (prof, dcp_path, error); dcp_path 为实际解析到的 DCP 绝对路径
    (无 dcp 字段时为 None), error 非空时 prof 为 None。
    """
    dcp = cfg.get("dcp")
    if not dcp:
        return _load_prof(), None, None
    p = _resolve_dcp_path(str(dcp))
    if not p.is_file():
        return None, str(p), f"preset 的 dcp 字段指向的文件不存在: {p}"
    try:
        prof = load_dcp(p)
    except Exception as e:
        return None, str(p), f"preset 的 dcp 字段解析失败 ({p}): {e}"
    return prof, str(p), None


def _resolve_out(out_path, default_name):
    """输出路径统一绝对化 (防止 vision_bridge chdir 影响)。"""
    out = Path(out_path) if out_path else (OUT_ROOT / "cli" / default_name)
    if not out.is_absolute():
        out = OUT_ROOT / "cli" / out.name
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def _detect_boxes(no_detect: bool, raw_path, prof, probe_rgb8):
    """主体/人脸框检测 (fix/batch 默认开启; --no-detect 或异常 → 空框回退全图)。

    检测输入 = 半尺寸渲染 probe (测量=渲染: 与最终画面同链路)。
    接线 engine.analyze.run_analysis (YOLOE 复用 guanlan, 失败静默回退)。
    """
    if no_detect:
        return [], []
    ctx = StageContext(raw_path, raw=None, prof=prof)
    return run_analysis(ctx, rgb8=probe_rgb8, detect=True, classify=False)


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
    if not args.no_detect:
        try:
            img0 = render_with_lut(args.raw, prof, lut, half_size=True)
            subj, faces = _detect_boxes(False, args.raw, prof, img0)
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


MANIFEST_FILE = Path(__file__).resolve().parent / "profiles" / "manifest.json"


def _norm_abs(p: Path) -> str:
    """跨盘/大小写不敏感的路径规范化 (Windows 下 normcase)。"""
    return os.path.normcase(str(p.resolve())) if os.name == "nt" else str(p.resolve())


def validate_preset_manifest(preset_path, cfg: dict) -> str | None:
    """manifest 一致性校验 (问题清单 C): 禁止 preset/dcp 与 manifest 交叉混用。

    规则 (no_profile_mixing):
      - preset 是 manifest 中登记的产品 preset → cfg['dcp'] 必须解析到该
        target 登记的 dcp, 否则返回错误;
      - cfg['dcp'] 指向 manifest 中登记的 dcp → 所用 preset 必须是该 target
        登记的 preset, 否则返回错误;
      - 两者都不是 manifest 实体 (临时/自定义 preset+dcp) → 不校验, 返回 None。

    返回: 错误信息 (违反时) 或 None (放行)。
    """
    if not MANIFEST_FILE.is_file():
        return None
    try:
        manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None
    targets = manifest.get("targets")
    if not isinstance(targets, dict):
        return None
    repo_root = MANIFEST_FILE.parent.parent.parent

    used_preset_key = None
    preset_norm = None
    if preset_path is not None:
        preset_norm = _norm_abs(Path(preset_path))

    dcp_norm = None
    dcp = cfg.get("dcp") if isinstance(cfg, dict) else None
    if dcp:
        dcp_norm = _norm_abs(_resolve_dcp_path(str(dcp)))

    for key, t in targets.items():
        if not isinstance(t, dict):
            continue
        m_preset, m_dcp = t.get("preset"), t.get("dcp")
        if not m_preset or not m_dcp:
            continue
        m_preset_norm = _norm_abs(repo_root / str(m_preset))
        m_dcp_norm = _norm_abs(repo_root / str(m_dcp))
        if preset_norm is not None and preset_norm == m_preset_norm:
            used_preset_key = key
            if dcp_norm is None or dcp_norm != m_dcp_norm:
                return (f"manifest 校验失败: preset {Path(preset_path)} 登记为 "
                        f"'{key}', 但 dcp 指向 {dcp!r}; 应使用 {m_dcp}")
        if dcp_norm is not None and dcp_norm == m_dcp_norm:
            if preset_norm is not None and preset_norm != m_preset_norm:
                return (f"manifest 校验失败: dcp {dcp} 登记为 '{key}', "
                        f"但 preset {Path(preset_path)} 未匹配; 应使用 {m_preset}")
    if used_preset_key is not None:
        # 覆盖 policy 显式声明时也执行 (no_profile_mixing 恒真, 先按内置 policy)
        policy = manifest.get("policy") or {}
        if policy.get("no_profile_mixing", True):
            pass  # 上面的硬匹配已是最严约束; 保留分支便于策略演进
    return None


def cmd_pipeline(args):
    """新引擎插件化管线: 全链 + JSON/preset 配置 + 逐级 probe 落盘。

    --preset <name|path>: presets/<name>.json, 或直接 JSON 文件路径 (临时 preset);
      加载后若含 "dcp" 字段 → load_dcp 绑定该 DCP profile 构建管线 (T6);
      缺字段 (旧 preset) 回退默认 profile, 兼容。
    --config <json>: 直接配置文件 (同样支持 "dcp" 字段绑定)。
    --scene <id|auto>: 场景风格 (presets/scenes.json)。auto = 半尺寸 probe 上
    主体检测 + 场景分类 (engine.analyze → engine.scenes) 后自动选预设;
    显式 id = portrait/landscape/night/street/food/mono。缺省 None = 基座。
    """
    if getattr(args, "preview", False):
        # 低分辨率快速预览: 轻量链 (preview_fast.json), 强制 half_size, 秒级出图。
        from rawlab.engine import pipeline_from_config
        preset_path = Path(__file__).resolve().parent / "presets" / "preview_fast.json"
        cfg = json.loads(preset_path.read_text(encoding="utf-8"))
        prof, dcp_path, prof_err = _load_prof_from_cfg(cfg)
        if prof_err:
            print(json.dumps({"ok": False, "error": prof_err, "dcp": dcp_path},
                             ensure_ascii=False))
            return
        pipe = pipeline_from_config(cfg, prof=prof)
        rgb8 = pipe.run_file(args.raw, half_size=True)
        out = _resolve_out(args.out, f"{Path(args.raw).stem}_preview.jpg")
        cv2.imwrite(str(out), cv2.cvtColor(rgb8, cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, int(pipe.output.get("quality", 95))])
        print(json.dumps({"ok": True, "mode": "preview", "output": str(out.resolve()),
                          "half_size": True, "stages": cfg["stages"],
                          "dcp": dcp_path}, ensure_ascii=False))
        return
    prof = _load_prof()
    cfg = {}
    preset_loaded: Path | None = None
    if args.preset:
        preset_arg = Path(args.preset)
        p = Path(__file__).resolve().parent / "presets" / f"{args.preset}.json"
        if not p.exists() and preset_arg.is_file():
            # --preset 亦接受直接 JSON 文件路径 (临时 preset / 自定义位置)
            p = preset_arg
        if not p.exists():
            print(json.dumps({"ok": False, "error": f"preset 不存在: {args.preset}"}))
            return
        cfg = json.loads(p.read_text(encoding="utf-8"))
        preset_loaded = p
    if args.config:
        config_path = Path(args.config)
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
        preset_loaded = config_path

    scene_id = None
    if args.scene:
        if args.scene == "auto":
            try:
                from rawlab.engine.analyze import run_analysis
                from rawlab.engine.core import StageContext
                from rawlab.render import render as legacy_render
                probe = legacy_render(args.raw, prof, half_size=True)
                ctx = StageContext(args.raw, prof=prof)
                run_analysis(ctx, rgb8=probe, detect=True, classify=True)
                scene_id = (ctx.state.get("scene") or {}).get("id")
            except Exception as e:
                print(f"[pipeline] 场景自动识别失败, 回退基座: {e}")
                scene_id = None
        else:
            scene_id = args.scene
    if scene_id:
        from rawlab.engine.scene_apply import apply_scene_preset
        scene_params, scene_lut = apply_scene_preset(scene_id)
        cfg.setdefault("params", {})
        for st, params in scene_params.items():
            cfg["params"].setdefault(st, {}).update(params)
        if scene_lut:
            cfg["params"].setdefault("stylize", {})["lut_path"] = scene_lut

    from rawlab.engine import pipeline_from_config
    # preset/config 携带 "dcp" 字段 → 绑定该 DCP profile (缺字段回退默认, 兼容旧 preset)
    prof, dcp_path, prof_err = _load_prof_from_cfg(cfg)
    if prof_err:
        print(json.dumps({"ok": False, "error": prof_err, "dcp": dcp_path},
                         ensure_ascii=False))
        return
    # manifest 一致性校验 (问题清单 C): preset 与 dcp 不得跨 target 混用
    manifest_err = validate_preset_manifest(preset_loaded, cfg)
    if manifest_err:
        print(json.dumps({"ok": False, "error": manifest_err, "dcp": dcp_path},
                         ensure_ascii=False))
        return
    pipe = pipeline_from_config(cfg, prof=prof)
    probe = OUT_ROOT / "probe" / Path(args.raw).stem if args.probe else None
    rgb8 = pipe.run_file(args.raw, half_size=args.half, probe_dir=probe)
    out = _resolve_out(args.out, f"{Path(args.raw).stem}_pipeline.jpg")
    cv2.imwrite(str(out), cv2.cvtColor(rgb8, cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, int(pipe.output.get("quality", 95))])
    print(json.dumps({"ok": True, "output": str(out.resolve()),
                      "scene": scene_id,
                      "dcp": dcp_path,
                      "profile": getattr(prof, "name", None),
                      "stages": pipe.describe(),
                      "probe": str(probe) if probe else None}, ensure_ascii=False))



def cmd_batch_pipeline(args):
    """Phase 4 T4.2: 批量渲染 (新 Pipeline)。

    --dir 扫描原始文件, --config 参数 JSON (可含 dcp 字段)/--dcp 绑定 profile,
    --out 输出目录 (默认 <dir>/rawlux_out), --half-size 降采样, --limit 限制数量,
    --no-resume 关闭断点续跑。逐张走 pipeline_from_config->run_file。
    """
    from rawlab.tools.batch_render import discover_raw_files, render_batch
    raw_files = discover_raw_files(args.dir, limit=args.limit)
    cfg = {}
    prof = None
    dcp_path = None
    if args.config:
        cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
        prof, dcp_path, prof_err = _load_prof_from_cfg(cfg)
        if prof_err:
            print(json.dumps({"ok": False, "error": prof_err, "dcp": dcp_path},
                             ensure_ascii=False))
            return
    elif args.dcp:
        prof = load_dcp(args.dcp)
        dcp_path = args.dcp
    else:
        prof = _load_prof()
    out_dir = Path(args.out) if args.out else Path(args.dir) / "rawlux_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = render_batch(raw_files, out_dir, cfg, prof=prof,
                           half_size=args.half_size, resume=not args.no_resume)
    cnt = {k: sum(1 for v in results.values() if v == k)
           for k in ("rendered", "skipped", "failed")}
    print(json.dumps({"ok": True, "out": str(out_dir.resolve()),
                      "found": len(raw_files), **cnt,
                      "failed_list": [k for k, v in results.items() if v == "failed"],
                      "dcp": dcp_path}, ensure_ascii=False))

def cmd_retouch(args):
    """修图会话首轮 (RetouchAgent): 分析 → 场景 → 意见 → 渲染 → 报告 → 落盘 + 会话 JSON。

    --edit / --edits 作为初轮意见 (parse_feedback 解析, 分号/逗号分隔多意见);
    --scene 默认 auto (半尺寸 probe 上主体检测 + 场景分类后自动选预设);
    --no-detect 关闭主体检测。输出结构化 JSON 供智能体消费。
    """
    try:
        prof = _load_prof()
        agent = RetouchAgent(prof, out_dir=args.out, detect=not args.no_detect)
        intents = []
        if args.edit:
            intents.extend(parse_feedback(args.edit))
        if args.edits:
            intents.extend(parse_feedback(args.edits))
        result = agent.retouch(args.raw, intents=intents, scene=args.scene)
        session_path = agent.save_session(
            agent._out_dir / f"{agent._stem}_session.json")
        rep = result.report or {}
        print(json.dumps({
            "ok": True,
            "scene": result.scene,
            "subject_boxes": result.subject_boxes,
            "ev": result.ev,
            "round_idx": result.round_idx,
            "output": str(result.image_path),
            "report": {
                "brightness": rep.get("tone", {}).get("brightness"),
                "saturation": rep.get("color", {}).get("saturation"),
            },
            "session": str(session_path),
        }, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))


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
    """批量: 每张 检测(默认) → 曝光修正 → 渲染 → 视觉报告, 输出汇总 JSON。"""
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
            # 检测输入 = 半尺寸渲染 probe; 曝光修正基于同一渲染测量 (测量=渲染)
            img0 = render(f, prof, half_size=True)
            subj, faces = _detect_boxes(args.no_detect, f, prof, img0)
            st = analyze_exposure(img0, subj, faces)
            ev = compute_exposure_ev(st)
            img = render(f, prof, exposure_ev=ev, half_size=True)
            bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            rep = build_vision_report(bgr)
            results.append({"file": name, "ev": round(ev, 3),
                            "subject_luma": round(st.subject_luma, 1),
                            "subject_used": st.subject_used,
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


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器 (独立函数, 便于测试解析规则)。"""
    ap = argparse.ArgumentParser(description="rawlab 智能修图 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("render"); p.add_argument("raw")
    p.add_argument("--ev", type=float, default=0.0)
    p.add_argument("--style"); p.add_argument("--out"); p.add_argument("--half", action="store_true")
    p = sub.add_parser("analyze"); p.add_argument("raw")
    p = sub.add_parser("fix"); p.add_argument("raw")
    p.add_argument("--style"); p.add_argument("--out"); p.add_argument("--half", action="store_true")
    p.add_argument("--no-detect", action="store_true",
                   help="关闭 YOLOE 主体检测 (曝光回退全图中位)")
    p = sub.add_parser("pipeline"); p.add_argument("raw")
    p.add_argument("--config")
    p.add_argument("--preset", default=None,
                   help="预设名 (presets/<name>.json) 或直接 JSON 文件路径; 含 'dcp' 字段时绑定该 DCP")
    p.add_argument("--out")
    p.add_argument("--half", action="store_true"); p.add_argument("--probe", action="store_true")
    p.add_argument("--scene", default=None,
                   help="场景风格: auto | portrait | landscape | night | street | food | mono")
    p.add_argument("--preview", action="store_true",
                   help="低分辨率快速预览: 轻量链 (preview_fast.json) + 强制 half_size")
    p = sub.add_parser("report"); p.add_argument("raw")
    p = sub.add_parser("batch"); p.add_argument("dir"); p.add_argument("--n", type=int, default=10)
    p.add_argument("--out")
    p.add_argument("--no-detect", action="store_true",
                   help="关闭 YOLOE 主体检测 (曝光回退全图中位)")
    p = sub.add_parser("batch-pipeline"); p.add_argument("dir")
    p.add_argument("--config", default=None, help="参数 JSON 文件路径 (可含 dcp 字段)")
    p.add_argument("--dcp", default=None, help="显式 DCP 路径 (覆盖默认 profile)")
    p.add_argument("--out", default=None, help="输出目录 (默认 <dir>/rawlux_out)")
    p.add_argument("--half-size", action="store_true", help="低分辨率快速预览")
    p.add_argument("--limit", type=int, default=None, help="只处理前 N 个文件")
    p.add_argument("--no-resume", action="store_true", help="关闭断点续跑")
    p = sub.add_parser("retouch"); p.add_argument("raw")
    p.add_argument("--edit", default=None, help="单条修图意见 (初轮 intents)")
    p.add_argument("--edits", default=None,
                   help="多条修图意见 (分号/逗号分隔)")
    p.add_argument("--scene", default="auto",
                   help="场景: auto | portrait | landscape | night | street | food | mono")
    p.add_argument("--out", default=None)
    p.add_argument("--no-detect", action="store_true",
                   help="关闭主体检测")
    return ap


def main():
    args = build_parser().parse_args()
    {"render": cmd_render, "analyze": cmd_analyze, "fix": cmd_fix,
     "report": cmd_report, "batch": cmd_batch, "pipeline": cmd_pipeline,
     "batch-pipeline": cmd_batch_pipeline,
     "retouch": cmd_retouch}[args.cmd](args)


if __name__ == "__main__":
    main()
