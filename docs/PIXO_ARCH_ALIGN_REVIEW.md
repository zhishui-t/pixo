# Pixo 架构对齐评审与实施路线（PIXO_ARCH_ALIGN_REVIEW）

> 版本：v1.0（架构评审稿）
> 日期：2026-08-22
> 评审人：架构师（Pixo 团队）
> 代码基线：`$PIXO_ROOT/pixo` @ `7c737a6 refactor: 迁移至 render 包并全量改名 RawLux -> Pixo Render`
> 评审对象：`docs/架构设计文档.md`（v0.1.0rc，917 行）
> 交付范围：差距表 / 管线顺序确认 / guanlan 复用评估 / 风险与对策 / DSH Agent 与前端打包方案 / P0-P2 路线图

---

## 0. 结论摘要（TL;DR）

1. **渲染底座与文档基本对齐，但命名空间不一致**：文档规划的 `pixo.render` 目前实际包路径是顶层 `render/`（`import render`）。代码与 render 内部文档大量使用 `pixo.render` 标识，但 Python 包结构尚未落成。这是一项**必须在产品化前解决、但不应阻断功能开发**的 P1 重构项。
2. **“构图前置”确认是 P0 缺口**：当前 render 管线**没有任何 crop/rotate 构图 Stage**（文档写“原在管线末端”已过时）。`core/warp.py` 只是 DNG OpcodeList3 的 WarpRectilinear 实现，不是用户构图。构图是视觉闭环的几何前提（mask 与测量区域必须先定框），必须最先补。
3. **guanlan 复用价值高，但不是“拿来即用”**：`rules/*`（曝光裁切、锐度/脱焦、色彩统计、运动模糊、连拍分组、光线判定）与 `scoring/frame_scorer.py` 大部分是 **cv2+numpy/rawpy 纯算法**，可直接迁移或轻适配；`vision/aesthetic.py`、`vision/fairface_age.py`、`vision/horizon_det.py` 可直接复用；**`yoloe_det.py` 当前只输出检测框，不输出分割 mask**（虽然权重是 `yoloe-26l-seg.pt`），且是 ultralytics 直连实现，需要改造成 `Segmenter` 接口适配器并补 mask 提取；`scene_probe.py`/`structure_info.py` 与 LR 业务耦合过深，只参考其多轮补采与充分性评估思路。
4. **YOLOE-26L-seg 的 AGPL-3.0 是真实产品化阻断项**：内部研发可用，对外发布必须换 Apache/MIT 模型或购买 Ultralytics 企业授权。本次方案将其严格隔离在单个 `Segmenter` 适配器内，并给出替代路线（Grounding-DINO + SAM 系等）。
5. **单张 ≤30s、批量 ≥2 张/分钟的预算“勉强可达但有条件”**：关键优化是**分割只在构图后的 preview 上跑一次、mask 在 3 轮迭代中复用**；否则 CPU 推理的 YOLOE-26L 会把预算吃穿。全分辨率 NEF 渲染 ~10.8s 是主要成本，批量吞吐需 2 个并行 worker。
6. **打包形态建议**：先 **Web+PWA（本地 FastAPI 服务 + DSH Web 宿主）**；桌面用 **Tauri + Python sidecar（PyInstaller）**；手机先做 **局域网远程客户端（Expo/React Native）**，不重写引擎。Flutter/原生重写不推荐。
7. **必须立即修正的文档漂移**：render/README 基线（597 vs 当前 498 收集）、根 requirements.txt 仍写 “rawlab”、bench JSON/工具默认路径仍指向 `$PIXO_ROOT/RawFlow`。这些不影响运行但会造成后续误判。

---

## 1. 评审方法与证据来源

- 逐节通读 `docs/架构设计文档.md`（917 行，第 1–19 节）。
- 实测盘点 render 包结构、全部 Stage 注册（`@register_stage` + order）、默认管线 `DEFAULT_STAGES`、`Pipeline.run_file` 解码路径。
- 实测盘点 guanlan `src/vision|rules|data_pipeline|scoring` 共约 8,036 行代码与 `config/vision.yaml`。
- 查阅 render 侧既有证据文档：`PIXO_RENDER_STATUS_20260820.md`、`FUNCTION_GATE_SPEC.md`、`PIXO_RENDER_PERFORMANCE_REVIEW.md`、`T25_REAL_NEF_PERFORMANCE_REPORT.md` 与 bench JSON 基线。
- 本机环境实测：`torch`/`ultralytics`/`onnxruntime`/`transformers` 可用，`mediapipe` 未安装；`pytest --collect-only` 当前收集 498 例（render/tests）+ 51 例（gate）。

---

## 2. “文档规划 vs 当前实现”差距总表

