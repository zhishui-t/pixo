"""test_dcp_writer —— DCP 二进制写入器往返测试 (dcp.write_dcp ↔ dcp.load_dcp)。

覆盖:
  - 矩阵/曲线/BEO 往返 (原有)
  - HueSatMap (0xC6FA/0xC6F9/0xC7A3) 与 LookTable (0xC726/0xC725/0xC7A4) 往返
  - load 侧标签勘误: 0xC6F8=ProfileName, 0xC726=ProfileLookTableData,
    0xC725=ProfileLookTableDims, 0xC7A4=ProfileLookTableEncoding,
    0xC6FA=ProfileHueSatMapData1, 0xC6F9=ProfileHueSatMapDims, 0xC7A3=ProfileHueSatMapEncoding
  - 曲线白→白契约: y(1.0) 必须为 1.0, 否则写入前 ValueError
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from rawlab.dcp import DcpProfile, load_dcp, write_dcp
from rawlab.engine.curves import parse_profile_curve

_H, _S, _V = 90, 16, 16  # Adobe Camera 系列联合形态 HueSatMap dims


def _make_profile(tmp_path: Path) -> DcpProfile:
    p = DcpProfile(path=tmp_path / "out.dcp")
    p.name = "RawLab Test Profile"
    p.calibration_signature = "com.adobe"
    p.color_matrix1 = [1.1643, -0.653, 0.0726, -0.4355, 1.2179, 0.2449,
                       -0.0231, 0.0811, 0.7571]
    p.color_matrix2 = [0.6, -0.3, 0.05, -0.2, 1.1, 0.1, -0.01, 0.05, 0.8]
    p.camera_calibration1 = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    p.camera_calibration2 = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    p.forward_matrix1 = [0.7, 0.1, 0.1, 0.1, 0.8, 0.1, 0.05, 0.05, 0.9]
    p.forward_matrix2 = [0.6, 0.2, 0.1, 0.1, 0.7, 0.2, 0.0, 0.1, 0.8]
    p.calibration_illuminant1 = 17
    p.calibration_illuminant2 = 21
    p.baseline_exposure_offset = -0.15
    xs = np.linspace(0.0, 1.0, 125)
    ys = np.clip(np.power(xs, 0.85), 0.0, 1.0)
    p.profile_tone_curve = list(np.ravel(np.stack([xs, ys], axis=1)))
    return p


def _identity_hsm(h: int = _H, s: int = _S, v: int = _V) -> list:
    """恒等 HueSatMap 表: 每个格点 (hue_shift=0, sat_scale=1, val_scale=1), 共 h*s*v*3 值。"""
    return [0.0, 1.0, 1.0] * (h * s * v)


def _random_hsm(rng: np.random.Generator, h: int = _H, s: int = _S, v: int = _V) -> list:
    """随机 HueSatMap 表 (hue_shift/sat_scale/val_scale 交错), 覆盖典型值域。"""
    return list(rng.uniform(-0.5, 2.0, h * s * v * 3))


def _minimal_dcp(path: Path, entries) -> None:
    """构造最小 DCP (TIFF 头 + 单 IFD)。entries = [(tag, typ, fmt, values), ...];

    fmt="raw" 时 values 为已打包 bytes (ASCII), 否则按 fmt 逐个 pack。
    """
    endian = "<"
    packed = []
    for tag, typ, fmt, values in entries:
        if fmt == "raw":
            raw = values
            cnt = len(raw)
        else:
            raw = struct.pack(endian + fmt * len(values), *values)
            cnt = len(values)
        packed.append((tag, typ, cnt, raw))
    n = len(packed)
    body_offset = 8 + 2 + n * 12 + 4
    body = bytearray()
    out = struct.pack(endian + "HHI", 0x4949, 42, 8)
    out += struct.pack(endian + "H", n)
    for tag, typ, cnt, raw in packed:
        if len(raw) <= 4:
            out += struct.pack(endian + "HHI", tag, typ, cnt) + raw.ljust(4, b"\x00")
        else:
            off = body_offset + len(body)
            body += raw
            out += struct.pack(endian + "HHII", tag, typ, cnt, off)
    out += struct.pack(endian + "I", 0)
    out += bytes(body)
    path.write_bytes(out)


# ---------------------------------------------------------------------------
# 原有: 矩阵 / 曲线 / 最小往返
# ---------------------------------------------------------------------------

def test_roundtrip_matrices(tmp_path):
    p = _make_profile(tmp_path)
    write_dcp(p.path, p)
    rt = load_dcp(p.path)
    assert rt.name == "RawLab Test Profile"
    assert rt.calibration_signature == "com.adobe"
    assert np.allclose(rt.color_matrix1, p.color_matrix1, atol=1e-4)
    assert np.allclose(rt.color_matrix2, p.color_matrix2, atol=1e-4)
    assert np.allclose(rt.camera_calibration1, p.camera_calibration1, atol=1e-4)
    assert np.allclose(rt.forward_matrix1, p.forward_matrix1, atol=1e-4)
    assert np.allclose(rt.forward_matrix2, p.forward_matrix2, atol=1e-4)
    assert rt.calibration_illuminant1 == 17
    assert rt.calibration_illuminant2 == 21
    assert abs(rt.baseline_exposure_offset - (-0.15)) < 1e-4


def test_roundtrip_tone_curve(tmp_path):
    p = _make_profile(tmp_path)
    write_dcp(p.path, p)
    rt = load_dcp(p.path)
    xs, ys = parse_profile_curve(rt.profile_tone_curve)
    assert xs is not None and len(xs) == 125
    assert np.all(np.diff(xs) > 0) and np.all(np.diff(ys) >= 0)  # 单调
    assert xs[0] >= 0.0 and xs[-1] <= 1.0 and ys.max() <= 1.0
    # 与写入曲线近似一致 (SRATIONAL 量化误差 ≤ 1e-4)
    orig = np.array(p.profile_tone_curve)
    assert np.abs(np.array(rt.profile_tone_curve) - orig).max() < 1e-4


def test_roundtrip_missing_optional(tmp_path):
    p = DcpProfile(path=tmp_path / "min.dcp")
    p.name = "minimal"
    p.color_matrix1 = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    write_dcp(p.path, p)
    rt = load_dcp(p.path)
    assert rt.name == "minimal"
    assert rt.color_matrix2 is None and rt.forward_matrix1 is None
    assert rt.profile_tone_curve is None


# ---------------------------------------------------------------------------
# HueSatMap (0xC6FA/0xC6F9/0xC7A3) 与 LookTable (0xC726/0xC725/0xC7A4) 往返
# ---------------------------------------------------------------------------

def test_roundtrip_hue_sat_map_identity(tmp_path):
    p = _make_profile(tmp_path)
    p.hue_sat_map = _identity_hsm()
    p.hue_sat_dims = [_H, _S, _V]
    p.hue_sat_encoding = 1
    write_dcp(p.path, p)
    rt = load_dcp(p.path)
    assert rt.hue_sat_dims == [_H, _S, _V]
    assert rt.hue_sat_encoding == 1
    assert rt.hue_sat_map is not None and len(rt.hue_sat_map) == _H * _S * _V * 3
    # FLOAT 直接序列化: (0,1,1) 恒等表逐元素精确往返
    assert np.abs(np.array(rt.hue_sat_map) - np.array(p.hue_sat_map)).max() <= 1e-4
    assert np.array_equal(np.array(rt.hue_sat_map), np.array(p.hue_sat_map))


def test_roundtrip_hue_sat_map_random(tmp_path):
    p = _make_profile(tmp_path)
    rng = np.random.default_rng(42)
    p.hue_sat_map = _random_hsm(rng)
    p.hue_sat_dims = [_H, _S, _V]
    p.hue_sat_encoding = 1
    write_dcp(p.path, p)
    rt = load_dcp(p.path)
    assert rt.hue_sat_dims == [_H, _S, _V]
    assert rt.hue_sat_encoding == 1
    assert rt.hue_sat_map is not None and len(rt.hue_sat_map) == len(p.hue_sat_map)
    assert np.abs(np.array(rt.hue_sat_map) - np.array(p.hue_sat_map)).max() <= 1e-4


def test_roundtrip_hue_sat_encoding_linear(tmp_path):
    p = _make_profile(tmp_path)
    p.hue_sat_map = _identity_hsm()
    p.hue_sat_dims = [_H, _S, _V]
    p.hue_sat_encoding = 0
    write_dcp(p.path, p)
    rt = load_dcp(p.path)
    assert rt.hue_sat_encoding == 0
    assert rt.hue_sat_dims == [_H, _S, _V]


def test_roundtrip_hue_sat_encoding_default_linear(tmp_path):
    # encoding=None → 写入 0xC7A3=0 (linear 缺省), 往返一致
    p = _make_profile(tmp_path)
    p.hue_sat_map = _identity_hsm()
    p.hue_sat_dims = [_H, _S, _V]
    p.hue_sat_encoding = None
    write_dcp(p.path, p)
    rt = load_dcp(p.path)
    assert rt.hue_sat_encoding == 0
    assert rt.hue_sat_dims == [_H, _S, _V]


def test_roundtrip_look_table_identity(tmp_path):
    p = _make_profile(tmp_path)
    p.look_table = _identity_hsm()
    p.look_table_dims = [_H, _S, _V]
    p.look_table_encoding = 1
    write_dcp(p.path, p)
    rt = load_dcp(p.path)
    assert rt.look_table_dims == [_H, _S, _V]
    assert rt.look_table_encoding == 1
    assert rt.look_table is not None and len(rt.look_table) == _H * _S * _V * 3
    assert np.array_equal(np.array(rt.look_table), np.array(p.look_table))


def test_roundtrip_look_table_encoding_default_srgb(tmp_path):
    # encoding=None → 写入 0xC7A4=1 (sRGB 缺省), 往返一致
    p = _make_profile(tmp_path)
    p.look_table = _identity_hsm()
    p.look_table_dims = [_H, _S, _V]
    p.look_table_encoding = None
    write_dcp(p.path, p)
    rt = load_dcp(p.path)
    assert rt.look_table_encoding == 1
    assert rt.look_table_dims == [_H, _S, _V]
    assert rt.look_table is not None and len(rt.look_table) == len(p.look_table)


def test_write_hue_sat_map_requires_dims(tmp_path):
    p = _make_profile(tmp_path)
    p.hue_sat_map = _identity_hsm()
    p.hue_sat_dims = None
    with pytest.raises(ValueError, match="hue_sat_dims"):
        write_dcp(p.path, p)


def test_write_hue_sat_map_dims_mismatch(tmp_path):
    p = _make_profile(tmp_path)
    p.hue_sat_map = _identity_hsm(90, 16, 16)
    p.hue_sat_dims = [90, 16, 8]  # 长度不符 (90*16*8*3 != 90*16*16*3)
    with pytest.raises(ValueError, match="不符"):
        write_dcp(p.path, p)


# ---------------------------------------------------------------------------
# load 侧标签勘误: 0xC726=LookTable, 0xC6FA=HueSatMap
# ---------------------------------------------------------------------------

def test_load_profile_name_from_c6f8(tmp_path):
    table = _identity_hsm()
    p = tmp_path / "Nikon Z 5 2 Camera Standard.dcp"
    _minimal_dcp(p, [
        (0xC726, 11, "f", table),
        (0xC725, 3, "H", [_H, _S, _V]),
        (0xC6F8, 2, "raw", b"Camera Standard\x00"),
    ])
    prof = load_dcp(p)
    assert prof.name == "Camera Standard"          # 0xC6F8 实为 ProfileName
    assert prof.look_table is not None and len(prof.look_table) == len(table)
    assert prof.look_table_dims == [_H, _S, _V]
    assert prof.look_table_encoding == 1           # 有 LookTable 数据但缺 encoding → 1 (sRGB)
    assert prof.hue_sat_map is None
    assert prof.hue_sat_dims is None


def test_load_look_table_encoding_default_srgb_nikon(tmp_path):
    table = _identity_hsm()
    p = tmp_path / "Nikon Z 5 2 Camera Standard.dcp"
    _minimal_dcp(p, [
        (0xC726, 11, "f", table),
        (0xC725, 3, "H", [_H, _S, _V]),
    ])
    prof = load_dcp(p)
    assert prof.look_table is not None and len(prof.look_table) == len(table)
    assert prof.look_table_dims == [_H, _S, _V]
    assert prof.look_table_encoding == 1
    assert prof.hue_sat_map is None


def test_load_look_table_encoding_default_srgb_generic(tmp_path):
    # 0xC726 (LookTable 数据) 缺 0xC7A4 → 按 1 (sRGB) 缺省, 不依赖 Nikon 特判
    table = _identity_hsm()
    p = tmp_path / "generic_profile.dcp"
    _minimal_dcp(p, [
        (0xC726, 11, "f", table),
        (0xC725, 3, "H", [_H, _S, _V]),
    ])
    prof = load_dcp(p)
    assert prof.look_table is not None
    assert prof.look_table_dims == [_H, _S, _V]
    assert prof.look_table_encoding == 1


def test_load_look_table_encoding_from_c7a4(tmp_path):
    table = _identity_hsm()
    p = tmp_path / "Nikon Z 5 2 Camera Standard.dcp"
    _minimal_dcp(p, [
        (0xC726, 11, "f", table),
        (0xC725, 3, "H", [_H, _S, _V]),
        (0xC7A4, 3, "H", [1]),
    ])
    prof = load_dcp(p)
    assert prof.look_table is not None
    assert prof.look_table_dims == [_H, _S, _V]
    assert prof.look_table_encoding == 1


def test_load_hue_sat_map_from_c6fa(tmp_path):
    table = _identity_hsm()
    p = tmp_path / "hue_sat_only.dcp"
    _minimal_dcp(p, [
        (0xC6FA, 11, "f", table),
        (0xC6F9, 3, "H", [_H, _S, _V]),
        (0xC7A3, 3, "H", [1]),
    ])
    prof = load_dcp(p)
    assert prof.hue_sat_map is not None and len(prof.hue_sat_map) == len(table)
    assert prof.hue_sat_dims == [_H, _S, _V]
    assert prof.hue_sat_encoding == 1
    assert prof.look_table is None


def test_load_hue_sat_encoding_default_linear(tmp_path):
    # 有 HueSatMap 数据但缺 encoding → 0 (linear)
    table = _identity_hsm()
    p = tmp_path / "hue_sat_default.dcp"
    _minimal_dcp(p, [
        (0xC6FA, 11, "f", table),
        (0xC6F9, 3, "H", [_H, _S, _V]),
    ])
    prof = load_dcp(p)
    assert prof.hue_sat_map is not None
    assert prof.hue_sat_dims == [_H, _S, _V]
    assert prof.hue_sat_encoding == 0


def test_load_encoding_no_default_without_data(tmp_path):
    # 只有 dims 而没有对应数据表时, 不做 encoding 缺省
    p = tmp_path / "dims_only.dcp"
    _minimal_dcp(p, [
        (0xC725, 3, "H", [_H, _S, _V]),
        (0xC6F9, 3, "H", [_H, _S, _V]),
        (0xC6F2, 10, "i", [0, 0, 1, 1]),
    ])
    prof = load_dcp(p)
    assert prof.look_table is None
    assert prof.look_table_encoding is None
    assert prof.look_table_dims == [_H, _S, _V]
    assert prof.hue_sat_map is None
    assert prof.hue_sat_encoding is None
    assert prof.hue_sat_dims == [_H, _S, _V]


def test_tag_names_errata():
    """low#2: 0xC726 标注官方名 ProfileLookTableData (联合形态约定写入注释);
    0xC728 不再误标 ProfileLookTableDims (注明待考); 0xC725 保留 dims 名。"""
    from rawlab.dcp import _TAG_NAMES
    assert _TAG_NAMES[0xC726] == "ProfileLookTableData"
    assert _TAG_NAMES[0xC728] == "ProfileToneCurveData"   # 官方名 (存疑待考标注)
    assert _TAG_NAMES[0xC725] == "ProfileLookTableDims"   # 未被 0xC728 占用
    # 联合形态语义: 0xC726 表 + 0xC725 dims + 0xC7A4 encoding
    assert _TAG_NAMES[0xC7A4] == "ProfileLookTableEncoding"


# ---------------------------------------------------------------------------
# 新增: 曲线白→白契约 (y(1.0) 必须为 1.0)
# ---------------------------------------------------------------------------

def test_write_curve_endpoint_y_must_be_one(tmp_path):
    p = _make_profile(tmp_path)
    curve = list(p.profile_tone_curve)
    curve[-1] = 0.99  # 破坏 y(1.0)
    p.profile_tone_curve = curve
    with pytest.raises(ValueError, match=r"y\(1\.0\)"):
        write_dcp(p.path, p)


def test_write_curve_endpoint_x_must_be_one(tmp_path):
    p = _make_profile(tmp_path)
    curve = list(p.profile_tone_curve)
    curve[-2] = 0.9999  # 末点 x 不为 1.0
    p.profile_tone_curve = curve
    with pytest.raises(ValueError, match="末点 x"):
        write_dcp(p.path, p)
