# R22 / Wave1 收口 / stream-1b（dev-1）—— A8 断言更新 + A10 镜像补齐 + A12 知情

- 角色：`dev-1`（开发流 1 收口）；范围：**仅** A8 / A10 / A12 三项（brief 明列）
- 工作目录：`K:\work\project\pixo`（Windows / PowerShell **5.1**）
- 上游依据：`.agent-team/design-r22.md` §7 **A8/A10/A12 授权原文**、§1 F01 行、§2.1；上一批交付报告 `.agent-team/streams/r22-stream-1.md`（R1/R7）
- 未提交 git；pytest 一律「cmd 重定向到 `.agent-team\tmp-*.txt` → `Get-Content -Encoding UTF8` 读」

---

## 0. 一句话结论

A8 两处冻结断言已按**新契约**改为**精确集合**（12 键 / 7 文件 / total=12 条，无任何放宽）；A10 镜像 `configs/rules/noise_rules.yaml` 已按**字节复制**落盘并与包内副本 sha256 相同、新增字节相等断言；A12 跨波次契约已知悉且规则 YAML 头注已写明「无执行位 ⇒ 永不生效」。**定向测试全绿：E1 14 passed（此前 2 failed）/ E2 29 passed / E3 38 passed。**

---

## 1. 授权引用（原文，design-r22 §7）

| # | 授权原文（摘） | 本次落实 |
|---|----------------|----------|
| **A8** | 「`dev-1` 可**最小改** `tests/unit/test_metrics_for_decide_public.py` 的两处冻结断言（`:160-171` 精确键集合、`:229-242` 6 文件/11 条）——它们是我方在 R21 为**当时契约**写的守卫，F01 扩容属**设计内变更**。硬要求：①必须改成**新的精确集合断言**（12 键 / 7 文件 / total=12 条），**禁止**放宽为子集或"包含式"；②改动处注明「R22 F01 扩容（design §1/§2.1）」；③stream 报告逐行给 diff 与理由；④……**这是 `tests/unit/**` 的定向授权，不改变「`tests/regression/**` 归 tester」的既有约定**」 | 见 §2 |
| **A10** | 「`configs/rules/` 是**镜像目录**（`test_decide_region_wiring.py:205` 断言镜像存在、`test_color_rules.py:79` 读镜像字节）⇒ 新增 `configs/rules/noise_rules.yaml`（与 `src/pixo/decide/rules/noise_rules.yaml` **字节一致**），并在新单测里断言镜像存在且相等。**这是本轮的定向 `configs/**` 授权（仅此一个文件）**，不改变「`configs/**` 默认禁改」」 | 见 §3 |
| **A12** | 「F01 的 `noise_luminance_rule_040` 当前**无渲染执行位**（`denoise` 不在 `DEFAULT_STAGES`、`_DOTTED_PARAM_REGISTRY` 无键）⇒ **Wave2 `super-dev` 必须登记 `denoise` stage + `denoise.luminance_strength` 参数键**，否则该规则永不生效（规则仍默认关）。此为 F02 交付的**硬性验收项**」 | 见 §4（**不改代码**，仅确认知悉） |

---

## 2. 交付物 1：A8 断言更新（精确集合，未放宽）

文件：`tests/unit/test_metrics_for_decide_public.py`（唯一 A8 目标文件）

### 2.1 逐行 diff（`git diff -- tests/unit/test_metrics_for_decide_public.py`）

