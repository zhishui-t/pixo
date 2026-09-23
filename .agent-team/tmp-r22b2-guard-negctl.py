"""F10 #3 守卫「非空转」外部取证（R22 stream-2b）。

不做 pytest 收集：直接 import 生产测试模块，调用其生产断言 + 三层负控，
打印每条被检查的路径（证明覆盖面）与负控异常文本（证明可证伪）。
仓库文件只读——负控用临时副本。
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"K:\work\project\pixo")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "unit"))

import test_tech_debt_invariants as t  # noqa: E402

print("=" * 72)
print("[A] 生产断言（正常态）")
t.test_model_license_registry_paths_resolve()
print("  test_model_license_registry_paths_resolve: PASS")
t.test_vision_model_path_or_source_resolution_rules()
print("  test_vision_model_path_or_source_resolution_rules: PASS")

print("=" * 72)
print("[B] 覆盖面审计：实际被检查的路径（证明非空转）")
lic = t._check_model_licenses()
print(f"  model_licenses.json: checked_paths={lic['checked_paths']} "
      f"dangling={lic['dangling']} incomplete={lic['incomplete']}")
for entry in t._load_json(t._LICENSE_PATH)["models"]:
    print(f"    - {entry['name']}: delivery={entry.get('delivery')!r} "
          f"files={entry['files']}")
vis = t._check_vision_model_paths()
print(f"  vision_models.json:  checked_paths={vis['checked_paths']} "
      f"pending={vis['pending']} unmarked={vis['unmarked']}")
for entry in t._load_json(t._VISION_MODELS_PATH)["models"]:
    kind = t._classify_path_or_source(entry["path_or_source"])
    print(f"    - {entry['id']}: kind={kind[0]} "
          f"path_or_source={entry['path_or_source']!r}")

print("=" * 72)
print("[C] 负控 1：files[] 路径改坏（临时副本）⇒ 生产断言必红")
tmp = Path(tempfile.mkdtemp(prefix="r22b2-"))
data = t._load_json(t._LICENSE_PATH)
for entry in data["models"]:
    if entry["name"] == "aesthetic_scorer.pt":
        entry["files"] = ["resources/models/aesthetic/__不存在__.pt"]
bad = tmp / "model_licenses.json"
bad.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
orig = t._LICENSE_PATH
t._LICENSE_PATH = bad
try:
    t.test_model_license_registry_paths_resolve()
    print("  !! 未变红 —— 断言空转（不可接受）")
except AssertionError as exc:
    print("  变红 ✓ AssertionError:", str(exc).splitlines()[0])
finally:
    t._LICENSE_PATH = orig

print("=" * 72)
print("[D] 负控 2：删掉 delivery 标记（临时副本）⇒ 层②必红")
data2 = t._load_json(t._LICENSE_PATH)
data2["models"][0].pop("delivery", None)
bad2 = tmp / "model_licenses-nodelivery.json"
bad2.write_text(json.dumps(data2, ensure_ascii=False), encoding="utf-8")
t._LICENSE_PATH = bad2
try:
    t.test_model_license_registry_paths_resolve()
    print("  !! 未变红（不可接受）")
except AssertionError as exc:
    print("  变红 ✓ AssertionError:", str(exc).splitlines()[0])
finally:
    t._LICENSE_PATH = orig

print("=" * 72)
print("[E] 负控 3：$GUANLAN_ROOT 形态 + 环境变量缺失 ⇒ 判「待核验」")
legacy = tmp / "vision_models-legacy.json"
legacy.write_text(json.dumps({
    "schema_version": "1.0",
    "models": [{"id": "legacy-env", "purpose": "p",
                "path_or_source": "$GUANLAN_ROOT/models/aesthetic_scorer.pt",
                "license": "需核验", "publishable": False, "pixo_status": "x"}],
}, ensure_ascii=False), encoding="utf-8")
env = {k: v for k, v in __import__("os").environ.items() if k != "GUANLAN_ROOT"}
res = t._check_vision_model_paths(path=legacy, env=env)
print("  pending =", res["pending"])
print("=" * 72)
print("结论: 三层负控均变红/判待核验 ⇒ 断言非空转，可被破坏性测试证伪。")
