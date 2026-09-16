# THIRD_PARTY_NOTICES — Pixo 第三方素材与许可声明

- 生成：2026-09-07（F16 批次）。素材唯一来源：`.agent-team/research/license-inventory.md`
  （researcher 只读盘点 + PyPI/deps.dev/GitHub/HuggingFace 许可核验）；代码血缘专节另引
  `.agent-team/research/dng-sdk-review.md`（F18）。
- 本文件是事实登记与义务指引，**不是法律意见**；各条目注明核验状态与可信度。
- 模型权重的权威台账为 `model_licenses.json`；与其他台账（`src/pixo/manifests/vision_models.json`
  等）冲突时以 `model_licenses.json` 为准，冲突逐条在 §4 标注。
- 台账快照时点注意：清单盘点时 PyYAML 尚属懒 import 依赖；**F17（2026-09-07）已将 PyYAML
  升必装、scipy 挂新 extras `calib`**，本文件按变更后口径成文并在 §3 注记。

---

## 0. 总述：许可面总体判定与三项必读警示

**总体判定**（清单 §0）：运行时依赖全部为 MIT/Apache/BSD 宽松许可（Python + 前端，前端传递树
144 包亦全宽松）；**不可分发项集中在模型权重（2 个 NC 后端，已门控）与代码/数据血缘
（RawTherapee GPL、Adobe DCP/SDK 痕迹、guanlan 移植）**。内部研发（不分发）当前不触发许可
义务；对外分发的阻断面与 `docs/PIXO_LICENSE_REVIEW.md` 判断一致并有所更新（rawpy/LibRaw
疑点已关闭、Adobe DNG SDK 许可解读已修正，见 §6）。

**三项必读警示（发布前必决，NOTICES 无法化解第 1 项）**：

> **警示一（最高危）：huesat 的 RawTherapee GPL-3.0 代码衍生。**
> `src/pixo/render/core/huesat.py:5-6` 自述实现「经 RawTherapee rtengine/dcp.cc 移植」，
> RawTherapee 为 GPL-3.0。这是**代码衍生而非依赖**，不能靠本 NOTICES 化解——GPL 衍生代码
> 使非 GPL 分发违约。发布前必须先行处置（重写 / git 考古核实是否仅注释表述夸大 / 隔离）。
> 完整分析见 §6 与 `.agent-team/research/dng-sdk-review.md`（F18 高危 H1）。

> **警示二：DCP 相机配置 ×6 的再分发条款未核验（R22 #3 已逐项盘点，结论＝待处置）。**
> `resources/dcp/` 6 个 .dcp 文件名指向 RawLab（rawlab.net 社区 DCP 分发站，推测，置信度中），
> 其再分发条款未经核验；且 `pyproject.toml [tool.setuptools.data-files]` 将 `resources/dcp/*.dcp`
> 打包，**会随 wheel 分发**。发布前必须核验来源 profile 的再分发许可（F18 §3.3-4 同项）。
> **R22 逐项盘点（2026-09-10，证据 `.agent-team/tmp-r22b2-dcp{,2,3}.txt`）**：6 个文件内嵌
> **无任何** license/copyright/permission/http/CC 条款文本；`ProfileCopyright`（tag 0xC6F4）
> 一律为生产者标签 `"RawLab fitted profile"`（本仓 DCP 写入器同值：`core/calibration.py:388`），
> `ProfileCalibrationSignature`（0xC612）为 `"com.adobe"`（同为写入器缺省值 `:386`，**不构成
> Adobe 血缘**）。⇒ 依文件内证据**不能判定为可发布**：须取得 RawLab 再分发许可，或替换为
> 自产/官方 DCP 后重跑标定与门禁。**注意本项不能按「纯登记资产」从打包面移除**——DCP 本体是
> 运行时素材（`service/runtime.py:41-46 _DEFAULT_DCP` → `:320` → `Renderer`/`load_dcp`）。