```diff
diff --git a/tests/unit/test_metrics_for_decide_public.py b/tests/unit/test_metrics_for_decide_public.py
index 65282f6..b77d044 100644
--- a/tests/unit/test_metrics_for_decide_public.py
+++ b/tests/unit/test_metrics_for_decide_public.py
@@ -6,8 +6,8 @@
    dict 断言，而不是与已改成 wrapper 的 loop 函数自比）；
 2. ``metric_universe(("face", "sky", "plant"))`` 覆盖 ``region_rules.yaml``
    的 condition 与 formula 引用的**全部**键；
-3. **显式传** ``metric_keys=metric_universe(...)`` 后，6 个 ``DEFAULT_RULES``
-   文件全部 ``load_rules`` 无 ``DecideError``；
+3. **显式传** ``metric_keys=metric_universe(...)`` 后，7 个 ``DEFAULT_RULES``
+   文件全部 ``load_rules`` 无 ``DecideError``（R22 F01 扩容：+noise_rules.yaml）；
 4. ``merge_proxy_metrics`` 把 ``compute_proxy_metrics`` 三键合到 measurement
    **顶层**（非 ``global`` 下），且随后 ``metrics_for_decide`` 可见。
 
@@ -168,6 +168,10 @@ def test_metric_keys_is_flatten_fixed_set_without_region_keys():
         "colorfulness_proxy",
         "tonal_range",
         "crop_suggestion_applicable",
+        # R22 F01 扩容（design §1/§2.1）：噪声/细节 4 层展平键入键宇宙
+        # measurement["global"]["detail"]["sharpness"] → 精确集合 10→12 键
+        "noise_ratio",
+        "detail_score",
     })
     assert not any(k.startswith(("face_", "sky_", "plant_")) for k in METRIC_KEYS)
 
@@ -226,8 +230,9 @@ def test_metric_universe_follows_prompts_argument():
 
 
 def test_default_rules_load_with_explicit_metric_universe():
-    """显式传键宇宙后，6 个 DEFAULT_RULES 文件全部 load_rules 无 DecideError。"""
-    assert len(DEFAULT_RULES) == 6
+    """显式传键宇宙后，7 个 DEFAULT_RULES 文件全部 load_rules 无 DecideError。"""
+    # R22 F01 扩容（design §1/§2.1）：新增 noise_rules.yaml（默认关）⇒ 6→7 文件
+    assert len(DEFAULT_RULES) == 7
     universe = metric_universe(("face", "sky", "plant"))
 
     total = 0
@@ -238,8 +243,10 @@ def test_default_rules_load_with_explicit_metric_universe():
         per_file[Path(path).name] = len(rules)
         total += len(rules)
 
-    assert total == 11, per_file  # 6 文件 / 11 条（exploration-r21 probe2 口径）
+    # R22 F01 扩容（design §1/§2.1）：noise_luminance_rule_040 计入 ⇒ 11→12 条
+    assert total == 12, per_file  # 7 文件 / 12 条（R22 F01 增量后口径）
     assert per_file["region_rules.yaml"] == 2
+    assert per_file["noise_rules.yaml"] == 1
 
 
 # ---------------------------------------------------------------- 验收 ④ 顶层合并
```

（git 附一行 warning：`LF will be replaced by CRLF the next time Git touches it` —— 该文件在检出时即为 LF；本次编辑未引入换行风格变化，`edit` 工具只替换文本片段。）

### 2.2 逐项理由（对应 A8 硬要求 ①②③）

| 行 | 旧 | 新 | 理由 |
|----|----|----|------|
| `:9-10`（模块 docstring） | 「6 个 `DEFAULT_RULES` 文件」 | 「7 个 ……（R22 F01 扩容：+noise_rules.yaml）」 | **同一契约的第二处表述**（验收 ③ 摘要）。A8 只点名「两处断言」，但此处留着旧数字会与新断言自相矛盾；属同文件 docstring 同步，一并更正并在本报告披露（见 §6-D1） |
| `:171-174`（键集合） | 10 键 | **12 键：追加 `"noise_ratio"` / `"detail_score"`** | F01 把 `METRIC_KEYS` 10→12（`metrics.py`）。断言仍是 `METRIC_KEYS == frozenset({...})` —— **精确相等**，未改 `issubset`/`<=`/`in`。注释行固定引用「design §1/§2.1」 |
| `:232-236`（文件数 + docstring） | `len(DEFAULT_RULES) == 6`；docstring「6 个」 | `== 7`；docstring「7 个」 | `src/pixo/decide/rules/__init__.py:47` 已登记第 7 个 `noise_rules.yaml`（上一批交付）；断言必须跟上**新契约**。`== 7` 仍是精确等值 |
| `:246-247`（总条数） | `total == 11`，# 6 文件 / 11 条 | `total == 12`，# 7 文件 / 12 条 | 新 YAML 含 **1** 条规则（`noise_luminance_rule_040`）⇒ 11+1=12。新增规则**默认关**，条数计入而求值不受影响 |
| `:248`（既有 per-file 断言） | `per_file["region_rules.yaml"] == 2` | **原样保留** | A8 要求「既有断言保持」；已保持 |
| `:249`（新增 per-file 断言） | — | `per_file["noise_rules.yaml"] == 1` | **收紧而非放宽**：把「+1 条来自新文件」钉成显式断言（防未来某文件数量变化时总数仍凑巧为 12 而静默漂移）。属 A8「必须改成新的精确集合断言」的加强，披露见 §6-D2 |

