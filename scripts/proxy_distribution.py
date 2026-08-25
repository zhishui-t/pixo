"""生成三代理指标实测分布表（t41）。

对 0711 与 2026春节 各取前 4 + 后 2 张 RAW（共 ≥12 张），全链渲染小图
（long_edge=512）后统计 compute_proxy_metrics 三指标，输出
docs/metrics/proxy_distribution.md（逐样表明细 + p25/p50/p75 汇总），
作为 P2 规则包阈值重推依据。

用法: python scripts/proxy_distribution.py [--long-edge 512]
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]
GROUPS = [
    ("0711", Path("K:/data/photo/0711/raw")),
    ("春节", Path("K:/data/photo/2026春节")),
]
METRICS = ("haze_proxy", "colorfulness_proxy", "tonal_range")


def pick_samples(folder: Path):
    # 过滤 macOS AppleDouble 垃圾文件（._DSC_xxx.NEF）
    files = sorted(f for f in folder.glob("*.NEF")
                   if not f.name.startswith("._"))
    return files[:4] + files[-2:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--long-edge", type=int, default=512)
    args = ap.parse_args()

    from pixo.render.api import Renderer
    from pixo.vision.measure import compute_proxy_metrics

    dcp = sorted(ROOT.joinpath("resources", "dcp").glob("*.dcp"))[0]
    renderer = Renderer(dcp)

    rows = []
    for label, folder in GROUPS:
        for f in pick_samples(folder):
            if not f.exists():
                print("missing", f)
                continue
            img = renderer.render_preview_full(f,
                                               long_edge=args.long_edge)
            m = compute_proxy_metrics(img)
            rows.append({"group": label, "file": f.name, **m})
            print(f"{f.name}: " + " ".join(
                f"{k}={m[k]:.4f}" for k in METRICS))

    assert len(rows) >= 12, f"样本不足: {len(rows)}"

    lines = [
        "# 三代理指标实测分布表（t41）",
        "",
        f"- 样本：0711 前4+后2、2026春节 前4+后2，共 {len(rows)} 张",
        f"- 渲染：render_preview_full(long_edge={args.long_edge})，"
        "全链默认参数",
        "- 口径：compute_proxy_metrics 统一 [0,1] 域"
        "（haze/colorfulness 归一化口径见 measure.py docstring）",
        "- 用途：P2 规则包（tone_clarity_rules.yaml 等）阈值重推依据",
        "",
        "## 逐样表明细",
        "",
        "| 组 | 文件 | haze_proxy | colorfulness_proxy | tonal_range |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['group']} | {r['file']} | {r['haze_proxy']:.4f} | "
            f"{r['colorfulness_proxy']:.2f} | {r['tonal_range']:.4f} |")

    lines += ["", "## 分位数汇总", "",
              "| 指标 | p25 | p50 | p75 | min | max |", "|---|---|---|---|---|---|"]
    for k in METRICS:
        vals = np.array([r[k] for r in rows], dtype=np.float64)
        lines.append(
            f"| {k} | {np.percentile(vals, 25):.4f} | "
            f"{np.percentile(vals, 50):.4f} | {np.percentile(vals, 75):.4f} "
            f"| {vals.min():.4f} | {vals.max():.4f} |")

    out = ROOT / "docs" / "metrics" / "proxy_distribution.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(chr(10).join(lines), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