> **警示三：NC 模型的 internal_development_only 门控状态。**
> uniface（face-parsing，NC 已 web 复核）与 sapiens（CC-BY-NC-4.0 已 web 复核）两个后端
> 默认不进 multi 路由，需 `PIXO_ALLOW_RESTRICTED=1` 显式放行（`model_licenses.json` 两处
> notes；`publishable=false`）。登记与门控一致，属「可发布但不可商用分发」项——任何默认
> 路径变更前必须保持该门控。

---

## 1. Python 运行时依赖（必装）

来源：`requirements.txt` == `pyproject.toml [project.dependencies]`（F17 后为 7 项）。许可证据
均经实读/实查（dist-info、GitHub LICENSE、PyPI JSON API），明细见清单 §1.1。

| 包 | 约束 | 许可 | 核验方式 | 主页 |
|---|---|---|---|---|
| rawpy | >=0.23 | **MIT**（rawpy 本体，© 2014 Maik Riechert）+ 捆绑 **LibRaw LGPL-2.1** | dist-info 实读：`LICENSE`=MIT、`LICENSE.LibRaw`=LGPL-2.1 全文 | https://pypi.org/project/rawpy/ ；LibRaw: https://www.libraw.org/ |
| numpy | >=1.26 | BSD-3-Clause（Copyright (c) 2005-2025, NumPy Developers） | GitHub LICENSE.txt 实读 | https://pypi.org/project/numpy/ |
| opencv-python | >=4.8 | Apache-2.0 | PyPI JSON API classifier 实查 | https://pypi.org/project/opencv-python/ |
| ExifRead | >=3.5 | BSD-3-Clause（Gene Cash / Ianaré Sévi） | dist-info LICENSE 实读 | https://pypi.org/project/ExifRead/ |
| pyyaml | >=6.0 | MIT | PyPI JSON API 实查 | https://pypi.org/project/PyYAML/ |
| fastapi | >=0.115 | MIT | GitHub LICENSE 实读 | https://pypi.org/project/fastapi/ |
| uvicorn | >=0.30 | BSD-3-Clause（© 2017-present, Encode OSS Ltd） | dist-info LICENSE.md 实读 | https://pypi.org/project/uvicorn/ |

**rawpy → LibRaw 捆绑说明**（清单 §0.3，本清单新解决项）：`PIXO_LICENSE_REVIEW.md:46`
遗留的「需核验」疑点已关闭——rawpy 安装元数据同时携带 rawpy 本体 MIT 许可与捆绑的 LibRaw
LGPL-2.1 许可全文。**分发义务 = 随分发物附这两份许可文本**（LGPL 动态链接场景下以附文本
方式可满足义务）。

标准义务摘要（非法律意见）：MIT/BSD-3-Clause 分发须保留版权与许可声明；Apache-2.0 分发须
附许可证全文并遵守 NOTICE/变更说明要求。

## 2. 可选依赖、dev 依赖与懒 import 依赖

**可选依赖组**（`pyproject.toml [project.optional-dependencies]`，清单 §1.2）：

| extras 组 | 条目 | 约束 | 许可 | 核验方式 |
|---|---|---|---|---|
| pixo-render | （空） | — | — | — |
| pixo-vision | onnxruntime | >=1.16 | MIT | PyPI JSON API classifier 实查 |
| pixo-vision-models | torch | >=2.0 | BSD-3-Clause（© 2016- Facebook, Inc.）；打包内含约 120 个第三方组件许可文件 | 安装 2.13.0+cu126 LICENSE 实读 |
| pixo-vision-models | transformers | >=4.30 | Apache-2.0 | PyPI JSON API 实查 |
| pixo-meta | （空） | — | — | — |
| **calib**（F17 新增） | scipy | >=1.11 | BSD-3-Clause | PyPI JSON API classifier 实查 |
| dev（requirements-dev.txt 同） | pytest | >=8.0 | MIT（© 2004 Holger Krekel） | GitHub LICENSE 实读 |

torch 注记：若未来随分发物捆绑 torch 本体，其约 120 个第三方组件许可需整体合规；Pixo 当前
场景为终端用户自装（extras 指针），不构成再分发。

**懒 import 隐性依赖的当前口径**（清单 §1.3 + F17 变更）：