**未被改动的关键冻结断言（有意保留）**：`test_public_flatten_matches_frozen_legacy_expectation`（`flat == _EXPECTED_FLAT`，`:102-111`）**仍逐键冻结 17 键旧口径**——因为 F01 新键取「缺省不写空键」语义（fixture 无 `detail` 层），既有展平口径逐键未变（上一批 E4 已实测通过，本批 E1 复跑仍通过）。

---

## 3. 交付物 2：A10 镜像补齐

### 3.1 落盘方式（字节复制，非手抄）

```powershell
python -c "from pathlib import Path; s = Path('src/pixo/decide/rules/noise_rules.yaml').read_bytes(); d = Path('configs/rules/noise_rules.yaml'); d.write_bytes(s); print('src bytes=%d  dst bytes=%d  equal=%s' % (len(s), len(d.read_bytes()), s == d.read_bytes()))"
→ src bytes=3036  dst bytes=3036  equal=True
```

- 新增文件：`configs/rules/noise_rules.yaml`（**本轮唯一 configs 授权文件**，A10）
- 内容 = `src/pixo/decide/rules/noise_rules.yaml` 的 `read_bytes()` 原样写入（零手抄、零重排）

### 3.2 新增单测断言（同既有镜像约定）

`tests/unit/test_noise_metric_keys.py:166-179`（新增，本文件属 dev-1 F01 文件域）：

```python
# ---------------------------------------------------------------- A10 双镜像

ROOT = Path(__file__).resolve().parents[2]
CONFIG_YAML = ROOT / "configs" / "rules" / "noise_rules.yaml"


def test_configs_mirror_exists_and_is_byte_identical():
    """A10（design §7）：``configs/rules/`` 是镜像目录，新规则文件必须同步。

    约定同 ``test_color_rules.py:77-81`` / ``test_decide_region_wiring.py:205``：
    镜像缺失即失败，且与包内副本**逐字节一致**（不得手抄漂移）。
    """
    assert CONFIG_YAML.exists(), "configs/rules/noise_rules.yaml 镜像缺失"
    assert CONFIG_YAML.read_bytes() == NOISE_YAML.read_bytes()
```

风格与 `test_color_rules.py:77-81`（`read_bytes()` 两侧对比）一致；`ROOT` 取 `parents[2]` 亦与 `test_color_rules.py` 同款。

### 3.3 `test_formula_guard_sunset.py` 是否受新增文件影响 → **不受影响，已绿（非空转）**

该文件的 `test_all_packs_load_via_engine_and_mirrors_in_sync`（`:81-89`）**会枚举 `configs/rules/*.yaml` 全量**（`sorted(CONFIG_DIR.glob("*.yaml"))`）并对每个文件做 ①`load_rules` 可解析 ②与 `src` 侧同名文件字节一致。新增镜像后它**必然吃到新文件**，因此我用独立探针证明它吃到了且能过（不是「文件没被扫到」的假绿）：

