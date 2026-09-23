# R32-T2 RT DCP 处理链对照吸收 —— 数值实验 (dev-1, 2026-09-23)
#
# 目的: 逐环节定量对比 RawTherapee (dcp.cc @ 6c4cb59) 与 pixo clean-room
#       (core/color.py, R11/R12) 的 DCP 数学, 为吸收裁决提供数据。
# 口径: 全部实验锚定真 Adobe DCP (Nikon Z 5 2 Camera Standard v2);
#       patch 集 = 确定性合成 24 色 (含中性梯/肤色/天空/ foliage 近似);
#       ΔE76 = Lab(D50 白) 欧氏距离, 两臂同一变换, 仅作相对比较。
# RT 参考侧 = dcp.cc 数学逐式移植 (测量专用, 非生产代码; GPL 出处:
#   rtengine/dcp.cc @ 6c4cb59, GPLv3 —— xyCoordToTemperature 的
#   Robertson 表取自 DNG SDK 公开参考实现, RT 同源)。
# 产物: .artifacts/_r32_t2_dcp_compare.json
import json
import math
import os
import sys

import numpy as np

ROOT = r"K:/work/project/pixo"
sys.path.insert(0, os.path.join(ROOT, "src"))

from pixo.render.core import color as px  # noqa: E402
from pixo.render.core.calibration import load_dcp  # noqa: E402

DCP_PATH = (r"C:/ProgramData/Adobe/CameraRaw/CameraProfiles/Camera"
            r"/Nikon Z 5 2/Nikon Z 5 2 Camera Standard v2.dcp")
OUT = os.path.join(ROOT, ".artifacts", "_r32_t2_dcp_compare.json")

# ---------------------------------------------------------------------------
# RT 参考实现 (dcp.cc 逐式移植, 测量专用)
# ---------------------------------------------------------------------------

def rt_xy_to_temperature(white_xy):
    """dcp.cc xyCoordToTemperature (DNG SDK Robertson 表) @ 6c4cb59。"""
    temp_table = [
        (0, 0.18006, 0.26352, -0.24341), (10, 0.18066, 0.26589, -0.25479),
        (20, 0.18133, 0.26846, -0.26876), (30, 0.18208, 0.27119, -0.28539),
        (40, 0.18293, 0.27407, -0.30470), (50, 0.18388, 0.27709, -0.32675),
        (60, 0.18494, 0.28021, -0.35156), (70, 0.18611, 0.28342, -0.37915),
        (80, 0.18740, 0.28668, -0.40955), (90, 0.18880, 0.28997, -0.44278),
        (100, 0.19032, 0.29326, -0.47888), (125, 0.19462, 0.30141, -0.58204),
        (150, 0.19962, 0.30921, -0.70471), (175, 0.20525, 0.31647, -0.84901),
        (200, 0.21142, 0.32312, -1.0182), (225, 0.21807, 0.32909, -1.2168),
        (250, 0.22511, 0.33439, -1.4512), (275, 0.23247, 0.33904, -1.7298),
        (300, 0.24010, 0.34308, -2.0637), (325, 0.24702, 0.34655, -2.4681),
        (350, 0.25591, 0.34951, -2.9641), (375, 0.26400, 0.35200, -3.5814),
        (400, 0.27218, 0.35407, -4.3633), (425, 0.28039, 0.35577, -5.3762),
        (450, 0.28863, 0.35714, -6.7262), (475, 0.29685, 0.35823, -8.5955),
        (500, 0.30505, 0.35907, -11.324), (525, 0.31320, 0.35968, -15.628),
        (550, 0.32129, 0.36011, -23.325), (575, 0.32931, 0.36038, -40.770),
        (600, 0.33724, 0.36051, -116.45),
    ]
    x, y = white_xy
    u = 2.0 * x / (1.5 - x + 6.0 * y)
    v = 3.0 * y / (1.5 - x + 6.0 * y)
    res = 0.0
    last_dt = 0.0
    for index in range(1, 31):
        r_, u_, v_, t_ = temp_table[index]
        du, dv = 1.0, t_
        length = math.sqrt(1.0 + dv * dv)
        du /= length
        dv /= length
        uu = u - u_
        vv = v - v_
        dt = -uu * dv + vv * du
        if dt <= 0.0 or index == 30:
            if dt > 0.0:
                dt = 0.0
            dt = -dt
            if index == 1:
                f = 0.0
            else:
                f = dt / (last_dt + dt)
            # mired 倒数插值 (dcp.cc:370)
            res = 1.0e6 / (temp_table[index - 1][0] * f
                           + temp_table[index][0] * (1.0 - f))
            break
        res = r_ * 100.0
        last_dt = dt
    return res