- **scipy**：`src/pixo/render/core/color.py:487`（`from scipy.optimize import least_squares`，
  DCP WB 求解）缺失时回退纯 numpy 粗网格。F17 起挂 extras `calib`（`pip install -e ".[calib]"`），
  `requirements.txt` 与 README 安装节均已注明「不装时标定拟合走 numpy 网格回退，较慢」。
- **PyYAML**：`src/pixo/decide/engine.py:257`、`src/pixo/know/graph.py:251`。原属懒 import
  隐性依赖；F17 起确认实为硬依赖（两处 ImportError 均无回退路径、decide/rules/ 5 个规则
  YAML 属核心链路），**已升必装**（见 §1 表）。

## 3. 模型权重（6 项）

来源：`model_licenses.json`（权威，6 条目）、`src/pixo/manifests/vision_models.json`（2 条目，
**部分过期**）、`resources/models/models_reference.json`（指针文件，与下表对齐）。

| # | 模型 | 许可 | status / 门控 | 来源 | 核验状态 |
|---|---|---|---|---|---|
| M1 | aesthetic_scorer.pt（rsinema/aesthetic-scorer） | MIT | redistribution_allowed_with_license_notice | https://huggingface.co/rsinema/aesthetic-scorer | **随 wheel 分发**（2026-09-07 用户拍板；git 不跟踪磁盘产物；安装态 `sys.prefix/data` 自动解析，`PIXO_AESTHETIC_MODEL` 覆盖仍最高优先） |
| M2 | openai/clip-vit-base-patch32（aesthetic 底座） | MIT | redistribution_allowed_with_license_notice（运行时 HF 自动下载，不入仓） | https://huggingface.co/openai/clip-vit-base-patch32 | 双台账一致；HF 页面未独立复核（可信度中高） |
| M3 | uniface-face-parsing（jonathandinu/face-parsing） | code MIT / **weights CC BY-NC-SA**（CelebAMask-HQ 派生） | **internal_development_only**，publishable=false，路由门控 `PIXO_ALLOW_RESTRICTED=1` | https://huggingface.co/jonathandinu/face-parsing | web 复核通过（2026-09-07）：model card 自述 non-commercial；NC 溯源 CelebAMask-HQ 数据集 |
| M4 | rfdetr-seg-2xl（roboflow RF-DETR-Seg） | Apache-2.0 | redistribution_allowed_with_license_notice（rfdetr pip 包首用下载） | https://github.com/roboflow/rf-detr | 台账登记；未独立复核（可信度中高） |
| M5 | segformer-b1-finetuned-ade-512-512（NVIDIA） | code Apache-2.0（原始）/ ADE20K 微调权重「随发布口径」 | **口径已裁决（R22 #3）**：`publishable=false`（可发布性权威字段）与 `status=usage=redistribution_allowed_with_license_notice`（**许可族档位**，两字段镜像由 `tests/unit/test_model_licenses.py::test_status_mirrors_usage` 钉死）不属同一语义 ⇒ 原「自相矛盾」表述作废、登记口径自洽 | https://huggingface.co/nvidia/segformer-b1-finetuned-ade-512-512 | **存疑（本清单最大未决项）**：ADE20K 数据集商用条款不明确，HF license tag 未独立复核；**发布前须核验**。引入第三档「待核验」usage 值需同步 `USAGE_VOCAB` 与 `multi_router` 门控语义（登记 `docs/tech_debt.md` 条目 3 遗留） |
| M6 | facebook/sapiens-seg-0.3b（Meta） | **CC-BY-NC-4.0**（HF 页 tag；Sapiens 论文自述 CC BY-NC-SA 4.0，SA 之差——取 HF tag 并列注记） | **internal_development_only**，publishable=false，隔离文件 `src/pixo/vision/segmenters/sapiens_body.py`，路由门控同 M3 | https://huggingface.co/facebook/sapiens-seg-0.3b-torchscript | web 复核通过（2026-09-07） |

