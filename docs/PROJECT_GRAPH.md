# PIXO 项目图谱 (src/pixo)

> 由 `scripts/build_project_graph.py` AST 解析生成 (root=K:\work\project\pixo\src\pixo)。所有依赖边来自源码 import 语句 (含行号), Stage 顺序来自 `render/pipeline/presets.py` DEFAULT_STAGES, 域契约来自各模块 `@register_stage` 声明 —— 无任何手画边。

- 图谱版本: 1.0, 模块数: 170, 内部+外部 import 边: 660, 扫描文件: 170

## 异常与诚实声明

- **被同名包遮蔽的模块** (Python 包优先, 不可导入, 仅为 re-export 门面占位): `render.pipeline.py`


## 分层架构

```mermaid
flowchart LR
  subgraph render["pixo.render"]
    render["render"]
    render__native["_native"]
    render_adjustments["adjustments"]
    render_core["core"]
    render_decide["decide"]
    render_geometry["geometry"]
    render_modules["modules"]
    render_pipeline["pipeline"]
    render_state["state"]
    render_web["web"]
  end
  agent["agent"]
  agent_prompts["agent.prompts"]
  decide["decide"]
  decide_rules["decide.rules"]
  harness["harness"]
  harness_goldens["harness.goldens"]
  know["know"]
  manifests["manifests"]
  meta["meta"]
  pipeline["pipeline"]
  pixo["pixo"]
  review["review"]
  service["service"]
  state["state"]
  trace["trace"]
  vision["vision"]
  vision_segmenters["vision.segmenters"]
  agent --> agent_prompts
  agent --> decide
  agent --> meta
  agent -->|2| pipeline
  agent --> render_modules
  agent --> render_pipeline
  agent --> service
  agent --> vision
  decide --> know
  decide --> state
  decide_rules --> decide
  harness -->|4| harness_goldens
  harness -->|2| pipeline
  harness -->|2| render
  harness --> review
  harness -->|2| vision
  harness_goldens -->|2| vision
  pipeline --> agent
  pipeline -->|2| decide
  pipeline -->|3| meta
  pipeline --> render_geometry
  pipeline --> render_modules
  pipeline -->|2| render_pipeline
  pipeline -->|2| render_web
  pipeline -->|2| state
  pipeline -->|5| vision
  render --> meta
  render --> pipeline
  render -->|2| render__native
  render -->|16| render_core
  render -->|17| render_modules
  render -->|10| render_pipeline
  render --> vision
  render__native --> render_core
  render_adjustments -->|5| render_core
  render_adjustments -->|11| render_modules
  render_core -->|6| render__native
  render_decide -->|3| decide
  render_decide --> decide_rules
  render_geometry --> render_modules
  render_modules -->|7| render__native
  render_modules -->|28| render_core
  render_modules -->|25| render_pipeline
  render_pipeline -->|7| render_core
  render_pipeline -->|2| render_modules
  render_state -->|4| state
  render_state --> trace
  render_web -->|3| render_core
  render_web -->|4| render_pipeline
  review --> state
  review --> trace
  service --> decide
  service --> meta
  service --> pipeline
  service --> render_core
  service -->|2| render_web
  service --> state
  service -->|2| vision
  service --> vision_segmenters
  state -->|3| trace
  vision --> vision_segmenters
  vision_segmenters -->|13| vision
```

跨层聚合边 (层 A → 层 B | 边数 | 模块级证据抽样):