| # | 模块 | 文档规划（`架构设计文档.md`） | 当前实现（基线 7c737a6） | 差距判定 | 动作 |
|---|---|---|---|---|---|
| 1 | **Pixo Render** | 命名空间 `pixo.render`；RAW 解码→WB→DCP→构图→曝光→高光/阴影→曲线→色彩校准→HSL→色调分离→清晰度/去朦胧→降噪→锐化→输出 | 实际包名 `render`；15+ core 原语、18 个 modules、Stage 插件管线、native C++ 内核齐全；**无构图 Stage**；降噪/锐化合并在 `refine`（独立 `denoise`/`sharpen` 为占位）；管线顺序与文档不同（见 §3） | **功能 85% 对齐，顺序与命名不一致** | P0：补 `compose` Stage；P1：包命名 `pixo.render` 化；同步文档顺序图 |
| 2 | **Pixo Vision** | `pixo.vision`：YOLOE-26L-seg 分割 + 区域测量 + 7 维美学评分 | Pixo 仓库**无 vision 包**；guanlan 有检测（框）代码、无 mask 提取 | **0%，P0-P1 新建设** | 从 guanlan 迁移改造（§4），建 `pixo/vision/` |
| 3 | **Pixo Meta** | `pixo.meta`：EXIF 提取/标准化、场景推断、连拍分组 | 仅有 `pipeline/base.py::camera_key` 用 exifread 读 3 个字段 | **约 5%** | P1：迁移 guanlan `burst_grouping`、`daylight`，新建 EXIF schema |
| 4 | **Pixo Decide** | `pixo.decide`：规则引擎、优先级链、终止判断、QC 回退 | 无 Decide；`pipeline/intents.py` 的 `EditIntent/parse_feedback/apply_intents` 是确定性规则解析的**可复用地基** | **约 15%** | P1：在其上建规则引擎（guanlan `color_rules.yaml` 模式） |
| 5 | **Pixo Know** | 知识图谱 + RAG + 风格卡片 | 无；`presets/scenes.json` 与 `lut` 注册表可视为最小“风格知识” | **约 5%** | P2：先落风格卡片 schema，图谱/RAG 后置 |
| 6 | **Pixo Agent** | DSH 主会话 + 原生视觉 + 工具调用 | 无集成；DSH 环境已具备视觉模型与热加载插件能力（`~/.dsh/profiles/web/cordis.patch.yml`） | **0% 集成** | P2：pixo-service + DSH 工具插件（§6） |
| 7 | **Pixo State** | 照片状态机 + 任务队列 | 无状态机；`web/session.py`（预览会话/参数指纹/generation）与 `web/export.py`（任务 submit/status/wait）是**会话与任务雏形** | **约 15%** | P1：在其上建 SQLite 状态机与任务队列 |
| 8 | **Pixo Review** | 复核队列、人工标注 | 无 | **0%** | P2：复核队列 UI + API |
| 9 | **Pixo Harness** | 批量渲染、指标计算、自动化测试 | **超出规划**：51 个 gate 测试、golden 回归、bench_preview/pipeline、native 等价测试、`run_all_tests.bat` 六步硬门禁 | **100%+** | 继续作为所有新功能的准入门禁 |
| 10 | **Pixo Trace** | 参数来源、决策记录 | 部分：`StageResult` 记录各 Stage 耗时/指标、`Pipeline.to_config` 可重建管线；**无参数级溯源记录** | **约 15%** | P1：在 service 层写参数溯源（沿用文档 §13 schema） |

补充的文档/仓库一致性缺口：

| 缺口 | 现状 | 影响 |
|---|---|---|
| `render/api` 目录 | 文档与任务描述写 `render/api`，实际是 `render/api.py` 单文件 + `render/web/*` | 命名歧义，写文档时统一为 `render.api` 模块 |
| README 测试基线 | `render/README.md` 写 “597 passed”，当前收集 498（496 passed/1 skip/1 xfailed 口径） | 状态文档漂移 |
| 根 requirements | 仍写 `# rawlab 运行时依赖` | 命名残留 |
| bench/工具默认路径 | `bench/*.json`、`gate_golden.py` 示例仍指向 `$RAWFLOW_ROOT/...` | 换仓后门禁示例不可复现 |
| 历史文件名 | `RAWLAB_MASTER_PLAN.md`、`RAWLAB_ADJUSTMENTS_PLAN.md` 等仍存在 | 已删除 rawlab，历史文档应归档改名 |

---

## 3. render 管线现状与 P0 构图缺口

### 3.1 实际管线（代码事实，基线 7c737a6）

`Pipeline.run_file` 先 `decode_raw`（rawpy，AHD/CFA 半尺寸，输出 `linear_cam`），再按 `DEFAULT_STAGES` 顺序执行：

| 执行序 | Stage | order | 域 | 职责（当前实现） |
|---|---|---|---|---|
| 0（非 Stage） | `decode_raw` | — | → `linear_cam` | RAW 解码，输出未乘 WB 的相机 RGB float32 |
| 1 | `exposure` | 10 | `linear_cam→linear_cam` | 曝光 EV（auto/baseline/manual，含高光软滚降） |
| 2 | `whitebalance` | 20 | `linear_cam→linear_rgb` | WB（as_shot/auto/manual/向量）+ **DCP 色彩矩阵链路（CM/FM/Bradford）+ 高光中性化**，即文档中“DCP 应用”实际发生在这里 |
| 3 | `huesat` | 25 | `linear_rgb→linear_rgb` | DCP HueSatMap/LookTable（默认关，标定用） |
| 4 | `tone` | 30 | `linear_rgb→gamma_rgb` | EOTF/亮度/对比/六键（Highlights/Shadows/Whites/Blacks）/用户曲线 |
| 5 | `clarity` | 46 | `gamma_rgb→gamma_rgb` | 清晰度（默认开 0.3） |
| 6 | `colorcal` | 50 | `gamma_rgb→gamma_rgb` | saturation/vibrance/场景曲线/肤色保护/gamut soft |
| 7 | `calibration` | 51 | `gamma_rgb→gamma_rgb` | 用户 RGB 校准 |
| 8 | `hsl` | 52 | `gamma_rgb→gamma_rgb` | 八段 HSL |
| 9 | `split_tone` | 54 | `gamma_rgb→gamma_rgb` | 分离色调 |
| 10 | `skin` | 55 | `gamma_rgb→gamma_rgb` | 磨皮（wants 门控，仅人像） |
| 11 | `stylize` | 60 | `gamma_rgb→gamma_rgb` | LUT 风格化 |
| 12 | `refine` | 70 | `gamma_rgb→gamma_rgb` | 锐化 + 色度降噪 + 高光去色 + 暖色保护（**实际承担文档里的锐化/降噪**） |

另注册但不在默认链：`dehaze`(45)、`denoise`(47 占位)、`sharpen`(48 占位)、`vibrance`(49 占位)。

### 3.2 与文档规划顺序的差异判定

文档规划：`RAW解码 → 白平衡 → DCP → 构图 → 曝光 → 高光/阴影 → 曲线 → 色彩校准 → HSL → 色调分离 → 清晰度/去朦胧 → 降噪 → 锐化 → 输出`。

实际差异与结论：