**打包配置（2026-09-07 实测修正+用户决策）**：`resources/models/README.md:3`「不保存大文件
权重」指 git 布局（`.gitignore` 排除 `*.pt`）。**权重现随 wheel 分发**（用户 2026-09-07
拍板）：data-files 显式包含 `aesthetic/*.pt`，加载器候选链含安装态 `sys.prefix/data/`
落位（env > 仓库布局 > 安装态 > 旧式前缀，单测钉死）。历史缺陷存档：data-files 目录
通配符曾致 wheel 构建失败（任何检出可复现），2026-09-07 队长修复（显式文件列表），
实测 310MB wheel 构建通过。MIT 分发义务由本声明承载。

**台账冲突 A（✅ 已校正，2026-09-10 R22 #3）**：`src/pixo/manifests/vision_models.json:14` 曾写
aesthetic「需核验」+ 旧 `$GUANLAN_ROOT` 路径，与 `model_licenses.json` 的 MIT 定论冲突——现已对齐：
`license = "MIT"`、`publishable = true`、`path_or_source = "resources/models/aesthetic/aesthetic_scorer.pt"`
（`delivery = in_repo`）；`vision_models.json` 的 `updated` 同步为 2026-09-10。双台账一致性由
`tests/unit/test_tech_debt_invariants.py::test_vision_model_path_or_source_resolution_rules` 守卫
（`$VAR` 形态解析不了即报「待核验」，不静默通过）。

gsam 相关条目已确认删除（F04 移除后全仓零残留，清单终验）。

## 4. 前端依赖（`frontend/package.json`）

解析源：`frontend/package-lock.json`（lock 内置 license 字段程序化提取，2026-09-07）。
直接依赖 12 项 + 传递依赖 132 项 = **144 包**；逐包 license 字段无空缺、无 copyleft
（GPL/AGPL 类）命中。

直接依赖（12 项，解析版本与许可）：

| 包 | 约束 | 解析版本 | 许可 |
|---|---|---|---|
| @mantine/core、@mantine/hooks | ^7.17.8 | 7.17.8 ×2 | MIT |
| react、react-dom | ^18.3.1 | 18.3.1 ×2 | MIT |
| zustand | ^5.0.3 | 5.0.15 | MIT |
| lucide-react | ^1.33.0 | 1.33.0 | **ISC**（唯一 ISC 项，见下） |
| @types/react、@types/react-dom | ^18.3.x | 18.3.31 / 18.3.7 | MIT |
| @vitejs/plugin-react | ^4.3.4 | 4.7.0 | MIT |
| vite | ^5.4.11 | 5.4.21 | MIT |
| typescript | ~5.6.3 | 5.6.3 | Apache-2.0 |
| playwright | ^1.62.1 | 1.62.1 | Apache-2.0 |

lucide-react（ISC）分发义务：随分发物附 ISC 许可文本。ISC 为标准模板：
"Permission to use, copy, modify, and/or distribute this software for any purpose with or
without fee is hereby granted, provided that the above copyright notice and this permission
notice appear in all copies."（https://opensource.org/licenses/ISC）

**覆盖度声明（如实）**：传递依赖（@babel 系、esbuild 平台二进制等）的「全宽松」结论基于
lock 文件 license 字段统计与抽样核验（@babel 7.29.7-8 MIT、@esbuild MIT），**未逐包人工
法律复核**（可信度中高）。分发前端构建产物前，建议用 license-checker 类工具做一次全量终验。

## 5. native 构建链与语料/数据

**native 构建链（`src/pixo/render/native/`）——NOTICES 负担：无。**
仓内 C++ 源码 19 文件（abi/colorcal/decode/hsv/lut3d/oklab/refine/stage_kernels/warm_sat）
自研、无 vendored 第三方代码（grep third-party/vendored/copyright/license 零命中；F18 已验
native 无 DNG/Adobe 引用）。MinGW-w64 + CMake 为构建期工具不随产物分发；产物 DLL 不入库
（`native/README.md`）。注：CMakeLists.txt:14 有一处「与 guanlan dng_engine 一致」注释，
指向 guanlan 项目的另一溯源线（见 §6 L-2 类），native 代码本身无 Adobe 引用。

**语料/数据**（清单 §5）：