| 源层 | 目标层 | 边数 | 证据 (module:line, 最多 8 条) |
|---|---|---|---|
| agent | agent.prompts | 1 | `agent:43` |
| agent | decide | 1 | `agent.patch_protocol:33` |
| agent | meta | 1 | `agent.tools:258` |
| agent | pipeline | 2 | `agent.orchestrator:14`, `agent.orchestrator:28` |
| agent | render.modules | 1 | `agent.patch_protocol:34` |
| agent | render.pipeline | 1 | `agent.patch_protocol:35` |
| agent | service | 1 | `agent.orchestrator:13` |
| agent | vision | 1 | `agent.burst_selection:18` |
| decide | know | 1 | `decide.engine:1114` |
| decide | state | 1 | `decide.engine:29` |
| decide.rules | decide | 1 | `decide.rules:13` |
| harness | harness.goldens | 4 | `harness.regression:7`, `harness.regression:7`, `harness:13`, `harness:13` |
| harness | pipeline | 2 | `harness.batch_render:21`, `harness.batch_render:7` |
| harness | render | 2 | `harness.metrics:7`, `harness.regression:22` |
| harness | review | 1 | `harness.failure_injection:10` |
| harness | vision | 2 | `harness.failure_injection:11`, `harness.metrics:8` |
| harness.goldens | vision | 2 | `harness.goldens.compare:13`, `harness.goldens.samples:11` |
| pipeline | agent | 1 | `pipeline.loop:1104` |
| pipeline | decide | 2 | `pipeline.loop:29`, `pipeline.loop:30` |
| pipeline | meta | 3 | `pipeline.batch:24`, `pipeline.batch:24`, `pipeline.loop:575` |
| pipeline | render.geometry | 1 | `pipeline.loop:32` |
| pipeline | render.modules | 1 | `pipeline.loop:308` |
| pipeline | render.pipeline | 2 | `pipeline.loop:309`, `pipeline.loop:310` |
| pipeline | render.web | 2 | `pipeline.loop:375`, `pipeline.loop:387` |
| pipeline | state | 2 | `pipeline.batch:25`, `pipeline.loop:31` |
| pipeline | vision | 5 | `pipeline.batch:26`, `pipeline.batch:303`, `pipeline.batch:674`, `pipeline.loop:33`, `pipeline.loop:34` |
| render | meta | 1 | `render.api:37` |
| render | pipeline | 1 | `render.tools.bench_e2e_loop:22` |
| render | render._native | 2 | `render.tools.bench_pipeline:178`, `render.tools.bench_preview:272` |
| render | render.core | 16 | `render.api:133`, `render.api:17`, `render.api:172`, `render.api:18`, `render.api:220`, `render.color_transform:37`, `render.color_transform:38`, `render.color_transform:7` (共 16) |
| render | render.modules | 17 | `render.params:10`, `render.params:11`, `render.params:12`, `render.params:13`, `render.params:14`, `render.params:15`, `render.params:16`, `render.params:17` (共 17) |
| render | render.pipeline | 10 | `render.api:134`, `render.api:15`, `render.api:16`, `render.api:221`, `render.params:21`, `render.params:26`, `render.tools.bench_pipeline:34`, `render.tools.bench_pipeline:35` (共 10) |
| render | vision | 1 | `render.tools.bench_e2e_loop:27` |
| render._native | render.core | 1 | `render._native:828` |
| render.adjustments | render.core | 5 | `render.adjustments.clarity_dehaze:4`, `render.adjustments.hsl:4`, `render.adjustments.split_toning:4`, `render.adjustments.tone_curve:4`, `render.adjustments.tone_curve:5` |
| render.adjustments | render.modules | 11 | `render.adjustments.clarity_dehaze:5`, `render.adjustments.clarity_dehaze:6`, `render.adjustments.color_calibration:4`, `render.adjustments.exposure:4`, `render.adjustments.highlights_shadows:7`, `render.adjustments.hsl:5`, `render.adjustments.noise_reduction:4`, `render.adjustments.sharpening:4` (共 11) |
| render.core | render._native | 6 | `render.core.huesat:437`, `render.core.huesat:467`, `render.core.huesat:468`, `render.core.huesat:469`, `render.core.io:168`, `render.core.lut3d:179` |
| render.decide | decide | 3 | `render.decide.engine:4`, `render.decide.rule_engine:4`, `render.decide:4` |
| render.decide | decide.rules | 1 | `render.decide.rules:4` |
| render.geometry | render.modules | 1 | `render.geometry.crop_rotate:4` |
| render.modules | render._native | 7 | `render.modules.color_cal:378`, `render.modules.exposure:458`, `render.modules.refine:140`, `render.modules.refine:199`, `render.modules.reshape:98`, `render.modules.tone_map:332`, `render.modules.white_balance:393` |
| render.modules | render.core | 28 | `render.modules.calibration:13`, `render.modules.color_cal:236`, `render.modules.color_cal:267`, `render.modules.color_cal:535`, `render.modules.exposure:318`, `render.modules.exposure:320`, `render.modules.exposure:333`, `render.modules.exposure:410` (共 28) |
| render.modules | render.pipeline | 25 | `render.modules.calibration:11`, `render.modules.calibration:12`, `render.modules.color_cal:33`, `render.modules.color_cal:34`, `render.modules.compose:30`, `render.modules.compose:31`, `render.modules.exposure:45`, `render.modules.hsl:13` (共 25) |
| render.pipeline | render.core | 7 | `render.pipeline.base:14`, `render.pipeline.base:15`, `render.pipeline.base:17`, `render.pipeline.base:18`, `render.pipeline.base:96`, `render.pipeline.base:98`, `render.pipeline.graph:279` |
| render.pipeline | render.modules | 2 | `render.pipeline.presets:23`, `render.pipeline.presets:34` |
| render.state | state | 4 | `render.state.exceptions:4`, `render.state.machine:4`, `render.state.store:4`, `render.state:4` |
| render.state | trace | 1 | `render.state.trace:4` |
| render.web | render.core | 3 | `render.web.export:36`, `render.web.session:211`, `render.web.session:26` |
| render.web | render.pipeline | 4 | `render.web.export:37`, `render.web.export:38`, `render.web.session:27`, `render.web.session:28` |
| review | state | 1 | `review.queue:10` |
| review | trace | 1 | `review.queue:64` |
| service | decide | 1 | `service.runtime:19` |
| service | meta | 1 | `service.runtime:18` |
| service | pipeline | 1 | `service.loop:8` |
| service | render.core | 1 | `service.runtime:106` |
| service | render.web | 2 | `service.runtime:21`, `service.runtime:22` |
| service | state | 1 | `service.runtime:20` |
| service | vision | 2 | `service.app:48`, `service.runtime:23` |
| service | vision.segmenters | 1 | `service.runtime:143` |
| state | trace | 3 | `state.machine:29`, `state.store:16`, `state:12` |
| vision | vision.segmenters | 1 | `vision.health:92` |
| vision.segmenters | vision | 13 | `vision.segmenters.common:11`, `vision.segmenters.grounded_sam:16`, `vision.segmenters.grounded_sam:18`, `vision.segmenters.multi_router:27`, `vision.segmenters.multi_router:28`, `vision.segmenters.rfdetr_person:13`, `vision.segmenters.rfdetr_person:55`, `vision.segmenters.sapiens_body:25` (共 13) |

## 管线数据流 (RAW → decode → IDT → 编辑 → ODT → encode)

