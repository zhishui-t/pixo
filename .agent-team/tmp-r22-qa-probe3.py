# R22 QA 独立核验探针 3：关键落点行号/上下文
import os, re, subprocess
ROOT = r"K:\work\project\pixo"
os.chdir(ROOT)
out = []
def p(*a): out.append(" ".join(str(x) for x in a))
def L(rel):
    fp = os.path.join(ROOT, rel)
    if not os.path.exists(fp):
        return None
    return open(fp, encoding="utf-8", errors="replace").read().splitlines()
def seg(rel, a, b):
    ls = L(rel)
    p("--- %s:%d-%d ---" % (rel, a, b))
    if ls is None:
        p("   MISSING"); return
    for n in range(a, min(b, len(ls)) + 1):
        p("   %d: %s" % (n, ls[n-1].rstrip()[:150]))

seg("src/pixo/service/app.py", 286, 316)
seg("src/pixo/render/pipeline/scene_apply.py", 40, 70)
seg("src/pixo/decide/rules/tone_clarity_rules.yaml", 25, 45)
seg("src/pixo/vision/measure.py", 540, 560)
seg("src/pixo/service/runtime.py", 940, 985)

# which measurement feeds decide in loop
lp = L("src/pixo/pipeline/loop.py")
p("--- loop.py metrics_for_decide / measurement call sites ---")
for i, l in enumerate(lp, 1):
    if "metrics_for_decide" in l or "final_measurement" in l or "preview_measurement" in l:
        p("   %d: %s" % (i, l.strip()[:140]))

seg("src/pixo/render/native/src/abi.cpp", 10, 30)
seg("frontend/src/components/StyleAiPanel.tsx", 16, 26)
seg("frontend/src/api/client.ts", 135, 150)

# 9/4 report tail
ls = L(".artifacts/eval_rp_ccm_ab_nikon_z5_2_20260904_235522.md")
p("--- 9/4 report tail (last 22) ---")
for n in range(max(1, len(ls)-22), len(ls)+1):
    p("   %d: %s" % (n, ls[n-1].rstrip()[:160]))
ls2 = L(".artifacts/eval_rp_ccm_ab_nikon_z5_2_20260828_232324.md")
p("--- 8/28 report tail (last 22) ---")
for n in range(max(1, len(ls2)-22), len(ls2)+1):
    p("   %d: %s" % (n, ls2[n-1].rstrip()[:160]))

# preview_long_edge production value
for rel in ["src/pixo/service/app.py", "src/pixo/service/runtime.py"]:
    p("--- %s preview_long_edge refs ---" % rel)
    for i, l in enumerate(L(rel), 1):
        if "preview_long_edge" in l:
            p("   %d: %s" % (i, l.strip()[:140]))

# tech_debt #17 现状段与 #3 尾部
seg("docs/tech_debt.md", 126, 140)
# git show commit
try:
    r = subprocess.run(["git", "show", "--stat", "--oneline", "3fbe56d"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    p("--- git show 3fbe56d --stat ---")
    p(r.stdout[:1500])
except Exception as e:
    p("git err", e)

# model_licenses entries detail
import json
d = json.load(open("model_licenses.json", encoding="utf-8"))
for e in d["models"]:
    p("LIC name=%s publishable=%s status=%s files=%s" % (e.get("name"), e.get("publishable"), e.get("status"), e.get("files")))
v = json.load(open("src/pixo/manifests/vision_models.json", encoding="utf-8"))
for e in v["models"]:
    p("VM id=%s license=%s publishable=%s path_or_source=%s pixo_status=%s keys=%s" % (e.get("id"), e.get("license"), e.get("publishable"), e.get("path_or_source"), e.get("pixo_status"), sorted(e.keys())))

# 其他许可台账文件
p("license-ish files:", [f for f in os.listdir(".") if "licen" in f.lower() or "NOTICE" in f])
open(".agent-team/tmp-r22-qa-probe3.txt", "w", encoding="utf-8").write("\n".join(out))
print("WROTE3", len(out))