1. **曝光在 WB/DCP 之前（linear_cam）**：EV 是对三通道同乘标量，与 WB/色彩矩阵可交换，**数学语义等价**；且当前曝光锚点探针本身会模拟 WB×CM 变换后在线性 sRGB 域定标，无需按文档重排。
2. **“DCP”不是独立 Stage**：已折叠进 `whitebalance` 的矩阵链路。对外文档应改为“WB+DCP 色彩链路”一步，避免实施者误建重复 Stage。
3. **高光/阴影、曲线**：由 `tone` Stage 统一承担（六键+EOTF+用户曲线），能力覆盖文档拆分。
4. **降噪/锐化在 refine 内嵌，末端顺序为“锐化+降噪合并处理”**：与文档“先降噪后锐化”的严格顺序不同。refine 当前是“锐化→色度降噪→高光去色”的观感组合，**若要严格物理顺序需在 P1 拆 Stage**；当前门禁已绿，不建议为顺序而顺序，可列为可选优化。
5. **构图完全缺失**：grep 证实 `crop/rotate/flip` 无任何管线实现（`modules/reshape.py` 只是“影调重塑层”占位文件）。文档 §7.2 写“原在管线末端，需前置改造”**已过时**——现在是没有，不是位置不对。

### 3.3 P0 判定：构图前置是 P0，且是视觉闭环的硬前置

构图改变画面内容与 mask 几何。若先建 Vision 再补构图，所有 mask/测量/金样本都要返工。因此 **compose 必须排在 Segmenter 之前交付**。

**推荐设计（`compose` Stage）**：

- 注册名 `compose`，**order=22**，域 `linear_rgb→linear_rgb`，插入 `whitebalance` 之后、`huesat` 之前。
- 语义：此时已完成 WB+DCP 色彩链路（即文档“DCP 后”），且所有影调/色彩调整在构图后像素上执行，mask 几何与最终画面一致。
- 参数（对齐文档 §7.4，补自动扶平）：

```json
{
  "compose": {
    "mode": "ratio|free|auto_level",
    "ratio": "3:2",
    "center": [0.5, 0.5],
    "rotation": 0.0,
    "horizontal_flip": false,
    "vertical_flip": false,
    "x": 0, "y": 0, "width": 0, "height": 0
  }
}
```

- 实现要求：
  - 纯整数裁剪/翻转走 **精确切片/轴翻转，必须逐位一致**（比文档的 ≤1e-4 更严）。
  - 含旋转走 `cv2.warpAffine + INTER_LANCZOS4`，边界反射/复制策略写入 Trace。
  - 归一化坐标语义：preview 先缩到 long_edge 再应用 compose，全分辨率直接应用；两者 A/B 门禁沿用 `p50 ≤2/255、p99 ≤10/255`。
  - 输出几何元数据（最终尺寸、变换矩阵、crop 矩形）进 `ctx.state`，供 Vision 记录 mask 坐标。
- 验收（承接文档 §7.3）：
  - 纯裁剪/翻转：与参考实现逐位一致（`np.array_equal`）。
  - 含旋转：PSNR ≥ 60dB 或平均 ΔE < 0.5。
  - 等价测试：同尺寸同位置旋转对比。
  - gate 新文件 `test_gate_compose.py`，并纳入 `run_all_tests.bat` 六步门禁。
- 自动扶平（P1 可选）：接入 guanlan `horizon_det.detect_horizon_angle`，输出 `auto_level` 建议值，由用户确认后写入 rotation（不自动强改）。

---

## 4. guanlan 复用/迁移评估

### 4.1 分模块复用结论（LOC 为实际行数）

| guanlan 模块 | LOC | 依赖 | 复用方式 | 迁移去向 |
|---|---|---|---|---|
| `vision/yoloe_det.py` | 612 | torch + ultralytics + `yoloe-26l-seg.pt` + `mobileclip2_b.ts` | **核心改造**：保留 prompt-free 94 词固化与多轮兜底，改为 `Segmenter` 适配器，**新增 mask 输出** | `pixo/vision/segmenters/yoloe.py` |
| `vision/detector.py` | 85 | 仅门面 | 轻适配：统一“模型未就绪→None→降级”契约 | `pixo/vision/segmenters/base.py` |
| `vision/aesthetic.py` | 132 | torch + transformers + 350MB 权重 | **直接迁移**（7 维 → 文档 5.4 的 7 维键名映射） | `pixo/vision/aesthetic.py` |
| `vision/horizon_det.py` | 109 | cv2 | 直接迁移 | `pixo/vision/geometry.py` |
| `vision/fairface_age.py` | 143 | onnxruntime + fairface.onnx | 直接迁移（CC BY 4.0，需署名；P2 可选） | `pixo/vision/person.py` |
| `vision/clip_zeroshot.py` / `clip_hier.py` | 270/204 | onnxruntime + 中文 CLIP 750MB | 可选迁移：**语义上下文进 Meta/Know，不作为硬事实** | `pixo/know/context.py` |
| `vision/scene_probe.py` / `structure_info.py` | 1338/603 | 全模型 + LR 语义 | **仅参考**：多轮补采/充分性评估/融合投票思路；业务耦合太重不整搬 | 设计参考 |
| `vision/content_axis.py` | 202 | cv2 + 嵌入预览 | 适配：构图建议/内容轴 | `pixo/vision/composition.py`（P2） |
| `vision/nima.py` | 132 | onnx（模型从未下载） | 不迁移，由 aesthetic 替代 | — |
| `vision/lut_apply.py` | 128 | cv2 | 不迁移（render `stylize`/`core.lut` 已拥有 LUT） | — |
| `rules/color_stats.py` | 119 | cv2+numpy | **直接迁移**（全图 LAB/HSV/暖色占比） | `pixo/vision/measure.py` global 部分 |
| `rules/exposure.py` | 111 | rawpy+cv2 | 直接迁移（RAW 域裁切检测） | `pixo/vision/measure.py` / `pixo/meta/quality.py` |
| `rules/zone_exposure.py` | 222 | rawpy+numpy | 直接迁移（分区曝光） | `pixo/vision/measure.py` |
| `rules/sharpness.py` | 391 | cv2+numpy | 直接迁移（Laplacian/FFT/主体锐度） | `pixo/vision/measure.py` |
| `rules/motion_blur.py` | 138 | cv2+numpy | 直接迁移（频域方向模糊） | `pixo/vision/measure.py` |
| `rules/haze.py` | 64 | cv2 | 直接迁移 | `pixo/vision/measure.py` |
| `rules/eye_detection.py` | 353 | mediapipe + YuNet + landmarker 模型 | 适配迁移（Pixo 环境需补 mediapipe；模型许可需核验） | `pixo/vision/person.py`（P2） |
| `rules/light_direction.py` / `opencv_lighting.py` | 182/163 | cv2 + 人脸 landmark | 适配迁移（光场上下文 → Meta 场景推断） | `pixo/meta/lighting.py` |
| `rules/scene_analysis.py` | 129 | cv2+numpy | 直接迁移，随后被 YOLOE+CLIP 增强 | `pixo/meta/context.py` |
| `rules/photo_profiler.py` | 220 | cv2+numpy | 适配迁移（阈值配置化） | `pixo/vision/measure.py` |
| `rules/burst_grouping.py` | 327 | exifread | **直接迁移**（时间/焦距/曝光三维聚类） | `pixo/meta/burst.py` |
| `rules/daylight.py` | 141 | datetime | 直接迁移（时间+GPS 光照） | `pixo/meta/lighting.py` |
| `rules/color_rules.py` | 109 | yaml | 模式复用（规则配置加载） | `pixo/decide/rules_loader.py` |
| `rules/semantic_mapper.py` | 321 | 无重依赖 | **适配重写**：当前把语义映射到 LR 参数，改为 Decide 参数目标 | `pixo/decide/semantic.py` |
| `scoring/frame_scorer.py` | 144 | numpy | 直接迁移（锐度/EAR/构图三维评分） | `pixo/review/scoring.py` |
| `data_pipeline/extract.py` | 236 | `src.engine.diagnosis` + 上述模块 | **拆解适配**：去掉 LR 字段，拆成 vision/meta/measure 三条独立入口 | 架构参考 |
| `data_pipeline/csv_store.py` | 226 | csv | 适配（列 schema 换 Pixo Record） | `pixo/state/report.py` |
| `data_pipeline/map_lr.py` | 208 | 无重依赖 | 适配（LR 星级/颜色标签 → Pixo 复核优先级/评级） | `pixo/review/map.py` |
| `config/vision.yaml` | 187 | yaml | 拆分配置：模型路径/阈值进 `pixo/vision`，LR 写回段删除 | `config/vision.yaml` |