```
[1] 镜像存在: True | src: True
[2] 字节数: src=3036 cfg=3036 | 相等=True
[3] sha256 src=d7b7f1ca8dc814c304f9cc1a5fbb8e644684ce2262eccaa10ebd49fa3caa68b1
    sha256 cfg=d7b7f1ca8dc814c304f9cc1a5fbb8e644684ce2262eccaa10ebd49fa3caa68b1
[4] configs/rules/*.yaml 盘点 (n=7): ['color_rules.yaml', 'crop_suggest_rule_003.yaml', 'exposure_rule_001.yaml', 'highlight_protect_rule_002.yaml', 'noise_rules.yaml', 'region_rules.yaml', 'tone_clarity_rules.yaml']
[5] noise_rules.yaml 已被日落护栏枚举: True
[6] 镜像全部为 src 侧同名文件: True
[7] 宽松模式 load_rules(configs 镜像) -> n=1, enabled=False
    严格模式注册集 n=24（含 noise_ratio=True）
[8] 严格模式 load_rules(configs 镜像) -> n=1, rule_id=noise_luminance_rule_040
[9] action.formula='0.5 * (noise_ratio / 0.62 - 1.0)'
    命中守卫 token: 无
[10] condition 无 formula 键: True
[11] DEFAULT_RULES n=7 -> ['exposure_rule_001.yaml', 'highlight_protect_rule_002.yaml', 'crop_suggest_rule_003.yaml', 'tone_clarity_rules.yaml', 'color_rules.yaml', 'region_rules.yaml', 'noise_rules.yaml']
```

结论（4 条护栏口径逐项预检，与 `test_formula_guard_sunset.py` 同口径）：
- **②任务「`load_rules` 可解析」**：宽松（空注册表，`:154-155` 提前返回）与**严格**（模拟 `SinglePhotoLoop` 注册后 24 键）**两种模式都加载成功** ⇒ 不会因注册表状态差异翻红；
- **②任务「日落条款」**：`action.formula` 为纯算术，**GUARD_TOKENS 零命中**（`"<"`/`">"`/`" if "`/`" and "`/`" or "` 等 9 个 token 全不出现）；`condition` 无 `formula` 键 ⇒ `test_no_conditional_logic_in_action_formulas` / `test_no_condition_level_formula_guards` 天然通过；
- **②任务「镜像字节」**：`[3]` sha256 完全相同 ⇒ `cfg == mir` 通过。

⇒ **无需修改 `test_formula_guard_sunset.py`**（也不在授权文件域内）。上一批遗留 **R7** 由此关闭。

---

## 4. 交付物 3：A12 知情（**未改任何代码**）

### 4.1 跨波次契约确认

我**知悉并接受** A12：Wave2 `super-dev` 须在 F02 交付时登记 `denoise` stage（入 `DEFAULT_STAGES`）**与** `denoise.luminance_strength` 参数键（入 `_DOTTED_PARAM_REGISTRY`），否则 `noise_luminance_rule_040` 永不生效；这是 F02 的**硬性验收项**。本批**未触碰** `DEFAULT_STAGES` / `_DOTTED_PARAM_REGISTRY` / 任何 `render/**` 文件。

### 4.2 独立复核：「当前规则无执行位 ⇒ 永不生效」成立（只读证据）

| 环节 | 事实 | 证据 |
|------|------|------|
| ① 点分键无映射 | `_DOTTED_PARAM_REGISTRY`（`loop.py:68-74`）**只有** `tone.shadows`/`tone.highlights`/`clarity.strength`/`dehaze.strength` + 色彩别名，**无** `denoise.*` | `loop.py:68-74` |
| ② 落入 informational 兜底 | `loop._apply_decide_params` 三路分支（曝光别名 / 注册表 / `region.`）均不命中 ⇒ 走 `else`：`"." in low` 时 **WARNING「Decide 输出点分参数无执行位, 保留为顶层 informational 键」**并原样保留键 | `loop.py:778-786` |
| ③ stage 不在默认链 | `DEFAULT_STAGES`（`presets.py:15-17`）= 15 个 stage：`exposure/whitebalance/compose/huesat/tone/dehaze/clarity/colorcal/calibration/hsl/split_tone/skin/region_adjust/stylize/refine` —— **无 `denoise`** | `presets.py:15-17` |
| ④ 即便入链也是空转 | `@register_stage("denoise", order=47)`（`reshape.py:118-127`）当前是**占位**：`wants() → False`、`process() → return`；`render/params.py:37` 已注册 `"denoise": DenoiseStage` | `reshape.py:118-127`、`params.py:37` |
| ⑤ 规则默认关 | YAML `enabled: false`（唯一切实开关，design §7 A9）；`engine` 侧 `rule.get("enabled") is False: continue` | `noise_rules.yaml:34`；上一批 E2/E4 |

