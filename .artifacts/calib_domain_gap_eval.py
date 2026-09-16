"""R19: 标定覆盖缺口专项评估 —— warmth 垫片精度实测 + wb_B 分布画像。

背景 (R18 发现): 全语料 56% 样本 wb_B 落 warmth 拟合域 [1.758,2.398] 外
(端点垫片承接), 曝光表 wb_B 结点域 [1.26,1.691] 外 89% (2D 表 wb 轴端点钳制)。

实验设计 (只读, 不改产品代码):
  Part A (warmth 垫片精度): 54 照片 × 6 臂渲染 @512 (生产缺省链, tone 缺省
    +0.25 与拟合假设一致):
      s-scan  warmth ∈ {0, 0.405, 0.9, 1.215, 1.62}  (= 缺省 0.9 × s∈{0,.45,.9,1.35,1.8})
              gain = 1 + warmth·(结点插值−1), 0=恒等, 0.9=现行垫片;
      fallback 臂: warmth 0.9 + fallback_outside_domain=true (域外回退内置斜率
              模型, wb_B≈1.07 日光 → s=0 即无暖度) —— 运行时自带替代臂。
    真值: RAW 内嵌缩略图 Lab 均值 (fit_warmth_curve 同源真值口径)。
    逐照片: Lab 均值差 (dL/da/db) + ΔE00; s-扫描 → 每照片最优 s (抛物线细化)。
  Part B (曝光表 wb 轴): 离线复算 —— R18 checkpoint 的 (med, wb_B, residual_ev)
    + 复刻 _cal_ev 含/不含 wb 分支 → wb 轴贡献与钳制受害面; residual_ev 对
    wb_B 相关性 (钳制是否丢失个性化信息)。

判定口径 (预登记):
  - 垫片受害 = ΔE00(Lab 均值, 垫片臂) ≥ 2.3 (JND) 且最优臂可恢复 ≥50%;
  - 若 OOS 组垫片误差中位 < JND 或最优 s ≈ 1 → 记录接受; 若最优 s 系统性
    偏离 1 且可恢复 → 扩域/回退建议。

用法: python .artifacts/calib_domain_gap_eval.py [--limit N]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from fit_rp_ccm import align_thumb_to_sensor, camera_thumb_rgb, iter_corpus  # noqa: E402
from pixo.pipeline.perceptual import delta_e_2000, linear_srgb_to_lab  # noqa: E402
from pixo.render.api import Renderer  # noqa: E402
from pixo.render.core.tone import srgb_decode  # noqa: E402

DCP = "resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
CKPT = Path(__file__).resolve().parent / "calib_domain_gap_checkpoint.jsonl"
OUT = Path(__file__).resolve().parent / "calib_domain_gap_results.json"
S_ARMS = (0.0, 0.45, 0.9, 1.35, 1.8)     # s × 缺省 warmth 0.9
FIT_DOM = (1.7578, 2.3984)
INTERP_DOM = (1.6778, 2.4784)
CAL_WB = (1.26, 1.691)
CAL_MED = (-6.811, -3.044)
PREVIEW_EDGE = 512


def lab_mean(rgb_u8_or_f: np.ndarray) -> np.ndarray:
    """gamma sRGB [0,1] → Lab 均值 (L∈[0,100])。"""
    img = np.asarray(rgb_u8_or_f, dtype=np.float64)
    if img.max() > 1.5:
        img = img / 255.0
    lin = srgb_decode(np.ascontiguousarray(img).astype(np.float32))
    lab = linear_srgb_to_lab(lin)
    return lab.reshape(-1, 3).mean(axis=0)


def load_done() -> set:
    if not CKPT.exists():
        return set()
    done = set()
    for line in CKPT.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                d = json.loads(line)
                done.add((d["photo_id"], d["arm"]))
            except Exception:
                pass
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="exports/auto/full_scan")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dcp", default=DCP)
    args = ap.parse_args()

    items = iter_corpus(args.corpus, None, args.limit)
    renderer = Renderer(args.dcp)
    done = load_done()
    ckpt_f = CKPT.open("a", encoding="utf-8")
    arms = [(f"s{g}", {"whitebalance": {"warmth": round(g * 0.9, 4)}})
            for g in S_ARMS]
    arms.append(("fallback", {"whitebalance": {"fallback_outside_domain": True}}))

    t0 = time.time()
    n_renders = 0
    try:
        for i, (pid, raw) in enumerate(items, 1):
            try:
                from pixo.meta import extract as meta_extract
                orientation = int(meta_extract(raw)["capture"].get("orientation") or 1)
            except Exception:
                orientation = 1
            ref = camera_thumb_rgb(raw)
            ref, _ = align_thumb_to_sensor(ref, orientation, "auto")
            import rawpy
            with rawpy.imread(raw) as rr:
                cam_wb = rr.camera_whitebalance
            wb_b = float(cam_wb[2]) / max(float(cam_wb[1]), 1e-9)

            for arm_name, extra in arms:
                key = (pid, arm_name)
                if key in done:
                    continue
                params = {k: dict(v) for k, v in extra.items()}
                rec: dict = {"photo_id": pid, "arm": arm_name, "wb_B": wb_b}
                try:
                    img = renderer.render_preview_full(
                        raw, long_edge=PREVIEW_EDGE, params=params)
                    if img.dtype == np.uint8:
                        img = img.astype(np.float64) / 255.0
                    if ref.shape[:2] != img.shape[:2]:
                        ref_r = cv2.resize(ref, (img.shape[1], img.shape[0]),
                                           interpolation=cv2.INTER_AREA)
                    else:
                        ref_r = ref
                    lr = lab_mean(img)
                    lf = lab_mean(ref_r)
                    d = lr - lf
                    rec["dL"], rec["da"], rec["db"] = float(d[0]), float(d[1]), float(d[2])
                    d00 = delta_e_2000(
                        linear_srgb_to_lab(srgb_decode(
                            np.ascontiguousarray(img).astype(np.float32))),
                        linear_srgb_to_lab(srgb_decode(
                            np.ascontiguousarray(ref_r).astype(np.float32))))
                    rec["dE00"] = float(d00.mean())
                    n_renders += 1
                except Exception as exc:  # noqa: BLE001
                    rec["error"] = f"{type(exc).__name__}: {exc}"
                ckpt_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                ckpt_f.flush()
                done.add(key)
            print(f"[{i}/{len(items)}] {pid} wb_B={wb_b:.3f} done "
                  f"({time.time() - t0:.0f}s)", flush=True)
    finally:
        ckpt_f.close()
    print(f"DONE renders={n_renders} ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
