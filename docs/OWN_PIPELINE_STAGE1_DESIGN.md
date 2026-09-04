# Pixo 自研渲染管线 · 阶段一详细设计（M-O1 / M-O2 / M-O3 + 前端联动）

> 状态：详细设计 v1（2026-08-27，队长架构师）。
> 上游：`docs/PIXO_RENDER_OWN_PIPELINE.md`（路线图 v1）。
> 本文经代码库实证审核后产出，可直接作为开发任务输入。

---

## 0. 设计稿审核结论（队长，已实证）

路线图文档与代码库**高度相符**，以下声明全部核实：

| 路线图声明 | 代码实证 |
|---|---|
| hsl 8 带通 gamma HSV | `src/pixo/render/core/hsl.py`：DEFAULT_BANDS 8 段（red 0…magenta 300）、环状余弦掩码、hue_shift/sat/lum 三参数 |
| skin Lab 椭圆 + 引导滤波 | `core/skin.py`：椭圆 (a=140,b=150,major 22,minor 14,θ=0.65)、smoothstep 软边界、guided_filter 自实现 |
| split_tone gamma RGB 混合 | `core/split_tone.py`：Rec.709 亮度 smoothstep 权重 + HSV 染色 |
| HSM HSV 三线性 | `core/huesat.py`：`apply_table_to_hsv` 三线性（H 环绕）+ `make_hue_sat_map` 恒等表 |
| DCP 矩阵链 | `core/color.py`：Bradford、1/T 插值、cam→XYZ/linear-sRGB/ProPhoto 矩阵族；`core/calibration.py` DcpProfile |
| RAW gate 12 features + SYNTH gate | `tools/gate_golden.py`：12 个命名 case + `render-gate-synth-v1` |
| A/B 回归 | `scripts/run_ab_regression.py` 存在 |
| native 逐位等价模式 | `render/native/src/*.cpp` + `native/tests/test_main.cpp` + `tests/unit/test_native_*.py`（abi/hsv/refine/warm_sat/decode/stage_kernels） |
| Oklab 为新建 | 全库 grep `oklab` 零命中，M-O1 确为绿地 |
| 前端栈 | `frontend/package.json`：React 18 + Mantine 7 + zustand 5 + vite 5 |

**审核发现 4 个盲点（路线图未覆盖，本设计已纳入）**：

- **A1 胶片卡消费者**：`configs/styles/films/` 下 13 张卡内嵌 `"hsl": {"bands": "<JSON 字符串>"}`（HSV 度语义，见 `kodak_portra_400.json` L37-41）。迁移 OKLCh 后 band 语义漂移，必须做 schema 兼容。
- **A2 知识包语义**：`configs/knowledge/photography_hue.json`、`photography_post2.json` 引用 hsl 操作语义（LLM 副驾提示层），量纲变更需同步。
- **A3 skin 白点口径**：路线图写 "Lab(D65)"，实现是 `cv2.COLOR_RGB2LAB`（OpenCV Lab 语义）。重拟合时以实现为准，不照抄文档。
- **A4 loop 色彩桥**：`src/pixo/pipeline/loop.py:54` `_COLOR_PARAM_ALIASES` 桥接色彩键到 colorcal，hsl 参数域变更需排查此桥与 `render/modules/reshape.py` 的消费注释。

---

## 1. 总体架构

### 1.1 新增模块清单

```
src/pixo/render/core/oklab.py        # Oklab/OKLCh 转换内核（纯 numpy，M-O1）
src/pixo/render/core/hsl_oklch.py    # OKLCh 域 8 带调整（M-O1）
src/pixo/render/core/split_tone_oklab.py  # Oklab 色相轴分离色调（M-O1）
src/pixo/render/core/rp_ccm.py       # 根多项式 CCM 应用（M-O3）
src/pixo/render/native/src/oklab.cpp/.h  # native Oklab 内核（M-O1）
scripts/fit_skin_oklch.py            # 皮肤椭圆重拟合（M-O2）
scripts/convert_hsm_to_oklch.py      # HSM 表→OKLCh 控制点离线转换（M-O2）
scripts/fit_rp_ccm.py                # RP-CCM 拟合（M-O3）
scripts/eval_rp_ccm_ab.py            # ΔE2000 并联评估报告（M-O3）
scripts/ab_intent_compare.py         # 意图级 HSV vs OKLCh 对照（验收工具）
```

### 1.2 编辑域开关（双轨渐进）

