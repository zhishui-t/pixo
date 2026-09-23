# stream-1 报告（dev-1 · 清债流）— F03 FairFace 彻底移除

> 2026-09-07 完成。范围：仅 F03（F04 gsam 未动）。文件域：src/pixo/vision/** + design.md F03 明示的 manifest/tests/docs 落点。

## 做了什么

按 design.md §2 F03 删除面清单逐项执行，删除 FairFace 年龄/性别模型全部运行时代码、清单条目、测试与 env 示例：

1. **删整文件** `src/pixo/vision/person.py`（FairFaceAge / PIXO_FAIRFACE_MODEL / get_fairface_age / fairface_health_info，-206 行）
2. **`src/pixo/vision/health.py`**：去 L15 `from .person import fairface_health_info`；去 L168 `fairface_info = _safe_health(...)`；去 models dict 的 `fairface`/`fairface_age` 两键（原 L187-188）；去顶层 `fairface` 键（原 L195）
3. **`src/pixo/vision/__init__.py`**：去 L47 person 导入行；去 `__all__` 三符号（FairFaceAge/get_fairface_age/fairface_health_info）
4. **`src/pixo/manifests/vision_models.json`**：删 fairface-onnx 条目（原 L30-41，注意修正了前一条目尾逗号保持 JSON 合法）；`updated` 字段同步为 2026-09-07（该字段无测试断言，校验器只查 schema_version）
5. **测试**：
   - `tests/unit/test_vision_extras.py`：去 FairFaceAge import + importable 断言；删 `test_fairface_missing_model_degrades` 整用例；`test_vision_health_includes_new_models` 的 key 元组去 "fairface" + 文件头 docstring 更新
   - `tests/unit/test_vision_router_semantics.py`：删「5. FairFace 懒加载」节三用例（construction/lazy_load/health singleton，原 L252-287）+ 文件头 docstring 该行 + `import pixo.vision.person as person_mod`（已无其他使用者）
   - `tests/unit/test_vision_manifests.py`：原 L19 `assert "fairface-onnx" in ids` 删除；防复活断言 `assert "fairface-onnx" not in ids` 落位到既有 `test_vision_models_no_unused_entries`（沿 t110 移除 YOLOE 的断言位惯例，语义正确于"只保留实际接入模型"用例）
6. **文档** `docs/LEARNED_BACKEND_GOVERNANCE.md`：§1.1 表「选择/覆写」行 env 示例去 `PIXO_FAIRFACE_MODEL`（其余示例均现存于代码）
7. **台账** `docs/tech_debt.md`：新增条目 14 记录 FairFace 移除事实（历史评审文档 PIXO_LICENSE_REVIEW.md 等按 design 不改写历史）
8. **缓存清理**：删 `src/pixo/.graphify/cache/ast/7331776800325e0a77ac3fd58d9705325689055e701a2a436e5dddeb12fe5f18.json`——person.py 的 graphify AST 派生缓存（gitignored、未跟踪、随源删除即陈旧），不清会让 `grep -ri fairface src/` 出陈旧命中

## 改了哪些文件

| 文件 | 变更 |
|---|---|
| `src/pixo/vision/person.py` | 删除（整文件） |
| `src/pixo/vision/health.py` | -5 行（import + fairface_info 变量 + 3 个键） |
| `src/pixo/vision/__init__.py` | -4 行（导入 + __all__ 三符号） |
| `src/pixo/manifests/vision_models.json` | 删 fairface-onnx 条目 + updated 日期 |
| `tests/unit/test_vision_extras.py` | 删 1 用例 + import/断言/docstring 清理 |
| `tests/unit/test_vision_router_semantics.py` | 删 3 用例 + person_mod import + docstring 行（-40 行） |
| `tests/unit/test_vision_manifests.py` | in→not in（落位到 no_unused_entries 用例） |
| `docs/LEARNED_BACKEND_GOVERNANCE.md` | env 示例去 PIXO_FAIRFACE_MODEL |
| `docs/tech_debt.md` | 新增条目 14（移除事实记录） |
| `src/pixo/.graphify/cache/...json` | 删陈旧派生缓存（gitignored，不入 diff） |

注意：`git status` 中 `.gitignore`(+3) 与 `docs/changelog.md`(+203) 的未提交改动**非本流所为**（Wave1 并行共享工作树，writer/其他流产物），本流未触碰。

## 如何验证

**命令 1 — 完成标准 grep**：
```
grep -rin "fairface" src/ tests/ configs/
```
输出仅 1 行：`tests\unit\test_vision_manifests.py:38:    assert "fairface-onnx" not in ids`
即**零活引用**；唯一命中是 design 明示要求的 not-in 防复活断言（与「grep 零命中」字面冲突，按任务书「零活引用」口径处置，与 t110 YOLOE 移除后 tests 中保留 yoloe not-in 断言同惯例）。src/ 与 configs/ 零命中。

**命令 2 — vision 域定向测试**：
```
python -m pytest tests/unit/test_vision_extras.py tests/unit/test_vision_router_semantics.py tests/unit/test_vision_manifests.py tests/unit/test_vision_segmenter.py tests/unit/test_vision_measure.py tests/unit/test_learned_isolation.py tests/unit/test_model_licenses.py tests/unit/test_tech_debt_invariants.py tests/unit/test_service_runtime_fixes.py -q
```
输出：**82 passed, 1 skipped**（含 vision_health 结构断言、manifests 校验、防复活台账断言、service 层 vision_health 消费方）。

**命令 3 — 悬空引用排查**：`grep -rn "vision\.person\|from \.person\|person_mod" src/ tests/`（排除 .graphify）零命中；`pixo.vision` 包导入正常（全部 vision 测试 collect+pass 佐证）。

## 遗留问题

1. **docs/ 下历史残留（范围外，不改）**：`docs/PIXO_LICENSE_REVIEW.md`、`docs/PIXO_ARCH_ALIGN_REVIEW.md`、`docs/project_graph*.json`、`docs/PROJECT_GRAPH.md`、`.artifacts/stage3_first_verdict.md` 仍有 fairface 字样——均为历史/派生文档，design 明示不改写历史；其中 project_graph*.json 疑似 graphify 生成物，若工具重跑会自行刷新，是否重生成留队长定。
2. **L27 示例行仍有 `PIXO_GSAM_SAM`**：F04 移除 gsam 时需同步处理（design F04 节已列治理文档更新项）。（F04 已处理，见下）
3. **共享工作树脏区**：`.gitignore`、`docs/changelog.md` 有并行流未提交改动，队长分批 commit 时注意归属切分。

---

# F04 gsam 彻底移除（同日接续完成）

## 做了什么

1. **删整文件** `src/pixo/vision/segmenters/grounded_sam.py`（GroundedSAMSegmenter / PIXO_GSAM_ENABLED / PIXO_GSAM_DINO / PIXO_GSAM_SAM）
2. **`multi_router.py` 兜底语义重设计**（4 后端路由行为零改动）：
   - 删 `DEFAULT_ROUTE = "gsam"` 与 `_get()` gsam 分支
   - `route_of`/`_route_of` 未命中返回 `None`（原返回 "gsam"）
   - `segment()` 分组时 `route is None` 的未知 prompt 不入组，落函数末尾**既有**的「prompt 无后端返回 → 零掩码 + warn-once（`missing:{p}` 键）」兜底——与禁用后端同语义，守 exceptions.py 降级契约
   - **语义边界钉死**：纯未知 prompt 请求 → 全零掩码 + warn，不上抛（路由未命中≠模型错误，不升级 manual_review）；真实后端全败仍上抛 SegmenterUnavailable（`unavailable and set(unavailable) == set(groups)` 逻辑未动，groups 为空时自然短路）
   - `routed_backend_names()` 去掉 `| {DEFAULT_ROUTE}`；docstring/warmup docstring 去 gsam 括注（`enabled()` 跳过预热逻辑保留——通用契约）
   - 模块 docstring 路由/降级语义两节重写
3. **`segmenters/__init__.py`**：`__all__`、懒加载 mapping、模块 docstring 三处去 GroundedSAMSegmenter
4. **`model_licenses.json`**：删 grounding-dino-tiny + sam-vit-base 条目（原 L56-65，尾逗号已修）；**`resources/models/models_reference.json`** L7 去 "/gsam"
5. **extras 保留证据链**（qa 修订点①）：`pyproject.toml` 的 `pixo-vision-models`（torch/transformers）**未动**——非 gsam 专用：`segformer_scenes.py:47-48`、`uniface_face.py:40-41`、`sapiens_body.py:171-172` 的 `_load()` 直接懒 import torch+transformers；`aesthetic.py:149-151`（CLIP 评分器）同；rfdetr 走 rfdetr pip 包自带 torch 链。全仓未发现把该 extras 描述为 gsam 专属的安装说明措辞（README/docs/pyproject grep 无命中），无需清理
6. **测试重写（非删除）**：
   - `test_multimodel_segmenter.py`：`test_route_table` 未知 prompt 断言 `== "gsam"` → `is None`；`test_routing_and_mask_contract` 改「未知 prompt 不投递任何后端 + 零掩码」；`test_unknown_prompt_degrades_to_zero_mask` 改「未知 prompt 零掩码 + warn-once + 不记 last_degraded」（warn-once 键 `missing:{p}`）；`test_single_group_unavailable_raises` 改用真实 down 假件（uniface）钉「单组后端全败仍上抛」契约；**新增** `test_all_unknown_prompts_zero_mask_no_raise` 钉「纯未知 prompt 不上抛」新语义；warmup 两用例去 gsam 道具
   - `test_vision_router_semantics.py`：`test_gsam_disabled_by_default` 改写为 `test_grounded_sam_removed` 防复活断言（`hasattr` 缺席 + `importlib.import_module` 抛 ImportError）；`test_warmup_skips_disabled_gsam` 改写为 `test_warmup_skips_disabled_backend`（假件钉 enabled() 跳过逻辑）；门控两用例断言改 `is None` / 去 gsam；文件头 docstring 更新
   - `test_sapiens_body.py`：`test_unknown_prompt_zero_mask_degrade` 去 PIXO_GSAM_ENABLED 道具，语义注释更新
7. **文档** `docs/LEARNED_BACKEND_GOVERNANCE.md`：§1.1 表 ENABLED 行——全库 grep 证实移除后**无任何存活 `PIXO_*_ENABLED` 开关**，如实标注「暂无在用实例」（PIXO_SEGMENTER 非 ENABLED 类，不宜伪例）；§1.1 MODEL 行去 `PIXO_GSAM_SAM`；§1.2 去 gsam 短路括注
8. **台账** `docs/tech_debt.md`：新增条目 15（gsam 移除事实 + extras 保留证据）
9. **缓存清理**：删 graphify 派生缓存 3 个（grounded_sam/multi_router 的 ast JSON + stat-index，gitignored 未跟踪），否则 grep src/ 出陈旧命中

## 改了哪些文件

| 文件 | 变更 |
|---|---|
| `src/pixo/vision/segmenters/grounded_sam.py` | 删除（整文件） |
| `src/pixo/vision/segmenters/multi_router.py` | 兜底语义重设计（docstring/DEFAULT_ROUTE/route_of/_route_of/segment 分组/routed_backend_names/_get/warmup 注释） |
| `src/pixo/vision/segmenters/__init__.py` | 去导出三处 |
| `model_licenses.json` | 删 grounding-dino+sam 条目 |
| `resources/models/models_reference.json` | 描述去 gsam |
| `tests/unit/test_multimodel_segmenter.py` | 6 用例重写/清理 + 1 新增 |
| `tests/unit/test_vision_router_semantics.py` | 3 用例重写 + 2 断言修订 + docstring |
| `tests/unit/test_sapiens_body.py` | 1 用例道具清理 |
| `docs/LEARNED_BACKEND_GOVERNANCE.md` | 三处示例/措辞更新 |
| `docs/tech_debt.md` | 新增条目 15 |
| `src/pixo/.graphify/cache/*`（3 个） | 删陈旧派生缓存（不入 diff） |

工作树另见大量并行流改动（goldens npy/manifest、loop.py、params.py、presets.py、export.py、session.py、render/modules/__init__.py、test_pipeline.py、test_phase1_chain.py、test_export.py 等）——**均非本流所为**（dev-2/dev-3/super-dev/qa Wave1 共享树），本流未触碰。

## 如何验证

**命令 1 — 完成标准 grep**：
```
grep -rin "gsam\|grounded_sam" src/ tests/ configs/
```
**src/ 与 configs/ 零命中**；tests/ 仅 5 处命中且全部为防复活断言本体（`test_grounded_sam_removed` 函数名/docstring/importlib 反导入路径 + `assert "gsam" not in routed_backend_names()` + 文件头指向防复活测试的 docstring），符合「零活引用（防复活断言除外）」口径。

**命令 2 — vision+router 域定向测试**：
```
python -m pytest tests/unit/test_multimodel_segmenter.py tests/unit/test_vision_router_semantics.py tests/unit/test_sapiens_body.py tests/unit/test_vision_extras.py tests/unit/test_vision_manifests.py tests/unit/test_vision_segmenter.py tests/unit/test_vision_measure.py tests/unit/test_learned_isolation.py tests/unit/test_model_licenses.py tests/unit/test_tech_debt_invariants.py tests/unit/test_service_runtime_fixes.py -q
```
输出：**107 passed, 2 skipped**（含 4 后端路由契约、降级/上抛边界、健康聚合、合规门控、防复活台账断言、service 层 vision_health 消费方）。

**命令 3 — JSON 合法性**：三份编辑过的 JSON（model_licenses / models_reference / vision_models）`json.load` 全通过。

**命令 4 — 无其他消费者**：`grep -rn "DEFAULT_ROUTE\|route_of\|ROUTE_TABLE" src/ tests/` 确认 DEFAULT_ROUTE 无外部导入者；models_reference.json 无测试消费方。

## 遗留问题（F04）

1. **loop 侧 manual_review 路径回归**（design 风险表要求确认项）：「纯未知 prompt」行为由 SegmenterUnavailable 升级改为零掩码后，loop 捕获 SegmenterUnavailable → manual_review 的路径本身未动且测试绿（test_pipeline 域由队长全量回归统一覆盖）；本流定向测试已钉 multi_router 侧新语义。
2. **`enabled()` 门控目前无真实适配器使用**（gsam 是唯一实现者）：warmup 的 enabled() 跳过分支保留为通用契约（假件钉死）；未来新 opt-in 后端按治理文档 §1.1 ENABLED 类命名即可。
3. **共享工作树**：并行流脏文件清单见上表下方说明，commit 归属切分留队长。

---

# F05 lr_baseline float 化处置（调查+建议，队长裁决）

> 2026-09-07 完成。结论=**记债（c）**，台账条目 16 已落 `docs/tech_debt.md`。未动任何 refine/native 代码。

## 启用面证据（逐链核实，文件:行）

1. **`resources/dcp/manifest.json` 自身无运行时读者**：`default_lr_preset`/`lr_baseline` 在 src/pixo **零代码引用**（全仓 grep）；该 manifest 仅被 `scripts/gen_project_graph_frontend.py:315-317`（项目文档图生成器）提及——它是 profile 拟合战役的 camera→preset 登记表，不是渲染配置。
2. **lr_baseline.json 不在任何生产加载面**：运行时风格卡体系 = `configs/styles/films/*.json`（`know/cards.py:28-39 _default_films_dir`）+ 内置 `DEFAULT_STYLE_CARDS`（`know/cards.py:147`）；lr_baseline 两者皆不在。web/session（`session.py:345` config 来自 decide/patch）、`render/api.py`（`render_preview` 只读 `preview_fast.json`，:113-115）、`build_default_pipeline`（`presets.py:15` DEFAULT_STAGES 默认参数）均不触及。
3. **默认链 warm_sat 短路**：`refine.py:180-184` default_params `warm_sat_curve/warm_sat_spot/warm_hue_curve = None` → `apply_warm_sat_gamma`（`refine.py:102-103`）直接返回原图。gate 金样本（4 features 默认路径）、预览、导出全走默认链 → **warm HSV u8 往返在生产零发生**。
4. **胶片卡零启用**：全 `configs/styles/` 带 warm_sat 曲线的仅 `lr_baseline.json` 与 `lr_camera_standard_baseline.json` 两张 LR 基线复刻卡；23 张胶片卡（dev-2 域）无一启用。
5. **当前唯一消费者 = 测量脚本**：`scripts/measure_u8_precision.py:75`（PRESET_C）——W4 的 0.57~0.90 ΔE76 数据来源（`docs/metrics/u8_midpoint_precision.md:10-11`：「lr_baseline 预设启用且门控命中时」），可复跑验证。
6. **对 native spike 的关键事实**：u8 native 内核 `warm_sat_gamma_u8` **已存在**（`refine.py:140-142` → `_native/__init__.py:1141`），与 Python LUT 回退共享同一 u8 HSV 域——量化误差源于入口 float→u8（`refine.py:111`），**不在算子实现**。「native 化」已完成且不构成清偿。

## 决策建议：c) 记债（已落台账条目 16）

- **a) float 化不做的理由**：t109 先例（3925b69，native F32 内核 + Python float 镜像 + golden 重生成）成本不小，而收益（回收 0.57~0.90 ΔE）当前仅存在于测量脚本路径——为无生产消费者的预设付改造代价，投入产出不成立。
- **b) native 化是伪选项**：见证据 6，native 已在位且不解决量化 ΔE；super-dev spike（`.agent-team/streams/hard-problems.md` 截至本报告落盘尚未产出）若给出 float native 方案，实质与 a) 合流，届时按清偿条件复核。
- **c) 记债成立**：潜在代价非现状缺陷；台账条目写明清偿条件（lr_baseline 接入生产风格卡体系 / 16bit 导出战役重启）与唯一有效路径（float 化，沿 3925b69 模式）。
- 若队长裁决改 a)：方案与工作量 = F32 native 内核（借 colorcal.cpp ApplyColorCalLabF32 模式）+ Python float 镜像（保持逐位一致的 H/S smoothstep 权重数学）+ 金样本基线重生成 + W4 复测；预估一个专项批次（super-dev 主刀），本流不动手。

## 改了哪些文件

| 文件 | 变更 |
|---|---|
| `docs/tech_debt.md` | 新增条目 16（记债 + 清偿条件） |
| `.agent-team/streams/stream-1.md` | 本节 |

（未动任何 src/tests/configs——调查型任务，零代码改动。）

## 遗留问题（F05）

1. super-dev warm_sat native spike 结论（hard-problems.md）落盘后，建议 qa 总审时对照本条复核方向一致性（预计同向：float 才是唯一有效路径）。
2. `resources/dcp/manifest.json` 与两张 lr_*_baseline 预设处于「有登记、无读者」状态——是否保留作战役记录、或在发布合规包（F16/F17）中声明为非运行时资产，留队长/裁。


