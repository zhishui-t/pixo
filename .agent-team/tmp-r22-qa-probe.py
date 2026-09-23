# R22 QA 独立核验探针（只读；输出重定向到文件）
import glob, json, os, re, sys
ROOT = r"K:\work\project\pixo"
os.chdir(ROOT)
out = []
def p(*a):
    out.append(" ".join(str(x) for x in a))

def readf(rel, a=None, b=None):
    fp = os.path.join(ROOT, rel)
    if not os.path.exists(fp):
        return None
    lines = open(fp, encoding="utf-8", errors="replace").read().splitlines()
    if a is None:
        return lines
    return lines[a-1:b]

# ---- P2: .cube / lut assets
cubes = [f for f in glob.glob("**/*", recursive=True) if f.lower().endswith((".cube", ".3dl", ".look"))]
p("P2 cube/3dl/look files:", len(cubes), cubes[:5])
lutdirs = [d for d in glob.glob("**/*", recursive=True) if os.path.isdir(d) and "lut" in os.path.basename(d).lower()]
p("P2 dirs named *lut*:", len(lutdirs), lutdirs[:8])
hits = []
for f in glob.glob("configs/**/*.json", recursive=True):
    try:
        t = open(f, encoding="utf-8", errors="replace").read()
    except Exception:
        continue
    if "lut_path" in t:
        hits.append(f)
p("P2 configs json with lut_path:", len(hits), hits[:5])
films = sorted(glob.glob("configs/styles/films/*.json"))
p("P2 films dir json count:", len(films))
if films:
    d = json.load(open(films[0], encoding="utf-8"))
    p("P2 sample card keys:", list(d.keys()), "stylize=", json.dumps(d.get("params", {}).get("stylize")))

# ---- P2: app.py styles endpoints
src = open("src/pixo/service/app.py", encoding="utf-8").read().splitlines()
for i, l in enumerate(src, 1):
    if "/api/styles" in l:
        p("P2 app.py:%d %s" % (i, l.strip()))
        for j in range(i, min(i+6, len(src))):
            p("     app.py:%d %s" % (j+1, src[j].strip()))

# ---- P2: frontend wiring
for rel, pat in [("frontend/src/api/client.ts", "listStyles"), ("frontend/src/store/useAppStore.ts", "fetchStyleCards"), ("frontend/src/components/StyleAiPanel.tsx", "StyleCard")]:
    fp = os.path.join(ROOT, rel)
    if not os.path.exists(fp):
        p("P2 MISSING", rel); continue
    L = open(fp, encoding="utf-8", errors="replace").read().splitlines()
    for i, l in enumerate(L, 1):
        if pat in l:
            p("P2 %s:%d %s" % (rel, i, l.strip()[:120])); break

# ---- P8: license registry
lines = readf("tests/unit/test_tech_debt_invariants.py", 85, 105)
p("P8 test_tech_debt_invariants.py:86-105")
for n, l in enumerate(lines or [], 86):
    p("   %d: %s" % (n, l))
for rel in ["model_licenses.json", "src/pixo/manifests/vision_models.json"]:
    fp = os.path.join(ROOT, rel)
    if not os.path.exists(fp):
        p("P8 MISSING", rel); continue
    d = json.load(open(fp, encoding="utf-8"))
    entries = d if isinstance(d, list) else d.get("models", d.get("entries", d))
    p("P8 %s: type=%s entries=%s topkeys=%s" % (rel, type(entries).__name__, len(entries) if hasattr(entries, "__len__") else "?", list(d.keys()) if isinstance(d, dict) else "-"))
    if isinstance(entries, list):
        for e in entries:
            if isinstance(e, dict):
                ks = [k for k in ("path", "local_path", "file", "files") if k in e]
                p("     id=%s keys=%s" % (e.get("id") or e.get("model") or e.get("name"), ks))

# ---- P4: skin tests / gate cases
L = open("tests/unit/test_skin_oklab.py", encoding="utf-8").read().splitlines()
for i, l in enumerate(L, 1):
    if "def test_skin_oklab" in l:
        p("P4 test_skin_oklab.py:%d %s" % (i, l.strip()))
g = open("tests/regression/goldens/gate_cases.py", encoding="utf-8").read().splitlines()
p("P4 gate_cases FEATURES region:")
for i, l in enumerate(g, 1):
    if "skin_oklch" in l or "FEATURES" in l:
        p("   gate_cases.py:%d %s" % (i, l.strip()[:100]))