- `RenderIntent` / StageParams 级新增 `color_domain: "hsv" | "oklch"`，**默认 `"hsv"`**（现有行为逐位不变）。
- `HslStage` / `SplitToneStage` 按 `color_domain` 分派到旧实现或新实现；旧实现代码**不删不改**（回退保证）。
- 金样本新增 oklch 域 case（见 §6），数据说话后再切默认。

### 1.3 域与精度总则（所有新内核必须遵守）

- 输入输出：gamma sRGB float [0,1]（与现 hsl/split_tone 一致）；内部 float64 计算、输出 float32。
- **dtype 契约（t1 交付后队长裁决 2026-08-28）**：Oklab/OKLCh 是内部工作域——`srgb_to_oklab`/`oklab_to_oklch`/`oklch_to_oklab` 出口 **float64**；仅 `oklab_to_srgb`（sRGB 渲染域出口）出 **float32**。依据：lab 以 float32 交接时量化噪声被近黑区 gamma 斜率 12.92 放大，往返下限实测 ~7e-7，1e-7 物理不可达；f64 内部域实测网格往返 1.8e-10。另：逆矩阵不得抄 Ottosson 原文公布常数（与正向不严格互逆，偏差 5.5e-8）——用正向常数的数值逆冻结为 12 位字面常数。t6 native 内核与 t12 检视以此为契约。
- Oklab 正向：linear sRGB → LMS（cbrt）→ LMS' → Oklab（Björn Ottosson 2020 标准矩阵，正向常数抄原文并注明出处；逆矩阵用数值逆，见上 dtype 契约）。
- **精度验收**：sRGB→Oklab→sRGB 往返，对 [0,1]³ 网格采样（步长 1/32）最大误差 ≤ 1e-7（对齐既有 DCP 数学复算基线）。
- **no-op 保证**：所有参数为 0 时逐位不变（连转换都不做，走快路径）——对齐 `hsl_adjust_rgb` 既有纪律。
- 纯函数、无 I/O、无全局状态；单测放 `tests/unit/`。

---

## 2. M-O1 详细设计

### 2.1 `core/oklab.py`（先行任务，无依赖）

API：
```python
def srgb_to_oklab(rgb01) -> np.ndarray      # (H,W,3) gamma sRGB → Oklab
def oklab_to_srgb(lab) -> np.ndarray        # 逆变换，负值裁剪策略：clip linear 后编码
def oklab_to_oklch(lab) -> np.ndarray       # L,a,b → L,C,h(度, 0..360)
def oklch_to_oklab(lch) -> np.ndarray       # h 环绕连续
```
- cbrt 负值处理：`np.cbrt`（实数立方根），与原文一致。
- 单测 `tests/unit/test_oklab.py`：往返精度（网格 1/32 ≤1e-7）、灰轴不动（R=G=B → C≈0, h 任意但稳定无 NaN）、黑/白端点精确、批量与单像素一致。

### 2.2 `core/hsl_oklch.py` —— hsl 迁移

- `oklch_adjust_rgb(img01, bands, smooth)`：结构对齐 `hsl_adjust_rgb`（逐段环状掩码 + protect），域换成 OKLCh：
  - `hue_shift` → h 角度平移（度，掩码加权，`% 360`）；
  - `saturation` → C 缩放 `C' = clip(C*(1+sat/100*m*protect), 0, C_max(L))`（C_max 由 gamut 内嵌约束，用软限幅 tanh 过渡，禁止硬截断——这是 HSV 饱和截断缺陷的根治点）；
  - `luminance` → L 缩放 `L' = clip(L*(1+lum/100*m*protect), 0, 1)`；
  - protect = 中性保护：`protect = smoothstep(C / C_NEUTRAL)`（C≈0 不动）。
- **band schema v2（A1 兼容关键）**：band dict 新增可选键 `"domain": "hsv"|"oklch"`，缺省 `"hsv"`。加载层（胶片卡→`know/cards.py` 路径）不识别 domain 时按 hsv 旧语义走旧内核——**13 张存量卡零迁移、逐位不变**。新卡/新 UI 写 `domain:"oklch"` + OKLCh 角度中心。
- OKLCh 8 带默认中心（按感知色相角重标定，供新卡与 UI）：red≈29、orange≈55、yellow≈100、green≈145、aqua≈195、blue≈264、purple≈295、magenta≈327（初值，M-O2 拟合后可修订，存 `DEFAULT_BANDS_OKLCH` 常量）。
- 单测：全 0 no-op 逐位；单 band 只动目标色相扇区（掩码外像素逐位不变）；domain 字段分派正确性；h 环绕 0/360 连续（348°+20° 平移无跳变）。

