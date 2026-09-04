"""θ 上下料 —— 五组件 configs 双向序列化 (阶段二 t31, OWN_PIPELINE_STAGE2_DESIGN §2)。

    θ = { warmth_knots[5], exposure_table[2D], neutral_curves,
          rp_ccm_coeff[18], skin_ellipse[5] }

从现有标定 JSON 加载初值供 t30 可微代理/t32 优化器取参; 优化后按**原 schema**
写回 ``configs/color/calib_out/`` (不覆盖源文件, 对照留档)。

五组件数据源与运行时消费方 (字段名逐一与 src/pixo 加载代码对齐, 本模块不 import
src —— src 侧只读 target_offset.json 这个数据文件):

  component        初值来源                                          运行时消费 (字段语义)
  ---------------  ------------------------------------------------  --------------------------------
  warmth_knots     configs/calibration/warmth_curve.json  "knots"    white_balance._load_warm_cal:
                   [[wb_B, gain_r, gain_g, gain_b] × n]              gain=1+warmth·(knot-1); wb_B 严格
                                                                     递增, 增益带界 [0.5, 1.5]
  exposure_table   src/pixo/render/target_offset.json     "cal_table" exposure._load_cal_table/_cal_ev:
                   [[m_log2, wb_B, ev] × n] (二维表)                 med 主键插值 + wb_B(±0.3 邻域)二次
                                                                     插值; 同 "probe_hi" 探针诊断随写
  neutral_curves   resources/camera_profiles/                        color_cal Stage ← calibration.
                   z5ii_neutral_trim.json                            camera_look_curves: 按 CCT 桶间
                   "default" + "by_cct" 的 neutral_a/b_curve         线性插值取 (a,b) 曲线 (7 点, u8
                                                                     Lab 偏移, L 中心 8..248)
  rp_ccm_coeff     configs/color/rp_ccm_nikon_z5_2.json   "matrix"   core.rp_ccm.apply_rp_ccm:
                   (3, 6) 行主序, out = features @ M.T               线性 sRGB, 根多项式保曝光不变
  skin_ellipse     configs/color/skin_oklab.json          "constants" core.skin.skin_mask_oklab (常量
                   SKIN_OKLAB_{A,B,MAJOR,MINOR,ANGLE}                硬编码镜像): OKLab 椭圆 (a, b,
                                                                     major, minor, angle[弧度])

写回契约:
  - 只替换 θ 字段, 其余字段 (meta/拟合报告/域标注…) 从源 doc 原样保留 —— 初值
    (θ 未动) 落盘的文件与源文件 JSON 值级全等, 便于 calib_out vs 源 diff 对照;
  - 落盘格式沿用各源文件既有风格 (warmth/rp_ccm/skin indent=2, neutral indent=1,
    target_offset 紧凑单行), 拒绝写到任何源文件路径上 (ValueError);
  - 精度契约: load→save→load 对 θ **数值逐位恒等** (float64 tobytes 级)。
    skin 角度以 constants 的弧度值为权威原样写回; "new_ellipse_fit.angle_deg"
    为报告字段, 若角度经拟合脚本的 4 位小数惯例往返无损则沿用惯例写法, 否则写
    全精度度数 (两种情况 constants 弧度都逐位等于 θ, 重载不受影响)。
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]

# θ 五组件键序 (loss/优化器的固定排序依据)
SOURCE_KEYS = ("warmth_knots", "exposure_table", "neutral_curves",
               "rp_ccm_coeff", "skin_ellipse")

# 初值来源 (运行时实际加载位置, 见模块 docstring)
DEFAULT_SOURCES: dict[str, Path] = {
    "warmth_knots": REPO_ROOT / "configs" / "calibration" / "warmth_curve.json",
    "exposure_table": REPO_ROOT / "src" / "pixo" / "render" / "target_offset.json",
    "neutral_curves": REPO_ROOT / "resources" / "camera_profiles" / "z5ii_neutral_trim.json",
    "rp_ccm_coeff": REPO_ROOT / "configs" / "color" / "rp_ccm_nikon_z5_2.json",
    "skin_ellipse": REPO_ROOT / "configs" / "color" / "skin_oklab.json",
}

# 写回文件名 (calib_out 内与源同名, reload 按同表映射)
OUT_NAMES: dict[str, str] = {
    "warmth_knots": "warmth_curve.json",
    "exposure_table": "target_offset.json",
    "neutral_curves": "z5ii_neutral_trim.json",
    "rp_ccm_coeff": "rp_ccm_nikon_z5_2.json",
    "skin_ellipse": "skin_oklab.json",
}

# 各文件落盘风格 (对齐既有生产者的 json.dump 调用)
_DUMP_INDENT = {"warmth_knots": 2, "exposure_table": None,
                "neutral_curves": 1, "rp_ccm_coeff": 2, "skin_ellipse": 2}

# warmth 增益带界 (与 white_balance._check_warmth_curve 一致)
_WARM_GAIN_LO, _WARM_GAIN_HI = 0.5, 1.5

# RP-CCM 项集 (与 core.rp_ccm.RP_TERMS 一致; 此处硬编码避免 scripts → src 依赖)
_RP_TERMS: dict[int, tuple[str, ...]] = {
    1: ("r", "g", "b"),
    2: ("r", "g", "b", "sqrt(rg)", "sqrt(rb)", "sqrt(gb)"),
}


@dataclass
class Theta:
    """θ 五组件 (float64 numpy 视图) + 写回模板。

    数组字段是优化器的参数载体; ``docs`` 是五个源 JSON 的原始解析结果
    (save 时 deepcopy 后替换 θ 字段, 非 θ 字段原样保留), ``sources`` 记录
    初值路径供防覆盖守卫与溯源。
    """

    warmth_knots: np.ndarray        # (n≥2, 4) [wb_B, gain_r, gain_g, gain_b]
    warmth_domain: tuple | None     # warmth_curve._domain.wb_B [lo, hi] (非 θ, 随写)
    exposure_table: np.ndarray      # (n≥3, 3) [m_log2, wb_B, ev] (二维表)
    probe_hi: np.ndarray | None     # (n, 3) 探针 p99 诊断 (非 θ, 随写)
    neutral_default: np.ndarray     # (2, m) [a_curve; b_curve]
    neutral_cct: np.ndarray         # (k,) by_cct 桶中心 (K)
    neutral_by_cct: np.ndarray      # (k, 2, m) 各桶 [a_curve; b_curve]
    rp_ccm_coeff: np.ndarray        # (3, t) degree 2 → t=6 → 18 系数
    rp_ccm_degree: int              # 1 | 2
    skin_ellipse: np.ndarray        # (5,) [a, b, major, minor, angle_rad]
    docs: dict = field(default_factory=dict, repr=False, compare=False)
    sources: dict = field(default_factory=dict, repr=False, compare=False)


# ---------------------------------------------------------------------------
# 加载
# ---------------------------------------------------------------------------

def _read_json(path: str | Path) -> tuple[dict, Path]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"标定 JSON 不存在: {p}")
    doc = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"{p}: 顶层不是 JSON object")
    return doc, p


def _finite(arr: np.ndarray, what: str) -> np.ndarray:
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{what} 含 NaN/Inf")
    return arr


def _theta_from_docs(docs: dict[str, dict],
                     sources: dict[str, Path] | None = None) -> Theta:
    """五个源 doc → Theta (含全量结构/带界校验, 与运行时加载规则对齐)。"""
    # -- warmth_knots: [[wb_B, r, g, b], ...] (white_balance._check_warmth_curve) --
    knots = np.asarray(docs["warmth_knots"].get("knots"), dtype=np.float64)
    if knots.ndim != 2 or knots.shape[1] != 4 or knots.shape[0] < 2:
        raise ValueError(
            f"warmth knots 需 (n≥2, 4) [[wb_B, r, g, b]], 实际 shape={knots.shape}")
    _finite(knots, "warmth knots")
    if not np.all(np.diff(knots[:, 0]) > 0):
        raise ValueError("warmth knots 结点 wb_B 必须严格递增")
    if knots[:, 1:].min() < _WARM_GAIN_LO or knots[:, 1:].max() > _WARM_GAIN_HI:
        raise ValueError(f"warmth knots 增益必须在 [{_WARM_GAIN_LO}, "
                         f"{_WARM_GAIN_HI}] 内")
    dom = (docs["warmth_knots"].get("_domain") or {}).get("wb_B")
    warmth_domain = None
    if (isinstance(dom, (list, tuple)) and len(dom) == 2 and dom[0] < dom[1]):
        warmth_domain = (float(dom[0]), float(dom[1]))

    # -- exposure_table: [[m_log2, wb_B, ev], ...] (exposure._load_cal_table) --
    tbl = docs["exposure_table"].get("cal_table")
    widths = {len(r) for r in tbl}
    if widths != {3} or len(tbl) < 3:
        raise ValueError(
            f"exposure cal_table 需 ≥3 行 [m_log2, wb_B, ev] (二维表), "
            f"实际 {len(tbl)} 行, 行宽 {sorted(widths)}")
    table = _finite(np.asarray(tbl, dtype=np.float64), "exposure cal_table")

    probe_rows = docs["exposure_table"].get("probe_hi")
    probe_hi = None
    if probe_rows:
        if {len(r) for r in probe_rows} != {3}:
            raise ValueError("probe_hi 行宽需为 3 [m_log2, wb_B, p99]")
        probe_hi = _finite(np.asarray(probe_rows, dtype=np.float64), "probe_hi")

    # -- neutral_curves: default + by_cct (calibration.camera_look_curves) --
    nd = docs["neutral_curves"].get("default")
    if not isinstance(nd, dict):
        raise ValueError("neutral_curves 缺 \"default\" 桶")
    curves2d, centers = [], []
    a0, b0 = nd.get("neutral_a_curve"), nd.get("neutral_b_curve")
    if not a0 or not b0:
        raise ValueError("neutral default 桶缺 neutral_a_curve/neutral_b_curve")
    curves2d.append((a0, b0))
    for item in docs["neutral_curves"].get("by_cct") or []:
        cct, entry = float(item[0]), item[1] if isinstance(item[1], dict) else {}
        a, b = entry.get("neutral_a_curve"), entry.get("neutral_b_curve")
        if not a or not b:
            raise ValueError(f"neutral by_cct 桶 cct={cct} 缺 a/b 曲线")
        centers.append(cct)
        curves2d.append((a, b))
    lens = {len(a) for a, _ in curves2d} | {len(b) for _, b in curves2d}
    if len(lens) != 1 or min(lens) < 2:
        raise ValueError(f"neutral 曲线长度需全一致且 ≥2, 实际 {sorted(lens)}")
    pairs = [np.asarray([a, b], dtype=np.float64) for a, b in curves2d]
    _finite(pairs[0], "neutral default curves")
    neutral_default = pairs[0]                          # (2, m)
    neutral_cct = np.asarray(centers, dtype=np.float64)
    neutral_by_cct = (np.stack(pairs[1:], axis=0)       # (k, 2, m)
                      if centers else np.zeros((0, 2, neutral_default.shape[1])))

    # -- rp_ccm_coeff: (3, t) matrix (core.rp_ccm.RPCCM.from_dict 同规) --
    rd = docs["rp_ccm_coeff"]
    if rd.get("type") != "pixo_rp_ccm" or int(rd.get("version", 0)) != 1:
        raise ValueError("rp_ccm JSON 缺 type='pixo_rp_ccm'/version=1")
    degree = int(rd["degree"])
    if degree not in _RP_TERMS or list(rd.get("terms") or []) != list(_RP_TERMS[degree]):
        raise ValueError(f"rp_ccm degree/terms 与项集表不符: degree={degree!r}")
    matrix = np.asarray(rd["matrix"], dtype=np.float64)
    if matrix.shape != (3, len(_RP_TERMS[degree])):
        raise ValueError(f"rp_ccm matrix 形状需 (3, {len(_RP_TERMS[degree])}), "
                         f"实际 {matrix.shape}")
    _finite(matrix, "rp_ccm matrix")

    # -- skin_ellipse: constants 五常数 (core.skin 硬编码镜像的权威源) --
    sc = docs["skin_ellipse"].get("constants") or {}
    ellipse = np.asarray(
        [sc.get("SKIN_OKLAB_A"), sc.get("SKIN_OKLAB_B"),
         sc.get("SKIN_OKLAB_MAJOR"), sc.get("SKIN_OKLAB_MINOR"),
         sc.get("SKIN_OKLAB_ANGLE")], dtype=np.float64)
    if ellipse.shape != (5,) or not np.all(np.isfinite(ellipse)):
        raise ValueError("skin constants 缺 SKIN_OKLAB_{A,B,MAJOR,MINOR,ANGLE} 或含非有限值")
    if ellipse[2] <= 0 or ellipse[3] <= 0:
        raise ValueError(f"skin 椭圆轴长必须为正, major/minor={ellipse[2]}/{ellipse[3]}")

    return Theta(
        warmth_knots=knots, warmth_domain=warmth_domain,
        exposure_table=table, probe_hi=probe_hi,
        neutral_default=neutral_default, neutral_cct=neutral_cct,
        neutral_by_cct=neutral_by_cct,
        rp_ccm_coeff=matrix, rp_ccm_degree=degree,
        skin_ellipse=ellipse,
        docs=docs,
        sources=dict(sources or {}),
    )


def load_theta(paths: dict[str, str | Path] | None = None) -> Theta:
    """从五个源 JSON 加载 θ 初值; ``paths`` 可按组件键覆盖来源路径。"""
    src = {k: Path((paths or {}).get(k, DEFAULT_SOURCES[k])) for k in SOURCE_KEYS}
    docs = {}
    for key in SOURCE_KEYS:
        docs[key], _ = _read_json(src[key])
    return _theta_from_docs(docs, src)


# ---------------------------------------------------------------------------
# 写回
# ---------------------------------------------------------------------------

def _validate(theta: Theta) -> None:
    """save 前全量校验 (load 侧规则复用; 就地改参后的非法值在此拦截)。"""
    _theta_from_docs(_theta_to_docs(theta), None)


def _theta_to_docs(theta: Theta) -> dict[str, dict]:
    """θ 数组 → 五组件"瘦 doc" (仅 θ 字段, 供校验/写回替换)。"""
    docs: dict[str, dict] = {}
    docs["warmth_knots"] = {
        "knots": [[float(x) for x in row] for row in theta.warmth_knots],
        "_domain": ({"wb_B": [theta.warmth_domain[0], theta.warmth_domain[1]]}
                    if theta.warmth_domain is not None else {}),
    }
    docs["exposure_table"] = {
        "cal_table": [[float(x) for x in row] for row in theta.exposure_table],
        **({"probe_hi": [[float(x) for x in row] for row in theta.probe_hi]}
           if theta.probe_hi is not None else {}),
    }
    nd = {"neutral_a_curve": [float(x) for x in theta.neutral_default[0]],
          "neutral_b_curve": [float(x) for x in theta.neutral_default[1]]}
    by_cct = [[float(c),
               {"neutral_a_curve": [float(x) for x in ab[0]],
                "neutral_b_curve": [float(x) for x in ab[1]]}]
              for c, ab in zip(theta.neutral_cct, theta.neutral_by_cct)]
    docs["neutral_curves"] = {"default": nd, "by_cct": by_cct}
    docs["rp_ccm_coeff"] = {
        "type": "pixo_rp_ccm", "version": 1,
        "degree": int(theta.rp_ccm_degree),
        "terms": list(_RP_TERMS[int(theta.rp_ccm_degree)]),
        "matrix": [[float(x) for x in row] for row in theta.rp_ccm_coeff],
    }
    a, b, major, minor, angle = (float(x) for x in theta.skin_ellipse)
    docs["skin_ellipse"] = {
        "constants": {"SKIN_OKLAB_A": a, "SKIN_OKLAB_B": b,
                      "SKIN_OKLAB_MAJOR": major, "SKIN_OKLAB_MINOR": minor,
                      "SKIN_OKLAB_ANGLE": angle},
        "new_ellipse_fit": {"center_a": a, "center_b": b,
                            "major": major, "minor": minor,
                            "angle_deg": _angle_deg_repr(angle)},
    }
    return docs


def _angle_deg_repr(angle_rad: float) -> float:
    """new_ellipse_fit.angle_deg 的写法: 拟合脚本惯例 (4 位小数) 能无损往返
    constants 弧度 (round(radians(deg),6) 逐位等于原值) 则沿用, 否则全精度
    —— constants 弧度恒为 θ 权威原样值, 两种写法都不影响重载恒等。"""
    deg_round = round(math.degrees(angle_rad), 4)
    if round(math.radians(deg_round), 6) == angle_rad:
        return deg_round
    return math.degrees(angle_rad)


def _apply_theta(key: str, template: dict, thin: dict) -> dict:
    """把组件 key 的 θ 字段从瘦 doc 替换进该组件模板的 deepcopy (其余字段
    —— meta/拟合报告/域标注 —— 原样保留)。"""
    out = copy.deepcopy(template)
    if key == "warmth_knots":
        out["knots"] = thin["knots"]
        if thin["_domain"]:
            # 只换 wb_B 数值, 模板 _domain 的 note 等注记保留
            out.setdefault("_domain", {})["wb_B"] = thin["_domain"]["wb_B"]
    elif key == "exposure_table":
        out.update(thin)
    elif key == "neutral_curves":
        out["default"] = thin["default"]
        out["by_cct"] = thin["by_cct"]
    elif key == "rp_ccm_coeff":
        out.update({k: thin[k] for k in ("degree", "terms", "matrix")})
    elif key == "skin_ellipse":
        out["constants"].update(thin["constants"])
        if "new_ellipse_fit" in out:
            out["new_ellipse_fit"].update(thin["new_ellipse_fit"])
    else:
        raise KeyError(key)
    return out


def save_theta(theta: Theta, out_dir: str | Path) -> dict[str, Path]:
    """θ 按**原 schema** 写回 out_dir (建议 configs/color/calib_out/)。

    拒绝写到**原始**标定文件路径 (DEFAULT_SOURCES, 对照留档红线; 从 calib_out
    重载后再写回 calib_out 是 t32 checkpoint/resume 的合法路径, 不在封锁之列)。
    返回 {组件键: 落盘路径}。
    """
    _validate(theta)
    out_dir = Path(out_dir)
    out_paths: dict[str, Path] = {}
    for key in SOURCE_KEYS:
        target = out_dir / OUT_NAMES[key]
        if target.resolve() == DEFAULT_SOURCES[key].resolve():
            raise ValueError(f"拒绝覆盖原始标定文件: {target} (写回须落 calib_out 等新目录)")
        out_paths[key] = target
    out_dir.mkdir(parents=True, exist_ok=True)
    for key in SOURCE_KEYS:
        doc = _apply_theta(key, theta.docs[key], _theta_to_docs(theta)[key])
        text = json.dumps(doc, ensure_ascii=False, indent=_DUMP_INDENT[key])
        out_paths[key].write_text(text, encoding="utf-8")
    return out_paths


# ---------------------------------------------------------------------------
# 往返恒等校验 (验收门: load→save→load 数值逐位)
# ---------------------------------------------------------------------------

def bitwise_equal(a, b) -> bool:
    """数值逐位相等 (含 -0.0/NaN 位型; float64 视图按字节比较)。"""
    a, b = np.asarray(a), np.asarray(b)
    return (a.shape == b.shape and a.dtype == b.dtype
            and a.tobytes() == b.tobytes())


def roundtrip_check(out_dir: str | Path,
                    paths: dict[str, str | Path] | None = None) -> dict:
    """load → save(out_dir) → reload, 逐组件报 θ 逐位恒等 + doc 值级全等。"""
    theta = load_theta(paths)
    out_paths = save_theta(theta, out_dir)
    rt = load_theta({k: out_paths[k] for k in SOURCE_KEYS})
    report: dict[str, dict] = {}
    for key in SOURCE_KEYS:
        src_doc = json.loads(Path(theta.sources[key]).read_text(encoding="utf-8"))
        out_doc = json.loads(out_paths[key].read_text(encoding="utf-8"))
        report[key] = {
            "theta_bitwise": _theta_component_equal(theta, rt, key),
            "doc_value_equal": src_doc == out_doc,
            "path": str(out_paths[key]),
        }
    report["ok"] = all(report[k]["theta_bitwise"] and report[k]["doc_value_equal"]
                       for k in SOURCE_KEYS)
    return report


def _theta_component_equal(t1: Theta, t2: Theta, key: str) -> bool:
    pairs = {
        "warmth_knots": (t1.warmth_knots, t2.warmth_knots),
        "exposure_table": (t1.exposure_table, t2.exposure_table),
        "neutral_curves": (
            (t1.neutral_default, t1.neutral_cct, t1.neutral_by_cct),
            (t2.neutral_default, t2.neutral_cct, t2.neutral_by_cct)),
        "rp_ccm_coeff": (t1.rp_ccm_coeff, t2.rp_ccm_coeff),
        "skin_ellipse": (t1.skin_ellipse, t2.skin_ellipse),
    }
    a, b = pairs[key]
    if isinstance(a, tuple):
        return all(bitwise_equal(x, y) for x, y in zip(a, b))
    return bitwise_equal(a, b)


# ---------------------------------------------------------------------------
# CLI: 初值快照落 calib_out + 往返恒等自检 (验收门演示)
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="θ 五组件初值快照 → calib_out (原格式写回) + 往返逐位恒等自检")
    ap.add_argument("--out", default=str(REPO_ROOT / "configs" / "color" / "calib_out"),
                    help="写回目录 (默认 configs/color/calib_out, 不覆盖源文件)")
    args = ap.parse_args(argv)

    report = roundtrip_check(args.out)
    print(f"θ 初值快照 + 往返自检 → {args.out}")
    for key in SOURCE_KEYS:
        r = report[key]
        print(f"  {key:<16} θ逐位={'OK' if r['theta_bitwise'] else 'FAIL'}  "
              f"doc全等={'OK' if r['doc_value_equal'] else 'FAIL'}  {r['path']}")
    print("PASS" if report["ok"] else "FAIL")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