⇒ 「无执行位」比 A12 原文更严：**映射缺失（①②）+ 管线未入链（③）+ 入链亦 no-op（④）三重惰性**；即使有人手工把 `enabled` 改 `True`，也只会得到一条 WARNING + 一个不影响渲染的顶层 informational 键。

### 4.3 「永不生效」是否已在 YAML/docstring 写清 → **已写清（三处）**

| 位置 | 原文（摘） | 是否点明「无执行位 ⇒ 不生效」 |
|------|-----------|------------------------------|
| `src/.../noise_rules.yaml:28-32`（头注【执行位交接 / 待接线】） | 「当前 `denoise` Stage **不在** `DEFAULT_STAGES`，且 loop `_DOTTED_PARAM_REGISTRY` 无该键 ⇒ 即使显式开启，本轮也**无渲染执行位**（值会落成顶层 informational 键）。F02（W2 super-dev）落地后由队长派单登记执行位」 | ✅ 明确（含 A12 归口责任人） |
| `src/.../noise_rules.yaml:10-16`（头注【闭环内不生效 · 有意为之】） | 「闭环 decide 只吃 preview measurement …… 阈值按**全幅**标定 ⇒ 在闭环 preview 口径下不可用，故 `enabled: false` 默认关」 | ✅ 明确（闭环面不生效的**另一条**理由，与 A12 的执行位缺失互补） |
| `src/.../decide/rules/__init__.py:42-46`（登记处注释） | 「噪声规则（**默认 enabled: false**）：阈值只在**导出全幅**口径标定 …… 闭环 decide 只吃 preview (preview_long_edge 缺省 1024) ⇒ 本规则闭环内不生效、生产零影响」 | ✅ 明确（装配侧入口即可见） |

⇒ A12 的「永不生效」这一事实**已在规则 YAML 头注与登记处注释写清**，Wave2 `super-dev` 打开该 YAML 即见「待接线」交接说明；无需本批补文档（也无可写的文件域）。

---

## 5. 验收证据（brief 4 条，逐条对应）

> 本机 PS 5.1：`>` 重定向默认 UTF-16LE；一律 `cmd /c "set PYTHONIOENCODING=utf-8&&python -m pytest ... > .agent-team\tmp-*.txt 2>&1"` 再 `Get-Content -Encoding UTF8`。

### E1 `test_metrics_for_decide_public.py` → **0 failed**（此前 2 failed）
```
cmd /c "set PYTHONIOENCODING=utf-8&&python -m pytest tests/unit/test_metrics_for_decide_public.py -q --color=no > .agent-team\tmp-r22b-pytest-e1.txt 2>&1"
→ ..............                                                           [100%]
→ 14 passed in 1.25s
```
存档：`.agent-team/tmp-r22b-pytest-e1.txt`。**对照**：上一批同命令 = `2 failed, 12 passed`，失败即 `test_metric_keys_is_flatten_fixed_set_without_region_keys`（Extra items: `noise_ratio`/`detail_score`）与 `test_default_rules_load_with_explicit_metric_universe`（`assert 7 == 6`）。两条均已按新契约转绿。

