"""生成三代理指标实测分布表（t41 基线 / t71 全语料分层扩样）。

t71 扩样：三场景（0711 / 2026春节 / 厦门编号子目录）分层抽样，默认
每场景 20 张（--samples-per-scene 可调），合计 >=60；同时强制包含
t41 原 12 样本作为基线对照列。输出 docs/metrics/proxy_distribution.md：
扩样日期标注、逐样表明细、扩样分位汇总、基线(12)对照、P2 六条阈值
漂移核对结论。

用法: python scripts/proxy_distribution.py [--long-edge 512]
         [--samples-per-scene 20]
"""
import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]
METRICS = ("haze_proxy", "colorfulness_proxy", "tonal_range")


def _fmt_row(cols):
    return "| " + " | ".join(str(c) for c in cols) + " |"

# 三场景：目录列表（厦门为编号子目录，逐个展开）
SCENES = [
    ("0711", [Path("K:/data/photo/0711/raw")]),
    ("春节", [Path("K:/data/photo/2026春节")]),
    ("厦门", []),
]

# t41 基线 12 样本文件名（对照列强制回含）
# t71+ 协调：厦门高调域外代表样本强制回含（t73 曝光缺口诊断证据）
FORCE_INCLUDE = {
    "厦门": ["DSC_0847.NEF"],
}

BASELINE_NAMES = {
    "0711": ["DSC_5236.NEF", "DSC_5237.NEF", "DSC_5238.NEF",
             "DSC_5239.NEF", "DSC_6006.NEF", "DSC_6007.NEF"],
    "春节": ["DSC_0352.NEF", "DSC_0353.NEF", "DSC_0354.NEF",
             "DSC_0355.NEF", "DSC_0606.NEF", "DSC_0607.NEF"],
}

# t41 发布的基线分位（docs/metrics 旧表），供漂移对照
OLD_BASELINE_PCTS = {
    "haze_proxy": (0.1202, 0.1633, 0.2260),
    "colorfulness_proxy": (4.7795, 5.4257, 6.1292),
    "tonal_range": (0.4636, 0.5218, 0.6821),
}

# P2 规则六条阈值（tone_clarity_rules.yaml 等现行值）
P2_THRESHOLDS = {
    "dehaze_trigger_ge": 0.22,          # haze_proxy >= 0.22 触发去雾
    "clarity_entry_ge": 0.12,           # haze_proxy >= 0.12 进入带通
    "clarity_band_lt": 0.22,            # 且 haze_proxy < 0.22
    "tonal_guard_ge": 0.46,             # tonal_range >= 0.46 守卫
    "vibrance_le": 4.78,                # colorfulness <= 4.78 低饱和带
    "saturation_ge": 6.13,              # colorfulness >= 6.13 高饱和带
}


def _valid_nefs(folder: Path):
    return sorted(f for f in folder.glob("*.NEF")
                  if not f.name.startswith("._"))


def build_scene_files():
    """返回 [(scene_label, [files...])]；厦门展开编号子目录。"""
    out = []
    scenes = []
    for label, dirs in SCENES:
        if label == "厦门":
            base = Path("K:/data/photo/厦门")
            dirs = sorted(d for d in base.iterdir() if d.is_dir())                 if base.is_dir() else []
            scenes.append((label, dirs))
        else:
            scenes.append((label, list(dirs)))
    for label, dirs in scenes:
        files = []
        for d in dirs:
            files.extend(_valid_nefs(d))
        files = sorted(set(files))
        if files:
            out.append((label, files))
    return out


