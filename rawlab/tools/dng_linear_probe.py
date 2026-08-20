"""dng_linear_probe —— 用同一 DNG + 外部 DCP 输出我们引擎的线性 sRGB TIFF。

对比对象: guanlan dng_engine --render --profile <dcp> --linear 输出。
"""
import argparse, json, sys, time
from pathlib import Path
import cv2, numpy as np, rawpy

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from rawlab.dcp import load_dcp
from rawlab.engine.core import StageContext, DOMAIN_LINEAR_CAM, STAGE_REGISTRY
from rawlab.engine import stages as _stages
from rawlab.engine.decode import decode_dng_stage3_like, decode_raw
from rawlab.tools.regress_anchors import crop_active_oriented


def render_linear(dng_path, dcp_path, ref_shape=None, half_size=True, hsm=True,
                  tone_table=None, dng_baseline_ev=None):
    prof = load_dcp(dcp_path)
    is_dng = str(dng_path).lower().endswith(".dng")
    if is_dng:
        # rawpy 侧复刻 DNG Stage2 线性化 + 6x6 CFA 平均, 不含 OpcodeList。
        img, raw = decode_dng_stage3_like(dng_path)
    else:
        img, raw = decode_raw(dng_path, half_size=half_size)
    # DNG SDK 先裁切/重采样 Stage3 到最终尺寸, 再做 CameraToProPhoto/LookTable。
    # rawpy 探针路径也采用同样顺序: 后面 6MP LookTable 会降到 1024x683,
    # 单张从 ~10s 降到 ~1.7s, 且与 SDK 流程顺序一致。
    if ref_shape is not None:
        if is_dng:
            from rawlab.tools.dng_stage3_replicate import dng_resample
            H, W = img.shape[:2]
            img = dng_resample(img, (1, 1, H, W - 2),
                               (ref_shape[1], ref_shape[0]))
        else:
            img = crop_active_oriented(img, raw)
            if img.shape[:2] != tuple(ref_shape[:2]):
                img = cv2.resize(img, (ref_shape[1], ref_shape[0]),
                                 interpolation=cv2.INTER_AREA)
    params = {
        # DNG SDK 的 BaselineExposure 补偿在 Stage3 之后的 ExposureRamp/ToneCurve
        # 中完成; 引擎 stage 在这里只能污染 Stage3 输入, 故探针路径置 off。
        'exposure': {'mode': 'off'},
        'whitebalance': {'mode': 'as_shot', 'warmth': 0.0, 'trim': [1.0, 1.0, 1.0]},
        'huesat': {'enabled': bool(hsm), 'strength': 1.0,
                   'warm_highlight_sat': 1.0, 'warm_sat_spot_scale': 1.0},
    }
    ctx = StageContext(dng_path, raw=raw, prof=prof, config={'stages': params})
    ctx.set_image(img, DOMAIN_LINEAR_CAM)
    for name in ['exposure', 'whitebalance', 'huesat']:
        st = STAGE_REGISTRY[name]()
        if name == 'huesat':
            ctx.state['use_dng_huesat_path'] = True
            if dng_baseline_ev is not None:
                ctx.state['dng_baseline_ev'] = float(dng_baseline_ev)
            if tone_table is not None:
                from rawlab.engine.dng_render import load_dng_tone_table
                ctx.state['dng_tone_table'] = load_dng_tone_table(tone_table)
                ctx.state['dng_apply_tone'] = True
        if st.wants(ctx):
            st.run(ctx)
    lin = np.clip(ctx.image, 0.0, 1.0).astype(np.float32)
    raw.close()
    return lin, ctx.state


def render_from_stage3(stage3_raw, dng_path, dcp_path, engine_log,
                       hsm=True, tone_table=None):
    """用 DNG SDK 自己的 Stage3 采样作为输入, 走我们引擎的 DNG ProPhoto 路径。

    输入对齐后, 剩余差异只来自我们的 color/huesat/tone 复刻, 不再含
    rawpy demosaic / INTER_AREA resize 的输入差异。
    """
    from rawlab.tools.dng_stage3_replicate import (
        dng_resample, exposure_ramp, load_tone_table, parse_color_math, rgb_tone)
    from rawlab.engine.color import (cam_wb_to_prophoto,
                                     dng_linear_prophoto_to_srgb)
    from rawlab.engine.decode import camera_neutral_wb
    from rawlab.engine.huesat import (apply_hue_sat_map_prophoto,
                                      apply_look_table_prophoto)
    info = parse_color_math(Path(engine_log).read_text(encoding='utf-8', errors='replace'))
    hdr = np.fromfile(stage3_raw, dtype='<u4', count=2)
    w, h = int(hdr[0]), int(hdr[1])
    stage = np.fromfile(stage3_raw, dtype='<f4', offset=8,
                        count=w * h * 3).reshape(h, w, 3)
    src = dng_resample(stage, info['src_bounds'], info['dst_size'])
    raw = rawpy.imread(dng_path)
    wb = camera_neutral_wb(raw)
    raw.close()
    prof = load_dcp(dcp_path)
    pp = cam_wb_to_prophoto(src, prof, wb)
    if hsm:
        pp = apply_hue_sat_map_prophoto(pp, prof, 1.0)
    baseline_ev = info['total_baseline'] - np.log2(info['stage3_gain'])
    pp = exposure_ramp(pp, baseline_ev)
    if hsm:
        pp = apply_look_table_prophoto(pp, prof, 1.0)
    if tone_table is not None:
        pp = rgb_tone(pp, load_tone_table(tone_table))
    lin = dng_linear_prophoto_to_srgb(pp)
    state = {'wb': wb, 'baseline_ev': baseline_ev,
             'src_bounds': info['src_bounds'], 'dst_size': info['dst_size']}
    # DNG SDK 非 HDR profile: RefBaselineRGBtoRGB 对 final 逐通道 Pin[0,1]
    return np.clip(lin, 0.0, 1.0).astype(np.float32), state


