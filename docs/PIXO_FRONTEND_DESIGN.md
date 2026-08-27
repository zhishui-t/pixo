# Pixo 前端 UI 设计方案（PIXO_FRONTEND_DESIGN）

> 版本：v1.0（仅设计，不开工）
> 日期：2026-08-22
> 作者：架构师（Pixo 团队）
> 关联：`docs/架构设计文档.md`（v0.1.0rc）、`docs/PIXO_ARCH_ALIGN_REVIEW.md`（t1）
> 边界：**只输出设计文档；不写代码、不联调真实后端、不打包（不做桌面/手机安装包）**

---

## 0. 摘要

本方案把 Pixo 前端设计为**“修图工作台 + DSH Agent 副驾”双中心**：

- 主工作区四区布局：**左侧图库 / 中间预览 / 右侧参数·测量·Agent / 底部时间线**；
- 预览以 `PreviewViewer` 为核心，支持 Original/Processed 切换、before/after 分屏滑块、放大拖动、快捷键；
- 所有参数控件统一为 **`SliderParam + NumberInput` 联动对**，参数路径与后端 `params[stage][param]` 一一对应，双向同步、带来源徽标（user/agent/decide/preset）；
- 前端只做**参数补丁（param patch）**，不直接拼整棵参数树；预览刷新复用 `RawPreviewSession` 的 generation + 指纹缓存，旧 generation 结果直接丢弃；
- DSH 以**聊天/指令面板 + Agent 推荐卡片 + 人工复核入口**嵌入右侧，Agent 的修改先变成“待确认参数补丁”，用户确认后才提交；
- 技术选型：**React 18 + Vite + TypeScript**，状态用 Zustand + TanStack Query，组件风格为专业暗色修图工具风（不花哨），先桌面 Web（≥1024px），移动端只做“看图/复核/聊天”伴侣视图。

---

## 1. 设计目标与原则

1. **即时反馈**：滑块/数值输入触发预览刷新，目标热路径 1024px 约 300–500ms（当前引擎 NEF hot≈414ms）；输入过程用本地乐观值 + 拖拽结束/防抖提交。
2. **可解释**：每个参数都能看到“谁改的、为什么”（user / agent / decide / preset / trace 徽标）。
3. **不替用户做最终决定**：Agent 只能建议，客观终止由 Decide 决定，UI 只呈现结论与理由。
4. **专业工具审美**：暗色主题、信息密度高、图标少而准、面板可折叠、大图为王。
5. **渐进增强**：先桌面；移动端是伴侣视图（浏览、复核、聊天），不是全功能编辑器。
6. **与引擎契约对齐**：UI 参数树 == `params[stage][param]`；导出走 `canonical_params()`；管线配置可与 `Pipeline.to_config()` 互转。

---

## 2. 信息架构与页面

```
Pixo（单页应用，工作区即主页）
├─ Workspace（主工作区：图库+预览+参数+Agent+时间线）
│   ├─ Library      （照片库/缩略图网格/导入/筛选/连拍分组/批处理状态）
│   ├─ Preview      （大图、before/after、缩放拖动、原始/处理切换）
│   ├─ Inspectors   （参数 / 测量 / 溯源 / Agent 聊天，可切换标签）
│   └─ Timeline     （单张闭环状态与迭代时间线）
├─ BatchBoard      （批量任务看板，可由图库切换进入）
├─ ReviewQueue     （人工复核队列）
└─ Settings        （模型/DSH/渲染/输出/快捷键）
```

不单独设“登录/项目页”：v1 是本地单用户工具，打开即工作区。

---

