# R22 QA 独立核验探针 4：decide 口径 / style cards 既有接线 / 未覆盖引用
import os, re, glob
ROOT = r"K:\work\project\pixo"
os.chdir(ROOT)
out = []
def p(*a): out.append(" ".join(str(x) for x in a))
def L(rel):
    fp = os.path.join(ROOT, rel)
    return open(fp, encoding="utf-8", errors="replace").read().splitlines() if os.path.exists(fp) else None
def seg(rel, a, b):
    ls = L(rel); p("--- %s:%d-%d ---" % (rel, a, b))
    if ls is None: p("   MISSING"); return
    for n in range(a, min(b, len(ls)) + 1):
        p("   %d: %s" % (n, ls[n-1].rstrip()[:150]))

seg("src/pixo/pipeline/loop.py", 1340, 1380)
seg("src/pixo/pipeline/loop.py", 755, 800)
# where is measurement computed (preview vs final)?
lp2 = L("src/pixo/pipeline/loop.py")
for i, l in enumerate(lp2, 1):
    if re.search(r"measure\(|measurement =|measurement:", l):
        p("MEAS loop.py:%d %s" % (i, l.strip()[:140]))
# enable_style_cards
p("--- enable_style_cards refs ---")
for f in glob.glob("src/**/*.py", recursive=True) + glob.glob("frontend/src/**/*.ts*", recursive=True):
    for i, l in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
        if "enable_style_cards" in l or "style_card" in l.lower():
            p("   %s:%d %s" % (f, i, l.strip()[:140]))
# free px hardcodes in tests
p("--- tests free px hardcodes ---")
for f in glob.glob("tests/**/*.py", recursive=True):
    for i, l in enumerate(open(f, encoding="utf-8", errors="replace"), 1):
        if re.search(r'"mode":\s*"free"', l) or re.search(r"'mode':\s*'free'", l) or "mode=\"free\"" in l:
            p("   %s:%d %s" % (f, i, l.strip()[:130]))
# docs legacy crop sample
p("--- docs 架构设计文档.md:380-396 ---")
seg("docs/架构设计文档.md", 380, 396)
# metrics for decide which measurement in service path
seg("src/pixo/service/runtime.py", 620, 680)
open(".agent-team/tmp-r22-qa-probe4.txt", "w", encoding="utf-8").write("\n".join(out))
print("WROTE4", len(out))
