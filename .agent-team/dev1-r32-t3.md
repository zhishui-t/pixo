# dev1 R32-T3 报告 · 胶片模拟 HaldCLUT 接入（格式适配路线）

日期：2026-09-23 ｜ 角色：dev-1 ｜ 分支：render-core-integration（未 commit）
执行引擎：宿主原生（R32 设计 §4 兜底条款）。
另：T2 reviewer 限向修订已完成（`dev1-r32-t2.md` V5 行 + `_r32_t2_dcp_compare.py/.json` e4 note 如实化，json 已重新生成）。

**一句话：路线 = 纯格式适配（零引擎吸收）；HaldCLUT(png, level 布局) → 转换工具 → 我方 .cube 卡库直接消费，恒等 CLUT 精确到 float32 eps、3 个胶片观感在真 DNG 样图上前后对比落档，strength 语义与 RT 逐位同构（0 偏差）。**

---

## 1. RT 侧侦察（clutstore.cc/h @ 6c4cb59，345 行；improcfun.cc 消费点）

RT 的 Film Simulation = `HaldCLUT`（clutstore）+ procparams `FilmSimulation{enabled, clutFilename, strength(0-100)}`。引擎数学：

| 项 | RT 事实 |
| :--- | :--- |
| 数据格式 | **方形 PNG**（经 StdImageSource 读，8/16 位皆可），边长 = **level³**（level>1 整数，`while level³ < fw` 找 exactly）；网格 N = **level²**（`clut_level *= level`）。常见 level 8 → 512×512 图、64³ 网格 |
| 载入 | 像素转 uint16 (0..65535) RGBA 交错表（每像素 stride 4，alpha 占位）；`working_color_space` 非空才做 ICC 转换（默认**空 = 不转换**） |
| 色彩域约定 | **按文件名后缀推断工作域**（`splitClutFilename`：文件名以工作空间名结尾如 `...ProPhoto.png` → 该域；缺省 sRGB）——社区 CLUT 的域语义靠命名约定，无元数据 |
| 应用插值 | **三线性**（8 角，`intp` 逐维），索引 `color = r + g·N + b·N²`（b 最慢），索引钳 `min(N-2, v·(N-1)/65535)`（顶格 → frac=1 → 末格） |
| 强度 | `intp(strength, out, in)` —— 与原图线性混合，无其它参数面（无色域钳制选项） |
| 缓存 | CLUTStore LRU（文件级） |

## 2. 接入设计：格式适配（否决引擎吸收）

**取舍依据**：
1. **数学覆盖**：RT 的 CLUT 应用 = 三线性查表 + 线性强度混合。我方 `core/lut3d.py` 已有四面体插值（Kasson 1993）+ `apply_f32`（native C++ 内核 v1.3.0，OpenMP）+ `lut_strength` 同构混合语义（`apply_f32(strength)` 与 RT `intp(strength,out,in)` 同式，实测 strength=0.5 时与手工中点混合偏差 **0.0**）。四面体无三线性的"扇形"误差（fan error）——**吸收 RT 引擎代码只有精度下行没有上行**（E 数据：仿射 CLUT 上四面体逐位精确 ≤1e-5，RT 三线性误差为其 10 倍以上，见 test_haldclut_convert.py::test_tetrahedral_beats_trilinear_on_affine）。
2. **工程面**：我方 stylize Stage 已有 `.cube` 全链（解析/缓存/LRU/原生内核/`lut_path` 参数）；新增面仅为**格式转换**（png→cube 一次性离线动作），运行时零新代码路径。
3. **GPL 面**：不移植 `clutstore.cc` 则无需新增 GPL 文件头（本报告与测试中的三线性参考实现仅为测量代码，位于 tests，出处已标注）。

**应用域对齐说明**：RT 默认把 CLUT 像素原样用于工作空间（多数社区包为显示域制作）；我方 stylize 应用域 = `DOMAIN_GAMMA_RGB`（sRGB gamma 显示域）——与社区 CLUT 的主流制作域一致。转换器**不做任何色彩变换**（像素值原样搬运），域语义随消费方；RT 的文件名后缀惯例在转换时人工确认即可（工具 docstring 已注）。

## 3. 实现（diff 清单）