## 3. 主工作区布局（桌面）

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ TopBar: 导入 | 批量看板 | 复核队列(3) | 设置      [照片名] [状态chip] [导出…]   │
├───────────────┬────────────────────────────────────────┬─────────────────────┤
│  PhotoLibrary │          PreviewViewer                  │  InspectorTabs      │
│               │  ┌───────────────────────────────────┐  │ ┌─────────────────┐ │
│  [搜索/筛选]  │  │   Original|Split|Processed 切换    │  │ │ 参数 测量 溯源   │ │
│  筛选chips:   │  │   ◀──────────▶  before/after滑块    │  │ │ Agent 推荐(3)   │ │
│  全部/待处理/  │  │                                   │  │ │ chat…           │ │
│  连拍组/已接受 │  │         (可放大/拖动)              │  │ ├─────────────────┤ │
│  废片/复核    │  │                                   │  │ │ SliderParam/Num  │ │
│               │  │  zoom: 100% [−][+] [适应] [1:1]    │  │ │ Input 联动控件   │ │
│  [缩略图网格] │  │  直方图/测量chip 浮层             │  │ │ (曝光/WB/曲线/…) │ │
│  [连拍组折叠] │  └───────────────────────────────────┘  │ └─────────────────┘ │
│  [批量状态]   │                                          │  AgentPanel(DSH)   │
├───────────────┴────────────────────────────────────────┴─────────────────────┤
│ Timeline: RAW_PENDING → SCREENED → BASE_RENDERED → EXPOSURE_ALIGNING → …     │
│           迭代1(测量→决策→渲染) · 迭代2 · FINAL_QC · [转人工复核]              │
└──────────────────────────────────────────────────────────────────────────────┘
```

**布局规则**：

- 左侧图库 240–320px（可折叠为 48px 图标条）；
- 中间预览 1fr，最小 640px；
- 右侧 320–380px，标签页可整体折叠；
- 底部时间线 88–120px，可折叠；
- 三块面板均可拖拽分栏，布局保存在 localStorage（不持久化到服务端）。

---

## 4. 组件清单与交互规格

### 4.1 PreviewViewer（核心预览组件）

**状态**：

```
viewMode: 'original' | 'processed' | 'split' | 'onion'
zoom: number (fit | 0.1–4.0)
pan: {x, y}
splitPos: number (0–1)
fullscreen: boolean
renderState: idle | pending | stale | ready | error
```

**交互**：

| 操作 | 行为 |
|---|---|
| 切换 Original / Processed | 原图=嵌入缩略图或 baseline 渲染；处理图=当前 generation；即时切换，不触发新渲染 |
| Split 对比滑块 | 左右拖动分界线，左侧 original、右侧 processed；滑块位置只影响展示层，不重渲染 |
| Onion（半透明叠层） | processed 覆盖 original，透明度 0–100%，用于对齐检查 |
| 放大/拖动 | 滚轮缩放（以光标为锚点）、空格+拖拽平移、双击 1:1、`0` 适应窗口 |
| 快捷键 | `O/P/S` 切换视图、`F` 全屏、`←/→` 上一张/下一张、`Ctrl+Z` 撤销参数 |
| 渲染中 | 保留上一帧 + 右上角 spinner + generation 数字；新帧到达原子替换，禁止闪烁白屏 |
| stale 防御 | UI 每次请求带 `gen`；响应 `gen` 落后于当前值则丢弃 |
| 放大镜（可选 P2） | 长按显示原分辨率 1:1 局部，用于确认锐化/降噪 |
| 信息浮层 | 直方图、主体/天空/人脸测量 chip 可开关显示 |

**原图来源**：v1 用 `RawPreviewSession` 的 baseline 参数渲染（`preview_baseline` 预设）；P2 接 RAW 嵌入缩略图（`raw.extract_thumb`）作为秒开原图。

### 4.2 SliderParam / NumberInput（参数联动对）

**统一 props**：

```
paramPath: 'tone.highlights' | 'whitebalance.temp' | 'hsl.bands[2].hue' | ...
value / min / max / step / unit / fmt
source: 'user' | 'agent' | 'decide' | 'preset' | 'locked'
onPreview(patch, opts)   // 拖拽过程：防抖提交（80–150ms）
onCommit(patch)          // 拖拽结束：最终提交 + 记 trace
```

**联动规则**：

1. 拖动滑块 → NumberInput 实时显示当前值（本地状态，不等待服务端）；
2. 输入框聚焦时滑块暂停推送；**Enter/失焦**才提交；Esc 取消恢复原值；
3. 提交后服务端返回 `generation` 与 canonical 值，若与本地不同（钳位/被锁定）→ 控件回弹到服务端值并 toast“已按服务端值 X 生效”；
4. 双击标签或 `Alt+Click` 恢复默认值；`Shift+拖拽` 细调（step/10）；
5. `source=locked` 时禁用并显示 🔒（用户锁定 > Agent 建议，见架构文档优先级链）；
6. `source=agent` 时滑块旁显示 Agent 建议值虚线刻度，点击刻度采纳。

**参数分组（与当前引擎 param_schema 对齐）**：

| 分组 | 参数（stage.param） | 范围/单位 |
|---|---|---|
| 曝光 | `exposure.mode`(auto/off/EV) + EV 数值 | −2.5..+2.5 EV，step 0.01 |
| 白平衡 | `whitebalance.mode`(as_shot/auto/manual)；`temp` | 1000..50000 K，step 50 |
| | `tint` | −150..+150，step 1 |
| 影调 | `tone.brightness` / `contrast`(0..1) / `highlights,shadows,whites,blacks` | 四键 −1..+1，step 0.01 |
| 曲线 | `tone.user_curve`（CurveEditor，见 4.3） | `{rgb,red,green,blue,luminance: [[x,y],…]}` |
| 色彩 | `colorcal.saturation` / `vibrance` | −1..+1，step 0.01 |
| 校准 | `calibration.shadow_tint`(−100..100)、`red/green/blue_hue`(−180..180)、`*_sat`(−100..100) | 步长 1 |
| HSL | `hsl.bands[i].{hue,sat,lum}`（8 色段 ×3） | hue −180..180°、sat/lum −1..+1 |
| 分离色调 | `split_tone.shadows_hue/sat`、`highlights_hue/sat`、`balance`、`strength` | hue 0..360°、sat 0..100 |
| 细节 | `clarity.strength`、`dehaze.strength`、`refine.sharpen`(0..1)、`refine.chroma_denoise`(0..5)、`refine.highlight_desat`(0..1) | — |
| 皮肤 | `skin.enabled` + `skin.strength`(0..1) | 人像门控 |
| 风格 | `stylize.lut_path` + `lut_strength`(0..1)；场景预设 portrait/landscape/night/street/food/mono | 下拉+强度 |

**坐标输入**：构图参数（compose，t1 P0-1 规划）用 `NumberInput` 组：`ratio`(3:2 选择器)、`center [x,y]`（0..1）、`rotation`(°)、`x/y/width/height`（像素），与预览图上的**裁剪框手柄**双向联动（裁剪框拖拽写回数值、数值输入移动裁剪框）。

### 4.3 CurveEditor（曲线编辑器）

- 画布 256×256 逻辑坐标，显示 4×4 网格、对角参考线、直方图背景；
- Tab：`RGB / R / G / B / 亮度`，与 `tone.user_curve` 五键一一对应；
- 交互：点击加点、拖动移点、右键删点、双击重置通道；x 单调不减校验（后端同样校验，错误 toast）；
- 导出结构：`{"rgb": [[x,y],…], "luminance": [[x,y],…]}`，随 param patch 一起提交。

### 4.4 PhotoLibrary（图库）

| 功能 | 交互 |
|---|---|
| 导入 | 按钮/拖拽目录 → 服务端扫描 RAW/JPEG → 返回候选列表（文件名、相机、拍摄时间、预估 DCP）→ 用户确认导入；导入中显示进度 |
| 缩略图网格 | 160px 卡片：缩略图 + 文件名 + 状态角标 + 星级/标签；悬停显示直方图迷你条 |
| 筛选 | chips：全部 / 待处理 / 处理中 / 已接受 / 需复核 / 废片 / 未导入；按场景、连拍组、ISO、时间过滤 |
| 排序 | 拍摄时间 / 文件名 / 美学分 / 状态 |
| 连拍分组 | 组头卡片（BURST_001·5 张，最佳帧★）+ 折叠展开；组内支持“选帧对比”双联视图 |
| 批量状态 | 卡片底部细进度条（队列中/渲染中/测量中/导出中/失败重试） |
| 多选 | Ctrl/Shift 多选 → 批量套场景预设、批量提交 Agent 建议、批量导出 |

### 4.5 BatchBoard（批量看板）

- 三列状态泳道：**队列 / 执行中 / 完成与异常**；
- 每张任务卡显示：缩略图、当前状态、当前步骤（Meta→Vision→Decide→Render→QC）、耗时、失败原因；
- 顶部：批量策略（场景预设、是否自动 QC、复核阈值）、暂停/继续、取消；
- 完成汇总条：N 张达标 / M 张转人工 / K 张失败 / 吞吐（张/分钟，来自服务端统计）。

### 4.6 AgentPanel / DSH Chat（Agent 面板）

```
┌─ AgentPanel ────────────────────────┐
│ DSH Agent                          │
│ [推荐卡 ×3：提亮人脸 +0.28EV …]     │
│  ┌───────────────────────────────┐  │
│  │ 图: 改亮一点，人脸偏暗          │  │
│  │ Agent: 已生成建议参数补丁：      │  │
│  │  Exposure +0.28 EV             │  │
│  │  理由: face_luminance 95<115   │  │
│  │  [应用并预览] [忽略] [编辑]     │  │
│  └───────────────────────────────┘  │
│ 输入框: “把天空压暗一点…”   [发送]   │
└─────────────────────────────────────┘
```

- **聊天消息类型**：文本、图像（原图/当前结果/局部裁剪）、工具调用卡（`pixo.vision.measure` 等，可展开 JSON）、参数补丁卡、升级人工卡。
- **Agent 推荐卡**：每条建议含“参数补丁 + 理由 + 置信度 + before/after 缩略对比”；三按钮语义：
  - `应用并预览`：补丁标 `source=agent`，走正常预览刷新，用户可继续微调；
  - `忽略`：记入 trace（ignored），不回写参数；
  - `编辑`：在右侧参数面板定位到该参数，进入手动模式（用户显式意图优先）。
- **人工复核入口**：Agent 或 Decide 输出 `manual_review` 时，AgentPanel 顶部出现醒目“转入复核队列”卡片，一键入队并携带 `unreliable_regions`、`rule_hits`、当前预览图。

### 4.7 MeasurementPanel（测量面板）

- **全局区**：mean luminance、highlight_clip%、shadow_clip%、contrast、preview_highlight_clip_estimate（架构文档 §5.4 字段）；
- **区域区**：face/sky/plant 等 chip 列表：confidence、area_ratio、`reliable` 徽标、mean Lab、highlight clip；不可靠区域灰色显示且标注“决策跳过”；
- **双轨提示**：迭代值来自 preview；FINAL_QC 后显示 full-res 实测并标 `full`；
- **美学区**：7 维分只读展示，标注“仅用于溯源与复核排序，不参与决策”。

### 4.8 TracePanel（参数溯源面板）

- 当前照片的**参数级时间线**：每行 `param | 前值→后值 | source 徽标 | rule_id/formula | 时间`；
- 点击行 → 右侧参数面板定位并显示原文理由；
- 顶部筛选：来源（user/agent/decide/preset/rollback）、阶段（迭代 1..3 / FINAL_QC）；
- 导出：单张 Trace JSON / 批量 CSV（P2）。

### 4.9 ReviewQueue（人工复核队列）

- 列表 + 并排查看：左=原图，右=处理图，可切换 split 对比；
- 顶部信息条：转入原因（AGENT_ESCALATED / QC 超标 / 关键区域不可靠）、`rule_hits`、Agent 建议；
- 三键操作：**接受 / 拒绝 / 编辑**（编辑进入参数模式，用户锁定优先级最高）；
- 快捷键：`A` 接受、`X` 拒绝、`E` 编辑、`→` 下一张；
- 底部统计：今日已复核、平均用时、不可自动修复率。

### 4.10 SettingsPanel

| 分区 | 内容 |
|---|---|
| 模型 | vision 各模型路径与可用性状态灯；**NC 后端门控提示**（uniface/sapiens 默认受限，需 `PIXO_ALLOW_RESTRICTED=1`） |
| DSH | DSH Web 地址、trusted hosts、会话模型选择、聊天面板开关 |
| 渲染 | preview long_edge(512/1024/2048)、输出位深(8/16)、decode_mode、渲染 worker 数 |
| 输出 | 默认格式（JPEG/WebP/PNG16/TIFF16/raw48）、质量、导出目录、GPS 剥离开关 |
| 工作区 | 布局恢复、主题（暗/更暗）、语言、快捷键表 |
| 关于 | 版本、render_version/detection_version、许可信息 |

### 4.11 通用：StatusBar / Toasts / 空态

- 底部状态栏：`generation #12 · 预览 1024 · 渲染 0.4s · native ✓ · multi ✓`；
- 全局 toast：渲染失败、模型未就绪、参数被钳位、导入完成；
- 空态：无照片 → 导入引导；无测量 → “模型未就绪，转人工”提示。