### 2.3 `core/split_tone_oklab.py` —— split_tone 迁移

- 语义对齐 `split_tone_rgb`（shadows/highlights hue+sat、balance、strength），改动点：
  - 权重仍用 Rec.709 Y smoothstep（**不动**，亮度分域与色彩域无关）；
  - 染色改为 OKLab 域：目标染色 = 固定 (L=像素L, C=sat/100·C_ref(L), h=hue°)，转回 sRGB 混合 `out = img*(1-w) + tint*w*strength`；
  - 高光染色在 L 高区自然低 C（感知线性），替代 HSV 的 V 保亮——高光色相漂移缺陷的根治点。
- 参数名不变（UI/卡片零改动），仅 `color_domain` 分派。
- 单测对齐 2.2 纪律 + sat=0 no-op。

### 2.4 native `oklab.cpp`（M-O1 后段）

- 对齐既有内核模式：`native/src/oklab.{h,cpp}` 暴露 F32 平面版 `srgb_to_oklab_f32 / oklab_to_srgb_f32`；`abi.cpp` 注册 `pixo_render_oklab_*`（params struct 对齐 `PixoRenderMatrixApply3Params` 风格：指针 + 宽高 + stride）。
- Python 侧 `_native/__init__.py` 加载与 fallback：native 不可用时回退 numpy 实现（对齐 `test_native_fallback.py` 模式）。
- **验收：native vs numpy 逐位等价**（`tests/unit/test_native_oklab.py`，随机 100 万像素 + 网格，bit-exact）。

### 2.5 金样本基线（M-O1 收口）

- `tests/regression/goldens/gate_cases.py` 新增 case：`hsl_oklch`（8 带 OKLCh 域典型参数）、`split_tone_oklab`；`color_domain:"hsv"` 下既有 12 case 基线**不动**（回归保护）。
- 走 `generate_gate_goldens.py` 生成 + reviewer 流程入库。

---

## 3. M-O2 详细设计（skin / colorcal / HSM 双轨）

- `scripts/fit_skin_oklch.py`：输入厦门/春节语料（`pixo.meta` 分组），皮肤样本（现 Lab 掩码 + person 分割掩码交集）在 **OKLab a-b 平面**重拟合椭圆（最小二乘二次曲线 → 中心/半轴/倾角），输出新常数并给出旧椭圆 vs 新椭圆的召回/误报对照表。**以 cv2 实现语义为准（A3），拟合脚本自带白点说明**。
- `core/skin.py` 新增 `SKIN_OKLAB_*` 常量与 `skin_mask_oklab`（不动旧函数）；`SkinStage` 按 `color_domain` 分派；`color_cal.py` 的 `scene_skin_trim` 联动改用同掩码。
- `scripts/convert_hsm_to_oklch.py`：DCP HSM 表（90×16×16）离线采样 → OKLCh 域 hue/C 控制点云（json 落 `configs/color/`），**只产出数据不接运行时**（阶段二才接），供 M-D1 标定期使用。

## 4. M-O3 详细设计（RP-CCM 并联）

- `core/rp_ccm.py`：`RPCCM` 数据类（系数 3×(3+p) 项：R,G,B 及其交叉幂，**根多项式不带纯度项平方**，保持曝光不变性——Finlayson 2015）；`apply_rp_ccm(linear_rgb, coeff)`；从 `pixo.meta` 读相机/分组。
- `scripts/fit_rp_ccm.py`：语料 + 相机 JPEG 弱监督参考（对齐 `calibrate_to_camera.py` 既有基础），最小二乘拟合，产出 `configs/color/rp_ccm_<camera>.json`。
- `scripts/eval_rp_ccm_ab.py`：同语料双轨渲染（DCP vs RP-CCM）→ ΔE2000 median/p95 报告（markdown 落 `.artifacts/`），**只报告不切默认**。
- 隔离纪律：拟合脚本依赖（sklearn/numpy）只进 scripts/，运行时 `core/rp_ccm.py` 仅 numpy。

## 5. 前端联动（frontend-* / ui-designer）

