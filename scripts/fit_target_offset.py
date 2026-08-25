"""拟合场景自适应曝光标定表 target_offset.json。

对每张 RAW: 用相机内嵌缩略图亮度为真值, 二分搜索 exposure.mode 数值 EV,
使全链渲染的 gamma 中位亮度与之匹配; 记录 (探针中位 log2, 匹配EV) 结点。
产物 src/pixo/render/target_offset.json 被 ExposureStage._load_cal_table()
查表取代中灰锚定/低光启发式 (结点>=3 生效)。

用法: python scripts/fit_target_offset.py RAW... [--write]
"""
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pixo.render.api import Renderer  # noqa: E402


def thumb_luma(p):
    import rawpy
    with rawpy.imread(str(p)) as raw:
        t = raw.extract_thumb()
        if t.format == rawpy.ThumbFormat.JPEG:
            bgr = cv2.imdecode(np.frombuffer(t.data, np.uint8), cv2.IMREAD_COLOR)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        else:
            rgb = np.asarray(t.data)[..., :3].copy()
    rot = {3: cv2.ROTATE_180, 6: cv2.ROTATE_90_CLOCKWISE,
           8: cv2.ROTATE_90_COUNTERCLOCKWISE}
    from pixo.meta import extract as ex
    o = int((ex(p)["capture"].get("orientation") or 1))
    if o in rot:
        rgb = cv2.rotate(rgb, rot[o])
    return float(np.median(cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[..., 0]))


def probe_med_log2(p, r):
    """与 ExposureStage._auto_ev 同域的场景中位 (线性 sRGB 亮度 log2)。"""
    from pixo.render.pipeline.context import StageContext, DOMAIN_LINEAR_CAM
    from pixo.render.core.io import decode_cfa_half, camera_neutral_wb_cached
    from pixo.render.modules.white_balance import WhiteBalanceStage
    import rawpy
    with rawpy.imread(str(p)) as raw:
        img = decode_cfa_half(raw, raw_path=p)
        ctx = StageContext(p, raw=raw, prof=r.profile, config={})
        ctx.set_image(img, DOMAIN_LINEAR_CAM)
        ctx.state["camera_wb"] = camera_neutral_wb_cached(raw, p)
    wb_stage = WhiteBalanceStage()
    wb_stage.run(ctx)  # 官方入口: 自动建 StageResult 并校验域
    lin = ctx.image
    y = 0.2126 * lin[..., 0] + 0.7152 * lin[..., 1] + 0.0722 * lin[..., 2]
    return float(np.median(np.log2(np.maximum(y, 1e-6))))


def fit_one(p, r, target_l):
    lo, hi = -4.0, 4.0
    for _ in range(7):
        mid = (lo + hi) / 2
        out = r.render_preview_full(p, long_edge=512,
                                    params={"exposure": {"mode": round(mid, 4)},
                                            "tone": {"brightness": 0.25}})
        cur = float(np.median(cv2.cvtColor(out, cv2.COLOR_RGB2LAB)[..., 0]))
        if cur < target_l:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--write"]
    write = "--write" in sys.argv
    dcp = sorted(Path(__file__).resolve().parents[1].joinpath("resources/dcp").glob("*.dcp"))[0]
    r = Renderer(dcp)
    pts = []
    for a in args:
        p = Path(a)
        tl = thumb_luma(p)
        m = probe_med_log2(p, r)
        ev = fit_one(p, r, tl)
        pts.append((m, ev))
        print(f"{p.name}: med_log2={m:+.2f} -> EV={ev:+.2f} (thumb_L={tl:.0f})")
    pts.sort()
    if write:
        out = Path("src/pixo/render/target_offset.json")
        out.write_text('{"cal_table": [' +
                       ", ".join(f"[{m:.3f}, {e:.3f}]" for m, e in pts) + ']}',
                       encoding="utf-8")
        print("wrote", out)
