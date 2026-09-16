"""R18 任务2: RP-CCM 拟合残差空间/频段分布评估 (tech_debt #13.4) —— 只读实验。

问题 (台账 #13.4): 拟合残差若集中在低频结构 (ISP 风格差) → 高斯低通加权采样
有望收益; 若残差近像素独立 (JPEG 噪声/视差) → 低通加权无益, 建议数据性关闭。

方法 (拟合口径 1:1 复刻, 不改 fit_rp_ccm.py):
  - 渲染: Renderer 中性参数 (exposure 0.0 / trim [1,1,1]) @512 —— 与拟合同口径;
  - 采样: stride=4 网格 + 双侧线性窗 [0.01,0.90] (fit_rp_ccm 同参数), 保留网格
    坐标与参考梯度 (拟合脚本丢弃坐标, 本实验需要空间分布);
  - 残差: 已发布系数 (configs/color/rp_ccm_nikon_z5_2.json) 逐样本残差;
  - 频段量化:
      a) LF 能量占比 = Var(G2(残差图)) / Var(残差图) (σ=2 网格格 ≈8px 原图);
      b) 残差图空间自相关 = corr(残差, G2(残差)) (白噪声 → ≈0);
      c) 池化径向功率谱 (FFT 频段分桶: DC-0.1 / 0.1-0.3 / 0.3-0.6 / 0.6-1);
      d) 结构相关: corr(残差, G8(参考亮度)) 与 corr(|残差|, |∇参考亮度|)
         —— "ISP 风格差"假设检验;
  - 加权拟合模拟 (不动拟合代码): 样本级加权正规方程 (Gram 累积), 权重
    w=exp(−g²/2σg²) (g=参考亮度梯度幅值, σg=语料梯度中位), 边缘/噪声降权。
    奇偶照片 27/27 交叉验证: 训练半各自解基线/加权矩阵, 测试半量 ΔE2000 与
    残差 (泛化收益 = 加权相对基线的测试侧改善)。
  - 预登记判定线: LF 占比中位 <0.30 且 自相关中位 <0.5 且 |结构相关|<0.30 且
    |亮度相关|<0.30 → 残差"不集中低频" → 建议数据性关闭 #13.4; 否则给出加权
    方案与量化收益。

用法: python .artifacts/rp_ccm_lowfreq_eval.py [--limit N]
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
sys.path.insert(0, str(ROOT / "scripts"))

from fit_rp_ccm import DCP, SAMPLE_LIN_HI, SAMPLE_LIN_LO, aligned_pair, iter_corpus  # noqa: E402
from pixo.pipeline.perceptual import delta_e_2000, linear_srgb_to_lab  # noqa: E402
from pixo.render.core.rp_ccm import rp_features  # noqa: E402
from pixo.render.core.tone import srgb_decode  # noqa: E402

try:
    from scipy.ndimage import gaussian_filter
except ImportError:  # pragma: no cover
    from cv2 import GaussianBlur as _gb

    def gaussian_filter(img, sigma):
        k = int(sigma * 3) | 1
        return _gb(img, (k, k), sigma)

CKPT_DIR = Path(__file__).resolve().parent / "rp_ccm_lowfreq_ckpt"
OUT = Path(__file__).resolve().parent / "rp_ccm_lowfreq_results.json"
STRIDE = 4
SIGMA_GRID = 2.0
SIGMA_STRUCT = 8.0


def gaussian(img: np.ndarray, sigma: float) -> np.ndarray:
    return gaussian_filter(img, sigma)


def render_phase(limit: int = 0) -> list[str]:
    """逐照片渲染+采样, 落盘 npz (F/dst/grad/maps), 返回完成 photo_id 列表。"""
    from pixo.render.api import Renderer

    items = iter_corpus("exports/auto/full_scan", None, limit)
    renderer = Renderer(DCP)
    coeff = json.loads((ROOT / "configs" / "color" / "rp_ccm_nikon_z5_2.json")
                       .read_text(encoding="utf-8"))
    M = np.asarray(coeff["matrix"], dtype=np.float64)
    degree = int(coeff.get("degree", 2))
    CKPT_DIR.mkdir(exist_ok=True)

    ids: list[str] = []
    t0 = time.time()
    for i, (pid, raw) in enumerate(items, 1):
        npz = CKPT_DIR / f"{pid}.npz"
        if npz.exists():
            ids.append(pid)
            continue
        try:
            pair = aligned_pair(renderer, raw, 512)
            if pair is None:
                raise RuntimeError("对齐失败")
            base, ref = pair
            gb = srgb_decode(np.ascontiguousarray(base[::STRIDE, ::STRIDE]).astype(np.float32))
            gr = srgb_decode(np.ascontiguousarray(ref[::STRIDE, ::STRIDE]).astype(np.float32))
            Hg, Wg = gb.shape[:2]
            bfl = gb.reshape(-1, 3).astype(np.float64)
            rfl = gr.reshape(-1, 3).astype(np.float64)
            ok = np.all((bfl >= SAMPLE_LIN_LO) & (bfl <= SAMPLE_LIN_HI), axis=1) & \
                 np.all((rfl >= SAMPLE_LIN_LO) & (rfl <= SAMPLE_LIN_HI), axis=1)
            if int(ok.sum()) < 1000:
                raise RuntimeError(f"有效样本过少 {int(ok.sum())}")
            src, dst = bfl[ok], rfl[ok]
            gain = float(dst.mean() / max(src.mean(), 1e-9))
            src_g = src * gain                          # 拟合同口径增益对齐
            F = rp_features(src_g, degree)
            resid = F @ M.T - dst
            r_norm = np.linalg.norm(resid, axis=1)
            ref_lum = gr @ np.array([0.2126, 0.7152, 0.0722])
            gy, gx = np.gradient(ref_lum)
            grad = np.sqrt(gx ** 2 + gy ** 2)
            rr, cc = np.divmod(np.flatnonzero(ok), Wg)
            map_norm = np.full((Hg, Wg), np.nan)
            map_norm[rr, cc] = r_norm
            map_dc = np.full((Hg, Wg), np.nan)
            map_dc[rr, cc] = np.linalg.norm(resid.mean(axis=0))
            np.savez_compressed(npz, F=F, dst=dst, grad=grad,  # 全网格 (分析侧按 valid 取)
                                map_norm=map_norm, map_dc=map_dc,
                                ref_lum=ref_lum, valid=ok.reshape(Hg, Wg))
            ids.append(pid)
            print(f"[{i}/{len(items)}] {pid} n={int(ok.sum())} "
                  f"resid_med={float(np.median(r_norm)):.4f}", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[{i}/{len(items)}] {pid} 跳过: {exc}", flush=True)
    print(f"render phase done ({time.time() - t0:.0f}s)", flush=True)
    return ids


def load_all(ids: list[str]) -> list[dict]:
    out = []
    for pid in ids:
        z = np.load(CKPT_DIR / f"{pid}.npz")
        out.append({"pid": pid, **{k: z[k] for k in z.files}})
    return out


def freq_metrics(recs: list[dict]) -> dict:
    lf_fracs, autocorrs, struct_corrs, lum_corrs, spectra, med = [], [], [], [], [], []
    for rec in recs:
        mn, valid = rec["map_norm"], rec["valid"].astype(bool)
        v = mn[valid]
        if v.size < 500:
            continue
        med.append(float(np.median(v)))
        filled = np.where(valid, mn, float(np.nanmean(v)))
        low = gaussian(filled, SIGMA_GRID)
        var_total = float(np.var(filled))
        if var_total <= 1e-12:
            continue
        lf_fracs.append(float(np.var(low) / var_total))
        c = filled - float(np.mean(filled))
        autocorrs.append(float(np.corrcoef(c.ravel(), gaussian(c, SIGMA_GRID).ravel())[0, 1]))
        lv = low[valid]
        gl = gaussian(rec["ref_lum"], SIGMA_STRUCT)
        if np.std(lv) > 1e-12 and np.std(gl[valid]) > 1e-12:
            lum_corrs.append(float(np.corrcoef(lv, gl[valid])[0, 1]))
        gv = rec["grad"]
        gv_map = np.where(valid, gv, np.nan)
        gvv = gv_map[valid]
        if np.std(v) > 1e-12 and np.std(gvv) > 1e-12:
            struct_corrs.append(float(np.corrcoef(v, gvv)[0, 1]))
        f = c * np.hanning(c.shape[0])[:, None] * np.hanning(c.shape[1])[None, :]
        ps = np.abs(np.fft.fftshift(np.fft.fft2(f))) ** 2
        spectra.append(ps / (float(ps.sum()) + 1e-12))
    pooled = {
        "n_photos": len(lf_fracs),
        "resid_norm_median": float(np.median(np.concatenate(
            [r["map_norm"][r["valid"].astype(bool)] for r in recs]))),
        "lf_frac_median": float(np.median(lf_fracs)),
        "lf_frac_p90": float(np.quantile(lf_fracs, 0.90)),
        "autocorr_median": float(np.median(autocorrs)),
        "struct_grad_corr_median": float(np.median(struct_corrs)),
        "lum_lowfreq_corr_median": float(np.median(lum_corrs)),
    }
    if spectra:
        acc: dict[tuple, list] = {}
        ph, pw = spectra[0].shape
        cy, cx = ph // 2, pw // 2
        yy, xx = np.mgrid[0:ph, 0:pw]
        rad = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2) / max(cy, cx)
        for ps in spectra:
            for lo, hi in ((0.0, 0.1), (0.1, 0.3), (0.3, 0.6), (0.6, 1.01)):
                m = (rad >= lo) & (rad < hi)
                acc.setdefault((lo, hi), []).append(float(ps[m].sum()))
        pooled["radial_energy_frac"] = {f"{lo:.1f}-{hi:.1f}": float(np.mean(v))
                                        for (lo, hi), v in acc.items()}
    return pooled


def weighted_fit_sim(recs: list[dict]) -> dict:
    """加权正规方程模拟 (Gram 累积) + 奇偶交叉验证。"""
    recs = [r for r in recs if r["F"].shape[0] >= 1000]
    order = sorted(range(len(recs)), key=lambda k: recs[k]["pid"])
    recs = [recs[k] for k in order]
    test_idx = list(range(1, len(recs), 2))     # 奇数位 = 测试
    train_idx = list(range(0, len(recs), 2))    # 偶数位 = 训练

    # σg: 语料梯度中位 (自适应带宽; 仅窗内有效样本)
    grads = np.concatenate([r["grad"][r["valid"].astype(bool)] for r in recs])
    sigma_g = float(np.median(grads))

    def gram(idxs, weighted: bool):
        G = np.zeros((6, 6))
        B = np.zeros((6, 3))
        for k in idxs:
            F, dst = recs[k]["F"], recs[k]["dst"]
            g = recs[k]["grad"][recs[k]["valid"].astype(bool)]
            w = np.exp(-(g ** 2) / (2 * sigma_g ** 2)) if weighted \
                else np.ones_like(g)
            Fw = F * w[:, None]
            G += Fw.T @ F
            B += Fw.T @ dst
        return np.linalg.solve(G + 1e-12 * np.eye(6), B).T   # (3,6)

    def eval_on(idxs, M):
        d_a, d_b, rn = [], [], []
        for k in idxs:
            F, dst = recs[k]["F"], recs[k]["dst"]
            pred = F @ M.T
            rn.append(np.linalg.norm(pred - dst, axis=1))
            # ΔE 用亮度对齐后的色度差 (评估口径); dst 即参考
            gain = float(dst.mean() / max(F[:, :3].mean(), 1e-9))
            d_a.append(delta_e_2000(linear_srgb_to_lab(F[:, :3] * gain),
                                    linear_srgb_to_lab(dst)))
            d_b.append(delta_e_2000(linear_srgb_to_lab(pred * gain),
                                    linear_srgb_to_lab(dst)))
        va, vb = np.concatenate(d_a), np.concatenate(d_b)
        vr = np.concatenate(rn)
        return {"de_median": float(np.median(vb)), "de_p95": float(np.quantile(vb, 0.95)),
                "resid_median": float(np.median(vr)),
                "baseline_de_median": float(np.median(va)),
                "baseline_de_p95": float(np.quantile(va, 0.95))}

    M_base_train = gram(train_idx, weighted=False)
    M_w_train = gram(train_idx, weighted=True)
    test_base = eval_on(test_idx, M_base_train)
    test_w = eval_on(test_idx, M_w_train)
    # 加权拟合自身的残差 LF 占比 (训练侧, 同频段口径)
    def lf_of(M, idxs):
        fr = []
        for k in idxs:
            F, dst = recs[k]["F"], recs[k]["dst"]
            Hg, Wg = recs[k]["map_norm"].shape
            valid = recs[k]["valid"].astype(bool)
            rr, cc = np.where(valid)
            rn = np.linalg.norm(F @ M.T - dst, axis=1)
            m = np.full((Hg, Wg), np.nan)
            m[rr, cc] = rn
            filled = np.where(valid, m, float(np.nanmean(m)))
            var_t = float(np.var(filled))
            if var_t <= 1e-12:
                continue
            fr.append(float(np.var(gaussian(filled, SIGMA_GRID)) / var_t))
        return float(np.median(fr)) if fr else float("nan")

    return {
        "sigma_g_median_grad": sigma_g,
        "test_baseline": test_base, "test_weighted": test_w,
        "de_median_delta": test_w["de_median"] - test_base["de_median"],
        "train_lf_frac_baseline": lf_of(M_base_train, train_idx),
        "train_lf_frac_weighted": lf_of(M_w_train, train_idx),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    ids = render_phase(args.limit)
    recs = load_all(ids)
    pooled = freq_metrics(recs)
    sim = weighted_fit_sim(recs)
    verdict_lf = (pooled["lf_frac_median"] < 0.30 and pooled["autocorr_median"] < 0.5
                  and abs(pooled["struct_grad_corr_median"]) < 0.30
                  and abs(pooled["lum_lowfreq_corr_median"]) < 0.30)
    out = {
        "freq": pooled, "weighted_sim": sim,
        "verdict": ("NOT_CONCENTRATED → 建议数据性关闭 #13.4" if verdict_lf
                    else "CONCENTRATED → 建议低通加权方案"),
        "pre_registered_rule": "LF占比<0.30 且 自相关<0.5 且 |梯度相关|<0.30 且 |亮度相关|<0.30",
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()
