# F13 掩码双线注入定向门禁

> 审核人：qa｜2026-09-07T01:29:25+08:00
> 对象：super-dev 交付（F13 preview/export 双线掩码通道），黑板 streams/hard-problems.md
> 基线：512bd0d（F12 已提交）+ 在飞共享树（F07 卡/依赖声明等并行流非本域）
> 方法：spike 复算 + 陷阱机制源码级验证 + loop.py 分区边界 diff 核对 + Route A/B 向后兼容推演 + 测试复跑

## 结论：**PASS**（F13 批可提交）

修复记录：**0 处**（F13 域内未发现需修复缺陷）
**升级项 1 条**（非 F13 引起，见 §7——F12 提交遗留红测试，需队长路由）

---

## 1. spike 证据链复算

- 复跑 `python .agent-team/spike/spike_f13_dual_line.py`：**五问全 PASS，输出与黑板逐行一致**
  （Q1 export 注入 OK / Q2 preview tier 对齐 / Q3 两线增益比 1.098 vs 1.094 → 漂移 0.0048 EV /
  Q4 缓存命中+失效各 1 次 / Q5 透传契约 / Q5b Route B 结构）。
- 0.0048 EV 独立复算：黑板比值取自未舍入内部值；qa 用舍入后比值复算得 ≈0.0053 EV——同数量级，
  两者均远低于 0.15 EV 门限（余量 >30 倍），结论不受舍入影响。✅

## 2. 设计级陷阱处置验证（两处均机制级实证成立）

### 陷阱① 坐标系（适配目标 = post-compose 消费帧，非入口帧）
- **同源性**：`region_masks.py:48` 导入的 `compute_crop_rect` 与 `ComposeStage.process`
  （compose.py:268 调用，定义 :63）是**同一函数对象**——预测与执行不存在双实现漂移。✅
- 三入口全部走同一适配器：`_render_full_quality`（export）/`_render_with_params`（preview）/
  `SyntheticRenderBackend._render`（合成线，不走 session 自带适配）——「三入口唯一适配点」属实。✅
- 测试钉法：`test_adapt_compose_prediction`（ratio/free 裁剪后目标帧）+
  `test_session_compose_crop_alignment`（session 级裁剪对齐）+ spike Q2「compose 1:1 裁剪对齐
  post-compose 帧 (96,96)」。✅

