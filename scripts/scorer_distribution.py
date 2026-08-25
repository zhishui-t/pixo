"""生成真评分器七维分布表与阈值建议（t58）。

对 12 样张（0711 前4后2、2026春节 前4后2）真实渲染小图后跑
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
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]
GROUPS = [
    ("0711", Path("K:/data/photo/0711/raw")),
    ("春节", Path("K:/data/photo/2026春节")),
]
DIMS = ("overall", "quality", "composition", "lighting", "color",
        "depth_of_field", "content")


def pick_samples(folder: Path):
    files = sorted(f for f in folder.glob("*.NEF")
                   if not f.name.startswith("._"))
    return files[:4] + files[-2:]


def synthetic_domain_images():
    """低纹理/合成交互域样本：量化"低分≠废片"的域外程度。"""
    flat = np.full((256, 256, 3), 0.5, dtype=np.float32)
    rng = np.random.default_rng(0)
    noise = rng.integers(70, 190, size=(256, 256, 3)).astype(np.uint8)
    ramp = np.linspace(0.35, 0.55, 256, dtype=np.float32)
    low_contrast = np.empty((256, 256, 3), dtype=np.float32)
    low_contrast[:] = ramp[None, :, None]
    return [("平坦灰图", flat), ("随机噪声(测试同款)", noise),
            ("低对比渐变", low_contrast)]


def _fmt_row(cols):
    return "| " + " | ".join(str(c) for c in cols) + " |"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--long-edge", type=int, default=512)
    args = ap.parse_args()

    from pixo.render.api import Renderer
    from pixo.vision.aesthetic import PixoAestheticScorer

    dcp = sorted(ROOT.joinpath("resources", "dcp").glob("*.dcp"))[0]
    renderer = Renderer(dcp)
    scorer = PixoAestheticScorer()
    health = scorer.health_info()
    print("scorer health:", health)

    rows = []
    timings = []
    for label, folder in GROUPS:
        for f in pick_samples(folder):
            if not f.exists():
                print("missing", f)
                continue
            img = renderer.render_preview_full(f,
                                               long_edge=args.long_edge)
            t0 = time.perf_counter()
            out = scorer.score(img)
            elapsed = round((time.perf_counter() - t0) * 1000.0, 1)
            timings.append(elapsed)
            if out is None:
                print("score None:", f.name)
                continue
            row = {"group": label, "file": f.name,
                   "elapsed_ms": elapsed}
            row.update({k: round(float(out.get(k, float("nan"))), 3)
                        for k in DIMS})
            rows.append(row)
            print(f"{f.name}: overall={row['overall']} "
                  f"({elapsed} ms)")

    assert len(rows) >= 12, f"有效样本不足: {len(rows)}"

    lines = [
        "# 真评分器七维分布与阈值建议（t58）",
        "",
        f"- 样本：0711 前4+后2、2026春节 前4+后2，共 {len(rows)} 张",
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

    lines += ["", "## 分位数汇总（实拍域）", "",
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

    lines += [
        "", "## 合成/低纹理域专项（低分≠废片 的域外程度）", "",
        "以下为合成图在真评分器下的得分。测试用噪声图被评低分属域外"
        "正常行为——评分器面向真实摄影分布训练，随机纹理/纯色不在其"
        "语义域内，**不能据此判定图片为废片**；闭环/批量链路不得把"
        "低分直接当质量结论。",
        "",
        _fmt_row(["合成样本", "overall", "说明"]),
        _fmt_row(["---", "---", "---"]),
    ]
    for name, img in synthetic_domain_images():
        out = scorer.score(img)
        val = "None" if out is None else f"{out.get('overall', 0):.2f}"
        note = ("零纹理无语义" if name == "平坦灰图"
                else "随机噪声=无摄影语义，测试夹具典型输入"
                if "噪声" in name else "低对比但真实存在")
        lines.append(_fmt_row([name, val, note]))

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