| 文件 | 改动 |
| :--- | :--- |
| `src/pixo/render/core/lut3d.py` | 新增 `hald_level_to_lut(hald, max_value=None)`：RT level 布局（边=level³、网格=level²、线性索引 `r+g·N+b·N²`）→ LUT3D；位深归一 uint8/uint16/float；向量化 gather。新增 `write_cube(data, path, title, domain)`：.cube 写出器（行序 r 最慢 b 最快，与 parse_cube 读入口径一致，%.6g）。与既有 `hald_to_lut`（n² 布局、/255 硬编码）并存不互扰——后者语义独立保留 |
| `src/pixo/render/tools/haldclut_convert.py`（新） | CLI：`python -m pixo.render.tools.haldclut_convert in.png [out.cube] [--title T]`；cv2 IMREAD_UNCHANGED 读图（8/16 位），BGR→RGB，level 自检，调 hald_level_to_lut + write_cube |
| `tests/unit/test_haldclut_convert.py`（新，6 用例） | 恒等精确性（16 位，顶点误差 ≤1.5e-5）、8/16 位一致性（≤2/255）、非法尺寸拒绝、write_cube↔parse_cube 往返（≤2e-6）、四面体 vs RT 三线性仿射精度对照、工具 convert() 端到端（png→cube→lookup 恒等） |

测试结果：test_haldclut_convert + test_lut **22 passed**。

## 4. 实测（.artifacts/_r32_t3_filmsim/，脚本 _r32_t3_filmsim.py）

- **CLUT**：3 个自造胶片观感（自有版权，规避 RT 包数据许可）：level 8（512×512、64³、16 位 png），设计域 = sRGB gamma（与 stylize 应用域同域）：
  1. `portra_warm`：阴影微暖/高光柔滚降/全局轻降饱和；
  2. `teal_orange`：阴影偏青/高光偏橙 + 对比增强（split-tone）；
  3. `acros_mono`：黑白（Rec709 亮度）+ 中高对比 S + 蓝区压暗。
- **链路**：`build_hald_png → haldclut_convert CLI（子进程，端到端）→ parse_cube → LUT3D.lookup`（与 stylize apply_f32 同式）。
- **样图**：`DSC_0352.dng`（R31 语料）经 `decode_cfa_half` 预览解码 → sRGB gamma；产物 before.png + 3 张 after.png + 3 .cube + 3 源 Hald png + summary.json。
- **数据**：portra_warm mean|Δ|=0.035、teal_orange 0.065、acros_mono 0.042（>2% 变化像素 95.2%/99.98%/97.3%）——量级与观感强度相符，目检 teal_orange 前后（冷蓝→暖金分色）方向正确。
- **strength 语义**：`apply_f32(strength=0.5)` 与「原图/全效手工中点」最大偏差 **0.0**（逐位同 RT `intp(strength,out,in)`）。

## 5. 数据许可观察（只引擎/格式层，不内置数据）

- **引擎侧**：clutstore.cc/h = GPLv3（与 pixo 同源合规）——本路线未移植，仅格式规格对照（布局/索引/插值语义为公开 HaldCLUT 规范，ImageMagick/3D LUT Creator 通用）。
- **RT 官方 Film Simulation 包**：分发入口长期为 `https://rawtherapee.com/shared/film-simulation-pack.zip`（数百个社区 CLUT 聚合包；URL 需使用时复验）。**许可异质**：聚合包无统一许可，各 CLUT 版权归各自作者（多见 CC-BY-NC/CC0/不注明混杂）→ 按 task-brief §0/T3 纪律**不入仓**；若需引入具体卡片，逐张取得作者许可或换 CC0 来源，评审记录另立。本棒实测全部使用自造 CLUT，零外部数据。
- **我方卡库对接形态**：转换产物 `.cube` 直接落 `configs/styles/films/`（与既有卡片同形态，`core/lut.py` 卡名映射表加一行即接入 stylize `lut_path`）；本次 3 张为实验件留在 `.artifacts/_r32_t3_filmsim/`，是否转正入库交队长/用户定。

## 6. 门禁证据

- 新增单测 6/6 + 既有 lut 面 16/16 全绿（test_haldclut_convert + test_lut = 22 passed）；
- 全量回归（最终代码态）：见文末回填；
- 未 commit；未动 master；未引入 RT 数据/引擎代码。

（回归结果回填处）**全量回归（最终代码态）：`1738 passed, 12 skipped, 1 xfailed, 0 failed`（203s）**。