def rt_map_white_matrix(white1, white2):
    """dcp.cc mapWhiteMatrix (DNG SDK MapWhiteMatrix, 线性化 Bradford)。"""
    mb = np.array([[0.8951, 0.2664, -0.1614],
                   [-0.7502, 1.7135, 0.0367],
                   [0.0389, -0.0685, 1.0296]])
    w1 = np.maximum(mb @ np.asarray(white1), 0.0)
    w2 = np.maximum(mb @ np.asarray(white2), 0.0)
    a = np.zeros((3, 3))
    for i in range(3):
        ratio = w2[i] / w1[i] if w1[i] > 0 else 10.0
        a[i, i] = max(0.1, min(ratio, 10.0))
    return np.linalg.inv(mb) @ a @ mb


def rt_xyz_to_xy(xyz):
    total = sum(xyz)
    if total > 0.0:
        return (xyz[0] / total, xyz[1] / total)
    return (0.3457, 0.3585)


def rt_xy_to_xyz(xy):
    x = min(max(xy[0], 0.000001), 0.999999)
    y = min(max(xy[1], 0.000001), 0.999999)
    s = x + y
    if s > 0.999999:
        sc = 0.999999 / s
        x, y = x * sc, y * sc
    return np.array([x / y, 1.0, (1.0 - x - y) / y])


def rt_find_xyz_to_camera(cm1, cm2, t1, t2, white_xy, preferred=0):
    """dcp.cc findXyztoCamera (mix = 1 → illuminant1)。"""
    has1, has2 = cm1 is not None, cm2 is not None
    if preferred == 1 and has1:
        has2 = False
    if preferred == 2 and has2:
        has1 = False
    if has1 and has2:
        wbtemp = rt_xy_to_temperature(white_xy)
        if wbtemp <= t1:
            mix = 1.0
        elif wbtemp >= t2:
            mix = 0.0
        else:
            inv_t = 1.0 / wbtemp
            mix = (inv_t - 1.0 / t2) / (1.0 / t1 - 1.0 / t2)
        if mix >= 1.0:
            return cm1
        if mix <= 0.0:
            return cm2
        return mix * cm1 + (1.0 - mix) * cm2
    return cm1 if has1 else cm2


def rt_neutral_to_xy(neutral, cm1, cm2, t1, t2, preferred=0):
    """dcp.cc neutralToXy (不动点, MAX_PASSES=30, 阈 1e-7)。"""
    last = np.array([0.3457, 0.3585])
    nxt = last.copy()
    for p in range(30):
        m = rt_find_xyz_to_camera(cm1, cm2, t1, t2, last, preferred)
        nxt = rt_xyz_to_xy(np.linalg.inv(m) @ neutral)
        if abs(nxt[0] - last[0]) + abs(nxt[1] - last[1]) < 1e-7:
            return nxt
        if p == 29:
            nxt = (last + nxt) * 0.5
        last = nxt
    return last


_XYZ_SRGB = np.array(px.SRGB_TO_XYZ_D65)


def rt_make_xyz_cam(cm1, cm2, fm1, fm2, t1, t2, neutral, preferred=0):
    """dcp.cc makeXyzCam: 返回 (cam→XYZ D50 矩阵, white_xy, mix)。"""
    white_xy = rt_neutral_to_xy(neutral, cm1, cm2, t1, t2, preferred)
    wbtemp = rt_xy_to_temperature(white_xy)
    if wbtemp <= t1:
        mix = 1.0
    elif wbtemp >= t2:
        mix = 0.0
    else:
        inv_t = 1.0 / wbtemp
        mix = (inv_t - 1.0 / t2) / (1.0 / t1 - 1.0 / t2)
    cm = (cm1 if (cm2 is None or mix >= 1.0)
          else (cm2 if mix <= 0.0 else mix * cm1 + (1.0 - mix) * cm2))
    white_xyz = rt_xy_to_xyz(white_xy)
    has_fwd = fm1 is not None or fm2 is not None
    if has_fwd:
        fwd = (fm1 if (fm2 is None or mix >= 1.0)
               else (fm2 if mix <= 0.0 else mix * fm1 + (1.0 - mix) * fm2))
        camera_white = cm @ white_xyz
        d = np.diag(camera_white)
        cam_xyz = np.linalg.inv(fwd @ np.linalg.inv(d))
    else:
        white_d50 = rt_xy_to_xyz((0.3457, 0.3585))
        cam_xyz = cm @ rt_map_white_matrix(white_d50, white_xyz)
    # dcraw legacy: sRGB 往返 + 行归一化 (dcp.cc 1900-1939)
    cam_rgb = cam_xyz @ _XYZ_SRGB
    for i in range(3):
        cam_rgb[i] /= cam_rgb[i].sum()
    rgb_cam = np.linalg.inv(cam_rgb)
    return _XYZ_SRGB @ rgb_cam, white_xy, mix