```mermaid
flowchart LR
  s0["RAW"]
  s1["decode"]
  s2["exposure<br/>linear_cam→linear_cam"]
  s3["whitebalance<br/>linear_cam→linear_rgb<br/>IDT"]
  s4["compose<br/>linear_rgb→linear_rgb"]
  s5["huesat<br/>linear_rgb→linear_rgb"]
  s6["tone<br/>linear_rgb→gamma_rgb<br/>ODT"]
  s7["dehaze<br/>gamma_rgb→gamma_rgb"]
  s8["clarity<br/>gamma_rgb→gamma_rgb"]
  s9["colorcal<br/>gamma_rgb→gamma_rgb"]
  s10["calibration<br/>gamma_rgb→gamma_rgb"]
  s11["hsl<br/>gamma_rgb→gamma_rgb"]
  s12["split_tone<br/>gamma_rgb→gamma_rgb"]
  s13["skin<br/>gamma_rgb→gamma_rgb"]
  s14["stylize<br/>gamma_rgb→gamma_rgb"]
  s15["refine<br/>gamma_rgb→gamma_rgb"]
  s16["encode"]
  s0 --> s1
  s1 --> s2
  s2 --> s3
  s3 --> s4
  s4 --> s5
  s5 --> s6
  s6 --> s7
  s7 --> s8
  s8 --> s9
  s9 --> s10
  s10 --> s11
  s11 --> s12
  s12 --> s13
  s13 --> s14
  s14 --> s15
  s15 --> s16
```

Stage 顺序来源: `render.pipeline.presets` DEFAULT_STAGES (行 14); 色彩域定义: `render/pipeline/context.py`; 每步域契约来自 `@register_stage` 装饰器 (行号见 JSON `pipeline.stages`)。

| 步骤 | 名称 | 类型 | 域 | 证据 |
|---|---|---|---|---|
| 0 | **RAW** | source |  | render.pipeline.graph:271 (Pipeline.run_file 入参 raw_path) |
| 1 | **decode** | io | → linear_cam | render.pipeline.graph:279 (run_file 内嵌套 import decode_raw) + render.pipeline.graph:290 (set_image 初始域 linear_cam) |
| 2 | exposure | stage (order=10) | linear_cam → linear_cam | `render.modules.exposure:358` |
| 3 | whitebalance | stage (order=20) | linear_cam → linear_rgb (**IDT**) | `render.modules.white_balance:242` |
| 4 | compose | stage (order=22) | linear_rgb → linear_rgb | `render.modules.compose:197` |
| 5 | huesat | stage (order=25) | linear_rgb → linear_rgb | `render.modules.huesat:38` |
| 6 | tone | stage (order=30) | linear_rgb → gamma_rgb (**ODT**) | `render.modules.tone_map:282` |
| 7 | dehaze | stage (order=45) | gamma_rgb → gamma_rgb | `render.modules.reshape:26` |
| 8 | clarity | stage (order=46) | gamma_rgb → gamma_rgb | `render.modules.reshape:56` |
| 9 | colorcal | stage (order=50) | gamma_rgb → gamma_rgb | `render.modules.color_cal:175` |
| 10 | calibration | stage (order=51) | gamma_rgb → gamma_rgb | `render.modules.calibration:16` |
| 11 | hsl | stage (order=52) | gamma_rgb → gamma_rgb | `render.modules.hsl:19` |
| 12 | split_tone | stage (order=54) | gamma_rgb → gamma_rgb | `render.modules.split_tone:21` |
| 13 | skin | stage (order=55) | gamma_rgb → gamma_rgb | `render.modules.skin:54` |
| 14 | stylize | stage (order=60) | gamma_rgb → gamma_rgb | `render.modules.style:19` |
| 15 | refine | stage (order=70) | gamma_rgb → gamma_rgb | `render.modules.refine:166` |
| 16 | **encode** | io | → uint8_srgb | render.pipeline.graph:301 (终检 gamma_rgb) + render.pipeline.graph:305 (clip*255+0.5 → uint8) |

## 模块职责表

职责取自各模块 docstring 首行 (脚本解析, 非人工转写)。入/出度只统计模块级 import (嵌套懒加载不计入度数, 证据在 JSON `edges[].scope`)。

### 层 `agent` —— pixo.agent —— Agent 编排 / 工具注册 / 连拍选帧。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `agent` | pixo.agent —— Agent 编排 / 工具注册 / 连拍选帧。 | 0 | 4 |
| `agent.burst_selection` | pixo.agent.burst_selection —— 连拍选帧 / 批内优选逻辑。 | 2 | 1 |
| `agent.orchestrator` | pixo.agent.orchestrator —— 任务编排入口。 | 2 | 3 |
| `agent.patch_protocol` | P3b —— LLM 参数补丁校验器（LLM 建议进系统的唯一闸门）。 | 1 | 3 |
| `agent.suggest` | agent.suggest —— LLM 参数建议编排（P3c）。 | 1 | 2 |
| `agent.tools` | pixo.agent.tools —— Agent 工具注册与调用封装。 | 2 | 3 |

### 层 `agent.prompts` —— pixo.agent.prompts —— Agent 提示词与工具说明。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `agent.prompts` | pixo.agent.prompts —— Agent 提示词与工具说明。 | 1 | 0 |

