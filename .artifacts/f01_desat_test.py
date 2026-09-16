"""F01 假设检验: 引擎误差是「系统性色相偏移」还是「色度压缩 (chroma compression)」?

背景
----
800 张实测: da 中位 -2.56, 84.2% 为负 → 表面像"系统偏绿"。
但抽查看单张:
  DSC_1682 (饱和绿草地): 相机 a=-24.8 → 我们 a=-15.1  (往 0 收)
  DSC_1515 (日落, 红):     相机 a=+17.7 → 我们 a=+8.0   (也往 0 收)
  DSC_5790 (近中性):       相机 a=-2.3  → 我们 a=-2.7   (几乎不动)
=> 备择假设 H1: 误差是**色度压缩**, da ≈ -k · a_cam (k>0), 在 a_cam≈0 处误差≈0。
   原假设   H0: 误差是固定色相偏移, da ≈ 常数, 与 a_cam 无关。
两者对"怎么修"含义完全不同: H0 → 调一个全局 trim; H1 → 必须动饱和度/矩阵。

判据
----
1. 回归 da = α + β·a_cam:  H1 要求 α≈0 且 β<0; H0 要求 β≈0。
   同理 db = α' + β'·b_cam。
2. 色度比 our_chroma/cam_chroma 应 <1, 且随 cam_chroma 增大而下降。
3. A 应随 cam_chroma 单调上升。

用法: python .artifacts/f01_desat_test.py --n 240
产出: .artifacts/f01_desat_report.md + f01_desat_rows.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / ".artifacts"))

from f01_batch import (  # noqa: E402
    discover, read_thumb, rot_k, to_common, lab_f32, de76, UNDO_ROT,
)

OUT = ROOT / ".artifacts/f01_desat_report.md"
ROWS = ROOT / ".artifacts/f01_desat_rows.json"
EDGE = 384


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=240)
    ap.add_argument("--seed", type=int, default=4242)
    args = ap.parse_args()

    groups = discover(None)
    # 用与主台架同一分层逻辑, 但换 seed 取独立子样本
    from f01_batch import sample
    picked = sample(groups, args.n, args.seed)

    from pixo.render.api import Renderer
    from pixo.meta import extract as meta_extract
    r = Renderer(sorted((ROOT / "resources/dcp").glob("*.dcp"))[0])
    print(f"样本 {len(picked)}  渲染长边 {EDGE}", flush=True)

    rows: list[dict] = []
    t0 = time.time()
    for i, (sess, grp, p) in enumerate(picked, 1):
        try:
            o = int(meta_extract(p)["capture"].get("orientation") or 1)
            thumb = read_thumb(p)
            our = r.render_preview_full(p, long_edge=EDGE)
            a, b = to_common(our, rot_k(thumb, UNDO_ROT.get(o, 0)))
            la, lb = lab_f32(a), lab_f32(b)
            ma = la.reshape(-1, 3).mean(axis=0)
            mb = lb.reshape(-1, 3).mean(axis=0)
            dv = ma - mb
            rows.append({
                "name": p.name, "session": sess,
                "cam_L": float(mb[0]), "cam_a": float(mb[1]), "cam_b": float(mb[2]),
                "our_L": float(ma[0]), "our_a": float(ma[1]), "our_b": float(ma[2]),
                "cam_chroma": float(np.hypot(mb[1], mb[2])),
                "our_chroma": float(np.hypot(ma[1], ma[2])),
                "A": float(np.linalg.norm(dv)),
                "C": de76(la, lb),
                "dL": float(dv[0]), "da": float(dv[1]), "db": float(dv[2]),
                "sat_cam": float(np.hypot(mb[1], mb[2])),
            })
        except Exception as e:  # noqa: BLE001
            rows.append({"name": p.name, "err": f"{type(e).__name__}: {e}"})
        if i % 30 == 0 or i == len(picked):
            print(f"  [{i}/{len(picked)}] {time.time() - t0:.0f}s", flush=True)

    ok = [x for x in rows if "err" not in x]
    ROWS.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    if len(ok) < 20:
        raise SystemExit("有效样本不足")

    G = lambda k: np.array([x[k] for x in ok], float)  # noqa: E731

    def fit(x, y):
        A_ = np.vstack([np.ones_like(x), x]).T
        coef, *_ = np.linalg.lstsq(A_, y, rcond=None)
        pred = A_ @ coef
        ss = 1 - ((y - pred) ** 2).sum() / max(((y - y.mean()) ** 2).sum(), 1e-9)
        rho = float(np.corrcoef(x, y)[0, 1])
        return float(coef[0]), float(coef[1]), float(ss), rho

    L = ["# F01 假设检验: 色相偏移 vs 色度压缩\n",
         f"- 样本 {len(ok)} (种子 {args.seed}, 长边 {EDGE})",
         "- H0 固定色相偏移: da ≈ 常数，与场景色度无关",
         "- H1 色度压缩: da ≈ -k·a_cam (k>0)，在 a_cam≈0 处误差≈0\n"]

    L.append("## 回归结果 (判据 1)\n")
    L.append("| 回归 | 截距 α | 斜率 β | R² | r | 判定 |")
    L.append("|---|---:|---:|---:|---:|---|")
    for yk, xk, lab in (("da", "cam_a", "da ~ a_cam"),
                        ("db", "cam_b", "db ~ b_cam"),
                        ("dL", "cam_L", "dL ~ L_cam")):
        a0, b1, s, rho = fit(G(xk), G(yk))
        verdict = ("支持 **H1 色度压缩**" if (abs(a0) < 0.5 * abs(G(yk).std()) and b1 < -0.05)
                   else "支持 **H0 固定偏移**" if abs(b1) < 0.05
                   else "介于两者之间")
        L.append(f"| {lab} | {a0:+.2f} | {b1:+.3f} | {s:.3f} | {rho:+.3f} | {verdict} |")
    L.append("")
    L.append("> H1 期望: 截距≈0, 斜率显著为负, R² 高。\n")

    # 判据 2: 色度比
    ratio = G("our_chroma") / np.maximum(G("cam_chroma"), 1e-6)
    L.append("## 色度保持率 (判据 2)\n")
    L.append(f"- our_chroma / cam_chroma: median **{np.median(ratio):.3f}** "
             f"(p25 {np.percentile(ratio, 25):.3f}, p75 {np.percentile(ratio, 75):.3f})")
    L.append(f"- <1 的占比: {(ratio < 1).mean() * 100:.1f}%")
    cc = G("cam_chroma")
    qs = np.percentile(cc, [0, 25, 50, 75, 100])
    L.append("")
    L.append("| 相机色度区间 | n | 色度保持率 median | A median | da median | db median |")
    L.append("|---|---:|---:|---:|---:|---:|")
    for j in range(4):
        m = (cc >= qs[j]) & (cc <= qs[j + 1] if j == 3 else cc < qs[j + 1])
        if m.sum() == 0:
            continue
        L.append(f"| {qs[j]:.0f}–{qs[j + 1]:.0f} | {int(m.sum())} | {np.median(ratio[m]):.3f} | "
                 f"{np.median(G('A')[m]):.2f} | {np.median(G('da')[m]):+.2f} | "
                 f"{np.median(G('db')[m]):+.2f} |")
    L.append("")
    L.append("> H1 期望: 色度越高，保持率越低、A 越大。\n")

    # 判据 3
    rho_A = float(np.corrcoef(cc, G("A"))[0, 1])
    L.append("## 判据 3: A 随场景色度\n")
    L.append(f"- Pearson r (cam_chroma ↔ A) = **{rho_A:+.3f}**")
    L.append(f"- 结论: {'色度越高误差越大 → 支持 H1' if rho_A > 0.4 else '无强相关 → 不支持 H1'}\n")

    # 按会话 (解释 0711 为何 da≈0)
    L.append('## 分会话: 为什么 0711 看起来"准"\n')
    L.append("| 会话 | n | cam_chroma median | da median | 保持率 median |")
    L.append("|---|---:|---:|---:|---:|")
    for s in sorted({x["session"] for x in ok}):
        m = np.array([x["session"] == s for x in ok])
        L.append(f"| {s} | {int(m.sum())} | {np.median(cc[m]):.2f} | "
                 f"{np.median(G('da')[m]):+.2f} | {np.median(ratio[m]):.3f} |")
    L.append("")

    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print("\n".join(L))
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
