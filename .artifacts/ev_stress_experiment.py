"""R18 任务1: 语料级 ±1EV 压力实验 (tech_debt #13.3) —— 只读实验, 不改产品代码。

方法:
  - 注入: monkeypatch pixo.render.core.io.decode_cfa_half, 对解码后的线性相机
    RGB 乘 2^ev (模拟拍摄曝光偏移; 线性域全局增益与光学曝光偏移同构)。
    api.render_preview_full 在函数体内 `from .core.io import decode_cfa_half`,
    故 patch io 模块属性即可生效; postprocess 回退路径不吃增益 (语料上
    cfa_half_native 为生产路径, 不触发回退; 0EV 臂充当对照)。
  - 挂钩: 类级包装 ExposureStage._auto_ev, 记录每次决策的 (med 探针, ev,
    ev_mode, spike_lift)。
  - 轨: 默认链渲染 (exposure auto + warmth 0.9 = 生产缺省) @ long_edge=512;
    参考与 ΔE 口径同 eval_rp_ccm_ab (缩略图对齐 + [0.01,0.90] 线性窗 + stride 3
    + 逐照片标量增益对齐); 另记未对齐 dL 与残差 EV (补偿不足可见化)。
  - warmth/曝光表域外: wb_B 逐照片解析 (EV 不变量), 域判定在分析阶段离线复算
    (复刻 _cal_ev 逻辑含 wb 钳位检测), 本脚本只记录 (med, ev_chosen, wb_B)。
  - 断点续跑: 逐 (photo, arm) 追加 JSONL checkpoint, 重跑跳过已完成键。

用法: python .artifacts/ev_stress_experiment.py [--limit N] [--arms -1,-0.5,0,0.5,1]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import pixo.render.core.io as rio  # noqa: E402
from fit_rp_ccm import (DCP, SAMPLE_LIN_HI, SAMPLE_LIN_LO, align_thumb_to_sensor,  # noqa: E402
                        camera_thumb_rgb, iter_corpus, sample_linear_pairs)
from pixo.pipeline.perceptual import delta_e_2000, linear_srgb_to_lab  # noqa: E402
from pixo.render.api import Renderer  # noqa: E402
from pixo.render.core.rp_ccm import apply_rp_ccm, load_rp_ccm  # noqa: E402
from pixo.render.core.tone import srgb_decode  # noqa: E402

CKPT = Path(__file__).resolve().parent / "ev_stress_checkpoint.jsonl"
OUT = Path(__file__).resolve().parent / "ev_stress_results.json"
ARMS = (-1.0, -0.5, 0.0, 0.5, 1.0)
PREVIEW_EDGE = 512
STRIDE = 3


def load_done() -> set:
    if not CKPT.exists():
        return set()
    done = set()
    for line in CKPT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                d = json.loads(line)
                done.add((d["photo_id"], d["ev"]))
            except Exception:
                pass
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="exports/auto/full_scan")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--arms", default="-1,-0.5,0,0.5,1")
    ap.add_argument("--dcp", default=DCP)
    args = ap.parse_args()
    arms = tuple(float(x) for x in args.arms.split(","))

    items = iter_corpus(args.corpus, None, args.limit)
    renderer = Renderer(args.dcp)
    coeff = load_rp_ccm(ROOT / "configs" / "color" / "rp_ccm_nikon_z5_2.json")

    from pixo.meta import extract as meta_extract
    from pixo.render.modules.exposure import ExposureStage, _probe_linear_srgb

    done = load_done()
    ckpt_f = CKPT.open("a", encoding="utf-8")

    # ---- 挂钩: _auto_ev 决策记录 (类级包装; 每次 render 恰好一次 exposure) ----
    orig_auto_ev = ExposureStage._auto_ev
    ev_log: dict[str, dict] = {}
    CUR_KEY = [""]

    def wrapped_auto_ev(self, ctx):
        ev = orig_auto_ev(self, ctx)
        try:
            y = _probe_linear_srgb(ctx, ctx.image)
            med = float(np.median(np.log2(np.maximum(y, 1e-6))))
        except Exception:
            med = float("nan")
        ev_log[CUR_KEY[0]] = {
            "ev_chosen": float(ev), "ev_mode": ctx.state.get("ev_mode"),
            "med": med, "spike_lift": bool(ctx.state.get("ev_spike_lift", False)),
        }
        return ev

    ExposureStage._auto_ev = wrapped_auto_ev

    # ---- 注入: 解码后线性增益 (实验臂) ----
    orig_decode = rio.decode_cfa_half
    CUR_GAIN = [None]  # None=不注入; 数值=增益臂 (注意 1.0 也是合法臂: ×2^1.0)

    def patched_decode(raw, raw_path=None):
        img = orig_decode(raw, raw_path=raw_path)
        if CUR_GAIN[0] is not None:
            img = img * np.float32(2.0 ** CUR_GAIN[0])
        return img

    rio.decode_cfa_half = patched_decode

    results: list[dict] = []
    t0 = time.time()
    try:
        for i, (pid, raw) in enumerate(items, 1):
            try:
                orientation = int((meta_extract(raw)["capture"].get("orientation") or 1))
            except Exception:
                orientation = 1
            ref = camera_thumb_rgb(raw)
            ref, _ = align_thumb_to_sensor(ref, orientation, "auto")
            import rawpy
            with rawpy.imread(raw) as rr:
                cam_wb = rr.camera_whitebalance  # [r, g, b, g2]
            wb_b = float(cam_wb[2]) / max(float(cam_wb[1]), 1e-9)
            ref_shape = ref.shape[:2]

            for ev_off in arms:
                key = f"{pid}|{ev_off}"
                if (pid, ev_off) in done:
                    continue
                CUR_KEY[0] = key
                CUR_GAIN[0] = ev_off if ev_off != 0.0 else None
                rec: dict = {"photo_id": pid, "ev": ev_off, "wb_B": wb_b}
                try:
                    base = renderer.render_preview_full(raw, long_edge=PREVIEW_EDGE)
                    if base.dtype == np.uint8:
                        base = base.astype(np.float64) / 255.0
                    else:
                        base = np.asarray(base, dtype=np.float64)
                    if ref_shape != base.shape[:2]:
                        import cv2
                        ref_r = cv2.resize(ref, (base.shape[1], base.shape[0]),
                                           interpolation=cv2.INTER_AREA)
                    else:
                        ref_r = ref
                    b_lin, r_lin = sample_linear_pairs(base, ref_r, stride=STRIDE)
                    rec["n"] = int(b_lin.shape[0])
                    g = base[::STRIDE, ::STRIDE]
                    rec["grid_points"] = int(g.shape[0] * g.shape[1])
                    lin = srgb_decode(
                        np.ascontiguousarray(g).reshape(-1, 3).astype(np.float32))
                    inwin = np.all((lin >= SAMPLE_LIN_LO) & (lin <= SAMPLE_LIN_HI),
                                   axis=1)
                    rec["render_inwin_rate"] = float(inwin.mean())
                    if b_lin.shape[0] >= 500:
                        gain = float(r_lin.mean() / max(b_lin.mean(), 1e-9))
                        rec["residual_ev"] = float(np.log2(gain))
                        rp_lin = apply_rp_ccm(b_lin, coeff).astype(np.float64)
                        d_a = delta_e_2000(linear_srgb_to_lab(b_lin * gain),
                                           linear_srgb_to_lab(r_lin))
                        d_b = delta_e_2000(linear_srgb_to_lab(rp_lin * gain),
                                           linear_srgb_to_lab(r_lin))
                        rec["a_median"] = float(np.median(d_a))
                        rec["a_p95"] = float(np.quantile(d_a, 0.95))
                        rec["b_median"] = float(np.median(d_b))
                        rec["b_p95"] = float(np.quantile(d_b, 0.95))
                        lab_b = linear_srgb_to_lab(b_lin)
                        lab_r = linear_srgb_to_lab(r_lin)
                        rec["unaligned_dL"] = float(
                            np.mean(lab_b[..., 0] - lab_r[..., 0]))
                    else:
                        rec["skipped"] = "有效样本过少"
                except Exception as exc:  # noqa: BLE001 — 崩溃本身是实验读数
                    rec["error"] = f"{type(exc).__name__}: {exc}"
                rec.update(ev_log.get(key, {}))
                results.append(rec)
                ckpt_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                ckpt_f.flush()
                done.add((pid, ev_off))
                print(f"[{i}/{len(items)}] {pid} ev={ev_off:+.1f} "
                      f"a={rec.get('a_median', float('nan')):.2f} "
                      f"b={rec.get('b_median', float('nan')):.2f} "
                      f"evc={rec.get('ev_chosen', float('nan')):+.2f} "
                      f"mode={rec.get('ev_mode')} {rec.get('error', '')}",
                      flush=True)
    finally:
        ExposureStage._auto_ev = orig_auto_ev
        rio.decode_cfa_half = orig_decode
        ckpt_f.close()

    OUT.write_text(json.dumps(
        {"arms": list(arms), "n_photos": len(items),
         "elapsed_s": time.time() - t0, "rows": results},
        ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"DONE {len(results)} rows -> {OUT} ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