### 4.2 用户判断“视觉已有代码，只需换 YOLOE-26L-seg”的核实结论

- guanlan **已经在用** `yoloe-26l-seg.pt`（2026-08-11 起替代 yolo26n），prompt-free 94 词固化、文本模式多轮兜底、物种细分都写好了——**“已有代码”属实**。
- 但当前 `YoloeDetector.detect()` **只返回 `{label, conf, box, area_ratio, elapsed_ms}`，从不读取 `results[0].masks`**；Pixo 文档 §5 要求的是 `face/sky/plant` 等**实例 mask + 区域测量**。因此“只换模型”不够，还需要：
  1. `segment(image, prompts) -> dict[prompt, mask]`：走 `model.predict(..., retina_masks=True)` 或读取 `result.masks.xy/data`，把多个实例 mask 按 prompt 词合并/编号（`face_0/face_1`）。
  2. 区域测量：迁移/新写 mask 上的 Lab/亮度/溢出率/对比度统计（文档 §5.4 的 global 字段可直接用 `rules/color_stats.py` + 直方图实现）。
  3. 可靠性规则：conf < 0.6 或 area < 0.5% → `reliable=false`（文档 §5.4）。
  4. 输入域统一：guanlan 契约是 BGR uint8，Pixo 内部是 RGB float32（gamma 域测量）——适配器负责转换，不改引擎。
  5. AGPL 隔离：ultralytics/YOLOE 的所有 import 只能出现在 `segmenters/yoloe.py` 一个文件内。

### 4.3 Pixo Vision 目标接口（冻结对外契约，内部可换）

```python
class Segmenter(Protocol):
    def segment(self, image_rgb: np.ndarray, prompts: list[str]) -> dict[str, np.ndarray]:
        """返回 {'face': mask_uint8(H,W), ...}；不可用时抛 SegmenterUnavailable"""

class VisionMeasure:
    def measure_region(self, image_rgb, mask, metrics) -> RegionMeasurement
    def measure_global(self, image_rgb) -> GlobalMeasurement

class AestheticScorer:
    def score(self, image_rgb) -> AestheticScores   # 仅进 Trace/复核排序
```

实现顺序：`MockSegmenter`（合成 mask，先打通闭环）→ `YoloeSegmenter`（guanlan 改造）→ 后续备选 `GroundingDinoSamSegmenter`。所有模型加载沿用 guanlan 的“加载失败返回 None、上层降级”约定，并新增 `vision_health()` 供 DSH Agent 与 UI 显示模型可用性。

---

## 5. 架构文档问题与风险评估

### 5.1 `pixo.render` 命名空间 vs 实际 `render` 包

- **问题**：文档/代码注释/README 全部自称 `pixo.render`，但 `import render` 才是现实；没有 `pyproject.toml`/`setup.py`，包不可安装、只能靠 PYTHONPATH。
- **影响**：后续 `pixo.vision`、`pixo.meta` 等新包落地时，若渲染层叫 `render`、视觉层叫 `pixo.vision`，会出现两套命名体系并存的长期技术债；工具链、插件、打包入口都要写死顶层包名。
- **决策**：**采用 src-layout 统一到 `pixo.*` 命名空间**：
  - P1 建 `pixo/render/`（物理移动 render 包），保留 1 个版本的 `render` 兼容别名（`sys.modules` shim）给 CLI/测试过渡。
  - 同步新增 `pyproject.toml`（包名 `pixo`，extras：`[pixo-render]`、`[pixo-vision]`）。
  - 迁移期间 CI 同时跑 `import pixo.render` 与 `import render` 双入口，绿后再删 shim。
- **不采用**：把整个项目再改名回 `render` 规范文档——因为后续模块都挂在 `pixo` 下，长痛不如短痛。

### 5.2 YOLOE-26L-seg 许可（AGPL-3.0）

