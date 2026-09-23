# R22 QA 独立核验探针 2：行号与耦合面
import glob, json, os, re
ROOT = r"K:\work\project\pixo"
os.chdir(ROOT)
out = []
def p(*a): out.append(" ".join(str(x) for x in a))
def L(rel): return open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace").read().splitlines()

def show(rel, pats, label=""):
    for i, l in enumerate(L(rel), 1):
        for pat in pats:
            if re.search(pat, l):
                p("%s %s:%d %s" % (label, rel, i, l.strip()[:130])); break

show("src/pixo/pipeline/loop.py", [r"adopt", r"_full_canvas_size", r"def _compose_fingerprint"], "LOOP")
show("src/pixo/service/runtime.py", [r"preview_long_edge", r"SinglePhotoLoop\(", r"aesthetic", r"crop_suggest", r'"soft_warnings"|soft_warnings', r"payload = "], "RT")
show("src/pixo/decide/engine.py", [r"soft_warnings", r"def qc_rollback"], "ENG")
show("src/pixo/render/pipeline/presets.py", [r"DEFAULT_STAGES"], "PRESET")
show("src/pixo/decide/rules/__init__.py", [r"DEFAULT_RULES"], "RULES")
show("src/pixo/vision/measure.py", [r"noise_ratio|detail_score", r"def measure_sharpness"], "MEAS")
show("src/pixo/render/modules/reshape.py", [r"class DenoiseStage", r"class SharpenStage", r"def wants"], "RESHAPE")
show("src/pixo/render/core/lut.py", [r"def load_lut_path", r"guanlan"], "LUT")
show("frontend/src/store/useAppStore.ts", [r"fetchStyleCards", r"setStyleCards", r"patchParam"], "STORE")
show("frontend/src/components/StyleAiPanel.tsx", [r"export function|export default", r"linear-gradient", r"onClick"], "PANEL")

# docs dir listing (F04 user doc owner)
p("DOCS files:", sorted(os.listdir("docs"))[:40])
# rules dir
p("RULES YAML:", sorted(os.path.basename(x) for x in glob.glob("src/pixo/decide/rules/*")))
# tech_debt #3 段
td = L("docs/tech_debt.md")
p("--- tech_debt 83-92 (#3) ---")
for n in range(83, 93): p("   %d: %s" % (n, td[n-1].strip()[:150]))
p("--- tech_debt 156-160 (#12) ---")
for n in range(156, 161): p("   %d: %s" % (n, td[n-1].strip()[:150]))
p("--- tech_debt 24 ---")
p("   24: %s" % td[23].strip()[:200])
p("--- tech_debt 240-264 (#17) ---")
for n in range(240, 265): p("   %d: %s" % (n, td[n-1].strip()[:140]))
# #25 in qa-report-r21 §7
qr = L(".agent-team/qa-report-r21.md")
for i, l in enumerate(qr, 1):
    if "25" in l and ("build/lib" in l or "旧" in l or "漂移" in l):
        p("QAR21:%d %s" % (i, l.strip()[:160]))
# goldens baseline / gate features count
gc = L("tests/regression/goldens/gate_cases.py")
p("FEATURES lines 25-42:")
for n in range(25, 43): p("   %d: %s" % (n, gc[n-1].strip()[:150]))
# R21 red line / baseline
p("golden baseline files:", sorted(os.path.basename(x) for x in glob.glob("tests/regression/goldens/*"))[:20])
# pytest count reference
for rel in [".agent-team/qa-report-r21.md", ".agent-team/DELIVERY-R21.md"]:
    for i, l in enumerate(L(rel), 1):
        if "1574" in l or "passed" in l.lower():
            p("%s:%d %s" % (rel, i, l.strip()[:150]))
open(".agent-team/tmp-r22-qa-probe2.txt", "w", encoding="utf-8").write("\n".join(out))
print("WROTE2", len(out))
