"""DCP 底座渲染 API: NEF/DNG + DCP -> 线性 sRGB (与 DNG SDK 对齐)。

运行时无 DNG SDK 依赖; 相机/镜头参数从 dng_camera_cache.json 查表。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Union

import numpy as np
import rawpy

from ..core.color import cam_wb_to_prophoto, linear_prophoto_to_srgb
from ..core.io import camera_neutral_wb, decode_stage3_like
from ..core.tone import apply_rgb_tone, exposure_ramp, load_tone_table
from ..core.huesat import apply_hue_sat_map_prophoto, apply_look_table_prophoto


def camera_key(raw_path: Union[str, Path]) -> str:
    import exifread
    with open(str(raw_path), "rb") as f:
        tags = exifread.process_file(f, details=False)
    return "|".join([
        str(tags.get("Image Model", "")).strip(),
        str(tags.get("EXIF LensModel", "")).strip(),
        str(tags.get("EXIF FocalLength", "")).strip(),
    ])


def load_camera_cache(path: Union[str, Path, None] = None) -> dict:
    if path is None:
        path = Path(__file__).resolve().parents[1] / "calibration_data" / "dng_camera_cache.json"
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_camera_entry(raw_path: Union[str, Path], cache: dict | None = None) -> dict:
    cache = cache or load_camera_cache()
    model, lens, focal = camera_key(raw_path).split("|")
    entries = cache.get("entries", {})
    key = "|".join((model, lens, focal))
    entry = entries.get(key)
    if entry is not None:
        return entry
    # 同机同镜头缓存了其他焦距: 用最近焦距的条目 (opcode 会略有偏差,
    # 但 10 张预览够用; 精确渲染应补焦距缓存)
    same = []
    for k, e in entries.items():
        if k.startswith(f"{model}|{lens}|"):
            try:
                same.append((abs(float(e.get("focal", 0)) - float(focal)), e))
            except (TypeError, ValueError):
                pass
    if same:
        same.sort(key=lambda x: x[0])
        return same[0][1]
    raise FileNotFoundError(
        f"dng_camera_cache 未命中: {key}; "
        f"先运行 render/tools/build_dng_camera_cache.py")


def render_dcp_linear(raw_path: Union[str, Path], dcp_path: Union[str, Path],
                      cache: dict | None = None,
                      dng_pair: Union[str, Path, None] = None) -> np.ndarray:
    """渲染 RAW + DCP 底座, 返回 (H,W,3) float32 线性 sRGB [0,1]。

    NEF 无配对 DNG 时按相机|镜头|焦距查 dng_camera_cache.json。
    """
    raw_path = Path(raw_path)
    is_dng = raw_path.suffix.lower() == ".dng"
    entry = None
    if dng_pair is not None or is_dng:
        # DNG 或显式配对: 直接读 opcode; 缓存项用于基线/影调表
        cache_all = cache or load_camera_cache()
        pair = Path(dng_pair) if dng_pair else raw_path
        img, raw_obj = decode_stage3_like(str(raw_path), dng_pair=str(pair))
        raw_obj.close()
        try:
            entry = find_camera_entry(pair, cache_all)
        except FileNotFoundError:
            entry = None
    else:
        entry = find_camera_entry(raw_path, cache)
        img, raw_obj = decode_stage3_like(
            str(raw_path), white_level=entry["white_level"],
            opcodes=entry["opcodes"])
        raw_obj.close()
    if entry is None:
        raise FileNotFoundError("缺少 dng_camera_cache 条目, 无法确定 baseline/tone table")
    from ..core.resample import dng_resample
    src = dng_resample(img, tuple(entry["src_bounds"]), tuple(entry["dst_size"]))
    from ..core.calibration import load_dcp
    prof = load_dcp(dcp_path)
    rp = rawpy.imread(str(raw_path))
    wb = camera_neutral_wb(rp)
    rp.close()
    pp = cam_wb_to_prophoto(src, prof, wb)
    pp = apply_hue_sat_map_prophoto(pp, prof, 1.0)
    baseline_ev = entry["total_baseline"] - np.log2(entry["stage3_gain"])
    pp = exposure_ramp(pp, baseline_ev)
    pp = apply_look_table_prophoto(pp, prof, 1.0)
    table = load_tone_table(entry["tone_table"])
    pp = apply_rgb_tone(pp, table)
    return linear_prophoto_to_srgb(pp)

__all__ = ["camera_key", "load_camera_cache", "find_camera_entry",
           "render_dcp_linear"]