- **事实**：Ultralytics YOLOE 开源许可为 AGPL-3.0（企业授权另售）；`mobileclip2_b.ts` 文本编码器权重随模型链下载，其许可需一并核验。
- **风险传导**：AGPL 的“网络服务亦触发源码义务”特性，对本地桌面应用**主要影响分发**（需开源整应用或购买企业授权），对云端修图服务是**直接阻断**。
- **决策**：
  1. 研发期可用，**不得进入任何对外发布产物**。
  2. 所有 YOLOE/ultralytics 依赖收敛到 `pixo/vision/segmenters/yoloe.py` 单文件 + `model_licenses.json` 登记。
  3. 阶段 2 Gate 增加硬检查：`grep -RIn ultralytics pixo --include="*.py" | wc -l` 仅允许命中 1 个文件。
  4. 替代路线（按优先级）：① Grounding-DINO（Apache-2.0）+ SAM2/SAM 系 mask 后处理（Apache-2.0）；② 购买 Ultralytics Enterprise License；③ 蒸馏到自有小模型。
  5. FairFace 为 CC BY 4.0（可商用、需署名）；MediaPipe Apache-2.0；中文 CLIP/aesthetic-scorer 许可在迁移时逐项登记（文档 §5.3 写“MIT”需留档核验）。

### 5.3 视觉/决策闭环依赖与稳定性

- **单点依赖链**：Decide 全部输入来自 Vision；Vision 失败时若不兜底，整条自动管线停摆。文档已有 `manual_review` 兜底，**必须把“模型未就绪”也映射为 `manual_review`**（guanlan 的降级约定只覆盖模型加载，不覆盖“关键区域不可靠但用户要求自动修”的语义）。
- **版本锁定**：测量必须同时记录 `render_version`、`detection_version`、`mask_version`（mask 版本文档未列，需补），否则回归不可解释。
- **迭代收敛**：`step_decay` 快速收敛 + 3 轮上限 + QC 回退 1 次的设计自洽；但要把“回退后再次超标”与“Agent 升级”在状态机里做成**不可绕过的服务端校验**，不能让 LLM 自己决定重试。
- **建议补一条规则**：`AGENT_ESCALATED` 必须携带 `reason` 与引用轮次，空理由拒绝转移。

### 5.4 性能预算

以当前实测为锚（NEF `DSC_5236`）：

| 环节 | 实测/估算 | 说明 |
|---|---|---|
| preview 渲染（1024 hot） | **414ms**（NEF）/ 296ms（DNG） | gate 已绿 |
| preview 渲染（2048 hot） | 1188ms（NEF） | gate 已绿 |
| 全分辨率 NEF 渲染 | **≈10.8s** | 每张仅最终 QC 1 次 |
| YOLOE-26L 推理 | guanlan 注释 GPU ≈40ms；**CPU 未实测，估 1–4s** | 最大不确定项 |
| aesthetic-scorer | 0.5–1s | 文档口径 |
| 区域测量（numpy/cv2） | <0.1s（1024） | 纯统计 |

- **结论**：单张 ≤30s 可达，但有两个前提：
  1. **mask 只算一次**：构图完成后在 1024 preview 上跑一次 `segment`，3 轮迭代仅重渲染+重测量，mask 复用（几何不变）。若每轮都跑 YOLOE，CPU 下 3×3s=9s 仍可能过，但余量变小。
  2. 全分辨率最终 QC 用**上采样 mask**测量，不再全图重跑 YOLOE；仅在 mask 置信度不足时升级到全图检测。
- **批量 ≥2 张/分钟**：单 worker 的 10.8s 全分辨率渲染会卡线（2×10.8=21.6s + 视觉/迭代余量约 8s，勉强），建议 service 固定 **2 个渲染 worker**（`ExportManager` 已有 ThreadPool 基础），并且批量模式 preview 并行、全分辨率串行排队。
- **P1 必做**：真实 NEF + YOLOE 组合的端到端基准 `pixo.bench.e2e_loop`，把 30s/2 张每分预算写进 gate（无 RAW_PATH 时 skip，同现有 gate_e2e 约定）。

### 5.5 部署形态风险

- render 依赖 rawpy/OpenCV/ctypes DLL；vision 依赖 torch（约 2GB 级）或 onnxruntime。**手机端原生运行 RAW 渲染 + 26L 模型不现实**，必须以桌面/服务器为算力底座、手机做客户端。
- Electron 打包 Python 需 sidecar；Tauri 更轻但需要 WebView2（Win10/11 自带）。**先 PWA 可零打包验证全部交互**。
- 离线分发：模型 + DCP + 相机缓存需进安装包 manifest 与版本校验；AGPL 模型单独通道，不进主安装包。

### 5.6 其他文档问题

- §7.2 “构图原在管线末端”与事实不符（根本没有）。
- §7.3 “插值在 DCP 色彩转换前的线性空间”与“DCP 后、影调前”两句互相矛盾；本评审取“**WB+DCP 链路之后（linear_rgb）、影调之前**”，与“调整作用于最终画面”的目标一致。
- §5.4 美学维度键名 `quality` 与 guanlan 实际 `technical_quality` 不同，迁移时以 Pixo schema 为准。
- §14.3 性能预算只有“初期 ≤30s”，未写迭代内各环节预算；建议补 §5.4 的分解表。

---

## 6. DSH Agent 改造方案

### 6.1 总体形态

```
DSH Web/主会话（Agent）
   │  原生视觉：deepseek-v4-flash-vision-exp（text+image）
   │  工具调用：pixo.* 插件（HTTP → pixo-service）
   ▼
pixo-service（Python FastAPI，本地 :9777）
   ├─ API：vision / meta / render / decide / state / review / trace / export
   ├─ 引擎：pixo.render + pixo.vision（进程内复用，不做子进程来回拷贝）
   ├─ 状态机：SQLite + JSON 事件流（唯一可信状态）
   └─ 任务队列：2 个全分辨率渲染 worker + N 个 preview worker
        │
        ▼
UI（React Web/PWA → Tauri 壳）
   导入 · 批处理 · 单张闭环 · 参数溯源 · 复核队列 · 设置
```

