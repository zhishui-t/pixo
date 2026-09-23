# streams/hard-problems.md — super-dev 攻坚流

> F13 掩码通道 preview/export 双线注入。执笔 2026-09-07。

## 1. spike 问题定义

**核心问题**：preview 线掩码走 state_extras（loop.py 合成后端 / RawRenderBackend.render_preview → session.py 注入 ctx.state），export 线（`RawRenderBackend.render_full` → `_render_full_quality`）**完全不带 state_extras**——preview 有区域效果、导出没有。要回答：

- Q1 export 线注入哪条路通：export API 增参（Route A）还是 session 状态携带（Route B）？
- Q2 掩码能否以消费契约形态（`ctx.state["region_masks"]` = prompt→float32 0..1）到达 order=57 消费点，且 shape 与**消费帧**一致（compose order=22 会中途裁剪改画幅）？
- Q3 同一掩码 preview（下采样）/export（上采样）两线区域效果方向+量级一致（tier EV 口径差历史教训门禁）？
- Q4 掩码进 state 后缓存指纹行为：同掩码命中 / 掩码变化失效（`_ndarray_digest` 含 data_ptr，大数组只采样首末 4KB）？
- Q5 适配器逐渲染新建数组会不会打崩 session stage 缓存命中？

## 2. 试了什么

spike 脚本 `/.agent-team/spike/spike_f13_dual_line.py`（**临时产物，可删**）：
- export 线用真 `run_full_pipeline(state_inject=...)`（`_render_full_quality` 的实际委托目标）+ 真 region_adjust（dev-3 F12 已在树，直接当真实消费方验证契约）；
- preview 线用真 `RawPreviewSession`（rawpy/decode/camera_wb 假件，integration 惯例）；
- 候选适配器内联（后提取为 `src/pixo/render/pipeline/region_masks.py`）；
- 缓存行为用真 session stage cache + 真 `_state_fingerprint`/`_ndarray_digest`。

期间发现的两个**设计级陷阱**（spike 价值所在）：
1. **坐标系陷阱**：masks_cache 来自对已渲染 preview 的分割 → 天然是 compose 后坐标。若把掩码适配到渲染**入口** shape，compose 裁剪（ratio/free）后在 order=57 消费点 shape 失配且几何错位（crop ≠ resize）。→ 适配目标必须用 `compute_crop_rect` 预测 **post-compose 帧**。
2. **缓存指纹陷阱**：`_ndarray_digest` 含 `data_ptr`。若入口每渲染都重采样/重转换掩码 → 每次新数组 → 指纹永变 → session stage 缓存永不命中。→ 适配器在「已 float32 且 shape 命中」时必须**原对象透传**；loop 侧一次转换、反复注入同一批数组。

## 3. 结论证据（命令 + 输出）

命令：`python .agent-team/spike/spike_f13_dual_line.py`

```
  [Q1] export 线注入 OK: region_adjust 消费 region_masks, 掩码 shape=(480, 640) 消费帧一致, dtype float32, applied=['sky']
  [Q3] export 线效果: 区域内 Δ=+16.2 (ratio 1.094, 期望≈2^(0.5/2.2)=1.171), 区域外 Δ=-0.04
  [Q2] preview 线注入 OK: tier=(96, 128), 掩码 shape=(96, 128) 对齐消费帧, applied=['sky']
  [Q3] preview 线效果: 区域内 Δ=+16.7 (ratio 1.098), 区域外 Δ=+0.15
  [Q3] 两线增益比: preview 1.098 vs export 1.094 → EV 口径漂移 0.0048 EV
  [Q2] compose 1:1 裁剪: 掩码对齐 post-compose 帧 (96, 96)
  [Q4] stage 缓存: 首渲染探针 1 次, 同掩码复渲染后仍 1 (命中), 换掩码后 1 次新增 (失效)
  [Q5] 透传契约 OK: 对齐时同对象; 失配时重采样
  [Q5b] Route B 结构可行: session 属性携带 + manager 转发
结论: 全部路线可行
```

**取舍结论（Route A vs B）**：两者**互补而非二选一**，都落了——
- Route A（export API 增参 `_render_full_quality(..., state_extras=)`）：loop 驱动的 FINAL_QC 导出线，与 `render_preview` 的 state_extras 透传模式完全对称，runner 层 `state_inject` 早已支持，纯签名透传。
- Route B（session 状态携带 `RawPreviewSession.region_masks` 属性 + `ExportManager` 转发）：web 服务导出线。**证据：掩码绝不能进 `canonical_params()`**——ndarray 会污染 `_param_fingerprint`（json 序列化 ndarray 得到不稳定字符串）且 params 面向用户配置；独立属性通道 + manager `getattr(session, "region_masks", None)` 转发是唯一干净路径（无掩码时不传新参，旧调用面逐位不变）。

## 4. 最终实现说明

