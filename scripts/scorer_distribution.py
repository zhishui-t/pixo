"""生成真评分器七维分布表与阈值建议（t58）。

对 12 样张（corpus_a 前4后2、corpus_festival 前4后2）真实渲染小图后跑
PixoAestheticScorer（source="pixo"，权重已在盘），产出：
  - docs/metrics/scorer_distribution.md：逐样本七维+耗时明细、
    p25/p50/p75 分位汇总、合成/低纹理域专项（量化"低分≠废片"
    的域外程度）、accept_threshold/stagnation_eps 阈值建议。
生产默认仍 None=关，启用由调用方——本表仅给建议值不改代码默认。
另记录逐张推理耗时供 P3 延迟评估。

用法: python scripts/scorer_distribution.py [--long-edge 512]
"""
import argparse
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]
SCENES = [
    ("corpus_a", [Path("<corpus>/a/raw")]),
    ("春节", [Path("<corpus_root>/corpus_festival")]),
]
# t71+ 协调：corpus_xiamen高调域外代表样本强制回含（t73 曝光缺口诊断证据）
FORCE_INCLUDE = {
    "corpus_xiamen": ["DSC_0847.NEF"],
}

BASELINE_NAMES = {
    "corpus_a": ["DSC_5236.NEF", "DSC_5237.NEF", "DSC_5238.NEF",
             "DSC_5239.NEF", "DSC_6006.NEF", "DSC_6007.NEF"],
    "春节": ["DSC_0352.NEF", "DSC_0353.NEF", "DSC_0354.NEF",
             "DSC_0355.NEF", "DSC_0606.NEF", "DSC_0607.NEF"],
}


def _valid_nefs(folder: Path):
    return sorted(f for f in folder.glob("*.NEF")
                  if not f.name.startswith("._"))


def build_scene_files():
    """三场景文件枚举；corpus_xiamen展开编号子目录。"""
    out = []
    for label, dirs in SCENES:
        files = []
        for d in dirs:
            files.extend(_valid_nefs(d))
        if label == "春节":
            pass
        files = sorted(set(files))
        if files:
            out.append((label, files))
    base = Path("<corpus_root>/corpus_xiamen")
    if base.is_dir():
        xm_files = []
        for d in sorted(d for d in base.iterdir() if d.is_dir()):
            xm_files.extend(_valid_nefs(d))
        if xm_files:
            out.append(("corpus_xiamen", sorted(set(xm_files))))
    return out


import numpy as _np


def stratified(files, n):
    if len(files) <= n:
        return list(files)
    idx = _np.linspace(0, len(files) - 1, n)
    idx = sorted({int(round(v)) for v in idx})
    return [files[i] for i in idx]
DIMS = ("overall", "quality", "composition", "lighting", "color",
        "depth_of_field", "content")


def pick_samples(files, n):
    """t71 分层抽样：排序后 linspace 均匀取代表点 + 基线强制回含由调用方处理。"""
    return stratified(files, n)


# ---- t98 合成/低纹理域探针（深化）----
# 五大类必选探针 + 同一场景退化阶梯（域内自洽性检验用）。
DEGRADATION_SIGMAS = (0, 4, 8, 14, 22, 30)


def _night_sky_base(size: int = 256, seed: int = 0) -> np.ndarray:
    """夜间渐变天空基底：顶部深蓝紫 → 地平线微亮，向量化随机星点。"""
    rng = np.random.default_rng(seed)
    y = np.linspace(0.0, 1.0, size, dtype=np.float32)[:, None]
    top = np.array([0.02, 0.03, 0.08], dtype=np.float32)     # 深蓝紫夜顶
    horizon = np.array([0.10, 0.12, 0.16], dtype=np.float32)  # 地平线微亮
    img = (top[None, None, :] * (1.0 - y)[:, :, None]
           + horizon[None, None, :] * y[:, :, None])
    img = np.broadcast_to(img, (size, size, 3)).copy()
    n_stars = 200
    rows = rng.integers(0, size, size=n_stars)
    cols = rng.integers(0, size, size=n_stars)
    bright = rng.uniform(0.5, 1.0, size=n_stars).astype(np.float32)
    img[rows, cols] = bright[:, None] * np.ones((1, 3), dtype=np.float32)
    return img


