"""拟合场景自适应曝光标定表 target_offset.json (二维 med×wb_B)。

对每张 RAW: 用相机内嵌缩略图亮度为真值, 二分搜索 exposure.mode 数值 EV,
使全链渲染的 gamma 中位亮度与之匹配; 记录 (探针中位 log2, 蓝绿比 wb_B,
匹配EV) 三元结点。wb_B = camera_neutral_wb[2]/wb[1] (G=1 归一后的 B/G),
区分同亮度下的钨丝灯/日光场景。
产物 src/pixo/render/target_offset.json 为 {"cal_table": [[m, wb_B, ev],
...], "probe_hi": [[m, wb_B, p99], ...]} 按 (m, wb) 排序; cal_table 由
ExposureStage._load_cal_table() 加载, _cal_ev() 先按 med 主键插值、
med 相近(±0.3)邻域内再按 wb_B 二次插值。probe_hi 记录各样本探针
(与 _auto_ev 同域的线性 sRGB 亮度) p99 分位, 供高光预算 (tech_debt#9)
标定域分析, loader 忽略未知键不阻塞。

用法: python scripts/fit_target_offset.py RAW... [--write]
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from pixo.render.api import Renderer  # noqa: E402


def thumb_stats(p):
    """相机缩略图的 (中位L, 均值L)。均值含高光压缩信息, 是主匹配目标。"""
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
    L = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)[..., 0]
    return float(np.median(L)), float(L.mean())


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


def probe_p99(p, r):
    """与 _auto_ev 同域 (_probe_linear_srgb 线性 sRGB 探针) 的 p99 分位。"""
    import rawpy
    from pixo.render.pipeline.context import StageContext, DOMAIN_LINEAR_CAM
    from pixo.render.core.io import decode_cfa_half, camera_neutral_wb_cached
    import pixo.render.modules.exposure as em
    with rawpy.imread(str(p)) as raw:
        img = decode_cfa_half(raw, raw_path=p)
        ctx = StageContext(p, raw=raw, prof=r.profile, config={})
        ctx.set_image(img, DOMAIN_LINEAR_CAM)
        ctx.state["camera_wb"] = camera_neutral_wb_cached(raw, str(p))
        y = em._probe_linear_srgb(ctx, ctx.image)
    return float(np.percentile(y, 99.0))


def scene_wb_b(p):
    """场景白平衡蓝绿比 wb[2]/wb[1] (As Shot, G=1 归一); 与 _auto_ev 同源。"""
    from pixo.render.core.io import camera_neutral_wb_cached
    import rawpy
    with rawpy.imread(str(p)) as raw:
        wb = camera_neutral_wb_cached(raw, str(p))
    return float(wb[2]) / max(float(wb[1]), 1e-9)


HIGHLIGHT_CLIP_MEASURE_EDGE = 1024  # 与 ab_vs_camera_thumb 同分辨率度量
HIGHLIGHT_CLIP_BUDGET_PCT = 2.3     # 绝对预算下限: 验收线 2.5 留余量
CAM_CLIP_RELATIVE = 1.10            # 相机相对余量: 我们 ≤ 相机clip×1.10
# 目标 = max(下限, 相机clip×相对余量)。相机缩略图是高光容忍真值:
# 高调场景相机本就大幅裁切(厦门0847 实测 17.9%), 绝对硬预算会迫使
# 均值匹配点被拖暗数步复刻欠曝(t73 教训); 以相机为锚自然分层。


def _clip_hi_pct(img):
    return float((img.max(axis=2) >= 250).mean()) * 100


def cam_thumb_rgb(p):
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
    return rgb


def cam_clip_pct(p):
    """相机内嵌缩略图 clip_hi (%) —— 高光容忍真值。"""
    return _clip_hi_pct(cam_thumb_rgb(p))


def fit_one(p, r, target_mean_l):
    """均值亮度匹配 + 高光裁切预算兜底 (tech_debt#9)。

    主目标: 渲染 gamma Lab **均值**对齐相机缩略图 —— 相机为保高光压低
    曝光的决策直接体现在其均值里 (高光被压缩则均值更低), 匹配均值即
    隐式继承该决策; 中位匹配在高调平顶场景会把整段亮部顶进滚降肩部
    (0355 案例, dL+8.9/clip 3.68%)。A/B 的 dL 验收口径同为均值。

    兜底: 均值匹配后若 1024px (与验收同分辨率) 实测 clip_hi 仍超预算,
    按 0.03EV 步进压低至多 8 步。
    """
    lo, hi = -4.0, 4.0

    def render_at(ev, edge):
        return r.render_preview_full(p, long_edge=edge,
                                     params={"exposure": {"mode": round(ev, 4)},
                                             "tone": {"brightness": 0.25}})

    for _ in range(7):
        mid = (lo + hi) / 2
        cur = float(cv2.cvtColor(render_at(mid, 512),
                                 cv2.COLOR_RGB2LAB)[..., 0].mean())
        if cur < target_mean_l:
            lo = mid
        else:
            hi = mid
    ev = (lo + hi) / 2
    clip = _clip_hi_pct(render_at(ev, HIGHLIGHT_CLIP_MEASURE_EDGE))
    # 目标 = max(绝对预算, 相机clip×相对余量): 高调大裁切场景由相机锚定
    # 放宽(防欠曝), 低裁切场景维持均值匹配不动(防相机对齐过度压暗)。
    target = max(HIGHLIGHT_CLIP_BUDGET_PCT,
                 cam_clip_pct(p) * CAM_CLIP_RELATIVE)
    for _ in range(8):
        if clip <= target:
            break
        ev -= 0.03
        clip = _clip_hi_pct(render_at(ev, HIGHLIGHT_CLIP_MEASURE_EDGE))
    print(f"    clip_hi@{HIGHLIGHT_CLIP_MEASURE_EDGE}px={clip:.2f}% "
          f"(target {target:.2f}%) @ EV={ev:+.2f}")
    return ev


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--write"]
    write = "--write" in sys.argv
    dcp = sorted(Path(__file__).resolve().parents[1].joinpath("resources/dcp").glob("*.dcp"))[0]
    r = Renderer(dcp)
    pts = []
    his = []
    for a in args:
        p = Path(a)
        _, tl_mean = thumb_stats(p)
        m = probe_med_log2(p, r)
        wbb = scene_wb_b(p)
        p99 = probe_p99(p, r)
        ev = fit_one(p, r, tl_mean)
        pts.append((m, wbb, ev))
        his.append((m, wbb, p99))
        print(f"{p.name}: med_log2={m:+.2f} wb_B={wbb:.3f} p99={p99:.4f} "
              f"-> EV={ev:+.2f} (thumb_meanL={tl_mean:.1f})")
    pts.sort()
    his.sort()
    if write:
        out = Path("src/pixo/render/target_offset.json")
        out.write_text(json.dumps(
            {"cal_table": [[round(m, 3), round(w, 3), round(e, 3)]
                           for m, w, e in pts],
             "probe_hi": [[round(m, 3), round(w, 3), round(v, 5)]
                          for m, w, v in his]},
            ensure_ascii=False), encoding="utf-8")
        print("wrote", out)