### E2 `test_noise_metric_keys.py` + `test_qc_soft_warnings.py` → **29 passed**（≥28）
```
cmd /c "set PYTHONIOENCODING=utf-8&&python -m pytest tests/unit/test_noise_metric_keys.py tests/unit/test_qc_soft_warnings.py -q --color=no > .agent-team\tmp-r22b-pytest-e2.txt 2>&1"
→ .............................                                            [100%]
→ 29 passed in 2.20s
```
存档：`.agent-team/tmp-r22b-pytest-e2.txt`。**= 上一批 28 passed + 本批新增镜像用例（`test_configs_mirror_exists_and_is_byte_identical`）1 条**。

### E3 镜像既有约定三文件 → **全绿 38 passed**
```
cmd /c "set PYTHONIOENCODING=utf-8&&python -m pytest tests/unit/test_decide_region_wiring.py tests/unit/test_color_rules.py tests/unit/test_formula_guard_sunset.py -q --color=no > .agent-team\tmp-r22b-pytest-e3.txt 2>&1"
→ ......................................                                   [100%]
→ 38 passed in 1.68s
```
存档：`.agent-team/tmp-r22b-pytest-e3.txt`。含 `test_decide_region_wiring.py:205/214`（镜像存在 + 字节一致）、`test_color_rules.py:77-81`（镜像字节）、`test_formula_guard_sunset.py:81-89`（**全量枚举含新文件** + 字节一致 + 可加载 + 日落条款）。

### E4 镜像字节相等的手工核验（独立于测试的两种工具链）

命令 1（Python 字节比较 + sha256，探针 `.agent-team/tmp-r22b-verify.py`）：
```
[2] 字节数: src=3036 cfg=3036 | 相等=True
[3] sha256 src=d7b7f1ca8dc814c304f9cc1a5fbb8e644684ce2262eccaa10ebd49fa3caa68b1
    sha256 cfg=d7b7f1ca8dc814c304f9cc1a5fbb8e644684ce2262eccaa10ebd49fa3caa68b1
```
命令 2（PowerShell 独立哈希 + 长度）：
```
Get-FileHash src\pixo\decide\rules\noise_rules.yaml, configs\rules\noise_rules.yaml -Algorithm SHA256 | Format-Table -AutoSize
→ SHA256  D7B7F1CA8DC814C304F9CC1A5FBB8E644684CE2262ECCAA10EBD49FA3CAA68B1  ...\src\pixo\decide\rules\noise_rules.yaml
→ SHA256  D7B7F1CA8DC814C304F9CC1A5FBB8E644684CE2262ECCAA10EBD49FA3CAA68B1  ...\configs\rules\noise_rules.yaml

Get-Item src\pixo\decide\rules\noise_rules.yaml, configs\rules\noise_rules.yaml | Select-Object FullName,Length | Format-Table -AutoSize
→ ...\src\pixo\decide\rules\noise_rules.yaml     3036
→ ...\configs\rules\noise_rules.yaml             3036
```
存档：`.agent-team/tmp-r22b-verify-out.txt`。两种独立工具链给出**同一 sha256**。

### E5 文件域核对（授权边界）
```
git status --porcelain   → 本批改动仅 3 项（其余为 dev-2 / 上一批遗留）：
 M tests/unit/test_metrics_for_decide_public.py          ← A8（授权）
?? configs/rules/noise_rules.yaml                        ← A10（唯一 configs 授权文件）
?? tests/unit/test_noise_metric_keys.py                  ← 上一批新建，本批仅追加 1 个镜像用例
```
本批**未触碰**：`tests/regression/**`、`frontend/**`、`src/**`、其余 `configs/**`、`DEFAULT_STAGES`/`_DOTTED_PARAM_REGISTRY`。

---

## 6. 与 brief 的偏差（逐条披露）

