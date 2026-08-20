"""DCP (Adobe Camera Profile) 解析 —— 阶段0核心。

DCP 是 TIFF 容器（新版本魔数 "IIRC"），内含相机色彩标定数据:
- ColorMatrix1/2 (tag 0xC621/0xC622): 相机 RGB → XYZ(D50) 色彩矩阵
- ForwardMatrix1/2 (tag 0xC714/0xC715): XYZ(D50) → 相机优化 RGB 前向矩阵
- ProfileToneCurve (tag 0xC6F2): 每通道分段影调曲线
- BaselineExposureOffset (tag 0xC7A5): 基线曝光偏移 (EV)
- HueSatMap: ProfileHueSatMapData1/2 (0xC6FA/0xC6FB, FLOAT) + dims 0xC6F9 + encoding 0xC6FC/0xC7A3;
- LookTable: ProfileLookTableData (0xC726, FLOAT) + dims 0xC725 + encoding 0xC6FD/0xC7A4
- ProfileName (tag 0xC6F8, ASCII): 相机预览名 (如 "Camera Standard")

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
    0xC623: "CameraCalibration1",
    0xC624: "CameraCalibration2",
    0xC65A: "CalibrationIlluminant1",
    0xC65B: "CalibrationIlluminant2",
    0xC6F2: "ProfileToneCurve",
    0xC6F4: "ProfileCopyright",
    0xC6F7: "ProfileEmbedPolicy",
    # 勘误: 0xC6F8 是 ProfileName (ASCII, 如 "Camera Standard"), 不是 LookTable。
    0xC6F8: "ProfileName",
    # 注意: 0xC6F9 = ProfileHueSatMapDims (50937), 不是 BaselineExposureOffset。
    # 真正的 BaselineExposureOffset 是 0xC7A5 (51109), 见 DNG SDK dng_tag_codes.h。
    0xC6F9: "ProfileHueSatMapDims",
    0xC6FA: "ProfileHueSatMapData1",
    0xC6FB: "ProfileHueSatMapData2",
    0xC6FC: "ProfileHueSatMapEncoding",
    0xC6FD: "ProfileLookTableEncoding",
    0xC714: "ForwardMatrix1",
    0xC715: "ForwardMatrix2",
    # 0xC726 = ProfileLookTableData (50982)。Adobe Camera Standard v2 的 90×16×16×3
    # 观感表就放在这里, 语义是 LookTable 而非 HueSatMap; HueSatMap 是 0xC6FA。
    0xC726: "ProfileLookTableData",
    # 待考 (low#2): 0xC728 官方名 ProfileToneCurveData (50984, dng_tag_codes.h),
    # 旧误标为 ProfileLookTableDims (实为 0xC725); 本解析未使用, 保留标注待考。
    0xC728: "ProfileToneCurveData",
    # 0xC725 = ProfileLookTableDims (50981), 配合 0xC726 LookTable 使用。
    0xC725: "ProfileLookTableDims",
    0xC727: "ProfileToneCurveDims",
    0xC729: "ProfileHueSatMapData2_alt",
    # DNG 1.4 新编号: 0xC7A3 = ProfileHueSatMapEncoding (0xC6FA),
    # 0xC7A4 = ProfileLookTableEncoding (0xC726, Adobe 系列惯例 1/sRGB)。
    0xC7A3: "ProfileHueSatMapEncoding",
    0xC7A4: "ProfileLookTableEncoding",
    0xC7A5: "BaselineExposureOffset",
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
    camera_calibration1: Optional[List[float]] = None  # 0xC623 (参考相机→个体相机)
    camera_calibration2: Optional[List[float]] = None  # 0xC624
    calibration_illuminant1: int = 17                  # 0xC65A (EXIF 光源枚举, 缺省 StdA)
    calibration_illuminant2: int = 21                  # 0xC65B (缺省 D65)
    forward_matrix1: Optional[List[float]] = None
    forward_matrix2: Optional[List[float]] = None
    profile_tone_curve: Optional[List[float]] = None   # 125 点 (x,y) 交错影调曲线 (0xC6FC)
    hue_sat_map: Optional[List[float]] = None          # 0xC6FA ProfileHueSatMapData1
    tone_curve: Optional[List[float]] = None           # 兼容旧字段 (指向 profile_tone_curve)
    baseline_exposure_offset: float = 0.0              # 0xC7A5 BaselineExposureOffset (EV)
    hue_sat_map1: Optional[List[float]] = None       # 色相/饱和度网格
    hue_sat_map2: Optional[List[float]] = None
    hue_sat_dims: Optional[List[int]] = None         # 0xC6F9 ProfileHueSatMapDims
    hue_sat_encoding: Optional[int] = None           # 0=线性, 1=sRGB (0xC6FC/0xC7A3/0xC7A4; 联合形态缺省 1)
    look_table: Optional[List[float]] = None         # 0xC726 ProfileLookTableData
    look_table_dims: Optional[List[int]] = None      # 0xC725 官方语义 (LookTable dims)
    look_table_encoding: Optional[int] = None        # 0xC6FD
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
        elif tag == 0xC623:
            prof.camera_calibration1 = val if isinstance(val, list) else None
        elif tag == 0xC624:
            prof.camera_calibration2 = val if isinstance(val, list) else None
        elif tag == 0xC65A:
            prof.calibration_illuminant1 = int(val[0]) if isinstance(val, list) and val else 17
        elif tag == 0xC65B:
            prof.calibration_illuminant2 = int(val[0]) if isinstance(val, list) and val else 21
        elif tag == 0xC714:
            prof.forward_matrix1 = val if isinstance(val, list) else None
        elif tag == 0xC715:
            prof.forward_matrix2 = val if isinstance(val, list) else None
        elif tag == 0xC6F2:
            if isinstance(val, list):
                prof.tone_curve = val
                prof.profile_tone_curve = val
        elif tag == 0xC726:
            # Adobe Camera 系列 DCP: 0xC726 是 ProfileLookTableData, 不是 HueSatMap。
            if isinstance(val, list) and val:
                prof.look_table = val
        elif tag == 0xC6FA:
            if isinstance(val, list) and val:
                prof.hue_sat_map = val
                prof.hue_sat_map1 = val
        elif tag == 0xC6FC:
            # 本 DCP: 125 点 (x,y) 交错影调曲线 (数据形态判定: 250 float, 值域 0-1)。
            # 0xC6FC 正规含义是 ProfileHueSatMapEncoding (DNG 1.4 表 15, 值 0/1);
            # 若为有效 0/1 值则按 encoding 解析, 否则按历史兼容当影调曲线。
            if isinstance(val, list) and len(val) == 1 and val[0] in (0, 1):
                prof.hue_sat_encoding = int(val[0])
            elif isinstance(val, list) and len(val) >= 16 and max(val) <= 1.0:
                prof.profile_tone_curve = val
                prof.tone_curve = val
        elif tag == 0xC6FD:
            if isinstance(val, list) and len(val) == 1 and val[0] in (0, 1):
                prof.look_table_encoding = int(val[0])
        elif tag == 0xC7A3:
            if isinstance(val, list) and len(val) == 1 and val[0] in (0, 1):
                prof.hue_sat_encoding = int(val[0])
        elif tag == 0xC7A4:
            if isinstance(val, list) and len(val) == 1 and val[0] in (0, 1):
                prof.look_table_encoding = int(val[0])
        elif tag == 0xC7A5:
            # BaselineExposureOffset (0xC7A5 / 51109, SRATIONAL, 单位 EV)。
            #
            # 符号约定 (对齐 Adobe dng_negative::TotalBaselineExposure):
            #   total = BaselineExposure() + BaselineExposureOffset()
            #   渲染增益 = 2^total, 即偏移"加到"基线曝光指数上。
            #   故负值(本机 -0.15)使整体基线曝光更低 → 渲染乘以 2^(-0.15)≈0.90,
            #   比"无偏移"暗 0.15 EV。引擎 exposure Stage 以 ev += offset 应用, 符号一致。
            if isinstance(val, list) and val:
                prof.baseline_exposure_offset = float(val[0])
            elif isinstance(val, (int, float)):
                prof.baseline_exposure_offset = float(val)
        elif tag == 0xC6F9:
            prof.hue_sat_dims = [int(v) for v in val] if isinstance(val, list) and val else None
        elif tag == 0xC6FB:
            prof.hue_sat_map2 = val if isinstance(val, list) else None
        elif tag == 0xC725:
            dims = [int(v) for v in val] if isinstance(val, list) and val else None
            prof.look_table_dims = dims
        elif tag == 0xC6F8:
            # 勘误: 0xC6F8 实为 ProfileName (ASCII, 如 "Camera Standard"); 0xC614 优先。
            if isinstance(val, list):
                prof.look_table = val
            elif isinstance(val, str) and val and not prof.name:
                prof.name = val
    # 缺省 encoding: HueSatMap(0xC6FA) 缺省 linear(0); LookTable(0xC726)
    # 缺省 sRGB(1) (本机 Adobe Camera 系列 0xC7A4 恒为 1)。
    if prof.hue_sat_map is not None and prof.hue_sat_encoding is None:
        prof.hue_sat_encoding = 0
    if prof.look_table is not None and prof.look_table_encoding is None:
        prof.look_table_encoding = 1
    return prof


# ---------------------------------------------------------------------------
# DCP 写入 (最小 DNG Camera Profile 序列化, 与 load_dcp 往返兼容)
# ---------------------------------------------------------------------------

_RATIONAL_DEN = 10000  # 浮点 → 有理数分母 (量化误差 1e-4, DCP 精度足够)


def _to_srationals(vals: List[float]) -> List[int]:
    """float 列表 → SRATIONAL 分子/分母交错整数序列 (分母固定 10000)。"""
    out: List[int] = []
    for v in vals:
        out.append(int(round(float(v) * _RATIONAL_DEN)))
        out.append(_RATIONAL_DEN)
    return out


def _tiff_entry(endian: str, tag: int, typ: int, cnt: int, value_bytes: bytes) -> bytes:
    """构造一条 TIFF IFD entry (12 字节, ≤4 字节内联, 否则存 offset)。"""
    if len(value_bytes) <= 4:
        value_bytes = value_bytes.ljust(4, b"\x00")
        return struct.pack(endian + "HHI", tag, typ, cnt) + value_bytes
    return struct.pack(endian + "HHII", tag, typ, cnt, 0)  # offset 后补


def _validate_tone_curve_endpoint(curve: List[float]) -> None:
    """白→白契约 (03-specification.md §2): 曲线末点必须为 (1.0, 1.0), y(1.0) 必须为 1.0。

    违反时 raise ValueError (在写入前拦截), 防止生成无法正确渲染高光的 DCP。
    """
    if curve is None or len(curve) < 2:
        return
    x_last, y_last = float(curve[-2]), float(curve[-1])
    if abs(x_last - 1.0) > 1e-6:
        raise ValueError(
            f"profile_tone_curve 末点 x 必须为 1.0 (实际 {x_last!r}), 违反白→白契约")
    if abs(y_last - 1.0) > 1e-6:
        raise ValueError(
            f"profile_tone_curve 的 y(1.0) 必须为 1.0 (实际 {y_last!r}), 违反白→白契约")


def write_dcp(path: str | Path, prof: DcpProfile) -> None:
    """把 DcpProfile 序列化为二进制 DCP (TIFF 小端, 魔数 II*\0, 单 IFD)。

    写入标签 (类型按 DNG 1.4):
      ProfileCalibrationSignature (ASCII) / ProfileName (ASCII) /
      ProfileCopyright (ASCII) / ProfileEmbedPolicy (LONG 0=允许复制) /
      CalibrationIlluminant1/2 (SHORT) /
      ColorMatrix1/2 (SRATIONAL) / CameraCalibration1/2 (SRATIONAL) /
      ForwardMatrix1/2 (RATIONAL) /
      ProfileToneCurve (SRATIONAL, 0xC6F2; 兼容镜像 0xC6FC) + Dims (SHORT 0xC727) /
      BaselineExposureOffset (SRATIONAL 0xC7A5) /
      HueSatMap: 表 0xC6FA (FLOAT) + dims 0xC6F9 (SHORT) + encoding 0xC7A3 (SHORT) /
      LookTable: 表 0xC726 (FLOAT) + dims 0xC725 (SHORT) + encoding 0xC7A4 (SHORT)。
    约束: ProfileToneCurve 末点必须 (1.0, 1.0) (白→白契约, 违反 raise ValueError);
      hue_sat_map 存在时必须提供合法 hue_sat_dims (0xC6F9);
      look_table 存在时必须提供合法 look_table_dims (0xC725)。
    缺省字段跳过; 至少要有 ColorMatrix1 或 ForwardMatrix1 之一。
    """
    endian = "<"
    entries: Dict[int, Tuple[int, bytes]] = {}

    def add(tag: int, typ: int, fmt: str, values) -> None:
        if values is None or (isinstance(values, (list, tuple)) and not values):
            return
        if typ == 2:
            raw = (str(values) + "\x00").encode("latin1")
            entries[tag] = (typ, raw)
        elif typ in (3, 4):
            seq = values if isinstance(values, (list, tuple)) else [values]
            raw = b"".join(struct.pack(endian + fmt, int(v)) for v in seq)
            entries[tag] = (typ, raw)
        elif typ == 10:  # SRATIONAL (分子/分母交错, int32)
            seq = values if isinstance(values, (list, tuple)) else [values]
            flat = _to_srationals([float(x) for x in seq])
            raw = struct.pack(endian + "i" * len(flat), *flat)
            entries[tag] = (typ, raw)
        elif typ == 5:  # RATIONAL (分子/分母交错, uint32)
            seq = values if isinstance(values, (list, tuple)) else [values]
            flat = _to_srationals([float(x) for x in seq])
            raw = struct.pack(endian + "I" * len(flat), *flat)
            entries[tag] = (typ, raw)
        elif typ == 11:  # FLOAT (HueSatMap 0xC6FA / LookTable 0xC726, 直接 float32 序列化)
            seq = values if isinstance(values, (list, tuple)) else [values]
            raw = struct.pack(endian + "f" * len(seq), *(float(x) for x in seq))
            entries[tag] = (typ, raw)

    add(0xC612, 2, "", prof.calibration_signature or "com.adobe")
    add(0xC614, 2, "", prof.name or "RawLab Baseline")
    add(0xC6F4, 2, "", "RawLab fitted profile")
    add(0xC6F7, 4, "I", 0)
    add(0xC65A, 3, "H", prof.calibration_illuminant1)
    add(0xC65B, 3, "H", prof.calibration_illuminant2)
    add(0xC621, 10, "ii", prof.color_matrix1)
    add(0xC622, 10, "ii", prof.color_matrix2)
    add(0xC623, 10, "ii", prof.camera_calibration1)
    add(0xC624, 10, "ii", prof.camera_calibration2)
    add(0xC714, 5, "II", prof.forward_matrix1)
    add(0xC715, 5, "II", prof.forward_matrix2)
    curve = prof.profile_tone_curve or prof.tone_curve
    if curve is not None and len(curve) >= 16:
        _validate_tone_curve_endpoint(curve)
        add(0xC6F2, 10, "ii", curve)
        add(0xC6FC, 10, "ii", curve)  # 兼容镜像 (本机 Adobe DCP 的曲线所在 tag)
        add(0xC727, 3, "H", len(curve) // 2)
    add(0xC7A5, 10, "ii", prof.baseline_exposure_offset)

    # ---- DNG 1.4: HueSatMapData1 0xC6FA + dims 0xC6F9 + encoding 0xC7A3 ----
    if prof.hue_sat_map is not None and len(prof.hue_sat_map):
        dims = prof.hue_sat_dims
        if not dims or len(dims) < 3 or min(int(v) for v in dims) < 2:
            raise ValueError(
                f"hue_sat_map 存在时必须提供合法 hue_sat_dims (0xC6F9), 实际 {dims!r}")
        h, s, v = int(dims[0]), int(dims[1]), int(dims[2])
        if len(prof.hue_sat_map) != h * s * v * 3:
            raise ValueError(
                f"hue_sat_map 长度 {len(prof.hue_sat_map)} 与 dims {dims} 要求的 {h * s * v * 3} 不符")
        add(0xC6FA, 11, "f", prof.hue_sat_map)
        add(0xC6F9, 3, "H", dims)
        add(0xC7A3, 3, "H", prof.hue_sat_encoding if prof.hue_sat_encoding is not None else 0)

    # ---- LookTable: 0xC726 + dims 0xC725 + encoding 0xC7A4 ----
    if prof.look_table is not None and len(prof.look_table):
        dims = prof.look_table_dims
        if not dims or len(dims) < 3 or min(int(v) for v in dims) < 2:
            raise ValueError(
                f"look_table 存在时必须提供合法 look_table_dims (0xC725), 实际 {dims!r}")
        h, s, v = int(dims[0]), int(dims[1]), int(dims[2])
        if len(prof.look_table) != h * s * v * 3:
            raise ValueError(
                f"look_table 长度 {len(prof.look_table)} 与 dims {dims} 要求的 {h * s * v * 3} 不符")
        add(0xC726, 11, "f", prof.look_table)
        add(0xC725, 3, "H", dims)
        add(0xC7A4, 3, "H", prof.look_table_encoding if prof.look_table_encoding is not None else 1)

    # ---- 布局: header(8) + IFD + 外置数据块 ----
    n = len(entries)
    ifd_offset = 8
    ifd_size = 2 + n * 12 + 4
    body_offset = ifd_offset + ifd_size
    body = bytearray()
    entry_bytes = bytearray()
    for tag in sorted(entries):
        typ, raw = entries[tag]
        cnt = len(raw) // {2: 1, 3: 2, 4: 4, 5: 8, 10: 8, 11: 4}[typ]
        if len(raw) <= 4:
            entry_bytes += _tiff_entry(endian, tag, typ, cnt, raw)
        else:
            off = body_offset + len(body)
            body += raw
            if len(body) % 2:
                body += b"\x00"
            entry_bytes += struct.pack(endian + "HHII", tag, typ, cnt, off)
    out = struct.pack(endian + "HHI", 0x4949, 42, ifd_offset)
    out += struct.pack(endian + "H", n)
    out += bytes(entry_bytes)
    out += struct.pack(endian + "I", 0)  # 无子 IFD
    out += bytes(body)
    Path(path).write_bytes(out)


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