### 层 `decide` —— pixo.decide —— 量化决策规则引擎。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `decide` | pixo.decide —— 量化决策规则引擎。 | 3 | 1 |
| `decide.conflict` | pixo.decide.conflict —— 冲突消歧兼容入口。 | 0 | 1 |
| `decide.engine` | Pixo Decide —— 确定性规则引擎 (P1-3)。 | 10 | 2 |
| `decide.rollback` | pixo.decide.rollback —— QC 回退兼容入口。 | 0 | 1 |
| `decide.rule_engine` | 兼容入口：``render.decide.rule_engine`` / ``pixo.decide.rule_engine``。 | 1 | 1 |
| `decide.rule_loader` | pixo.decide.rule_loader —— 规则加载兼容入口。 | 0 | 1 |
| `decide.termination` | pixo.decide.termination —— 终止判断兼容入口。 | 0 | 1 |

### 层 `decide.rules` —— pixo.decide.rules —— 内置规则 YAML 镜像 + 引擎符号转发。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `decide.rules` | pixo.decide.rules —— 内置规则 YAML 镜像 + 引擎符号转发。 | 1 | 1 |

### 层 `harness` —— pixo.harness —— Pixo Harness/金样本/回归兼容入口。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `harness` | pixo.harness —— Pixo Harness/金样本/回归兼容入口。 | 0 | 6 |
| `harness.batch_render` | pixo.harness.batch_render —— 批量/单张渲染 Harness 兼容入口。 | 1 | 2 |
| `harness.failure_injection` | pixo.harness.failure_injection —— 故障注入兼容工具。 | 1 | 2 |
| `harness.metrics` | pixo.harness.metrics —— 测量/性能指标兼容入口。 | 1 | 2 |
| `harness.regression` | pixo.harness.regression —— 金样本/回归兼容入口。 | 1 | 3 |

### 层 `harness.goldens` —— pixo.harness.goldens —— 金样本集 v0 基础设施。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `harness.goldens` | pixo.harness.goldens —— 金样本集 v0 基础设施。 | 2 | 3 |
| `harness.goldens.compare` | pixo.harness.goldens.compare —— 金样本回归/对比接口。 | 1 | 3 |
| `harness.goldens.generate_manifest` | 生成 golden_manifest.json（内置合成 + 真实占位）。 | 0 | 2 |
| `harness.goldens.manifest` | pixo.harness.goldens.manifest —— 金样本 manifest 数据结构与校验。 | 5 | 0 |
| `harness.goldens.samples` | pixo.harness.goldens.samples —— 合成金样本生成器与内置登记数据。 | 3 | 2 |
| `harness.goldens.validate_manifest` | 校验 golden_manifest.json。 | 2 | 1 |

### 层 `know` —— pixo.know —— Pixo 知识层 v1（混合知识库）。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `know` | pixo.know —— Pixo 知识层 v1（混合知识库）。 | 0 | 5 |
| `know.cards` | pixo.know.cards —— 风格卡片 schema 与 Decide 建议规则。 | 4 | 1 |
| `know.context` | pixo.know.context —— 知识查询结果 -> LLM prompt 注入段格式器。 | 0 | 0 |
| `know.graph` | pixo.know.graph —— 简单知识图谱（结构化硬知识）。 | 3 | 0 |
| `know.paths` | pixo.know.paths —— 仓库配置目录定位（去 CWD 化）。 | 2 | 0 |
| `know.query` | pixo.know.query —— 混合查询：知识图谱 + RAG 聚合。 | 2 | 2 |
| `know.rag` | pixo.know.rag —— 轻量混合检索（关键词 + BM25 风格打分）。 | 3 | 0 |
| `know.registry` | pixo.know.registry —— 知识包加载/登记。 | 1 | 6 |

### 层 `manifests` —— pixo.manifests —— Pixo Vision 模型清单读取/校验。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `manifests` | pixo.manifests —— Pixo Vision 模型清单读取/校验。 | 1 | 0 |
| `manifests.__main__` | pixo.manifests CLI：校验 Vision 模型清单。 | 0 | 1 |

### 层 `meta` —— Pixo Meta —— 元数据提取/标准化、连拍分组、基础光照推断。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `meta` | Pixo Meta —— 元数据提取/标准化、连拍分组、基础光照推断。 | 1 | 3 |
| `meta.burst` | Pixo Meta —— 连拍分组 (P0-5)。 | 3 | 1 |
| `meta.burst_grouping` | 兼容入口：``render.meta.burst_grouping`` 与 guanlan burst_grouping.py 对应。 | 0 | 1 |
| `meta.daylight` | 兼容入口：``render.meta.daylight`` 与 guanlan daylight.py 对应。 | 0 | 1 |
| `meta.exif` | Pixo Meta —— EXIF 提取与标准化 (P0-5 基础)。 | 3 | 2 |
| `meta.extract` | 兼容入口：``render.meta.extract`` 与 ``render.meta.exif`` 等价。 | 5 | 1 |
| `meta.lighting` | Pixo Meta —— 基础光照/场景上下文 (P0-5)。 | 3 | 0 |

### 层 `pipeline` —— pixo.pipeline —— Pixo 单张/批量闭环编排层。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `pipeline` | pixo.pipeline —— Pixo 单张/批量闭环编排层。 | 0 | 2 |
| `pipeline.batch` | pixo.pipeline.batch —— 批量流程 + 连拍选帧三层过滤（P2-2）。 | 3 | 6 |
| `pipeline.loop` | pixo.pipeline.loop —— 单张修图闭环编排（P1-5）。 | 5 | 13 |

### 层 `pixo`

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `pixo` | pixo —— Pixo 渲染 / 视觉 / 元数据统一命名空间包。 | 0 | 0 |