### 6.2 工具注册（P2）

| 工具 | 输入 | 输出 | 安全边界 |
|---|---|---|---|
| `pixo.vision.health` | — | 各模型可用性/版本 | 只读 |
| `pixo.vision.segment` | image_id, prompts | mask 元数据（不返回全图） | 只读；AGPL 隔离 |
| `pixo.vision.measure` | image_id, region | 测量 JSON（§5.4 schema） | 只读 |
| `pixo.vision.aesthetic` | image_id | 7 维分（仅 Trace/复核） | 只读 |
| `pixo.meta.extract` | raw_path | 标准化 EXIF | 只读 |
| `pixo.meta.infer_context` | meta | 场景/光场/连拍分组 | 只读 |
| `pixo.render.preview` | image_id, params（来源 token） | 预览图 + 测量 | params 必须携带 `source`（decide/user/agent_nl） |
| `pixo.render.final` | image_id | 全分辨率 QC + 导出 | 仅 FINAL_QC 状态可调 |
| `pixo.decide.decide` | image_id, 当前测量 | 决策 JSON（adjust/stop/manual_review） | **唯一终止判断来源** |
| `pixo.state.get` / `pixo.state.history` | photo_id | 状态/事件流 | 只读 |
| `pixo.review.submit` | photo_id, reason | 入复核队列 | 必须带 reason |
| `pixo.trace.query` | param | 溯源链 | 只读 |

**注册方式**：优先 DSH 插件包（本地 `.mjs`，热加载进 `~/.dsh/profiles/web/cordis.patch.yml` 的 insert 块，并从 `dsh.profile.bundles` 移除包避免重复注入——按本机已验证的热加载流程）；插件内部只做 HTTP 薄封装，逻辑全在 pixo-service，避免 DSH 端重复实现。

### 6.3 任务编排与状态机

- 状态机照文档 §11.1，但把**转移校验下沉到 pixo-service**：`RAW_PENDING→SCREENED→BASE_RENDERED→EXPOSURE_ALIGNING→COLOR_CORRECTING→STYLE_APPLIED→FINAL_QC→ACCEPTED/MANUAL_REVIEW/REJECTED`。
- DSH Agent 只做：意图解析（用户自然语言 → `EditIntent`，可复用 `pipeline/intents.parse_feedback`）、任务规划（单张/批量/连拍）、语义优选（表情/姿态/眼神）、异常解释、升级人工。
- **Agent 不能**：直接写状态、绕过 Decide 改参数、否决客观终止。工具层不提供任意状态迁移接口；`pixo.decide.decide` 返回 continue 时由 service 自动推进，Agent 只能 `agree` 或 `escalate(reason)`。
- 连拍选帧三层过滤沿用文档 §8.4：硬过滤（motion_blur/sharpness/EAR/曝光）→ aesthetic 预筛 → Agent 语义优选 Top 3-5，全部落 Trace。

### 6.4 人工复核

- 复核队列实体：`photo_id、state、unreliable_regions、rule_hits、trace、before/after、agent_reason、escalation`。
- UI 动作只有三种：`accept`（重新入队 QC 放行）、`reject`（终态）、`edit`（进入手动参数模式，用户锁定参数优先级最高）。
- 复核统计（不可自动修复率）进 Harness 周报，目标 <5%（文档 §14.2）。

---

## 7. 前端/产品方案

### 7.1 主要页面与交互

| 页面 | 核心交互 | 备注 |
|---|---|---|
| **导入** | 拖入/选择 RAW 目录；自动识别相机（现有 `camera_key` 缓存）；DCP 匹配预览；批量策略选择 | 复用 `pixo.meta.extract` 预扫描 |
| **批处理看板** | 卡片网格（状态/缩略图/指标 chip）；批量启动/暂停/失败重试；按场景/连拍分组过滤 | 状态来自 service，UI 只订阅 |
| **单张闭环** | before/after 对比滑块；左侧参数面板（曝光六键/WB/HSL…）；右侧测量面板（人脸/天空/主体 Lab 与裁切）；迭代轮次时间线；每轮 `Decide` 理由卡片 | preview 走 `RawPreviewSession` 的参数指纹缓存，改参即刷（hot 414ms） |
| **参数溯源** | 选中任意参数 → 时间线显示 `rule_id/formula/source/前值→后值`；支持导出 JSON | 文档 §13 schema |
| **复核队列** | 队列列表 + 并排对比 + Agent 理由；accept/reject/edit 三键；快捷键批量 | 复核动作进 Trace |
| **设置** | 模型路径与可用性（含 AGPL 隔离状态灯）；性能档（preview long_edge/worker 数）；DSH 地址与信任主机；输出格式（JPEG/WebP/PNG16/TIFF16）；GPS 隐私开关；风格卡片库 | 设置变更可追溯 |
| **Harness（开发页）** | gate/回归/A-B 结果、基准对比、golden 管理 | 直接消费现有 tools 输出 |

### 7.2 打包形态推荐（分阶段）

| 阶段 | 形态 | 选型 | 理由 |
|---|---|---|---|
| 阶段 1（P0-P1 开发期） | **本地 Web + PWA** | FastAPI 服务 + React/Vite 前端；PWA 可安装 | 零打包成本；DSH Web 宿主天然支持；手机经 `https://47.102.120.125.sslip.io` 类信任主机直接访问（本机已配置 trustedHosts） |
| 阶段 2（P2 桌面） | **Tauri 2 + Python sidecar** | Rust 壳（<10MB）+ PyInstaller onedir 的 pixo-service + WebView2 | 比 Electron 小一个量级；Python 引擎不用重写；`ExportManager` 的线程池直接复用 |
| 备选桌面 | Electron | 若 Tauri 侧边车进程管理遇到不可解问题 | 与现有 Node/DSH 生态同栈，但体积/内存更大 |
| 阶段 3（P2.5 手机） | **Expo/React Native 远程客户端** | 连本地/云端 pixo-service，手机只做 UI + 上传 RAW + 显示 | 不在手机跑 rawpy/torch；Flutter 不推荐（需维护第二套 UI 技术栈，且与 DSH/React 生态脱节） |
| 云端形态（可选） | 自托管服务 | pixo-service + 对象存储 + GPU 推理 | AGPL 模型**禁止**进云端服务，必须先完成 §5.2 替换 |

