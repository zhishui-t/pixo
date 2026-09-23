"""Stage tone (order=30) —— 影调 (linear_rgb → gamma_rgb)。

基座影调 = sRGB 曲线基 (DCP ProfileToneCurve 默认关闭, 保留为 Adobe look 开关):
  - profile_curve=False (默认): 用精确 sRGB EOTF 曲线基 (或纯 1/2.2 幂, 参数 eotf)。
  - profile_curve=True: **复合** DCP ProfileToneCurve —— Adobe 管线里该曲线是
    linear→linear 的场景曲线、施于输出编码**之前**, 故此处为 base_lut∘curve_lut
    (曲线输出仍为线性值, 再走 EOTF), 而非用曲线整条替代编码 (R24 修复);
    无曲线时回退曲线基。
  - use_filmic=True: 用 filmic 影调重塑曲线 (Phase 1.5 增强层, 默认不用)。

profile_curve 默认 False 的纪律依据:
  2026-08-16 A/B (6 张 NEF vs 相机预览) 时槽位还是"曲线替代编码"的坏实现
  (暗部 5-7% 裁切); R23 引擎基线中性化把"打开 RAW 即施加观感"定为越权,
  ProfileToneCurve 是**相机配置文件槽位** (Adobe look / Picture Control 落点),
  由调用方以**数据**形式注入, 不写死在代码里。R24 复合修复后 (n=24 探针):
  A 28.65(V0 中性)→13.58 / cc 0.96→0.97, 曲线形状正确但"默认开"仍属编辑
  动作, 维持默认关。实证: .artifacts/_r24_compose_probe.py。

RGB 三通道共用同一条亮度曲线 ⇒ 中性灰在任何亮度层级保持中性。

参数:
  profile_curve  使用 DCP ProfileToneCurve (默认 False; True = Adobe look)
  eotf           影调来源: 'srgb'(默认, 精确 sRGB EOTF) | 'power22' (纯幂) |
                 'lrfit' (LR 标定) | 'recipe' (相机 thumb 拟合标定, R24;
                 二者读包内 v3 JSON, 缺失回退 sRGB 曲线基并记降级)
  gamma          eotf='power22' 的幂 / filmic 基础 (默认 2.2)
  brightness     显示亮度增益 (EV, 线性域预乘, 每机校准常量)
  use_filmic     Phase 1.5 filmic 曲线 (默认 False, 优先于 profile_curve)
  contrast/toe/shoulder  filmic 参数 (use_filmic=True 时生效)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..pipeline.graph import Stage, StageContext, register_stage
from ..pipeline.graph import DOMAIN_LINEAR_RGB, DOMAIN_GAMMA_RGB
from ..core.curves import (make_filmic_lut, make_base_curve_lut, apply_lut1d,
                      apply_lut1d_fast, parse_profile_curve, curve_lut_from_points)
from ..core import calibration_store
from ..degradation import record_degradation

_LUT_CACHE = {}
# DcpProfile 影调曲线复合 LUT 缓存：(id(prof), eotf, gamma) 键 + **值里持
# prof 强引用**。不能用 WeakKeyDictionary——DcpProfile 是 @dataclass(默认生成
# __eq__) 不可哈希；也不能裸 id() 键——prof 被 GC 后 id 可能被新对象复用，导致
# 张冠李戴的曲线 (原实现的潜在缺陷)。强引用钉住 prof ⇒ 条目存活期内 id 不可能
# 复用；每条目仅 (prof 引用 + 16K float LUT)，profile 实例有限，泄漏可忽略。
_PROFILE_CACHE: dict[tuple, tuple] = {}
_LRFIT_CACHE = None
# R24 recipe 标定缓存 (v3 同构: gains + 共享曲线; 目标=相机内嵌 JPEG,
# 由 tools/fit_tone_curve.py 拟合)。与 _LRFIT_CACHE 分立保持既有
# monkeypatch 形态 (元组) 不变。
_RECIPE_CACHE = None
_N_FAST = 16384  # 热路径 LUT 级数 (最近邻, 量化误差 <1/32768 不可感知)
# LR 标定文件 (包内资源, 默认不存在): 文件 I/O/缓存统一走
# core.calibration_store —— 缺失时由 store 负缓存 (旧实现每次调用都
# p.exists() stat 探测), 存在时按 (mtime_ns, size) 失效重读。
_LR_CAL_FILE = Path(__file__).resolve().parent.parent / "lr_tone_curve.json"
# recipe 标定文件 (包内资源, 默认不存在; fit_tone_curve.py 产出)
_RECIPE_CAL_FILE = Path(__file__).resolve().parent.parent / "recipe_tone_curve.json"


def _reset_caches() -> None:
    """测试隔离钩子: 还原影调 LUT / lrfit·recipe 标定缓存并重置 calibration_store。

    _PROFILE_CACHE 不清: 键为 (id(prof), eotf, gamma) 且值持 prof 强引用
    (防 id 复用的修复保持不动), 与文件标定加载无关, 条目跨 reset 恒有效。
    """
    global _LRFIT_CACHE, _RECIPE_CACHE
    _LRFIT_CACHE = None
    _RECIPE_CACHE = None
    _LUT_CACHE.clear()
    calibration_store.reset()


def _load_fit_doc(cal_file: Path):
    """v3 标定文档 → (gains[3], 共享曲线 LUT); 缺失/无效 → None。

    格式: {"version": 3|4, "gains": [r,g,b], "curve": [1024 点 0..255]}
    语义 (tools/fit_tone_curve.py 拟合, rawlab v4 工具 R24 找回改造):
      - gains: 线性域逐通道增益, 吸收目标与我们的全局色差 (亮度标度+WB/色调方向);
      - curve: 一条共享影调曲线, 三通道同曲线 → 中性像素任意层级保持中性。
    历史教训 (2026-08): v1 逐通道 CDF 曲线把拟合照片的白平衡烘焙进曲线,
      换一张照片 (5236) 就整体发蓝 (用户报"一黄一蓝, RGB 标反?"), 实为
      逐通道直方图匹配的跨图缺陷, 不是通道标反。
    文件读取走 core.calibration_store (负缓存: 缺失不再每次 stat);
    解析/防呆逻辑与迁移前逐行一致。
    """
    doc = calibration_store.load_json(cal_file)
    if doc is None:
        return None
    try:
        gains = np.asarray(doc.get("gains", [1.0, 1.0, 1.0]),
                           dtype=np.float32)
        curve = np.asarray(doc["curve"], dtype=np.float64) / 255.0
        # 防呆: 曲线退化 (如 0..1 误存又除 255) 时直接判无效
        if float(curve.max()) >= 0.1:
            grid = np.linspace(0.0, 1.0, _N_FAST, dtype=np.float64)
            lut = np.interp(grid, np.linspace(0.0, 1.0, len(curve)),
                            curve).astype(np.float32)
            return (gains, lut)
    except Exception:
        return None
    return None


def _get_tone_fit(kind: str):
    """lrfit / recipe 标定 (v3 同构); kind='lrfit' 读 LR 标定文件,
    'recipe' 读相机 thumb 拟合标定 (R24); 文件缺失 → None。
    两缓存分立 ⇒ 既有 _LRFIT_CACHE 元组 monkeypatch 形态不变。"""
    if kind == "recipe":
        global _RECIPE_CACHE
        if _RECIPE_CACHE is None:
            _RECIPE_CACHE = _load_fit_doc(_RECIPE_CAL_FILE)
        return _RECIPE_CACHE
    global _LRFIT_CACHE
    if _LRFIT_CACHE is None:
        _LRFIT_CACHE = _load_fit_doc(_LR_CAL_FILE)
    return _LRFIT_CACHE


def _get_lut(gamma: float, contrast: float, toe: float, shoulder: float) -> np.ndarray:
    key = ("f", round(gamma, 3), round(contrast, 4), round(toe, 4), round(shoulder, 4))
    lut = _LUT_CACHE.get(key)
    if lut is None:
        lut = make_filmic_lut(4096, contrast=contrast, toe=toe, shoulder=shoulder)
        _LUT_CACHE[key] = lut
    return lut


def _get_base_lut(eotf: str, gamma: float) -> np.ndarray:
    key = ("b", str(eotf), round(float(gamma), 3))
    lut = _LUT_CACHE.get(key)
    if lut is None:
        lut = make_base_curve_lut(eotf=str(eotf), gamma=float(gamma), n=_N_FAST)
        _LUT_CACHE[key] = lut
    return lut


def _get_profile_lut(prof, eotf: str = "srgb",
                     gamma: float = 2.2) -> np.ndarray | None:
    """DCP 影调曲线**复合** LUT (缓存; 无曲线返回 None)。

    R24: ProfileToneCurve 是 Adobe 管线里的 **linear→linear** 场景曲线
    (施于输出编码之前), 不是完整的 linear→gamma 映射 —— 返回
    base_lut ∘ profile_lut (曲线输出作为线性值再走 EOTF)。旧实现
    用曲线整条替代编码 ⇒ 逐像素结构错位 (n=24 探针: A 36.37→13.58,
    cc 0.89→0.97, .artifacts/_r24_compose_probe.py)。
    复合预构为单条 16384 级 LUT ⇒ 热路径仍单次 gather, native 不变。
    """
    if prof is None:
        return None
    key = (id(prof), str(eotf), round(float(gamma), 3))
    entry = _PROFILE_CACHE.get(key)
    if entry is None:
        parsed = parse_profile_curve(getattr(prof, "profile_tone_curve", None))
        if parsed:
            prof_lut = curve_lut_from_points(*parsed, _N_FAST)
            # 复合 (base∘profile): apply_lut1d 线性插值, 单调性由
            # "profile 非降 + base 递增" 的复合构造保证; 白→白契约
            # (曲线两端点 0→0/1→1 + base 端点) 随之保持。
            lut = apply_lut1d(prof_lut, _get_base_lut(str(eotf), float(gamma)))
        else:
            lut = None
        # 值持 (prof, lut) 强引用：防 prof 释放后 id 被新 profile 复用
        # (DcpProfile 不可哈希，无法用 WeakKeyDictionary)。
        entry = (prof, lut)
        _PROFILE_CACHE[key] = entry
    return entry[1]


_RGB_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def _check_highlight_compress_curve(curve) -> np.ndarray:
    arr = np.asarray(curve, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2 or arr.shape[0] < 2:
        raise ValueError(f"highlight_compress_curve 需 ≥2 个 [wb_B, gain] 结点 (shape={arr.shape})")
    if not np.all(np.diff(arr[:, 0]) > 0):
        raise ValueError("highlight_compress_curve 结点 wb_B 必须严格递增")
    if arr[:, 1].min() < 0.0 or arr[:, 1].max() > 0.5:
        raise ValueError("highlight_compress_curve 增益必须在 [0, 0.5] 内")
    return arr


def _ssclip(v):
    """smoothstep 0..1 (C1)。"""
    v = np.clip(v, 0.0, 1.0)
    return v * v * (3.0 - 2.0 * v)


# T1.5 四键幅度系数: 各键满载(±1)时区域作用的 lerp/scale 强度。
# 实测调参保证: 全 4 键在 [-0.8, 0.8] 范围内灰阶 ramp 单调、白/黑点不硬 clip。
# (极端 +-1.0 时除 whites 压缩外仍单调; 测试取 +-0.8 覆盖常规使用区间。)
_SIXKEY_GAIN = 0.7


def _band(x, lo, hi, rec):
    """带通掩码 [0,1]: 在 [lo, hi] 间升至峰值区, 两端 smoothstep 滚降回 0。

    rec: 上沿恢复宽度 → 掩码在高端归 0, 使端点恒等(白点不越 1、黑非负)。
    与 highlight_compress 的 up*down 同型。
    """
    up = _ssclip((x - lo) / max(hi - lo, 1e-6))
    down = _ssclip((hi + rec - x) / max(rec, 1e-6))
    return up * down


def _apply_sixkey(x: np.ndarray, ctx, stage) -> np.ndarray:
    """T1.5 Highlights/Shadows/Whites/Blacks 四键 (线性域, EOTF 之前)。

    全 0 → 原样返回 (逐位一致)。实现: 亮度代理 L=x@[.2126 .7152 .0722],
    三通道乘/混合同一标量带通掩码 ⇒ 中性灰不偏色、灰阶 ramp 单调:
      - highlights: 亮部带(0.55-0.78);   >0 提高光 / <0 压高光。
      - shadows:    暗部带(0-0.14);      >0 提阴影 / <0 压阴影。
      - whites:     近白肩带(0.75-0.90); >0 提白 / <0 压白。
      - blacks:     近黑带(0-0.08);      >0 提黑 / <0 压黑。
    提升方向用 lerp 向白 (x'=x(1-d)+d, 0<=x'<=1 ⇒ 白点不越 1 硬裁);
    压缩方向用缩放 (x'=x(1-d), 0<=x'<=x ⇒ 黑点保持非负)。带通两端归 0
    恢复恒等 ⇒ 区域隔离 (只改目标色段)、端点恒等。
    """
    h = float(stage.p(ctx, "highlights"))
    s_ = float(stage.p(ctx, "shadows"))
    w = float(stage.p(ctx, "whites"))
    b = float(stage.p(ctx, "blacks"))
    if h == 0.0 and s_ == 0.0 and w == 0.0 and b == 0.0:
        return x
    L = (x @ _RGB_WEIGHTS).astype(np.float32)  # (H,W) 线性亮度代理
    K = _SIXKEY_GAIN
    out = x
    # (参数名, 掩码 (lo,hi,rec))
    for name, v, params in (("highlights", h, (0.55, 0.78, 0.28)),
                            ("shadows", s_, (0.00, 0.14, 0.36)),
                            ("whites", w, (0.75, 0.90, 0.16)),
                            ("blacks", b, (0.00, 0.08, 0.20))):
        if v == 0.0:
            continue
        mask = _band(L, *params)
        d = np.clip(abs(v) * K * mask, 0.0, 1.0)[..., None]
        if v > 0.0:
            out = out * (1.0 - d) + d          # 提升: lerp 向白, 不越 1
        else:
            out = out * (1.0 - d)              # 压缩: 缩放, 保持非负
    return out


def _parse_user_curve_points(points, name):
    """解析 [[x,y],...] 用户曲线控制点并校验 (x∈[0,1] 且单调不减)。"""
    if not isinstance(points, (list, tuple)) or len(points) == 0:
        raise ValueError(
            f"user_curve.{name} 需为非空 [[x,y],...] 控制点列表")
    arr = np.asarray(points, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(
            f"user_curve.{name} 每个控制点必须为 [x,y] 二元组")
    xs = arr[:, 0]
    ys = arr[:, 1]
    if not np.all((xs >= 0.0) & (xs <= 1.0)):
        raise ValueError(
            f"user_curve.{name} 控制点 x 必须在 [0,1] 内")
    if np.any(np.diff(xs) < 0.0):
        raise ValueError(
            f"user_curve.{name} 控制点 x 必须单调不减 (允许相等)")
    return xs, ys


# R32-T4: user_curve 插值模式 (对照吸收 RawTherapee diagonalcurvetypes.h;
# "linear" 缺省逐位不变, 其余见 core/curves.py 模式注)
_USER_CURVE_MODES = ("linear", "spline", "akima", "catmull_rom", "monotone")


def _user_curve_mode(user_curve) -> str:
    """取 user_curve 的插值模式 (dict 形式 "mode" 键, 缺省 linear)。"""
    if isinstance(user_curve, dict):
        mode = user_curve.get("mode", "linear") or "linear"
        if mode not in _USER_CURVE_MODES:
            raise ValueError(
                f"user_curve.mode 非法: {mode!r} (合法: {_USER_CURVE_MODES})")
        return mode
    return "linear"


def _curve_lut_for(xs, ys, n, mode):
    return curve_lut_from_points(xs, ys, n, mode=mode)


def _apply_user_curve(img, user_curve, n: int = 4096) -> np.ndarray:
    """在 gamma 域 RGB 图上应用用户控制点曲线 (rgb → 分通道 → luminance)。

    user_curve 结构 (JSON 友好):
      - [[x,y],...]                     RGB 主曲线 (三通道同 LUT, linear)
      - {"rgb":[[x,y],...], "mode":M}   M = 插值模式 (R32-T4 新增, 可省,
                                        缺省 "linear"; 合法: linear/spline/
                                        akima/catmull_rom/monotone —— spline=
                                        自然三次样条(RT DCT_Spline 同数学),
                                        catmull_rom=向心 CR α=0.375(RT 同参,
                                        y∈{0,1} 平段=黑白渐近线精确保持),
                                        monotone=Fritsch–Carlson 过冲自由)
      - {"red":[[..]], "green":[[..]], "blue":[[..]]}  分通道 (缺省恒等)
      - {"luminance":[[x,y],...]}       亮度曲线 (Rec.709 Y, 按 newY/max(oldY,eps)
                                         等比缩放 RGB 保色调, clip [0,1])
    mode 作用于 dict 内全部曲线组; 线性模式与 T1.4 既有语义逐位一致
    (缺省不开启, 向后兼容)。应用顺序: rgb → per-channel → luminance。
    None/空 → 原样返回 (no-op)。
    """
    img = np.asarray(img, dtype=np.float32).copy()
    if user_curve is None:
        return img
    mode = _user_curve_mode(user_curve)
    if isinstance(user_curve, (list, tuple)):
        if len(user_curve) == 0:
            return img
        xs, ys = _parse_user_curve_points(user_curve, "rgb")
        lut = _curve_lut_for(xs, ys, n, mode)
        for c in range(3):
            img[..., c] = apply_lut1d_fast(img[..., c], lut)
        return img
    if not isinstance(user_curve, dict):
        raise ValueError(
            "user_curve 须为 [[x,y],...] 或 "
            "{rgb/red/green/blue/luminance: [[x,y],...]} 结构")
    if not user_curve:
        return img
    allowed = {"rgb", "red", "green", "blue", "luminance", "mode"}
    unknown = set(user_curve) - allowed
    if unknown:
        raise ValueError(
            f"user_curve 含未知键 {sorted(unknown)}; 合法键: {sorted(allowed)}")
    if "rgb" in user_curve:
        xs, ys = _parse_user_curve_points(user_curve["rgb"], "rgb")
        lut = _curve_lut_for(xs, ys, n, mode)
        for c in range(3):
            img[..., c] = apply_lut1d_fast(img[..., c], lut)
    per_ch = {"red": 0, "green": 1, "blue": 2}
    for ch in ("red", "green", "blue"):
        if ch in user_curve:
            xs, ys = _parse_user_curve_points(user_curve[ch], ch)
            lut = _curve_lut_for(xs, ys, n, mode)
            img[..., per_ch[ch]] = apply_lut1d_fast(img[..., per_ch[ch]], lut)
    if "luminance" in user_curve:
        xs, ys = _parse_user_curve_points(user_curve["luminance"], "luminance")
        lut = _curve_lut_for(xs, ys, n, mode)
        old_y = (img @ _RGB_WEIGHTS).astype(np.float32)  # Rec.709 Y
        new_y = apply_lut1d_fast(old_y, lut)
        scale = new_y / np.maximum(old_y, 1e-9)
        img = img * scale[..., np.newaxis]
        img = np.clip(img, 0.0, 1.0)
    return img


@register_stage("tone", order=30,
                domain_in=DOMAIN_LINEAR_RGB, domain_out=DOMAIN_GAMMA_RGB)
class ToneStage(Stage):
    name = "tone"

    param_schema = {
        "profile_curve": {"type": "bool"},
        "eotf": {"type": "str",
                 "choices": ["srgb", "power22", "lrfit", "recipe"]},
        "gamma": {"type": "float", "min": 1.0, "max": 4.0},
        "brightness": {"type": "float"},
        "use_filmic": {"type": "bool"},
        "contrast": {"type": "float", "min": 0.0, "max": 1.0},
        "toe": {"type": "float", "min": 0.0, "max": 1.0},
        "shoulder": {"type": "float", "min": 0.0, "max": 1.0},
        "highlight_compress_curve": {"type": "float_or_str"},
        "user_curve": {"type": "float_or_str"},
        # T1.5 曝光六键中的 Highlights/Shadows/Whites/Blacks 四键 (-1..1, 0=no-op):
        # 线性域亮度掩码乘性作用, 中性不偏色、ramp 单调、白/黑点不硬clip。
        "highlights": {"type": "float", "min": -1.0, "max": 1.0},
        "shadows": {"type": "float", "min": -1.0, "max": 1.0},
        "whites": {"type": "float", "min": -1.0, "max": 1.0},
        "blacks": {"type": "float", "min": -1.0, "max": 1.0},
    }

    def default_params(self):
        # profile_curve 默认 False: 基座用 sRGB EOTF; ProfileToneCurve 是
        #   **相机配置文件槽位** (Adobe look / 相机 Picture Control 的落点),
        #   由调用方以**数据**形式注入, 不写死在代码里。
        # brightness 默认 0.0: 旧默认 +0.25 是"对齐相机预览偏暗"打的补丁
        #   (实测关掉它 dL 中位 −1.81 → −4.99)。补丁掩盖的是**曲线形状差**
        #   (缺口在中段, 一个线性增益结构上补不上), 且属编辑动作 ⇒ 归零。
        # contrast / shoulder 默认 0.0: 二者只在 use_filmic=True 分支被消费,
        #   默认链上是**死参数**, 归零以消除"默认即观感"的假象。
        return {"profile_curve": False, "eotf": "srgb", "gamma": 2.2,
                "brightness": 0.0, "use_filmic": False,
                "contrast": 0.0, "toe": 0.0, "shoulder": 0.0,
                "highlight_compress_curve": None,
                "user_curve": None,
                "highlights": 0.0, "shadows": 0.0, "whites": 0.0, "blacks": 0.0}

    def wants(self, ctx: StageContext) -> bool:
        """**恒为 True**: 本 Stage 是 linear→gamma 的输出编码步 (**域转换**),
        不是可选的编辑动作 —— 打开 RAW 就必须把线性场景光编到显示域。
        显式声明而非依赖基类, 避免基类默认改 False 后输出编码被跳过。
        """
        return True

    def process(self, ctx: StageContext) -> None:
        use_filmic = bool(self.p(ctx, "use_filmic"))
        use_profile = bool(self.p(ctx, "profile_curve"))
        brightness = float(self.p(ctx, "brightness"))
        gamma = float(self.p(ctx, "gamma"))
        eotf = str(self.p(ctx, "eotf"))
        x = ctx.image * (2.0 ** brightness)
        # T1.5 四键: Highlights/Shadows/Whites/Blacks (线性域, EOTF 之前)。
        # 全 0 时 _apply_sixkey 直接原样返回 (逐位一致); 三通道乘同一标量亮度
        # 掩码 → 中性灰不偏色、灰阶 ramp 单调; 白/黑端点不硬 clip。
        x = _apply_sixkey(x, ctx, self)

        def _apply_lut(img, lut):
            try:
                from .._native import tone_apply_lut1d
                return tone_apply_lut1d(img, lut)
            except Exception as exc:
                # F03 #8: LUT1D native 插值不可用 → apply_lut1d_fast (逐位差风险)
                record_degradation(
                    "render.tone_map.lut1d_native", exc,
                    detail="LUT1D 插值回退 apply_lut1d_fast")
                return apply_lut1d_fast(img, lut)

        if eotf in ("lrfit", "recipe"):
            # 标定影调 (v3: 线性增益 + 共享曲线, tools/fit_tone_curve.py):
            # gains 吸收全局色差, 曲线只做影调 —— 中性像素保持中性, 且可跨图
            # 泛化 (v1 逐通道曲线会把单张照片的 WB 烘焙进曲线, 跨图发蓝)。
            # 注意: 曲线已含目标的亮度锚定, 此处不再乘 brightness。
            fit = _get_tone_fit(eotf)
            if fit is not None:
                gains, lut = fit
                # E2 修复: 六键 (Highlights/Shadows/Whites/Blacks) 在标定分支
                # 同样生效 —— 基于六键结果乘 gains; 仍不乘 brightness
                # (注释语义保持: 曲线已含目标的亮度锚定)。
                x6 = _apply_sixkey(ctx.image.astype(np.float32), ctx, self)
                xc = np.clip(x6 * gains, 0.0, 1.0)
                # 共享曲线 ⇒ 整图单次 _apply_lut (native 需 (H,W,3);
                # 旧逐通道 2D 调用会触发 lut1d_native 降级回退, R24 实跑暴露)
                y = _apply_lut(xc, lut)
                profile_used = False
            else:
                # R24: 标定缺失的静默回退改可观测 —— 旧行为请求 lrfit 却
                # 无声落 sRGB 曲线基 (R23 探针 V5==V0 逐位相同之谜)。
                cal_file = _LR_CAL_FILE if eotf == "lrfit" else _RECIPE_CAL_FILE
                record_degradation(
                    f"render.tone_map.{eotf}_calibration_missing", None,
                    path=str(cal_file),
                    reason="calibration_missing",
                    detail="标定文件缺失 → 回退 sRGB 曲线基",
                    kind="fallback")
                y = _apply_lut(x, _get_base_lut("srgb", gamma))
                profile_used = False
        elif use_filmic:
            lut = _get_lut(gamma, float(self.p(ctx, "contrast")),
                           float(self.p(ctx, "toe")), float(self.p(ctx, "shoulder")))
            y = _apply_lut(x, lut)
            profile_used = False
        elif use_profile:
            # R24: 复合 LUT (base∘curve), eotf/gamma 与曲线基分支同源
            profile_lut = _get_profile_lut(ctx.prof, eotf, gamma)
            if profile_lut is not None:
                y = _apply_lut(x, profile_lut)
                profile_used = True
            else:
                # 无 DCP 曲线 → 回退曲线基 (精确 sRGB EOTF / 纯 1/2.2 幂)
                y = _apply_lut(x, _get_base_lut(eotf, gamma))
                profile_used = False
        else:
            y = _apply_lut(x, _get_base_lut(eotf, gamma))
            profile_used = False

        # 用户控制点曲线 (T1.4): 在 gamma 域对 EOTF/影调结果施加
        # (rgb → 分通道 → luminance), highlight_compress 之前。
        # user_curve 为嵌套 list/dict (JSON 友好), 结构合法性由 core 参数校验层
        # (_curve_dict_check) + _apply_user_curve 双重把关, 统一走 self.p()。
        user_curve = self.p(ctx, "user_curve", None)
        if user_curve is not None:
            y = _apply_user_curve(y, user_curve)

        # 高光软压缩 (按 wb_B 曲线): 只压 gamma 亮段, 不碰中灰/暗部。
        hc_curve = self.p(ctx, "highlight_compress_curve", None)
        hc_gain = 0.0
        if hc_curve is not None:
            hc_arr = _check_highlight_compress_curve(hc_curve)
            wb = ctx.state.get("wb_cam", ctx.state.get("wb"))
            if wb is not None:
                wb_b = float(wb[2] / max(float(wb[1]), 1e-9))
                hc_gain = float(np.interp(wb_b, hc_arr[:, 0], hc_arr[:, 1]))
        if hc_gain > 0.0:
            L = (y @ _RGB_WEIGHTS).astype(np.float32)
            up = np.clip((L - 0.70) / 0.10, 0.0, 1.0)
            down = np.clip((0.94 - L) / 0.06, 0.0, 1.0)
            up = up * up * (3.0 - 2.0 * up)
            down = down * down * (3.0 - 2.0 * down)
            w = up * down
            y = y * (1.0 - hc_gain * w[..., np.newaxis])
        ctx.set_image(np.clip(y, 0.0, 1.0).astype(np.float32), DOMAIN_GAMMA_RGB)
        ctx.state["tone_highlight_compress"] = hc_gain
        ctx.state["tone_brightness"] = brightness
        ctx.state["tone_profile_curve"] = profile_used
        ctx.state["tone_eotf"] = eotf