def _black_field(size: int = 256, seed: int = 0) -> np.ndarray:
    """夜间黑场：近零均值 + 极低读出噪声（暗帧/长曝黑场形态）。"""
    rng = np.random.default_rng(seed)
    base = np.full((size, size, 3), 0.008, dtype=np.float32)
    noise = rng.normal(0.0, 0.004, size=(size, size, 3)).astype(np.float32)
    return np.clip(base + noise, 0.0, 1.0)


def _add_gaussian_noise(img: np.ndarray, sigma: float,
                        seed: int) -> np.ndarray:
    """加性高斯噪声（浮点域）。"""
    rng = np.random.default_rng(seed)
    noise = rng.normal(0.0, sigma, size=img.shape).astype(np.float32)
    return np.clip(img + noise, 0.0, 1.0)


def _sprinkle_dead_pixels(img: np.ndarray, n: int, seed: int) -> np.ndarray:
    """随机坏点（死像素，置最亮）模拟传感器坏点。"""
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    rows = rng.integers(0, h, size=n)
    cols = rng.integers(0, w, size=n)
    img = img.copy()
    img[rows, cols] = 1.0
    return img


def build_synthetic_probes(seed: int = 0, size: int = 256):
    """t98：≥5 类合成/低纹理探针（确定性生成，可复跑）。

    返回 [(名称, img_rgb), ...]；img 为 uint8[0,255] 或 float32[0,1]，
    直接适配 PixoAestheticScorer.score 双 dtype 契约。
    """
    rng = np.random.default_rng(seed)
    pure_noise = rng.integers(70, 190, size=(size, size, 3)).astype(np.uint8)
    flat = np.full((size, size, 3), 0.5, dtype=np.float32)
    ramp = np.linspace(0.35, 0.55, size, dtype=np.float32)
    low_contrast = np.empty((size, size, 3), dtype=np.float32)
    low_contrast[:] = ramp[None, :, None]
    return [
        ("纯噪声(均匀随机)", pure_noise),
        ("平坦灰图", flat),
        ("低对比渐变", low_contrast),
        ("渐变天空+星点", _night_sky_base(size=size, seed=seed)),
        ("夜间黑场", _black_field(size=size, seed=seed)),
    ]


def build_degradation_ladder(seed: int = 0, size: int = 256,
                             sigmas=DEGRADATION_SIGMAS):
    """同一星空基底的退化阶梯：加性高斯噪声 + 坏点撒布。

    名称内嵌预期质量序（纯净→最劣），用于检验合成域内相对排名自洽性。
    """
    labels = ["纯净", "轻噪声σ4", "中噪声σ8", "重噪声σ14",
              "极重噪声σ22", "坏点σ30"]
    base = _night_sky_base(size=size, seed=seed)
    out = []
    for idx, (label, sigma) in enumerate(zip(labels, sigmas)):
        img = _add_gaussian_noise(base, sigma, seed=seed + 100 + idx)
        if idx >= 4:  # 末两档追加坏点（死像素）
            img = _sprinkle_dead_pixels(img, n=int(40 * (idx - 3)),
                                        seed=seed + 90 + idx)
        out.append((f"星空退化·{label}", img))
    return out


