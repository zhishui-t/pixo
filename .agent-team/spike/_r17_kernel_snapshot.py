# r17 参数化零漂移实证 (临时): 固定语料 × 固定参数 → 内核输出快照/对拍。
# 用法: python .agent-team/spike/_r17_kernel_snapshot.py save   (改造前, DLL 1.5.0)
#       python .agent-team/spike/_r17_kernel_snapshot.py check  (改造后, DLL 1.6.0)
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import cv2  # noqa: E402

from pixo.render import _native as native  # noqa: E402

OUT = Path(__file__).resolve().parent / "_r17_kernel_ref.npz"

rng = np.random.default_rng(20260907)
imgs = [rng.uniform(0.0, 1.0, size=(40, 40, 3)).astype(np.float32),
        np.clip(rng.uniform(-0.1, 1.1, size=(40, 40, 3)), None, None).astype(np.float32)]
wbs_params = [
    dict(saturation=0.2, vibrance=0.15, hueDeg=5.0, neutralA=0.6, neutralB=-0.4,
         neutralSigma=9.0, skinProtect=0.7, skinTrimA=-2.0, skinTrimB=-4.0),
    dict(skinProtect=0.7),
    dict(skinTrimA=2.0, skinTrimB=-3.5, skinProtect=0.3),
]

outputs = []
for img in imgs:
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    for kw in wbs_params:
        p = native.PixoRenderColorCalParams(**kw)
        outputs.append(native.colorcal_apply_lab_f32_oklch(lab, img, p))

if sys.argv[1] == "save":
    np.savez(OUT, *outputs)
    print(f"[save] {len(outputs)} kernel 输出入快照 (DLL {native.version()})")
else:
    ref = np.load(OUT)
    assert len(ref.files) == len(outputs)
    bad = 0
    for i, (a, b) in enumerate(zip(ref.files, outputs)):
        if not np.array_equal(ref[a], b):
            bad += 1
            print(f"[FAIL] 输出 {i} 不逐位一致")
    print(f"[check] DLL {native.version()}: {'PASS — 逐位零漂移' if bad == 0 else f'FAIL {bad}'}")
    sys.exit(0 if bad == 0 else 1)
