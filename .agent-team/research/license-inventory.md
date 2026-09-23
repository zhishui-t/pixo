# Pixo 许可素材清单（F16，供 writer 成文 THIRD_PARTY_NOTICES.md）

- 日期：2026-09-07 · 方法：只读盘点（requirements/pyproject/lock 文件/安装元数据/台账 JSON 交叉核对）+ PyPI/deps.dev/GitHub/HF 许可核验
- 上游：F04 gsam 移除（已验证：全仓 src/manifests/configs 对 `gsam|grounded` **零残留**，`grounded_sam.py` 文件已删除——注：本会话扫描中途落地，前后两次 grep 结果不同，以当前树为准）
- 配套：Adobe DNG SDK / RawTherapee GPL 血缘的完整分析见同目录 `dng-sdk-review.md`（F18）
- 契约：本清单只供素材，**不做决策**；逐项给来源与可信度

---

## 0. 结论（前置）：许可面总体判定

1. **总体**：运行时依赖全部为 MIT/Apache/BSD 宽松许可（12 项 Python + 12 项前端直接依赖，前端传递树 144 包亦全宽松）；**不可分发项集中在模型权重（2 个 NC 后端，已门控）与代码/数据血缘（RawTherapee GPL、Adobe DCP/SDK 痕迹、guanlan 移植）**。内部研发可行；对外分发的阻断面与 `PIXO_LICENSE_REVIEW.md` 判断一致并有所更新（见下）。
2. **F18 高危发现重申（NOTICES 必须反映）**：`src/pixo/render/core/huesat.py:5-6` 自述实现「经 RawTherapee rtengine/dcp.cc 移植」，RawTherapee 为 **GPL-3.0**（来源：[RawTherapee 仓库](https://github.com/RawTherapee/RawTherapee)）——这是**代码衍生而非依赖**，不能靠 NOTICES 化解，须先决（重写/核实/隔离），NOTICES 成文只能如实披露。
3. **本会话新解决**：rawpy 捆绑 LibRaw 的许可疑点（`PIXO_LICENSE_REVIEW.md:46` 遗留「需核验」）已落地——安装元数据同时携带 `LICENSE`（rawpy 本体 **MIT**，© 2014 Maik Riechert）与 `LICENSE.LibRaw`（**LGPL-2.1**）（来源：本机 `site-packages/rawpy-0.27.0.dist-info/`，文件实读）。分发义务 = 随分发物附两份许可文本（LGPL 动态链接场景下可满足）。
4. **本会话新发现（3 处台账矛盾，writer 需按本清单口径取数）**：
   - `resources/models/README.md:3` 称「不保存大文件权重」，但 `resources/models/aesthetic/aesthetic_scorer.pt`（333.7MB）**实际在仓**，且 `pyproject.toml` `[tool.setuptools.data-files]` 打包 `resources/models/*` → **随 wheel 分发**（MIT，可分发但必须附声明）；
   - `manifests/vision_models.json:14` 仍写 aesthetic「需核验」+ 旧 `$GUANLAN_ROOT` 路径，与 `model_licenses.json` 的 MIT 定论冲突（前者过期）；
   - `model_licenses.json` segformer 条目自相矛盾：`publishable: false` 但 `usage/status = redistribution_allowed_with_license_notice`（§2 表内详述）。
5. **NC 模型现状**：uniface（face-parsing，**NC 已 web 复核**）与 sapiens（**CC-BY-NC-4.0 已 web 复核**）默认不进路由、需 `PIXO_ALLOW_RESTRICTED=1`（`model_licenses.json` 两处 notes）——登记与门控一致，属「可发布但不可商用分发」项。

---

## 1. Python 依赖

版本约束来源：`requirements.txt` / `requirements-dev.txt` / `pyproject.toml [project.optional-dependencies]`（逐条实读）。许可核验来源标注于每行。URL 一律为 PyPI 官方项目页。

### 1.1 运行时依赖（`requirements.txt` == `pyproject dependencies`，6 项）

| 包 | 约束 | 许可 | 许可证据 | URL |
|---|---|---|---|---|
| rawpy | >=0.23 | **MIT**（rawpy 本体）+ 捆绑 **LibRaw LGPL-2.1** | dist-info 实读：`LICENSE`=MIT(©2014 Maik Riechert)、`LICENSE.LibRaw`=LGPL-2.1 全文；`PIXO_LICENSE_REVIEW.md:46` 遗留疑点就此关闭 | https://pypi.org/project/rawpy/ ；LibRaw: https://www.libraw.org/ |
| numpy | >=1.26 | BSD-3-Clause | GitHub LICENSE.txt 实读（"Copyright (c) 2005-2025, NumPy Developers"）；安装 2.5.1 携带多个 bundled License-File（lapack_lite/pocketfft 等，wheel 分发义务归 numpy 上游，Pixo 不再分发） | https://pypi.org/project/numpy/ |
| opencv-python | >=4.8 | Apache-2.0 | PyPI JSON API：`License :: OSI Approved :: Apache Software License`（本会话实查） | https://pypi.org/project/opencv-python/ |
| ExifRead | >=3.5 | BSD-3-Clause（Gene Cash / Ianaré Sévi） | 安装 dist-info LICENSE 实读（"Copyright (c) 2002-2007 Gene Cash…"） | https://pypi.org/project/ExifRead/ |
| fastapi | >=0.115 | MIT | GitHub LICENSE 实读（"The MIT License (MIT)"）；PyPI latest 0.141.1 | https://pypi.org/project/fastapi/ |
| uvicorn | >=0.30 | BSD-3-Clause（Encode OSS） | 安装 dist-info LICENSE.md 实读（"Copyright © 2017-present, Encode OSS Ltd"） | https://pypi.org/project/uvicorn/ |

### 1.2 可选依赖组（`pyproject.toml:18-28`）

| 组 | 条目 | 约束 | 许可 | URL |
|---|---|---|---|---|
| `pixo-render` | （空） | — | — | — |
| `pixo-vision` | onnxruntime | >=1.16 | MIT | PyPI JSON API 实查（MIT License classifier）；https://pypi.org/project/onnxruntime/ |
| `pixo-vision-models` | torch | >=2.0 | **BSD-3-Clause（PyTorch）**+ 打包内含大量第三方组件（dist-info 携带 ~120 个 third_party License 文件，分发 torch 本体时需整体合规；Pixo 场景为终端用户自装，指针即可） | 安装 2.13.0+cu126 LICENSE 实读（"Copyright (c) 2016- Facebook, Inc"）；https://pypi.org/project/torch/ |
| `pixo-vision-models` | transformers | >=4.30 | Apache-2.0 | PyPI JSON API 实查（"Apache 2.0 License"）；https://pypi.org/project/transformers/ |
| `pixo-meta` | （空） | — | — | — |
| `dev`（requirements-dev.txt 同） | pytest | >=8.0 | MIT | GitHub LICENSE 实读（"The MIT License (MIT), Copyright (c) 2004 Holger Krekel"）；https://pypi.org/project/pytest/ |

### 1.3 懒 import 隐性依赖（不在任何 requirements 中，代码内延迟 import）

| 包 | import 位置 | 许可 | URL | 说明 |
|---|---|---|---|---|
| scipy | `src/pixo/render/core/color.py:487`（`from scipy.optimize import least_squares`，DCP WB 求解） | BSD-3-Clause | PyPI JSON API 实查（BSD classifier）；https://pypi.org/project/scipy/ | `PIXO_LICENSE_REVIEW.md:52` 已登记；tech_debt #4 要求在安装说明声明 |
| PyYAML | `src/pixo/decide/engine.py:257`、`src/pixo/know/graph.py:251`（`import yaml`） | MIT | PyPI JSON API 实查（MIT）；https://pypi.org/project/PyYAML/ | 同上 |

---

## 2. 模型权重

来源文件：`model_licenses.json`（6 条目，gsam 条目已确认删除）、`src/pixo/manifests/vision_models.json`（2 条目，**部分过期**）、`resources/models/models_reference.json`（指针文件）。**交叉核对结论：以 model_licenses.json 为准**，冲突逐条标注。

| # | 模型 | 台账许可 | 台账 status | 来源 URL | 核验状态 / 冲突 |
|---|---|---|---|---|---|
| M1 | aesthetic_scorer.pt（rsinema/aesthetic-scorer，HF） | MIT | redistribution_allowed_with_license_notice | https://huggingface.co/rsinema/aesthetic-scorer | **在仓**（333.7MB，`resources/models/aesthetic/`）；**冲突 A**：`vision_models.json:14` 仍写「需核验（来源 rsinema/aesthetic-scorer）」+ 旧 `$GUANLAN_ROOT` 路径——过期，以 MIT 定论为准（可信度：model_licenses.json 高，含 README front-matter 与键名形状核对记录） |
| M2 | openai/clip-vit-base-patch32（aesthetic 底座） | MIT | redistribution_allowed_with_license_notice（运行时 HF 自动下载，不入仓） | https://huggingface.co/openai/clip-vit-base-patch32 | 两台账一致（MIT）；`vision_models.json:25` 同口径。**未独立复核 HF 页面**（可信度中高：双台账一致 + OpenAI CLIP MIT 为公知） |
| M3 | uniface-face-parsing（jonathandinu/face-parsing，HF） | code MIT / weights CC BY-NC-SA（CelebAMask-HQ 派生） | **internal_development_only**，publishable=false，路由门控 `PIXO_ALLOW_RESTRICTED=1` | https://huggingface.co/jonathandinu/face-parsing | **web 复核通过（本会话）**：model card 自述 non-commercial research/educational；NC 属性溯源自 CelebAMask-HQ 数据集（[数据集页](https://mmlab.ie.cuhk.edu.hk/projects/CelebA/CelebAMask_HQ.html)、[GitHub](https://github.com/switchablenorms/CelebAMask-HQ)） |
| M4 | rfdetr-seg-2xl（roboflow RF-DETR-Seg） | Apache-2.0 | redistribution_allowed_with_license_notice（rfdetr pip 包首用下载） | https://github.com/roboflow/rf-detr | 台账登记；**未独立复核**（可信度中高：Apache 为 RF-DETR 公开口径） |
| M5 | segformer-b1-finetuned-ade-512-512（NVIDIA，HF） | code Apache-2.0(原始) / ADE20K 微调权重「随发布口径」 | 条目**自相矛盾**：publishable=false 但 status=redistribution_allowed_with_license_notice | https://huggingface.co/nvidia/segformer-b1-finetuned-ade-512-512 | **存疑（本清单最大未决项）**：ADE20K 数据集的商用条款不明确，HF 页面 license tag 未独立复核；代码侧 `segformer_scenes.py:5` 自述「权重随 ADE 派生口径」。**writer 暂按「存疑、发布前须核验」成文** |
| M6 | facebook/sapiens-seg-0.3b（Meta，HF） | CC-BY-NC-4.0（Sapiens2 License 口径） | **internal_development_only**，publishable=false，隔离文件 `src/pixo/vision/segmenters/sapiens_body.py`，路由门控同 M3 | https://huggingface.co/facebook/sapiens-seg-0.3b-torchscript | **web 复核通过（本会话）**：HF 页 CC-BY-NC-4.0；**并列差异**：[Sapiens 论文](https://arxiv.org/html/2408.12569v1) 自述 CC BY-NC-SA 4.0（SA 之差，writer 取 HF 页 tag 并加注） |

**台账间一致性**：`models_reference.json` 仅指针（segmentation×4 + aesthetic×2）与上表对齐；gsam 零残留（本会话终验）。

---

## 3. 前端依赖（`frontend/package.json`）

解析源：`frontend/package-lock.json`（lock 内置 license 字段，本会话程序化提取；node_modules 在盘可交叉）。直接依赖 12 项 + 传递依赖 132 项 = **144 包**，逐包 license 字段无空缺、无 copyleft（GPL/AGPL 类）命中。

| 包（直接依赖） | 约束 | 解析版本 | 许可 |
|---|---|---|---|
| @mantine/core / @mantine/hooks | ^7.17.8 | 7.17.8 ×2 | MIT |
| react / react-dom | ^18.3.1 | 18.3.1 ×2 | MIT |
| zustand | ^5.0.3 | 5.0.15 | MIT |
| lucide-react | ^1.33.0 | 1.33.0 | **ISC**（唯一 ISC，NOTICES 需含 ISC 文本） |
| @types/react / @types/react-dom | ^18.3.x | 18.3.31 / 18.3.7 | MIT |
| @vitejs/plugin-react | ^4.3.4 | 4.7.0 | MIT |
| vite | ^5.4.11 | 5.4.21 | MIT |
| typescript | ~5.6.3 | 5.6.3 | Apache-2.0 |
| playwright | ^1.62.1 | 1.62.1 | Apache-2.0 |

传递依赖（@babel 系、esbuild 平台二进制等）lock 内许可字段全部 MIT/Apache/ISC 类（抽样核验 @babel 7.29.7-8 MIT、@esbuild MIT；**全量 144 包未逐包人工复核**，按 lock license 字段统计，可信度中高，建议 writer 成文时用 `license-checker` 类工具终验一遍）。

---

## 4. native 构建链（`src/pixo/render/native/`）

| 项 | 许可面 | 证据 |
|---|---|---|
| 仓内 C++ 源码（abi/colorcal/decode/hsv/lut3d/oklab/refine/stage_kernels/warm_sat，19 文件） | **自研，无 vendored 第三方代码** | 本会话 grep `third-party|vendored|copyright|license` 于 native/src 与 CMakeLists **零命中**；F18 已验 native 无 DNG/Adobe 引用 |
| 构建工具 MinGW-w64 + CMake | 构建期工具，不随产物分发；产物 DLL 不入库（`native/README.md`「build/ 不入库」「DLL 不入库」） | `src/pixo/render/native/README.md:16-18` |
| ctypes 运行时加载 | 无额外许可面 | 同上 |

**native 侧 NOTICES 负担：无**。

---

## 5. 语料 / 数据

| 项 | 位置 | 性质与许可判定 | 来源/可信度 |
|---|---|---|---|
| DCP 相机配置 ×6（含 `Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp` 等） | `resources/dcp/`（manifest.json 登记三 target + truth 层级；README 仅一行无来源） | **存疑**：文件名指向 RawLab（rawlab.net 社区 DCP 分发站），「Adobe Standard」为渲染意图命名非 Adobe 出品——**RawLab DCP 的再分发条款未核验**；且 `pyproject.toml` data-files 将 `resources/dcp/*.dcp` 打包 → **会随 wheel 分发**。F18 §3.3 已立「推测，置信度中」。Adobe DNG SDK 关联风险另见 F18（DCP 是格式数据，SDK 许可不覆盖之；DNG 规范另有专利许可） | `resources/dcp/manifest.json`、`README.md`（本会话实读）；**建议 writer 挂「发布前核验」标签** |
| HSM→OKLCh 点云 ×1 | `configs/color/hsm_oklch_nikon_z_5_2_rawlab_lr_adobe_standard_baseline.json` | 自产数据，但**血缘**：从上述 DCP 的 ProfileLookTable（23040 网格→2765 点采样）转换（JSON `source_dcp` 字段自述，「与 DNG SDK HSM 应用域一致」）→ 继承 DCP 的未核验许可面 + F18 M11 | F18 报告 §1 M11 |
| RP-CCM / skin_oklab / warmth_curve 等拟合产物 | `configs/color/rp_ccm_nikon_z5_2.json`、`configs/color/skin_oklab.json`、`configs/calibration/warmth_curve.json` | 自产（本仓语料拟合），无第三方许可面 | configs 实读 |
| LR 预设 / 风格卡 24+2 / LUT | `configs/styles/`（14 文件 + films/ 26 文件） | **自产 JSON**；注意：仓内**无 .cube 文件**（find 零命中），运行时 LUT 目录回退指向**仓外** `guanlan/luts`（`src/pixo/render/core/lut.py:28`）→ 若分发环境无该目录则 LUT 功能不可用（功能问题非许可问题，但 LUT 内容若来自 guanlan 需按 §6-2 处理） | lut.py:27-28 实读 |
| 金样本数据 | `data/golden/`（raw/reference/annotations；README 仅一行） | 自产回归数据（Nikon 自摄语料） | `data/golden/README.md`；**推测**（README 无详述，置信度中：raw/ 内容未逐文件核验） |

---

## 6. 代码血缘项（非依赖，NOTICES 必须反映——writer 重点段）

| # | 位置 | 血缘 | NOTICES 处置（供 writer，非决策） |
|---|---|---|---|
| **L-1（最高优先）** | `src/pixo/render/core/huesat.py:5-6` | **RawTherapee rtengine/dcp.cc 移植声明（GPL-3.0）**——F18 高危 H1；另 :286-289「与 dng_render.BuildHueSatMapEncodingTable 逐项一致」叠加 Adobe SDK 同构自认 | **不能仅靠 NOTICES 化解**：GPL 衍生代码使非 GPL 分发违约。成文时如实披露 + 显著标注「发布前须重写或核实」；完整分析见 `dng-sdk-review.md` |
| L-2 | `src/pixo/meta/burst.py:3,11`、`src/pixo/meta/lighting.py:3,11` | 「Ported/adapted from Guanlan (观澜) src/rules/burst_grouping.py / daylight.py」——guanlan 为组织内部前作（推断，无独立许可文本） | `PIXO_LICENSE_REVIEW.md §4` 已列「有归属但原项目许可未登记」；writer 按内部移植披露，**guanlan 许可性质需队长确认**（推测：内部项目，置信度中） |
| L-3 | `src/pixo/vision/measure.py:14`、`src/pixo/vision/aesthetic.py:3`（「迁移自 guanlan src/vision/aesthetic.py」） | guanlan 算法口径参考 / 代码迁移 | 同上 |
| L-4 | `src/pixo/render/core/lut.py:28` | 运行时 LUT 目录回退 `guanlan/luts`（仓外数据复用） | 数据来源登记缺失；同 L-2 待确认 |
| L-5 | `src/pixo/render/core/{calibration,color,huesat}.py`、`modules/{white_balance,huesat}.py`、`io.py` 等 | **Adobe DNG SDK 痕迹**（注释级引用/移植自认，F18 高 12 项/中 11 项/低 12 项） | 指向 `dng-sdk-review.md`；SDK 许可本身允许衍生+分发（附声明+商业分发赔偿条款），**开源发布阻断**——F18 §3 已述 |
| L-6 | `src/pixo/vision/health.py:5` | 注释级提及（非真实 import），无许可面 | F18/许可复审均已确认 |

---

## 7. 存疑 / 冲突汇总（writer 挂标签清单）

| 项 | 状态 | 建议成文口径 |
|---|---|---|
| DCP ×6 再分发条款 | **未核验**（RawLab 社区文件） | 「发布前核验」标签 + wheel 打包事实并陈 |
| segformer ADE20K 权重 | **存疑**（台账自相矛盾 + 数据集条款不明） | 「publishable=false、发布前须核验」 |
| sapiens 许可 SA 差异 | HF 页 CC-BY-NC-4.0 vs 论文 CC BY-NC-SA 4.0 | 取 HF tag + 并列注记（两来源已给出） |
| aesthetic_scorer 位置 | README 称不入仓 vs 实际在仓 + pyproject 打包 | 以实盘为准（在仓、随 wheel 分发、MIT 附声明）；README 属过期文档 |
| vision_models.json | 过期（需核验/旧路径） | 以 model_licenses.json 为准 |
| guanlan 项目许可性质 | **未确认**（内部推断） | 内部移植披露 + 待队长确认 |
| huesat RawTherapee GPL | **高危未决**（F18） | 显著披露 + 发布前必决 |
| 前端 132 传递包 | lock license 字段全宽松但未逐包人工复核 | 建议工具化终验后成文 |
| Adobe DNG SDK 专利面 | F18 已述：SDK 许可无专利条款、DNG 规范专利许可另立可撤销 | 指向 F18 报告 |

---

## 8. 来源清单

**仓库文件（本会话实读）**：`requirements.txt`、`requirements-dev.txt`、`pyproject.toml`、`model_licenses.json`、`src/pixo/manifests/vision_models.json`、`resources/models/models_reference.json`、`resources/models/README.md`、`resources/models/aesthetic/`（.pt 在盘实测）、`resources/dcp/manifest.json`、`resources/dcp/README.md`、`frontend/package.json`、`frontend/package-lock.json`（144 包 license 字段程序化提取）、`src/pixo/render/native/README.md` + native/src 19 文件（第三方代码零命中 grep）、`configs/color/`、`configs/styles/`、`data/golden/README.md`、`src/pixo/render/core/{color,lut}.py`、`src/pixo/decide/engine.py:257`、`src/pixo/know/graph.py:251`、`src/pixo/meta/{burst,lighting}.py`、`src/pixo/vision/{aesthetic,measure,health}.py`、`src/pixo/vision/segmenters/`（gsam 零残留终验）。

**安装环境（本机 site-packages 实读）**：rawpy-0.27.0.dist-info（LICENSE + LICENSE.LibRaw=LGPL-2.1）、uvicorn-0.52.1.dist-info（LICENSE.md）、torch-2.13.0+cu126.dist-info（LICENSE + ~120 第三方 License 文件）、ExifRead-3.5.1.dist-info（LICENSE）。

**web 核验（本会话）**：PyPI JSON API（opencv-python/onnxruntime/transformers/scipy/PyYAML classifier 实查）；GitHub LICENSE 实读（[numpy](https://github.com/numpy/numpy)、[fastapi](https://github.com/fastapi/fastapi)、[pytest](https://github.com/pytest-dev/pytest)）；[HF face-parsing](https://huggingface.co/jonathandinu/face-parsing)（NC 复核 + [CelebAMask-HQ](https://github.com/switchablenorms/CelebAMask-HQ)）；[HF sapiens-seg-0.3b-torchscript](https://huggingface.co/facebook/sapiens-seg-0.3b-torchscript)（CC-BY-NC-4.0 复核 + [Sapiens 论文](https://arxiv.org/html/2408.12569v1)）；[RawTherapee GPL-3.0](https://github.com/RawTherapee/RawTherapee)。

**明确标注的推测**：DCP 来源为 RawLab 社区（文件名推断，置信度中）；guanlan 为内部项目（命名与工作流措辞推断，置信度中）；前端传递树「全宽松」为 lock license 字段统计而非逐包法律复核（置信度中高）；goldens 数据全自产（README 无详述，置信度中）。