---

## 5. 状态与数据流

### 5.1 UI 状态模型（草案）

```ts
type Source = 'user' | 'agent' | 'decide' | 'preset' | 'locked';
interface ParamPatch { [stage: string]: { [param: string]: unknown } }

interface AppState {
  library: { photos: Photo[], filter, sort, burstGroups, importJob? }
  active: {
    photoId?: string
    sessionId?: string          // = RawPreviewSession.session_id
    generation: number          // 服务端参数版本
    params: ParamPatch          // 本地乐观参数视图
    canonical?: ParamPatch      // 服务端 canonical_params()
    view: ViewState
    pendingPatches: ParamPatch  // 尚未提交
  }
  inspector: { tab: 'params' | 'measure' | 'trace' | 'agent', collapsed: bool[] }
  timeline: { states: PhotoState[], events: TraceEvent[] }
  agent: { messages: Message[], recommendations: AgentSuggestion[] }
  reviewQueue: ReviewItem[]
  render: { longEdge: 1024, bps: 8, fmt: 'jpeg', quality: 88 }
  settings: Settings
}
```

### 5.2 关键数据流：一次滑块改动

```
用户拖动 SliderParam
  → 本地乐观更新 value + NumberInput
  → debounce 80–150ms（或拖拽结束立即）
  → PUT /api/sessions/{id}/params  body: {"tone":{"highlights":0.3},"__source":"user"}
  → 服务端 RawPreviewSession.update_params() 深合并、generation++
  → 响应 {generation, canonical: {...}}
  → UI 以 generation 为准更新，触发
  → GET /api/sessions/{id}/image?gen=N&long_edge=1024&fmt=jpeg
  → 服务端 submit_render()/encode() 返回 {gen, image_url, elapsed_ms}
  → 客户端校验 gen == 当前；旧 gen 丢弃；新图原子替换 <img>
```