def compare(ours, ref):
    ref = np.asarray(ref, dtype=np.float32)
    # 曝光归一: 中位 luma 对齐 (只看色彩结构)
    def luma(x):
        return x @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    lo, lr = luma(ours), luma(ref)
    scale = float(np.median(lr) / max(np.median(lo), 1e-9))
    ours_n = np.clip(ours * scale, 0.0, None)
    diff = ours_n - ref
    print('raw mean abs', float(np.abs(ours - ref).mean()))
    print('scaled mean abs', float(np.abs(ours_n - ref).mean()))
    for i, ch in enumerate('RGB'):
        d = diff[..., i]
        print(f'{ch}: mean={d.mean():+.6f} std={d.std():.6f} mae={np.abs(d).mean():.6f} p95={np.percentile(np.abs(d),95):.6f}')
    return diff


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dng', required=True)
    ap.add_argument('--dcp', required=True)
    ap.add_argument('--ref', required=True)
    ap.add_argument('--out', default=None)
    ap.add_argument('--no-hsm', action='store_true')
    ap.add_argument('--tone-table', default=None,
                    help='DNG_DUMP_TONE_TABLE 输出 (线性渲染里 SDK 仍套 ProfileToneCurve)')
    ap.add_argument('--baseline-ev', type=float, default=None,
                    help='DNG TotalBaselineExposure - log2(Stage3Gain)')
    ap.add_argument('--stage3-raw', default=None,
                    help='DNG SDK --dump-stage3-raw 输出 (跳过 rawpy 输入, 逐级对齐 Stage3 之后)')
    ap.add_argument('--engine-log', default=None,
                    help='dng_engine 的 --dump-color-math + DNG_DUMP_RESAMPLE_INFO 日志')
    ap.add_argument('--rawpy', action='store_true',
                    help='显式使用 rawpy 输入 (默认自动走 SDK Stage3 缓存)')
    args = ap.parse_args()
    ref = cv2.imread(args.ref, cv2.IMREAD_UNCHANGED)
    if ref is None:
        print('cannot read ref tiff'); return 1
    print('ref', ref.shape, ref.dtype, float(ref.min()), float(ref.max()))
    if ref.ndim == 3:
        ref = cv2.cvtColor(ref, cv2.COLOR_BGR2RGB)
    if args.stage3_raw:
        if not args.engine_log:
            print('--stage3-raw 需要 --engine-log (crop/dst/baseline 信息)')
            return 2
        ours, state = render_from_stage3(
            args.stage3_raw, args.dng, args.dcp, args.engine_log,
            hsm=not args.no_hsm, tone_table=args.tone_table)
    elif not args.rawpy:
        # 边界对齐默认模式: 让 dng_engine 自己 dump Stage3 + color-math/tone
        # 探针, 再走我们引擎的 DNG 路径。rawpy 输入只作为 --rawpy 显式备选。
        from rawlab.tools.dng_stage3_replicate import run_engine
        out_dir = Path(args.dng).parent / "rawflow_dng_cache"
        try:
            stage_raw, _, tone_path, text = run_engine(
                args.dng, args.dcp, out_dir, Path(args.dng).stem)
            log = out_dir / f"{Path(args.dng).stem}.engine.log"
            ours, state = render_from_stage3(
                stage_raw, args.dng, args.dcp, log,
                hsm=not args.no_hsm, tone_table=tone_path)
        except Exception as exc:
            print('auto SDK stage3 failed, fallback rawpy:', exc)
            ours, state = render_linear(
                args.dng, args.dcp, ref_shape=ref.shape,
                hsm=not args.no_hsm, tone_table=args.tone_table,
                dng_baseline_ev=args.baseline_ev)
    else:
        ours, state = render_linear(args.dng, args.dcp, ref_shape=ref.shape,
                                    hsm=not args.no_hsm, tone_table=args.tone_table,
                                    dng_baseline_ev=args.baseline_ev)
    print('ours', ours.shape, ours.min(), ours.max(), 'wb', state.get('wb'))
    if args.out:
        cv2.imwrite(args.out, cv2.cvtColor(ours, cv2.COLOR_RGB2BGR))
        print('wrote', args.out)
    compare(ours, ref)
    return 0


if __name__ == '__main__':
    sys.exit(main())
