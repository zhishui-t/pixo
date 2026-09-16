"""A/B: 引擎全链渲染 vs 相机内嵌预览 (量化 ΔE/裁切)。用法: python scripts/ab_vs_camera_thumb.py"""
import sys
from pathlib import Path

import cv2
import numpy as np
import rawpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pixo.render.api import Renderer  # noqa: E402


def cam_thumb(p: Path) -> np.ndarray:
    """RAW 内嵌预览 → 与 pixo 渲染画布同构的朝向 (传感器画布)。

    注意 (2026-09-14 修正): NEF 内嵌缩略图**已是显示态**, 不能再套 EXIF 教科书
    旋转表, 否则 48.4% 的竖拍样本会被转成 180° 反相 (逐像素 ΔE 虚高 2.8x)。
    pixo render_preview_full 输出传感器尺寸画布, 故此处须把缩略图**逆旋**回去。
    映射表与实证依据同 scripts/fit_rp_ccm.py:100-106 (np.rot90 的 k 参数)。
    """
    with rawpy.imread(str(p)) as raw:
        t = raw.extract_thumb()
        if t.format == rawpy.ThumbFormat.JPEG:
            bgr = cv2.imdecode(np.frombuffer(t.data, np.uint8), cv2.IMREAD_COLOR)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        else:
            rgb = np.asarray(t.data)[..., :3].copy()
    try:
        from pixo.meta import extract as ex
        o = int((ex(p)["capture"].get("orientation") or 1))
    except Exception:
        o = 1
    k = {3: 2, 6: 1, 8: -1}.get(o, 0)
    if k:
        rgb = np.ascontiguousarray(np.rot90(rgb, k))
    return rgb


def lab(img_u8):
    return cv2.cvtColor(img_u8, cv2.COLOR_RGB2LAB).astype(np.float32)


def compare(name, ours_u8, ref_u8):
    h = min(ours_u8.shape[0], ref_u8.shape[0])
    w = min(ours_u8.shape[1], ref_u8.shape[1])
    a = cv2.resize(ours_u8, (w, h), interpolation=cv2.INTER_AREA)
    b = cv2.resize(ref_u8, (w, h), interpolation=cv2.INTER_AREA)
    la, lb = lab(a), lab(b)
    d = np.linalg.norm(la - lb, axis=2)
    hi_a = float((a.max(axis=2) >= 250).mean()) * 100
    lo_a = float((a.min(axis=2) <= 5).mean()) * 100
    hi_b = float((b.max(axis=2) >= 250).mean()) * 100
    lo_b = float((b.min(axis=2) <= 5).mean()) * 100
    print(f"{name}: dE={d.mean():.1f}/p50={np.median(d):.1f} "
          f"dL={(la[...,0]-lb[...,0]).mean():+.1f} "
          f"da={(la[...,1]-lb[...,1]).mean():+.1f} "
          f"db={(la[...,2]-lb[...,2]).mean():+.1f} | "
          f"clip_hi 我们={hi_a:.2f}% 相机={hi_b:.2f}% "
          f"clip_lo 我们={lo_a:.2f}% 相机={lo_b:.2f}%")


if __name__ == "__main__":
    # 单图模式 (t72): 命令行传入任意 RAW 路径即只跑这些; 缺省跑四样张回归。
    import sys

    dcp = sorted(Path(__file__).resolve().parents[1].joinpath("resources/dcp").glob("*.dcp"))[0]
    r = Renderer(dcp)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    paths = [Path(a) for a in args] or [
             Path("<corpus>/a/raw/DSC_5236.NEF"),
             Path("<corpus>/a/raw/DSC_5239.NEF"),
             Path("<corpus>/festival/DSC_0352.NEF"),
             Path("<corpus>/festival/DSC_0355.NEF"),
             Path("<corpus>/xiamen/set01/DSC_0847.NEF")]  # 高调缺口回归线(t73/t80)
    for p in paths:
        if not p.exists():
            print("missing", p)
            continue
        ref = cam_thumb(p)
        ours = r.render_preview_full(p, long_edge=1024)
        compare(f"{p.name} [默认]", ours, ref)
        alt = r.render_preview_full(p, long_edge=1024,
                                    params={"tone": {"brightness": 0.25}})
        compare(f"{p.name} [b=0.25]", alt, ref)