**规则**：

1. 前端永远只发**局部 patch**；服务端 `_deep_merge` 负责与现有参数树合并（与 `RawPreviewSession.update_params` 现有实现一致）。
2. `generation` 是唯一版本令牌：所有图片/测量/trace 响应都带 gen，落后即弃（对应 `StaleGenerationError` 防御）。
3. 快速连续拖动只保留最后一次请求；中间 pending 请求可 AbortController 取消。
4. 导出链路：`ExportManager.submit(session, fmt)` 内部取 `canonical_params()` → full-quality 渲染 → 前端轮询 `status(task_id)`；导出期间参数仍可继续预览（导出快照独立）。
5. 管线持久化：`Pipeline.to_config()` 的 `{name, stages, params, output}` 与 UI 的 params 树 + 预设选择互转；保存方案时存储 to_config JSON。

### 5.3 与 render/web 现有能力的对接表

| UI 能力 | 现有引擎能力 | 缺口（仅设计，不在本任务实现） |
|---|---|---|
| 预览渲染 | `RawPreviewSession.render/submit_render/encode`，L1/L2/L3 缓存 + generation | 需 HTTP 包装；无 image URL 路由 |
| 参数合并 | `RawPreviewSession.update_params` 深合并 + generation++ | 需 API 层 |
| 最终导出 | `ExportManager.submit/status/wait`（JPEG/WebP/PNG16/TIFF16/raw48） | 需 API 层 + 任务持久化（当前仅内存） |
| 参数规范化 | `canonical_params()` | 直接可用 |
| 参数校验 | 各 Stage `param_schema`（min/max/choices） | 需把 schema 暴露为 `/api/schema` 供 UI 动态渲染控件 |
| 测量/Agent/状态机 | 尚无（t1 P0/P1 规划） | 按 `PIXO_ARCH_ALIGN_REVIEW.md` 路线逐步接入 |

