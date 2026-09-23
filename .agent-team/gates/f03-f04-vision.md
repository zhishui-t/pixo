# F03+F04 清债流联合定向门禁（vision 域）

> 审核人：qa｜2026-09-07T01:22:45+08:00（2026-09-06T17:22:45Z）
> 对象：stream-1 交付（F03 FairFace 移除 + F04 gsam 移除），dev-1 黑板 streams/stream-1.md
> 基线树：f357b35 + Wave1 并行流共享工作树（金样本 regen/F12/F13 改动在场但不属本门禁域）
> 方法：设计删除面逐项比对 + 全仓 grep + 兜底语义契约边界推演 + 下游联动只读核对 + 定向测试复跑

## 结论：**PASS**（分批 commit 放行依据——F03/F04 两批可提交）

修复记录：**0 处**（未发现需修复缺陷；观察项 2 条见 §6，不阻断）

---

## 1. F03 FairFace 移除审核

| 审核项 | 证据 | 结论 |
|---|---|---|
| 全仓零活引用 | `grep -ri fairface src/ tests/ configs/`：唯一命中 `test_vision_manifests.py` 的 `assert "fairface-onnx" not in ids`（否定断言本体）；src/configs 零命中 | ✅ |
| 防复活断言在位 | `test_vision_models_no_unused_entries`（test_vision_manifests.py:33）：fairface-onnx 与 t110 YOLOE 移除同列 not-in 清单——「清单只留实际接入模型」强不变量 | ✅ |
| 删除面 vs 设计逐项 | person.py 整删（-206 行）；health.py 去 import+fairface_info+3 键；`__init__.py` 去 L47 导入+`__all__` 三符号；vision_models.json 删 fairface-onnx 条目+updated 日期；三测试文件清理；GOVERNANCE 去 PIXO_FAIRFACE_MODEL——与 design.md F03 节逐行一致 | ✅ |
| health 聚合行为 | `vision_health()` models dict 现 8 键（无 fairface/fairface_age）、顶层无 fairface；全仓 grep 无 `health["fairface"]` 类消费方残留；`test_vision_health_includes_new_models` 断言面已同步（aesthetic/horizon） | ✅ |
| graphify 派生缓存 | person.py 的 AST 缓存已删（否则 grep src/ 出陈旧命中）——dev-1 处置正确 | ✅ |

## 2. F04 gsam 移除审核（重点：兜底语义变更）

| 审核项 | 证据 | 结论 |
|---|---|---|
| 全仓零活引用 | `grep -rni "gsam\|grounded_sam" src/ tests/ configs/`：src/configs 零命中；tests/ 5 命中全为防复活断言本体（`test_grounded_sam_removed` :257 含 hasattr 缺席+importlib 反导入抛 ImportError；`assert "gsam" not in routed_backend_names()` :315）——与 t110「零活引用（防复活断言除外）」同口径 | ✅ |
| **契约边界 A：纯未知 prompt 不上抛** | multi_router.segment() 分组时 `route is None → continue`，未知 prompt 落函数末尾既有兜底：零掩码 + warn-once（键 `missing:{p}`）+ **不记 last_degraded**；新用例 `test_all_unknown_prompts_zero_mask_no_raise` 钉死该新语义 | ✅ |
| **契约边界 B：真实后端全败仍上抛** | `unavailable and set(unavailable) == set(groups)` 逻辑零改动（groups 空时自然短路不触发）；`test_single_group_unavailable_raises` 改用真实 down 假件（uniface 抛 SegmenterUnavailable）钉「单组全败上抛」——比旧版（依赖 gsam 禁用道具）更贴近契约本体，质量提升 | ✅ |
| exceptions.py 契约保留 | 「部分组失败→零掩码+每 backend 一次 warning+last_degraded」「全部组不可用→上抛升级 manual_review」「非可用性异常 best-effort 降级」三段语义在重写后逐字有效（模块 docstring 同步重写） | ✅ |
| 4 后端路由零改动 | ROUTE_TABLE 常量区零 diff；`test_route_table`/`test_routing_and_mask_contract` 断言 face→uniface、person→rfdetr、sky→segformer 投递不变+未知 prompt 不投递任何后端；合规门控三用例（默认门控/ALLOW_RESTRICTED 放行/真实注册表）断言面不变 | ✅ |
| route_of 公共 API 变更 | 签名 `str → str \| None`；仓内唯一外部消费者是测试（已同步）；`DEFAULT_ROUTE` 无任何导入者（grep 证实） | ✅ |
| extras 保留（qa 设计修订点） | pyproject `pixo-vision-models` 零改动；全仓无「gsam 专属」安装措辞（grep 无命中）；台账条目 15 载明保留证据链（segformer/uniface/sapiens `_load()` 直接懒 import + aesthetic CLIP + rfdetr pip 链） | ✅ |
| 登记文件 | model_licenses.json 删 gsam 条目（尾逗号已修）；models_reference.json 去 "/gsam"；三份编辑 JSON `json.load` 复验合法 | ✅ |