### 层 `render` —— pixo.render —— Pixo 渲染引擎独立包。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `render` | pixo.render —— Pixo 渲染引擎独立包。 | 0 | 0 |
| `render.api` | pixo.render 渲染引擎统一 API (v0.1)。 | 2 | 10 |
| `render.color_transform` | pixo.render.color_transform —— 色彩空间转换公开层。 | 0 | 3 |
| `render.dcp` | pixo.render.dcp —— DCP 解析与应用公开层。 | 0 | 1 |
| `render.params` | pixo.render.params —— 集中导出 Stage 参数 schema 与常量。 | 0 | 19 |
| `render.pipeline` ⚠️被同名包遮蔽 | pixo.render.pipeline —— Phase C 规划公开入口。 | 0 | 0 |
| `render.raw_loader` | pixo.render.raw_loader —— RAW 解码公开接入层。 | 0 | 1 |
| `render.tools.bench_e2e_loop` | pixo.render.tools.bench_e2e_loop —— P1-7 单张/批量端到端性能基准。 | 0 | 3 |
| `render.tools.bench_pipeline` | pixo.render pipeline 性能基准 (M5 / T5)。 | 0 | 5 |
| `render.tools.bench_preview` | pixo.render P1 全链路预览基准与回归 (v1.5 / t12)。 | 1 | 7 |
| `render.tools.gate_golden` | pixo.render 功能 golden 回归生成/对比工具 (t35, t108 扩四条默认路径)。 | 1 | 1 |

### 层 `render._native` —— pixo.render native C++ kernels (MinGW DLL, loaded via ctypes).

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `render._native` | pixo.render native C++ kernels (MinGW DLL, loaded via ctypes). | 15 | 1 |

### 层 `render.adjustments` —— pixo.render.adjustments —— Phase C 规划的调整模块公开目录。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `render.adjustments` | pixo.render.adjustments —— Phase C 规划的调整模块公开目录。 | 0 | 0 |
| `render.adjustments.clarity_dehaze` | adjustments.clarity_dehaze —— 清晰度/去朦胧公开接口。 | 0 | 3 |
| `render.adjustments.color_calibration` | adjustments.color_calibration —— 色彩校准公开接口。 | 0 | 1 |
| `render.adjustments.exposure` | adjustments.exposure —— 曝光调整公开接口。 | 0 | 1 |
| `render.adjustments.highlights_shadows` | adjustments.highlights_shadows —— 高光/阴影公开接口。 | 0 | 1 |
| `render.adjustments.hsl` | adjustments.hsl —— HSL 色彩调整公开接口。 | 0 | 2 |
| `render.adjustments.noise_reduction` | adjustments.noise_reduction —— 降噪公开接口。 | 0 | 1 |
| `render.adjustments.sharpening` | adjustments.sharpening —— 锐化公开接口。 | 0 | 1 |
| `render.adjustments.split_toning` | adjustments.split_toning —— 分离色调公开接口。 | 0 | 2 |
| `render.adjustments.tone_curve` | adjustments.tone_curve —— 影调/曲线公开接口。 | 0 | 3 |
| `render.adjustments.white_balance` | adjustments.white_balance —— 白平衡公开接口。 | 0 | 1 |

### 层 `render.core` —— render.core —— 核心引擎模块 (原生引擎核心)。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `render.core` | render.core —— 核心引擎模块 (原生引擎核心)。 | 0 | 7 |
| `render.core.calibration` | DCP (Adobe Camera Profile) 解析 —— 阶段0核心。 | 10 | 0 |
| `render.core.calibration_store` | render.core.calibration_store —— 标定 JSON 统一加载/缓存 (深审 L4/L5 治理收敛)。 | 4 | 0 |
| `render.core.color` | engine.color —— DCP 色彩链路纯函数模块 (数学层, 无 I/O)。 | 9 | 1 |
| `render.core.curves` | engine.curves —— 影调曲线原语 (全部查表实现, 单调、可微、无逐像素幂)。 | 5 | 0 |
| `render.core.enhance` | engine.enhance —— 观感增强纯函数 (clarity / dehaze), 解决"发灰/发暗/没质感"。 | 4 | 1 |
| `render.core.hsl` | engine.hsl —— 人工 HSL 八色段调整 (纯函数, 区别于 DCP 自动 HueSatMap)。 | 4 | 1 |
| `render.core.hsl_oklch` | engine.hsl_oklch —— OKLCh 域人工 8 色段调整 (band schema v2, M-O1)。 | 2 | 3 |
| `render.core.huesat` | engine.huesat —— DCP HueSatMap / LookTable 解码与应用 (纯函数, 无 I/O)。 | 4 | 7 |
| `render.core.io` | engine.decode —— RAW 解码 (采集层, 非 Style 插件)。 | 17 | 2 |
| `render.core.lut` | 3D LUT 风格映射 (阶段3) —— 复用 engine.lut3d (四面体插值 + .cube 1D shaper + DOMAIN)。 | 1 | 1 |
| `render.core.lut3d` | engine.lut3d —— 四面体 3D LUT (Kasson 1993) + .cube 解析 (1D shaper + DOMAIN)。 | 1 | 1 |
| `render.core.oklab` | engine.oklab —— Oklab / OKLCh 转换内核 (纯 numpy, M-O1 先行任务)。 | 4 | 0 |
| `render.core.resample` | render.core.resample —— Stage3 双程立方重采样 (原生实现)。 | 1 | 0 |
| `render.core.rp_ccm` | engine.rp_ccm —— 根多项式 CCM (Root-Polynomial Colour Correction Matrix)。 | 0 | 0 |
| `render.core.skin` | engine.skin —— 椭圆肤色掩码 + 引导滤波磨皮 (阶段2, T5)。 | 4 | 1 |
| `render.core.split_tone` | render.core.split_tone —— 分离色调 (split toning) 纯函数。 | 3 | 0 |
| `render.core.split_tone_oklab` | render.core.split_tone_oklab —— 分离色调 OKLab 域染色 (M-O1, 设计 §2.3)。 | 1 | 3 |
| `render.core.tone` | DNG Stage3 之后的影调/色彩可复用数值函数 (M1 clean-room 版). | 7 | 0 |
| `render.core.usercal` | engine.usercal —— 用户可调 RGB 校准 (shadow tint + 三原色 hue/sat)。 | 1 | 1 |
| `render.core.warp` | DNG WarpRectilinear（OpcodeList3）—— 独立纯 NumPy 实现。 | 2 | 0 |