### 7.3 UI 技术细节（基于当前 render 已有能力）

- 预览渲染：`RawPreviewSession.render(long_edge, output_bps)` + `submit_render/latest_result`，已具备 generation 令牌与参数指纹缓存，前端直接按 generation 拉取。
- 导出：`ExportManager.submit/status/wait` 已支持 8/16-bit 多格式任务化导出，UI 只需轮询。
- 批处理骨架：`pipeline_from_config` + `Pipeline.to_config` 可把 UI 状态与管线配置互转，作为“参数面板 ↔ 引擎”的序列化边界。
- 缺少的部分：任何 HTTP 层（当前 render 无 fastapi/flask）、照片状态库、认证（局域网内可选 token）、模型下载/校验器——列入 P1/P2。

---

## 8. 实施路线图（P0 / P1 / P2）

### P0：几何与视觉地基（先打通可测量闭环）

| 编号 | 任务 | 依赖 | 验收标准 |
|---|---|---|---|
| P0-1 | **compose 构图前置 Stage**：order=22 插入 `whitebalance` 后；裁剪/旋转/翻转 + 几何元数据；`test_gate_compose.py`；接入 run_all_tests | 无 | 纯裁剪/翻转逐位一致；旋转 PSNR≥60dB 或 ΔE<0.5；预览 vs 全质量 A/B p50≤2、p99≤10/255；全量 498+gate 绿 |
| P0-2 | **Segmenter 接口 + MockSegmenter + 模型健康检查** | 无（可与 P0-1 并行） | `segment(image,prompts)->mask dict` 契约冻结；Mock 可合成 face/sky/plant；`vision_health()` 可报告 |
| P0-3 | **YoloeSegmenter**：迁移 guanlan `yoloe_det/detector`，补 `result.masks` 输出、RGB 域适配、AGPL 单文件隔离 | P0-2 | 真实图片 face/sky/person mask 与检测框一致；`grep ultralytics` 仅命中 1 文件；`model_licenses.json` 登记 |
| P0-4 | **区域/全局测量**：迁移 `color_stats/exposure/zone_exposure/sharpness/motion_blur` 到 `pixo/vision/measure.py`，输出文档 §5.4 schema + reliable 标记 | P0-2 | 合成图数值单测；空 mask/NaN/低置信度失败注入测试；测量结果版本字段齐全 |
| P0-5 | **Pixo Meta 基础**：EXIF 提取/标准化 + `burst_grouping/daylight` 迁移 | 无 | 标准 EXIF 字段正确；连拍分组与 guanlan 对拍一致 |
| **P0 Gate** | compose 验收 + Segmenter 隔离 + 测量 schema + Meta 基础 + 性能预测量 | P0-1..5 | 对应架构文档阶段 2 Gate 清单全部可勾选（mask 金样本 ≥50% 可延至 P1-2 前） |

### P1：决策闭环与产品化地基

| 编号 | 任务 | 依赖 | 验收标准 |
|---|---|---|---|
| P1-1 | **pixo 命名空间落地**：src-layout `pixo/render/` + `pyproject.toml` + `render` 兼容 shim + 文档/bench 路径清理（RawFlow 残留、README 基线、requirements 注释） | P0-1 | `import pixo.render` 与 `import render` 双绿；`pip install -e .` 可用；残留路径 grep 清零 |
| P1-2 | **金样本集**：20 曝光 + 10 肤色 + 10 场景 + 10 连拍，mask 标注 ≥50% | P0-4 | manifest + 哈希锁定；golden 生成/对比流程可用 |
| P1-3 | **Pixo Decide**：YAML 规则引擎（优先级/锁定/step_decay/冲突消歧/曝光方向限幅/终止条件/QC 回退） | P0-4,P0-5 | 每条规则单测；3 轮收敛与回退路径状态机测试 |
| P1-4 | **Pixo State + Trace**：SQLite 状态机 + 事件流 + 参数溯源；服务端强校验转移 | P1-3 | 非法转移被拒；任意参数可查完整溯源链 |
| P1-5 | **单张闭环 e2e**：compose→segment(一次)→3 轮 preview 迭代→FINAL_QC 全分辨率→export | P0-1..P1-4 | 真实 NEF 端到端 ≤30s；mask 复用实测；不可自动修复样本正确转 MANUAL_REVIEW |
| P1-6 | **pixo-service API**：FastAPI 包装 vision/meta/render/decide/state/trace，2 worker 队列 | P1-4,P1-5 | OpenAPI 文档齐全；并发 2 张/分钟基准；鉴权 token |
| P1-7 | **性能门禁升级**：真实 NEF+YOLOE 组合 bench，把 30s/2 张每分写进 gate_e2e | P1-5 | gate 基准 JSON 入库；超标阻塞 |

### P2：Agent、产品与发布

| 编号 | 任务 | 依赖 | 验收标准 |
|---|---|---|---|
| P2-1 | **DSH 工具插件**：pixo.* 工具注册（热加载 insert 块 + bundles 去重）+ 任务编排/状态机接入/AGENT_ESCALATED | P1-6 | DSH 会话可完成“修这张图，提亮人脸”全流程；Agent 无法绕过 Decide |
| P2-2 | **批量流程 + 连拍选帧**：Meta 分组→硬过滤→aesthetic 预筛→Agent 语义优选 Top3-5 | P2-1 | 连拍组自动产出推荐+理由+confidence；低置信度转人工 |
| P2-3 | **Web UI v1（PWA）**：七页面 + DSH 聊天面板嵌入 | P1-6 | 单张闭环 ≤3 轮可在 UI 全程可视化；复核队列可完成 accept/reject/edit |
| P2-4 | **复核与报告**：复核队列 + CSV/HTML 报告 + 参数溯源导出 | P2-3 | 不可自动修复率统计可出数 |
| P2-5 | **桌面打包**：Tauri 2 + PyInstaller sidecar（Windows 首发） | P2-3 | 干净 Win10/11 安装包可用；离线模型/DCP 校验；无 AGPL 产物 |
| P2-6 | **知识层 v1**：风格卡片 schema + 相机/镜头知识 + 简单 RAG（摄影案例） | P1-6 | 风格卡片进入 Decide 输入且优先级链生效 |
| P2-7 | **手机客户端（Expo/RN）**：局域网/远程连接、导入、看板、复核 | P2-3 | 手机可完成导入→查看→复核；不承载推理 |
| P2-8 | **许可复审节点**：YOLOE 替换/授权决策，按 §5.2 路线落地 | P0-3（复审输入） | 发布分支无 AGPL 运行时依赖；或企业授权文件归档 |

