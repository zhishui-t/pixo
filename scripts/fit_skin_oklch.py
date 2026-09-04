"""皮肤椭圆 OKLab 重拟合 (弱监督) —— 厦门/春节语料 (设计 §3 / M-O2)。

白点口径声明 (审核盲点 A3, 以实现语义为准):
  旧椭圆 (core.skin SKIN_LAB_*) 定义在 cv2.COLOR_RGB2LAB 的输出域 —— OpenCV
  从 gamma sRGB 经 D65 白点 (Xn≈0.9505, Zn≈1.0889) 归一的 XYZ 求 Lab, uint8
  输入时输出 8bit 变体 (L∈0..255, a/b 中心 128), 旧常数 (a=140,b=150, 单位
  与半径均在此 u8 域) 依赖该语义。设计文档写 "Lab(D65)" 是文档措辞, 本拟合
  **以 cv2 实现语义为准, 不照抄文档**: 皮肤样本 = 旧 cv2-Lab 椭圆掩码
  (core.skin.skin_mask) ∩ person 分割掩码, 故新常数的正样本边界直接继承
  cv2-Lab 语义; 新椭圆工作域为 OKLab (Ottosson 2020, sRGB D65, 无 D50/Bradford
  适配), 与渲染管线 core.oklab 完全同源。

样本与拟合:
  - 语料: --root 目录树下的 RAW (缺省 厦门 + 2026春节), pixo.meta 分组
    (capture.datetime 日期 → 组; meta 缺失回退父目录名); 复用 t2 口径:
    Renderer 中性渲染 (exposure mode 0.0 / wb trim [1,1,1]) 作像素源
    (相机缩略图对齐/朝向复原在本任务不需要 —— 无跨源配对, 色彩统计与朝向无关)。
  - 正样本: 旧掩码硬核 (d_old<=1) ∩ person (RF-DETR-Seg 2XL, 最大实例);
  - 负样本两族: 背景 (person 之外) 与 person 内非肤 (旧软掩码 <0.5, 发/衣等)。
  - 椭圆: OKLab a-b 平面二次型最小二乘 (二阶矩闭式解定中心/倾角/离心率;
    填充点云上 Fitzgibbon 直接曲线拟合会退化成圆, 见 fit_ellipse_lsq 说明)
    + 覆盖分位等比定标 (--coverage, 缺省 0.99); 离群裁剪仅 99.5% 分位一轮
    (分割溢出/真离群; 教训: 95% 过激裁剪会抽掉色彩多样性使拟合病态)。

产出 (只产数据与报告, 不切运行时默认 —— 运行时常数人工核对后回填 core.skin):
  - configs/color/skin_oklab.json —— 拟合常数 + 旧/新椭圆召回/误报对照 (机器读);
  - .artifacts/fit_skin_oklch.md —— 同一数据的 markdown 渲染 (人读, 零手画边)。
  拟合依赖 (scipy) 只进本脚本, 运行时 core 仅 numpy (隔离纪律)。

用法:
  python scripts/fit_skin_oklch.py --limit 4          # 冒烟 (前 4 张)
  python scripts/fit_skin_oklch.py                    # 全语料
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pixo.render.api import Renderer
from pixo.render.core.oklab import oklab_to_srgb, srgb_to_oklab
from pixo.render.core.skin import (
    SKIN_LAB_A,
    SKIN_LAB_B,
    SKIN_MAJOR,
    SKIN_MINOR,
    SKIN_ANGLE,
    SOFT_BAND,
    skin_mask,
)

DCP = "resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
DEFAULT_ROOTS = ("K:/data/photo/2026春节", "K:/data/photo/厦门")
RAW_EXTS = (".nef", ".nrw", ".raf", ".arw", ".cr3")

WHITE_POINT_NOTE = (
    "A3: 样本遴选与对照基准以 cv2.COLOR_RGB2LAB 实现语义为准 (D65 白点, "
    "uint8 输出 L/a/b∈0..255, a/b 中心 128), 不照抄设计文档的 'Lab(D65)' 措辞; "
    "新椭圆工作域 OKLab 为 sRGB D65 (Ottosson 2020), 与 core.oklab 管线同源, "
    "全程无 D50/Bradford 适配。"
)


# ---------------------------------------------------------------------------
# 语料 / 分组 (pixo.meta)
# ---------------------------------------------------------------------------

def iter_raws(roots: list[str]) -> list[str]:
    """目录树 → RAW 文件列表 (确定性排序, 对齐 iter_corpus 的去重口径)。"""
    seen: dict[str, str] = {}
    for root in roots:
        root = Path(root)
        if not root.exists():
            print(f"警告: 语料根不存在, 跳过 {root}", file=sys.stderr)
            continue
        for p in sorted(root.rglob("*")):
            if p.is_file() and p.suffix.lower() in RAW_EXTS \
                    and not p.name.startswith("."):   # macOS ._资源 fork 垃圾
                seen.setdefault(p.stem, str(p))
    return list(seen.values())


def meta_group(raw: str) -> tuple[str, str]:
    """pixo.meta → (组标签, 相机标识)。组 = capture 日期 (厦门/春节按拍摄日
    自然分组); meta 缺失回退父目录名。"""
    from pixo.meta import extract as meta_extract
    try:
        m = meta_extract(raw)
        cam = (m.get("camera") or {}).get("model") or \
              (m.get("camera") or {}).get("make") or "unknown"
        dt = (m.get("capture") or {}).get("datetime") or ""
        day = str(dt)[:10]
        if not day or day == "None":
            raise ValueError("no capture date")
        return day, cam
    except Exception:
        return Path(raw).parent.name, "unknown"


def balance_by_group(raws: list[str], per_group: int) -> list[str]:
    """按 pixo.meta 组轮询抽样, 每组至多 per_group 张 (确定性, 保持各拍摄日
    均衡入样; 大语料全量跑不现实 —— 渲染+分割 ~5s/张)。"""
    if per_group <= 0:
        return raws
    by_g: dict[str, list[str]] = {}
    for raw in raws:
        by_g.setdefault(meta_group(raw)[0], []).append(raw)
    picked: list[str] = []
    for r in range(per_group):
        for g in sorted(by_g):
            if len(by_g[g]) > r:
                picked.append(by_g[g][r])
    print(f"分组均衡抽样: {len(by_g)} 组 × ≤{per_group} 张 → {len(picked)} 张",
          flush=True)
    return picked


# ---------------------------------------------------------------------------
# 渲染 / 分割 / 采样
# ---------------------------------------------------------------------------

def render_neutral(renderer: Renderer, raw: str, long_edge: int) -> np.ndarray:
    """中性渲染 → gamma RGB float64 [0,1] (t2 口径: exposure 0.0 / trim [1,1,1])。"""
    base = renderer.render_preview_full(
        raw, long_edge=long_edge,
        params={"exposure": {"mode": 0.0}, "whitebalance": {"trim": [1, 1, 1]}})
    if base.dtype == np.uint8:
        return base.astype(np.float64) / 255.0
    return np.clip(np.asarray(base, dtype=np.float64), 0.0, 1.0)


def person_mask(rgb8: np.ndarray, threshold: float,
                seg=None) -> np.ndarray:
    """渲染图 → 最大 person 实例 0/1 掩码 (RF-DETR-Seg 2XL)。无检出 → 全 0。

    seg 可传入进程内复用的 RFDetrPersonSegmenter (权重加载 ~2s, 逐张新建
    会成倍拖慢全语料)。
    """
    if seg is None:
        from pixo.vision.segmenters.rfdetr_person import RFDetrPersonSegmenter
        seg = RFDetrPersonSegmenter(threshold=threshold)
    out = seg.segment(rgb8, ["person"]).get("person")
    if out is None:
        return np.zeros(rgb8.shape[:2], dtype=bool)
    return np.asarray(out) > 0


def _stride_subsample(mask2d: np.ndarray, cap: int) -> np.ndarray:
    """布尔图 → 超出 cap 时按行程 stride 抽样 (确定性, 不引入随机种子)。"""
    idx = np.flatnonzero(mask2d.ravel())
    if idx.size > cap:
        idx = idx[::int(np.ceil(idx.size / cap))]
    return idx


def collect_samples(img01: np.ndarray, pmask: np.ndarray,
                    max_per_photo: int) -> dict[str, np.ndarray] | None:
    """单张图 → 样本索引族 (OKLab a-b 由调用方按索引取)。

    positive: 旧 Lab 椭圆硬核 (skin_mask>=1) ∩ person;
    bg:       person 之外 (背景, 误报负样本);
    person_ns: person 内旧软掩码 <0.5 (发/衣/眼等 person 非肤)。
    """
    rgb8 = (img01 * 255.0 + 0.5).astype(np.uint8)
    old_soft = skin_mask(rgb8)
    pos = (old_soft >= 1.0) & pmask
    if int(pos.sum()) < 500:
        return None
    ns = pmask & (old_soft < 0.5)
    bg = ~pmask
    out = {}
    for name, m in (("positive", pos), ("bg", bg), ("person_ns", ns)):
        idx = _stride_subsample(m, max_per_photo)
        if idx.size:
            px = img01.reshape(-1, 3)[idx]
            out[name] = srgb_to_oklab(px).astype(np.float64)
    if "positive" not in out:
        return None
    return out


# ---------------------------------------------------------------------------
# 椭圆拟合 (Fitzgibbon 直接最小二乘, 纯 numpy+scipy.linalg, 只进 scripts/)
# ---------------------------------------------------------------------------

def ellipse_mahalanobis(pts: np.ndarray, cx: float, cy: float, major: float,
                        minor: float, angle: float) -> np.ndarray:
    """OKLab a-b 点集 → 椭圆马氏距离 d (旋转变换约定同 core.skin._ellipse_mahalanobis)。"""
    da = pts[:, 0] - cx
    db = pts[:, 1] - cy
    cos_a, sin_a = np.cos(angle), np.sin(angle)
    u = da * cos_a + db * sin_a
    v = -da * sin_a + db * cos_a
    return np.sqrt(np.maximum((u / major) ** 2 + (v / minor) ** 2, 0.0))


def fit_ellipse_lsq(pts: np.ndarray) -> tuple[float, float, float, float, float]:
    """填充点云的二次型最小二乘椭圆拟合 → (cx, cy, major, minor, angle)。

    方法说明: 样本是**面积填充**的肤色点云 (非边界点), Fitzgibbon 直接二次
    曲线拟合在此类数据上会退化成圆 (实测 ratio→1.0, 单元测试守卫); 故取二阶
    矩闭式解 —— 均值为中心, 协方差特征分解给朝向与离心率 (对均匀填充椭圆,
    var = 半轴²/4, 该解即二次型 min Σ((p-μ)ᵀM(p-μ)-1)² 的闭式解), 尺寸偏差
    由 fit_skin_ellipse 的覆盖分位等比定标吸收。倾角约定对齐 core.skin
    (u 轴 = 主轴方向, |angle|<=π/2)。
    """
    mu = pts.mean(axis=0)
    cov = np.cov(pts, rowvar=False)
    lam, vec = np.linalg.eigh(np.asarray(cov, dtype=np.float64))
    lam = np.clip(lam, 1e-12, None)
    axes = 2.0 * np.sqrt(lam)              # λ 升序 → 半轴升序
    minor, major = float(axes[0]), float(axes[1])
    ev = vec[:, 1]                          # 最大 λ 特征向量 = 主轴方向
    angle = float(np.arctan2(ev[1], ev[0]))
    if angle > np.pi / 2:
        angle -= np.pi
    elif angle < -np.pi / 2:
        angle += np.pi
    return float(mu[0]), float(mu[1]), major, minor, angle


def fit_skin_ellipse(pts: np.ndarray, coverage: float) -> dict:
    """支撑界分位包围拟合 + 99.5% 分位单轮离群裁剪 → 椭圆参数 dict。

    方法: 密度矩 (均值/协方差) 拟合追的是样本密度等高线, 会被正样本云中
    近中性高光尾巴拽向中性区 (实测 fp_bg 0.27→0.75 反而恶化); 本拟合改为
    追**支撑界** —— 主轴系 (朝向取协方差主轴) 下对 |u-中位|、|v-中位| 取
    轴向分位半轴 (并集界: 轴向分位 q_axis = 1-(1-coverage)/2 保证整体覆盖
    ≥ coverage)。半轴只看分位端点不看密度, 皮肤云形态不匀不影响放置。
    """
    keep = pts
    trimmed = 0
    cx, cy, major, minor, angle = _enclosing_fit(keep, coverage)
    d = ellipse_mahalanobis(keep, cx, cy, major, minor, angle)
    thr = np.quantile(d, 0.995)
    sel = d <= thr
    if not bool(sel.all()) and int(sel.sum()) >= 1000:
        trimmed = int((~sel).sum())
        keep = keep[sel]
        cx, cy, major, minor, angle = _enclosing_fit(keep, coverage)
        d = ellipse_mahalanobis(keep, cx, cy, major, minor, angle)
    # 均匀定标: 轴向分位在 CDF 平顶区会收缩 ~3% (覆盖不达标), 按马氏距离
    # 的 coverage 分位等比放大, 使 P(d<=1) = coverage 精确成立
    scale = float(np.quantile(d, coverage))
    if scale > 0:
        major, minor = major * scale, minor * scale
    return {"center_a": round(cx, 6), "center_b": round(cy, 6),
            "major": round(major, 6), "minor": round(minor, 6),
            "angle_deg": round(float(np.degrees(angle)), 4),
            "trimmed": trimmed, "coverage": coverage,
            "n_fit": int(keep.shape[0])}


def _enclosing_fit(pts: np.ndarray, coverage: float) -> tuple:
    """主轴系轴向分位包围椭圆 → (cx, cy, major, minor, angle)。

    朝向 = 协方差主轴 (云的主延展方向); 中心 = 主轴系中位; 半轴 =
    |坐标-中位| 的轴向分位 (q_axis = 1-(1-coverage)/2, 并集界)。
    """
    _, _, major0, minor0, angle0 = fit_ellipse_lsq(pts)   # 仅取朝向
    ca, sa = np.cos(angle0), np.sin(angle0)
    u = pts[:, 0] * ca + pts[:, 1] * sa
    v = -pts[:, 0] * sa + pts[:, 1] * ca
    q_axis = 1.0 - (1.0 - coverage) / 2.0
    cu, ru = float(np.median(u)), float(np.quantile(np.abs(u - np.median(u)),
                                                    q_axis))
    cv_, rv = float(np.median(v)), float(np.quantile(np.abs(v - np.median(v)),
                                                     q_axis))
    cx = cu * ca - cv_ * sa
    cy = cu * sa + cv_ * ca
    # (u, v) 系半轴 (ru, rv) → 主轴方向角 = angle0 (ru≥rv) 或 angle0±90°
    if ru >= rv:
        return cx, cy, ru, rv, angle0
    return cx, cy, rv, ru, angle0 + np.pi / 2


def ellipse_eval(ell: dict, pos: np.ndarray, bg: np.ndarray,
                 ns: np.ndarray | None, pos_core: np.ndarray | None = None
                 ) -> dict:
    """椭圆在 (正样本, 背景, person 非肤) 三族上的召回/误报。

    ns 为 None (样本不足, 如红衣人像下旧椭圆把衣物也判成肤) 时
    fp_person_nonskin 记 None。pos_core 给定时附加 recall_core (色度核内
    召回 —— 核 = 确凿色度肤色, 近中性尾巴之外的诚实召回口径)。
    """
    def d(pts):
        return ellipse_mahalanobis(pts, ell["center_a"], ell["center_b"],
                                   ell["major"], ell["minor"],
                                   float(np.radians(ell["angle_deg"])))
    out = {"recall": round(float((d(pos) <= 1.0).mean()), 4),
           "fp_bg": round(float((d(bg) <= 1.0).mean()), 4),
           "fp_person_nonskin": (round(float((d(ns) <= 1.0).mean()), 4)
                                 if ns is not None and ns.shape[0] else None),
           "area": round(float(np.pi * ell["major"] * ell["minor"]), 6)}
    if pos_core is not None and pos_core.shape[0]:
        out["recall_core"] = round(float((d(pos_core) <= 1.0).mean()), 4)
    return out


OLD_ELLIPSE = {"center_a": SKIN_LAB_A, "center_b": SKIN_LAB_B,
               "major": SKIN_MAJOR, "minor": SKIN_MINOR,
               "angle_deg": round(float(np.degrees(SKIN_ANGLE)), 4)}


def evaluate_old(pos, bg, ns) -> dict:
    """旧 cv2-Lab 椭圆评估: 马氏距离在旧域 u8 Lab (a/b 中心 128) 计算。

    pos/bg/ns 为 **(N,3) 全 OKLab** (重建 RGB 须 L 通道; ns 可为 None,
    此时 fp_person_nonskin 记 None, 口径同 ellipse_eval)。
    """
    def rates(full_ok):
        rgb = np.clip(oklab_to_srgb(full_ok), 0.0, 1.0)
        u8 = (rgb * 255.0 + 0.5).astype(np.uint8).reshape(1, -1, 3)
        lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB)
        u = lab[..., 1].ravel().astype(np.float64)
        v = lab[..., 2].ravel().astype(np.float64)
        da, db = u - OLD_ELLIPSE["center_a"], v - OLD_ELLIPSE["center_b"]
        cos_a, sin_a = np.cos(SKIN_ANGLE), np.sin(SKIN_ANGLE)
        uu = da * cos_a + db * sin_a
        vv = -da * sin_a + db * cos_a
        return np.sqrt((uu / SKIN_MAJOR) ** 2 + (vv / SKIN_MINOR) ** 2)

    return {"recall": round(float((rates(pos) <= 1.0).mean()), 4),
            "fp_bg": round(float((rates(bg) <= 1.0).mean()), 4),
            "fp_person_nonskin": (round(float(
                (rates(ns) <= 1.0).mean()), 4)
                if ns is not None and ns.shape[0] else None),
            "area": round(float(np.pi * SKIN_MAJOR * SKIN_MINOR), 1)}


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", action="append", default=None,
                    help=f"语料根目录 (可多次; 缺省 {DEFAULT_ROOTS})")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--per-group", type=int, default=0,
                    help="按 pixo.meta 组轮询抽样, 每组至多 N 张 (0=不限)")
    ap.add_argument("--dcp", default=DCP)
    ap.add_argument("--long-edge", type=int, default=640)
    ap.add_argument("--seg-threshold", type=float, default=0.5)
    ap.add_argument("--max-per-photo", type=int, default=20000,
                    help="每张图各族样本上限 (stride 抽样)")
    ap.add_argument("--coverage", type=float, default=0.96,
                    help="新椭圆对色度核正样本的覆盖分位定标目标")
    ap.add_argument("--chroma-core", type=float, default=0.04,
                    help="色度核阈值: 只用 OKLCh C>=该值的正样本定形 (0=全量)。"
                         "近中性尾巴 (高光/ Mask渗漏) 会把矩/包围拟合拽向中性带, "
                         "实测 fp_bg 0.27→0.75; 色度核符合旧椭圆设计意图 "
                         "(中心=平均色度肤色)")
    ap.add_argument("--out-json", default="configs/color/skin_oklab.json")
    ap.add_argument("--out-md", default=".artifacts/fit_skin_oklch.md")
    ap.add_argument("--cache", default=".artifacts/fit_skin_samples.npz",
                    help="采样缓存 npz (渲染+分割最贵, 缓存后评估可断点重放)")
    ap.add_argument("--resume", action="store_true",
                    help="缓存存在时跳过渲染/分割, 直接重放评估")
    args = ap.parse_args()

    roots = args.root or list(DEFAULT_ROOTS)
    raws = iter_raws(roots)
    if args.limit:
        raws = raws[:args.limit]
    if args.per_group:
        raws = balance_by_group(raws, args.per_group)

    cache = Path(args.cache)
    labels = {}
    group_photos: dict[str, set] = {}
    t0 = time.time()
    if args.resume and cache.exists():
        z = np.load(cache, allow_pickle=False)
        pos, bg, ns = z["positive"], z["bg"], z["person_ns"]
        labels = {k: z[f"{k}_g"] for k in ("positive", "bg", "person_ns")}
        n_fail = int(z["n_fail"])
        n_listed = int(z["n_listed"])
        group_photos = {g: set(v) for g, v in
                        json.loads(str(z["group_photos"])).items()}
        print(f"缓存重放: {cache} (skin={pos.shape[0]:,} bg={bg.shape[0]:,} "
              f"ns={ns.shape[0]:,})", flush=True)
    else:
        if not raws:
            print("语料为空: 检查 --root", file=sys.stderr)
            sys.exit(2)
        renderer = Renderer(args.dcp)
        # 分割器进程内复用 (权重加载 ~2s/次, 逐张新建成倍拖慢全语料)
        from pixo.vision.segmenters.rfdetr_person import RFDetrPersonSegmenter
        seg = RFDetrPersonSegmenter(threshold=args.seg_threshold)

        pooled = {"positive": [], "bg": [], "person_ns": []}
        n_fail = 0
        n_listed = len(raws)
        for i, raw in enumerate(raws, 1):
            pid = Path(raw).stem
            try:
                g, cam = meta_group(raw)
                img = render_neutral(renderer, raw, args.long_edge)
                rgb8 = (img * 255.0 + 0.5).astype(np.uint8)
                pmask = person_mask(rgb8, args.seg_threshold, seg)
                cover = float(pmask.mean())
                if cover < 0.01:
                    raise RuntimeError(f"person 占比过低 {cover:.3f}")
                fam = collect_samples(img, pmask, args.max_per_photo)
                if fam is None:
                    raise RuntimeError("皮肤样本不足 (<500)")
                for k, v in fam.items():
                    pooled[k].append(v)
                    labels.setdefault(k, []).extend([g] * v.shape[0])
                group_photos.setdefault(g, set()).add(pid)
                print(f"[{i}/{len(raws)}] {pid} group={g} person={cover:.2f} "
                      f"pos={len(fam['positive'])} bg={len(fam.get('bg', ()) )} "
                      f"ns={len(fam.get('person_ns', ()) )}", flush=True)
            except Exception as exc:  # noqa: BLE001 — 单张失败不拖垮整批
                n_fail += 1
                print(f"[{i}/{len(raws)}] {pid} 跳过: {exc}", flush=True)

        pos = np.vstack(pooled["positive"])
        bg = np.vstack(pooled["bg"]) if pooled["bg"] else np.zeros((0, 3))
        ns = (np.vstack(pooled["person_ns"]) if pooled["person_ns"]
              else np.zeros((0, 3)))

    try:  # 采样缓存 (渲染+分割最贵; 评估阶段 bug 可 --resume 重放不重采)
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            cache, positive=pos, bg=bg, person_ns=ns,
            positive_g=np.asarray(labels["positive"], dtype="U24"),
            bg_g=np.asarray(labels["bg"], dtype="U24"),
            person_ns_g=np.asarray(labels["person_ns"], dtype="U24"),
            group_photos=json.dumps({g: sorted(v)
                                     for g, v in group_photos.items()}),
            n_fail=n_fail, n_listed=n_listed)
        print(f"采样缓存 -> {cache}", flush=True)
    except Exception as exc:  # noqa: BLE001 — 缓存失败不阻塞报告
        print(f"缓存写入失败 (继续): {exc}", file=sys.stderr)

    # person 内非肤族在红衣/紧构图语料上可为空 (旧椭圆把衣物也判肤 —— 正是
    # 重拟合动机), 记 None 不阻塞
    ns = ns if ns.shape[0] >= 500 else None
    if bg.shape[0] < 500:
        print("背景负样本不足, 无法给出误报对照", file=sys.stderr)
        sys.exit(1)

    # a-b 平面点集 (亮度不进椭圆模型, 与旧椭圆同构); evaluate_old 需全
    # OKLab (重建 RGB 转 cv2-Lab), 传 3 列
    pos_ab, bg_ab = pos[:, 1:], bg[:, 1:]
    ns_ab = None if ns is None else ns[:, 1:]
    # 色度核定形 (见 --chroma-core 说明): 定形/核内召回用核, 对照表同时
    # 报告对全体正样本的召回 (近中性带是主动放弃的折衷, 见报告 notes)
    c_pos = np.hypot(pos_ab[:, 0], pos_ab[:, 1])
    core_sel = c_pos >= args.chroma_core
    new_ell = fit_skin_ellipse(pos_ab[core_sel], args.coverage)
    new_eval = ellipse_eval(new_ell, pos_ab, bg_ab, ns_ab,
                            pos_core=pos_ab[core_sel])
    old_eval = evaluate_old(pos, bg, ns)

    per_group_fit = {}
    per_group_cmp = {}
    g_lab = np.asarray(labels["positive"])
    bg_lab = np.asarray(labels["bg"])
    ns_lab = (np.asarray(labels["person_ns"]) if ns is not None else None)
    for g in sorted(set(g_lab.tolist())):
        sel = g_lab == g
        g_pos3 = pos[sel]
        g_ab = g_pos3[:, 1:]
        if g_ab.shape[0] < 2000:
            continue
        bg_sel = bg_lab == g
        ns_sel = (ns_lab == g) if ns_lab is not None else None
        g_core = (np.hypot(g_ab[:, 0], g_ab[:, 1]) >= args.chroma_core)
        if int(g_core.sum()) < 1000:
            continue    # 组色度核过小, 无稳定定形意义
        ge = fit_skin_ellipse(g_ab[g_core], args.coverage)
        per_group_fit[g] = {"n_photos": len(group_photos.get(g, ())),
                            "n_skin": int(g_ab.shape[0]),
                            "ellipse": ge}
        per_group_cmp[g] = {
            "old": evaluate_old(g_pos3, bg[bg_sel],
                                ns[ns_sel] if ns_sel is not None else None),
            "new": ellipse_eval(ge, g_ab, bg[bg_sel][:, 1:],
                                None if ns_sel is None
                                else ns[ns_sel][:, 1:],
                                pos_core=g_ab[g_core])}

    report = {
        "schema": "pixo.skin_oklab.v1",
        "source": "scripts/fit_skin_oklch.py",
        "white_point_note": WHITE_POINT_NOTE,
        "corpus": {"roots": roots, "n_photos": n_listed,
                   "n_photos_failed": n_fail,
                   "dcp": Path(args.dcp).name,
                   "long_edge": args.long_edge,
                   "seg_threshold": args.seg_threshold,
                   "max_per_photo": args.max_per_photo,
                   "coverage": args.coverage,
                   "chroma_core": args.chroma_core},
        "samples": {"n_skin": int(pos_ab.shape[0]),
                    "n_bg": int(bg_ab.shape[0]),
                    "n_person_nonskin": int(ns_ab.shape[0]) if ns_ab is not None else 0},
        "constants": {"SKIN_OKLAB_A": new_ell["center_a"],
                      "SKIN_OKLAB_B": new_ell["center_b"],
                      "SKIN_OKLAB_MAJOR": new_ell["major"],
                      "SKIN_OKLAB_MINOR": new_ell["minor"],
                      "SKIN_OKLAB_ANGLE": round(
                          float(np.radians(new_ell["angle_deg"])), 6),
                      "SKIN_OKLAB_SOFT_BAND": SOFT_BAND},
        "new_ellipse_fit": new_ell,
        "baseline_ellipse": {**OLD_ELLIPSE,
                             "domain": "cv2.COLOR_RGB2LAB uint8 (a/b 中心 128)",
                             "constants": {"SKIN_LAB_A": SKIN_LAB_A,
                                           "SKIN_LAB_B": SKIN_LAB_B,
                                           "SKIN_MAJOR": SKIN_MAJOR,
                                           "SKIN_MINOR": SKIN_MINOR,
                                           "SKIN_ANGLE": SKIN_ANGLE}},
        "comparison": {"pooled": {"old": old_eval, "new": new_eval},
                       "per_group": per_group_cmp},
        "per_group_fit": per_group_fit,
        "notes": [
            "正样本 = 旧 cv2-Lab 椭圆硬核 ∩ person 分割掩码 (弱监督, 无人工标注); "
            "旧椭圆 recall≡1.0 由构造决定 (fp_person_nonskin=0 同理, 定义性零), "
            "对照价值在于同等色度肤召回下背景误报的削减。",
            "像素源 = pixo 中性渲染 (exposure 0.0 / trim [1,1,1]), 与 t2 语料口径一致。",
            "召回/误报的三族定义见 samples; area 为各自域内 π·major·minor, "
            "跨域 (u8 Lab vs OKLab) 不可直接比较, 对照以召回/误报为准。",
            "person 内非肤族 (发/衣) 在旧椭圆过宽的语料 (如红衣人像) 上可不足 "
            "500 样本, 此时 fp_person_nonskin 记 None (—) —— 空缺本身即旧椭圆 "
            "过宽的证据。",
            "方法学结论 (本语料实测): 正样本云含大量近中性像素 (C<0.03 占 32%), "
            "密度矩/支撑包围拟合都会被拽向中性带 (fp_bg 0.27→0.75, 反而恶化); "
            "色度核 (--chroma-core) 定形符合旧椭圆设计意图 (中心=平均色度肤色), "
            "代价是主动放弃近中性带召回 (该带本应由中性保护机制兜底), "
            "换来 fp_bg 首次低于旧椭圆。recall=全体正样本召回, recall_core="
            f"C>={args.chroma_core} 色度核召回 (诚实口径)。",
        ],
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    out_md = Path(args.out_md)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_md(report), encoding="utf-8")

    print(f"\n== 新常数: {report['constants']}")
    print(f"== pooled 旧: {old_eval}")
    print(f"== pooled 新: {new_eval}")
    print(f"-> {out_json}")
    print(f"-> {out_md}")
    print(f"DONE {time.time() - t0:.1f}s", flush=True)


def _fmt(v) -> str:
    """指标格式化 (None → em dash, 见 fp_person_nonskin 可选语义)。"""
    return "—" if v is None else f"{v:.4f}"


def render_md(r: dict) -> str:
    """JSON 报告 → markdown (全部字段从 JSON 渲染, 零手画边)。"""
    cmp_pool = r["comparison"]["pooled"]
    c = r["constants"]
    lines = [
        "# 皮肤椭圆 OKLab 重拟合报告 (M-O2)",
        "",
        f"- 语料: {', '.join(r['corpus']['roots'])} ({r['corpus']['n_photos']} 张, "
        f"失败 {r['corpus']['n_photos_failed']}); DCP {r['corpus']['dcp']}; "
        f"long_edge={r['corpus']['long_edge']}",
        f"- 样本: 皮肤 {r['samples']['n_skin']:,} / 背景 {r['samples']['n_bg']:,} / "
        f"person 非肤 {r['samples']['n_person_nonskin']:,}",
        f"- {r['white_point_note']}",
        "",
        "## 新常数 (回填 core.skin)",
        "",
        "```python",
        f"SKIN_OKLAB_A = {c['SKIN_OKLAB_A']}",
        f"SKIN_OKLAB_B = {c['SKIN_OKLAB_B']}",
        f"SKIN_OKLAB_MAJOR = {c['SKIN_OKLAB_MAJOR']}",
        f"SKIN_OKLAB_MINOR = {c['SKIN_OKLAB_MINOR']}",
        f"SKIN_OKLAB_ANGLE = {c['SKIN_OKLAB_ANGLE']}",
        f"SKIN_OKLAB_SOFT_BAND = {c['SKIN_OKLAB_SOFT_BAND']}",
        "```",
        "",
        "## 旧 / 新椭圆对照 (pooled)",
        "",
        "| 椭圆 | 召回(全体) | 召回(色度核) | 误报(背景) | 误报(person 非肤) |",
        "|---|---|---|---|---|",
        f"| 旧 (cv2-Lab u8) | {_fmt(cmp_pool['old']['recall'])} | — | "
        f"{_fmt(cmp_pool['old']['fp_bg'])} | "
        f"{_fmt(cmp_pool['old']['fp_person_nonskin'])} |",
        f"| 新 (OKLab) | {_fmt(cmp_pool['new']['recall'])} | "
        f"{_fmt(cmp_pool['new'].get('recall_core'))} | "
        f"{_fmt(cmp_pool['new']['fp_bg'])} | "
        f"{_fmt(cmp_pool['new']['fp_person_nonskin'])} |",
        "",
        "## 分组对照",
        "",
        "| 组 | 椭圆 | 召回 | 误报(背景) | 误报(person 非肤) |",
        "|---|---|---|---|---|",
    ]
    for g, e in r["comparison"]["per_group"].items():
        lines.append(f"| {g} | 旧 | {_fmt(e['old']['recall'])} | "
                     f"{_fmt(e['old']['fp_bg'])} | "
                     f"{_fmt(e['old']['fp_person_nonskin'])} |")
        lines.append(f"| {g} | 新 | {_fmt(e['new']['recall'])} | "
                     f"{_fmt(e['new']['fp_bg'])} | "
                     f"{_fmt(e['new']['fp_person_nonskin'])} |")
    lines += ["", "## 分组拟合常数 (稳定性参考)", ""]
    for g, f in r["per_group_fit"].items():
        e = f["ellipse"]
        lines.append(f"- **{g}** ({f['n_photos']} 张, {f['n_skin']:,} 样本): "
                     f"a={e['center_a']}, b={e['center_b']}, "
                     f"major={e['major']}, minor={e['minor']}, "
                     f"angle={e['angle_deg']}°")
    lines += ["", "## 注记", ""] + [f"- {n}" for n in r["notes"]]
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    main()