- **ui-designer 先行**：OKLCh 编辑域 UI 规范——色相环控件角度标注映射（HSV 度 vs OKLCh 度双刻度）、8 带滑杆 center 量纲标注、饱和滑杆"C（色度）"语义文案。
- **frontend-1 实现**：`frontend/`（React+Mantine+zustand）HSL 面板与 split_tone 面板支持 `color_domain` 参数（默认 hsv UI 不变），oklch 域下 center 滑杆按 §2.2 OKLCh 角度量纲；zustand store 增域字段；`typecheck` + `test:e2e` 过。
- **frontend-2**：胶片卡编辑器/展示（如涉及）与知识包文案同步（A2），e2e 冒烟预览链路（改 oklch 参数→preview 接口往返）。

## 6. 质量门操作手册（本阶段逐任务对应）

| 变更 | 金样本 | native 等价 | 语料 A/B |
|---|---|---|---|
| oklab.py 内核 | 不涉及（纯新模块） | — | — |
| hsl/split_tone oklch 域 | 新增 2 case + 旧 12 case 不动 | hsv 旧内核不动即安全 | `ab_intent_compare.py` |
| skin oklch | skin case 双域 | 不涉及 | 召回/误报对照 |
| native oklab | 不涉及 | **逐位等价强制** | — |
| RP-CCM | 不涉及（不切默认） | 不涉及 | ΔE2000 报告强制 |
| 前端 | — | — | e2e 冒烟 |

验收红线：`pytest tests/unit tests/regression` 全绿；hsv 域全部既有 gate 基线**逐位不变**；oklch 域新基线 reviewer 通过。

## 7. 任务依赖图（weave 派单对照）

```
t1 oklab 内核 ──┬─► t3 hsl 迁移 ──┬─► t8 前端实现 ◄─ t7 UI 规范 ◄─ t1
               ├─► t4 split_tone ─┼─► t9 卡/知识包同步 ◄─ t3,t4
               ├─► t5 skin 重拟合 ┤
               └─► t6 native ─────┴─► t10 金样本+gate 回归 ◄─ t3,t4,t5,t6
t2 RP-CCM（独立线）─────────────────► t13 QA 终审
t3,t4 ─► t11 意图级 A/B 对照
t3..t6,t8,t9 ─► t12 代码检视（≤2 轮）─► t13 QA 终审 ◄─ t10,t11,t2
```

---

## 8. 交付物索引（阶段一收口追加，2026-09-04）

> 本节与 §9 为文档收口任务**纯追加**，不修改上文 §0-§7 任何既有内容。每条验收结论一句话；标注「复跑」者为收口时点（2026-09-04）实测。

### 8.1 M-O1 编辑域内核（Oklab/OKLCh）

| 产物 | 验收结论（一句话） |
|---|---|
| `src/pixo/render/core/oklab.py` | 独立复核**通过**（`.artifacts/t1_review.md`）：网格 1/32 往返实测 1.844e-10（验收线 ≤1e-7）；逆矩阵取正向常数 12 位数值逆（抄原文公布逆常数实测 1.69e-6，验收线物理不可达）；dtype 契约（内部域 f64、仅 `oklab_to_srgb` 出 f32）经反事实实验证实必要（f32 交接下限 ~7e-7）。 |
| `tests/unit/test_oklab.py` | 23 用例全绿（复跑）：往返精度/灰轴不动/黑白端点/批量逐位一致/dtype 出口契约/负输入与色域外无 NaN/h 折回；断言阈值 1e-7 对实测 1.8e-10 留约 500 倍余量。 |
| `.artifacts/t1_review.md` + `.artifacts/t1_review_probe.py` | t1 交付独立复核报告（测试工程师 1，结论：**通过**）：探针不复用交付代码路径、独立复现全部宣称精度数字；抓出 2 处**文档表述级**瑕疵（docstring「互逆残差<5e-13」数字不成立、锚点「7 位吻合」表述过强），不阻塞验收，遗留 t19/t24 落实修正。 |
| `src/pixo/render/core/hsl_oklch.py` | `oklch_adjust_rgb` + `DEFAULT_BANDS_OKLCH`（OKLCh 8 带感知色相角中心）交付：饱和 C 软限幅 tanh 渐近色域包络（e→0 斜率 1 连续、无平台无硬折）、中性保护、h 环绕连续；三条逐位 no-op 快路径（全 0 / 掩码全零 / 掩码外像素**绕过域重建**——堵住 f32 出口暗部 ~1ulp 抖动）。 |
| `src/pixo/render/modules/hsl.py`（增量改动） | HslStage `color_domain` 双轨分派交付：缺省 `hsv` 与旧内核**逐位一致**（13 张存量卡零迁移，盲点 A1 关闭）；band 级 `domain` 键逐段覆盖、hsv/oklch 可混排、非法域值报错。 |
| `tests/unit/test_hsl_oklch.py` | 18 用例全绿（复跑）：逐位 no-op×3、单 band 只动目标扇区、348°+20° 环绕无跳变、软限幅单调无平台、Stage 分派/混排/缺省带/报错。 |

