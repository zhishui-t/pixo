# R22 QA 独立复核 P3：噪声指标的分辨率依赖与排序单调性
import os, sys
ROOT = r"K:\work\project\pixo"
os.chdir(ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))
out = []
def p(*a): out.append(" ".join(str(x) for x in a))
try:
    import numpy as np, cv2, rawpy
    from pixo.vision.measure import measure_sharpness
except Exception as e:
    open(".agent-team/tmp-r22-qa-probe5.txt", "w", encoding="utf-8").write("IMPORT FAIL: %r" % (e,))
    print("IMPORT FAIL", e); raise SystemExit(0)

RAW = r"K:\data\photo\0711\raw"
targets = ["DSC_5314", "DSC_5278", "DSC_5236", "DSC_5241"]
p("rawpy", rawpy.__version__, "cv2", cv2.__version__)
rows = []
for name in targets:
    fp = os.path.join(RAW, name + ".NEF")
    if not os.path.exists(fp):
        p("MISSING", fp); continue
    with rawpy.imread(fp) as raw:
        thumb = raw.extract_thumb()
    if thumb.format == rawpy.ThumbFormat.JPEG:
        img = cv2.imdecode(np.frombuffer(thumb.data, np.uint8), cv2.IMREAD_COLOR)
    else:
        img = thumb.data
    if img is None:
        p("decode fail", name); continue
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = img.shape[:2]
    p("%s thumb=%dx%d" % (name, w, h))
    for le in (512, 1024, 2048, 0):
        if le == 0:
            cur = img
        else:
            s = le / max(h, w)
            cur = cv2.resize(img, (int(round(w*s)), int(round(h*s))), interpolation=cv2.INTER_AREA)
        m = measure_sharpness(cur)
        rows.append((name, le or max(h, w), m["noise_ratio"], m["detail_score"]))
p("")
p("%-12s %8s %12s %14s" % ("photo", "long_edge", "noise_ratio", "detail_score"))
for r in rows:
    p("%-12s %8d %12.4f %14.2f" % r)
# monotonicity check at 512 tier
by = {}
for name, le, nr, ds in rows:
    by.setdefault(le, []).append((name, nr))
for le in sorted(by):
    seq = by[le]
    p("tier %d noise_ratio order: %s" % (le, ", ".join("%s=%.4f" % x for x in seq)))
open(".agent-team/tmp-r22-qa-probe5.txt", "w", encoding="utf-8").write("\n".join(out))
print("WROTE5", len(out))
