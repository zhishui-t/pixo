"""DCP HueSatMap 表 → OKLCh 控制点云离线转换 (设计 §3 / M-O2, 供 M-D1 标定)。

输入: DCP 的 HueSatMap (0xC6FA, 本机表 dims 90×16×16, 每格 (hue_shift_deg,
sat_scale, val_scale)); 采样域与运行时 apply_hue_sat_map_prophoto 完全同构:
  HSV(线性 ProPhoto 域, H∈[0,360), S/V∈[0,1]) → RGB_pp → 线性 sRGB →
  gamma sRGB → OKLab → OKLCh; 对每个网格节点记录"查表前/后"的 OKLCh 坐标
  (h_in, C_in, L_in) 与表的 OKLCh 语义作用量: Δh (环绕折回 ±180)、C 增益、
  L 增益 —— 即"这个 OKLCh 控制点在 DCP look 下应被移动/缩放多少"。

产出: configs/color/hsm_oklch_<dcp-slug>.json (控制点云)。
纪律: **只产数据不接运行时** —— 阶段二才由 M-D1 消费; 本脚本不改任何运行时
配置/代码路径。恒等节点 (|Δh|、|ΔC/C|、|ΔL/L| 均小于容差) 缺省剪除。

用法:
  python scripts/convert_hsm_to_oklch.py                     # 默认 DCP
  python scripts/convert_hsm_to_oklch.py --keep-identity     # 保留全网格
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pixo.render.core.calibration import load_dcp
from pixo.render.core.color import (linear_prophoto_to_linear_srgb,
                                    linear_srgb_to_linear_prophoto)
from pixo.render.core.huesat import (_hsv_to_rgb, _rgb_to_hsv,
                                     _srgb_decode_v, _srgb_encode_v)
from pixo.render.core.oklab import oklab_to_oklch, srgb_to_oklab
from pixo.render.core.tone import srgb_encode

DCP = "resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
OUT_DIR = "configs/color"

# 恒等容差 (Δh 度 / C、L 相对增益); 表本身 float32, 取 3 位小数量级
EPS_DH = 1e-2
EPS_GAIN = 1e-3


def resolve_table(prof, which: str):
    """选表 → (table, dims, encoding, 表来源标签)。

    "auto": 真 HueSatMap (0xC6FA) 优先, 缺席回退 LookTable —— 本机 RawLab
    DCP 族无 0xC6FA, 90×16×16 表在联合标签 0xC726 (语义 LookTable, 见
    core/calibration.py 旧版联合标签注释), 即任务所称 "HSM 表 (90×16×16)"。
    """
    from pixo.render.core.huesat import get_hue_sat_table, get_look_table
    if which in ("auto", "hsm"):
        t, d, e = get_hue_sat_table(prof)
        if t is not None:
            return t, d, e, "ProfileHueSatMap (0xC6FA)"
        if which == "hsm":
            print("DCP 无真 HueSatMap 表", file=sys.stderr)
            sys.exit(1)
    t, d, e = get_look_table(prof)
    if t is not None:
        return t, d, e, "ProfileLookTable (0xC726 联合标签)"
    print("DCP 无 HueSatMap/LookTable 表", file=sys.stderr)
    sys.exit(1)


def _pp_hsv_to_oklch(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    """线性 ProPhoto 域 HSV → gamma sRGB → OKLCh (出口 float64, (...,3))。"""
    pp = _hsv_to_rgb(h, s, v)
    lin = linear_prophoto_to_linear_srgb(pp.astype(np.float64))
    return oklab_to_oklch(srgb_to_oklab(srgb_encode(lin)))


def convert(table: np.ndarray, dims: tuple[int, int, int], encoding: int,
            strength: float = 1.0) -> list[dict]:
    """(H,S,V,3) 表 → OKLCh 控制点列表 (含恒等节点, 剪除由调用方做)。"""
    h_divs, s_divs, v_divs = dims
    # 网格节点坐标 (对齐 apply_table_to_hsv 的三线性节点语义)
    h_axis = (np.arange(h_divs, dtype=np.float64) * (360.0 / h_divs))
    s_axis = np.arange(s_divs, dtype=np.float64) / max(s_divs - 1, 1)
    v_axis = np.arange(v_divs, dtype=np.float64) / max(v_divs - 1, 1)
    hh, ss, vv = np.meshgrid(h_axis, s_axis, v_axis, indexing="ij")

    # 表作用量 (strength 语义同 apply_table_to_hsv)
    hue_shift = table[..., 0].astype(np.float64) * strength
    sat_scale = 1.0 + strength * (table[..., 1].astype(np.float64) - 1.0)
    val_scale = 1.0 + strength * (table[..., 2].astype(np.float64) - 1.0)

    lch_in = _pp_hsv_to_oklch(hh, ss, vv)
    s_out = np.clip(ss * sat_scale, 0.0, 1.0)
    if encoding == 1:
        # DNG RefBaselineHueSatMap 语义: V 轴在 sRGB gamma 域缩放 (同运行时)
        v_out = _srgb_decode_v(_srgb_encode_v(vv) * val_scale)
    else:
        v_out = vv * val_scale
    lch_out = _pp_hsv_to_oklch((hh + hue_shift) % 360.0, s_out,
                               np.clip(v_out, 0.0, None))

    # oklab_to_oklch 出口为 (L, C, h): h 在第 3 列, C 在第 2 列
    l_in = lch_in[..., 0].ravel()
    c_in = lch_in[..., 1].ravel()
    h_in = lch_in[..., 2].ravel()
    l_out = lch_out[..., 0].ravel()
    c_out = lch_out[..., 1].ravel()
    h_out = lch_out[..., 2].ravel()
    idx = np.argwhere(np.ones(dims[:3], dtype=bool))   # (n, 3) 网格索引

    dh = (h_out - h_in + 180.0) % 360.0 - 180.0        # 环绕折回 ±180
    with np.errstate(divide="ignore", invalid="ignore"):
        c_gain = np.where(c_in > EPS_GAIN, c_out / np.maximum(c_in, 1e-12), 1.0)
        l_gain = np.where(l_in > EPS_GAIN, l_out / np.maximum(l_in, 1e-12), 1.0)

    points = []
    for n in range(idx.shape[0]):
        points.append({
            "grid": [int(idx[n, 0]), int(idx[n, 1]), int(idx[n, 2])],
            "h": round(float(h_in[n]), 4), "c": round(float(c_in[n]), 6),
            "l": round(float(l_in[n]), 6),
            "dh": round(float(dh[n]), 4),
            "c_gain": round(float(c_gain[n]), 6),
            "l_gain": round(float(l_gain[n]), 6),
        })
    return points


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dcp", default=DCP)
    ap.add_argument("--out-dir", default=OUT_DIR)
    ap.add_argument("--table", default="auto", choices=("auto", "hsm", "look"),
                    help="auto: 真 HSM 优先, 缺席用 LookTable (本机 DCP 族)")
    ap.add_argument("--keep-identity", action="store_true",
                    help="保留恒等网格节点 (缺省剪除, 点云更小)")
    ap.add_argument("--strength", type=float, default=1.0)
    args = ap.parse_args()

    prof = load_dcp(args.dcp)
    table, dims, encoding, table_src = resolve_table(prof, args.table)
    print(f"HSM dims={dims} encoding={encoding} 格数={table.shape[0] * table.shape[1] * table.shape[2]}")

    points = convert(table, dims, encoding, strength=args.strength)
    n_total = len(points)
    if not args.keep_identity:
        points = [p for p in points
                  if abs(p["dh"]) >= EPS_DH
                  or abs(p["c_gain"] - 1.0) >= EPS_GAIN
                  or abs(p["l_gain"] - 1.0) >= EPS_GAIN]

    slug = re.sub(r"[^a-z0-9]+", "_", Path(args.dcp).stem.lower()).strip("_")
    out = Path(args.out_dir) / f"hsm_oklch_{slug}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "pixo.hsm_oklch_points.v1",
        "source_dcp": str(Path(args.dcp).name),
        "table_source": table_src,
        "table_dims": list(dims),
        "table_encoding": encoding,
        "strength": args.strength,
        "sampling_domain": ("HSV(线性 ProPhoto, 与 DNG SDK HSM 应用域一致) → "
                            "线性 sRGB → gamma sRGB → OKLCh (core.oklab)"),
        "point_semantics": {
            "grid": "[i_hue, j_sat, k_val] 源表网格索引 (布局 ((v*H)+h)*S+s)",
            "h/c/l": "查表前像素的 OKLCh 色相(度)/色度/亮度",
            "dh": "查表后色相增量 (度, 折回 ±180)",
            "c_gain": "查表后色度增益 (C_out/C_in; C_in≈0 时恒 1)",
            "l_gain": "查表后亮度增益 (L_out/L_in; L_in≈0 时恒 1)",
        },
        "identity_eps": {"dh_deg": EPS_DH, "gain": EPS_GAIN},
        "n_points_total": n_total,
        "n_points": len(points),
        "n_identity_pruned": n_total - len(points),
        "points": points,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    print(f"点云 {len(points)}/{n_total} (剪除恒等 {n_total - len(points)}) -> {out}")


if __name__ == "__main__":
    main()