### 5.4 API 草案（REST + SSE，只做设计）

```
# 会话/预览
POST   /api/import                       # 扫描目录，返回候选清单
POST   /api/photos                      # 确认导入，创建 photo 记录
GET    /api/photos?filter=&sort=        # 图库列表 + 缩略图
GET    /api/photos/{id}                 # 详情 + 状态 + trace 摘要
POST   /api/photos/{id}/sessions        # 创建 RawPreviewSession，返回 session_id
PUT    /api/sessions/{id}/params        # 局部 patch；body 含 __source
GET    /api/sessions/{id}/canonical     # canonical_params()
GET    /api/sessions/{id}/image?gen=&long_edge=&fmt=&quality=
GET    /api/sessions/{id}/histogram?gen=  # 预览直方图（可选）
DELETE /api/sessions/{id}               # 关闭会话

# 导出
POST   /api/sessions/{id}/exports       # body: {fmt, quality, output_dir}
GET    /api/exports/{task_id}           # ExportManager.status()

# 测量/决策（P1 后端出现后，UI 契约先行）
GET    /api/photos/{id}/measurements?gen=&scope=preview|full
POST   /api/photos/{id}/decide          # 触发一轮 Decide
GET    /api/photos/{id}/timeline        # 状态机事件流 + trace

# Agent（P2）
GET    /api/agent/conversations/{photo_id}
POST   /api/agent/chat                  # 文本/图像消息 → DSH
POST   /api/agent/recommendations/{id}/apply   # 应用/忽略/编辑
POST   /api/photos/{id}/review          # 转入复核队列

# 设置/诊断
GET    /api/health                      # 模型可用性/native/版本/许可提示
GET    /api/schema/params               # param_schema 汇总（动态渲染滑块）
```