### 层 `render.decide` —— render.decide 兼容 shim -> pixo.decide。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `render.decide` | render.decide 兼容 shim -> pixo.decide。 | 0 | 1 |
| `render.decide.engine` | render.decide.engine 兼容 shim -> pixo.decide.engine。 | 0 | 1 |
| `render.decide.rule_engine` | render.decide.rule_engine 兼容 shim -> pixo.decide.rule_engine。 | 0 | 1 |
| `render.decide.rules` | render.decide.rules 兼容 shim -> pixo.decide.rules。 | 0 | 1 |

### 层 `render.geometry` —— pixo.render.geometry —— Phase C 规划的几何公开目录。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `render.geometry` | pixo.render.geometry —— Phase C 规划的几何公开目录。 | 0 | 0 |
| `render.geometry.crop_rotate` | geometry.crop_rotate —— 裁剪/旋转公开接口。 | 1 | 1 |
| `render.geometry.smart_crop` | geometry.smart_crop —— 主体感知智能裁剪建议 (纯算法核心, 无 IO)。 | 1 | 1 |

### 层 `render.modules` —— render.modules —— 可调参数渲染模块 (原生实现, 独立注册)。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `render.modules` | render.modules —— 可调参数渲染模块 (原生实现, 独立注册)。 | 4 | 33 |
| `render.modules.calibration` | Stage calibration (order=51) —— 用户可调 RGB 校准 (gamma_rgb → gamma_rgb)。 | 3 | 3 |
| `render.modules.clarity` | render.modules.clarity —— 来自 render.modules.reshape。 | 4 | 1 |
| `render.modules.color_cal` | Stage colorcal (order=50) —— 色彩校准 (gamma_rgb → gamma_rgb, Lab 域)。 | 4 | 6 |
| `render.modules.compose` | Stage compose (order=22) —— 构图前置 (linear_rgb → linear_rgb)。 | 4 | 2 |
| `render.modules.dehaze` | render.modules.dehaze —— 来自 render.modules.reshape。 | 4 | 1 |
| `render.modules.denoise` | render.modules.denoise —— 来自 render.modules.reshape。 | 4 | 1 |
| `render.modules.exposure` | Stage exposure (order=10) —— 曝光矫正 (linear_cam 域, 场景参考)。 | 4 | 9 |
| `render.modules.hsl` | Stage hsl (order=52) —— 人工 HSL 八色段调整 (gamma_rgb → gamma_rgb)。 | 4 | 4 |
| `render.modules.huesat` | Stage huesat (order=25) —— DCP HueSatMap + LookTable 应用 (linear_rgb → linear_rgb)。 | 3 | 5 |
| `render.modules.refine` | Stage refine (order=70) —— 精修 (gamma_rgb → gamma_rgb, 显示域轻量打磨)。 | 3 | 4 |
| `render.modules.reshape` | engine.stages.reshape —— 影调重塑层 (Phase 1.5 实装)。 | 6 | 6 |
| `render.modules.sharpen` | render.modules.sharpen —— 来自 render.modules.reshape。 | 4 | 1 |
| `render.modules.skin` | Stage skin (order=55) —— 人像磨皮 (gamma_rgb → gamma_rgb)。 | 3 | 3 |
| `render.modules.split_tone` | Stage split_tone (order=54) —— 分离色调 (gamma_rgb → gamma_rgb)。 | 4 | 4 |
| `render.modules.style` | Stage stylize (order=60) —— 风格化 (gamma_rgb → gamma_rgb)。 | 3 | 3 |
| `render.modules.tone_map` | Stage tone (order=30) —— 影调 (linear_rgb → gamma_rgb)。 | 5 | 5 |
| `render.modules.white_balance` | Stage whitebalance (order=20) —— 白平衡 / 色彩矫正 (linear_cam → linear_rgb)。 | 5 | 7 |