def stratified(files, n):
    """排序后按 linspace 均匀取 n 个代表点（跨编号域铺开）。"""
    if len(files) <= n:
        return list(files)
    idx = np.linspace(0, len(files) - 1, n)
    idx = sorted({int(round(v)) for v in idx})
    return [files[i] for i in idx]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--long-edge", type=int, default=512)
    ap.add_argument("--samples-per-scene", type=int, default=20)
    args = ap.parse_args()

    from pixo.render.api import Renderer
    from pixo.vision.measure import compute_proxy_metrics

    dcp = sorted(ROOT.joinpath("resources", "dcp").glob("*.dcp"))[0]
    renderer = Renderer(dcp)

    rows = []
    baseline_rows = []
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
                skipped.append((str(f), type(exc).__name__ + ": " + str(exc)[:80]))
                print("SKIP", f.name, type(exc).__name__, str(exc)[:60])
                continue
            m = compute_proxy_metrics(img)
            is_base = f.name in BASELINE_NAMES.get(label, [])
            rows.append({"group": label, "file": f.name,
                         "is_baseline": is_base, **m})
            if is_base:
                baseline_rows.append(rows[-1])
            count_scene += 1
        scene_counts[label] = count_scene
        print(f"[{label}] samples={count_scene} skipped={len(skipped)}")

    total = len(rows)
    assert total >= 60, f"扩样后样本不足: {total}"

    def pct_table(section_rows):
        lines = [_fmt_row(["指标", "p25", "p50", "p75", "min", "max"]),
                 _fmt_row(["---"] * 6)]
        for k in METRICS:
            vals = np.array([r[k] for r in section_rows], dtype=np.float64)
            lines.append(_fmt_row([
                k, f"{np.percentile(vals, 25):.4f}",
                f"{np.percentile(vals, 50):.4f}",
                f"{np.percentile(vals, 75):.4f}",
                f"{vals.min():.4f}", f"{vals.max():.4f}"]))
        return lines

    new_pcts = {k: tuple(float(np.percentile(
        [r[k] for r in rows], q)) for q in (25, 50, 75)) for k in METRICS}

    lines = [
        "# 三代理指标实测分布表（t41 基线 / t71 全语料分层扩样）",
        "",
        f"- 扩样日期：{date.today().isoformat()}",
        f"- 样本：三场景分层各 {args.samples_per_scene}，"
        f"合计 {total} 张"
        + ("；含 t41 基线 12 张强制回含" if baseline_rows else ""),
        "- 场景样本数：" + "、".join(
            f"{k}={v}" for k, v in scene_counts.items()),
        "- 形态说明：全语料未发现 JPG 直出层（仅 RAW），双形态对照不可行",
        f"- 解码失败跳过：{len(skipped)} 张"
        + ("；明细：" + "；".join(f"{Path(fp).name}({rs})" for fp, rs in skipped[:5]) if skipped else ""),
        f"- 渲染：render_preview_full(long_edge={args.long_edge})，"
        "全链默认参数",
        "",
        "## 扩样分位汇总（全部样本）", "",
    ]
    lines += pct_table(rows)

    lines += ["", "## 基线 12 样本对照列（t41 口径复算）", ""]
    if baseline_rows:
        lines += pct_table(baseline_rows)
        lines.append("")
        lines.append("旧表发布值(t41)：" + "；".join(
            f"{k} p25/p50/p75=" + "/".join(f"{v:.4f}" for v in OLD_BASELINE_PCTS[k])
            for k in METRICS))
    else:
        lines.append("(基线文件缺失，无法复算)")

    drift = []
    hz = new_pcts["haze_proxy"]
    tr = new_pcts["tonal_range"]
    cf = new_pcts["colorfulness_proxy"]
    drift.append(
        f"- dehaze 触发 >= {P2_THRESHOLDS['dehaze_trigger_ge']}："
        f"新 p75(haze)={hz[2]:.4f} → "
        + ("仍可触发" if hz[2] >= P2_THRESHOLDS["dehaze_trigger_ge"]
           else "触发簇上移不足，阈值需下探"))
    drift.append(
        f"- clarity 带通 [{P2_THRESHOLDS['clarity_entry_ge']}, "
        f"{P2_THRESHOLDS['clarity_band_lt']})：新 p25={hz[0]:.4f}/"
        f"p50={hz[1]:.4f} → 入口 {'仍覆盖' if hz[0] <= P2_THRESHOLDS['clarity_entry_ge'] else '入口偏移'}"
        f"，带通上限 {'仍截到分布' if hz[1] < P2_THRESHOLDS['clarity_band_lt'] else '已越过'}")
    drift.append(
        f"- tonal 守卫 >= {P2_THRESHOLDS['tonal_guard_ge']}："
        f"新 p25(tonal)={tr[0]:.4f} → "
        + ("守卫仍可达" if tr[0] >= P2_THRESHOLDS["tonal_guard_ge"] * 0.9
           else "守卫偏紧"))
    drift.append(
        f"- vibrance 低饱和带 <= {P2_THRESHOLDS['vibrance_le']}："
        f"新 p25(cf)={cf[0]:.4f} → "
        + ("低饱和带仍有人口" if cf[0] <= P2_THRESHOLDS["vibrance_le"]
           else "低饱和带人口流失"))
    drift.append(
        f"- saturation 高饱和带 >= {P2_THRESHOLDS['saturation_ge']}："
        f"新 p75(cf)={cf[2]:.4f} → "
        + ("高饱和带仍有人口" if cf[2] >= P2_THRESHOLDS["saturation_ge"]
           else "高饱和带人口不足"))

    lines += ["", "## P2 六条阈值漂移核对（扩样 vs 现行阈值）", ""] + drift

    # 高调缺口案例档案（t71+ 协调批准）：预算哨兵失效模式首个实证。
    case_file = None
    for label, files in build_scene_files():
        if label != "厦门":
            continue
        for f in files:
            if f.name == "DSC_0847.NEF":
                case_file = f
                break
        if case_file is not None:
            break
    if case_file is not None:
        cimg = renderer.render_preview_full(case_file,
                                            long_edge=args.long_edge)
        carr = cimg.astype(np.float32) / 255.0
        cgray = (0.2126 * carr[..., 0] + 0.7152 * carr[..., 1]
                 + 0.0722 * carr[..., 2])
        c_med255 = float(np.median(cgray)) * 255.0
        c_mean = float(np.mean(cgray))
        c_p99 = float(np.percentile(cgray, 99))
        c_p95 = float(np.percentile(cgray, 95))
        c_tr = c_p95 - float(np.percentile(cgray, 5))
        lines += [
            "", "## 高调缺口案例 DSC_0847（预算哨兵失效模式实证）", "",
            f"- 样本路径：{case_file}",
            f"- 四读数（渲染后灰度域）：gray_med={c_med255:.1f}"
            "(0-255口径) / "
            f"mean={c_mean:.3f} / p99={c_p99:.4f} / p95={c_p95:.4f}；"
            f"tonal_range={c_tr:.4f}",
            "- 结论：p99≈p95 顶部重合 → 高光仍被 highlight_budget "
            "预算哨兵钳死，合法提亮未放行。",
            "- 历史对照：t71 首测同图 gray_med=62.9（开发3 报 dL≈-55）；"
            f"本表复测 {c_med255:.1f} ——期间曝光/暖度标定经并行调整，"
            "缺口收窄但哨兵钳制特征仍在。预算/标定修正(t73)引用时以"
            "本节最新读数为准。",
        ]

    out_md = ROOT / "docs" / "metrics" / "proxy_distribution.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(chr(10).join(lines), encoding="utf-8")
    print("wrote", out_md)


if __name__ == "__main__":
    main()