# ---------------------------------------------------------------------------
# 公共实验设施
# ---------------------------------------------------------------------------

def macbeth_like_patches():
    """确定性 24 色合成 patch (线性相机 RGB, 已按 WB 白化前→白化后同构)。

    取色: 6 级中性梯 + 肤色/天空/ foliage/砖 等经验色 (sRGB gamma 域设计值
    线性化), 仅作矩阵间相对比较, 不含绝对色度主张。
    """
    srgb_design = [
        (115, 82, 68), (194, 150, 130), (98, 122, 157), (87, 108, 67),
        (133, 128, 177), (103, 189, 170), (214, 126, 44), (80, 91, 166),
        (193, 90, 99), (94, 60, 108), (157, 188, 64), (224, 163, 46),
        (56, 61, 150), (70, 148, 73), (175, 54, 60), (231, 199, 31),
        (187, 86, 149), (8, 133, 161), (243, 243, 242), (200, 200, 200),
        (160, 160, 160), (122, 122, 121), (85, 85, 85), (52, 52, 52),
    ]
    lin = []
    for r, g, b in srgb_design:
        v = np.array([r, g, b], dtype=np.float64) / 255.0
        lin.append(np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4))
    return np.array(lin)


def xyz_d50_to_lab(xyz):
    """XYZ(D50) → Lab (D50 白, 4 位 PCS 白)。"""
    w = np.array(px.xy_to_xyz(*px._PCS_D50_XY))
    t = xyz / w
    eps, kap = 216.0 / 24389.0, 24389.0 / 27.0
    f = np.where(t > eps, np.cbrt(t), (kap * t + 16.0) / 116.0)
    return np.stack([116.0 * f[..., 1] - 16.0,
                     500.0 * (f[..., 0] - f[..., 1]),
                     200.0 * (f[..., 1] - f[..., 2])], axis=-1)


def de76(a, b):
    d = np.sqrt(np.sum((np.asarray(a) - np.asarray(b)) ** 2, axis=-1))
    return d


def wb_from_temp(temp_k, tint=0.0):
    x, y = px.temp_to_xy(temp_k)
    if tint:
        xy = px.temp_tint_to_xy(temp_k, tint)
        x, y = xy
    return px.temp_tint_to_wb(PROF, temp_k, tint)


def mat_stats(m_rt, m_px):
    d = np.abs(m_rt - m_px)
    return {"max_abs_elem": float(d.max()), "mean_abs_elem": float(d.mean())}


# ---------------------------------------------------------------------------
# 实验主体
# ---------------------------------------------------------------------------

PROF = load_dcp(DCP_PATH)


