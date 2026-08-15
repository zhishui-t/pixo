"""DCP (Adobe Camera Profile) 解析 —— 阶段0核心。

DCP 是 TIFF 容器（新版本魔数 "IIRC"），内含相机色彩标定数据:
- ColorMatrix1/2 (tag 0xC621/0xC622): 相机 RGB → XYZ(D50) 色彩矩阵
- ForwardMatrix1/2 (tag 0xC714/0xC715): XYZ(D50) → 相机优化 RGB 前向矩阵
- ProfileToneCurve (tag 0xC6F2): 每通道分段影调曲线
- BaselineExposureOffset (tag 0xC6F9): 基线曝光偏移
- ProfileHueSatMapData1/2 (tag 0xC6FA/0xC6FB): 色相/饱和度网格 (HueSatMap)

参考: Adobe DNG SDK dng_tags.h + dng_camera_profile.cpp
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# TIFF 字段类型字节数
_TIFF_SIZES = {
    1: 1,   # BYTE
    2: 1,   # ASCII
    3: 2,   # SHORT
    4: 4,   # LONG
    5: 8,   # RATIONAL
    6: 1,   # SBYTE
    7: 1,   # UNDEFINED
    8: 2,   # SSHORT
    9: 4,   # SLONG
    10: 8,  # SRATIONAL
    11: 4,  # FLOAT
    12: 8,  # DOUBLE
}

_TAG_NAMES = {
    0xC612: "ProfileCalibrationSignature",
    0xC614: "ProfileName",
    0xC621: "ColorMatrix1",
    0xC622: "ColorMatrix2",
    0xC6F2: "ProfileToneCurve",
    0xC6F4: "ProfileCopyright",
    0xC6F7: "ProfileEmbedPolicy",
    0xC6F8: "ProfileLookTable",
    0xC6F9: "BaselineExposureOffset",
    0xC6FA: "ProfileHueSatMapData1",
    0xC6FB: "ProfileHueSatMapData2",
    0xC6FC: "ProfileHueSatMapEncoding",
    0xC714: "ForwardMatrix1",
    0xC715: "ForwardMatrix2",
    0xC726: "ProfileHueSatMapData",
    0xC728: "ProfileLookTableDims",
    0xC725: "ProfileHueSatMapDims",
    0xC727: "ProfileToneCurveDims",
    0xC729: "ProfileHueSatMapData2_alt",
}

# 色彩学常量 (CIE 标准)
# sRGB 线性矩阵: XYZ(D65) → 线性 sRGB
XYZ_D65_TO_SRGB = [
    [3.2404542, -1.5371385, -0.4985314],
    [-0.9692660, 1.8760108, 0.0415560],
    [0.0556434, -0.2040259, 1.0572252],
]
SRGB_TO_XYZ_D65 = [
    [0.4124564, 0.3575761, 0.1804375],
    [0.2126729, 0.7151522, 0.0721750],
    [0.0193339, 0.1191920, 0.9503041],
]
# Bradford 色适应: D50 → D65
BRADFORD_D50_TO_D65 = [
    [0.9555766, -0.0230393, 0.0631636],
    [-0.0282895, 1.0099416, 0.0210077],
    [0.0122982, -0.0204830, 1.3299098],
]


@dataclass
class DcpProfile:
    """解析后的 DCP 相机配置文件。"""
    path: Path
    name: str = ""
    calibration_signature: str = ""
    color_matrix1: Optional[List[float]] = None      # 9 元素行主序 3x3
    color_matrix2: Optional[List[float]] = None
    forward_matrix1: Optional[List[float]] = None
    forward_matrix2: Optional[List[float]] = None
    profile_tone_curve: Optional[List[float]] = None   # 125 点 (x,y) 交错影调曲线 (0xC6FC)
    hue_sat_map: Optional[List[float]] = None          # 3×90×16×16 (hue/sat/val 平面, 0xC726)
    tone_curve: Optional[List[float]] = None           # 兼容旧字段 (指向 profile_tone_curve)
    baseline_exposure_offset: float = 0.0
    hue_sat_map1: Optional[List[float]] = None       # 色相/饱和度网格
    hue_sat_map2: Optional[List[float]] = None
    hue_sat_dims: Optional[List[int]] = None
    look_table: Optional[List[float]] = None         # ProfileLookTable (如有)
    tags: Dict[str, object] = field(default_factory=dict)

    def matrix3(self, values: Optional[List[float]]) -> Optional[List[List[float]]]:
        if not values or len(values) < 9:
            return None
        return [values[0:3], values[3:6], values[6:9]]


def _parse_ifd(data: bytes, endian: str, offset: int) -> Dict[int, Tuple[int, int, object]]:
    """解析单个 IFD, 返回 {tag: (type, count, value)}。"""
    entries = struct.unpack_from(endian + "H", data, offset)[0]
    tags: Dict[int, Tuple[int, int, object]] = {}
    for i in range(entries):
        e = offset + 2 + i * 12
        if e + 12 > len(data):
            break
        tag, typ, cnt = struct.unpack_from(endian + "HHI", data, e)
        size = _TIFF_SIZES.get(typ, 1) * cnt
        voff = e + 8
        if size > 4:
            voff = struct.unpack_from(endian + "I", data, voff)[0]
        try:
            tags[tag] = (typ, cnt, _read_values(data, endian, typ, cnt, voff))
        except (struct.error, IndexError):
            continue
    return tags


def _read_values(data: bytes, endian: str, typ: int, cnt: int, off: int) -> object:
    if typ in (1, 7):   # BYTE / UNDEFINED
        return data[off:off + cnt]
    if typ == 2:        # ASCII
        raw = data[off:off + cnt]
        return raw.split(b"\x00")[0].decode("latin1", errors="replace")
    if typ == 3:        # SHORT
        return list(struct.unpack_from(endian + "H" * cnt, data, off))
    if typ == 4:        # LONG
        return list(struct.unpack_from(endian + "I" * cnt, data, off))
    if typ == 5:        # RATIONAL
        out = []
        for j in range(cnt):
            n, d = struct.unpack_from(endian + "II", data, off + 8 * j)
            out.append(n / d if d else 0.0)
        return out
    if typ == 9:        # SLONG
        return list(struct.unpack_from(endian + "i" * cnt, data, off))
    if typ == 10:       # SRATIONAL (DCP 色彩矩阵用)
        out = []
        for j in range(cnt):
            n, d = struct.unpack_from(endian + "ii", data, off + 8 * j)
            out.append(n / d if d else 0.0)
        return out
    if typ == 11:       # FLOAT
        return list(struct.unpack_from(endian + "f" * cnt, data, off))
    if typ == 12:       # DOUBLE
        return list(struct.unpack_from(endian + "d" * cnt, data, off))
    return data[off:off + cnt]


def load_dcp(path: str | Path) -> DcpProfile:
    """加载并解析 DCP 文件。"""
    p = Path(path)
    data = p.read_bytes()
    if len(data) < 8 or data[:2] not in (b"II", b"MM"):
        raise ValueError(f"不是 TIFF/DCP 文件: {p}")
    endian = "<" if data[:2] == b"II" else ">"
    magic = data[2:4]
    # 标准 TIFF 魔数 42; 新版 DCP 用 "RC" 标记
    if magic != b"\x2a\x00" and magic != b"RC":
        raise ValueError(f"未知 TIFF 魔数: {magic!r}")

    ifd0_offset = struct.unpack_from(endian + "I", data, 4)[0]
    tags0 = _parse_ifd(data, endian, ifd0_offset)
    # 子 IFD (tag 0x014A SubIFDs 或 tag 330) 通常含 LookTable
    all_tags = dict(tags0)
    sub_ifds = []
    for t in (0x014A, 330, 0x8769):
        if t in tags0 and tags0[t][0] in (4, 3):
            v = tags0[t][2]
            sub_ifds = v if isinstance(v, list) else [v]
            break
    for sub in sub_ifds:
        try:
            all_tags.update(_parse_ifd(data, endian, int(sub)))
        except (struct.error, ValueError):
            continue

    prof = DcpProfile(path=p)
    for tag, (typ, cnt, val) in all_tags.items():
        name = _TAG_NAMES.get(tag, f"tag_{tag:04X}")
        prof.tags[name] = val
        if tag == 0xC614:
            prof.name = str(val)
        elif tag == 0xC612:
            prof.calibration_signature = str(val)
        elif tag == 0xC621:
            prof.color_matrix1 = val if isinstance(val, list) else None
        elif tag == 0xC622:
            prof.color_matrix2 = val if isinstance(val, list) else None
        elif tag == 0xC714:
            prof.forward_matrix1 = val if isinstance(val, list) else None
        elif tag == 0xC715:
            prof.forward_matrix2 = val if isinstance(val, list) else None
        elif tag == 0xC6F2:
            if isinstance(val, list):
                prof.tone_curve = val
                prof.profile_tone_curve = val
        elif tag == 0xC726 or tag == 0xC6FA:
            if isinstance(val, list) and val:
                prof.hue_sat_map = val
                prof.hue_sat_map1 = val
        elif tag == 0xC6FC:
            # 本 DCP: 125 点 (x,y) 交错影调曲线 (数据形态判定: 250 float, 值域 0-1)
            if isinstance(val, list) and len(val) >= 16 and max(val) <= 1.0:
                prof.profile_tone_curve = val
                prof.tone_curve = val
        elif tag == 0xC7A5:
            # BaselineExposureOffset (DNG 1.4+, 本 DCP = -0.15 EV)
            if isinstance(val, list) and val:
                prof.baseline_exposure_offset = float(val[0])
        elif tag == 0xC6F9:
            if isinstance(val, list) and val:
                prof.baseline_exposure_offset = float(val[0])
            elif isinstance(val, float):
                prof.baseline_exposure_offset = val
        elif tag == 0xC6FB:
            prof.hue_sat_map2 = val if isinstance(val, list) else None
        elif tag == 0xC725:
            prof.hue_sat_dims = val if isinstance(val, list) else None
        elif tag == 0xC6F8:
            prof.look_table = val if isinstance(val, list) else None
    return prof


def find_camera_dcp(model: str, profile_name: str = "Camera Standard",
                    search_dirs: Optional[List[str]] = None) -> Optional[Path]:
    """在 Adobe CameraRaw 配置目录查找相机 DCP。

    model: 相机型号, 如 "Nikon Z 5 2"
    profile_name: "Camera Standard" / "Adobe Standard" 等
    """
    import os
    dirs = search_dirs or [
        r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles",
        os.path.expandvars(r"%APPDATA%\Adobe\CameraRaw\CameraProfiles"),
    ]
    model_dir = Path(model)
    for base in dirs:
        base = Path(base)
        for sub in ("Camera", "Adobe Standard"):
            cand = base / sub / model_dir / f"{model} {profile_name}.dcp"
            if cand.exists():
                return cand
        # Adobe Standard 目录下文件名带相机名
        std = base / "Adobe Standard" / f"{model} {profile_name}.dcp"
        if std.exists():
            return std
    return None


if __name__ == "__main__":
    import sys
    d = load_dcp(r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera"
                 r"\Nikon Z 5 2\Nikon Z 5 2 Camera Standard.dcp")
    print(f"name: {d.name}")
    print(f"signature: {d.calibration_signature}")
    cm = d.matrix3(d.color_matrix1)
    print("ColorMatrix1:")
    if cm:
        for row in cm:
            print("  ", [round(x, 6) for x in row])
    fm = d.matrix3(d.forward_matrix1)
    print("ForwardMatrix1:")
    if fm:
        for row in fm:
            print("  ", [round(x, 6) for x in row])
    print(f"tone_curve: {len(d.tone_curve) if d.tone_curve else 0} pts")
    print(f"baseline_exposure: {d.baseline_exposure_offset}")
    print(f"hue_sat_map1: {len(d.hue_sat_map1) if d.hue_sat_map1 else 0} vals, "
          f"dims={d.hue_sat_dims}")