| 项 | 位置 | 许可判定 |
|---|---|---|
| DCP 相机配置 ×6 | `resources/dcp/` | **待处置（警示二；R22 #3 逐项盘点）**：RawLab 生产者标签来源，6 文件内嵌**零许可/版权条款文本** ⇒ 不能判定为可发布；被 pyproject data-files 打包随 wheel 分发，且为**运行时素材**（服务默认 DCP）。逐项见下表 |
| HSM→OKLCh 点云 ×1 | `configs/color/hsm_oklch_nikon_z_5_2_rawlab_lr_adobe_standard_baseline.json` | 自产数据但**血缘继承**上述 DCP（ProfileLookTable 23040 网格→2765 点采样，JSON `source_dcp` 自述）→ 同挂「发布前核验」标签 |
| RP-CCM / skin_oklab / warmth_curve 拟合产物 | `configs/color/rp_ccm_nikon_z5_2.json`、`configs/color/skin_oklab.json`、`configs/calibration/warmth_curve.json` | 自产（本仓语料拟合），无第三方许可面 |
| LR 预设 / 风格卡 24+2 / LUT 卡 | `configs/styles/` | 自产 JSON；仓内无 .cube 文件，运行时 LUT 目录回退指向**仓外** `guanlan/luts`（`src/pixo/render/core/lut.py:28`）——分发环境无该目录则 LUT 功能不可用（功能问题），LUT 内容若来自 guanlan 需按 §6 L-2 口径确认 |
| 金样本数据 | `data/golden/` | 自产回归数据（Nikon 自摄语料，README 无详述，推测置信度中） |

**DCP ×6 逐项盘点（R22 #3，2026-09-10；实读 IFD0 与二进制内嵌串，证据
`.agent-team/tmp-r22b2-dcp2.txt` / `-dcp3.txt`）**：

| # | 文件 | sha256[:16] | `manifest.json` 引用 | UniqueCameraModel(0xC614) | ProfileCopyright(0xC6F4) | 判定 |
|---|------|-------------|----------------------|---------------------------|--------------------------|------|
| 1 | `Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp` | `aefcae08e6e7bd90` | ✅ `lr_adobe_standard_v2` | `Nikon Z 5 2 RawLab LR Baseline`（与文件名不符） | `RawLab fitted profile` | **待处置** |
| 2 | `Nikon Z 5 2 RawLab LR Baseline.dcp` | `f3a19d9a59ad9f8b` | ✅ `lr_camera_standard_v2` | `Nikon Z 5 2 RawLab LR Camera Standard Baseline`（与文件名不符） | `RawLab fitted profile` | **待处置** |
| 3 | `Nikon Z 5 2 RawLab LR Camera Standard Baseline.dcp` | `f3a19d9a59ad9f8b` | ❌ | 同 #2 | `RawLab fitted profile` | **待处置**（与 #2 **逐字节重复**） |
| 4 | `Nikon Z 5 2 RawLab Preview Baseline.dcp` | `b21f2149b9890f38` | ✅ `camera_preview` | `Nikon Z 5 2 RawLab Preview Baseline` | `RawLab fitted profile` | **待处置** |
| 5 | `Nikon Z 5 2 RawLab Preview Baseline v2.dcp` | `8d9d911a90f3d8f9` | ❌ | `…Preview Baseline v2` | `RawLab fitted profile` | **待处置** |
| 6 | `Nikon Z 5 2 RawLab Preview Baseline v3.dcp` | `9b27eb48f1ee7e67` | ❌ | `…Preview Baseline v3` | `RawLab fitted profile` | **待处置** |

- **来源标注**：6 个文件内**唯一**可归属线索是文件名与内嵌标签 `RawLab`；仓内无 URL/条款/
  授权声明（`git grep -i rawlab` 命中仅文件名引用与 `RawLab fitted profile` 标签）。NOTICES
  原记「rawlab.net，推测置信度中」维持。
- **许可文本核验**：6 文件 `grep -c` 于 `copyright` / `license` / `permission` / `reserved` /
  `http` / `creativecommons` / `CC BY` **全部 0 次** ⇒ 无内嵌授权，**不可判定为可发布**。