### 改动文件
| 文件 | 改动 |
|------|------|
| `src/pixo/render/pipeline/region_masks.py` | **新增** 140 行：共享适配器 `adapt_region_masks` / `adapt_state_extras`（三入口唯一适配点） |
| `src/pixo/pipeline/loop.py` | +59/-? 行，**仅 backend/state_extras 掩码区**：① 分割后一次性转软掩码存 `self._region_masks_soft`；② 迭代注入点/crop 建议同步点/FINAL_QC 刷新点三处把掩码并入 state_extras（同一批数组对象反复注入→缓存稳定）；③ `SyntheticRenderBackend._render` 入口适配（合成线不走 session）；④ `RawRenderBackend.render_full` 透传 state_extras |
| `src/pixo/render/web/session.py` | `region_masks` 属性（Route B）+ `_render_with_params` 里 state_extras 的掩码适配到本渲染消费帧（pipe 构建前移一行，无行为差） |
| `src/pixo/render/web/export.py` | `_render_full_quality` 增参 `state_extras`（None 不注入，旧语义不变）；`ExportManager._run` 无掩码时不传新参 |
| `tests/integration/test_export.py` | 2 个 fake 签名加 `**kwargs`（配合新调用面） |
| `tests/unit/test_region_masks_channel.py` | **新增** 22 个测试 |

**未碰**：`_DOTTED_PARAM_REGISTRY` / `_apply_decide_params`（dev-3 域）、`_resize_masks`（测量二值语义原样）、modules/compose.py。

### 数据流（最终形态）
```
masks_cache (uint8 0/255, 首轮 preview 帧)
  └─ loop 分割点: adapt_region_masks(masks_cache) → self._region_masks_soft  (float32, 一次)
      ├─ 迭代注入点/crop 同步点: backend.state_extras = {**boxes, "region_masks": soft}
      │    ├─ preview: session 适配到 tier post-compose 帧 → 透传(命中) → ctx.state
      │    └─ full:    _render_full_quality 适配到全分辨率 post-compose 帧 → ctx.state
      └─ FINAL_QC 刷新点: 幂等重放（单轮闭环兜底）
```

### 测试证据
- `python -m pytest tests/unit/test_region_masks_channel.py -q` → **22 passed**：
  - 适配器 8 项（归一/上下采样/透传同对象/compose 预测/free 全幅/HxWx1/坏掩码跳过/extras 透传）
  - 缓存指纹 3 项（内容变化失效 / 大数组仅中部变化 ptr 兜底 / 同对象稳定）
  - session 4 项（tier 适配 / 同掩码命中+变化失效 / Route B 属性 / compose 裁剪对齐）
  - export 4 项（全分辨率注入+效果 / None 不注入向后兼容 / manager 转发同批数组 / 无掩码旧调用面）
  - e2e 3 项（backend 两线方向一致+漂移<0.15EV / loop 双线注入闭环+消费点 shape 断言 / 单轮闭环 FINAL_QC 补齐）
- 邻域回归 `pytest tests/unit/test_region_adjust.py tests/unit/test_pipeline.py tests/unit/test_loop_termination.py tests/integration/test_preview_session.py tests/integration/test_export.py tests/unit/test_exposure_tier_consistency.py` → 118 passed 全绿。

## 5. 降维交接（dev-3 / F14 / 服务层怎么消费）

- **dev-3 (region_adjust)**：契约已兑现且已用你的 stage 实测——`ctx.state["region_masks"]` = dict prompt→float32 HxW [0,1]，shape == 消费帧（你 `_prepare_mask` 的 resize 分支成为兜底而非主路径；羽化仍归你）。掩码坐标 = **最终帧（compose 后）**。
- **F14 (decide region.* 接线)**：闭环已可观测——decide 写 region 键 → region_adjust enabled=True → 渲染像素变化。注意 `enabled` 联动沿 dehaze 模式；掩码存在性由本通道保证（迭代≥2 或 FINAL_QC），wants 门控已是静默跳过。
- **服务层（web 导出线）**：闭环结束后 `session.region_masks = loop._region_masks_soft`（或从 loop result 透出，若需 result 级携带请提需求——目前 LoopResult 未带掩码，防 ndarray 进 to_dict；最小改动由服务层从 loop 实例取）。ExportManager 自动转发。
- **注入方注意（缓存纪律）**：请注入**同一批 float 数组对象**（loop 模式）；若每次传新对象/uint8 原始掩码，正确性不变但 session stage 缓存会退化为逐渲染 miss。

## 6. 遗留问题

1. **compose free-px-rect 跨分辨率先失称（既有，非本次引入）**：loop smart_crop 采纳写 full-canvas 像素矩形（loop.py `rect_norm_to_px(..., fw, fh)`），preview 在小 tier 上按同像素值裁剪 → preview/full 裁剪窗口相对不一致。ratio/默认路径无此问题。掩码通道两线仍一致（同参数同适配），但掩码几何相对新旧裁剪窗会偏。建议另开条目（compose 参数归一化到相对坐标）。
2. **export 线全分辨率掩码内存**：24MP × float32 ≈ 96MB/prompt，多 prompt 并存时峰值显著（export 线无 stage 缓存、一次性）。首版可接受；若实测紧张，可改 transport 为共享低分辨率 + 消费点上采样（需 dev-3 主路径而非兜底）。
3. **`tests/unit/test_build_project_graph.py::test_real_repo_graph_invariants` 红**：dev-3 的 presets.py DEFAULT_STAGES 加 region_adjust 后该测试钉死的旧 stage 列表失配（断言 diff 全在 region_adjust/stylize 顺序）——**非 F13 引起**（我在干净树上验证过该测试原本绿），归 F12/F15 更新断言。
4. **tier EV 家族**：export 线现在也接收 face_boxes/subject_boxes（state_extras 整体透传）→ exposure box 测光在导出线同样生效，闭合了「preview box 测光、导出无」的潜在口径差；无金样本路径经过该分支（golden 走 gate 工具路径），F06 复验不受影响。
