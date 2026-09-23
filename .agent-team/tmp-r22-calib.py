"""R22 / F01+F06 —— 全幅口径阈值标定 v3（靶向抽样）。

口径：rawpy 内嵌相机 JPEG **全幅 6048x4032**，4 层路径
`measurement["global"]["detail"]["sharpness"]`（design-r22 §2.1 裁决③：
噪声/细节类指标只用导出全幅标定）。

抽样：低 ISO 组 DSC_5236~5250 + 高 ISO 组 DSC_5278/5279/5290~5295/
5309/5310/5314/5315（exploration-r22 §1.5 的 ISO>=3200 清单）。
逐行输出可被 `tmp-r22-calib-report.py` 增量解析（部分完成也能出分位表）。

命令：python .agent-team/tmp-r22-calib.py > .agent-team/tmp-r22-calib-out.txt 2>&1
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np
import rawpy

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pixo.meta import extract as meta_extract          # noqa: E402
from pixo.vision.measure import compute_proxy_metrics   # noqa: E402

ROOT = Path(r"K:\data\photo\0711\raw")
LOW_ISO = list(range(5236, 5251))
HIGH_ISO = [5278, 5279, 5290, 5291, 5292, 5293, 5294, 5295,
            5309, 5310, 5314, 5315]


def thumb_rgb(path: Path) -> np.ndarray | None:
    try:
        with rawpy.imread(str(path)) as raw:
            thumb = raw.extract_thumb()
        if thumb.format == rawpy.ThumbFormat.JPEG:
            img = cv2.imdecode(np.frombuffer(thumb.data, dtype=np.uint8),
                               cv2.IMREAD_COLOR)
        else:
            img = thumb.data
        if img is None:
            return None
        return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    except Exception as exc:  # noqa: BLE001
        print(f"# thumb failed {path.name}: {type(exc).__name__}: {exc}")
        return None


def sharpness_fast(rgb: np.ndarray) -> tuple[float, float]:
    """measure_sharpness 的 noise_ratio/detail_score 同式快路径（去 FFT 项）。"""
    gray = cv2.cvtColor(np.clip(rgb, 0.0, 255.0).astype(np.uint8),
                        cv2.COLOR_RGB2GRAY)
    lap_raw = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    med = cv2.medianBlur(gray, 5)
    lap_denoised = float(cv2.Laplacian(med, cv2.CV_64F).var())
    noise = max(0.0, min(1.0, (lap_raw - lap_denoised) / max(lap_raw, 1e-6)))
    return round(noise, 4), round(lap_denoised, 2)


def iso_of(path: Path) -> int | None:
    try:
        meta = meta_extract(str(path)) or {}
    except Exception as exc:  # noqa: BLE001
        print(f"# meta failed {path.name}: {type(exc).__name__}: {exc}")
        return None
    iso = (meta.get("exposure") or {}).get("iso")
    try:
        return int(iso) if iso is not None else None
    except (TypeError, ValueError):
        return None


def main() -> int:
    t0 = time.time()
    for idx in LOW_ISO + HIGH_ISO:
        path = ROOT / f"DSC_{idx}.NEF"
        if not path.exists():
            print(f"# missing {path.name}")
            continue
        t1 = time.time()
        iso = iso_of(path)
        t2 = time.time()
        img = thumb_rgb(path)
        t3 = time.time()
        if img is None:
            continue
        noise, detail = sharpness_fast(img)
        t4 = time.time()
        proxies = compute_proxy_metrics(img)
        t5 = time.time()
        print(f"{path.name}\tiso={iso}\t{img.shape[1]}x{img.shape[0]}\t"
              f"noise={noise}\tdetail={detail}\t"
              f"colorful={proxies.get('colorfulness_proxy')}\t"
              f"haze={proxies.get('haze_proxy')}\t"
              f"tonal={proxies.get('tonal_range')}\t"
              f"[meta={t2-t1:.1f}s thumb={t3-t2:.1f}s sharp={t4-t3:.1f}s "
              f"proxy={t5-t4:.1f}s]")
        sys.stdout.flush()
    print(f"\nelapsed={time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