### 层 `render.pipeline` —— render.pipeline —— 管线框架 (惰性导出, 避免循环 import)。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `render.pipeline` | render.pipeline —— 管线框架 (惰性导出, 避免循环 import)。 | 0 | 0 |
| `render.pipeline.base` | DCP 底座渲染 API: NEF/DNG + DCP -> 线性 sRGB (与 DNG SDK 对齐)。 | 1 | 6 |
| `render.pipeline.context` | engine.core —— 渲染引擎插件框架 (统一整合层)。 | 5 | 0 |
| `render.pipeline.graph` | render.pipeline.graph —— Stage 插件框架与 Pipeline (原生实现)。 | 30 | 2 |
| `render.pipeline.intents` | engine.intents —— EditIntent 编辑模型 + 修图意见解析 (阶段3, T1+T2)。 | 0 | 1 |
| `render.pipeline.presets` | render.pipeline.presets —— 默认管线组装 + JSON 配置驱动 (原生实现)。 | 7 | 3 |
| `render.pipeline.runner` | render.pipeline.runner —— 渲染执行公共样板 (三渲染入口收敛)。 | 4 | 3 |
| `render.pipeline.scene_apply` | engine.scene_apply —— 场景→风格预设注册表与应用 (阶段2, T4)。 | 1 | 0 |

### 层 `render.state` —— render.state 兼容 shim -> pixo.state。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `render.state` | render.state 兼容 shim -> pixo.state。 | 0 | 1 |
| `render.state.exceptions` | render.state.exceptions 兼容 shim -> pixo.state.exceptions。 | 0 | 1 |
| `render.state.machine` | render.state.machine 兼容 shim -> pixo.state.machine。 | 0 | 1 |
| `render.state.store` | render.state.store 兼容 shim -> pixo.state.store。 | 0 | 1 |
| `render.state.trace` | render.state.trace 兼容 shim -> pixo.trace。 | 0 | 1 |

### 层 `render.web` —— pixo.render Web/自动化预览输出模块（v1.5，不含前端 UI）。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `render.web` | pixo.render Web/自动化预览输出模块（v1.5，不含前端 UI）。 | 0 | 0 |
| `render.web.encode` | pixo.render Web/自动化输出编码器（v1.5）。 | 2 | 0 |
| `render.web.export` | pixo.render 最终全质量 export 层（t32）。 | 2 | 4 |
| `render.web.session` | pixo.render 预览会话与缓存增量（v1.5）。 | 2 | 5 |

### 层 `review` —— pixo.review —— 人工复核队列、报告与 Trace 导出（P2-4）。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `review` | pixo.review —— 人工复核队列、报告与 Trace 导出（P2-4）。 | 1 | 4 |
| `review.models` | pixo.review.models —— 人工复核队列实体。 | 4 | 0 |
| `review.queue` | pixo.review.queue —— 人工复核队列与审核动作。 | 1 | 3 |
| `review.report` | pixo.review.report —— 复核 CSV / HTML 报告生成。 | 1 | 1 |
| `review.trace_export` | pixo.review.trace_export —— 单张 Trace JSON / 多张 CSV 导出。 | 1 | 1 |

### 层 `service` —— pixo.service —— Pixo 本地 FastAPI 服务。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `service` | pixo.service —— Pixo 本地 FastAPI 服务。 | 1 | 2 |
| `service.__main__` | pixo.service.__main__ —— 本地启动入口。 | 0 | 1 |
| `service.app` | pixo.service.app —— FastAPI 本地服务应用。 | 2 | 2 |
| `service.loop` | pixo.service.loop —— 单张闭环兼容入口。 | 0 | 1 |
| `service.runtime` | pixo.service.runtime —— Pixo 本地服务运行时。 | 2 | 8 |

### 层 `state` —— pixo.state —— Pixo State（照片状态机）。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `state` | pixo.state —— Pixo State（照片状态机）。 | 4 | 4 |
| `state.exceptions` | pixo.state.exceptions —— 状态机与 Trace 异常。 | 3 | 0 |
| `state.machine` | pixo.state.machine —— 照片状态机与服务端强校验。 | 7 | 2 |
| `state.photo_state` | pixo.state.photo_state —— 照片状态模型兼容入口。 | 0 | 1 |
| `state.state_machine` | pixo.state.state_machine —— 状态机兼容入口。 | 0 | 1 |
| `state.store` | pixo.state.store —— SQLite 状态与 Trace 持久化。 | 2 | 2 |

### 层 `trace` —— pixo.trace —— 参数级溯源事件模型与查询。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `trace` | pixo.trace —— 参数级溯源事件模型与查询。 | 5 | 2 |
| `trace.query` | pixo.trace.query —— Trace 事件查询/过滤。 | 1 | 1 |
| `trace.recorder` | pixo.trace.recorder —— 参数级溯源事件模型。 | 2 | 0 |

### 层 `vision` —— pixo.vision —— Pixo Vision 视觉感知基础包（P0-2）。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `vision` | pixo.vision —— Pixo Vision 视觉感知基础包（P0-2）。 | 9 | 8 |
| `vision.aesthetic` | pixo.vision.aesthetic —— 7 维美学评分器。 | 4 | 0 |
| `vision.base` | pixo.vision.base —— Segmenter 对外契约与基类。 | 9 | 1 |
| `vision.exceptions` | pixo.vision.exceptions —— 分割模块异常与降级约定。 | 11 | 0 |
| `vision.geometry` | pixo.vision.geometry —— 水平线检测/自动扶平。 | 2 | 0 |
| `vision.health` | pixo.vision.health —— Pixo Vision 模型健康检查。 | 1 | 4 |
| `vision.measure` | pixo.vision.measure —— Pixo Vision 区域/全局测量。 | 3 | 0 |
| `vision.mock` | pixo.vision.mock —— MockSegmenter 合成 mask，用于测量/闭环测试。 | 2 | 2 |
| `vision.person` | pixo.vision.person —— FairFace 年龄/性别辅助接口。 | 2 | 0 |
| `vision.segmenter` | pixo.vision.segmenter —— Segmenter 接口便捷入口。 | 0 | 3 |