def main():
    results = {"dcp": os.path.basename(DCP_PATH),
               "meta": {"illuminants": [PROF.calibration_illuminant1,
                                        PROF.calibration_illuminant2],
                        "has_cm2": PROF.color_matrix2 is not None,
                        "has_fm2": PROF.forward_matrix2 is not None,
                        "ptc_points": (len(PROF.profile_tone_curve) // 2
                                       if PROF.profile_tone_curve else 0),
                        "baseline_exposure_offset": PROF.baseline_exposure_offset,
                        "look_dims": PROF.look_table_dims,
                        "look_encoding": PROF.look_table_encoding,
                        "hsm_dims": PROF.hue_sat_dims}}
    cm1 = px._mat3(PROF.color_matrix1)
    cm2 = px._mat3(PROF.color_matrix2)
    fm1 = px._mat3(PROF.forward_matrix1)
    fm2 = px._mat3(PROF.forward_matrix2)
    t1, t2 = px._calibration_temperatures(PROF)
    patches = macbeth_like_patches()

    # ---- E1: xy → CCT 三算法对比 ----
    canon = {"A(2856K)": ((0.4476, 0.4074), 2856.0),
             "D50": ((0.3457, 0.3585), 5000.0),
             "D55": ((0.3324, 0.3474), 5503.0),
             "D65": ((0.31271, 0.32902), 6504.0),
             "D75": ((0.29902, 0.31485), 7504.0)}
    bb = []
    for tk in (2000, 2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000, 6500,
               7500, 8500, 10000, 15000, 20000):
        x, y = px.temp_to_xy(float(tk))
        bb.append((f"BB{tk}K", (x, y), float(tk)))
    rows = []
    canon_list = [(name, xy, ref) for name, (xy, ref) in canon.items()]
    for name, (x, y), ref in canon_list + bb:
        rt_t = rt_xy_to_temperature((x, y))
        kim_t = px.temperature_from_xy(x, y)
        mcc_t = px.xy_to_cct(x, y)
        rows.append({"point": name, "xy": [round(x, 5), round(y, 5)],
                     "ref_k": ref,
                     "rt_robertson": round(rt_t, 1),
                     "pixo_kim": round(kim_t, 1),
                     "pixo_mccamy": round(mcc_t, 1),
                     "err_rt": round(rt_t - ref, 1),
                     "err_kim": round(kim_t - ref, 1),
                     "err_mccamy": round(mcc_t - ref, 1)})
    results["e1_cct"] = {
        "note": "ref=命名照明体定义值/黑体轨迹真值; rt=Robertson 表, kim=Kim2002 "
                "最近点, mccamy=McCamy1992 (我方 neutral_to_xy 公开路径在用)",
        "rows": rows,
        "max_abs_err": {"rt_robertson": round(max(abs(r["err_rt"]) for r in rows), 1),
                        "pixo_kim": round(max(abs(r["err_kim"]) for r in rows), 1),
                        "pixo_mccamy": round(max(abs(r["err_mccamy"]) for r in rows), 1)},
    }

    # ---- E2: neutral→xy 不动点 + CM 插值矩阵 (WB 扫描) ----
    e2 = []
    for temp_k in (2800, 3200, 3800, 4500, 5000, 5500, 6500, 7500):
        wb = wb_from_temp(temp_k)
        neutral = px.wb_to_neutral(wb)
        xy_rt = rt_neutral_to_xy(neutral, cm1, cm2, t1, t2)
        xy_kim = px._neutral_to_xy(neutral, PROF)
        xy_mcc = px.neutral_to_xy(neutral, PROF)
        m_rt, _, _ = rt_make_xyz_cam(cm1, cm2, None, None, t1, t2, neutral)
        cm_rt = rt_find_xyz_to_camera(cm1, cm2, t1, t2, xy_rt)
        cm_kim = px._find_matrices(PROF, xy_kim)[0]
        e2.append({
            "wb_temp_k": temp_k,
            "xy_rt": [round(v, 6) for v in xy_rt],
            "xy_kim": [round(v, 6) for v in xy_kim],
            "xy_mccamy": [round(v, 6) for v in xy_mcc],
            "xy_dist_rt_kim": round(math.dist(xy_rt, xy_kim), 7),
            "xy_dist_rt_mccamy": round(math.dist(xy_rt, xy_mcc), 7),
            "cm_max_elem_diff_rt_vs_kim": float(np.abs(cm_rt - cm_kim).max()),
            "wbtemp_rt": round(rt_xy_to_temperature(xy_rt), 1),
            "cct_kim": round(px.temperature_from_xy(*xy_kim), 1),
            "cct_mccamy": round(px.xy_to_cct(*xy_mcc), 1),
        })
    results["e2_neutral_to_xy_cm"] = {
        "note": "wb=合成 neutral (temp_tint_to_wb); 同一 neutral 三路白点迭代; "
                "内部不一致: cam_to_xyz_matrix 走 _neutral_to_xy(Kim), "
                "cct_from_wb/公开 neutral_to_xy 走 McCamy",
        "rows": e2,
    }

    # ---- E3: no-FM 路径 cam→XYZ 矩阵 + patch ΔE ----
    e3 = []
    for temp_k in (3200, 4500, 6500):
        wb = wb_from_temp(temp_k)
        neutral = px.wb_to_neutral(wb)
        m_rt_native, xy_rt, mix = rt_make_xyz_cam(cm1, cm2, None, None, t1, t2,
                                                  neutral)
        # RT 矩阵吃 native 相机值; 我方 patches 为 WB 后值 → 折 diag(1/wb)
        m_rt_wb = m_rt_native @ np.diag(1.0 / np.asarray(wb, dtype=np.float64))
        m_px = px.cam_to_xyz_matrix(PROF, wb)
        xyz_rt = (np.atleast_2d(patches) @ m_rt_wb.T)
        xyz_px = (np.atleast_2d(patches) @ m_px.T)
        de = de76(xyz_d50_to_lab(xyz_rt), xyz_d50_to_lab(xyz_px))
        e3.append({
            "wb_temp_k": temp_k,
            "matrix_diff": mat_stats(m_rt_wb, m_px),
            "patch_de76_mean": round(float(np.mean(de)), 3),
            "patch_de76_max": round(float(np.max(de)), 3),
            "mix": round(mix, 4),
            "gray_rt": np.round(xyz_rt[-1] / xyz_rt[-1].sum(), 5).tolist(),
            "gray_px": np.round(xyz_px[-1] / xyz_px[-1].sum(), 5).tolist(),
        })
    results["e3_cam_to_xyz_cm_path"] = {
        "note": "无 FM 假设下 RT(CM·MapWhiteMatrix + dcraw 遗产 sRGB 往返行归一化, "
                "逐式移植) vs pixo(Bradford(scene→D50)·inv(CM)·diag(1/wb), 规范语义); "
                "patch=24色。关键发现: pixo 灰点恒等于 PCS D50 (规范: 中性白→PCS 白); "
                "RT 灰点随 WB 漂移 (dcraw 行归一化以 sRGB 白为中性基准) —— 见 gray_rt; "
                "ΔE 含该系统性白点差, 为两链真实渲染差 (非测量误差)。RT 的绝对像素域"
                "还依赖 pre_mul/cam_wb_matrix 管道 (本实验不可达), gray 漂移方向为下界。",
        "rows": e3,
    }

    # ---- E4: FM 路径 cam→XYZ 矩阵 + patch ΔE ----
    e4 = []
    for temp_k in (3200, 4500, 6500):
        wb = wb_from_temp(temp_k)
        neutral = px.wb_to_neutral(wb)
        m_rt_native, xy_rt, mix = rt_make_xyz_cam(cm1, cm2, fm1, fm2, t1, t2,
                                                  neutral)
        m_rt_wb = m_rt_native @ np.diag(1.0 / np.asarray(wb, dtype=np.float64))
        m_px = px.cam_to_prophoto_matrix(PROF, wb)
        # 我方 FM 域矩阵出 ProPhoto(D50), 折回 XYZ: pp→PCS 用 4位 ROMM 缩放逆
        pp_m4 = np.asarray(px._ROMM_RGB_TO_XYZ_D50_4)
        s = np.diag(np.asarray(px.xy_to_xyz(*px._PCS_D50_XY)) / (pp_m4 @ np.ones(3)))
        m_px_xyz = np.linalg.inv(s) @ m_px  # WB 后相机 → XYZ(D50)
        xyz_rt = np.atleast_2d(patches) @ m_rt_wb.T
        xyz_px = np.atleast_2d(patches) @ m_px_xyz.T
        de = de76(xyz_d50_to_lab(xyz_rt), xyz_d50_to_lab(xyz_px))
        e4.append({
            "wb_temp_k": temp_k,
            "matrix_diff": mat_stats(m_rt_wb, m_px_xyz),
            "patch_de76_mean": round(float(np.mean(de)), 3),
            "patch_de76_max": round(float(np.max(de)), 3),
            "gray_rt": np.round(xyz_rt[-1] / xyz_rt[-1].sum(), 5).tolist(),
            "gray_px": np.round(xyz_px[-1] / xyz_px[-1].sum(), 5).tolist(),
        })
    results["e4_cam_to_xyz_fm_path"] = {
        "note": "勘误 (R32-T2 reviewer 限向修订): 初稿曾把 RT dcp.cc:1892 的"
                "无 FM 分支 MapWhiteMatrix 源白点常量 {0.3457,0.3585,0.2958}"
                "(=PCS D50) 误写为 'FM1@(1,1,1)=D50 逐位验证' —— 本脚本无该"
                "断言, 且 RT 字面构造复算 (四种输入折叠) 灰点均 ≠ D50 (见 rows"
                ".gray_rt)。如实表述: (a) 该常量是无 FM 分支的源白点; (b) FM "
                "语义 (Adobe 构造 FM 使 FM·(1,1,1)=D50 白) 与 pixo "
                "cam_to_prophoto_matrix 的白点缩放构造方向一致, 但 RT 生产链的"
                "等效输入域依赖 pre_mul/cam_wb_matrix 管道 (静态读码不可达), "
                "gray_rt 漂移即其表现; ΔE 含该系统差, 逐像素对齐需 RT 全管线"
                "复刻, 超出矩阵级对照范围。",
        "rows": e4,
    }

    # ---- E5: PTC 曲线形状与施加语义 ----
    ptc = PROF.profile_tone_curve
    xs = np.array(ptc[0::2], dtype=np.float64)
    ys = np.array(ptc[1::2], dtype=np.float64)
    grid = np.linspace(0.0, 1.0, 4097)
    lin = np.interp(grid, xs, ys)
    try:
        from scipy.interpolate import PchipInterpolator
        pchip = PchipInterpolator(xs, ys)(grid)
        spline_note = "RT DiagonalCurve(DCT_Spline) 以 monotone PCHIP 代理 (同为保单调三次)"
    except ImportError:  # pragma: no cover
        pchip = lin
        spline_note = "scipy 缺失, 退化线性"
    lut_lin = lin
    base = px.__dict__.get("srgb_encode")
    base_lut = np.where(grid <= 0.0031308, 12.92 * grid,
                        1.055 * np.power(grid, 1.0 / 2.4) - 0.055)
    results["e5_ptc"] = {
        "note": spline_note + "; 施加语义: RT=AdobeToneCurve (max/min 过 LUT, "
                "med 保色相线性重推, ProPhoto 域, 65535 尺) vs pixo=tone stage "
                "per-channel LUT 复合 base∘curve (R24); 此处量曲线形状差",
        "n_points": len(xs),
        "lin_vs_pchip_max_abs": round(float(np.abs(lin - pchip).max()), 5),
        "lin_vs_pchip_mean_abs": round(float(np.abs(lin - pchip).mean()), 6),
        "curve_lut_endpoints": {"y0": float(lin[0]), "y1": float(lin[-1])},
        "adobe_default_curve_injection": {
            "rt": "Adobe Systems 版权 + 无 ProfileToneCurve tag → 注入 ACR 默认曲线",
            "pixo": "无 tag → 不施加 PTC (parse_profile_curve=None)",
            "this_dcp": "有 125 点 tag, 不触发注入",
        },
    }

    # ---- E6: baseline exposure 施加点 ----
    bloe = PROF.baseline_exposure_offset
    scale = 2.0 ** bloe
    probe = np.array([0.02, 0.05, 0.1, 0.18, 0.3, 0.5, 0.7, 0.9])
    after_ptc = np.interp(probe * scale, grid, lin)
    before_ptc = np.interp(probe, grid, lin) * scale
    enc = np.where(after_ptc <= 0.0031308, 12.92 * after_ptc,
                   1.055 * np.power(after_ptc, 1 / 2.4) - 0.055)
    enc_b = np.where(before_ptc <= 0.0031308, 12.92 * before_ptc,
                     1.055 * np.power(before_ptc, 1 / 2.4) - 0.055)
    results["e6_baseline_exposure"] = {
        "offset_ev": bloe,
        "scale": round(scale, 5),
        "rt": "×2^bloe 在 ProPhoto 域、LookTable/PTC 之前 (step2ApplyTile)",
        "pixo": "exposure Stage ev += offset (线性域增益, 矩阵后/PTC LUT 前——"
                "域与顺序均不同, 见 tone_map Stage)",
        "order_effect_max_gamma_delta": round(float(np.abs(enc - enc_b).max()), 5),
        "order_effect_note": "先乘后过曲线 vs 先过曲线后乘 的编码输出最大差 "
                             "(probe 梯度, PTC 非线性 ⇒ 顺序不可交换)",
    }

    # ---- E7: LookTable/HSM 底座缺位幅度 ----
    e7 = {"note": "pixo 底座链当前不消费 DCP LookTable/HueSatMap (R11 A 轨退役; "
                  "huesat Stage B 轨=用户可选 OKLCh 形变, 非底座); "
                  "RT 对含 LookTable 的 DCP 在 step2 ProPhoto 域应用。",
          "this_dcp_look_dims": PROF.look_table_dims,
          "quantification": "定性 (RT hsdApply 移植含 3D 三线性+sRGB v 编码, "
                            "量幅度需完整表应用链, 留待吸收项落地后随附)"}
    results["e7_looktable_hsm_gap"] = e7

    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=1)
    print("saved:", OUT)
    print(json.dumps(results["e1_cct"]["max_abs_err"], indent=1))


if __name__ == "__main__":
    main()