### 陷阱② 缓存指纹（data_ptr 透传契约）
- **机制证实**：`session.py:44 _ndarray_digest` = shape/dtype/**data_ptr** + 首末 4KB 采样——
  逐渲染新建数组确实会使指纹永变、stage 缓存永不命中，陷阱真实。✅
- **处置证实**：适配器「已 float32 且 shape 命中 → 原对象透传」（`adapt_region_masks` 透传分支）；
  loop 侧一次转换（分割点 :1156-1167）+ 三个注入点（迭代 :1125 / crop 同步 :870 / FINAL_QC :1525）
  均引用**同一批** `self._region_masks_soft` 数组对象。✅
- 测试钉法：`test_adapt_pass_through_same_object_when_aligned`（同对象）+
  `test_state_fingerprint_same_mask_object_stable`（同掩码命中）+
  `test_state_fingerprint_mask_content_change_invalidates`（变化失效）+
  `test_ndarray_digest_large_mask_middle_only_change`（大数组中部变化 ptr 兜底）。✅

## 3. loop.py 掩码区边界完整性

`git diff 512bd0d -- loop.py` 共 **7 hunks**，逐一定位：
| hunk | 位置 | 内容 |
|---|---|---|
| @@332 | SyntheticRenderBackend._render | 合成线入口适配（不走 session） |
| @@401 | RawRenderBackend.render_full | state_extras 透传（Route A 对称） |
| @@708 | SinglePhotoLoop.__init__ | `_region_masks_soft` 属性 |
| @@852 | crop 建议同步点 | 掩码随框一并粘性注入 |
| @@1103 | 迭代注入点 | 同上（同批数组） |
| @@1129 | 分割转换点 | 二值→float32 一次转换 |
| @@1488 | FINAL_QC 刷新点 | 单轮闭环补齐+幂等重放 |

**`_DOTTED_PARAM_REGISTRY`（66-72）/`_apply_decide_params`（531-568）/`_COLOR_PARAM_ALIASES` 零触碰**
（diff 内三符号 grep 计 0）；`_resize_masks`（测量二值语义）未动；modules/compose.py 未动。
dev-3 F14 注册表区改动当前未进树，无同文件冲突。✅ 边界完整

## 4. Route A/B 双路由取舍与 None 语义

| 路由 | 实现 | 向后兼容证据 |
|---|---|---|
| A（export API 增参） | `_render_full_quality(..., state_extras=None)`，入口适配后并入 state_inject | None/空不注入；`test_render_full_quality_no_extras_backward_compatible` 钉旧语义 ✅ |
| B（session 属性携带） | `RawPreviewSession.region_masks`（**缺省 None**）+ `ExportManager._run` `getattr` 转发 | 无掩码时**不传新参**（与旧调用面逐字一致，`test_export_manager_without_masks_keeps_old_call_face`）；旧键（face_boxes 等）经 `adapt_state_extras` 原样透传（无 region_masks 键时原 dict 对象返回） ✅ |

掩码不进 `canonical_params()` 的论证成立（ndarray 污染 `_param_fingerprint` 且不可 JSON 序列化，
params 面向用户配置）——独立属性通道是正确取舍。✅

## 5. 测试复跑与 e2e 门禁真实性

```
python -m pytest tests/unit/test_region_masks_channel.py -q        → 22 passed（1.18s）
邻域（黑板清单 6 文件）                                              → 96 passed（3.43s）
```
对账：黑板「邻域 118」= 96（邻域 6 文件）+ 22（通道文件）——qa 复跑 96+22=118 全绿零失败，口径吻合。✅

e2e 门禁用例真实性（逐行审读）：
- `test_backend_preview_export_same_direction`：同一 uint8 掩码，preview（下采样）vs export（全分辨率），
  带/不带掩码双基线，区域内效果 >5、区域外误伤 <3，**两线增益比 |Δlog2| < 0.15 EV**——tier 口径差
  历史教训的门禁化，真实且量化；
- `test_loop_injects_masks_preview_and_export_lines`：首轮无掩码→次轮注入，**消费点捕获**
  （_CaptureStage order=58）断言两线 shape==各自消费帧 + float32 + 方向一致 + <0.15EV；
- `test_loop_single_iteration_final_qc_still_injects`：max_iterations=1 的 FINAL_QC 补齐场景
  （首轮注入发生在分割前的时序缺口）——边界场景覆盖到位。✅

## 6. 遗留项分级核对

| 遗留项 | super-dev 定性 | qa 核验 |
|---|---|---|
| compose free-px-rect 跨分辨率失称 | 既有问题非本次引入 | ✅ `rect_norm_to_px` 在 512bd0d 已存在（:237 定义/:1428 使用），F13 diff 零触碰；建议另开条目（compose 参数归一化）合理 |
| export 线全分辨率掩码内存（24MP×float32≈96MB/prompt） | 首版可接受 | ✅ 如实记录；缓解路径（共享低分辨率+消费点上采样）已留 dev-3 主路径演进位 |
| tier EV 家族（export 线现也接收 boxes） | 闭合 preview/export box 测光口径差；无金样本路径经过 | ✅ 与 F06 复验不冲突（gate 工具路径不经该分支） |

## 7. 升级项（报队长路由，非 F13 引起）

**`tests/unit/test_build_project_graph.py::test_real_repo_graph_invariants` 在 HEAD（512bd0d）红**：
- 断言 :371 精确列表钉 DEFAULT_STAGES，index 12 diff：`'region_adjust' != 'stylize'`——
  **F12 批提交（512bd0d）遗漏的第三处机械同步**（dev-3 已同步 test_phase1_chain/test_pipeline，
  漏了 build_project_graph 工具测试；super-dev 黑板遗留 3 已如实报告并验证非 F13 引起）。
- 影响：不阻断 F13 提交，但**最终全量回归必红**（基线 1396 passed 不保）。
- 处置建议：一行机械修复（期望列表 skin 后插 `"region_adjust"`）——属 dev-3 域（F15 断言批）
  或队长热修；qa 本门禁修复边界限 F13 域，未动。**建议随 F13 批提交前一并热修，避免 HEAD 带红。**

## 8. commit 放行清单

- **F13 批**（建议整批一个 commit，或适配器+注入两批）：region_masks.py（新）+ loop.py 掩码区 7 hunks +
  session.py（Route B+预览适配）+ export.py（Route A+manager 转发）+ test_region_masks_channel.py（新，
  22 例）+ test_export.py（fake 签名 **kwargs 两处）
- 前置：§7 红测试热修建议同批或先行（队长裁决）
- 依赖序：F13 与在飞 F07/F10（films/*.json）、F17（pyproject/requirements/README）文件不相交，可并行提交；
  F14（dev-3）依赖本批的掩码通道契约（已在 F12 门禁 §4 冻结口径）

> 门禁章：qa 2026-09-07T01:29:25+08:00 — F13 PASS，零修复，两陷阱处置机制级成立；
> 升级项 1（F12 遗留红测试，建议提交前热修）。