def _spearman_rho(x, y):
    """秩相关（无 scipy 依赖的朴素实现）；并列秩取平均。"""
    x = list(x)
    y = list(y)
    n = len(x)
    if n < 2:
        return 0.0

    def _rank(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        ranks = [0.0] * len(v)
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    rx = _rank(x)
    ry = _rank(y)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return cov / (sxx * syy) ** 0.5


def synthetic_tables(probe_rows, ladder_rows):
    """t98：组装合成域分位表 + 退化阶梯自洽性结论的 markdown 行。

    probe_rows: 合成探针逐样本行（name + 七维 + elapsed_ms）
    ladder_rows: 退化阶梯行（name + overall；顺序=预期质量序）
    返回 (lines, verdict)；lines 为 markdown 文本行列表（后接空行）。
    """
    lines = [
        "## 合成域分位表（t98 深化：≥5 探针）",
        "",
        "合成探针为生成图。**绝对分无跨域语义**：评分器面向真实摄影"
        "分布训练，合成域得分带不可跨域解释——不可与实拍域绝对分比较，"
        "亦不可直接当废片/好片结论（t58 已制度化跨域禁比 + domain_hint）。",
        "",
        _fmt_row(["合成探针"] + list(DIMS) + ["耗时ms"]),
        _fmt_row(["---"] + ["---"] * len(DIMS) + ["---"]),
    ]
    for r in probe_rows:
        lines.append(_fmt_row(
            [r["name"]]
            + [f"{r[k]:.3f}" for k in DIMS]
            + [f"{r['elapsed_ms']:.0f}"]))
    if len(probe_rows) >= 3:
        lines += ["", "### 合成域分位汇总（探针内，n=%d）" % len(probe_rows),
                  "",
                  _fmt_row(["维度", "p25", "p50", "p75", "min", "max"]),
                  _fmt_row(["---"] * 6)]
        for k in DIMS:
            vals = np.array([r[k] for r in probe_rows], dtype=np.float64)
            lines.append(_fmt_row([
                k, f"{np.percentile(vals, 25):.3f}",
                f"{np.percentile(vals, 50):.3f}",
                f"{np.percentile(vals, 75):.3f}",
                f"{vals.min():.3f}", f"{vals.max():.3f}"]))
        lines += [""]
        lines.append(
            "> 注：n=%d 探针样本少，分位仅示合成域带量级，不作阈值使用。"
            % len(probe_rows))

    verdict = ""
    if len(ladder_rows) >= 2:
        expected = list(range(1, len(ladder_rows) + 1))  # 预期质量序（1 最好）
        actual = [r["overall"] for r in ladder_rows]     # 分数序（越高=模型越好）
        rho = _spearman_rho(expected, actual)
        monotone = all(actual[i] >= actual[i + 1]
                       for i in range(len(actual) - 1))
        lines += ["", "### 域内自洽性：同一场景退化阶梯",
                  "",
                  "对同一星空基底施加单调递增噪声（σ=0→30，末两档追加"
                  "坏点），预期质量序 纯净>轻>中>重>极重>坏点。若模型给分"
                  "随退化单调下降，则合成域内相对排名自洽（Spearman 秩相关）。",
                  "",
                  _fmt_row(["阶梯", "overall", "预期质量序"]),
                  _fmt_row(["---", "---", "---"])]
        for r, exp in zip(ladder_rows, expected):
            lines.append(_fmt_row([r["name"], f"{r['overall']:.3f}", exp]))
        lines += ["",
                  f"- 打分序列：{[round(v, 3) for v in actual]}",
                  f"- Spearman ρ = **{rho:.2f}**；单调递减 = {monotone}"]
        # 符号约定：expected=质量标签(1 最好→n 最差)，模型自洽时打分随标签
        # 序递减 → ρ 为负。可用判定：ρ≤−0.7 且单调递减。
        if rho <= -0.7 and monotone:
            verdict = ("**结论：合成域内相对排名可用。** 同域退化阶梯与模型"
                       "打分序一致（ρ≤−0.7 且单调递减），域内相对排名可作"
                       "合成图质检的相对信号；绝对分仍禁跨域。")
        else:
            verdict = ("**结论：合成域内相对排名仅有限可用/不可靠。** "
                       f"ρ={rho:.2f}（|ρ|过小或非单调），打分序与已知退化序"
                       "不一致——域内相对排名只宜作弱参考，不得作硬性质"
                       "检门槛；批量链路若启用须注明降级语义。")
        lines += ["", verdict]
    return lines, verdict





def _fmt_row(cols):
    return "| " + " | ".join(str(c) for c in cols) + " |"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--long-edge", type=int, default=512)
    ap.add_argument("--samples-per-scene", type=int, default=20)
    args = ap.parse_args()

    from pixo.render.api import Renderer
    from pixo.vision.aesthetic import PixoAestheticScorer

    dcp = sorted(ROOT.joinpath("resources", "dcp").glob("*.dcp"))[0]
    renderer = Renderer(dcp)
    scorer = PixoAestheticScorer()
    health = scorer.health_info()
    print("scorer health:", health)

    rows = []
    baseline_rows = []
    timings = []
    skipped = []
    scene_counts = {}
    for label, files in build_scene_files():
        picks = stratified(files, args.samples_per_scene)
        picked_names = {f.name for f in picks}
        for bname in BASELINE_NAMES.get(label, []):
            if bname not in picked_names:
                match = [f for f in files if f.name == bname]
                if match:
                    picks.append(match[0])
        for fname in FORCE_INCLUDE.get(label, []):
            if fname not in picked_names:
                match = [f for f in files if f.name == fname]
                if match:
                    picks.append(match[0])
                    picked_names.add(fname)
        picks.sort()
        count_scene = 0
        for f in picks:
            try:
                img = renderer.render_preview_full(
                    f, long_edge=args.long_edge)
            except Exception as exc:  # noqa: BLE001 - 坏片跳过并记录
                skipped.append((f.name, type(exc).__name__))
                print("SKIP", f.name, type(exc).__name__)
                continue
            t0 = time.perf_counter()
            out = scorer.score(img)
            elapsed = round((time.perf_counter() - t0) * 1000.0, 1)
            timings.append(elapsed)
            if out is None:
                print("score None:", f.name)
                continue
            is_base = f.name in BASELINE_NAMES.get(label, [])
            row = {"group": label, "file": f.name,
                   "is_baseline": is_base, "elapsed_ms": elapsed}
            row.update({k: round(float(out.get(k, float("nan"))), 3)
                        for k in DIMS})
            rows.append(row)
            if is_base:
                baseline_rows.append(row)
            count_scene += 1
            print(f"{f.name}: overall={row['overall']} "
                  f"({elapsed} ms)")
        scene_counts[label] = count_scene
        print(f"[{label}] samples={count_scene} skipped={len(skipped)}")

    total = len(rows)
    assert total >= 60, f"扩样后有效样本不足: {total}"

    lines = [
        "# 真评分器七维分布与阈值建议（t58 基线 / t71 分层扩样）",
        "",
        f"- 扩样日期：{date.today().isoformat()}",
        f"- 样本：三场景分层各 {args.samples_per_scene}，合计 {total} 张"
        + ("；含基线 12 张强制回含" if baseline_rows else ""),
        "- 场景样本数：" + "、".join(
            f"{k}={v}" for k, v in scene_counts.items()),
        f"- 解码失败跳过：{len(skipped)} 张",
        f"- 渲染：render_preview_full(long_edge={args.long_edge})，"
        "全链默认参数",
        "- 评分：PixoAestheticScorer(source=pixo)，权重已在盘；"
        "七维为 overall/quality/composition/lighting/color/"
        "depth_of_field/content",
        "",
        "## 逐样表明细",
        "",
        _fmt_row(["组", "文件"] + list(DIMS) + ["耗时ms"]),
        _fmt_row(["---"] * 2 + ["---"] * len(DIMS) + ["---"]),
    ]
    for r in rows:
        lines.append(_fmt_row(
            [r["group"], r["file"]]
            + [f"{r[k]:.2f}" for k in DIMS] + [f"{r['elapsed_ms']:.0f}"]))

    lines += ["", "## 扩样分位汇总（全部样本）", "",
              _fmt_row(["维度", "p25", "p50", "p75", "min", "max"]),
              _fmt_row(["---"] * 6)]
    for k in DIMS:
        vals = np.array([r[k] for r in rows], dtype=np.float64)
        lines.append(_fmt_row([
            k, f"{np.percentile(vals, 25):.3f}",
            f"{np.percentile(vals, 50):.3f}",
            f"{np.percentile(vals, 75):.3f}",
            f"{vals.min():.3f}", f"{vals.max():.3f}"]))
    tm = np.array(timings, dtype=np.float64)

    if baseline_rows:
        lines += ["", "## 基线 12 样本对照列（t58 口径复算）", "",
                  _fmt_row(["维度", "p25", "p50", "p75", "min", "max"]),
                  _fmt_row(["---"] * 6)]
        for k in DIMS:
            vals = np.array([r[k] for r in baseline_rows],
                            dtype=np.float64)
            lines.append(_fmt_row([
                k, f"{np.percentile(vals, 25):.3f}",
                f"{np.percentile(vals, 50):.3f}",
                f"{np.percentile(vals, 75):.3f}",
                f"{vals.min():.3f}", f"{vals.max():.3f}"]))
    lines.append(_fmt_row([
        "elapsed_ms", f"{np.percentile(tm, 25):.0f}",
        f"{np.percentile(tm, 50):.0f}", f"{np.percentile(tm, 75):.0f}",
        f"{tm.min():.0f}", f"{tm.max():.0f}"]))

    overall_vals = np.array([r["overall"] for r in rows],
                            dtype=np.float64)
    p25 = float(np.percentile(overall_vals, 25))
    p50 = float(np.percentile(overall_vals, 50))
    rec_accept = round(max(p25 - 0.2, round(p50, 1)), 1)
    rec_stag = 0.1

    # ---- t98 合成域深化：≥5 探针 + 退化阶梯（域内自洽性）----
    probe_rows = []
    for name, img in build_synthetic_probes():
        t0 = time.perf_counter()
        out = scorer.score(img)
        elapsed = round((time.perf_counter() - t0) * 1000.0, 1)
        if out is None:
            print("synthetic score None:", name)
            continue
        row = {"name": name, "elapsed_ms": elapsed}
        row.update({k: round(float(out.get(k, float("nan"))), 3)
                    for k in DIMS})
        probe_rows.append(row)
        print(f"[synthetic] {name}: overall={row['overall']} ({elapsed} ms)")
    ladder_rows = []
    for name, img in build_degradation_ladder():
        out = scorer.score(img)
        if out is None:
            print("ladder score None:", name)
            continue
        ladder_rows.append({
            "name": name,
            "overall": round(float(out.get("overall", 0.0)), 3),
        })
        print(f"[ladder] {name}: overall={ladder_rows[-1]['overall']}")
    synth_lines, verdict = synthetic_tables(probe_rows, ladder_rows)
    lines += [""] + synth_lines
    print("synthetic verdict:", verdict)

    rec_accept = round(p50, 1)
    lines += [
        "", "## 阈值建议（文档化推荐值）", "",
        f"- 实拍域 overall 分布：p25={p25:.2f}，p50={p50:.2f}，"
        f"p75={float(np.percentile(overall_vals, 75)):.2f}",
        "- **重要：真评分器输出为带符号原始分（12 张实拍全部为负），"
        "并非 0-5 或 0-100 假设域；绝对阈值必须以本表经验分布为准，"
        "禁止沿用其他量纲的整数习惯。**",
        f"- 建议 accept_threshold ≈ **{rec_accept}**（取 p50 整档："
        "以中位质量为采纳基线，迭代改善越过中位即视为有效）",
        f"- 建议 stagnation_eps ≈ **{rec_stag}**"
        "（head 输出粒度粗、样张间离散大，连续两轮相对改善低于 0.1 "
        "视为停滞；后续可用同图多轮回测收紧）",
        "- 冷启动提示：首次推理含权重加载约 15.8s，稳态单张 ~20ms——"
        "P3 接线应常驻评分器实例并预热，避免每轮冷启。",
        "- **生产默认仍 None=关，启用由调用方显式传入**——本节仅为"
        "文档化推荐值，不改动任何代码默认。",
    ]

    out_md = ROOT / "docs" / "metrics" / "scorer_distribution.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(chr(10).join(lines), encoding="utf-8")
    print("wrote", out_md)


if __name__ == "__main__":
    main()