### 8.2 M-O3 RP-CCM 线（独立线）

| 产物 | 验收结论（一句话） |
|---|---|
| `src/pixo/render/core/rp_ccm.py` | 根多项式 CCM 运行时交付（Finlayson 2015 项集、不含纯度平方项）：特征随线性 RGB 曝光精确等比缩放（测试锁定），恒等系数快路径逐位 no-op，运行时仅 numpy（sklearn 隔离在 scripts/）。 |
| `tests/unit/test_rp_ccm.py` | 28 用例全绿（复跑）：合成图表精确复原/噪声拟合稳定、曝光不变性、秩亏 min-norm 不崩、JSON 逐位往返、出口 dtype/值域契约、输入校验。 |
| `scripts/fit_rp_ccm.py` | 语料弱监督拟合交付：相机 JPEG 参考 + 逐照片标量曝光增益对齐 + 仅 99% 分位一轮裁剪（保住高饱和样本），产出 `configs/color/rp_ccm_nikon_z5_2.json`。 |
| `scripts/eval_rp_ccm_ab.py` | DCP vs DCP+RP-CCM 双轨 ΔE2000 A/B 评估交付（含 `--selftest`），**只报告不切默认**（§4 纪律）。 |
| `configs/color/rp_ccm_nikon_z5_2.json` | Nikon Z5_2 系数入库（含 meta 透传，JSON 往返逐位一致）。 |
| `.artifacts/eval_rp_ccm_ab_nikon_z5_2_20260828_232324.md` | 54 张全扫描语料实测：总体 ΔE2000 median 6.151→5.675（**-7.7%**）、p95 -2.9%，45/54 照片 B 轨更优；DCP 基线与 configs 默认未被修改。 |
| `scripts/README.md`（增量改动） | fit_rp_ccm / eval_rp_ccm_ab / build_project_graph 三条新脚本已入目录文档。 |

### 8.3 项目图谱（DAG 追加批次 t14/t15，不在原 §1.1 清单内）

| 产物 | 验收结论（一句话） |
|---|---|
| `scripts/build_project_graph.py` | AST 解析 `src/pixo` 生成项目图谱交付：**零手画边**（import 边带源码行号、Stage 顺序取 `presets.DEFAULT_STAGES`、域契约取 `@register_stage`），`--check` 幂等守卫（忽略时间戳防漂移）、`--merge` 消费前端片段（id 冲突即报错）；Windows 大小写敏感陷阱已规避并有单测。 |
| `docs/project_graph.json` + `docs/PROJECT_GRAPH.md` | 后端图谱机读+人读版（v1.0：169 模块 / 523 边），人读版全部字段自 JSON 渲染。 |
| `docs/project_graph_frontend.json` + `docs/PROJECT_GRAPH_FRONTEND.md` | 前端+configs 资产图谱（严格 nodes/edges 片段格式，供 `--merge`）：区分 import 边/运行时调用边/契约镜像边，单列「已封装未接线」端点 5 个；资产统计脚本现场计算（films 卡实扫 24 张而非任务书的 13 张）。 |
| `docs/project_graph_full.json` | merge 后全量图谱（267 节点 / 652 边）。 |
| `tests/unit/test_build_project_graph.py` | 18 用例全绿（复跑）：模块 id/相对导入层级/import 分类/片段合并与冲突/CLI generate+check/真实仓图谱不变量。 |
| ⚠️ 待办（供 t25） | 收口时点实测 `build_project_graph.py --check` **报漂移**（`project_graph.json` + `PROJECT_GRAPH.md`）：图谱生成于 f48d453 时点，其后工作区新增 hsl 域分派等阶段一改动——t25 终审前须重跑 `python scripts/build_project_graph.py --merge docs/project_graph_frontend.json` 再生成（守卫按设计生效，非缺陷）；前端图谱生成脚本 `gen_project_graph_frontend.py` 现存放于 `.artifacts/`，建议归位 `scripts/`。 |

### 8.4 UI 规范（t7 先行交付）