### 层 `vision.segmenters` —— pixo.vision.segmenters —— 真实分割模型适配器。

| 模块 | 职责 (docstring 首行) | 入度 | 出度 |
|---|---|---|---|
| `vision.segmenters` | pixo.vision.segmenters —— 真实分割模型适配器。 | 0 | 0 |
| `vision.segmenters.common` | segmenters/common —— 多模型适配器共享助手（无第三方重依赖）。 | 7 | 1 |
| `vision.segmenters.grounded_sam` | pixo.vision.segmenters.grounded_sam —— 开放词汇分割适配器（可选懒加载）。 | 1 | 3 |
| `vision.segmenters.multi_router` | pixo.vision.segmenters.multi_router —— prompt 路由多模型 Segmenter。 | 2 | 8 |
| `vision.segmenters.rfdetr_person` | pixo.vision.segmenters.rfdetr_person —— 人物实例分割适配器。 | 1 | 4 |
| `vision.segmenters.sapiens_body` | pixo.vision.segmenters.sapiens_body —— Sapiens 部位解析适配器（t91 + t99 守卫）。 | 1 | 3 |
| `vision.segmenters.segformer_scenes` | pixo.vision.segmenters.segformer_scenes —— 场景语义分割适配器。 | 1 | 3 |
| `vision.segmenters.uniface_face` | pixo.vision.segmenters.uniface_face —— 人脸解析适配器（UniFace/BiSeNet 位）。 | 1 | 3 |

## 外部依赖清单 (隔离位置)

来自 AST 全量扫描 (模块级 + 嵌套懒加载, 含行号)。`all_nested=true` 表示该依赖从不做模块级导入 —— 全部延迟到函数内, 即懒加载隔离。

| 依赖 | 使用点数 | 所在层 | 懒加载 | 隔离位置 (module:line) |
|---|---|---|---|---|
| PIL | 1 | vision.segmenters | 是 | `vision.segmenters.grounded_sam:71` |
| cv2 | 23 | pipeline, render, render.core, render.modules, render.pipeline, render.web, vision, vision.segmenters | 否 | `pipeline.loop:26`, `render.api:23`, `render.api:130`, `render.api:247`, `render.core.enhance:13`, `render.core.huesat:505`, `render.core.skin:25`, `render.modules.color_cal:30`, `render.modules.compose:27`, `render.modules.exposure:206` …共 23 处 |
| exifread | 2 | meta, render.pipeline | 是 | `meta.exif:498`, `render.pipeline.base:22` |
| fastapi | 3 | service | 否 | `service.app:12`, `service.app:13`, `service.app:14` |
| numpy | 63 | agent, harness.goldens, pipeline, render, render._native, render.core, render.geometry, render.modules, render.pipeline, render.web, vision, vision.segmenters | 否 | `agent.burst_selection:16`, `harness.goldens.compare:11`, `harness.goldens.samples:9`, `pipeline.batch:22`, `pipeline.loop:27`, `render._native:25`, `render.api:13`, `render.api:248`, `render.core.calibration:21`, `render.core.calibration:508` …共 63 处 |
| onnxruntime | 2 | vision | 是 | `vision.person:52`, `vision.person:87` |
| rawpy | 9 | pipeline, render, render.core, render.pipeline, render.web | 否 | `pipeline.batch:620`, `pipeline.loop:354`, `render.api:131`, `render.api:249`, `render.core.io:17`, `render.pipeline.base:12`, `render.tools.bench_preview:92`, `render.tools.bench_preview:132`, `render.web.session:24` |
| rfdetr | 1 | vision.segmenters | 是 | `vision.segmenters.rfdetr_person:41` |
| scipy | 1 | render.core | 是 | `render.core.color:487` |
| torch | 13 | vision, vision.segmenters | 是 | `vision.aesthetic:74`, `vision.aesthetic:101`, `vision.aesthetic:148`, `vision.aesthetic:149`, `vision.aesthetic:212`, `vision.segmenters.grounded_sam:44`, `vision.segmenters.grounded_sam:70`, `vision.segmenters.sapiens_body:171`, `vision.segmenters.sapiens_body:246`, `vision.segmenters.segformer_scenes:47` …共 13 处 |
| transformers | 6 | vision, vision.segmenters | 是 | `vision.aesthetic:102`, `vision.aesthetic:150`, `vision.segmenters.grounded_sam:45`, `vision.segmenters.sapiens_body:172`, `vision.segmenters.segformer_scenes:48`, `vision.segmenters.uniface_face:41` |
| uvicorn | 1 | service | 否 | `service.__main__:8` |
| yaml | 2 | decide, know | 是 | `decide.engine:257`, `know.graph:251` |

标准库使用汇总 (计数, 不建边): __future__×155, abc×3, argparse×5, ast×1, collections×8, concurrent×3, contextlib×2, copy×8, csv×2, ctypes×2, dataclasses×19, datetime×10, hashlib×5, html×1, importlib×4, io×2, json×27, logging×20, math×7, numbers×3, os×17, pathlib×46, re×6, sqlite3×1, statistics×2, struct×3, sys×7, tempfile×1, threading×6, time×10, types×1, typing×62, urllib×2, uuid×3, warnings×2

## 合并的外部片段 (t15)

- `K:/work/project/pixo/docs/project_graph_frontend.json` (origin=project_graph_frontend): +85 节点, +129 边
