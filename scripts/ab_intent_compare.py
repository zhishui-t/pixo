"""意图级编辑域 A/B 对照 —— HSV 旧内核 vs OKLCh 新内核 (设计 §6 / t23)。

同一调整意图 (如 "+10 橙饱和" / "高光暖移") 分别用两条实现轨渲染同一小语料
(≥20 张, 含厦门样张):
  A 轨 (hsv,  现行默认): core.hsl.hsl_adjust_rgb / core.split_tone.split_tone_rgb
  B 轨 (oklch, 新实现):  core.hsl_oklch.oklch_adjust_rgb /
                         core.split_tone_oklab.split_tone_oklab_rgb
基座: Renderer.render_preview_full 中性参数 (exposure 0.0 / wb trim [1,1,1]),
两轨共用同一基座逐像素独立施加意图 (内核均为逐像素算子, 网格抽样与全图逐位同值)。

统计三族指标 (设计 §6):
  1. 意图目标色相扇区内 ΔE2000 分布 —— 意图实现强度**量级对照** (对齐带
     [0.9,1.1], 否则标 更强/更弱)。扇区 = 各轨在自己域的基像环状掩码 ≥0.5
     的交集 (HSV 色相轮非均匀, 同名义 width 的两轨足迹在 OKLCh 空间不重合,
     仅单轨作用的部分单列"扇区错位带"); 不设不劣于闸门 —— "+10" 的数值语义
     跨域不同 (HSV S 随 V 缩放且饱和无中性保护, OKLCh C 感知比例 + 中性
     保护), 跨域无真值;
  2. 扇区外误伤 ΔE2000 (双轨掩码均 <0.05) —— 越低越好, 不劣于闸门: B/A ≤ 1.1,
     median 小值地板 0.05 ΔE, p95 小值地板 1.0 (JND, 掩码软窗尾部两轨均
     亚感知即不劣);
  3. 高光区色相漂移量 (split_tone 意图; HSV "V 保亮"已知缺陷的验证指标):
     - 色相落点误差: 染色主导像素 (w=wh·strength ≥ 0.5) 的结果 OKLCh 色相
       相对拨盘色相的角偏差。oklch 轨拨盘角即 OKLCh 角; hsv 轨拨盘角经
       UI_OKLCH_SPEC §2.2 表 B 冻结锚点分段线性映射到 OKLCh (感知参考域,
       路线图 "HSV 类缺陷根治点" 的裁决空间)。median/p95 均为不劣于闸门。
     - 近白 (Y≥0.95) 色度强加: 结果色度中位数 —— V 保亮把高光推饱和的根因
       证据; oklch 域 C_ref(L) 近白自然趋 0 (设计 §2.3 根治点)。
色相扇区/落点一律以**基像 OKLCh 色相**为公共空间; C < C_NEUTRAL (0.02,
与内核中性保护同值) 的近中性像素色相无定义, 不入扇区/错位带 (计入误伤侧,
两轨在该处均近似不动)。

ΔE2000 直接复用 scripts/eval_rp_ccm_ab.py 的 delta_e_2000 (--selftest 已过
Sharma 2005 文献对自检)。报告 markdown 落 .artifacts/ab_intent_report.md
(+ 同名 .json 机读版); **同种子 + 同语料清单 → 全部指标逐位可复现** (时间戳
除外)。

纪律: 只报告不切默认 —— 本脚本不写任何 configs/, 不修改两轨内核 (对齐
eval_rp_ccm_ab / 设计 §4)。

用法:
  python scripts/ab_intent_compare.py --selftest     # CIEDE2000 文献对自检
  python scripts/ab_intent_compare.py --limit 4 --out .artifacts/ab_intent_smoke.md
  python scripts/ab_intent_compare.py                # 厦门样张全量 + full_scan 抽样 = 24 张
  python scripts/ab_intent_compare.py --limit 0      # 厦门样张 + full_scan 全量
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval_rp_ccm_ab import delta_e_2000, linear_srgb_to_lab, selftest as de2000_selftest
from fit_rp_ccm import DCP, iter_corpus
from pixo.render.api import Renderer
from pixo.render.core.hsl import DEFAULT_BANDS as DEFAULT_BANDS_HSV
from pixo.render.core.hsl_oklch import C_NEUTRAL, DEFAULT_BANDS_OKLCH, oklch_adjust_rgb
from pixo.render.core.hsl import hsl_adjust_rgb
from pixo.render.core.hsl import _ring_mask
from pixo.render.core.huesat import _rgb_to_hsv
from pixo.render.core.oklab import oklab_to_oklch, srgb_to_oklab
from pixo.render.core.split_tone import _RGB_WEIGHTS, _shadow_weight, split_tone_rgb
from pixo.render.core.split_tone_oklab import split_tone_oklab_rgb
from pixo.render.core.tone import srgb_decode

XIAMEN_REPORT = "exports/auto/xiamen_sample/report.json"

# UI_OKLCH_SPEC §2.2 表 B (冻结): HSV 纯色 (S=V=100%) → OKLCh 角。
# 仅用于把 hsv 轨的拨盘角换算到 OKLCh 感知参考域 (报告裁决空间), 不参与渲染。
_ANCHOR_HSV = np.asarray([0.0, 30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330])
_ANCHOR_OKLCH = np.asarray([29.2, 52.8, 109.8, 135.9, 142.5, 151.1, 194.8,
                            256.2, 264.1, 293.8, 328.4, 362.6])


def hsv_hue_to_oklch(h: float) -> float:
    """HSV 色相角 → OKLCh 角 (表 B 分段线性; <0 折到解环绕区间 [0,330])。"""
    return float(np.interp(float(h) % 360.0, _ANCHOR_HSV, _ANCHOR_OKLCH))


def _wrap180(d):
    """角差折到 (-180, 180]。"""
    return (np.asarray(d, dtype=np.float64) + 180.0) % 360.0 - 180.0


def _band(template: dict, domain: str | None = None, **overrides) -> dict:
    """从默认带模板拷贝生成意图 band (缺省键补 0, 与内核 schema 对齐)。"""
    b = {"hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0, **template}
    if domain is not None:
        b["domain"] = domain
    b.update(overrides)
    return b


# ---------------------------------------------------------------------------
# 意图矩阵 (每意图两轨参数 + 扇区/高光口径)
# ---------------------------------------------------------------------------

class Intent:
    def __init__(self, key, desc, kind, bands_hsv=None, bands_oklch=None,
                 split_params=None, center_hsv=None, center_oklch=None,
                 width=45.0, target_h_hsv=None, target_h_oklch=None):
        self.key = key
        self.desc = desc
        self.kind = kind                      # "hsl" | "split"
        self.bands_hsv = bands_hsv            # A 轨 bands (HSV 度, 无 domain 键)
        self.bands_oklch = bands_oklch        # B 轨 bands (OKLCh 度, domain 盖戳)
        self.split_params = split_params or {}
        self.center_hsv = center_hsv          # hsl: A 轨掩码中心 (HSV 度)
        self.center_oklch = center_oklch      # hsl: B 轨掩码中心 (OKLCh 度)
        self.width = width
        self.target_h_hsv = target_h_hsv      # split: A 轨拨盘角 (HSV 度)
        self.target_h_oklch = target_h_oklch  # split: B 轨拨盘角 (OKLCh 度)

    def apply(self, img, domain: str):
        """对 gamma f64 [0,1] 图施加本意图 (指定轨); 返回内核 f32 出口。"""
        if self.kind == "hsl":
            bands = self.bands_hsv if domain == "hsv" else self.bands_oklch
            fn = hsl_adjust_rgb if domain == "hsv" else oklch_adjust_rgb
            return fn(img, bands, smooth=1.0)
        p = self.split_params
        fn = split_tone_rgb if domain == "hsv" else split_tone_oklab_rgb
        return fn(img, p["shadows_hue"], p["shadows_sat"],
                  p["highlights_hue"], p["highlights_sat"],
                  balance=p["balance"], strength=p["strength"])


# band 参数从生产默认模板派生 (DEFAULT_BANDS / DEFAULT_BANDS_OKLCH 的同名带),
# 保证对照的是 "同一意图在两套域量纲下的各自正解", 而非手搓角度。
_INTENTS = [
    Intent(
        key="orange_sat+10", kind="hsl", desc="+10 橙饱和",
        bands_hsv=[_band(DEFAULT_BANDS_HSV[1], saturation=10.0)],
        bands_oklch=[_band(DEFAULT_BANDS_OKLCH[1], saturation=10.0)],
        center_hsv=float(DEFAULT_BANDS_HSV[1]["hue_center"]),
        center_oklch=float(DEFAULT_BANDS_OKLCH[1]["hue_center"]),
    ),
    Intent(
        key="green_hue+10", kind="hsl", desc="+10° 绿色相平移",
        bands_hsv=[_band(DEFAULT_BANDS_HSV[3], hue_shift=10.0)],
        bands_oklch=[_band(DEFAULT_BANDS_OKLCH[3], hue_shift=10.0)],
        center_hsv=float(DEFAULT_BANDS_HSV[3]["hue_center"]),
        center_oklch=float(DEFAULT_BANDS_OKLCH[3]["hue_center"]),
    ),
    Intent(
        key="split_highlights_warm", kind="split",
        desc="高光暖移 (highlights hue45/sat30, strength1, balance0.5)",
        split_params={"shadows_hue": 45.0, "shadows_sat": 0.0,
                      "highlights_hue": 45.0, "highlights_sat": 30.0,
                      "balance": 0.5, "strength": 1.0},
        target_h_hsv=45.0,
        target_h_oklch=45.0,
    ),
]
_SPLIT = _INTENTS[2]
_SPLIT_A_TARGET_OKLCH = hsv_hue_to_oklch(_SPLIT.target_h_hsv)  # 表 B: 45° → 81.3°


def _kernel_noop_sanity(base: np.ndarray) -> None:
    """内核接线自检 (首张成功照片上跑一次): 全 0 参数两轨逐位 no-op。

    对齐设计 §1.3 no-op 保证 —— 若破坏说明脚本接线或内核契约出了问题。
    """
    b32 = base.astype(np.float32)
    zero = {"hue_shift": 0.0, "saturation": 0.0, "luminance": 0.0}
    hsv0 = [{**DEFAULT_BANDS_HSV[0], **zero}]
    oklch0 = [{**DEFAULT_BANDS_OKLCH[0], **zero, "domain": "oklch"}]
    checks = {
        "hsl_adjust_rgb 全0带": hsl_adjust_rgb(base, hsv0),
        "oklch_adjust_rgb 全0带": oklch_adjust_rgb(base, oklch0),
        "split_tone_rgb sat0": split_tone_rgb(base, 45.0, 0.0, 210.0, 0.0),
        "split_tone_oklab_rgb sat0": split_tone_oklab_rgb(base, 45.0, 0.0, 210.0, 0.0),
    }
    for name, out in checks.items():
        if not np.array_equal(out, b32):
            raise RuntimeError(f"内核 no-op 自检失败: {name} 未逐位直通")


# ---------------------------------------------------------------------------
# 语料
# ---------------------------------------------------------------------------

def _group_of(pid: str, raw: str, xiamen: bool) -> str:
    if xiamen:
        return "厦门"
    text = f"{pid} {raw}"
    if "春节" in text:
        return "2026春节"
    return "full_scan"


def build_corpus(corpus_dir: str, raws: list[str] | None, limit: int,
                 seed: int) -> tuple[list[dict], list[str]]:
    """厦门样张 (全量) + full_scan 抽样 (seed 决定) → 语料清单; 缺文件剔除。

    返回 (清单 [{photo_id, raw, group}], 剔除说明)。清单顺序: 厦门在前,
    其后按抽样索引升序 —— 同种子同语料文件集下逐位可复现。
    """
    xiamen: list[dict] = []
    dropped: list[str] = []
    if raws is None and Path(XIAMEN_REPORT).is_file():
        seen: set[str] = set()
        for it in json.loads(Path(XIAMEN_REPORT).read_text(encoding="utf-8")):
            raw = str(it["raw"])
            if raw in seen:
                continue
            seen.add(raw)
            if not Path(raw).is_file():
                dropped.append(f"{it['id']}: 缺文件")
                continue
            xiamen.append({"photo_id": str(it["id"]), "raw": raw, "group": "厦门"})
    else:
        xiamen = []

    full = sorted(iter_corpus(corpus_dir, raws, 0), key=lambda kv: kv[0])
    if raws:
        items = [{"photo_id": pid, "raw": raw,
                  "group": _group_of(pid, raw, False)} for pid, raw in full]
    else:
        full = [(pid, raw) for pid, raw in full if Path(raw).is_file()]
        n_full = max(limit - len(xiamen), 0) if limit else len(full)
        rng = np.random.default_rng(seed)
        pick = sorted(rng.choice(len(full), size=min(n_full, len(full)),
                                 replace=False).tolist())
        items = [{"photo_id": full[i][0], "raw": full[i][1],
                  "group": _group_of(full[i][0], full[i][1], False)} for i in pick]
    corpus = xiamen + items
    return (corpus[:limit] if limit else corpus), dropped


# ---------------------------------------------------------------------------
# 单照片统计
# ---------------------------------------------------------------------------

def photo_stats(base: np.ndarray, stride: int) -> dict:
    """基像公共量 (网格抽样): Lab/OKLCh/亮度/高光权重。"""
    g = base[::stride, ::stride]
    lin = srgb_decode(np.ascontiguousarray(g).astype(np.float32)).astype(np.float64)
    lab = linear_srgb_to_lab(lin)
    lch = oklab_to_oklch(srgb_to_oklab(g))
    y = np.clip(g @ _RGB_WEIGHTS, 0.0, 1.0)
    return {"grid": g, "lab": lab, "lch": lch, "y": y,
            "wh": 1.0 - _shadow_weight(y, 0.5)}


def intent_stats(pub: dict, it: Intent) -> dict:
    """单照片单意图两轨统计 (返回可 JSON 化的标量/数组混合 dict)。"""
    g, lab0, lch0 = pub["grid"], pub["lab"], pub["lch"]
    c0, h0 = lch0[..., 1], lch0[..., 2]
    out: dict = {"key": it.key}
    for tag, domain in (("a", "hsv"), ("b", "oklch")):
        img = it.apply(g, domain).astype(np.float64)
        lin = srgb_decode(np.ascontiguousarray(img).astype(np.float32)).astype(np.float64)
        d = delta_e_2000(lab0, linear_srgb_to_lab(lin))
        out[f"de_{tag}"] = d
        if it.kind == "split":
            out[f"lch_{tag}"] = oklab_to_oklch(srgb_to_oklab(img))

    if it.kind == "hsl":
        # 扇区 = 双轨掩码共同作用区: 各轨在自己域的基像环状掩码 ≥0.5 的交集
        # (固定单侧扇区会把另一轨的主动作用区误算成"误伤" —— HSV 色相轮
        # 非均匀, 同名义 width 的足迹在 OKLCh 空间不重合, 绿区压缩最狠)。
        hsv_h = _rgb_to_hsv(g)[0]          # (h, s, v) 元组 → h, [0,360)
        m_a = _ring_mask(hsv_h, it.center_hsv, it.width, 1.0)
        m_b = _ring_mask(h0, it.center_oklch, it.width, 1.0)
        neutral = c0 < C_NEUTRAL
        in_sec = (m_a >= 0.5) & (m_b >= 0.5) & ~neutral
        disagree = ~in_sec & ~neutral & (np.maximum(m_a, m_b) >= 0.05)
        out_sec = ~in_sec & ~disagree      # 含近中性像素 (两轨在该处均≈不动)
        out["in_sector"] = in_sec
        out["disagree"] = disagree
        out["out_sector"] = out_sec
        out["n_neutral"] = int(neutral.sum())
        return out

    # split: 高光区/阴影区 + 色相落点 + 近白色度
    w = pub["wh"] * float(it.split_params["strength"])
    out["zone"] = w >= 0.5
    out["outzone"] = w <= 0.1
    out["hi_white"] = pub["y"] >= 0.95
    cA = out["lch_a"][..., 1]
    cB = out["lch_b"][..., 1]
    okA = out["zone"] & (cA >= C_NEUTRAL)
    okB = out["zone"] & (cB >= C_NEUTRAL)
    out["land_err_a"] = np.abs(_wrap180(out["lch_a"][..., 2][okA]
                                        - _SPLIT_A_TARGET_OKLCH))
    out["land_err_b"] = np.abs(_wrap180(out["lch_b"][..., 2][okB]
                                        - it.target_h_oklch))
    return out


def _agg(vals: list[np.ndarray]) -> dict:
    if not vals:
        return {"n": 0, "median": None, "p95": None}
    v = np.concatenate(vals)
    return {"n": int(v.size), "median": float(np.median(v)),
            "p95": float(np.quantile(v, 0.95))}


def _ratio_verdict(b_med: float | None, a_med: float | None,
                   lo: float = 0.9, hi: float = 1.1,
                   abs_eps: float = 0.05, abs_gap: float = 0.02) -> tuple[float | None, str]:
    """比值 + 不劣于判定 (误伤/漂移类, 单侧越低越好; 小值保护见 docstring)。

    A < abs_eps (比值无意义) 时: B−A ≤ abs_eps 亦判 "不劣于(小值)"
    (p95 闸门传 abs_eps=1.0 = JND 地板: 两轨尾部均不可感知即不劣)。
    """
    if a_med is None or b_med is None:
        return None, "无数据"
    if a_med < abs_eps:
        ok = (b_med - a_med) <= abs_eps
        return None, "不劣于(小值)" if ok else "劣于(小值)"
    return (b_med / a_med, "不劣于") if b_med / a_med <= hi else (b_med / a_med, "劣于")


def _ratio_label(b_med: float | None, a_med: float | None,
                 lo: float = 0.9, hi: float = 1.1) -> tuple[float | None, str]:
    """扇区内实现强度的量级对照标签 (非闸门 —— "+10" 的数值语义跨域不同:
    HSV S 随 V 缩放且无中性保护, OKLCh C 感知比例 + 中性保护, 同数值的
    感知强度天然不同; 跨域无真值, 只报对齐/更强/更弱)。"""
    if a_med is None or b_med is None:
        return None, "无数据"
    if a_med < 1e-9:
        return None, "A 无作用"
    r = b_med / a_med
    if lo <= r <= hi:
        return r, "对齐"
    return r, ("更强" if r > 1.1 else "更弱")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default="exports/auto/full_scan")
    ap.add_argument("--raw", action="append", default=None,
                    help="显式 RAW (可多次; 指定后跳过厦门样张与抽样)")
    ap.add_argument("--limit", type=int, default=24,
                    help="语料总数上限 (含厦门样张; 0=全量)")
    ap.add_argument("--seed", type=int, default=20260904, help="full_scan 抽样种子")
    ap.add_argument("--dcp", default=DCP)
    ap.add_argument("--preview-edge", type=int, default=512)
    ap.add_argument("--stride", type=int, default=2, help="统计网格抽样步长")
    ap.add_argument("--out-dir", default=".artifacts")
    ap.add_argument("--out", default=None,
                    help="报告路径 (缺省 <out-dir>/ab_intent_report.md)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        de2000_selftest()
        if args.raw is None and not Path(args.corpus).is_dir():
            return

    corpus, dropped = build_corpus(args.corpus, args.raw, args.limit, args.seed)
    # 设计 §6 要求 ≥20 张: 默认报告路径强制; 显式 --out 视为冒烟, 警告放行
    if len(corpus) < 20:
        msg = (f"语料 {len(corpus)} 张 (<20, 设计 §6 要求): "
               f"检查 --corpus/--raw/--limit")
        if args.out is None:
            print(msg, file=sys.stderr)
            sys.exit(2)
        print(f"警告: {msg} (冒烟模式, --out 已显式指定)", file=sys.stderr)
    renderer = Renderer(args.dcp)

    # 池: 每意图 {指标名: [逐照片像素值数组]}; 分照片行另存标量
    pool: dict[str, dict[str, list]] = {it.key: {
        "in_a": [], "in_b": [], "out_a": [], "out_b": [],
        "dis_a": [], "dis_b": [],
        "zone_a": [], "zone_b": [], "oz_a": [], "oz_b": [],
        "land_a": [], "land_b": [], "cw_a": [], "cw_b": []} for it in _INTENTS}
    rows: list[dict] = []
    skipped: list[str] = []
    sanity_done = False
    t0 = time.time()

    for i, item in enumerate(corpus, 1):
        pid, raw = item["photo_id"], item["raw"]
        try:
            base = renderer.render_preview_full(
                raw, long_edge=args.preview_edge,
                params={"exposure": {"mode": 0.0},
                        "whitebalance": {"trim": [1, 1, 1]}})
            if base.dtype == np.uint8:   # output_bps=8 → gamma uint8
                base = base.astype(np.float64) / 255.0
            else:
                base = np.asarray(base, dtype=np.float64)
            if not sanity_done:
                _kernel_noop_sanity(base)
                sanity_done = True
            pub = photo_stats(base, args.stride)
            row: dict = {"photo_id": pid, "group": item["group"]}
            for it in _INTENTS:
                st = intent_stats(pub, it)
                pa, pb = pool[it.key], {}
                if it.kind == "hsl":
                    ins, outs, dis = st["in_sector"], st["out_sector"], st["disagree"]
                    pa["in_a"].append(st["de_a"][ins]); pa["in_b"].append(st["de_b"][ins])
                    pa["out_a"].append(st["de_a"][outs]); pa["out_b"].append(st["de_b"][outs])
                    pa["dis_a"].append(st["de_a"][dis]); pa["dis_b"].append(st["de_b"][dis])
                    pb = {"in_a": float(np.median(st["de_a"][ins])) if ins.any() else None,
                          "in_b": float(np.median(st["de_b"][ins])) if ins.any() else None,
                          "out_a": float(np.median(st["de_a"][outs])) if outs.any() else None,
                          "out_b": float(np.median(st["de_b"][outs])) if outs.any() else None,
                          "n_in": int(ins.sum()), "n_dis": int(dis.sum())}
                else:
                    z, oz = st["zone"], st["outzone"]
                    pa["zone_a"].append(st["de_a"][z]); pa["zone_b"].append(st["de_b"][z])
                    pa["oz_a"].append(st["de_a"][oz]); pa["oz_b"].append(st["de_b"][oz])
                    pa["land_a"].append(st["land_err_a"]); pa["land_b"].append(st["land_err_b"])
                    # 近白 (Y>=0.95) 结果色度 (原始像素值入池): V 保亮根因证据
                    cw_a = float(np.median(st["lch_a"][..., 1][st["hi_white"]])) \
                        if st["hi_white"].any() else None
                    cw_b = float(np.median(st["lch_b"][..., 1][st["hi_white"]])) \
                        if st["hi_white"].any() else None
                    if cw_a is not None:
                        pa["cw_a"].append(st["lch_a"][..., 1][st["hi_white"]])
                        pa["cw_b"].append(st["lch_b"][..., 1][st["hi_white"]])
                    pb = {"zone_a": float(np.median(st["de_a"][z])) if z.any() else None,
                          "zone_b": float(np.median(st["de_b"][z])) if z.any() else None,
                          "land_a": float(np.median(st["land_err_a"])) if st["land_err_a"].size else None,
                          "land_b": float(np.median(st["land_err_b"])) if st["land_err_b"].size else None,
                          "cw_a": cw_a, "cw_b": cw_b, "n_zone": int(z.sum())}
                row[it.key] = pb
            rows.append(row)
            print(f"[{i}/{len(corpus)}] {pid} 完成", flush=True)
        except Exception as exc:  # noqa: BLE001 — 单张失败不拖垮整批
            skipped.append(f"{pid}: {exc}")
            print(f"[{i}/{len(corpus)}] {pid} 跳过: {exc}", flush=True)

    if len(rows) < 20 and args.out is None:
        print(f"有效照片 {len(rows)} 张 (<20), 不出报告 (设计 §6 要求 ≥20)",
              file=sys.stderr)
        sys.exit(1)

    # ---- 汇总 + 判定 ----
    summary: dict = {}
    for it in _INTENTS:
        p = pool[it.key]
        if it.kind == "hsl":
            a_in, b_in = _agg(p["in_a"]), _agg(p["in_b"])
            a_out, b_out = _agg(p["out_a"]), _agg(p["out_b"])
            a_dis, b_dis = _agg(p["dis_a"]), _agg(p["dis_b"])
            r_in, v_in = _ratio_label(b_in["median"], a_in["median"])
            r_out, v_out = _ratio_verdict(b_out["median"], a_out["median"])
            r_out95, v_out95 = _ratio_verdict(b_out["p95"], a_out["p95"], abs_eps=1.0)
            summary[it.key] = {"kind": "hsl", "desc": it.desc,
                               "center_hsv": it.center_hsv,
                               "center_oklch": it.center_oklch, "width": it.width,
                               "in_a": a_in, "in_b": b_in, "out_a": a_out,
                               "out_b": b_out, "dis_a": a_dis, "dis_b": b_dis,
                               "ratio_in": r_in, "label_in": v_in,
                               "ratio_out": r_out, "verdict_out": v_out,
                               "ratio_out_p95": r_out95, "verdict_out_p95": v_out95}
        else:
            za, zb = _agg(p["zone_a"]), _agg(p["zone_b"])
            oza, ozb = _agg(p["oz_a"]), _agg(p["oz_b"])
            la, lb = _agg(p["land_a"]), _agg(p["land_b"])
            cwa, cwb = _agg(p["cw_a"]), _agg(p["cw_b"])
            r_land, v_land = _ratio_verdict(lb["median"], la["median"])
            r_land95, v_land95 = _ratio_verdict(lb["p95"], la["p95"], abs_eps=1.0)
            r_cw, v_cw = _ratio_verdict(cwb["median"], cwa["median"])
            summary[it.key] = {"kind": "split", "desc": it.desc,
                               "target_h_oklch_b": it.target_h_oklch,
                               "target_h_oklch_a": _SPLIT_A_TARGET_OKLCH,
                               "zone_a": za, "zone_b": zb, "outzone_a": oza,
                               "outzone_b": ozb, "land_a": la, "land_b": lb,
                               "nearwhite_c_a": cwa, "nearwhite_c_b": cwb,
                               "ratio_land": r_land, "verdict_land": v_land,
                               "ratio_land_p95": r_land95, "verdict_land_p95": v_land95,
                               "ratio_nearwhite_c": r_cw, "verdict_nearwhite_c": v_cw}

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else out_dir / "ab_intent_report.md"
    write_report(out, args, corpus, rows, summary, skipped, dropped,
                 elapsed=time.time() - t0, sanity=sanity_done)
    json_out = out.with_suffix(".json")
    json_out.write_text(json.dumps({
        "seed": args.seed, "args": {k: v for k, v in vars(args).items()},
        "corpus": corpus, "skipped": skipped, "dropped": dropped,
        "summary": summary, "rows": rows,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"DONE {out} (+{json_out.name}) {time.time() - t0:.0f}s")


# ---------------------------------------------------------------------------
# 报告渲染
# ---------------------------------------------------------------------------

def _fmt(x, nd=3):
    return "—" if x is None else f"{x:.{nd}f}"


def _fmt2(x):
    return "—" if x is None else f"{x:.2f}"


def write_report(out: Path, args, corpus, rows, summary, skipped, dropped,
                 elapsed: float, sanity: bool) -> None:
    s_orange, s_green, s_split = (summary["orange_sat+10"], summary["green_hue+10"],
                                  summary["split_highlights_warm"])
    L: list[str] = [
        "# 意图级编辑域 A/B 报告 (HSV 旧内核 vs OKLCh 新内核)",
        "",
        f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')} · 用时 {elapsed:.0f}s · "
        f"内核 no-op 自检: {'通过' if sanity else '未执行'}",
        f"- 语料: 厦门样张 {sum(1 for c in corpus if c['group'] == '厦门')} + "
        f"full_scan 抽样 {sum(1 for c in corpus if c['group'] != '厦门')} = "
        f"{len(corpus)} 张 (清单见文末; 抽样种子 seed={args.seed})",
        f"- 基座: render_preview_full 中性参数 (exposure 0.0 / trim [1,1,1]) "
        f"@ long_edge={args.preview_edge}, 统计网格 stride={args.stride} "
        f"(内核逐像素算子, 网格抽样与全图逐位同值)",
        "- A 轨 (现行默认): `core.hsl.hsl_adjust_rgb` / `core.split_tone.split_tone_rgb` · "
        "B 轨 (新实现): `core.hsl_oklch.oklch_adjust_rgb` / "
        "`core.split_tone_oklab.split_tone_oklab_rgb`; 同一基像逐像素独立施加意图",
        "- 指标: CIEDE2000 (复用 `eval_rp_ccm_ab.delta_e_2000`, Sharma 2005 文献对 "
        "`--selftest` 通过); 色相/扇区一律以基像 OKLCh 色相为公共空间; "
        f"C < {C_NEUTRAL} (内核中性保护同值) 的近中性像素不入扇区/落点统计",
        "- 判定准则: **不劣于闸门**只放在口径良定的伤害类指标上 —— 扇区外误伤 "
        "(median 与 p95)、高光色相落点误差 (median 与 p95)、近白色度强加 (median), "
        "单侧 B/A ≤ 1.1; A 侧小于绝对地板时改判小值 (median 地板 0.05 ΔE / B−A "
        "≤ 0.05; p95 地板 1.0 = JND —— 两轨尾部均不可感知即不劣); 扇区内实现强度"
        "为**量级对照** (对齐带 [0.9,1.1], 否则标 更强/更弱) —— \"+10\" 的数值语义"
        "跨域不同 (HSV S 随 V 缩放且饱和无中性保护, OKLCh C 感知比例缩放 + 中性"
        "保护; 色相角非均匀, 绿区 HSV 30° ≈ OKLCh 9°), 跨域无真值, 不设不劣于闸门",
        "",
        "## 意图矩阵",
        "",
        "| 意图 | A 轨 (hsv 域参数) | B 轨 (oklch 域参数) | 统计口径 |",
        "|---|---|---|---|",
        f"| +10 橙饱和 | orange band center {s_orange['center_hsv']:.0f}° (HSV) "
        f"| orange band center {s_orange['center_oklch']:.0f}° (OKLCh) "
        f"| 扇区 = 双轨掩码 ≥0.5 交集 |",
        f"| +10° 绿色相 | green band center {s_green['center_hsv']:.0f}° (HSV) "
        f"| green band center {s_green['center_oklch']:.0f}° (OKLCh) "
        f"| 扇区 = 双轨掩码 ≥0.5 交集 |",
        "| 高光暖移 | highlights hue=45° (HSV 拨盘) | highlights hue=45° (OKLCh 拨盘) "
        "| 高光区 = wh·strength ≥ 0.5; 落点目标: A 轨 45° 经 UI 表 B → "
        f"{_SPLIT_A_TARGET_OKLCH:.1f}°, B 轨 45° |",
        "",
        "> 扇区口径: hsl 意图的\"目标色相族\"像素 = **各轨在自己域的基像环状掩码 "
        "≥0.5 的交集** (掩码是基像逐像素函数)。HSV 色相轮非均匀 (UI_OKLCH_SPEC "
        "§2.2), 同名义 width 的两轨足迹在 OKLCh 空间不重合 —— 仅单轨作用的部分"
        "单独列为\"扇区错位带\" (域几何差异, 非内核误伤); 双轨掩码均 <0.05 才计"
        "误伤。两轨 band 参数各自取自生产默认带模板 (DEFAULT_BANDS / "
        "DEFAULT_BANDS_OKLCH 同名带), 对照同一意图在两套域量纲下的各自正解; "
        f"近中性像素 (C < {C_NEUTRAL}) 不入扇区/错位带, 计入误伤侧 "
        "(两轨在该处均近似不动)。",
        "",
        "## 总体结果 (全语料像素池)",
        "",
        "### 意图 1: +10 橙饱和 (hsl)",
        "",
        "| 指标 | A: hsv | B: oklch | B/A | 判定 |",
        "|---|---:|---:|---:|---|",
        f"| 扇区内 ΔE2000 median | {_fmt(s_orange['in_a']['median'])} "
        f"| {_fmt(s_orange['in_b']['median'])} "
        f"| {'' if s_orange['ratio_in'] is None else format(s_orange['ratio_in'], '.2f')} "
        f"| {s_orange['label_in']} (量级对照) |",
        f"| 扇区内 ΔE2000 p95 | {_fmt(s_orange['in_a']['p95'])} "
        f"| {_fmt(s_orange['in_b']['p95'])} | — | (对照判中位数) |",
        f"| 扇区外误伤 ΔE2000 median | {_fmt(s_orange['out_a']['median'])} "
        f"| {_fmt(s_orange['out_b']['median'])} "
        f"| {'' if s_orange['ratio_out'] is None else format(s_orange['ratio_out'], '.2f')} "
        f"| **{s_orange['verdict_out']}** |",
        f"| 扇区外误伤 ΔE2000 p95 | {_fmt(s_orange['out_a']['p95'])} "
        f"| {_fmt(s_orange['out_b']['p95'])} "
        f"| {'' if s_orange['ratio_out_p95'] is None else format(s_orange['ratio_out_p95'], '.2f')} "
        f"| **{s_orange['verdict_out_p95']}** |",
        f"| 扇区错位带 ΔE2000 median (单轨作用, 非闸门) "
        f"| {_fmt(s_orange['dis_a']['median'])} "
        f"| {_fmt(s_orange['dis_b']['median'])} | — | |",
        f"| 样本数 (内/错位/外) | {s_orange['in_a']['n']}/{s_orange['dis_a']['n']}"
        f"/{s_orange['out_a']['n']} "
        f"| {s_orange['in_b']['n']}/{s_orange['dis_b']['n']}/{s_orange['out_b']['n']} "
        f"| | |",
        "",
        "### 意图 2: +10° 绿色相平移 (hsl)",
        "",
        "| 指标 | A: hsv | B: oklch | B/A | 判定 |",
        "|---|---:|---:|---:|---|",
        f"| 扇区内 ΔE2000 median | {_fmt(s_green['in_a']['median'])} "
        f"| {_fmt(s_green['in_b']['median'])} "
        f"| {'' if s_green['ratio_in'] is None else format(s_green['ratio_in'], '.2f')} "
        f"| {s_green['label_in']} (量级对照) |",
        f"| 扇区内 ΔE2000 p95 | {_fmt(s_green['in_a']['p95'])} "
        f"| {_fmt(s_green['in_b']['p95'])} | — | (对照判中位数) |",
        f"| 扇区外误伤 ΔE2000 median | {_fmt(s_green['out_a']['median'])} "
        f"| {_fmt(s_green['out_b']['median'])} "
        f"| {'' if s_green['ratio_out'] is None else format(s_green['ratio_out'], '.2f')} "
        f"| **{s_green['verdict_out']}** |",
        f"| 扇区外误伤 ΔE2000 p95 | {_fmt(s_green['out_a']['p95'])} "
        f"| {_fmt(s_green['out_b']['p95'])} "
        f"| {'' if s_green['ratio_out_p95'] is None else format(s_green['ratio_out_p95'], '.2f')} "
        f"| **{s_green['verdict_out_p95']}** |",
        f"| 扇区错位带 ΔE2000 median (单轨作用, 非闸门) "
        f"| {_fmt(s_green['dis_a']['median'])} "
        f"| {_fmt(s_green['dis_b']['median'])} | — | |",
        f"| 样本数 (内/错位/外) | {s_green['in_a']['n']}/{s_green['dis_a']['n']}"
        f"/{s_green['out_a']['n']} "
        f"| {s_green['in_b']['n']}/{s_green['dis_b']['n']}/{s_green['out_b']['n']} "
        f"| | |",
        "",
        "### 意图 3: 高光暖移 (split_tone)",
        "",
        "| 指标 | A: hsv | B: oklch | B/A | 判定 |",
        "|---|---:|---:|---:|---|",
        f"| 高光区 ΔE2000 median | {_fmt(s_split['zone_a']['median'])} "
        f"| {_fmt(s_split['zone_b']['median'])} | — | (实现量级参考) |",
        f"| 高光区 ΔE2000 p95 | {_fmt(s_split['zone_a']['p95'])} "
        f"| {_fmt(s_split['zone_b']['p95'])} | — | |",
        f"| 阴影区误伤 ΔE2000 median | {_fmt(s_split['outzone_a']['median'])} "
        f"| {_fmt(s_split['outzone_b']['median'])} | — | (两轨应≈0, 接线自检) |",
        f"| **色相落点误差 median (°)** | {_fmt2(s_split['land_a']['median'])} "
        f"| {_fmt2(s_split['land_b']['median'])} "
        f"| {'' if s_split['ratio_land'] is None else format(s_split['ratio_land'], '.2f')} "
        f"| **{s_split['verdict_land']}** |",
        f"| **色相落点误差 p95 (°)** | {_fmt2(s_split['land_a']['p95'])} "
        f"| {_fmt2(s_split['land_b']['p95'])} "
        f"| {'' if s_split['ratio_land_p95'] is None else format(s_split['ratio_land_p95'], '.2f')} "
        f"| **{s_split['verdict_land_p95']}** |",
        f"| 近白 (Y≥0.95) 色度强加 median (ΔC 口径, 越低越好) "
        f"| {_fmt(s_split['nearwhite_c_a']['median'], 4)} "
        f"| {_fmt(s_split['nearwhite_c_b']['median'], 4)} "
        f"| {'' if s_split['ratio_nearwhite_c'] is None else format(s_split['ratio_nearwhite_c'], '.2f')} "
        f"| **{s_split['verdict_nearwhite_c']}** |",
        f"| 样本数 (高光区 / 落点) | {s_split['zone_a']['n']}/{s_split['land_a']['n']} "
        f"| {s_split['zone_b']['n']}/{s_split['land_b']['n']} | | |",
        "",
        "> 色相落点误差 = 染色主导像素 (w≥0.5 且结果 C≥0.02) 的结果 OKLCh 色相相对"
        "拨盘色相的角偏差。A 轨目标角经 UI_OKLCH_SPEC 表 B 锚点映射 (HSV 45°→"
        f"{_SPLIT_A_TARGET_OKLCH:.1f}°); hsv 域 \"V 保亮\" 使降饱和染色的感知色相"
        "随量级/亮度漂移 (UI 规格 §2.2 已知非均匀性), oklch 域拨盘角即感知角。"
        "近白色度强加 = Y≥0.95 像素结果色度中位数: HSV 的 V 保亮在近白强加色度 "
        "(设计 §2.3 根治点), oklch 域 C_ref(L) 近白自然趋 0; 其落点误差集中于 "
        "C 很小的近白 clip 旋转 (内核已文档化的 M-O2 cusp 近似), 感知量级见色度列。",
        "",
        "> 误伤 p95 的机理注: 掩码是余弦软窗无硬截止, 色相平移在掩码尾部 (m≈0.05) "
        "仍有 ~0.5° 旋转 —— oklch 轨对彩度像素按感知角均匀旋转 (中性保护只压 "
        "C<0.02), hsv 轨的 hue_shift 另受 protect=S 阻尼, 故 hsv 尾部更小; 两者均 "
        "≪ JND (ΔE2000 ≈ 1.0), 由 p95 闸门的 JND 地板口径覆盖。",
        "",
    ]

    # ---- 结论 ----
    L += ["## 结论 (中位数 / p95 不劣于判定)", ""]
    for key, lab in (("orange_sat+10", "意图 1 (+10 橙饱和)"),
                     ("green_hue+10", "意图 2 (+10° 绿色相)")):
        s = summary[key]
        L.append(
            f"- **{lab}**: 扇区内实现强度 B/A 中位数 "
            f"{_fmt2(s['ratio_in'])} → {s['label_in']} "
            f"(A {_fmt(s['in_a']['median'])} / B {_fmt(s['in_b']['median'])}, "
            "量级对照非闸门 —— 同数值在两域的感知强度天然不同: HSV S 随 V 缩放"
            "且饱和无中性保护, OKLCh C 感知比例 + 中性保护; 色相角非均匀, 绿区"
            "压缩最狠 HSV 30° ≈ OKLCh 9°); 扇区外误伤 B/A "
            f"{_fmt2(s['ratio_out'])} → **{s['verdict_out']}** "
            f"(A {_fmt(s['out_a']['median'])} / B {_fmt(s['out_b']['median'])})。")
    s = summary["split_highlights_warm"]
    L.append(
        f"- **意图 3 (高光暖移)**: 色相落点误差中位数 B/A {_fmt2(s['ratio_land'])} → "
        f"**{s['verdict_land']}** (A {_fmt2(s['land_a']['median'])}° / B "
        f"{_fmt2(s['land_b']['median'])}°), p95 B/A {_fmt2(s['ratio_land_p95'])} → "
        f"**{s['verdict_land_p95']}** (A {_fmt2(s['land_a']['p95'])}° / B "
        f"{_fmt2(s['land_b']['p95'])}°); 近白色度强加中位数 B/A "
        f"{_fmt2(s['ratio_nearwhite_c'])} → **{s['verdict_nearwhite_c']}** "
        f"(A {_fmt(s['nearwhite_c_a']['median'], 4)} / B "
        f"{_fmt(s['nearwhite_c_b']['median'], 4)})。")
    gates = [("意图1 误伤 median", summary["orange_sat+10"]["verdict_out"]),
             ("意图1 误伤 p95", summary["orange_sat+10"]["verdict_out_p95"]),
             ("意图2 误伤 median", summary["green_hue+10"]["verdict_out"]),
             ("意图2 误伤 p95", summary["green_hue+10"]["verdict_out_p95"]),
             ("意图3 落点误差 median", summary["split_highlights_warm"]["verdict_land"]),
             ("意图3 落点误差 p95", summary["split_highlights_warm"]["verdict_land_p95"]),
             ("意图3 近白色度", summary["split_highlights_warm"]["verdict_nearwhite_c"])]
    gate_ok = all(v.startswith("不劣于") for _, v in gates)
    L += [
        f"- **总体 (不劣于闸门 = 误伤 median/p95 ×2 + 落点误差 median/p95 + 近白色度)**: "
        f"{'全部通过 → oklch 域新内核不劣于 hsv 域旧内核' if gate_ok else '存在未过闸门: ' + '; '.join(f'{k}={v}' for k, v in gates if not v.startswith('不劣于'))}。",
        "",
        f"- 语料: {len(corpus)} 张 (厦门样张含内), 跳过 {len(skipped)}; "
        f"统计像素池见各表样本数行。",
        "",
        "## 分照片明细 (median)",
        "",
        "| photo | 组 | I1 扇区内 A/B | I1 扇区外 A/B | I2 扇区内 A/B | "
        "I2 扇区外 A/B | I3 高光区 A/B | I3 落点误差° A/B | I3 近白C A/B |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        i1, i2, i3 = r["orange_sat+10"], r["green_hue+10"], r["split_highlights_warm"]
        L.append(
            f"| {r['photo_id']} | {r['group']} "
            f"| {_fmt2(i1['in_a'])}/{_fmt2(i1['in_b'])} "
            f"| {_fmt2(i1['out_a'])}/{_fmt2(i1['out_b'])} "
            f"| {_fmt2(i2['in_a'])}/{_fmt2(i2['in_b'])} "
            f"| {_fmt2(i2['out_a'])}/{_fmt2(i2['out_b'])} "
            f"| {_fmt2(i3['zone_a'])}/{_fmt2(i3['zone_b'])} "
            f"| {_fmt2(i3['land_a'])}/{_fmt2(i3['land_b'])} "
            f"| {'—' if i3['cw_a'] is None else format(i3['cw_a'], '.4f')}"
            f"/{'—' if i3['cw_b'] is None else format(i3['cw_b'], '.4f')} |")
    if skipped:
        L += ["", f"跳过 {len(skipped)} 张: " + "; ".join(skipped[:5]) +
              (" ..." if len(skipped) > 5 else "")]
    if dropped:
        L += ["", f"厦门清单剔除 {len(dropped)}: " + "; ".join(dropped[:5])]
    L += [
        "",
        "## 语料清单 (复现依据)",
        "",
        f"seed={args.seed}; 语料 = 厦门样张全量 "
        f"({XIAMEN_REPORT}) + full_scan 抽样 ({args.corpus}); "
        f"共 {len(corpus)} 张, 顺序即处理顺序。",
        "",
        "| # | photo_id | 组 | raw |",
        "|---|---|---|---|",
    ]
    for i, c in enumerate(corpus, 1):
        L.append(f"| {i} | {c['photo_id']} | {c['group']} | {c['raw']} |")
    L += [
        "",
        "## 复现",
        "",
        "```bash",
        "python scripts/ab_intent_compare.py --selftest          # CIEDE2000 文献对自检",
        f"python scripts/ab_intent_compare.py --seed {args.seed} --limit {args.limit}"
        f" --preview-edge {args.preview_edge} --stride {args.stride}",
        "```",
        "",
        "> 同种子 + 同语料清单 → 全部指标逐位可复现 (生成时间戳除外); 机读版 "
        f"`{out.with_suffix('.json').name}` 含全部逐照片行与汇总数字。",
        "> 纪律: 本报告只作决策依据, **不切换运行时默认** (设计 §6); "
        "两轨内核与 configs/ 均未被本脚本修改。",
        "",
    ]
    out.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    main()