事件推送：`SSE /api/events` 推 `session.generation`、`export.status`、`photo.state_changed`、`agent.message`、`review.new`；SSE 断线自动重连，不阻塞核心渲染请求。

---

## 6. 技术选型建议

| 维度 | 建议 | 理由 / 备选 |
|---|---|---|
| 框架 | React 18 + Vite + TypeScript（严格模式） | 与 DSH Web 生态同栈；Vite 开发快 |
| 状态 | Zustand（客户端工作区状态）+ TanStack Query（服务端状态/缓存/轮询） | 轻量、类型好；不引入 Redux |
| 样式 | CSS Modules + 少量自定义 design tokens；暗色专业风 | Tailwind 可作备选；**禁止花哨动画**，只保留 120ms 内过渡 |
| 组件基础 | Radix primitives / 自研 headless（Slider、Dialog、Tabs、Tooltip、ContextMenu） | 不引入重型组件库；图标 Lucide |
| 曲线/画布 | 自研轻量 `<CurveEditor>`（pointer events + SVG/canvas） | 不需要第三方图表库 |
| 预览图 | `<img>` + blob URL（JPEG 预览）+ 自定义 zoom/pan 变换 | 1024 预览图无切片需求 |
| 请求 | fetch + AbortController；SSE 用 EventSource | 暂不引入 WebSocket 复杂度 |
| 移动端 | 响应式降级：<1024px 隐藏参数细调，只保留看图/复核/聊天/设置 | P2 再单独做 Expo/RN 客户端（不在本次范围） |

**视觉风格**：深灰 `#1a1d21` 背景、`#262a2f` 面板、`#3a7afe` 主强调色、橙/绿/红状态色（转人工=橙、达标=绿、失败=红）；等宽数字（tabular-nums）；测量数据用小号 mono 字体。

---

## 7. 线框图（文字版原型）

### 7.1 Workspace（默认）