- **结论（可发布 / 待处置）**：**6/6 待处置**。可发布路径二选一：①取得 RawLab 再分发许可并
  附文本；②替换为自产/官方 DCP 后重跑标定（`configs/color/*`、`skin_oklab.json`、暖度/曝光表）
  与门禁。**不得**简单从 wheel 剔除 `resources/dcp/*.dcp`（服务默认 DCP 为运行时素材）。
  替换属独立变更，本轮未实施，登记 `docs/tech_debt.md` 条目 3 遗留 / R23。

**登记资产声明（非运行时消费）**：`resources/dcp/manifest.json` 与
`configs/styles/lr_baseline.json`、`lr_camera_standard_baseline.json` 两张 LR 基线预设为
**登记资产、非运行时消费**（队长裁定口径，2026-09-07；证据链见
`.agent-team/streams/stream-1.md` F05 节）——manifest 的 `default_lr_preset`/`lr_baseline`
在 src/pixo 零代码引用，lr_baseline 预设不在生产风格卡体系（`know/cards.py`）与默认管线
（`presets.py` DEFAULT_STAGES）任何加载面上，当前唯一消费者为测量脚本
`scripts/measure_u8_precision.py`。它们不构成运行时第三方素材面；其中 DCP 文件本体的
再分发核验义务不因此免除（仍见警示二）。**R22 补正（2026-09-10）**：上述「非运行时消费」
只对 `manifest.json` 与两张 LR 预设成立；**DCP 文件本体是运行时素材**
（`src/pixo/service/runtime.py:41-46 _DEFAULT_DCP` → `:320` → `Renderer` → `load_dcp`），
因此「从 wheel 打包面剔除 DCP」不是本项的合法处置路径。

## 6. 代码衍生项专节（非依赖，NOTICES 只能披露、不能化解）

完整分析见 `.agent-team/research/dng-sdk-review.md`（F18，2026-09-07）。本节为发布维护者
摘要，血缘认定以 F18 逐条证据为准。

### 6.1 huesat 的 RawTherapee GPL-3.0 血缘（警示一，最高优先）

- `src/pixo/render/core/huesat.py:5-6` 自述实现「Adobe 参考实现 (dng_render.cpp /
  dng_color_spec.cpp) **经 RawTherapee rtengine/dcp.cc 移植**」；:286-289 进一步自述
  encode/decode 表与 `dng_render.BuildHueSatMapEncodingTable` 「逐项一致」；生产代码内
  保留「DNG SDK 基准复刻」执行路径开关（`modules/huesat.py:18,168,176`）。
- RawTherapee 为 GPL-3.0（https://github.com/RawTherapee/RawTherapee ）。若移植属实，
  该文件为 GPL 衍生品：**非 GPL 形态的任何分发（含闭源与多数开源许可组合）均违约**。
- 待决问题（F18 §3.3-2，需队长/用户拍板）：该血缘是「注释表述夸大」还是「真实取码」——
  git 历史比对可判；若仅为表述夸大，降级为改注释即可。
- 在此问题解决前，本文件的登记**不构成对该项的合规化**。

### 6.2 Adobe DNG SDK 衍生痕迹概述

- **痕迹总量**：DNG 关键词命中 286 行（排除生成物缓存；src 217 / docs 45 / tests 19 /
  scripts 3 / configs 1 / 根文件 1）。实质性溯源痕迹约 **35 项，覆盖 18 个文件**：
  高 12（注释自认移植/同构/读源码，如 `color.py:587`「注意 DNG 源码用 D50_xy_coord()…」
  为读源码直接证据；`docs/架构设计文档.md:859` 仓库自认移植）、中 11（以 SDK 源文件或内部
  行为为权威依据）、低 12（clean-room 声明/命名/路径/流程文档）。
- **许可事实（F18 修正仓库既有假设）**：Adobe DNG SDK 许可原文明确授予 "prepare
  derivative works from … distribute and sublicense the Software for any purpose"
  （一手原文：https://scancode-licensedb.aboutcode.org/adobe-dng-sdk.LICENSE ）。真实约束：
  ① 分发人类可读副本须保留 Adobe 版权声明；② 商业分发触发对 Adobe 的赔偿义务（§5）；
  ③ **不可再授权**——SDK 衍生代码不能以本项目自身许可（含开源许可）再发布；
  ④ SDK 文档不得修改；⑤ DNG 规范另行许可（与 SDK 分离），SDK 许可无专利授权，DNG 格式
  实施另有单独的规范专利许可（可撤销）。
  因此：闭源商业发布**可行但带上述义务**；**开源发布被阻断**（项目方向为开源，
  `PIXO_RENDER_OWN_PIPELINE.md:171`）。`PIXO_LICENSE_REVIEW.md:115` 的「不能移植进发布
  产品」属过严解读，但其开源阻断结论在「不可再授权」理由下依然成立。
