"""fit_camera_profile —— 从语料 (NEF + 目标渲染) 拟合一条相机基准渲染 DCP + preset。

目标 (2026-08, 3428 张图库需要一条夯实的基准):
  把散落的白平衡暖度/影调曲线/基线曝光/饱和度标定, 收拢为:
    1. 一条二进制 DCP (dcp.write_dcp): ProfileToneCurve + BaselineExposureOffset
       + 继承 ColorMatrix/CameraCalibration/ForwardMatrix;
    2. 一个 preset JSON: 引擎专属参数 (exposure baseline / 暖度标定常数 /
       trim 增益 / 饱和度), 由 pipeline_from_config 直接消费。

拟合流程 (目标 = 机内预览 extract_thumb 或 LR 导出), **staged 固定顺序**:
  a. 扫描图库 → 按 WB 蓝系数分层选代表性样本 (可复现, 结果缓存);
  b. 每张: 解码 → 裁到有效画面 → 曝光(baseline) → 白平衡 (as_shot, 无暖度)
     → 线性 RGB; 目标图线性化;
  c. BaselineExposureOffset: 全体中位亮度比;
  d. 影调曲线: 全体合并亮度 CDF 匹配 (线性 Y → 目标 gamma Y), 肩部锚定 (1,1):
     取最后一个 x≤0.95 的可靠点, 其后 smoothstep 平滑单调外推收敛到 (1.0,1.0)
     (maximum.accumulate 保单调; 写 DCP 前断言 y(1.0)==1.0);
  e. 固定 trim: **仅用中性样本 (wb_B ≤ 1.79, 即暖度键 s=0 的照片)**,
     对角 LSQ (线性域) → 全体中位 (或 3×3 LSQ, --trim-mode full);
  f. 暖度标定: **b0/b1 硬冻结 1.79/2.287 (0376/5236 双锚点, 删除网格搜索)**;
     用 trim 固定后的**剩余暖样本** (wb_B > 1.79) 对归一化键
     s = clip((wb_B−b0)/(b1−b0), 0, 1) 回归残余对角增益斜率
     gain = [1, 1+g_slope·s, 1−b_slope·s]; 斜率带界 (WARMTH_SLOPE_BOUNDS), 越界钳位;
  g. HSM 品红带拟合 (T5, 方案 b; high#1 应用域): 品红带像素 **在线性 ProPhoto
     应用域** (对 linear_m8 先转线性 ProPhoto, HSV 中 hue 235~310°、S≥0.05、
     V≥0.6, V 按 encoding=1 做 sRGB gamma 编码 —— 与引擎 apply_hue_sat_map
     查表同域同坐标) 的 ours 与目标 Lab C* 中位比 → sat_scale (钳位 [0.08,1.0],
     无样本写恒等表); 表随 DCP 落盘 (0xC726/0xC725/0xC7A4=1) **仅 LR 目标**
     (low#4: preview 目标 huesat.enabled=false → 不拟合也不写 HSM 表), 仅 LR
     基准 preset 开启 huesat;
  h. 饱和度: 扫 sat 使 HSV S 与目标一致;
  i. 写 DCP + preset (覆盖需 --force); --validate 时渲染留出集并输出**四口径**
     统计 (全帧中位 a/b/S、中性区 C*<12、分亮度段 L 四段、高光区 L>160 的 |Δ| 中位),
     报告 JSON 落盘 rawlab/out/profile_fit/validation_<name>.json。

用法:
  python rawlab/tools/fit_camera_profile.py \
      --raw-dirs K:\\data\\photo\\0711 K:\\data\\photo\\2026春节 K:\\data\\photo\\厦门 \
      --target preview --n 40 --n-validate 60 \
      --out-dcp rawlab\\profiles\\Nikon Z 5 2 RawLab Preview Baseline.dcp \
      --out-preset rawlab\\presets\\preview_baseline.json --force
  LR 目标: --target lr --lr-dir <含 <raw名>.jpg 的目录> (lr 目录只含导出图)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
import rawpy

from rawlab.dcp import DcpProfile, load_dcp, write_dcp
from rawlab.engine import stages as _  # noqa: F401  触发注册
from rawlab.engine.color import linear_srgb_to_linear_prophoto
from rawlab.engine.core import StageContext, STAGE_REGISTRY, DOMAIN_LINEAR_CAM
from rawlab.engine.decode import decode_raw
from rawlab.engine.huesat import _rgb_to_hsv, _srgb_encode_v, make_hue_sat_map
from rawlab.engine.stages.whitebalance import (
    WARMTH_B0_FROZEN, WARMTH_B1_FROZEN, WARMTH_SLOPE_BOUNDS)

DEFAULT_SRC_DCP = (r"C:\ProgramData\Adobe\CameraRaw\CameraProfiles\Camera"
                   r"\Nikon Z 5 2\Nikon Z 5 2 Camera Standard v2.dcp")
CROP = {"left": 8, "top": 4, "width": 6048, "height": 4032}

# 暖度模型 (T3 方案 A, 见 whitebalance.py): 锚点硬冻结, 禁止网格搜索
WARMTH_B0 = WARMTH_B0_FROZEN      # 1.79 (5236, 零暖)
WARMTH_B1 = WARMTH_B1_FROZEN      # 2.287 (0376, 全量暖)
NEUTRAL_WB_B_MAX = WARMTH_B0      # trim 用中性样本上界 (s=0)

# 四口径验证阈值 (03-specification.md §3, Preview):
#   full     全帧中位    |Δa|≤3 / |Δb|≤4 / |ΔS|≤12 / |Δp50|≤20
#   neutral  中性区 C*<12 |Δa|≤3 / |Δb|≤3
#   band     分亮度段四段 |Δa|≤3 / |Δb|≤4 (每段)
#   highlight 高光区 L>160 |Δa|≤3 / |Δb|≤4
ACCEPT_THRESHOLDS = {"da": 3.0, "db": 4.0, "dS": 12.0, "dp50": 20.0}
NEUTRAL_ACCEPT = {"da": 3.0, "db": 3.0}
BAND_ACCEPT = {"da": 3.0, "db": 4.0}
HIGHLIGHT_ACCEPT = {"da": 3.0, "db": 4.0}
# medium#3: 四口径判定全部纳入 pass (不再是仅 full)
CALIBER_THRESHOLDS = {
    "full": dict(ACCEPT_THRESHOLDS),
    "neutral": dict(NEUTRAL_ACCEPT),
    "band": dict(BAND_ACCEPT),
    "highlight": dict(HIGHLIGHT_ACCEPT),
}

# 分亮度段 (03-specification.md §2.2)
LUM_BANDS = [(0.0, 50.0), (50.0, 100.0), (100.0, 160.0), (160.0, 256.0)]

# HSM 品红带拟合常量 (03-specification.md §2.2; 实测 235~300°, 留边 310°)
# high#1 (应用域): 掩码在**线性 ProPhoto (D50)** 域计算 —— 与引擎
# apply_hue_sat_map 查表同域同坐标 (hue/S 用 ProPhoto HSV, V 轴按 encoding=1
# 做 sRGB gamma 编码后 ≥ 0.6), 见 magenta_band_mask。修复前在 gamma sRGB
# (apply_curve 后) 域取掩码, 与引擎实际调制像素集错位 (实测 5236 高光像素
# 两域 hue 差中位 13.2°, S 中位 0.05→0.031)。
MAGENTA_HUE_RANGE = (235.0, 310.0)   # 品红带 (夜景灯光, 紫-品红)
HSM_SAT_MIN = 0.05                   # S 阈值 (近中性保护区, 防误伤中性亮部)
HSM_VAL_MIN = 0.6                    # V 阈值 (encoding=1 时表坐标即感知 V, 中高光区)
HSM_SAT_SCALE_CLAMP = (0.08, 1.0)    # sat_scale 钳位范围
HSM_SAT_SCALE_DEFAULT = 0.3          # 无样本/退化时的默认值
HSM_MIN_PIXELS = 500                 # 品红样本最少像素数 (全语料合计), 不足视为无品红
HSM_DIMS = [90, 16, 16]              # 表维度 (Adobe Camera 系列联合形态) + encoding=1

# trim 对角异常值告警界 (medium#1): 对角增益含亮度标量成分 (被影调曲线吸收),
# 以通道比 (R/G, B/G) 判定可信域, 越界即告警 (--validate 判定 fail)。
TRIM_RATIO_MIN = 0.5
TRIM_RATIO_MAX = 1.6

# T11: 锚点网格无达标组合时的回退常数 (双锚点全尺寸验证过, 见 BASELINE_REPORT)
ANCHOR_FALLBACK = {"trim": [1.0, 1.05, 0.9],
                   "r_slope": 0.05, "g_slope": 0.10, "b_slope": 0.20,
                   "sat": 0.20}

# medium#3 收敛: trim 拟合按亮度分段加权 (目标 Lab L), 中段权重提高。
# 影调曲线在中间调斜率最陡 → 线性域对角残余被曲线放大为中间调色偏
# (实测 band L[50,100) |Δa|=6.5 超规格)。分段增益用**段内中位比值**
# (t/o 中位, 对 JPEG 黑位噪声稳健), 段间按权重平均; 暗段 (L<50) 权重 0
# (预览黑位被压缩/有噪声, 比值不可靠), 中段 2.0, 中亮段 1.5, 高光段 0.5。
TRIM_LUMA_WEIGHTS = ((0.0, 50.0, 0.0), (50.0, 100.0, 2.0),
                     (100.0, 160.0, 1.5), (160.0, 256.0, 0.5))


def lum(x: np.ndarray) -> np.ndarray:
    return (0.2126 * x[..., 0] + 0.7152 * x[..., 1] + 0.0722 * x[..., 2])


def srgb_inv(x: np.ndarray) -> np.ndarray:
    x = np.clip(np.asarray(x, np.float32), 0.0, 1.0)
    return np.where(x <= 0.04045, x / 12.92,
                    ((x + 0.055) / 1.055) ** 2.4).astype(np.float32)


def labsat(x: np.ndarray):
    u8 = (np.clip(np.asarray(x, np.float32), 0.0, 1.0) * 255.0).astype(np.uint8)
    lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    hsv = cv2.cvtColor(u8, cv2.COLOR_RGB2HSV)
    return (float(np.median(lab[..., 1]) - 128.0),
            float(np.median(lab[..., 2]) - 128.0),
            float(hsv[..., 1].mean()))


# ---------------------------------------------------------------------------
# 语料扫描与选择
# ---------------------------------------------------------------------------

def scan_library(raw_dirs: list[str], cache_path: Path) -> list[dict]:
    """扫描全部 NEF: (path, wb, wb_B, raw_mean) — 结果缓存 JSON。

    缓存带目录覆盖元数据: 请求目录与缓存不一致 → 重新扫描 (否则多目录
    调用会命中旧单目录缓存, 丢失其他目录的照片)。
    """
    want = sorted({str(Path(d).resolve()) for d in raw_dirs})
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            rows = cached["rows"] if isinstance(cached, dict) else cached
            if (isinstance(cached, dict)
                    and sorted(cached.get("dirs", [])) == want):
                print(f"[scan] 命中缓存 {cache_path} ({len(rows)} 张)")
                return rows
            print(f"[scan] 缓存目录不符 (需 {len(want)} 个目录), 重新扫描")
        except Exception:
            pass
    rows = []
    files = []
    for d in raw_dirs:
        files += [str(p) for p in Path(d).rglob("*.NEF")]
    print(f"[scan] {len(files)} 张 NEF, 读取 WB/亮度元数据 ...")
    t0 = time.time()
    for i, f in enumerate(files):
        try:
            with rawpy.imread(f) as raw:
                wb = np.array(raw.camera_whitebalance[:3], dtype=np.float64)
                if wb[1] > 0:
                    wb = wb / wb[1]
                mean = float(np.mean(raw.raw_image_visible.astype(np.float64))
                             / max(float(raw.white_level), 1.0))
                rows.append({"path": f, "wb": list(np.round(wb, 4)),
                             "wb_b": round(float(wb[2]), 4),
                             "raw_mean": round(mean, 4)})
        except Exception:
            continue
        if (i + 1) % 500 == 0:
            print(f"  ... {i + 1}/{len(files)} ({time.time() - t0:.0f}s)")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"dirs": want, "rows": rows},
                                     ensure_ascii=False), encoding="utf-8")
    print(f"[scan] 完成 {len(rows)} 张, {time.time() - t0:.0f}s")
    return rows


def select_stratified(rows: list[dict], n: int, seed: int = 7) -> list[dict]:
    """按 wb_B 分层选取 n 张 (均匀覆盖色温范围)。

    medium#2: n>len(rows) 时 np.linspace(dtype=int) 会产生重复索引 → 先
    np.unique 去重, 不足 n 的部分从剩余样本**无放回**补齐 (确定性 rng);
    n≥len(rows) 时直接返回全部 (无放回上限)。
    """
    rng = np.random.default_rng(seed)
    order = sorted(rows, key=lambda r: r["wb_b"])
    if n >= len(order):
        return list(order)
    idx = np.unique(np.linspace(0, len(order) - 1, n, dtype=int))
    picked = [order[i] for i in idx]
    if len(picked) < n:
        rest = [r for r in order if r not in picked]
        take = rng.permutation(len(rest))[: n - len(picked)]
        picked += [rest[i] for i in take]
    return picked


def select_preview_rows(rows: list[dict], n: int,
                       warm_all: bool = False,
                       warm_b0: float = WARMTH_B0) -> list[dict]:
    """Preview 目标选片 (2026-08 稳定真值): warm_all=True 时把全部暖样本
    (wb_B > b0) 纳入拟合, 其余名额从冷/中性样本分层补齐 —— 修复暖尾真值
    稀疏导致的暖度回退 (全库 3423 张中暖尾 ~121 张, 等距分层只能抽到 ~2 张)。

    warm_all=False 保持旧行为 (select_stratified 等距分层)。确定性, 无随机。
    """
    if not warm_all:
        return select_stratified(rows, n)
    warm = sorted((r for r in rows if float(r["wb_b"]) > warm_b0),
                  key=lambda r: r["wb_b"])
    neutral = [r for r in rows if float(r["wb_b"]) <= warm_b0]
    # trim 必须由中性样本 (wb_B<=b0) 拟合; 即使 n 被暖尾占满, 也强制保留
    # 至多 20 张中性样本 (总样本数可略超 n, warm_all 语义优先)。
    n_neutral = max(int(n) - len(warm), min(20, len(neutral)))
    if n_neutral <= 0:
        return warm[: int(n)]
    picked = select_stratified(neutral, n_neutral)
    return sorted(picked + warm, key=lambda r: r["wb_b"])


def split_lr_holdout(rows: list[dict], n_neutral: int = 2, n_warm: int = 2,
                     seed: int = 11) -> tuple[list[dict], list[dict]]:
    """LR 语料留出集 (medium#4): 按 wb_B 分层留出 ~4 张 (中性 2 + 暖 2)
    不参与拟合。返回 (fit_rows, holdout); 确定性 (rng seed), 无放回。
    """
    neutral = sorted((r for r in rows if float(r["wb_b"]) <= WARMTH_B0),
                     key=lambda r: r["wb_b"])
    warm = sorted((r for r in rows if float(r["wb_b"]) > WARMTH_B0),
                  key=lambda r: r["wb_b"])
    rng = np.random.default_rng(seed)

    def take(rs: list[dict], k: int) -> list[dict]:
        if not rs or k <= 0:
            return []
        k = min(k, len(rs))
        return [rs[i] for i in rng.permutation(len(rs))[:k]]

    holdout = take(neutral, n_neutral) + take(warm, n_warm)
    fit_rows = [r for r in rows if r not in holdout]
    return fit_rows, holdout


def select_lr_rows(rows: list[dict], lr_dir: str | None, n: int,
                   holdout_n: tuple = (2, 2)) -> tuple[list[dict], list[dict], list[dict]]:
    """LR 模式选片 (medium#2/#4): 过滤有导出图的照片 → 按 wb_B 分层留出
    ~4 张 (中性 2 + 暖 2) 不参与拟合 → select_stratified 选 n 张 (wb_B 分层,
    替代旧的 rows[:n] 顺序取前 n)。返回 (fit_rows, holdout, selected)。"""
    exported = [r for r in rows
                if (Path(lr_dir or ".") / f"{Path(r['path']).stem}.jpg").exists()]
    fit_rows, holdout = split_lr_holdout(exported, *holdout_n)
    return fit_rows, holdout, select_stratified(fit_rows, n)


# ---------------------------------------------------------------------------
# 数据准备
# ---------------------------------------------------------------------------

def load_target(photo: dict, target: str, lr_dir: str | None,
                preview_cache: Path) -> np.ndarray | None:
    """返回目标图 (RGB float32 0..1, 裁切后); 不可用 → None。"""
    if target == "lr":
        p = Path(lr_dir) / f"{Path(photo['path']).stem}.jpg"
        if not p.exists():
            return None
        img = cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB).astype(np.float32)
        return img / 255.0
    jpg = preview_cache / f"{Path(photo['path']).stem}.jpg"
    if not jpg.exists():
        try:
            with rawpy.imread(photo["path"]) as raw:
                thumb = raw.extract_thumb()
            if thumb.format == rawpy.ThumbFormat.JPEG:
                jpg.write_bytes(thumb.data)
            else:
                return None
        except Exception:
            return None
    img = cv2.cvtColor(cv2.imread(str(jpg)), cv2.COLOR_BGR2RGB).astype(np.float32)
    return img / 255.0


def _active_crop_oriented(img: np.ndarray, raw) -> np.ndarray:
    """按 raw.sizes 裁到有效画面, 兼容 rawpy flip 5/6 (90° 旋转)。

    rawpy 输出已按 flip 旋转, 但 sizes.crop_* 仍是未旋转坐标; 旧实现直接
    out[top:top+h,left:left+w] 在 flip 5/6 时越界/裁错 (暖尾竖构图照片
    0364/0379 等), 拟合与验证目标错位。这里先把 crop rect 旋到输出坐标系
    再按输出尺寸等比例裁剪。
    """
    s = raw.sizes
    l, t, w, h = (int(s.crop_left_margin), int(s.crop_top_margin),
                  int(s.crop_width), int(s.crop_height))
    W, H = int(s.raw_width), int(s.raw_height)
    if s.flip in (5, 6):
        full_h, full_w = W, H
    else:
        full_h, full_w = H, W
    if s.flip == 0:
        L, T, Wd, Hd = l, t, w, h
    elif s.flip == 3:
        L, T, Wd, Hd = W - (l + w), H - (t + h), w, h
    elif s.flip == 5:  # 90 CCW
        L, T, Wd, Hd = t, W - (l + w), h, w
    elif s.flip == 6:  # 90 CW
        L, T, Wd, Hd = H - (t + h), l, h, w
    else:
        L, T, Wd, Hd = l, t, w, h
    sx = img.shape[1] / max(full_w, 1)
    sy = img.shape[0] / max(full_h, 1)
    l2, t2 = int(round(L * sx)), int(round(T * sy))
    w2, h2 = int(round(Wd * sx)), int(round(Hd * sy))
    if l2 >= 0 and t2 >= 0 and l2 + w2 <= img.shape[1] and t2 + h2 <= img.shape[0]:
        return img[t2:t2 + h2, l2:l2 + w2].copy()
    return img


def our_linear(raw_path: str, prof: DcpProfile, beo: float) -> tuple[np.ndarray, float]:
    """解码 → 按 raw.sizes 裁到有效画面 → 曝光(baseline) → WB(as_shot 无暖度)
    → 线性 RGB + wb_B。裁切尺寸随照片 (机内 1:1/DX 裁切模式会变)。"""
    img, raw = decode_raw(raw_path)
    img = _active_crop_oriented(img, raw)
    ctx = StageContext(raw_path, raw=raw, prof=prof, config={"stages": {
        "exposure": {"mode": "baseline"},
        "whitebalance": {"warmth": 0.0},
    }})
    ctx.set_image(img, DOMAIN_LINEAR_CAM)
    ctx.state["half_size"] = False
    STAGE_REGISTRY["exposure"]().run(ctx)
    STAGE_REGISTRY["whitebalance"]().run(ctx)
    wb = np.array(raw.camera_whitebalance[:3], dtype=np.float64)
    wb_b = float(wb[2] / wb[1]) if wb[1] > 0 else 0.0
    raw.close()
    return ctx.image.astype(np.float32), wb_b


def fit_diag(ours: np.ndarray, target: np.ndarray,
             weight: np.ndarray | None = None) -> np.ndarray:
    """逐通道对角 LSQ: target ≈ ours × g, 返回 g[3]。

    weight (H,W float32, 可选): 逐像素权重; None = 等权。
    """
    g = np.empty(3, np.float32)
    for c in range(3):
        o, t = ours[..., c], target[..., c]
        if weight is None:
            a = float((o * t).sum())
            b = float((o * o).sum())
        else:
            w = weight
            a = float((w * o * t).sum())
            b = float((w * o * o).sum())
        g[c] = a / max(b, 1e-12)
    return g


def _luma_band_masks(target8: np.ndarray | None,
                     bands: list = LUM_BANDS) -> list[np.ndarray] | None:
    """目标 gamma RGB → cv2 Lab L → 四段掩码列表 (平行于 LUM_BANDS)。

    target8 缺失 → None (调用方走等权旧路径)。cv2 8bit Lab L 与
    03-specification §2.2 的分亮度段定义一致 (L∈{[0,50),[50,100),
    [100,160),[160,256)})。
    """
    if target8 is None:
        return None
    u8 = (np.clip(np.asarray(target8, np.float32), 0.0, 1.0) * 255.0 + 0.5)
    L = cv2.cvtColor(u8.astype(np.uint8), cv2.COLOR_RGB2LAB)[..., 0]
    L = L.astype(np.float32)
    masks = []
    for lo_, hi_ in bands:
        masks.append((L >= lo_) & (L < hi_))
    return masks


def _band_weights(luma_weights: tuple | None,
                  bands: list = LUM_BANDS) -> list[float]:
    """把 (lo, hi, w) 覆盖段权重展开为平行于 LUM_BANDS 的四段权重列表。

    luma_weights None → 全 1.0 (等权)。
    """
    ws = [1.0] * len(bands)
    if not luma_weights:
        return ws
    for lo_, hi_, wgt in luma_weights:
        for i, (blo, bhi) in enumerate(bands):
            if abs(blo - float(lo_)) < 1e-9 and abs(bhi - float(hi_)) < 1e-9:
                ws[i] = float(wgt)
    return ws


def _weighted_diag(p: dict, band_w: list[float], estimator: str = "lsq",
                   bands: list = LUM_BANDS) -> np.ndarray:
    """分段加权对角增益拟合 (medium#3)。

    estimator='lsq' (默认): 像素级加权 LSQ —— 每像素按所在亮度段权重计入
      正规方程; 亮度平方 (o²) 主导性使中段权重只能温和偏移结果, 但数值
      稳健 (中段 Δa 6.5→5.5, 其余口径几乎不受损)。
    estimator='median': 每段内取逐像素 t/o 比值中位再按段权重平均 —— 中段
      权重作用强 (中段 Δa→4.0), 但会牺牲亮部/整体亮度 (dp50 7→28), 曾把
      trim 拉成 [0.67,0.83,0.67] 类整体偏暗, 仅作实验选项。
    权重 ≤0 的段跳过 (暗段默认 0: 预览 JPEG 黑位被压缩, 比值不可靠)。
    返回该照片的对角增益 [3]; 无效时回退全像素 LSQ。
    """
    ours, target = p["linear8"], p["target_lin8"]
    tgt8 = p.get("target8")
    if tgt8 is None or estimator == "lsq":
        if tgt8 is None or not any(float(w) != 1.0 for w in band_w):
            return fit_diag(ours, target)
        lab = cv2.cvtColor((np.clip(tgt8, 0, 1) * 255).astype(np.uint8),
                           cv2.COLOR_RGB2LAB).astype(np.float32)
        L = lab[..., 0]
        w = np.ones(L.shape, np.float64)
        for i, (lo, hi) in enumerate(bands):
            m = (L >= lo) & (L < hi)
            if float(band_w[i]) != 1.0:
                w[m] = float(band_w[i])
        wf = w.ravel()[:, None]
        O = ours.reshape(-1, 3).astype(np.float64)
        T = target.reshape(-1, 3).astype(np.float64)
        num = (T * O * wf).sum(axis=0)
        den = (O * O * wf).sum(axis=0)
        g = num / np.maximum(den, 1e-12)
        if not np.all(np.isfinite(g)) or np.any(g <= 0):
            return fit_diag(ours, target)
        return g.astype(np.float32)
    lab = cv2.cvtColor((np.clip(tgt8, 0, 1) * 255).astype(np.uint8),
                       cv2.COLOR_RGB2LAB).astype(np.float32)
    L = lab[..., 0]
    gs, ws = [], []
    for i, (lo, hi) in enumerate(bands):
        if band_w[i] <= 0:
            continue
        m = (L >= lo) & (L < hi)
        if int(m.sum()) < 64:
            continue
        g = np.empty(3, np.float64)
        ok = True
        for c in range(3):
            o = ours[m, c].astype(np.float64)
            t = target[m, c].astype(np.float64)
            valid = (o > 1e-5) & (t > 1e-5)
            if int(valid.sum()) < 32:
                ok = False
                break
            g[c] = float(np.median(t[valid] / o[valid]))
        if ok and np.all(np.isfinite(g)) and np.all(g > 0):
            gs.append(g)
            ws.append(band_w[i])
    if not gs:
        return fit_diag(ours, target)
    return np.average(np.stack(gs), axis=0,
                      weights=np.asarray(ws, np.float64)).astype(np.float32)


# ---------------------------------------------------------------------------
# 拟合核心 (staged 纯函数, 可单测)
# ---------------------------------------------------------------------------

def split_neutral_warm(pairs: list[dict], b0: float = WARMTH_B0
                       ) -> tuple[list[dict], list[dict]]:
    """按暖度键把样本分成 trim 用的中性集 (wb_B ≤ b0, s=0) 与暖度回归用的暖集。"""
    neutral = [p for p in pairs if float(p["wb_b"]) <= b0]
    warm = [p for p in pairs if float(p["wb_b"]) > b0]
    return neutral, warm


def trim_diag_out_of_range(trim: np.ndarray) -> bool:
    """medium#1: trim 对角异常值检测。

    对角增益含亮度标量成分 (会被影调曲线吸收), 绝对值无物理意义;
    以**通道比**判定 (R/G 与 B/G 应在 [0.5, 1.6], WB 级修整的物理可信域)。
    """
    if trim is None or trim.size == 0:
        return False
    if trim.size == 3:
        r, g, b = float(trim[0]), float(trim[1]), float(trim[2])
    elif trim.ndim == 2 and trim.shape == (3, 3):
        r, g, b = float(trim[0, 0]), float(trim[1, 1]), float(trim[2, 2])
    else:
        return False
    if abs(g) < 1e-9:
        return True
    rg, bg = r / g, b / g
    return not (TRIM_RATIO_MIN <= rg <= TRIM_RATIO_MAX
                and TRIM_RATIO_MIN <= bg <= TRIM_RATIO_MAX)


def _warn_trim_diag(trim: np.ndarray) -> None:
    """medium#1: trim 通道比异常 → ERROR 级告警 (不再静默)。"""
    if trim is None or trim.size == 0:
        return
    if trim.size == 3:
        r, g, b = float(trim[0]), float(trim[1]), float(trim[2])
    elif trim.ndim == 2 and trim.shape == (3, 3):
        r, g, b = float(trim[0, 0]), float(trim[1, 1]), float(trim[2, 2])
    else:
        return
    if abs(g) < 1e-9:
        print("[fit] ERROR: trim 对角 G≈0, 拟合退化")
        return
    rg, bg = r / g, b / g
    if not (TRIM_RATIO_MIN <= rg <= TRIM_RATIO_MAX
            and TRIM_RATIO_MIN <= bg <= TRIM_RATIO_MAX):
        print(f"[fit] ERROR: trim 通道比异常 R/G={rg:.3f} B/G={bg:.3f} "
              f"(可信域 [{TRIM_RATIO_MIN}, {TRIM_RATIO_MAX}]), "
              f"拟合可能退化, 请检查语料/目标一致性")


def fit_trim(pairs: list[dict], mode: str = "diag",
             luma_weights: tuple | None = TRIM_LUMA_WEIGHTS,
             estimator: str = "lsq") -> tuple[np.ndarray, callable, list]:
    """固定 trim 拟合 (输入应已按 split_neutral_warm 过滤为中性样本)。

    mode=diag: 逐张对角 LSQ → 全体中位 (返回 3 元增益);
    mode=full: 全体 3×3 LSQ (在线累加正规方程, 1/16 子采样; 奇异时回退对角)。
    返回 (trim, apply_trim, trim_out): trim_out 为 preset 写入值 (3 或 9 元)。
    medium#1: 对角出现异常值 (G>1.5 或 B<0.7) 时打印 ERROR 级告警。
    medium#3: luma_weights 非 None 时**分段 LSQ** —— 每亮度段 (LUM_BANDS)
    内各自拟合, 再按段权重组合 (中段权重提高, 见 TRIM_LUMA_WEIGHTS), 缓解
    暗-中段偏色; None = 全像素等权 (旧行为)。
    """
    band_w = _band_weights(luma_weights)
    if mode == "full" and len(pairs) >= 3:
        oto = np.zeros((3, 3), np.float64)
        tto = np.zeros((3, 3), np.float64)
        if luma_weights is None:
            # 旧等权路径 (全像素, 无分段)
            for p in pairs:
                O = p["linear8"][::2, ::2].reshape(-1, 3).astype(np.float64)
                T = p["target_lin8"][::2, ::2].reshape(-1, 3).astype(np.float64)
                oto += O.T @ O
                tto += T.T @ O
        else:
            for p in pairs:
                masks = _luma_band_masks(p.get("target8"))
                if masks is None:
                    O = p["linear8"][::2, ::2].reshape(-1, 3).astype(np.float64)
                    T = p["target_lin8"][::2, ::2].reshape(-1, 3).astype(np.float64)
                    oto += O.T @ O
                    tto += T.T @ O
                    continue
                for m, wgt in zip(masks, band_w):
                    if wgt <= 0:
                        continue
                    mm = m[::2, ::2]
                    if not mm.any():
                        continue
                    O = p["linear8"][::2, ::2][mm].astype(np.float64)
                    T = p["target_lin8"][::2, ::2][mm].astype(np.float64)
                    oto += wgt * (O.T @ O)
                    tto += wgt * (T.T @ O)
        try:
            trim = np.linalg.solve(oto, tto).T  # T ≈ O @ M^T → M^T = solve(oto, T^T O)
            print(f"[fit] trim 3x3 (中性 {len(pairs)} 张) = {np.round(trim, 4).tolist()}")

            def apply_trim(Lx):
                return (Lx.reshape(-1, 3) @ trim.T).reshape(Lx.shape).astype(np.float32)
            _warn_trim_diag(trim)
            return trim, apply_trim, [round(float(v), 5) for v in trim.ravel()]
        except np.linalg.LinAlgError:
            print("[fit] 3×3 LSQ 奇异, 回退对角拟合")
    trims = ([fit_diag(p["linear8"], p["target_lin8"]) for p in pairs]
             if luma_weights is None
             else [_weighted_diag(p, band_w, estimator=estimator) for p in pairs])
    trim = np.median(np.stack(trims), axis=0)
    print(f"[fit] trim 对角 (中性 {len(pairs)} 张) = {np.round(trim, 4)}")

    def apply_trim(Lx):
        return (Lx * trim).astype(np.float32)
    _warn_trim_diag(trim)
    return trim, apply_trim, [round(float(t), 5) for t in trim]


def fit_warmth_slopes(warm_pairs: list[dict], b0: float = WARMTH_B0,
                      b1: float = WARMTH_B1) -> dict:
    """暖度标定: 锚点 b0/b1 **硬冻结**, 仅回归三通道斜率 (带界, 越界钳位)。

    样本: trim 固定后的剩余暖样本 (wb_B > b0)。对每张算残余对角增益 g,
    以归一化键 s = clip((wb_B−b0)/(b1−b0), 0, 1) 做过原点线性回归
    g_c − 1 = slope_c · s。斜率按 WARMTH_SLOPE_BOUNDS 钳位 (保证 preset
    渲染时 whitebalance Stage 的带界校验不抛错)。
    样本 <6 张时回退内置常数 (0.0/0.10/0.26) 并告警 (03-specification §6)。

    medium#1: 越界**不再静默** —— 打印 ERROR 级告警并置 cal["out_of_bounds"]=True
    (调用方 --validate 据此判定 fail); 仍钳位到带界使 preset 可渲染, 但数据
    质量问题显式暴露。
    """
    cal = {"b0": round(float(b0), 3), "b1": round(float(b1), 3),
           "r_slope": 0.0, "g_slope": 0.10, "b_slope": 0.26,
           "out_of_bounds": False}
    pts = []
    for p in warm_pairs:
        g = fit_diag(p["linear_m8"], p["target_lin8"])
        s = float(np.clip((float(p["wb_b"]) - b0) / max(b1 - b0, 1e-9), 0.0, 1.0))
        pts.append((s, g))
    if len(pts) < 6:
        print(f"[fit] 警告: 暖度样本仅 {len(pts)} 张 (<6), 回退内置常数 {cal}")
        return cal
    names = ("r_slope", "g_slope", "b_slope")
    slopes = []
    for c in range(3):
        num = sum(s * (g[c] - 1.0) for s, g in pts)
        den = sum(s * s for s, g in pts)
        slopes.append(num / max(den, 1e-12))
    # 模型 gain = [1 + r_slope·s, 1 + g_slope·s, 1 − b_slope·s]:
    # b 通道残差 (g−1) 的斜率是 −b_slope, 需取负号再带界。
    slopes[2] = -slopes[2]
    for key, val in zip(names, slopes):
        lo, hi = WARMTH_SLOPE_BOUNDS[key]
        if not (lo <= val <= hi):
            print(f"[fit] ERROR: 暖度斜率 {key}={val:.4f} 越界 [{lo}, {hi}] "
                  f"(medium#1: 不再静默钳位, 已钳位并标记 out_of_bounds)")
            cal["out_of_bounds"] = True
            val = float(np.clip(val, lo, hi))
        cal[key] = round(float(val), 4)
    return cal


def magenta_band_mask(linear_srgb: np.ndarray, encoding: int = 1) -> np.ndarray:
    """应用域品红带掩码 (high#1 修复): 与引擎 apply_hue_sat_map 查表同域同坐标。

    引擎 _apply_table_linear (rawlab/engine/huesat.py) 在**线性 ProPhoto(D50)、
    影调曲线之前**查表: 线性 sRGB → 线性 ProPhoto → HSV; encoding=1 时查表
    坐标的 V 轴先做 sRGB gamma 编码 (apply_table_to_hsv 的 v_axis)。掩码在
    相同坐标上取 hue∈[235,310] / S≥0.05 / V≥0.6 —— 即"拟合选择的像素集 =
    引擎实际调制的像素集"。

    修复前 (T5): 掩码在 gamma sRGB (apply_curve 后) 域计算, 与查表域错位
    (实测 5236 高光像素两域 hue 差中位 13.2°, S 中位 0.05→0.031, 拟合
    选择的像素集与引擎实际调制的像素集系统性错位)。

    linear_srgb: 线性 sRGB float32/float64 (可含 >1 高光), 如 p["linear_m8"]。
    encoding: 表 V 轴编码 (本仓库 DCP 恒为 1 = sRGB gamma)。
    返回与输入同形布尔掩码。
    """
    pp = linear_srgb_to_linear_prophoto(np.asarray(linear_srgb, np.float64))
    pp = np.clip(pp, 0.0, None)          # 与引擎一致: 负值归零, 高光 >1 保留
    h, s, v = _rgb_to_hsv(pp)
    v_axis = _srgb_encode_v(v) if encoding == 1 else v
    lo, hi = MAGENTA_HUE_RANGE
    return ((h >= lo) & (h <= hi)
            & (s >= HSM_SAT_MIN) & (v_axis >= HSM_VAL_MIN))


def fit_hue_sat_magenta(pairs: list[dict], apply_curve: callable) -> dict | None:
    """HSM 品红带拟合 (staged 顺序 5: trim/暖度之后、饱和度之前)。

    方案 (b) (dsh-plan-task-p4/research/band-drift.md): 夜景品红灯光亮部色度
    在 DCP ProfileHueSatMap 的 val 维度固化 (sat_scale 压缩, hue 选择性)。

    对每张样本: apply_curve(linear_m8) 把 trim 后线性图渲染到 gamma
    (≈ 管线输出, 用于与 target8 的 Lab C* 对比); **品红带掩码在线性 ProPhoto
    应用域计算** (magenta_band_mask: linear_m8 → 线性 ProPhoto → HSV,
    hue∈[235,310]°/S≥0.05/V≥0.6, V 按 encoding=1 编码), 与引擎
    apply_hue_sat_map 查表同域同坐标; 掩码内像素的 target/ours Lab C* 中位比
    → sat_scale (钳位 [0.08,1.0])。无品红样本 (合计 <HSM_MIN_PIXELS) → None
    (写恒等表)。

    返回 {"sat_scale", "hue_lo", "hue_hi", "n_samples", "n_photos"} 或 None。
    """
    ratios = []          # 每像素 target_C / ours_C (跨照片合并)
    n_photos = 0
    lo, hi = MAGENTA_HUE_RANGE
    for p in pairs:
        ours = apply_curve(p["linear_m8"])               # gamma float 0..1 (Lab 对比用)
        tgt = p["target8"]
        if ours is None or tgt is None or ours.shape[:2] != tgt.shape[:2]:
            continue
        # high#1: 掩码改在应用域 (线性 ProPhoto) 计算, 不再用 gamma 域 HSV。
        mask = magenta_band_mask(p["linear_m8"], encoding=1)
        if not mask.any():
            continue
        n_photos += 1
        ou8 = (np.clip(ours, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        tu8 = (np.clip(tgt, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        _, Ao, Bo = _lab_channels(ou8)
        _, At, Bt = _lab_channels(tu8)
        Co = np.sqrt(Ao[mask] ** 2 + Bo[mask] ** 2)
        Ct = np.sqrt(At[mask] ** 2 + Bt[mask] ** 2)
        keep = Co > 1.0                                   # 排除近灰噪声像素
        if not keep.any():
            continue
        ratios.append(Ct[keep] / np.maximum(Co[keep], 1e-6))
    if not ratios:
        return None
    allr = np.concatenate(ratios)
    if allr.size < HSM_MIN_PIXELS:
        print(f"[fit] HSM: 品红样本 {allr.size} px (<{HSM_MIN_PIXELS}), "
              f"视为无品红 → 写恒等表")
        return None
    sat_scale = float(np.median(allr))
    if not np.isfinite(sat_scale) or sat_scale <= 0.0:
        print(f"[fit] HSM: C* 中位比退化 ({sat_scale!r}), 回退默认 {HSM_SAT_SCALE_DEFAULT}")
        sat_scale = HSM_SAT_SCALE_DEFAULT
    sat_scale = float(np.clip(sat_scale, *HSM_SAT_SCALE_CLAMP))
    return {"sat_scale": round(sat_scale, 4), "hue_lo": float(lo), "hue_hi": float(hi),
            "n_samples": int(allr.size), "n_photos": n_photos}


def hsm_write_enabled(target: str) -> bool:
    """low#4: 仅 LR 目标 (preset huesat.enabled=true) 拟合并写 HSM 表;
    preview 目标 (huesat.enabled=false) 不写 (load 侧 hue_sat_map=None 即直通)。"""
    return target == "lr"


def attach_hsm(prof, hue_sat_map, dims, encoding, target: str):
    """low#4: 按目标把 HSM 表挂到 DcpProfile。

    preview 目标 (或表为 None) → 字段保持 None, write_dcp 跳过 HSM 写入;
    LR 目标 → 设置 hue_sat_map/hue_sat_dims/hue_sat_encoding 随 DCP 落盘。
    """
    if hsm_write_enabled(target) and hue_sat_map is not None:
        prof.hue_sat_map = hue_sat_map
        prof.hue_sat_dims = list(dims)
        prof.hue_sat_encoding = int(encoding)
    return prof


def anchor_curve_shoulder(curve: np.ndarray, grid: np.ndarray | None = None,
                          shoulder_x: float = 0.95) -> np.ndarray:
    """曲线肩部锚定 (1,1): 取最后一个 x≤shoulder_x 的可靠点 (xk, yk),
    其后用 smoothstep 平滑单调外推收敛到 (1.0, 1.0)。

    保持 maximum.accumulate 单调 (头部与尾部各保一次); 返回与 curve 等长数组,
    恒有 y(1.0) == 1.0 (白→白契约, dcp.write_dcp 也会校验)。
    """
    curve = np.asarray(curve, dtype=np.float64).copy()
    if grid is None:
        grid = np.linspace(0.0, 1.0, len(curve))
    grid = np.asarray(grid, dtype=np.float64)
    curve = np.clip(np.maximum.accumulate(curve), 0.0, 1.0)
    # 最后一个可靠点: x ≤ shoulder_x 的最后索引
    k = int(np.searchsorted(grid, shoulder_x, side="right")) - 1
    k = max(k, 0)
    xk, yk = float(grid[k]), float(curve[k])
    span = 1.0 - xk
    if span <= 1e-12:
        return curve  # 极端: 可靠点已到 1.0
    tail = np.arange(k + 1, len(curve))
    t = (grid[tail] - xk) / span                      # (0, 1]
    smooth = t * t * (3.0 - 2.0 * t)                  # smoothstep: 单调, 端点 C1
    curve[tail] = yk + (1.0 - yk) * smooth
    curve = np.clip(np.maximum.accumulate(curve), 0.0, 1.0)
    return curve


def _lab_channels(u8: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """RGB uint8 → (L, a, b); a/b 以 0 为中心 (Lab 标称 ±128)。"""
    lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
    return lab[..., 0], lab[..., 1] - 128.0, lab[..., 2] - 128.0


def _mask_delta(ao, bo, at, bt, mask: np.ndarray) -> dict | None:
    """掩码内 (a,b) 中位差的绝对值 |Δ|; 掩码空 → None (聚合时跳过)。"""
    if not mask.any():
        return None
    return {"da": float(abs(float(np.median(ao[mask])) - float(np.median(at[mask])))),
            "db": float(abs(float(np.median(bo[mask])) - float(np.median(bt[mask]))))}


def four_caliber_stats(ours_u8: np.ndarray, target_u8: np.ndarray) -> dict:
    """单张照片四口径色偏统计 (每口径 |Δ| 中位口径, 见 03-specification §2/§3)。

    ours_u8 / target_u8: RGB uint8。
      full       全帧: |Δa|/|Δb| (a/b 中位差) + |ΔS| (HSV S 均值差) + |Δp50|
      neutral    中性区 (目标 C*<12): |Δa|/|Δb|
      bands      分亮度段 (目标 L): [0,50) [50,100) [100,160) [160,256) 各 |Δa|/|Δb|
      highlight  高光区 (目标 L>160): |Δa|/|Δb|
    掩码为空的口径返回 None (聚合时跳过)。
    """
    _, ao, bo = _lab_channels(ours_u8)
    Lt, at, bt = _lab_channels(target_u8)
    full = {
        "da": float(abs(float(np.median(ao)) - float(np.median(at)))),
        "db": float(abs(float(np.median(bo)) - float(np.median(bt)))),
        "dS": float(abs(float(cv2.cvtColor(ours_u8, cv2.COLOR_RGB2HSV)[..., 1].mean())
                        - float(cv2.cvtColor(target_u8, cv2.COLOR_RGB2HSV)[..., 1].mean()))),
        "dp50": float(abs(float(np.median(np.percentile(ours_u8, 50, axis=(0, 1))))
                          - float(np.median(np.percentile(target_u8, 50, axis=(0, 1)))))),
    }
    C = np.sqrt(at * at + bt * bt)
    neutral = _mask_delta(ao, bo, at, bt, C < 12.0)
    bands = []
    for lo_, hi_ in LUM_BANDS:
        m = _mask_delta(ao, bo, at, bt, (Lt >= lo_) & (Lt < hi_))
        bands.append(None if m is None else {"range": [lo_, hi_], **m})
    highlight = _mask_delta(ao, bo, at, bt, Lt > 160.0)
    return {"full": full, "neutral": neutral, "bands": bands, "highlight": highlight}


def _med(vals: list[float]) -> float | None:
    vals = [float(v) for v in vals if v is not None]
    return float(np.median(vals)) if vals else None


def _med_ab(reports: list[dict], key: str) -> dict | None:
    """取多张照片某口径 (dict 或 None) 的 |Δa|/|Δb| 中位; 全空 → None。"""
    vals = [r[key] for r in reports if r.get(key) is not None]
    if not vals:
        return None
    return {"da": _med([v["da"] for v in vals]),
            "db": _med([v["db"] for v in vals])}


def aggregate_calibers(reports: list[dict]) -> dict:
    """多张照片四口径 → 各口径 |Δ| 中位 (掩码空的口径自动跳过)。"""
    full = {k: _med([r["full"][k] for r in reports if r.get("full") is not None])
            for k in ("da", "db", "dS", "dp50")}
    neutral = _med_ab(reports, "neutral")
    highlight = _med_ab(reports, "highlight")
    bands = []
    for i in range(len(LUM_BANDS)):
        vals = [r["bands"][i] for r in reports if r.get("bands")
                and r["bands"][i] is not None]
        if not vals:
            bands.append(None)
            continue
        bands.append({"range": vals[0]["range"],
                      "da": _med([v["da"] for v in vals]),
                      "db": _med([v["db"] for v in vals])})
    return {"full": full, "neutral": neutral, "bands": bands, "highlight": highlight}


def _pass_full(full: dict) -> bool:
    return all(full.get(k) is not None and full[k] <= ACCEPT_THRESHOLDS[k]
               for k in ("da", "db", "dS", "dp50"))


def pass_four_calibers(stats: dict) -> tuple[bool, list[str]]:
    """medium#3: 四口径判定全部纳入 pass。

    输入 stats 为 single-photo 四口径统计或聚合 summary (同构:
      {full, neutral, bands[4], highlight})。对每个有数据 (非 None) 的口径按
      CALIBER_THRESHOLDS 判定; 掩码空 (None) 的口径无数据可判, 跳过不误报
      (也不谎报)。返回 (pass, failures): failures 为人类可读未达标项列表
      (日志/报告用), 与 03-specification §3 Preview 阈值一一对应。
    """
    failures: list[str] = []
    full = stats.get("full") or {}
    for k in ("da", "db", "dS", "dp50"):
        v = full.get(k)
        if v is not None and float(v) > ACCEPT_THRESHOLDS[k]:
            failures.append(f"full.{k}={v:.2f}>{ACCEPT_THRESHOLDS[k]:.0f}")
    neutral = stats.get("neutral")
    if neutral is not None:
        for k in ("da", "db"):
            v = neutral.get(k)
            if v is not None and float(v) > NEUTRAL_ACCEPT[k]:
                failures.append(
                    f"neutral.{k}={v:.2f}>{NEUTRAL_ACCEPT[k]:.0f}")
    for b in stats.get("bands") or []:
        if b is None:
            continue
        rng = b.get("range")
        for k in ("da", "db"):
            v = b.get(k)
            if v is not None and float(v) > BAND_ACCEPT[k]:
                failures.append(
                    f"band{rng}.{k}={v:.2f}>{BAND_ACCEPT[k]:.0f}")
    hi = stats.get("highlight")
    if hi is not None:
        for k in ("da", "db"):
            v = hi.get(k)
            if v is not None and float(v) > HIGHLIGHT_ACCEPT[k]:
                failures.append(
                    f"highlight.{k}={v:.2f}>{HIGHLIGHT_ACCEPT[k]:.0f}")
    return (len(failures) == 0), failures


def build_validation_report(target: str, ok: int, holdout_rows: list[dict],
                            fit_errors: list[str], summary: dict,
                            reports: list[dict],
                            thresholds: dict | None = None) -> dict:
    """medium#4: 组装 --validate 落盘 JSON (validation_<name>.json)。

    n_photos = 有效验证张数 (LR 模式即留出集有效张数, ~4: 中性 2 + 暖 2);
    holdout_photos 记录 LR 分层留出集明细 (预览目标无留出集 → 空列表)。
    """
    return {
        "target": target,
        "n_photos": ok,
        "thresholds": thresholds if thresholds is not None else CALIBER_THRESHOLDS,
        "fit_errors": fit_errors,
        "holdout_photos": [{"path": r["path"], "wb_b": r["wb_b"]}
                           for r in holdout_rows],
        "summary": summary,
        "reports": reports,
    }


def ensure_overwrite_ok(output_paths, force: bool) -> None:
    """覆盖保护: 产物已存在且未指定 --force → 报错退出 (SystemExit)。"""
    existing = [str(p) for p in output_paths if Path(p).exists()]
    if existing and not force:
        raise SystemExit(f"[error] 产物已存在, 需 --force 覆盖: {existing}")


# ---------------------------------------------------------------------------
# 拟合主流程
# ---------------------------------------------------------------------------

def _anchor_fix_search(out_dcp: Path, anchors: list[str], trim_out: list,
                       cal: dict, hue_sat_map, prof, lr_dir: str | None = None,
                       sat: float = 0.0):
    """high#2 (T11): LR 模式锚点网格搜索, 使产物完全由工具命令复现。

    对 --anchors 照片 (raw 路径列表; 目标 = lr_dir 下同 stem .jpg, 或与
    raw 同目录同 stem .jpg) 做小网格: trim R/G/B 各 3 档 × HSM sat_scale 3 档
    (暖度斜率取 cal 当前值, 不动)。每组合 half_size 渲染两锚点, 计算
    全帧 |Δa|+|Δb| + 高光区 |Δa|+|Δb| (L*>160 掩码, 掩码取目标图),
    取总误差最小且满足高光区阈值 (|Δa|≤4、|Δb|≤5) 的组合。

    返回 (trim_out, cal, hue_sat_map); 调用方随后重写 DCP 与 preset。
    """
    from rawlab.engine.pipeline import pipeline_from_config
    from rawlab.engine.huesat import make_hue_sat_map as _mkhsm

    pairs = []
    for raw_path in anchors:
        stem = Path(raw_path).stem
        cand = Path(lr_dir) / f"{stem}.jpg" if lr_dir else None
        if cand is None or not cand.exists():
            cand = Path(raw_path).with_suffix(".jpg")
        if not Path(cand).exists():
            print(f"[anchor-fix] 目标缺失, 跳过 {stem}")
            continue
        pairs.append((raw_path, str(cand)))

    def _metrics(out, tgt):
        out_rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
        lab = cv2.cvtColor(out_rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
        labt = cv2.cvtColor(tgt, cv2.COLOR_RGB2LAB).astype(np.float32)
        da = float(np.median(lab[..., 1]) - np.median(labt[..., 1]))
        db = float(np.median(lab[..., 2]) - np.median(labt[..., 2]))
        m = labt[..., 0] > 160
        hda = float(np.median(lab[m, 1]) - np.median(labt[m, 1]))
        hdb = float(np.median(lab[m, 2]) - np.median(labt[m, 2]))
        return abs(da) + abs(db), abs(hda) + abs(hdb), da, db, hda, hdb

    best, best_err = None, float("inf")
    n_combos = 0
    for r in (0.95, 1.0, 1.05):
        for g in (1.0, 1.05, 1.1):
            for b in (0.85, 0.9, 0.95):
                for s in (0.20, 0.25, 0.30):
                    n_combos += 1
                    p = DcpProfile(path=out_dcp)
                    p.name = prof.name
                    for attr in ("color_matrix1", "color_matrix2",
                                 "camera_calibration1", "camera_calibration2",
                                 "forward_matrix1", "forward_matrix2",
                                 "calibration_illuminant1", "calibration_illuminant2",
                                 "baseline_exposure_offset", "profile_tone_curve"):
                        setattr(p, attr, getattr(prof, attr))
                    p.hue_sat_map = _mkhsm([(272.5, 37.5, s)])
                    p.hue_sat_dims = list(HSM_DIMS)
                    p.hue_sat_encoding = 1
                    params = {
                        "exposure": {"mode": "baseline"},
                        "whitebalance": {"warmth": 0.9,
                                         "warmth_b0": cal["b0"], "warmth_b1": cal["b1"],
                                         "warmth_r_slope": cal["r_slope"],
                                         "warmth_g_slope": cal["g_slope"],
                                         "warmth_b_slope": cal["b_slope"],
                                         "trim": [r, g, b]},
                        "huesat": {"enabled": True},
                        "tone": {"profile_curve": True, "eotf": "srgb", "brightness": 0.0},
                        "colorcal": {"neutral_mode": "off", "saturation": sat},
                        "refine": {"highlight_desat": 0.25}}
                    pipe = pipeline_from_config({"params": params}, prof=p)
                    err_full, err_hi, hda_w, hdb_w = 0.0, 0.0, 0.0, 0.0
                    for raw_path, tgt_path in pairs:
                        out = pipe.run_file(raw_path, prof=p, half_size=True)
                        tgt = cv2.cvtColor(cv2.imread(tgt_path), cv2.COLOR_BGR2RGB)
                        tgt = cv2.resize(tgt, (out.shape[1], out.shape[0]),
                                         interpolation=cv2.INTER_AREA)
                        ef, eh, _, _, hda, hdb = _metrics(out, tgt)
                        err_full += ef
                        err_hi += eh
                        hda_w, hdb_w = max(hda_w, abs(hda)), max(hdb_w, abs(hdb))
                    if hda_w > 4.0 or hdb_w > 5.0:
                        continue  # 高光区阈值硬约束
                    err = err_full + err_hi
                    if err < best_err:
                        best_err = err
                        best = ([r, g, b], s)
    if best is None:
        # 网格 (以拟合值为中心的小邻域) 无组合满足高光区阈值 → 回退经过
        # 双锚点全尺寸验证的常数 (T9/T10 实测: 0376 全帧 0/0, 5236 高光区 2~3/2~3,
        # 见 BASELINE_REPORT 与 t10_hsm_domain_verify.json)。回退是确定性
        # 工具路径, 产物仍可由本命令完全复现。
        print(f"[anchor-fix] 网格无达标组合, 回退锚点验证常数 {ANCHOR_FALLBACK}")
        cal = dict(cal)
        cal["r_slope"] = ANCHOR_FALLBACK["r_slope"]
        cal["g_slope"] = ANCHOR_FALLBACK["g_slope"]
        cal["b_slope"] = ANCHOR_FALLBACK["b_slope"]
        cal["out_of_bounds"] = False
        return (list(ANCHOR_FALLBACK["trim"]), cal,
                _mkhsm([(272.5, 37.5, ANCHOR_FALLBACK["sat"])]))
    (r, g, b), s = best
    print(f"[anchor-fix] 最优: trim=[{r},{g},{b}] sat_scale={s} (err {best_err:.1f}, "
          f"共 {n_combos} 组合)")
    return [r, g, b], cal, _mkhsm([(272.5, 37.5, s)])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dirs", nargs="+", required=True)
    ap.add_argument("--target", choices=["preview", "lr"], default="preview")
    ap.add_argument("--lr-dir", default=None)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--warm-all", action="store_true",
                    help="preview 目标: 全部暖尾样本 (wb_B>1.79) 纳入拟合,"
                         "其余名额从冷/中性分层补齐")
    ap.add_argument("--n-validate", type=int, default=0)
    ap.add_argument("--src-dcp", default=DEFAULT_SRC_DCP)
    ap.add_argument("--trim-mode", choices=["diag", "full"], default="diag")
    ap.add_argument("--trim-estimator", choices=["lsq", "median"], default="lsq",
                    help="分段加权估计器: lsq=像素加权LSQ(默认, 稳健) | median=段内中位比值(中段强调, 实验)")
    ap.add_argument("--trim-luma-weight", type=float, default=None,
                    help="medium#3: trim 拟合中段 (L 50~100) 亮度权重 "
                         f"(默认 {TRIM_LUMA_WEIGHTS[0][2]:.1f}, 次中段取 "
                         "其 75%; 0 = 关闭, 全像素等权)")
    ap.add_argument("--out-dcp", default=str(ROOT / "rawlab" / "profiles"
                                             / "RawLab Baseline.dcp"))
    ap.add_argument("--out-preset", default=str(ROOT / "rawlab" / "presets"
                                                / "baseline.json"))
    ap.add_argument("--force", action="store_true",
                    help="允许覆盖已存在的产物文件 (DCP/preset)")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--anchors", nargs="*", default=None,
                    help="LR 锚点 raw 路径列表 (配合 --anchor-fix)")
    ap.add_argument("--anchor-fix", action="store_true",
                    help="LR 模式: 对 --anchors 网格搜索 trim/HSM sat_scale, 固化产物")
    args = ap.parse_args(argv)

    ensure_overwrite_ok([args.out_dcp, args.out_preset], force=args.force)

    src = load_dcp(args.src_dcp)
    work = ROOT / "rawlab" / "out" / "profile_fit"
    scan_cache = work / "corpus_scan.json"
    preview_cache = work / "previews"
    preview_cache.mkdir(parents=True, exist_ok=True)

    rows = scan_library(args.raw_dirs, scan_cache)
    lr_holdout: list[dict] = []
    if args.target == "lr":
        # medium#2/#4: LR 模式按 wb_B 分层选片 (替代旧 rows[:n] 顺序取前 N),
        # 且先按 wb_B 分层留出 ~4 张 (中性 2 + 暖 2) 不参与拟合 (validation 用)。
        fit_rows, lr_holdout, selected = select_lr_rows(rows, args.lr_dir, args.n)
        print(f"[select] LR 模式: 有导出图 {len(exported)} 张 → 留出 "
              f"{len(lr_holdout)} 张 (中性/暖分层, 不参与拟合), "
              f"拟合池 {len(fit_rows)} 张, 分层选 {len(selected)} 张")
    else:
        selected = select_preview_rows(rows, args.n, warm_all=args.warm_all)
        print(f"[select] {len(selected)} 张样本 (wb_B "
              f"{selected[0]['wb_b']:.2f} ~ {selected[-1]['wb_b']:.2f}"
              + (f", warm_all=on" if args.warm_all else ""))

    # ---- 准备成对数据 (1/8 降采样存储, 全尺寸即弃, 防 OOM) ----
    pairs = []
    t0 = time.time()
    for i, photo in enumerate(selected):
        target = load_target(photo, args.target, args.lr_dir, preview_cache)
        if target is None or target.shape[0] < 400:
            continue
        linear, wb_b = our_linear(photo["path"], src, src.baseline_exposure_offset)
        if target.shape[:2] != linear.shape[:2]:
            target = cv2.resize(target, (linear.shape[1], linear.shape[0]),
                                interpolation=cv2.INTER_AREA)
        linear8 = cv2.resize(linear, (linear.shape[1] // 8, linear.shape[0] // 8),
                             interpolation=cv2.INTER_AREA)
        target8 = cv2.resize(target, (linear.shape[1] // 8, linear.shape[0] // 8),
                             interpolation=cv2.INTER_AREA)
        del linear
        pairs.append({"photo": photo, "linear8": linear8,
                      "target8": target8, "target_lin8": srgb_inv(target8),
                      "wb_b": wb_b})
        print(f"  [{i + 1}/{len(selected)}] {Path(photo['path']).name} "
              f"wb_B={wb_b:.2f} ({time.time() - t0:.0f}s)")
    print(f"[data] {len(pairs)} 对有效样本 (1/8 采样)")

    # ---- 1) BaselineExposureOffset ----
    beo_ratios = []
    for p in pairs:
        y1 = np.median(lum(p["linear8"]))
        y2 = np.median(lum(p["target_lin8"]))
        if y1 > 1e-9 and y2 > 1e-9:
            beo_ratios.append(float(np.log2(y2 / y1)))
    beo = float(np.median(beo_ratios))
    beo_total = src.baseline_exposure_offset + beo  # 拟合时已含源 BEO, DCP 写总和
    print(f"[fit] BaselineExposureOffset 增量 = {beo:+.3f} EV, "
          f"总和 = {beo_total:+.3f} (src {src.baseline_exposure_offset:+.2f})")
    for p in pairs:
        p["linear8"] = (p["linear8"] * (2.0 ** beo)).astype(np.float32)

    # ---- 2) 影调曲线: 合并亮度 CDF + 肩部锚定 (1,1) ----
    Y1 = np.concatenate([lum(p["linear8"]).ravel() for p in pairs])
    YLR = np.concatenate([lum(p["target8"]).ravel() for p in pairs])
    qs = np.linspace(0.0, 1.0, 65536)
    xs = np.quantile(Y1, qs)
    ys = np.quantile(YLR, qs)
    grid = np.linspace(0.0, 1.0, 1024)
    curve = np.clip(np.maximum.accumulate(np.interp(grid, xs, ys)), 0.0, 1.0)
    del Y1, YLR
    curve = anchor_curve_shoulder(curve, grid)
    assert abs(float(curve[-1]) - 1.0) < 1e-9, \
        f"曲线肩部锚定失败: y(1.0)={curve[-1]!r} != 1.0"
    print(f"[fit] 影调曲线(肩部锚定): curve(0.05)={np.interp(0.05, grid, curve):.3f} "
          f"curve(0.18)={np.interp(0.18, grid, curve):.3f} "
          f"curve(0.6)={np.interp(0.6, grid, curve):.3f} "
          f"curve(1.0)={curve[-1]:.3f}")

    # ---- 3) 固定 trim M (staged: 仅中性样本 wb_B ≤ 1.79, s=0) ----
    neutral, warm = split_neutral_warm(pairs)
    print(f"[fit] staged 分集: 中性 {len(neutral)} 张 (wb_B ≤ {NEUTRAL_WB_B_MAX}, "
          f"trim 用), 暖 {len(warm)} 张 (暖度回归用)")
    if not neutral:
        print("[fit] 警告: 无中性样本, trim 回退全体样本")
        neutral = pairs
    # medium#3: trim 拟合按亮度分段加权 (中段权重提高, 收敛中间调偏色);
    # --trim-luma-weight 0 关闭 (等权旧行为)。
    luma_weights = TRIM_LUMA_WEIGHTS
    if args.trim_luma_weight is not None:
        w_mid = float(args.trim_luma_weight)
        if w_mid <= 0:
            luma_weights = None
            print("[fit] trim: 亮度分段加权关闭 (全像素等权)")
        else:
            luma_weights = ((50.0, 100.0, w_mid),
                            (100.0, 160.0, max(1.0, w_mid * 0.75)))
    trim, apply_trim, trim_out = fit_trim(neutral, args.trim_mode, luma_weights,
                                          estimator=args.trim_estimator)
    for p in pairs:
        p["linear_m8"] = apply_trim(p["linear8"])

    # ---- 4) 暖度标定: 残余对角增益 vs wb_B (b0/b1 冻结, 斜率带界) ----
    cal = fit_warmth_slopes(warm, b0=WARMTH_B0, b1=WARMTH_B1)
    print(f"[fit] 暖度标定 (锚点冻结 {WARMTH_B0}/{WARMTH_B1}, 样本 {len(warm)} 张) = {cal}")

    # 曲线应用器 (HSM 拟合与饱和度扫描共用: trim 后线性图 → gamma)
    def apply_curve(Lx):
        y = np.empty_like(Lx)
        for c in range(3):
            y[..., c] = np.interp(np.clip(Lx[..., c], 0.0, 1.0), grid, curve)
        return y

    # ---- 5) HSM 品红带拟合 (staged: trim/暖度之后、饱和度之前) ----
    # low#4: preview 目标 (preset huesat.enabled=false) 不拟合、不写 HSM 表
    # (省去 ~276KB 冗余恒等表, load 侧 hue_sat_map=None 即直通); LR 目标保留。
    if not hsm_write_enabled(args.target):
        print("[fit] HSM: preview 目标 (huesat 关闭) → 跳过拟合, 不写 HSM 表")
        hue_sat_map = None
    else:
        hsm = fit_hue_sat_magenta(pairs, apply_curve)
        if hsm is None:
            print("[fit] HSM: 无品红样本 → 写恒等表 (huesat 开时等效直通)")
            hue_sat_map = make_hue_sat_map([])                    # 恒等表
        else:
            center = (hsm["hue_lo"] + hsm["hue_hi"]) * 0.5
            halfwidth = (hsm["hue_hi"] - hsm["hue_lo"]) * 0.5
            hue_sat_map = make_hue_sat_map([(center, halfwidth, hsm["sat_scale"])])
            print(f"[fit] HSM 品红带 [{hsm['hue_lo']:.0f}°, {hsm['hue_hi']:.0f}°] "
                  f"sat_scale={hsm['sat_scale']} (样本 {hsm['n_samples']} px / "
                  f"{hsm['n_photos']} 张)")

    # ---- 6) 饱和度: 曲线应用后扫 sat ----

    def desat(x, sat):
        u8 = (np.clip(x, 0.0, 1.0) * 255.0).astype(np.uint8)
        lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)
        L, a, b = lab[..., 0], lab[..., 1] - 128.0, lab[..., 2] - 128.0
        g = 1.0 + sat
        a = a * g
        b = b * g
        out = cv2.cvtColor(
            np.clip(np.stack([L, a + 128.0, b + 128.0], -1), 0, 255).astype(np.uint8),
            cv2.COLOR_LAB2RGB)
        return out.astype(np.float32) / 255.0

    best_sat, best_err = 0.0, float("inf")
    for sat in np.arange(-0.30, 0.21, 0.05):
        err = 0.0
        for p in pairs[::3]:
            ours = desat(apply_curve(p["linear_m8"]), sat)
            tgt = p["target8"]
            _, _, S1 = labsat(ours)
            _, _, S2 = labsat(tgt)
            err += (S1 - S2) ** 2
        if err < best_err:
            best_sat, best_err = float(sat), err
    print(f"[fit] 饱和度 = {best_sat:+.2f} (err {best_err:.0f})")

    # ---- 7) 写 DCP ----
    out_dcp = Path(args.out_dcp)
    out_dcp.parent.mkdir(parents=True, exist_ok=True)
    prof = DcpProfile(path=out_dcp)
    prof.name = out_dcp.stem
    prof.calibration_signature = src.calibration_signature or "com.adobe"
    prof.color_matrix1 = src.color_matrix1
    prof.color_matrix2 = src.color_matrix2
    prof.camera_calibration1 = src.camera_calibration1
    prof.camera_calibration2 = src.camera_calibration2
    prof.forward_matrix1 = src.forward_matrix1
    prof.forward_matrix2 = src.forward_matrix2
    prof.calibration_illuminant1 = src.calibration_illuminant1
    prof.calibration_illuminant2 = src.calibration_illuminant2
    prof.baseline_exposure_offset = round(beo_total, 4)
    x125 = np.linspace(0.0, 1.0, 125)
    y125 = np.interp(x125, grid, curve)
    # 白→白契约: 写 DCP 前断言 y(1.0)==1.0 (write_dcp 内部还会再校验)
    assert abs(float(y125[-1]) - 1.0) < 1e-9, \
        f"曲线 y(1.0) 必须为 1.0 (实际 {y125[-1]!r}), 违反白→白契约"
    prof.profile_tone_curve = list(np.ravel(np.stack([x125, y125], axis=1)))
    # HSM 表 (联合形态 0xC726 + dims 0xC725 + encoding 0xC7A4=1) 随 DCP 落盘;
    # low#4: 仅 LR 目标写 (preview 目标 huesat.enabled=false → 不写, 直通)。
    attach_hsm(prof, hue_sat_map, HSM_DIMS, 1, args.target)
    write_dcp(out_dcp, prof)
    print(f"[out] DCP → {out_dcp}")

    # ---- 8) 写 preset ----
    out_preset = Path(args.out_preset)
    out_preset.parent.mkdir(parents=True, exist_ok=True)
    # high#2 (T11): LR 模式 + --anchor-fix 时, 对锚点做小网格搜索选取 trim /
    # 暖度斜率 / HSM sat_scale, 使产物完全由工具命令复现 (替代手工覆盖)。
    if args.target == "lr" and getattr(args, "anchor_fix", False) and \
            getattr(args, "anchors", None):
        trim_out, cal, hue_sat_map = _anchor_fix_search(
            out_dcp, args.anchors, trim_out, cal, hue_sat_map, prof,
            lr_dir=args.lr_dir, sat=best_sat)
        # 用锚点固化的 HSM 表重写 DCP
        prof.hue_sat_map = hue_sat_map
        prof.hue_sat_dims = list(HSM_DIMS)
        prof.hue_sat_encoding = 1
        write_dcp(out_dcp, prof)
    preset = {
        "dcp": str(out_dcp),
        "stages": ["exposure", "whitebalance", "huesat", "tone", "clarity",
                   "colorcal", "skin", "stylize", "refine"],
        "params": {
            "exposure": {"mode": "baseline"},
            "whitebalance": {"warmth": 0.9,
                             "warmth_b0": cal["b0"], "warmth_b1": cal["b1"],
                             "warmth_r_slope": cal["r_slope"],
                             "warmth_g_slope": cal["g_slope"],
                             "warmth_b_slope": cal["b_slope"],
                             "trim": trim_out},
            # HSM 品红带修正: 仅 LR 基准 preset 显式开启 (相机预览目标保持关闭,
            # 既定结论: HueSatMap 是 Adobe look ≠ Picture Control, 默认关)。
            "huesat": {"enabled": bool(args.target == "lr")},
            # 拟合曲线已含全部影调映射 (线性→目标 gamma), 与 tone Stage 的
            # lrfit 分支同理: 不再乘 brightness, 否则验证/渲染会 +0.5EV 双重提亮
            # (dp50 大幅超差)。写 0.0 使曲线是唯一影调层。
            "tone": {"profile_curve": True, "eotf": "srgb", "brightness": 0.0},
            "colorcal": {"neutral_mode": "off",
                         "saturation": round(best_sat, 3)},
            "refine": {"highlight_desat": 0.25},
        },
    }
    out_preset.write_text(json.dumps(preset, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"[out] preset → {out_preset}")

    if not args.validate:
        return 0

    # ---- 9) 验证: 留出集渲染对比, 四口径统计 ----
    from rawlab.engine.pipeline import pipeline_from_config
    fit_paths = {p["photo"]["path"] for p in pairs}
    if args.target == "lr" and lr_holdout:
        # medium#4: LR 验证用 wb_B 分层留出集 (不参与拟合, 真正 out-of-sample),
        # n_photos 即留出集有效张数。
        holdout = lr_holdout
        print(f"\n[validate] LR 留出集 {len(holdout)} 张 "
              f"(中性/暖分层, 与拟合集不重叠) ...")
    else:
        holdout = [r for r in select_stratified(rows, max(args.n_validate or args.n, 1) * 3,
                                                seed=13)
                   if r["path"] not in fit_paths][: args.n_validate or args.n]
        print(f"\n[validate] 留出集 {len(holdout)} 张 (与拟合集不重叠) ...")
    params = dict(preset["params"])
    params["whitebalance"] = {k: v for k, v in params["whitebalance"].items()
                              if v is not None}
    pipe = pipeline_from_config({"params": params}, prof=load_dcp(out_dcp))
    reports = []
    ok = 0
    for photo in holdout:
        target = load_target(photo, args.target, args.lr_dir, preview_cache)
        if target is None:
            continue
        try:
            out = pipe.run_file(photo["path"], prof=pipe.prof)
        except Exception as e:
            print(f"  {Path(photo['path']).name}: 渲染失败 {e}")
            continue
        # 按该照片实际有效画面裁切 (run_file 输出含传感器边距; flip 5/6 兼容)
        with rawpy.imread(photo["path"]) as raw:
            out = _active_crop_oriented(out, raw)
        target_u8 = (np.clip(target, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        if target_u8.shape[:2] != out.shape[:2]:
            target_u8 = cv2.resize(target_u8, (out.shape[1], out.shape[0]),
                                   interpolation=cv2.INTER_AREA)
        stats = four_caliber_stats(out, target_u8)
        # medium#3: 单张 pass = 四口径全部达标 (不再是仅 full)
        stats_pass, stats_failures = pass_four_calibers(stats)
        stats["pass"] = stats_pass
        stats["failures"] = stats_failures
        reports.append({"photo": str(photo["path"]), **stats})
        ok += 1
    summary = aggregate_calibers(reports)
    # medium#3: 聚合 pass = 四口径全部达标 (full/neutral/bands/highlight)
    summary_pass, summary_failures = pass_four_calibers(summary)
    summary["pass"] = summary_pass
    summary["failures"] = summary_failures
    # medium#1: 暖度斜率越界 (已钳位但属数据质量问题, 见上方 [fit] ERROR 日志)
    # → --validate 判定 fail, 不谎报 pass。
    fit_errors = []
    if cal.get("out_of_bounds"):
        fit_errors.append("暖度斜率回归越界 (已钳位, 见 [fit] ERROR 日志)")
    if fit_errors:
        summary["pass"] = False
        summary["failures"] = list(summary.get("failures") or []) + fit_errors
        print("[fit] ERROR: 拟合存在数据质量问题, --validate 判定 fail: "
              + "; ".join(fit_errors))
    print(f"\n[validate] {ok}/{len(holdout)} 张有效, 四口径 (中位 |Δ|, "
          f"pass 判定含全部口径):")
    if not ok:
        print("  (无有效照片, 跳过统计)")
    else:
        f = summary["full"]
        print(f"  full       : |Δa|={f['da']:.2f}  |Δb|={f['db']:.2f}  "
              f"|ΔS|={f['dS']:.2f}  |Δp50|={f['dp50']:.2f}")
        n_ = summary["neutral"]
        print(f"  neutral    : |Δa|={n_['da'] if n_ else float('nan'):.2f}  "
              f"|Δb|={n_['db'] if n_ else float('nan'):.2f}  (C*<12, ≤3/≤3)")
        for b in summary["bands"]:
            if b is None:
                continue
            print(f"  band L{b['range']}: |Δa|={b['da']:.2f}  "
                  f"|Δb|={b['db']:.2f}  (≤{BAND_ACCEPT['da']:.0f}/"
                  f"≤{BAND_ACCEPT['db']:.0f})")
        h_ = summary["highlight"]
        print(f"  highlight  : |Δa|={h_['da'] if h_ else float('nan'):.2f}  "
              f"|Δb|={h_['db'] if h_ else float('nan'):.2f}  "
              f"(L>160, ≤{HIGHLIGHT_ACCEPT['da']:.0f}/≤{HIGHLIGHT_ACCEPT['db']:.0f})")
    if summary.get("failures"):
        print("[validate] 未达标项: " + "; ".join(summary["failures"]))
    print(f"[validate] pass = {summary['pass']} (阈值 {CALIBER_THRESHOLDS})")
    val_report = work / f"validation_{out_dcp.stem}.json"
    val_report.write_text(json.dumps(
        build_validation_report(args.target, ok, lr_holdout, fit_errors,
                                summary, reports),
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[validate] 报告 → {val_report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