```
┌TopBar──────────────────────────────────────────────────────────┐
│ [导入] [批量看板] [复核队列(3)]       DSC_5236.NEF  ●EXPOSURE_ALIGNING  [导出▾] [⚙] │
├──────────────┬────────────────────────────────┬────────────────┤
│图库          │  [原图|Split|处理]  gen#12     │ 标签: 参数 测量 │
│──────────────│                                │ 溯源 Agent     │
│🔎___________ │  ┌────────────────────────────┐ │───────────────│
│chips: 全部   │  │        │                   │ │ 曝光          │
│ 待处理 连拍  │  │ 原图   │      处理图        │ │ mode: auto ▾  │
│ 复核 废片    │  │        │   ◀────▶ slider    │ │ EV [—●——] +0.28│
│──────────────│  │        │                   │ │ 白平衡        │
│[缩略图][缩略图]│ │                            │ │ as_shot ▾     │
│[缩略图][缩略图]│ └────────────────────────────┘ │ 色温 [———●—]   │
│[缩略图][缩略图]│ 100% [－][＋][适应][1:1]   ℹ   │ 影调          │
│              │                                │ 高光 [——●——]  │
│连拍组 BURST_001│                               │ …             │
│ [■■■■■] 5张  │                                │───────────────│
│──────────────│                                │ DSH Agent     │
│批量: ▓▓▓░ 3/5│                                │ [建议卡]      │
│              │                                │ [应用][忽略]   │
│              │                                │ _____________ │
├──────────────┴────────────────────────────────┴────────────────┤
│时间线: SCREENED ✓ → BASE_RENDERED ✓ → EXPOSURE_ALIGNING(迭代2) → │
│  ── FINAL_QC → ACCEPTED        [转人工复核] [撤销] [接受当前结果]  │
│状态栏: gen#12 · 预览1024 · 0.41s · native✓ · multi✓ · DSH✓         │
└──────────────────────────────────────────────────────────────────┘
```

### 7.2 单张闭环（测量+溯源标签页）

```
右侧 Inspector（测量 tab）                右侧 Inspector（溯源 tab）
┌──────────────────────┐                 ┌──────────────────────┐
│ 全局                 │                 │ 来源: 全部 ▾          │
│ luminance  112       │                 │ 14:22 Exposure       │
│ highlight  0.4% ✓    │                 │  0.0 → +0.28 EV      │
│ shadow     2.0% ⚠    │                 │  [decide] exposure_  │
│ contrast   0.24      │                 │  rule_001            │
│──────────────        │                 │  face_luminance 95<  │
│ 区域                 │                 │  115                 │
│ face  conf .87 ●可靠 │                 │ 14:21 Agent 建议     │
│   L65 a18 b22 面积3% │                 │  提亮人脸 → 已采纳   │
│ sky   conf .92 ●可靠 │                 │ 14:20 preset 场景    │
│   L80 a2 b-10 裁切1% │                 │  portrait            │
│──────────────        │                 │ [导出Trace JSON]     │
│ 美学 3.8/5 (仅参考)   │                 └──────────────────────┘
└──────────────────────┘
```

### 7.3 图库 / 批量看板

```
┌BatchBoard────────────────────────────────────────────────────┐
│ 队列(4)         │  执行中(1)          │  完成/异常(12)         │
│ [缩略图] …      │  [缩略图]           │  [缩略图]✓ [缩略图]⚠   │
│ [缩略图] …      │  ▓▓▓▓░░ QC中        │  [缩略图]→人工 [缩略图]✓│
│ [缩略图] …      │  迭代2/3 · 0.8s     │  …                    │
│ [缩略图] …      │                     │                        │
└───────────────────────────────────────────────────────────────┘
汇总: 达标 9 · 转人工 2 · 失败 1 · 吞吐 1.8张/分钟   [暂停][继续]
```

### 7.4 复核队列

```
┌ReviewQueue─────────────────────────────────────────────────────┐
│ 队列(3)                       │ 对比视图                        │
│ ┌───────────────┐            │ ┌────────────┬───────────────┐ │
│ │ DSC_0364 ⚠    │            │ │ 原图        │ 处理图        │ │
│ │ 高光裁切 3.2% │            │ │             │  ◀──▶         │ │
│ ├───────────────┤            │ └────────────┴───────────────┘ │
│ │ DSC_0479 ⚠    │            │ 原因: FINAL_QC highlight>3%    │ │
│ │ 人脸不可靠    │            │ rules: qc_rollback_rule(1次)    │ │
│ └───────────────┘            │ [接受A] [拒绝X] [编辑E] [下一张→]│
└───────────────────────────────────────────────────────────────┘
```