- **clean-room 声明现状**：warp.py / tone.py / resample.py 声明 clean-room + 黑盒 oracle
  （符合业界黑盒惯例），但引用的 `CLEANROOM_M1..M5.md` 过程记录**不在仓库内**，主张目前
  缺纸面证据；color.py 的注释（H4-H8）构成「读过源码」的直接反证，不满足 clean-room。
- **发布前动作参考**（F18 §3.2 选项 A-D，供决策非本文件裁定）：warp/tone/resample 补
  过程证据；color/huesat/io 按发布形态选重写（B）或隔离声明（C）；无论何种形态，
  §6.1 的 GPL 线都须单独先行排除。

### 6.3 guanlan（观澜）移植与仓外复用

- `src/pixo/meta/burst.py:3,11`、`src/pixo/meta/lighting.py:3,11`、
  `src/pixo/vision/measure.py:14`、`src/pixo/vision/aesthetic.py:3` 自述移植/迁移自
  guanlan（观澜）项目；`src/pixo/render/core/lut.py:28` 运行时 LUT 目录回退指向仓外
  `guanlan/luts`。
- guanlan 推断为组织内部前作（命名与工作流措辞推断，置信度中），**无独立许可文本登记**——
  其许可性质需队长确认。若未来分发涉及上述代码或 LUT 内容，须先补该确认。
- `src/pixo/vision/health.py:5` 为注释级提及（非真实 import），无许可面。

## 7. 存疑/冲突速查表（发布前逐项核销）

| 项 | 状态 | 处置口径 |
|---|---|---|
| huesat RawTherapee GPL 血缘 | 高危未决（F18） | 发布前必决：核实/重写/隔离（§6.1） |
| DCP ×6 再分发条款 | **待处置**（RawLab 生产者标签；6 文件内嵌零许可文本，R22 #3 逐项盘点） | 取得 RawLab 许可或替换 DCP 后重跑标定；wheel 打包事实并陈（§5）。**不可**从打包面剔除（运行时素材） |
| segformer ADE20K 权重 | 存疑（数据集条款不明；`publishable=false` 为权威） | publishable=false、发布前须核验（§3 M5）；口径裁决已消除 `publishable`/`status` 的表面冲突 |
| sapiens 许可 SA 差异 | HF 页 CC-BY-NC-4.0 vs 论文 CC BY-NC-SA 4.0 | 取 HF tag，已并列注记（§3 M6） |
| ~~aesthetic_scorer.pt 位置~~ | 初版误报「在仓+随 wheel 打包」；实测：磁盘部署产物（不入 git）、曾致 wheel 构建失败（data-files 目录通配） | **已修复（2026-09-07）**：打包配置改显式文件列表，构建通过，权重不进包=既定设计 |
| vision_models.json | ✅ 已校正（2026-09-10 R22 #3） | 与 `model_licenses.json` 对齐：aesthetic = MIT / publishable=true / 仓内路径；`$GUANLAN_ROOT` 旧路径作废（§3 冲突 A） |
| guanlan 许可性质 | 未确认（内部推断） | 内部移植披露 + 待队长确认（§6.3） |
| clean-room 过程记录 | CLEANROOM_M1..M5 不在仓 | 补档或 git 考古后才能坐实 warp/tone/resample 主张（§6.2） |
| Adobe DNG SDK 专利面 | SDK 许可无专利条款；DNG 规范专利许可另立可撤销 | 见 F18（本文件 §6.2）；未做专利检索 |
| 前端传递树 132 包 | lock 字段统计全宽松，未逐包人工复核 | 分发前工具化终验（§4） |