## 3. loop 侧联动核对（只读，未动 loop.py）

- **升级路径完好**：loop.py:1153-1157 `except SegmenterUnavailable → sm.escalate("分割模型不可用") → stop "segmenter_unavailable"` 原样在位，服务真实后端故障。
- **新语义下游自洽**：纯未知 prompt 现走零掩码（旧：gsam 禁用→上抛升级）。零掩码下游降级链已核：
  `measure.py:466-478` 空 mask → `reliable: False`、`mean_luminance: None`、不抛异常 →
  loop `_metrics_for_decide` 展平 `<name>_reliable=False` → decide 规则不消费假零值。
- **判定：loop.py 无需联动修改**（该语义变化属设计 F04 明示项+风险表登记项，dev-1 台账/测试已钉死；
  loop 全量回归由队长统一执行覆盖）。
- 备注：loop.py 当前树上的改动为 super-dev F13 掩码通道（:1158-1167 region_masks 适配），非本门禁域，不评。

## 4. 台账（tech_debt 条目 14/15）一致性

| 条目 | 核对 | 结论 |
|---|---|---|
| 14 FairFace 移除 | 措辞与实测一致；引用的防复活断言 `test_vision_models_no_unused_entries` 真实存在（:33）；「历史评审文档不改写」与 design 一致 | ✅ |
| 15 gsam 移除 | 兜底语义描述与 multi_router 实现逐点对应；extras 保留段与 qa 抽查事实一致（含文件:行号）；引用断言 `test_grounded_sam_removed` 真实存在（:257） | ✅ |

## 5. 定向测试复跑

```
python -m pytest tests/unit/test_multimodel_segmenter.py tests/unit/test_vision_router_semantics.py \
  tests/unit/test_sapiens_body.py tests/unit/test_vision_extras.py tests/unit/test_vision_manifests.py \
  tests/unit/test_vision_segmenter.py tests/unit/test_vision_measure.py tests/unit/test_learned_isolation.py \
  tests/unit/test_model_licenses.py tests/unit/test_tech_debt_invariants.py tests/unit/test_service_runtime_fixes.py -q
```
**107 passed, 2 skipped（10.66s）**——与队长预期口径逐数一致。
2 skip = `test_learned_isolation.py:48`（learned/ 未建预铺门）+ `test_sapiens_body.py:267`（无本地权重），
均为 F02 基线已核良性项，非本批新增。

## 6. 观察项（不阻断，供队长知悉）

1. **零掩码 warn 文案微瑕**：未知 prompt 走既有尾部兜底，warning 文案为「prompt 无后端返回」
   （实情是「无路由后端可投递」）——语义可达、断言已钉，纯文案层面，不值得为此扩 diff（记此备查）。
2. **docs/PROJECT_GRAPH.md 与 docs/project_graph*.json 仍有 fairface/gsam 字样**：graphify 派生
   文档，dev-1 已在 stream-1.md 遗留项登记；建议随本轮或下轮工具重跑刷新，队长定时机。

## 7. 放行清单（供分批 commit）

- F03 批：person.py 删 + health/`__init__`/vision_models.json + 三测试 + GOVERNANCE（FAIRFACE 行）+ tech_debt 条目 14
- F04 批：grounded_sam.py 删 + multi_router + segmenters/`__init__` + model_licenses/models_reference + 三测试 + GOVERNANCE（GSAM 行）+ tech_debt 条目 15
- 共享树并行流文件（loop.py/render 域/金样本 regen/changelog 等）不属本门禁，归属切分按 stream 报告提示由队长执行

> 门禁章：qa 2026-09-07T01:22:45+08:00 — F03 PASS / F04 PASS / 联合 PASS，零修复，loop 联动无问题。