### 7.5 移动端伴侣视图（<1024px，仅设计）

```
┌───────────────────────┐
│ 照片库 (网格/连拍组)    │
├───────────────────────┤
│       预览图           │
│  [原图|Split|处理]      │
├───────────────────────┤
│ 测量chip: face 95 lum │
├───────────────────────┤
│ DSH 聊天 (底部抽屉)     │
│  [Agent建议: +0.28EV]  │
│  [应用] [忽略] [复核]   │
└───────────────────────┘
```

---

## 8. DSH Agent 集成的 UI 形态

1. **位置**：右侧 Inspector 的 `Agent` 标签；全屏时可拖出为浮动窗。
2. **形态**：DSH 聊天面板嵌入（iframe 或 DSH Web 组件），消息上方渲染 Pixo 自定义卡片类型（参数补丁卡 / 工具调用卡 / 推荐卡）。P2 之前可以先做“聊天容器 + 事件占位”。
3. **闭环三态**：
   - **建议态**：Agent 输出参数补丁 + 理由 + 置信度，UI 渲染推荐卡，用户 apply/ignore/edit；
   - **执行态**：Decide 每轮结果在时间线推进，聊天面板同步贴出本轮测量摘要（tool card）；
   - **升级态**：`MANUAL_REVIEW` 时顶部红/橙横幅 + “立即复核”按钮，聊天保留上下文。
4. **人工复核操作**：复核队列的每个卡片显示 Agent 原话、理由、`confidence`；用户操作写回 trace（`review.accept/reject/edit`），并作为消息回传 DSH 会话形成记忆。
5. **权限可视化**：Agent 不能直接写终态；UI 上 Agent 卡只有“建议”，状态迁移按钮只在服务端校验通过后显示可用。

---

## 9. “不做”的边界（本设计明确排除）

- ❌ 不写任何前端/后端代码，不创建工程脚手架；
- ❌ 不打包：不做 Tauri/Electron/PyInstaller/Expo 安装包（用户明确要求）；
- ❌ 不做真实后端联调：`/api/*` 与 SSE 为**设计草案**，本期不实现、不验证；
- ❌ 不设计登录/多用户/云同步/计费；
- ❌ 不做移动端完整参数编辑器（仅伴侣视图设计）；
- ❌ 不改动 render 引擎与测试；
- ❌ 不引入第三方重型图表/UI 库的最终决策（仅给出选型建议，实现时再冻结依赖）。

---

## 10. 与 t1 路线的衔接

- 本设计假设 t1 的 `compose`（P0-1）、Vision 测量（P0-4）、State/Trace（P1-4）、service（P1-6）按路线落地后，UI 数据契约才完整；
- 在 P1-6 之前，前端可先用 `RawPreviewSession` 直连的本地开发页验证 PreviewViewer/SliderParam（mock 参数 schema），但**本任务不实施**；
- 打包计划（t1 P2-5/P2-7）暂缓，本 UI 设计保持“先 Web/PWA 可运行”的兼容性。

---

## 11. 设计验收清单（后续开工时逐项核对）

1. 滑块与数值输入双向联动，服务端钳位/锁定能正确回弹；
2. 拖拽滑块 300–500ms 内出新预览，旧 generation 图片不闪烁；
3. before/after 分屏、缩放拖动、快捷键与全屏可用；
4. 图库支持导入、筛选、连拍分组折叠、批量状态显示；
5. Agent 推荐卡可 apply/ignore/edit，修改可溯源；
6. 复核队列 accept/reject/edit 流程完整；
7. 参数面板覆盖当前 12-stage 全部可调参数（含曲线与 8 段 HSL）；
8. 移动端 <1024px 自动降级为伴侣视图；
9. 所有设计约束遵循：不打包、不真实联调、专业暗色风格。