| 产物 | 验收结论（一句话） |
|---|---|
| `docs/UI_OKLCH_SPEC.md` | UI 规格 v1.0 交付（ui-designer，上游 §5）：HSV↔OKLCh 双刻度锚点表冻结+分段线性（角度偏移非均匀 +15°~+50°，**不存在固定偏移**，读数只用于显示不参与提交数学）、width 半径语义、饱和滑杆改「色度 C」+软限幅文案、split_tone 色谱随域切换、提交契约只 patch `color_domain`+band（切域不改数值）；全部映射数字为已交付内核实测。 |
| `.artifacts/ui_oklch_probe.py` | 规格数字复现探针（2026-08-28 实测口径，前端禁止自行估算）。 |

### 8.5 收口缺口与并行交付快照（供 t25 终审核对，对照 §1.1 模块清单）

截至收口快照（2026-09-04 07:55）：

- **已验收交付**（本轮收口验证范围）：§8.1-§8.4 所列 oklab / hsl_oklch + HslStage 分派 / RP-CCM 线 / 项目图谱 / UI 规格 / t1 复核；四个新单测文件复跑 87 passed。
- **并行交付中**（快照观察，**未经本收口验证**，截至快照无配套单测与复核记录）：`core/split_tone_oklab.py`（原 t4 / 重组 t17，实现已落地）；`core/skin.py` 的 OKLab 椭圆常数增量（原 t5 / 重组 t18）；`modules/split_tone.py`、`modules/skin.py`、`modules/color_cal.py` 域分派改动；frontend `types.ts` 改动与新增 `e2e/capture_hsv.mjs`（疑为原 t8 / t20 启动，未证实）。
- **确认缺口**：native `oklab.cpp`（原 t6 / t19）、胶片卡/知识包语义同步（原 t9 / t21）、金样本 oklch case + gate 回归（原 t10 / t22）、`ab_intent_compare.py`（原 t11 / t23）、代码检视（原 t12 / t24）。另：t1 复核报告 §5.1/§5.2 两处 docstring 表述修正尚未落地（随 t19/t24 落实）。

---

## 9. 批次映射表（重组批次 t17-t25 ↔ 原设计编号 t4-t13，供 t25 终审引用）

> **映射依据**：① 原设计 §7 依赖图编号 t1-t13；② DAG 派单实证——t1（oklab）/ t2（RP-CCM 线）/ t3（hsl_oklch）/ t7（UI 规范）按**原号**派发并已交付（知识库 own-pipeline-stage1 反思记录可查），t14（全仓图谱）/ t15（前端图谱）/ t16（t1 独立复核）为 DAG 追加批次、不在原 t1-t13 内；③ 原 t4-t13 中尚未派发的 9 个任务按依赖序 1:1 重组为 t17-t25（t7 已先行交付，故不在重组范围）。1:1 对位为依依赖序重建，如与派单系统批次描述有出入，以派单记录为准。各批次验收口径不变，见「设计依据」列。

| 重组批次 | 承接原任务 | 内容 | 设计依据 | 上游（重组号） | 收口时点状态 |
|---|---|---|---|---|---|
| t17 | t4 | `core/split_tone_oklab.py` 分离色调 OKLab 迁移 | §2.3 | t1 | 交付中 |
| t18 | t5 | skin OKLab 椭圆重拟合 + `skin_mask_oklab` | §3 | t1 | 交付中 |
| t19 | t6 | native `oklab.cpp` 逐位等价 + t1 复核表述修正 | §2.4 | t1, t16 | 未交付 |
| t20 | t8 | 前端 HSL/split_tone 面板 `color_domain` | §5 | t7, t17, t18 | 未交付 |
| t21 | t9 | 胶片卡/知识包 OKLCh 语义同步（A1/A2） | §2.2, §5 | t3, t17 | 未交付 |
| t22 | t10 | 金样本 oklch case + gate 回归（旧 case 基线不动） | §2.5 | t17, t18, t19 | 未交付 |
| t23 | t11 | `ab_intent_compare.py` 意图级 A/B 对照 | §6 | t3, t17 | 未交付 |
| t24 | t12 | 代码检视（≤2 轮，含 t1 复核 §5.1/§5.2 落实核对） | §6 | t17..t21, t23 | 未交付 |
| t25 | t13 | QA 终审（以本表 + §8 交付物索引 + §8.5 缺口清单为输入） | §6 | t2, t22, t23, t24 | 待上游 |

> 状态列为收口快照（2026-09-04 07:55）：t17/t18 交付物已在工作区出现但未经本收口验证（见 §8.5），t19-t24 无交付记录，t25 待上游收齐。已交付批次（t1/t2/t3/t7/t14/t15/t16）的产物与结论见 §8。
