"""逐阶段渲染统计转储（独立诊断工具，t24）。

对指定 RAW 手动驱动管线逐 Stage 执行并输出量化 JSON：
  decode      探针亮度中位/分位数(p50/p90/p98/p99.7)+线性饱和比；
  exposure    决策(ev/ev_mode)与 clip_p 口径前后值(p98、饱和比 before/after)；
  whitebalance 线性域饱和裁切比；
  tone        gamma 域 clip_hi/clip_lo（口径同 scripts/ab_vs_camera_thumb.py）；
  另附 RAW 内嵌缩略图直方图摘要与全链渲染 A/B 对照（ΔE/da/db/裁切）。

实现：参照 scripts/fit_target_offset.py 的手动 StageContext 驱动法，
不改引擎源码。用法:
  python scripts/dump_render_stats.py RAW [--json out.json]
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]
QUANTILES = (50.0, 90.0, 98.0, 99.7)


def _luma(img):
    """Rec.709 亮度平面。"""
    return (0.2126 * img[..., 0] + 0.7152 * img[..., 1] + 0.0722 * img[..., 2])


def _r(v, nd=6):
    return round(float(v), nd)


def lin_stats(img):
    """线性域探针统计：亮度分位数 + log2 中位 + 任一通道饱和像素占比。"""
    y = _luma(img)
    qs = {f"p{q:g}": _r(np.percentile(y, q)) for q in QUANTILES}
    return {
        "domain": "linear",
        "luma_quantiles": qs,
        "med_log2": _r(np.median(np.log2(np.maximum(y, 1e-6))), 4),
        "clip_sat_pct": _r((img >= 1.0).any(axis=2).mean() * 100.0, 4),
    }


def gamma_clip_stats(img):
    """gamma 域裁切统计，口径同 ab_vs_camera_thumb (u8: >=250 / <=5)。"""
    u8 = (np.clip(img, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    return {
        "domain": "gamma_rgb",
        "clip_hi_pct": _r((u8.max(axis=2) >= 250).mean() * 100.0, 4),
        "clip_lo_pct": _r((u8.min(axis=2) <= 5).mean() * 100.0, 4),
    }


def cam_thumb(p):
    """相机内嵌缩略图 (RGB u8, 已按 EXIF 方向摆正)，同 ab_vs_camera_thumb。"""
    import rawpy
    with rawpy.imread(str(p)) as raw:
        t = raw.extract_thumb()
        if t.format == rawpy.ThumbFormat.JPEG:
            bgr = cv2.imdecode(np.frombuffer(t.data, np.uint8), cv2.IMREAD_COLOR)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        else:
            rgb = np.asarray(t.data)[..., :3].copy()
    try:
        from pixo.meta import extract as ex
        o = int(ex(p)["capture"].get("orientation") or 1)
    except Exception:
        o = 1
    rot = {3: cv2.ROTATE_180, 6: cv2.ROTATE_90_CLOCKWISE,
           8: cv2.ROTATE_90_COUNTERCLOCKWISE}
    if o in rot:
        rgb = cv2.rotate(rgb, rot[o])
    return rgb


def thumb_summary(rgb):
    """缩略图摘要：L 通道 16 桶直方图(%) + 同口径裁切统计。"""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    hist = np.histogram(lab[..., 0], bins=16, range=(0, 256))[0].astype(np.float64)
    hist = np.round(hist / max(hist.sum(), 1) * 10000.0) / 100.0
    return {
        "size": [int(rgb.shape[1]), int(rgb.shape[0])],
        "L_histogram_16bin_pct": [_r(v, 2) for v in hist],
        "clip_hi_pct": _r((rgb.max(axis=2) >= 250).mean() * 100.0, 4),
        "clip_lo_pct": _r((rgb.min(axis=2) <= 5).mean() * 100.0, 4),
    }


def ab_compare(ours_u8, ref_u8):
    """全链渲染 vs 相机缩略图：Lab ΔE 与 dL/da/db 均值 (同口径)。"""
    h = min(ours_u8.shape[0], ref_u8.shape[0])
    w = min(ours_u8.shape[1], ref_u8.shape[1])
    a = cv2.resize(ours_u8, (w, h), interpolation=cv2.INTER_AREA)
    b = cv2.resize(ref_u8, (w, h), interpolation=cv2.INTER_AREA)
    la = cv2.cvtColor(a, cv2.COLOR_RGB2LAB).astype(np.float32)
    lb = cv2.cvtColor(b, cv2.COLOR_RGB2LAB).astype(np.float32)
    d = np.linalg.norm(la - lb, axis=2)
    return {
        "dE_mean": _r(d.mean(), 3),
        "dE_p50": _r(float(np.median(d)), 3),
        "dL_mean": _r((la[..., 0] - lb[..., 0]).mean(), 3),
        "da_mean": _r((la[..., 1] - lb[..., 1]).mean(), 3),
        "db_mean": _r((la[..., 2] - lb[..., 2]).mean(), 3),
        "clip_hi_pct_ours": _r((a.max(axis=2) >= 250).mean() * 100.0, 4),
        "clip_hi_pct_camera": _r((b.max(axis=2) >= 250).mean() * 100.0, 4),
        "clip_lo_pct_ours": _r((a.min(axis=2) <= 5).mean() * 100.0, 4),
        "clip_lo_pct_camera": _r((b.min(axis=2) <= 5).mean() * 100.0, 4),
    }


def dump_for(raw_path, ab_compatible=False):
    """手动驱动 Stage 链，收集逐阶段统计 dict。

    ab_compatible=True 时在 tone 段附全链最终渲染的同口径裁切
    （与 scripts/ab_vs_camera_thumb.py 完全可比）。
    """
    from pixo.render.api import Renderer
    from pixo.render.pipeline.context import StageContext, DOMAIN_LINEAR_CAM
    from pixo.render import modules as _stages  # noqa: F401 触发 Stage 注册
    from pixo.render.pipeline.graph import Pipeline
    from pixo.render.core.io import decode_cfa_half, camera_neutral_wb_cached
    import rawpy

    dcp = sorted(ROOT.joinpath("resources", "dcp").glob("*.dcp"))[0]
    renderer = Renderer(dcp)

    out = {"file": Path(raw_path).name}
    # tone(order=30) 及其之前的链前缀：exposure10 → whitebalance20 →
    # compose22 → huesat25 → tone30（wants() 不满足的自动跳过）。
    pipe = Pipeline(stages=["exposure", "whitebalance", "compose", "huesat", "tone"])
    with rawpy.imread(str(raw_path)) as raw:
        img = decode_cfa_half(raw, raw_path=raw_path)
        ctx = StageContext(raw_path, raw=raw, prof=renderer.profile, config={})
        ctx.set_image(img, DOMAIN_LINEAR_CAM)
        ctx.state["camera_wb"] = camera_neutral_wb_cached(raw, str(raw_path))

        out["decode"] = lin_stats(ctx.image)
        pre_p98 = float(np.percentile(_luma(ctx.image), 98.0))
        pre_clip = float((ctx.image >= 1.0).any(axis=2).mean() * 100.0)

        for stage in pipe.stages:
            if not stage.wants(ctx):
                continue
            stage.run(ctx)
            if stage.name == "exposure":
                stats = lin_stats(ctx.image)
                stats["ev"] = _r(ctx.state.get("ev"), 4)
                stats["ev_mode"] = str(ctx.state.get("ev_mode") or "manual_or_off")
                # clip_p 口径前后值：p98 亮度与饱和比 (增益前 vs 增益后)
                stats["p98_before"] = _r(pre_p98)
                stats["p98_after"] = stats["luma_quantiles"]["p98"]
                stats["clip_sat_pct_before"] = _r(pre_clip, 4)
                out["exposure"] = stats
            elif stage.name == "whitebalance":
                wbstats = lin_stats(ctx.image)
                wbstats["note"] = (
                    "clip_sat_pct=线性域任一通道>=1.0 的饱和像素占比"
                    "(WB/曝光增益域)，与 gamma u8 >=250 的 clip_hi 非一口径"
                )
                out["whitebalance"] = wbstats
            elif stage.name == "tone":
                tstats = gamma_clip_stats(ctx.image)
                tstats["note"] = (
                    "ToneStage 刚结束的原生半分辨率快照，不含 colorcal/"
                    "skin/refine 等后续级(colorcal 会大幅回拉高光)；"
                    "与全链 A/B 的 clip_hi 相差可达数倍，勿直接对比"
                )
                out["tone"] = tstats

    # 全链渲染 vs 相机缩略图 A/B（引擎默认参数，含标定 brightness）
    ours = renderer.render_preview_full(raw_path, long_edge=1024)
    ref = cam_thumb(raw_path)
    out["thumb_summary"] = thumb_summary(ref)
    out["ab_vs_camera_thumb"] = ab_compare(ours, ref)
    if ab_compatible:
        out["tone"]["clip_hi_pct_fullchain"] = _r(
            (ours.max(axis=2) >= 250).mean() * 100.0, 4)
        out["tone"]["clip_lo_pct_fullchain"] = _r(
            (ours.min(axis=2) <= 5).mean() * 100.0, 4)
        out["tone"]["fullchain_note"] = (
            "全链最终渲染(long_edge=1024, 含 colorcal/skin/refine)同口径，"
            "数值应与 ab_vs_camera_thumb.clip_*_pct_ours 一致")
    return out


def main():
    ap = argparse.ArgumentParser(description="逐阶段渲染统计转储")
    ap.add_argument("raw", nargs="+", help="RAW 文件路径")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="输出 JSON 文件路径（单 RAW 时使用）")
    ap.add_argument("--ab-compatible", action="store_true",
                    help="tone 段附全链最终渲染的同口径 clip 统计")
    args = ap.parse_args()

    reports = [dump_for(p, args.ab_compatible) for p in args.raw]
    payload = reports[0] if len(reports) == 1 else reports
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.json_out:
        Path(args.json_out).write_text(text + chr(10), encoding='utf-8')
        print("wrote", args.json_out)
    for rep in reports:
        dec = rep["decode"]["luma_quantiles"]
        exp = rep.get("exposure", {})
        wb = rep.get("whitebalance", {})
        tn = rep.get("tone", {})
        ab = rep.get("ab_vs_camera_thumb", {})
        print(f"{rep['file']}: decode_med_log2={rep['decode']['med_log2']:+.2f} "
              f"p98={dec['p98']:.4f} p99.7={dec['p99.7']:.4f}")
        print(f"  exposure: ev={exp.get('ev')} mode={exp.get('ev_mode')} "
              f"p98 {exp.get('p98_before')}->{exp.get('p98_after')} "
              f"sat {exp.get('clip_sat_pct_before')}%->{exp.get('clip_sat_pct')}%")
        print(f"  wb(linear): sat={wb.get('clip_sat_pct')}% | "
              f"tone(gamma): hi={tn.get('clip_hi_pct')}% lo={tn.get('clip_lo_pct')}%")
        print(f"  thumb: hi={rep['thumb_summary']['clip_hi_pct']}% "
              f"lo={rep['thumb_summary']['clip_lo_pct']}% | "
              f"A/B: dE={ab.get('dE_mean')} da={ab.get('da_mean')} db={ab.get('db_mean')} "
              f"hi 我们{ab.get('clip_hi_pct_ours')}%/相机{ab.get('clip_hi_pct_camera')}%")


if __name__ == "__main__":
    main()