| # | 偏差 | 理由 |
|---|------|------|
| **D1** | 除 A8 点名的「两处断言」外，同步改了**模块 docstring `:9-10`** 的「6 个文件」→「7 个文件」 | 同属验收 ③ 的契约表述；不改则同一文件内新旧数字自相矛盾（`:9` 说 6 个、`:233` 说 7 个）。属同文件 docstring 同步，无行为影响 |
| **D2** | 在 `test_default_rules_load_with_explicit_metric_universe` 中**新增** `assert per_file["noise_rules.yaml"] == 1`（A8 未点名） | **收紧**而非放宽：把总量 +1 的来源钉死到新文件，防「总量凑巧等于 12」的静默漂移。既有 `per_file["region_rules.yaml"] == 2` 原样保留 |
| **D3** | 新增单测 1 条，故 E2 = **29** passed（brief 表述「28+ passed」） | 由 A10「并在新单测里断言镜像存在且相等」直接要求；28+1=29，符合「28+」口径 |

无功能代码改动；无「放宽断言」；无跨文件域改动。

---

## 7. 遗留问题（范围外，仅记录，未动手）

| # | 遗留 | 状态 |
|---|------|------|
| **L1** | **A12 执行位**：`denoise` 未入 `DEFAULT_STAGES`、`_DOTTED_PARAM_REGISTRY` 无 `denoise.luminance_strength`；且 `DenoiseStage`（`reshape.py:118-127`）目前是 `wants()→False` 的**空占位** | **Wave2 `super-dev` F02 硬性验收项**（design §7 A12）。本批已知情、未改 |
| **L2** | 规则级 **env 开启机制**不存在（唯一开关 = YAML `enabled`） | 上一批 R2（design §7 A9 已登记遗留，涉 `load_rules`/`evaluate_rules`，超本轮域） |
| **L3** | 噪声阈值**闭环内不可用**（只按全幅标定；闭环只吃 preview 1024） | 上一批 R4；design §2.1 / §7 A6 已认可，无需本轮处理 |
| **L4** | 软告警**色彩轴 tier 混用**（值取全幅渲染语义、阈值取 512 语料分位） | 上一批 R5/D6；需 QA 知晓，后续用「渲染后全幅」语料重标定 |
| **L5** | 标定语料边界：26 张 = **内嵌相机 JPEG 全幅**（非 RAW 全幅渲染链），高低 ISO 的 `noise_ratio` 分布重叠 ⇒ 0.62 是保守零误触线而非判别切分 | 上一批 R6；真实链全幅标定另开专项（预算/串行约束见 design §5） |
| **L6** | `build/lib/pixo/**` 旧副本漂移（tech_debt #25） | 上一批 R8；F10（dev-2）域，本批未处置 |
| —— | 上一批 **R1**（2 处冻结断言）→ **本批关闭**；上一批 **R7**（configs 镜像缺失）→ **本批关闭** | 见 §2 / §3 |

---

## 8. 交接要点（给 tester / QA-checker / 队长）

1. **R1/R7 已销账**：`tests/unit/test_metrics_for_decide_public.py` 2 failed → **0 failed**；`configs/rules/` 镜像已补齐并有两处独立断言（新单测 + `test_formula_guard_sunset` 全量枚举）。
2. **全量回归预期**：Wave1 dev-1 面（F01+F06）应无红；若仍见 `test_metrics_for_decide_public.py` 失败，请核对是否取到**本批版本**（`METRIC_KEYS` 断言应为 12 键、`len(DEFAULT_RULES) == 7`）。
3. **门禁相关**：新规则 `enabled: false` ⇒ `evaluate_rules` 不产出该 `rule_id`，`rule_ids` 集合预期不变；`test_formula_guard_sunset.py` 已确认吃下新文件且全绿。
4. **不要**在本批之后继续增改 `configs/rules/`（A10 授权仅 `noise_rules.yaml` 一个文件）；Wave2 若改 `src` 侧 `noise_rules.yaml`（例如接线后改阈值），**必须同步镜像**，否则 `test_formula_guard_sunset.py:81-89` 与新单测会红。
5. 证据存档：`.agent-team/tmp-r22b-pytest-e1.txt`、`tmp-r22b-pytest-e2.txt`、`tmp-r22b-pytest-e3.txt`、`tmp-r22b-verify-out.txt`、`tmp-r22b-diff-a8.txt`、`tmp-r22b-git-status.txt`、`tmp-r22b-verify.py`。
