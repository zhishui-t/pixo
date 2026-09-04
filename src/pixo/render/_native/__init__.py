"""pixo.render native C++ kernels (MinGW DLL, loaded via ctypes).

当前提供:
  - rgb_to_hsv / hsv_to_rgb: float64 全图 HSV 转换, 对齐 render/core/huesat.py
    的 NumPy 实现 (用于 apply_local_warm_sat 热点)。
  - rgb_to_hsv_f32 / hsv_to_rgb_f32: float32 版本。
  - apply_local_warm_sat_native: M1 broad 分支整段内核。
  - colorcal_apply_lab_f32: colorcal 全量 Lab float 域内核 (v1.2.0, 生产路径);
    colorcal_apply_lab (uint8 Lab 域) 为兼容保留。
  - lut3d_apply_f32: stylize 3D LUT 四面体插值 float 内核 (v1.3.0, 生产路径,
    逐位对齐 lut3d.lookup 的 float32 语义)。
  - srgb_to_oklab_f32 / oklab_to_srgb_f32: Oklab F32 平面版转换内核 (v1.4.0),
    逐位对齐 core.oklab (sRGB 侧 float32, L/a/b 平面 float64, 设计 §1.3);
    srgb_to_oklab / oklab_to_srgb 为带 numpy 回退的便捷封装。
  - version: ABI 版本查询 (major==1 才视为可用)。

若 DLL 不存在或加载失败, 本模块保持可导入, 由调用方回退纯 Python。
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

import numpy as np

_DLL_NAME = "pixo_render_native.dll"
_DLL_PATH = Path(__file__).parent / _DLL_NAME

# MinGW-w64 运行库目录; 若 DLL 依赖的 libgcc_s_seh-1.dll / libstdc++-6.dll
# 不在系统 PATH 中, 先把它加入 DLL 搜索路径 (Windows 10 1809+ 支持)。
_MINGW_BIN = Path(r"D:\code\mingw64\bin")


def _add_dll_search_path() -> None:
    if os.name != "nt" or not hasattr(os, "add_dll_directory"):
        return
    if _MINGW_BIN.exists():
        try:
            os.add_dll_directory(str(_MINGW_BIN))
        except Exception:
            pass


_add_dll_search_path()


class PixoRenderWarmSatParams(ctypes.Structure):
    _fields_ = [
        ("satScale", ctypes.c_float),
        ("spotSatScale", ctypes.c_float),
        ("hueCenter", ctypes.c_float),
        ("hueHalfwidth", ctypes.c_float),
        ("satMin", ctypes.c_float),
        ("valMin", ctypes.c_float),
        ("coverageMax", ctypes.c_float),
        ("contrastSigmaFrac", ctypes.c_float),
        ("contrastThr", ctypes.c_float),
        ("contrastSoft", ctypes.c_float),
    ]


class PixoRenderVersion(ctypes.Structure):
    _fields_ = [
        ("major", ctypes.c_int),
        ("minor", ctypes.c_int),
        ("patch", ctypes.c_int),
    ]


class PixoRenderColorCalParams(ctypes.Structure):
    _fields_ = [
        ("saturation", ctypes.c_float),
        ("vibrance", ctypes.c_float),
        ("hueDeg", ctypes.c_float),
        ("neutralA", ctypes.c_float),
        ("neutralB", ctypes.c_float),
        ("neutralSigma", ctypes.c_float),
        ("skinProtect", ctypes.c_float),
        ("skinTrimA", ctypes.c_float),
        ("skinTrimB", ctypes.c_float),
        ("curveA", ctypes.POINTER(ctypes.c_float)),
        ("curveB", ctypes.POINTER(ctypes.c_float)),
    ]


class PixoRenderRefineSatProtectionParams(ctypes.Structure):
    _fields_ = [
        ("lo", ctypes.c_float),
        ("hi", ctypes.c_float),
    ]


class PixoRenderRefineSharpenParams(ctypes.Structure):
    _fields_ = [
        ("sharpen", ctypes.c_float),
        ("gray", ctypes.POINTER(ctypes.c_float)),
        ("satProtect", ctypes.POINTER(ctypes.c_float)),
        ("grayBlur", ctypes.POINTER(ctypes.c_float)),
    ]


class PixoRenderRefineChromaParams(ctypes.Structure):
    _fields_ = [
        ("chromaDenoise", ctypes.c_float),
        ("gray", ctypes.POINTER(ctypes.c_float)),
        ("satProtect", ctypes.POINTER(ctypes.c_float)),
        ("blurUp", ctypes.POINTER(ctypes.c_float)),
        ("grayBlurUp", ctypes.POINTER(ctypes.c_float)),
    ]


class PixoRenderRefineHighlightParams(ctypes.Structure):
    _fields_ = [
        ("highlightDesat", ctypes.c_float),
        ("gray", ctypes.POINTER(ctypes.c_float)),
        ("satProtect", ctypes.POINTER(ctypes.c_float)),
    ]


class PixoRenderRefineApplyParams(ctypes.Structure):
    _fields_ = [
        ("sharpen", ctypes.c_float),
        ("chromaDenoise", ctypes.c_float),
        ("highlightDesat", ctypes.c_float),
        ("gray", ctypes.POINTER(ctypes.c_float)),
        ("satProtect", ctypes.POINTER(ctypes.c_float)),
        ("grayBlur", ctypes.POINTER(ctypes.c_float)),
        ("blurUp", ctypes.POINTER(ctypes.c_float)),
        ("grayBlurUp", ctypes.POINTER(ctypes.c_float)),
    ]


class PixoRenderWarmGammaParams(ctypes.Structure):
    _fields_ = [
        ("gain", ctypes.c_float),
        ("hueShiftDeg", ctypes.c_float),
    ]


class PixoRenderCfaDecodeParams(ctypes.Structure):
    _fields_ = [
        ("patternR", ctypes.c_int),
        ("patternG0", ctypes.c_int),
        ("patternG1", ctypes.c_int),
        ("patternB", ctypes.c_int),
        ("black", ctypes.c_float * 4),
        ("whiteLevel", ctypes.c_float),
        ("outputScale", ctypes.c_float),
    ]


class PixoRenderExposureParams(ctypes.Structure):
    _fields_ = [
        ("ev", ctypes.c_float),
        ("rolloffKnee", ctypes.c_float),
        ("vignette", ctypes.c_float),
    ]


class PixoRenderMatrixApply3Params(ctypes.Structure):
    _fields_ = [
        ("matrix", ctypes.POINTER(ctypes.c_float)),
    ]


class PixoRenderToneApplyLut1DParams(ctypes.Structure):
    _fields_ = [
        ("lut", ctypes.POINTER(ctypes.c_float)),
        ("lutSize", ctypes.c_int),
    ]


class PixoRenderClarityParams(ctypes.Structure):
    _fields_ = [
        ("strength", ctypes.c_float),
        ("gray", ctypes.POINTER(ctypes.c_float)),
        ("smallBlur", ctypes.POINTER(ctypes.c_float)),
        ("largeBlur", ctypes.POINTER(ctypes.c_float)),
    ]


class PixoRenderLut3DParams(ctypes.Structure):
    _fields_ = [
        ("lut", ctypes.POINTER(ctypes.c_float)),    # size^3 * 3, [r,g,b] 序
        ("size", ctypes.c_int),                     # N >= 2
        ("domainMin", ctypes.c_float),              # f32(DOMAIN_MIN)
        ("domainSpan", ctypes.c_float),             # f32(DOMAIN_MAX - DOMAIN_MIN)
        ("shaper", ctypes.POINTER(ctypes.c_float)), # 可选 1D LUT, None = 无
        ("shaperSize", ctypes.c_int),               # shaper 非空时 >= 2
        ("strength", ctypes.c_double),              # 0..1 混合 (f64 对齐 Python)
    ]


class PixoRenderSrgbToOklabParams(ctypes.Structure):
    """gamma sRGB f32 (H,W,3) -> Oklab f64 平面 L/a/b; stride 单位见字段注释。"""

    _fields_ = [
        ("rgb", ctypes.POINTER(ctypes.c_float)),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("stride", ctypes.c_int),        # rgb 行距 (float 元素数, >= width*3)
        ("l", ctypes.POINTER(ctypes.c_double)),
        ("a", ctypes.POINTER(ctypes.c_double)),
        ("b", ctypes.POINTER(ctypes.c_double)),
        ("planeStride", ctypes.c_int),   # L/a/b 行距 (double 元素数, >= width)
    ]


class PixoRenderOklabToSrgbParams(ctypes.Structure):
    """Oklab f64 平面 L/a/b -> gamma sRGB f32 (H,W,3)。"""

    _fields_ = [
        ("l", ctypes.POINTER(ctypes.c_double)),
        ("a", ctypes.POINTER(ctypes.c_double)),
        ("b", ctypes.POINTER(ctypes.c_double)),
        ("planeStride", ctypes.c_int),   # L/a/b 行距 (double 元素数, >= width)
        ("rgb", ctypes.POINTER(ctypes.c_float)),
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("stride", ctypes.c_int),        # rgb 行距 (float 元素数, >= width*3)
    ]


_lib = None
_load_error: str | None = None
_version: tuple[int, int, int] | None = None

if _DLL_PATH.exists():
    try:
        _lib = ctypes.CDLL(str(_DLL_PATH))
        _lib.PixoRenderRgbToHsv.restype = None
        _lib.PixoRenderRgbToHsv.argtypes = [
            ctypes.POINTER(ctypes.c_double),  # rgb
            ctypes.POINTER(ctypes.c_double),  # h
            ctypes.POINTER(ctypes.c_double),  # s
            ctypes.POINTER(ctypes.c_double),  # v
            ctypes.c_int64,                   # n
        ]
        _lib.PixoRenderHsvToRgb.restype = None
        _lib.PixoRenderHsvToRgb.argtypes = [
            ctypes.POINTER(ctypes.c_double),  # h
            ctypes.POINTER(ctypes.c_double),  # s
            ctypes.POINTER(ctypes.c_double),  # v
            ctypes.POINTER(ctypes.c_double),  # rgb
            ctypes.c_int64,                   # n
        ]
        _lib.PixoRenderRgbToHsvF32.restype = None
        _lib.PixoRenderRgbToHsvF32.argtypes = [
            ctypes.POINTER(ctypes.c_float),   # rgb
            ctypes.POINTER(ctypes.c_float),   # h
            ctypes.POINTER(ctypes.c_float),   # s
            ctypes.POINTER(ctypes.c_float),   # v
            ctypes.c_int64,                   # n
        ]
        _lib.PixoRenderHsvToRgbF32.restype = None
        _lib.PixoRenderHsvToRgbF32.argtypes = [
            ctypes.POINTER(ctypes.c_float),   # h
            ctypes.POINTER(ctypes.c_float),   # s
            ctypes.POINTER(ctypes.c_float),   # v
            ctypes.POINTER(ctypes.c_float),   # rgb
            ctypes.c_int64,                   # n
        ]
        _lib.PixoRenderApplyLocalWarmSat.restype = ctypes.c_int
        _lib.PixoRenderApplyLocalWarmSat.argtypes = [
            ctypes.POINTER(ctypes.c_float),   # rgb
            ctypes.POINTER(ctypes.c_float),   # out
            ctypes.c_int,                     # width
            ctypes.c_int,                     # height
            ctypes.POINTER(PixoRenderWarmSatParams),
        ]
        if hasattr(_lib, "PixoRenderApplyLocalWarmSatF64"):
            _lib.PixoRenderApplyLocalWarmSatF64.restype = ctypes.c_int
            _lib.PixoRenderApplyLocalWarmSatF64.argtypes = [
                ctypes.POINTER(ctypes.c_double),  # rgb
                ctypes.POINTER(ctypes.c_double),  # out
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderWarmSatParams),
            ]
        # M2/M3 可选内核: 旧 v1.0 DLL 尚未导出这些符号时不能导致整个 native
        # 不可用; 缺失时对应函数抛 RuntimeError, 由调用方回退纯 Python。
        if hasattr(_lib, "PixoRenderColorCalApplyLab"):
            _lib.PixoRenderColorCalApplyLab.restype = ctypes.c_int
            _lib.PixoRenderColorCalApplyLab.argtypes = [
                ctypes.POINTER(ctypes.c_float),   # lab (uint8 Lab 域, float 视图)
                ctypes.POINTER(ctypes.c_uint8),   # labOut
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderColorCalParams),
            ]
        # 1.2.0: colorcal float Lab 域内核 (cv2 float Lab: L∈[0,100], a/b 中心
        # 0, float32 入/出)。旧 v1.1 DLL 未导出时不影响加载, 调用方
        # (modules/color_cal.py) 回退纯 Python float 实现。
        if hasattr(_lib, "PixoRenderColorCalApplyLabF32"):
            _lib.PixoRenderColorCalApplyLabF32.restype = ctypes.c_int
            _lib.PixoRenderColorCalApplyLabF32.argtypes = [
                ctypes.POINTER(ctypes.c_float),   # lab (float Lab 域)
                ctypes.POINTER(ctypes.c_float),   # labOut (float Lab 域)
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderColorCalParams),
            ]
        if hasattr(_lib, "PixoRenderGamutSoft"):
            _lib.PixoRenderGamutSoft.restype = ctypes.c_int
            _lib.PixoRenderGamutSoft.argtypes = [
                ctypes.POINTER(ctypes.c_float),   # rgb
                ctypes.POINTER(ctypes.c_float),   # out
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.c_float,                   # strength
            ]
        if hasattr(_lib, "PixoRenderRefineSatProtection"):
            _lib.PixoRenderRefineSatProtection.restype = ctypes.c_int
            _lib.PixoRenderRefineSatProtection.argtypes = [
                ctypes.POINTER(ctypes.c_float),   # rgb
                ctypes.POINTER(ctypes.c_float),   # satProtect
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderRefineSatProtectionParams),
            ]
        if hasattr(_lib, "PixoRenderRefineSharpen"):
            _lib.PixoRenderRefineSharpen.restype = ctypes.c_int
            _lib.PixoRenderRefineSharpen.argtypes = [
                ctypes.POINTER(ctypes.c_float),   # rgb
                ctypes.POINTER(ctypes.c_float),   # out
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderRefineSharpenParams),
            ]
        if hasattr(_lib, "PixoRenderRefineChroma"):
            _lib.PixoRenderRefineChroma.restype = ctypes.c_int
            _lib.PixoRenderRefineChroma.argtypes = [
                ctypes.POINTER(ctypes.c_float),   # rgb
                ctypes.POINTER(ctypes.c_float),   # out
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderRefineChromaParams),
            ]
        if hasattr(_lib, "PixoRenderRefineHighlight"):
            _lib.PixoRenderRefineHighlight.restype = ctypes.c_int
            _lib.PixoRenderRefineHighlight.argtypes = [
                ctypes.POINTER(ctypes.c_float),   # rgb
                ctypes.POINTER(ctypes.c_float),   # out
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderRefineHighlightParams),
            ]
        if hasattr(_lib, "PixoRenderRefineApply"):
            _lib.PixoRenderRefineApply.restype = ctypes.c_int
            _lib.PixoRenderRefineApply.argtypes = [
                ctypes.POINTER(ctypes.c_float),   # rgb
                ctypes.POINTER(ctypes.c_float),   # out
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderRefineApplyParams),
            ]
        if hasattr(_lib, "PixoRenderWarmSatGammaU8"):
            _lib.PixoRenderWarmSatGammaU8.restype = ctypes.c_int
            _lib.PixoRenderWarmSatGammaU8.argtypes = [
                ctypes.POINTER(ctypes.c_uint8),   # hsv
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderWarmGammaParams),
            ]
        if hasattr(_lib, "PixoRenderDecodeCfaHalf"):
            _lib.PixoRenderDecodeCfaHalf.restype = ctypes.c_int
            _lib.PixoRenderDecodeCfaHalf.argtypes = [
                ctypes.POINTER(ctypes.c_uint16),  # cfa
                ctypes.POINTER(ctypes.c_float),   # rgbOut
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderCfaDecodeParams),
            ]
        if hasattr(_lib, "PixoRenderExposureApply"):
            _lib.PixoRenderExposureApply.restype = ctypes.c_int
            _lib.PixoRenderExposureApply.argtypes = [
                ctypes.POINTER(ctypes.c_float),   # rgb
                ctypes.POINTER(ctypes.c_float),   # out
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderExposureParams),
            ]
        if hasattr(_lib, "PixoRenderMatrixApply3"):
            _lib.PixoRenderMatrixApply3.restype = ctypes.c_int
            _lib.PixoRenderMatrixApply3.argtypes = [
                ctypes.POINTER(ctypes.c_float),   # rgb
                ctypes.POINTER(ctypes.c_float),   # out
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderMatrixApply3Params),
            ]
        if hasattr(_lib, "PixoRenderToneApplyLut1D"):
            _lib.PixoRenderToneApplyLut1D.restype = ctypes.c_int
            _lib.PixoRenderToneApplyLut1D.argtypes = [
                ctypes.POINTER(ctypes.c_float),   # rgb
                ctypes.POINTER(ctypes.c_float),   # out
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderToneApplyLut1DParams),
            ]
        if hasattr(_lib, "PixoRenderClarityApply"):
            _lib.PixoRenderClarityApply.restype = ctypes.c_int
            _lib.PixoRenderClarityApply.argtypes = [
                ctypes.POINTER(ctypes.c_float),   # rgb
                ctypes.POINTER(ctypes.c_float),   # out
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderClarityParams),
            ]
        # 1.3.0: stylize LUT3D 四面体插值 float 内核 (对齐 lut3d.lookup 的
        # float32 语义)。旧 v1.2 DLL 未导出时不影响加载, 调用方
        # (core/lut3d.py apply_f32) 回退纯 numpy lookup 实现。
        if hasattr(_lib, "PixoRenderLut3DApplyF32"):
            _lib.PixoRenderLut3DApplyF32.restype = ctypes.c_int
            _lib.PixoRenderLut3DApplyF32.argtypes = [
                ctypes.POINTER(ctypes.c_float),   # rgb
                ctypes.POINTER(ctypes.c_float),   # out
                ctypes.c_int,                     # width
                ctypes.c_int,                     # height
                ctypes.POINTER(PixoRenderLut3DParams),
            ]
        # 1.4.0: Oklab F32 平面版转换内核 (与 core/oklab.py 逐位一致, 设计
        # §2.4)。旧 v1.3 DLL 未导出时不影响加载, 便捷封装回退纯 numpy 实现。
        if hasattr(_lib, "PixoRenderSrgbToOklabF32"):
            _lib.PixoRenderSrgbToOklabF32.restype = ctypes.c_int
            _lib.PixoRenderSrgbToOklabF32.argtypes = [
                ctypes.POINTER(PixoRenderSrgbToOklabParams),
            ]
        if hasattr(_lib, "PixoRenderOklabToSrgbF32"):
            _lib.PixoRenderOklabToSrgbF32.restype = ctypes.c_int
            _lib.PixoRenderOklabToSrgbF32.argtypes = [
                ctypes.POINTER(PixoRenderOklabToSrgbParams),
            ]

        # ABI 版本检查：v1.0 旧 DLL 没有 PixoRenderVersion 符号时容忍加载,
        # 但 version() 返回 None；major != 1 按不可用处理。
        if hasattr(_lib, "PixoRenderVersion"):
            _lib.PixoRenderVersion.restype = ctypes.c_int
            _lib.PixoRenderVersion.argtypes = [ctypes.POINTER(PixoRenderVersion)]
            _version_buf = PixoRenderVersion()
            _status = _lib.PixoRenderVersion(ctypes.byref(_version_buf))
            if _status == 0 and _version_buf.major == 1:
                _version = (_version_buf.major, _version_buf.minor,
                            _version_buf.patch)
            else:
                _lib = None
                _load_error = (
                    f"native ABI version check failed: status={_status}, "
                    f"version=({_version_buf.major},{_version_buf.minor},"
                    f"{_version_buf.patch})"
                )
    except Exception as e:  # pragma: no cover - depends on runtime env
        _lib = None
        _load_error = f"{type(e).__name__}: {e}"
else:
    _load_error = f"native DLL not found: {_DLL_PATH}"


def available() -> bool:
    return _lib is not None


def load_error() -> str | None:
    return _load_error


def version() -> tuple[int, int, int] | None:
    """返回 ABI 版本 (major, minor, patch)；旧 v1.0 无版本符号时返回 None。"""
    return _version


def _require_lib():
    if _lib is None:
        raise RuntimeError(f"native DLL unavailable: {_load_error}")


def _check_status(status: int):
    """负状态码按不可恢复错误抛出；状态 1 由调用方决定是否回退。"""
    if status < 0:
        raise RuntimeError(f"native status {status}")


def rgb_to_hsv(rgb: np.ndarray):
    """返回 (h, s, v), 与 render.core.huesat._rgb_to_hsv 语义一致 (float64)。"""
    _require_lib()
    arr = np.ascontiguousarray(rgb, dtype=np.float64)
    if arr.ndim < 1 or arr.shape[-1] != 3:
        raise ValueError(f"rgb 须为 (...,3), 实际 {arr.shape}")
    n = arr.size // 3
    h = np.empty(arr.shape[:-1], dtype=np.float64)
    s = np.empty(arr.shape[:-1], dtype=np.float64)
    v = np.empty(arr.shape[:-1], dtype=np.float64)
    _lib.PixoRenderRgbToHsv(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        h.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        s.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        v.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        ctypes.c_int64(n),
    )
    return h, s, v


def hsv_to_rgb(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    """返回 RGB (...,3), 与 render.core.huesat._hsv_to_rgb 语义一致 (float64)。"""
    _require_lib()
    h = np.ascontiguousarray(h, dtype=np.float64)
    s = np.ascontiguousarray(s, dtype=np.float64)
    v = np.ascontiguousarray(v, dtype=np.float64)
    if not (h.shape == s.shape == v.shape):
        raise ValueError("h/s/v shape 必须一致")
    n = h.size
    rgb = np.empty((*h.shape, 3), dtype=np.float64)
    _lib.PixoRenderHsvToRgb(
        h.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        s.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        v.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        rgb.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        ctypes.c_int64(n),
    )
    return rgb


def rgb_to_hsv_f32(rgb: np.ndarray):
    """float32 版 rgb_to_hsv, 用于 apply_local_warm_sat 等现有 float32 路径。"""
    _require_lib()
    arr = np.ascontiguousarray(rgb, dtype=np.float32)
    if arr.ndim < 1 or arr.shape[-1] != 3:
        raise ValueError(f"rgb 须为 (...,3), 实际 {arr.shape}")
    n = arr.size // 3
    h = np.empty(arr.shape[:-1], dtype=np.float32)
    s = np.empty(arr.shape[:-1], dtype=np.float32)
    v = np.empty(arr.shape[:-1], dtype=np.float32)
    _lib.PixoRenderRgbToHsvF32(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        h.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        s.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        v.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        ctypes.c_int64(n),
    )
    return h, s, v


def hsv_to_rgb_f32(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    """float32 版 hsv_to_rgb, 用于 apply_local_warm_sat 等现有 float32 路径。"""
    _require_lib()
    h = np.ascontiguousarray(h, dtype=np.float32)
    s = np.ascontiguousarray(s, dtype=np.float32)
    v = np.ascontiguousarray(v, dtype=np.float32)
    if not (h.shape == s.shape == v.shape):
        raise ValueError("h/s/v shape 必须一致")
    n = h.size
    rgb = np.empty((*h.shape, 3), dtype=np.float32)
    _lib.PixoRenderHsvToRgbF32(
        h.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        s.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        v.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        rgb.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        ctypes.c_int64(n),
    )
    return rgb


def decode_cfa_half(cfa: np.ndarray, pattern_r: int, pattern_g0: int,
                    pattern_g1: int, pattern_b: int, black,
                    white_level: float,
                    output_scale: float = 1.0) -> np.ndarray:
    """调用 C++ CFA 2×2 分箱解码；返回 float32 RGB (H/2, W/2, 3)。

    black 为长度 4 的序列，已按 2x2 线性位置换算（不是 rawpy 原始 color id 顺序）。
    """
    _require_lib()
    if not hasattr(_lib, "PixoRenderDecodeCfaHalf"):
        raise RuntimeError("native decode kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(cfa, dtype=np.uint16)
    if arr.ndim != 2:
        raise ValueError(f"cfa 须为 (H,W) uint16, 实际 {arr.shape}")
    h, w = arr.shape
    if h < 2 or w < 2:
        raise ValueError(f"cfa 至少 2x2, 实际 {arr.shape}")
    black_arr = np.asarray(black, dtype=np.float32)
    if black_arr.shape != (4,):
        raise ValueError(f"black 须为长度 4, 实际 {black_arr.shape}")
    params = PixoRenderCfaDecodeParams(
        patternR=int(pattern_r),
        patternG0=int(pattern_g0),
        patternG1=int(pattern_g1),
        patternB=int(pattern_b),
        black=(ctypes.c_float * 4)(*black_arr.tolist()),
        whiteLevel=float(white_level),
        outputScale=float(output_scale),
    )
    out_h, out_w = h // 2, w // 2
    out = np.empty((out_h, out_w, 3), dtype=np.float32)
    ret = _lib.PixoRenderDecodeCfaHalf(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_uint16)),
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        ctypes.c_int(w),
        ctypes.c_int(h),
        ctypes.byref(params),
    )
    _check_status(ret)
    return out


def exposure_apply(rgb: np.ndarray, ev: float = 0.0,
                   rolloff_knee: float = 0.9,
                   vignette: float = 0.0) -> np.ndarray:
    """调用 C++ 曝光内核（增益 + 高光软滚降 + 可选抗暗角）。"""
    _require_lib()
    if not hasattr(_lib, "PixoRenderExposureApply"):
        raise RuntimeError("native exposure kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb 须为 (H,W,3), 实际 {arr.shape}")
    h, w = arr.shape[:2]
    out = np.empty_like(arr)
    params = PixoRenderExposureParams(ev=float(ev), rolloffKnee=float(rolloff_knee),
                                  vignette=float(vignette))
    ret = _lib.PixoRenderExposureApply(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        ctypes.c_int(w), ctypes.c_int(h), ctypes.byref(params))
    _check_status(ret)
    return out


def matrix_apply3(rgb: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """调用 C++ 3x3 矩阵内核；out = rgb @ matrix.T。"""
    _require_lib()
    if not hasattr(_lib, "PixoRenderMatrixApply3"):
        raise RuntimeError("native matrix kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb 须为 (H,W,3), 实际 {arr.shape}")
    m = np.ascontiguousarray(matrix, dtype=np.float32).reshape(-1)
    if m.size != 9:
        raise ValueError(f"matrix 须为 3x3 或 9 元素, 实际 {m.size}")
    h, w = arr.shape[:2]
    out = np.empty_like(arr)
    params = PixoRenderMatrixApply3Params(
        matrix=m.ctypes.data_as(ctypes.POINTER(ctypes.c_float)))
    ret = _lib.PixoRenderMatrixApply3(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        ctypes.c_int(w), ctypes.c_int(h), ctypes.byref(params))
    _check_status(ret)
    return out


def tone_apply_lut1d(rgb: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """调用 C++ 1D LUT 内核（线性插值，输入 0..1）。"""
    _require_lib()
    if not hasattr(_lib, "PixoRenderToneApplyLut1D"):
        raise RuntimeError("native tone lut kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb 须为 (H,W,3), 实际 {arr.shape}")
    l = np.ascontiguousarray(lut, dtype=np.float32).reshape(-1)
    if l.size < 2:
        raise ValueError(f"lut 至少 2 点, 实际 {l.size}")
    h, w = arr.shape[:2]
    out = np.empty_like(arr)
    params = PixoRenderToneApplyLut1DParams(
        lut=l.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        lutSize=int(l.size))
    ret = _lib.PixoRenderToneApplyLut1D(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        ctypes.c_int(w), ctypes.c_int(h), ctypes.byref(params))
    _check_status(ret)
    return out


def clarity_apply(rgb: np.ndarray, strength: float, gray: np.ndarray,
                  small_blur: np.ndarray, large_blur: np.ndarray) -> np.ndarray:
    """调用 C++ clarity 内核（blur 平面由 Python cv2 预计算）。"""
    _require_lib()
    if not hasattr(_lib, "PixoRenderClarityApply"):
        raise RuntimeError("native clarity kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb 须为 (H,W,3), 实际 {arr.shape}")
    h, w = arr.shape[:2]
    g = _as_hw(gray, "gray")
    sb = _as_hw(small_blur, "small_blur")
    lb = _as_hw(large_blur, "large_blur")
    if g.shape != (h, w) or sb.shape != (h, w) or lb.shape != (h, w):
        raise ValueError(f"gray/blur shape 须为 {(h, w)}, 实际 {g.shape}/{sb.shape}/{lb.shape}")
    out = np.empty_like(arr)
    params = PixoRenderClarityParams(
        strength=float(strength),
        gray=_f32_ptr(g),
        smallBlur=_f32_ptr(sb),
        largeBlur=_f32_ptr(lb))
    ret = _lib.PixoRenderClarityApply(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        ctypes.c_int(w), ctypes.c_int(h), ctypes.byref(params))
    _check_status(ret)
    return out


def lut3d_apply_f32(rgb: np.ndarray, lut: np.ndarray,
                    domain_min: float = 0.0, domain_max: float = 1.0,
                    shaper: np.ndarray | None = None,
                    strength: float = 1.0) -> np.ndarray:
    """调用 C++ 3D LUT 四面体插值内核 (v1.3.0)；返回 float32 RGB (H,W,3)。

    与 render.core.lut3d.LUT3D.lookup 逐位对齐 (权重/MAC 在 float64、
    末端舍入 float32, 与 numpy NEP50 数组提升语义一致):
      rgb   : (H,W,3) float32 ∈ [0,1] (越界按 DOMAIN 窗口截断, 与 lookup 一致);
      lut   : (N,N,N,3) float32 表数据 (索引序 [r,g,b], r 最慢 b 最快);
      shaper: 可选 (m,) float32 1D shaper (先于 3D 查表线性插值);
      strength: 0..1 与原图混合 (0=原图), 与 apply() 的混合语义一致但全程
              float 不经 u8 量化。
    无状态设计: 表指针每次调用传入, 缓存由 LUT3D 实例侧管理。
    DLL < 1.3.0 未导出该符号时抛 RuntimeError, 调用方回退 numpy lookup。
    """
    _require_lib()
    if not hasattr(_lib, "PixoRenderLut3DApplyF32"):
        raise RuntimeError("native lut3d F32 kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb 须为 (H,W,3), 实际 {arr.shape}")
    table = np.ascontiguousarray(lut, dtype=np.float32)
    if table.ndim != 4 or table.shape[3] != 3 or \
            table.shape[0] != table.shape[1] or table.shape[1] != table.shape[2]:
        raise ValueError(f"lut 须为 (N,N,N,3), 实际 {table.shape}")
    size = int(table.shape[0])
    if size < 2:
        raise ValueError(f"lut size 至少 2, 实际 {size}")
    if shaper is not None:
        sh = np.ascontiguousarray(shaper, dtype=np.float32).reshape(-1)
        if sh.size < 2:
            raise ValueError(f"shaper 至少 2 点, 实际 {sh.size}")
        shaper_size = int(sh.size)
        shaper_ptr = sh.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
    else:
        shaper_size = 0
        shaper_ptr = None
    if not (float(domain_max) > float(domain_min)):
        raise ValueError(f"非法 DOMAIN: [{domain_min}, {domain_max}]")
    h, w = arr.shape[:2]
    out = np.empty((h, w, 3), dtype=np.float32)
    params = PixoRenderLut3DParams(
        lut=table.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        size=size,
        domainMin=float(domain_min),
        # span 以 Python float64 计算后舍入 f32, 对齐 numpy 标量语义
        # ((x-dmin)/(dmax-dmin) 中 span 先 f64 后 f32) —— 见内核头注释。
        domainSpan=float(domain_max) - float(domain_min),
        shaper=shaper_ptr,
        shaperSize=shaper_size,
        strength=float(strength),
    )
    ret = _lib.PixoRenderLut3DApplyF32(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        ctypes.c_int(w), ctypes.c_int(h), ctypes.byref(params))
    _check_status(ret)
    return out


def srgb_to_oklab_f32(rgb: np.ndarray) -> np.ndarray:
    """调用 C++ Oklab 正向内核 (v1.4.0); 返回 Oklab float64 (H,W,3)。

    gamma sRGB float32 (H,W,3) -> Oklab float64, 与 core.oklab.srgb_to_oklab
    逐位一致 (设计 §1.3 dtype 契约: Oklab 内部工作域出口 f64; f32 交接会把
    往返误差放大到 ~7e-7)。DLL < 1.4.0 未导出时抛 RuntimeError。
    """
    _require_lib()
    if not hasattr(_lib, "PixoRenderSrgbToOklabF32"):
        raise RuntimeError("native oklab kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb 须为 (H,W,3), 实际 {arr.shape}")
    h, w = arr.shape[:2]
    l = np.empty((h, w), dtype=np.float64)
    a = np.empty((h, w), dtype=np.float64)
    b = np.empty((h, w), dtype=np.float64)
    params = PixoRenderSrgbToOklabParams(
        rgb=arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        width=w, height=h, stride=w * 3,
        l=l.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        a=a.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        b=b.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        planeStride=w,
    )
    ret = _lib.PixoRenderSrgbToOklabF32(ctypes.byref(params))
    _check_status(ret)
    return np.stack([l, a, b], axis=-1)


def oklab_to_srgb_f32(lab: np.ndarray) -> np.ndarray:
    """调用 C++ Oklab 逆向内核 (v1.4.0); 返回 gamma sRGB float32 (H,W,3)。

    Oklab (H,W,3) -> sRGB float32, 与 core.oklab.oklab_to_srgb 逐位一致
    (linear 域 clip 到 [0,1] 后编码, 末端舍入 f32)。DLL < 1.4.0 未导出时抛
    RuntimeError。
    """
    _require_lib()
    if not hasattr(_lib, "PixoRenderOklabToSrgbF32"):
        raise RuntimeError("native oklab kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(lab, dtype=np.float64)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"lab 须为 (H,W,3), 实际 {arr.shape}")
    h, w = arr.shape[:2]
    l = np.ascontiguousarray(arr[..., 0])
    a = np.ascontiguousarray(arr[..., 1])
    b = np.ascontiguousarray(arr[..., 2])
    out = np.empty((h, w, 3), dtype=np.float32)
    params = PixoRenderOklabToSrgbParams(
        l=l.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        a=a.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        b=b.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
        planeStride=w,
        rgb=out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        width=w, height=h, stride=w * 3,
    )
    ret = _lib.PixoRenderOklabToSrgbF32(ctypes.byref(params))
    _check_status(ret)
    return out


def _oklab_numpy_impl(name: str):
    # 延迟导入: _native 先于 core 加载时避免导入环 (core.oklab 不反向依赖本模块)
    from pixo.render.core import oklab as _oklab

    return getattr(_oklab, name)


def srgb_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """gamma sRGB -> Oklab, native 优先, 不可用回退 core.oklab numpy 实现。

    native 路径 (F32 平面版) 仅当输入为 float32 (H,W,3) 时走 —— f32 是渲染
    域 dtype 契约; 其它 dtype (如 f64 精密输入) 走 numpy, 避免被静默量化。
    两路径结果与 core.oklab.srgb_to_oklab 逐位一致 (验收见
    tests/unit/test_native_oklab.py)。
    """
    arr = np.asarray(rgb)
    if (arr.dtype == np.float32 and arr.ndim == 3 and arr.shape[2] == 3
            and available() and hasattr(_lib, "PixoRenderSrgbToOklabF32")):
        try:
            return srgb_to_oklab_f32(arr)
        except RuntimeError:
            pass  # 内核异常时回退 numpy, 不放大为调用方错误
    return _oklab_numpy_impl("srgb_to_oklab")(rgb)


def oklab_to_srgb(lab: np.ndarray) -> np.ndarray:
    """Oklab -> gamma sRGB float32, native 优先, 不可用回退 core.oklab numpy 实现。

    (H,W,3) 且 native 可用时走 F32 内核; 任意 dtype 均安全 (两路径都先转
    f64 计算)。其它形状 (...,3) 走 numpy (core 支持任意 (...,3))。
    """
    arr = np.asarray(lab)
    if (arr.ndim == 3 and arr.shape[2] == 3
            and available() and hasattr(_lib, "PixoRenderOklabToSrgbF32")):
        try:
            return oklab_to_srgb_f32(arr)
        except RuntimeError:
            pass
    return _oklab_numpy_impl("oklab_to_srgb")(lab)


def apply_local_warm_sat_native(rgb: np.ndarray, params: PixoRenderWarmSatParams):
    """调用 C++ 完整 M1 内核（broad + spot）。

    返回 (out, handled)。handled=False 时调用方回退纯 Python。
    float32 输入走 f32 ABI；float64 输入走 f64 ABI；其它 dtype 转 float32。
    """
    _require_lib()
    arr = np.ascontiguousarray(rgb)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb 须为 (H,W,3), 实际 {arr.shape}")
    h, w = arr.shape[:2]
    if arr.dtype == np.float64 and hasattr(_lib, "PixoRenderApplyLocalWarmSatF64"):
        out = np.empty_like(arr)
        ret = _lib.PixoRenderApplyLocalWarmSatF64(
            arr.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            out.ctypes.data_as(ctypes.POINTER(ctypes.c_double)),
            ctypes.c_int(w),
            ctypes.c_int(h),
            ctypes.byref(params),
        )
    else:
        arr32 = np.ascontiguousarray(arr, dtype=np.float32)
        out = np.empty_like(arr32)
        ret = _lib.PixoRenderApplyLocalWarmSat(
            arr32.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            ctypes.c_int(w),
            ctypes.c_int(h),
            ctypes.byref(params),
        )
        if arr.dtype != np.float32:
            out = out.astype(arr.dtype, copy=False)
    if ret < 0:
        raise RuntimeError(f"native status {ret}")
    return out, ret == 0


def colorcal_apply_lab(lab: np.ndarray, params: PixoRenderColorCalParams) -> np.ndarray:
    """调用 C++ M2 全量 Lab 内核（旧, uint8 Lab 域）；返回 uint8 Lab (H,W,3)。

    16bit 精度改造后生产 stage 改用 colorcal_apply_lab_f32; 本内核仅为
    ABI 向后兼容与 scripts/measure_u8_precision.py 保真自检保留。
    """
    _require_lib()
    if not hasattr(_lib, "PixoRenderColorCalApplyLab"):
        raise RuntimeError("native colorcal kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(lab, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"lab 须为 (H,W,3), 实际 {arr.shape}")
    h, w = arr.shape[:2]
    out = np.empty((h, w, 3), dtype=np.uint8)
    ret = _lib.PixoRenderColorCalApplyLab(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        ctypes.c_int(w),
        ctypes.c_int(h),
        ctypes.byref(params),
    )
    _check_status(ret)
    return out


def colorcal_apply_lab_f32(lab: np.ndarray,
                           params: PixoRenderColorCalParams) -> np.ndarray:
    """调用 C++ float Lab 域全量内核；返回 float32 Lab (H,W,3)。

    输入/输出均为 cv2 float Lab 坐标 (L∈[0,100], a/b 中心 0) —— 注意与旧
    colorcal_apply_lab 的 uint8 Lab 域 (L∈[0,255], a/b 中心 128) 是两套标度,
    换算 L_f=L_u8*100/255, a_f=a_u8-128, b_f=b_u8-128。params 结构两内核
    同布局 (曲线值为 a/b 偏移, 域不变; 亮度节点由内核各自解释)。
    DLL < 1.2.0 未导出该符号时抛 RuntimeError, 调用方回退纯 Python float 实现。
    """
    _require_lib()
    if not hasattr(_lib, "PixoRenderColorCalApplyLabF32"):
        raise RuntimeError("native colorcal F32 kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(lab, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"lab 须为 (H,W,3), 实际 {arr.shape}")
    h, w = arr.shape[:2]
    out = np.empty((h, w, 3), dtype=np.float32)
    ret = _lib.PixoRenderColorCalApplyLabF32(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        ctypes.c_int(w),
        ctypes.c_int(h),
        ctypes.byref(params),
    )
    _check_status(ret)
    return out


def gamut_soft(rgb: np.ndarray, strength: float) -> np.ndarray:
    """调用 C++ 色域软压缩；返回 float32 RGB (H,W,3)。"""
    _require_lib()
    if not hasattr(_lib, "PixoRenderGamutSoft"):
        raise RuntimeError("native gamut_soft kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb 须为 (H,W,3), 实际 {arr.shape}")
    h, w = arr.shape[:2]
    out = np.empty_like(arr)
    ret = _lib.PixoRenderGamutSoft(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        out.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
        ctypes.c_int(w),
        ctypes.c_int(h),
        ctypes.c_float(strength),
    )
    _check_status(ret)
    return out


def _as_hw(arr: np.ndarray, name: str) -> np.ndarray:
    """把 HxW 或 HxWx1 转成 C 连续 HxW float32。"""
    arr = np.ascontiguousarray(arr, dtype=np.float32)
    if arr.ndim == 3 and arr.shape[2] == 1:
        arr = arr[..., 0]
    if arr.ndim != 2:
        raise ValueError(f"{name} 须为 (H,W) 或 (H,W,1), 实际 {arr.shape}")
    return arr


def _f32_ptr(arr: np.ndarray):
    return arr.ctypes.data_as(ctypes.POINTER(ctypes.c_float))


def refine_sat_protection(rgb: np.ndarray, lo: float = 0.08,
                          hi: float = 0.32) -> np.ndarray:
    """调用 C++ M3 饱和保护权重；返回 float32 (H,W)。"""
    _require_lib()
    if not hasattr(_lib, "PixoRenderRefineSatProtection"):
        raise RuntimeError("native refine sat_protection kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb 须为 (H,W,3), 实际 {arr.shape}")
    h, w = arr.shape[:2]
    out = np.empty((h, w), dtype=np.float32)
    params = PixoRenderRefineSatProtectionParams(lo=float(lo), hi=float(hi))
    ret = _lib.PixoRenderRefineSatProtection(
        _f32_ptr(arr), _f32_ptr(out), ctypes.c_int(w), ctypes.c_int(h),
        ctypes.byref(params),
    )
    _check_status(ret)
    return out


def refine_sharpen(rgb: np.ndarray, gray: np.ndarray, sat_protect: np.ndarray,
                   gray_blur: np.ndarray, sharpen: float) -> np.ndarray:
    """调用 C++ M3 灰空间锐化；返回 float32 (H,W,3)。"""
    _require_lib()
    if not hasattr(_lib, "PixoRenderRefineSharpen"):
        raise RuntimeError("native refine sharpen kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb 须为 (H,W,3), 实际 {arr.shape}")
    h, w = arr.shape[:2]
    gray = _as_hw(gray, "gray")
    sat_protect = _as_hw(sat_protect, "sat_protect")
    gray_blur = _as_hw(gray_blur, "gray_blur")
    if not (gray.shape == sat_protect.shape == gray_blur.shape == (h, w)):
        raise ValueError("gray/sat_protect/gray_blur shape 须为 (H,W)")
    out = np.empty_like(arr)
    params = PixoRenderRefineSharpenParams(
        sharpen=float(sharpen), gray=_f32_ptr(gray),
        satProtect=_f32_ptr(sat_protect), grayBlur=_f32_ptr(gray_blur),
    )
    ret = _lib.PixoRenderRefineSharpen(
        _f32_ptr(arr), _f32_ptr(out), ctypes.c_int(w), ctypes.c_int(h),
        ctypes.byref(params),
    )
    _check_status(ret)
    return out


def refine_chroma(rgb: np.ndarray, gray: np.ndarray, sat_protect: np.ndarray,
                  blur_up: np.ndarray, gray_blur_up: np.ndarray,
                  chroma_denoise: float) -> np.ndarray:
    """调用 C++ M3 色度降噪；返回 float32 (H,W,3)。"""
    _require_lib()
    if not hasattr(_lib, "PixoRenderRefineChroma"):
        raise RuntimeError("native refine chroma kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb 须为 (H,W,3), 实际 {arr.shape}")
    h, w = arr.shape[:2]
    gray = _as_hw(gray, "gray")
    sat_protect = _as_hw(sat_protect, "sat_protect")
    blur_up = np.ascontiguousarray(blur_up, dtype=np.float32)
    gray_blur_up = _as_hw(gray_blur_up, "gray_blur_up")
    if blur_up.ndim != 3 or blur_up.shape[2] != 3 or blur_up.shape[:2] != (h, w):
        raise ValueError(f"blur_up 须为 (H,W,3), 实际 {blur_up.shape}")
    if gray_blur_up.shape != (h, w):
        raise ValueError("gray_blur_up shape 须为 (H,W)")
    out = np.empty_like(arr)
    params = PixoRenderRefineChromaParams(
        chromaDenoise=float(chroma_denoise), gray=_f32_ptr(gray),
        satProtect=_f32_ptr(sat_protect), blurUp=_f32_ptr(blur_up),
        grayBlurUp=_f32_ptr(gray_blur_up),
    )
    ret = _lib.PixoRenderRefineChroma(
        _f32_ptr(arr), _f32_ptr(out), ctypes.c_int(w), ctypes.c_int(h),
        ctypes.byref(params),
    )
    _check_status(ret)
    return out


def refine_highlight(rgb: np.ndarray, gray: np.ndarray, sat_protect: np.ndarray,
                     highlight_desat: float) -> np.ndarray:
    """调用 C++ M3 高光去色；返回 float32 (H,W,3)。"""
    _require_lib()
    if not hasattr(_lib, "PixoRenderRefineHighlight"):
        raise RuntimeError("native refine highlight kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb 须为 (H,W,3), 实际 {arr.shape}")
    h, w = arr.shape[:2]
    gray = _as_hw(gray, "gray")
    sat_protect = _as_hw(sat_protect, "sat_protect")
    if gray.shape != (h, w) or sat_protect.shape != (h, w):
        raise ValueError("gray/sat_protect shape 须为 (H,W)")
    out = np.empty_like(arr)
    params = PixoRenderRefineHighlightParams(
        highlightDesat=float(highlight_desat), gray=_f32_ptr(gray),
        satProtect=_f32_ptr(sat_protect),
    )
    ret = _lib.PixoRenderRefineHighlight(
        _f32_ptr(arr), _f32_ptr(out), ctypes.c_int(w), ctypes.c_int(h),
        ctypes.byref(params),
    )
    _check_status(ret)
    return out


def refine_apply(rgb: np.ndarray, gray: np.ndarray, sat_protect: np.ndarray,
                 gray_blur: np.ndarray | None, blur_up: np.ndarray | None,
                 gray_blur_up: np.ndarray | None, sharpen: float,
                 chroma_denoise: float, highlight_desat: float) -> np.ndarray:
    """调用 C++ M3 一次融合内核 (规格 PixoRenderRefineApply)。"""
    _require_lib()
    if not hasattr(_lib, "PixoRenderRefineApply"):
        raise RuntimeError("native refine apply kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(rgb, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"rgb 须为 (H,W,3), 实际 {arr.shape}")
    h, w = arr.shape[:2]
    gray = _as_hw(gray, "gray")
    sat_protect = _as_hw(sat_protect, "sat_protect")
    if gray.shape != (h, w) or sat_protect.shape != (h, w):
        raise ValueError("gray/sat_protect shape 须为 (H,W)")
    gray_blur_c = _as_hw(gray_blur, "gray_blur") if gray_blur is not None else None
    blur_up_c = np.ascontiguousarray(blur_up, dtype=np.float32) if blur_up is not None else None
    gray_blur_up_c = _as_hw(gray_blur_up, "gray_blur_up") if gray_blur_up is not None else None
    if sharpen > 0 and gray_blur_c is None:
        raise ValueError("sharpen>0 时 gray_blur 不能为空")
    if chroma_denoise > 0 and (blur_up_c is None or gray_blur_up_c is None):
        raise ValueError("chroma_denoise>0 时 blur_up/gray_blur_up 不能为空")
    out = np.empty_like(arr)
    params = PixoRenderRefineApplyParams(
        sharpen=float(sharpen), chromaDenoise=float(chroma_denoise),
        highlightDesat=float(highlight_desat), gray=_f32_ptr(gray),
        satProtect=_f32_ptr(sat_protect),
        grayBlur=_f32_ptr(gray_blur_c) if gray_blur_c is not None else None,
        blurUp=_f32_ptr(blur_up_c) if blur_up_c is not None else None,
        grayBlurUp=_f32_ptr(gray_blur_up_c) if gray_blur_up_c is not None else None,
    )
    ret = _lib.PixoRenderRefineApply(
        _f32_ptr(arr), _f32_ptr(out), ctypes.c_int(w), ctypes.c_int(h),
        ctypes.byref(params),
    )
    _check_status(ret)
    return out


def warm_sat_gamma_u8(hsv: np.ndarray, gain: float,
                      hue_shift_deg: float) -> None:
    """调用 C++ M3 gamma 暖色补强 (uint8 HSV in-place)。"""
    _require_lib()
    if not hasattr(_lib, "PixoRenderWarmSatGammaU8"):
        raise RuntimeError("native warm_sat_gamma kernel unavailable (DLL 未导出)")
    arr = np.ascontiguousarray(hsv, dtype=np.uint8)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"hsv 须为 (H,W,3) uint8, 实际 {arr.shape}")
    h, w = arr.shape[:2]
    params = PixoRenderWarmGammaParams(gain=float(gain), hueShiftDeg=float(hue_shift_deg))
    ret = _lib.PixoRenderWarmSatGammaU8(
        arr.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
        ctypes.c_int(w), ctypes.c_int(h), ctypes.byref(params),
    )
    _check_status(ret)


__all__ = ["available", "load_error", "version", "rgb_to_hsv", "hsv_to_rgb",
           "rgb_to_hsv_f32", "hsv_to_rgb_f32", "PixoRenderWarmSatParams",
           "PixoRenderVersion", "PixoRenderColorCalParams", "PixoRenderCfaDecodeParams",
           "PixoRenderExposureParams", "PixoRenderMatrixApply3Params",
           "PixoRenderToneApplyLut1DParams", "PixoRenderClarityParams",
           "PixoRenderLut3DParams",
           "apply_local_warm_sat_native", "decode_cfa_half",
           "colorcal_apply_lab", "colorcal_apply_lab_f32", "gamut_soft",
           "PixoRenderRefineSatProtectionParams",
           "PixoRenderRefineSharpenParams", "PixoRenderRefineChromaParams",
           "PixoRenderRefineHighlightParams", "PixoRenderRefineApplyParams",
           "PixoRenderWarmGammaParams", "refine_sat_protection", "refine_sharpen",
           "refine_chroma", "refine_highlight", "refine_apply",
           "warm_sat_gamma_u8", "exposure_apply", "matrix_apply3",
           "tone_apply_lut1d", "clarity_apply", "lut3d_apply_f32",
           "PixoRenderSrgbToOklabParams", "PixoRenderOklabToSrgbParams",
           "srgb_to_oklab_f32", "oklab_to_srgb_f32", "srgb_to_oklab", "oklab_to_srgb"]