### 依赖关系摘要

```
P0-1(compose) ──┐
P0-2(Segmenter接口) ─┼─→ P0-4(测量) ──→ P1-3(Decide) ──→ P1-4(State/Trace)
P0-3(YOLOE适配) ────┘                                   │
P0-5(Meta) ──────────────────────────────────────────────┘
                                              ↓
                    P1-5(单张闭环) → P1-6(service) → P1-7(性能门禁)
                                              ↓
                    P2-1(DSH工具) → P2-2(批量/连拍) → P2-3(UI) → P2-4/5/6/7
```

---

## 9. 关键决策清单（供拍板）

| # | 决策 | 推荐 | 替代方案 |
|---|---|---|---|
| D1 | 包命名 | 统一迁到 `pixo.render`（保留 `render` shim 一版） | 保持 `render`、仅改文档 |
| D2 | 构图插入点 | `compose` @ order 22（WB+DCP 之后、huesat/tone 之前） | order 15（WB 前，与文档“插值在线性空间”字面一致，但 mask/测量对齐更差） |
| D3 | YOLOE 策略 | 研发期隔离使用，发布前替换/授权，Gate 硬检查 | 立即弃用（P0-3 换 GroundingDINO+SAM，周期 +2~4 周） |
| D4 | mask 计算频率 | 构图后 preview 上只跑一次，3 轮迭代复用，全分辨率 QC 上采样 mask | 每轮重跑（预算可能超标） |
| D5 | Agent 边界 | Decide 唯一终止判断；service 强校验；Agent 只能 agree/escalate | 放开 Agent 写状态（否决，违反文档原则） |
| D6 | 打包 | PWA 先行 → Tauri + Python sidecar → Expo/RN 手机客户端 | Electron；Flutter；云端优先 |
| D7 | 降噪/锐化顺序 | 保持 refine 内嵌组合（门禁已绿），严格物理顺序拆 Stage 列为 P1 可选 | 立即拆 denoise/sharpen 两 Stage |

---

## 10. 风险清单

| 风险 | 等级 | 证据/触发条件 | 应对 |
|---|---|---|---|
| 构图缺失导致视觉返工 | **P0 阻断** | 当前无 compose Stage；mask/金样本均依赖构图几何 | 本路线 P0-1 第一优先级 |
| YOLOE AGPL 产品化 | **高** | Ultralytics YOLOE AGPL-3.0 | 单文件隔离 + Gate 检查 + D3 路线 + P2-8 复审 |
| YOLOE 当前无 mask 输出 | **高（周期）** | guanlan `detect()` 只读 boxes | P0-3 补 `result.masks` 路径，工作量约 0.5–1 天，需真实权重验证 |
| CPU 下 YOLOE-26L 时延未实测 | **高** | 仅 GPU 40ms 注释 | P0-3 起记录 CPU/GPU 双基准；超预算启用 mask 复用 + 降档 26m |
| 全分辨率 NEF ~10.8s 挤压批量预算 | **中高** | T25/性能评审实测 | 2 worker 队列；批量 preview 并行；full-res 排队；P1-7 门禁 |
| `pixo.render` 重命名回归面大 | **中** | 498+51 测试、bench/CLI/文档路径依赖 | shim 过渡 + 双入口 CI + 一次性脚本迁移，禁手改 |
| DNG SDK 移植细节合规（§16.2） | **高（发布期）** | 架构文档已登记 | 产品化前 clean-room 复审，延续既有 M1-M5 等价测试 |
| 文档漂移误导实施 | **中** | README 597 vs 498；rawlab 注释；RawFlow 路径 | P1-1 一并清理，并建立“代码/文档一致性检查”gate |
| guanlan 模块隐性耦合 | **中** | `extract.py→src.engine.diagnosis`、LR 字段遍布 | 只按 §4.1 白名单迁移，逐模块迁移+测试，不整目录拷贝 |
| 移动端算力预期 | **中** | torch/rawpy/26L 模型无法上手机 | 产品定义先写死：手机=远程客户端，不做端侧引擎 |
| 人工复核容量 | **低-中** | 不可自动修复率目标 <5% | UI 复核效率 + 连拍批量动作 + 统计周报 |

---

## 附录 A：本次评审读取的关键证据文件

- `docs/架构设计文档.md`（917 行全文）
- `render/pipeline/{graph,presets,context,base,intents,scene_apply}.py`
- `render/modules/{exposure,white_balance,tone_map,refine,reshape}.py`
- `render/{api.py,__init__.py,README.md}`
- `render/web/{session,export,encode}.py`
- `render/docs/{PIXO_RENDER_STATUS_20260820,FUNCTION_GATE_SPEC,PIXO_RENDER_PERFORMANCE_REVIEW,PIXO_RENDER_1S_PREVIEW_DESIGN}.md`
- `render/bench/{native_baseline_v1,preview_hot_baseline,preview_v16_nef_baseline_hot}.json`、`T25_REAL_NEF_PERFORMANCE_REPORT.md`
- guanlan `src/vision/*`（14 文件）、`src/rules/*`（17 文件）、`src/scoring/frame_scorer.py`、`src/data_pipeline/*`、`config/vision.yaml`、`requirements.txt`、`AGENTS.md`
- 本机环境：`torch/ultralytics/onnxruntime/transformers` 可用、`mediapipe` 未装；DSH `~/.dsh/profiles/web/cordis.patch.yml`（trustedHosts 与热加载机制）