p("P4 gate_cases 'compose' hits:", sum(1 for l in g if "compose" in l.lower()))
p("P4 gate_cases FEATURES count (approx):", len(re.findall(r'"', "".join(g[24:42]))))

# ---- P5/P7/F09: compose default + adopt_crop + region_masks
c = open("src/pixo/render/modules/compose.py", encoding="utf-8").read().splitlines()
for i, l in enumerate(c, 1):
    if '"mode"' in l or "def compute_crop_rect" in l or "def default_params" in l:
        p("F09 compose.py:%d %s" % (i, l.strip()[:120]))
lp = open("src/pixo/pipeline/loop.py", encoding="utf-8").read().splitlines()
for i, l in enumerate(lp, 1):
    if "def rect_norm_to_px" in l or "def rect_px_to_norm" in l or "def adopt_crop" in l or "def register_metric_keys" in l or "def _qc_outcome" in l:
        p("F09/loop.py:%d %s" % (i, l.strip()[:120]))
p("rect_px_to_norm call sites in src:", sum(1 for f in glob.glob("src/**/*.py", recursive=True) for l in open(f, encoding="utf-8", errors="replace") if "rect_px_to_norm" in l))
rm = open("src/pixo/render/pipeline/region_masks.py", encoding="utf-8").read().splitlines()
for i, l in enumerate(rm, 1):
    if "def _post_compose_shape" in l or "compute_crop_rect" in l:
        p("F09 region_masks.py:%d %s" % (i, l.strip()[:120]))

# ---- F01: metrics keys
m = open("src/pixo/pipeline/metrics.py", encoding="utf-8").read().splitlines()
p("F01 metrics.py:30-95")
for n, l in enumerate(m[29:95], 30):
    p("   %d: %s" % (n, l))

# ---- P7: engine all/between
e = open("src/pixo/decide/engine.py", encoding="utf-8").read().splitlines()
for i, l in enumerate(e, 1):
    if 'get("all")' in l or 'op == "between"' in l or "_QC_OVERFLOW_THRESHOLD" in l or "soft_warnings" in l:
        p("F06/F07 engine.py:%d %s" % (i, l.strip()[:120]))
for i, l in enumerate(lp, 1):
    if "soft_warnings" in l or "register_metric_keys" in l:
        p("F06 loop.py:%d %s" % (i, l.strip()[:120]))
rt = open("src/pixo/service/runtime.py", encoding="utf-8").read().splitlines()
for i, l in enumerate(rt, 1):
    if "soft_warnings" in l or "targets={}" in l:
        p("F06 runtime.py:%d %s" % (i, l.strip()[:130]))

# ---- F04: session update_params zero validation
s = open("src/pixo/render/web/session.py", encoding="utf-8").read().splitlines()
p("F04 session.py:172-182")
for n, l in enumerate(s[171:182], 172):
    p("   %d: %s" % (n, l))

# ---- #10 duplicate numbering
t = open("docs/tech_debt.md", encoding="utf-8").read().splitlines()
p("F10 tech_debt ^N. headings:")
for i, l in enumerate(t, 1):
    if re.match(r"^\d+\.\s", l):
        p("   %d: %s" % (i, l.strip()[:80]))

# ---- #17 pinned test
tr = open("tests/unit/test_region_masks_channel.py", encoding="utf-8").read().splitlines()
for i, l in enumerate(tr, 1):
    if "test_free_px_rect_cross_resolution_geometry_mismatch_recorded" in l:
        p("F09 test_region_masks_channel.py:%d %s" % (i, l.strip()))
        for n in range(i, min(i+40, len(tr))):
            p("   %d: %s" % (n+1, tr[n]))

# ---- except Exception count
cnt = 0; per = {}
for f in glob.glob("src/pixo/**/*.py", recursive=True):
    n = sum(1 for l in open(f, encoding="utf-8", errors="replace") if "except Exception" in l)
    if n:
        cnt += n; per[f] = n
p("F03 except Exception total:", cnt, sorted(per.items(), key=lambda kv: -kv[1])[:6])

open(".agent-team/tmp-r22-qa-probe.txt", "w", encoding="utf-8").write("\n".join(out))
print("WROTE", len(out), "lines")
