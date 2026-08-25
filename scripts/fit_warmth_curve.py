"""拟合分桶暖度曲线 warmth_curve.json —— WB 分桶 · 0355 偏色治理 (t14)。

以 RAW 内嵌缩略图为色彩真值: 对样本在不同 whitebalance.warmth_curve 结点下
全链渲染, 最小化 Lab da/db 偏差, 拟合按 wb_B 分段的 [wb_B, r, g, b] 增益结点。
产物 configs/calibration/warmth_curve.json 由 WhiteBalanceStage 的 warm_cal_file
开关缺省加载 (文件存在即生效); 文件缺失时 Stage 回退内置斜率模型, 行为兼容。

方法: 每个样本在键 b=wb_B/wb_G 处放一个结点, 用有限差分测 (r,g,b) 三通道
结点增量 → (da,db) 的雅可比, 最小二乘解结点增量; 曲线两端补斜率模型等效结点,
未采样区段保持旧行为。结点经 Stage 的 warmth 缩放生效 (gain=1+warmth*(knot-1)),
故全部测量都在生产默认参数 (warmth=0.9, brightness=0.25) 下进行。

用法:
  python scripts/fit_warmth_curve.py --baseline   # 仅打印基线 da/db
  python scripts/fit_warmth_curve.py              # 拟合+验收报告 (不写文件)
  python scripts/fit_warmth_curve.py --write      # 拟合并写 configs/calibration/
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pixo.render.api import Renderer  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
CAL_PATH = REPO / "configs" / "calibration" / "warmth_curve.json"

# 样本: 0355 为治理目标 (基线 da-12/db+14.5), 0711 室内两张对照 (5236 是验收门禁)
SAMPLES = [
    ("0355", "K:/data/photo/2026春节/DSC_0355.NEF"),
    ("0352", "K:/data/photo/2026春节/DSC_0352.NEF"),
    ("5236", "K:/data/photo/0711/raw/DSC_5236.NEF"),
    ("5239", "K:/data/photo/0711/raw/DSC_5239.NEF"),
]
GATES = {"0355": (6.0, 6.0), "5236": (5.0, None)}  # (|da|<=, |db|<=)
# 留出验证 (t17 评审③-2): 不参与拟合, --write 前须过 |da| 门禁
HOLDOUTS = [
    ("6007", "K:/data/photo/0711/raw/DSC_6007.NEF"),
    ("0360", "K:/data/photo/2026春节/DSC_0360.NEF"),
]
HOLDOUT_GATE = {"6007": 6.0}  # 未列出的留出样本仅观测打印
BASE_PARAMS = {"tone": {"brightness": 0.25}}       # P0 标准观感
EPS = 0.04      # 灵敏度有限差分步长 (结点空间)
LONG_EDGE = 512


def cam_thumb(p: Path) -> np.ndarray:
    """RAW 内嵌预览 (RGB u8, 已按 EXIF 方向摆正) —— 色彩真值。"""
    import rawpy
    with rawpy.imread(str(p)) as raw:
        t = raw.extract_thumb()
        if t.format == rawpy.ThumbFormat.JPEG:
            bgr = cv2.imdecode(np.frombuffer(t.data, np.uint8), cv2.IMREAD_COLOR)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        else:
            rgb = np.asarray(t.data)[..., :3].copy()
    rot = {3: cv2.ROTATE_180, 6: cv2.ROTATE_90_CLOCKWISE,
           8: cv2.ROTATE_90_COUNTERCLOCKWISE}
    from pixo.meta import extract as ex
    o = int(ex(p)["capture"].get("orientation") or 1)
    if o in rot:
        rgb = cv2.rotate(rgb, rot[o])
    return rgb


def lab_offsets(ours_u8, ref_u8):
    """渲染 vs 参考的平均 (dL, da, db)。"""
    h = min(ours_u8.shape[0], ref_u8.shape[0])
    w = min(ours_u8.shape[1], ref_u8.shape[1])
    a = cv2.resize(ours_u8, (w, h), interpolation=cv2.INTER_AREA)
    b = cv2.resize(ref_u8, (w, h), interpolation=cv2.INTER_AREA)
    la = cv2.cvtColor(a, cv2.COLOR_RGB2LAB).astype(np.float32)
    lb = cv2.cvtColor(b, cv2.COLOR_RGB2LAB).astype(np.float32)
    d = la - lb
    return (float(d[..., 0].mean()), float(d[..., 1].mean()),
            float(d[..., 2].mean()))


def render_rgb(p, r, extra=None):
    """生产默认观感参数 (+可选 whitebalance 覆盖) 的全链渲染 RGB u8。"""
    params = {k: dict(v) for k, v in BASE_PARAMS.items()}
    for k, v in (extra or {}).items():
        params.setdefault(k, {}).update(v)
    return r.render_preview_full(str(p), long_edge=LONG_EDGE, params=params)


def measure(p, r, extra=None):
    return lab_offsets(render_rgb(p, r, extra), cam_thumb(Path(p)))


def wb_b_key(p: Path, r) -> float:
    """相机 WB 蓝系数 b = wb_B/wb_G (暖度模型分桶键, apply_warmth 校正前)。"""
    from pixo.render.pipeline.context import StageContext, DOMAIN_LINEAR_CAM
    from pixo.render.core.io import decode_cfa_half, camera_neutral_wb_cached
    from pixo.render.modules.white_balance import WhiteBalanceStage
    import rawpy
    with rawpy.imread(str(p)) as raw:
        img = decode_cfa_half(raw, raw_path=p)
        ctx = StageContext(p, raw=raw, prof=r.profile, config={})
        ctx.set_image(img, DOMAIN_LINEAR_CAM)
        ctx.state["camera_wb"] = camera_neutral_wb_cached(raw, p)
    WhiteBalanceStage().run(ctx)  # 官方入口; wb_cam 存校正前相机 WB
    wb = np.asarray(ctx.state["wb_cam"], dtype=np.float64)
    return float(wb[2] / max(float(wb[1]), 1e-9))


def curve_param(knots):
    """结点列表 → whitebalance.warmth_curve 参数 (float_or_str 放行数值嵌套表)。"""
    return {"whitebalance": {"warmth_curve": [[round(float(x), 5) for x in k]
                                              for k in knots]}}


def probe_curve(b_key, dr=0.0, dg=0.0, db=0.0):
    """以 b_key 为中心的 ≥3 结点探针曲线 (满足结点≥2 且严格递增校验)。"""
    lo = min(1.05, b_key - 0.05)
    hi = max(2.60, b_key + 0.05)
    base = [1.0 + dr, 1.0 + dg, 1.0 + db]
    return [[lo, 1.0, 1.0, 1.0], [b_key] + base, [hi, 1.0, 1.0, 1.0]]


def neutral_ref(p, r, b_key):
    """中性结点 (gain=1) 探针渲染偏移 —— 雅可比与求解的共同参考态。

    t17 评审③-1: 扰动响应以中性结点曲线为基准, 若改用无曲线斜率基线,
    差分会混入 (中性 - 斜率基线)/EPS 的常数偏置。斜率基线仅作报告口径。
    """
    return measure(p, r, curve_param(probe_curve(b_key)))


def sensitivity(p, r, b_key, ref_off):
    """雅可比 J[3x2]: 结点 (r,g,b) 单位增量 -> (da,db) 响应 (成对有限差分)。

    ref_off 必须来自同一参考态的中性结点探针渲染 (neutral_ref)。
    """
    j = np.zeros((3, 2), dtype=np.float64)
    for c in range(3):
        d = [0.0, 0.0, 0.0]
        d[c] = EPS
        _, da, db = measure(p, r, curve_param(probe_curve(b_key, *d)))
        j[c] = ((da - ref_off[1]) / EPS, (db - ref_off[2]) / EPS)
    return j


def slope_equiv_knot(b, warmth=0.9):
    """内置斜率模型在键 b 的等效结点 (再经 Stage warmth 缩放后与旧行为等价)。"""
    from pixo.render.modules.white_balance import (WARMTH_B0_FROZEN,
                                                  WARMTH_B1_FROZEN,
                                                  WARMTH_DAY_BAND)
    b0, b1 = WARMTH_B0_FROZEN, WARMTH_B1_FROZEN
    s = float(np.clip((b - b0) / max(b1 - b0, 1e-9), 0.0, 1.0)) * warmth
    s2 = float(np.clip((b0 - b) / max(WARMTH_DAY_BAND, 1e-9), 0.0, 1.0)) * warmth
    gains = [(1.0 - 0.25 * s2) * (1.0 + 0.0 * s),
             1.0 + 0.10 * s, 1.0 - 0.26 * s]
    return [round(float(b), 4)] + [round(1.0 + (g - 1.0) / warmth, 5)
                                   for g in gains]


def build_curve(keys, deltas, warmth=0.9):
    """样本结点 (+两端斜率等效垫片) → 排序/去重/带界后的曲线。

    keys: {name: b_key}; deltas: {name: (dr,dg,db)} 结点空间增量。
    近邻键 (<0.03) 合并取均值; 增益钳制 [0.55,1.45] (留界内余量)。
    """
    pts = {}
    order = sorted(keys.items(), key=lambda kv: kv[1])
    merged = []
    for name, b in order:
        if merged and abs(b - merged[-1][1]) < 0.03:
            n0, b0 = merged[-1]
            merged[-1] = (n0 + "+" + name, (b0 + b) / 2.0)
        else:
            merged.append((name, b))
    for name, b in merged:
        names = name.split("+")
        d = np.mean([deltas[n] for n in names], axis=0)
        knot = [1.0 + float(x) for x in d]
        knot = [float(np.clip(x, 0.55, 1.45)) for x in knot]
        pts[round(float(b), 4)] = knot
    lo_b = min(pts) - 0.08
    hi_b = max(pts) + 0.08
    for pad_b in (lo_b, hi_b):
        eq = slope_equiv_knot(pad_b, warmth)
        if all(abs(pad_b - k) > 0.01 for k in pts):
            pts[round(pad_b, 4)] = eq[1:]
    out = [[b] + pts[b] for b in sorted(pts)]
    assert len(out) >= 2 and all(out[i][0] < out[i + 1][0]
                                 for i in range(len(out) - 1))
    return out


def solve_deltas(names, errs, jacob):
    """min-norm 最小二乘: 每样本 delta = -pinv(J) @ (da,db)。"""
    deltas = {}
    for n in names:
        e = np.array(errs[n][1:], dtype=np.float64)  # (da,db)
        deltas[n] = tuple(np.linalg.pinv(jacob[n].T) @ (-e))
    return deltas


def verify(r, knots, keys, tag=""):
    """用给定曲线渲染全部样本并对照门禁; 返回 (是否全过, 行数据)。"""
    extra = curve_param(knots) if knots else None
    print(f"--- 验收[{tag}] warmth=0.9 brightness=0.25 ---")
    ok_all = True
    rows = {}
    for name, p in SAMPLES:
        dL, da, db = measure(Path(p), r, extra)
        g_da, g_db = GATES.get(name, (None, None))
        verdict = []
        if g_da is not None:
            okd = abs(da) <= g_da
            verdict.append(f"|da|<={g_da}:{'PASS' if okd else 'FAIL'}")
            ok_all = ok_all and okd
        if g_db is not None:
            okd = abs(db) <= g_db
            verdict.append(f"|db|<={g_db}:{'PASS' if okd else 'FAIL'}")
            ok_all = ok_all and okd
        print(f"  {name} b={keys[name]:.3f} da={da:+.2f} db={db:+.2f} "
              f"{' '.join(verdict) if verdict else '(观测)'}")
        rows[name] = {"b_key": round(keys[name], 4), "dL": round(dL, 2),
                      "da": round(da, 2), "db": round(db, 2)}
    return ok_all, rows


def main():
    args = sys.argv[1:]
    write = "--write" in args
    baseline_only = "--baseline" in args
    dcp = sorted((REPO / "resources" / "dcp").glob("*.dcp"))[0]
    r = Renderer(dcp)
    names = [n for n, _ in SAMPLES]
    paths = dict(SAMPLES)
    keys = {n: wb_b_key(Path(paths[n]), r) for n in names}
    for n in names:
        print(f"{n}: wb_B 键 = {keys[n]:.4f}")
    errs = {n: measure(Path(paths[n]), r) for n in names}
    for n in names:
        print(f"{n}: 基线 dL={errs[n][0]:+.2f} da={errs[n][1]:+.2f} "
              f"db={errs[n][2]:+.2f}")
    if baseline_only:
        return
    # 参考态统一 (t17 评审③-1): 求解误差与雅可比同用中性结点参考态;
    # 斜率基线 errs 仅作报告/前后对比口径, 不进求解。
    refs = {n: neutral_ref(Path(paths[n]), r, keys[n]) for n in names}
    jacob = {n: sensitivity(Path(paths[n]), r, keys[n], refs[n]) for n in names}
    deltas = solve_deltas(names, refs, jacob)
    knots = build_curve(keys, deltas)
    print("拟合曲线 v1:", knots)
    ok, rows = verify(r, knots, keys, "v1")
    res = {n: measure(Path(paths[n]), r, curve_param(knots)) for n in names}
    deltas2 = {}
    for n in names:
        e = np.array(res[n][1:], dtype=np.float64)
        dd = np.linalg.pinv(jacob[n].T) @ (-e)
        deltas2[n] = tuple(np.asarray(deltas[n]) + dd)
    knots2 = build_curve(keys, deltas2)
    if knots2 != knots:
        print("拟合曲线 v2:", knots2)
        ok, rows = verify(r, knots2, keys, "v2-final")
        knots = knots2
    # 留出验证 (t17 评审③-2): 只验不学
    print("--- 留出验证 (未参与拟合) ---")
    ho_ok = True
    ho_rows = {}
    for hname, hp in HOLDOUTS:
        if not Path(hp).exists():
            print(f"  {hname}: 文件缺失, 跳过")
            continue
        hdL, hda, hdb = measure(Path(hp), r, curve_param(knots))
        hg = HOLDOUT_GATE.get(hname)
        okh = True if hg is None else abs(hda) <= hg
        ho_ok = ho_ok and okh
        tag = f"|da|<={hg}:{'PASS' if okh else 'FAIL'}" if hg else "(观测)"
        print(f"  {hname} da={hda:+.2f} db={hdb:+.2f} {tag}")
        ho_rows[hname] = {"dL": round(hdL, 2), "da": round(hda, 2),
                          "db": round(hdb, 2)}
    ok = ok and ho_ok
    print("总体(含留出):", "PASS" if ok else "FAIL")
    if write and not ok:
        print("门禁未过, 拒绝写入", CAL_PATH)
        return
    if write:
        CAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        fit_b = [keys[n] for n in names]
        doc = {
            "version": 1,
            "type": "warmth_curve",
            "knots": [[float(x) for x in k] for k in knots],
            "_domain": {"wb_B": [round(min(fit_b), 4), round(max(fit_b), 4)],
                        "note": "拟合样本覆盖域; 域外由端点垫片承接(近似斜率模型)"},
            "meta": {
                "holdouts": ho_rows,
                "source": "scripts/fit_warmth_curve.py",
                "truth": "RAW 内嵌缩略图 Lab 均值",
                "assumes": {"warmth": 0.9, "tone.brightness": 0.25},
                "samples": rows,
                "gates": {"DSC_0355": "|da|<=6 且 |db|<=6",
                          "DSC_5236": "|da|<=5"},
                "note": "结点经 Stage warmth 缩放生效 gain=1+warmth*(knot-1)",
            },
        }
        with open(CAL_PATH, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        print("wrote", CAL_PATH)


if __name__ == "__main__":
    main()
