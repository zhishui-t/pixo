# r10 perf 验收 (临时脚本, 结论回收后可删): hsv vs oklch native 内核/stage 级。
import sys
import time

sys.path.insert(0, "src")
import ctypes

import cv2
import numpy as np

from pixo.render import _native as native
from pixo.render.modules.color_cal import ColorCalStage
from pixo.render.pipeline.graph import DOMAIN_GAMMA_RGB, StageContext


def med(f, n=11):
    f(); f()
    ts = []
    for _ in range(n):
        t0 = time.perf_counter(); f(); ts.append(time.perf_counter() - t0)
    return float(np.median(ts)) * 1e3


rng = np.random.default_rng(20260907)
img = rng.uniform(0.0, 1.0, size=(512, 512, 3)).astype(np.float32)
lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
ca = np.asarray([0.5, 1, 2, 1.5, 0, -1, -0.5], np.float32)
cap = ca.ctypes.data_as(ctypes.POINTER(ctypes.c_float))
p = native.PixoRenderColorCalParams(
    saturation=0.2, vibrance=0.15, hueDeg=5.0, neutralA=0.6, neutralB=-0.4,
    neutralSigma=9.0, skinProtect=0.7, skinTrimA=-2.0, skinTrimB=-4.0, curveA=cap)

k_hsv = med(lambda: native.colorcal_apply_lab_f32(lab, p))
k_ok = med(lambda: native.colorcal_apply_lab_f32_oklch(lab, img, p))
k_ok_maskonly = med(lambda: native.colorcal_apply_lab_f32_oklch(
    lab, img, native.PixoRenderColorCalParams(skinProtect=0.7)))
print(f"kernel hsv        : {k_hsv:6.2f} ms")
print(f"kernel oklch      : {k_ok:6.2f} ms  (delta {k_ok - k_hsv:.2f} = mask 成本)")
print(f"kernel oklch gain-only (mask+gain): {k_ok_maskonly:6.2f} ms")


def bench_stage(domain):
    stage = ColorCalStage()
    cfg = {"stages": {"colorcal": {
        "color_domain": domain,
        "saturation": 0.2, "vibrance": 0.15, "hue": 5.0,
        "neutral_a": 0.6, "neutral_b": -0.4, "neutral_mode": "static",
        "skin_protect": 0.7, "skin_trim": [-2.0, -4.0], "gamut_soft": 0.5}}}

    def run():
        ctx = StageContext("x.NEF", config=cfg)
        ctx.set_image(img, DOMAIN_GAMMA_RGB)
        stage.run(ctx)
        return ctx.image
    return med(run)


s_hsv = bench_stage("hsv")
s_ok = bench_stage("oklch")
native._lib = None
native._load_error = "x"
s_okpy = bench_stage("oklch")
print(f"stage hsv native  : {s_hsv:6.2f} ms")
print(f"stage oklch native: {s_ok:6.2f} ms  ({s_ok / s_hsv:.2f}x hsv)")
print(f"stage oklch python: {s_okpy:6.2f} ms  ({s_okpy / s_ok:.1f}x 慢于 native, "
      f"回收 {s_okpy / s_hsv:.1f}x->{s_ok / s_hsv:.2f}x)")
