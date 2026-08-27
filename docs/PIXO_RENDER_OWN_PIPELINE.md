# Pixo 自研渲染管线设计（Own Pipeline Roadmap）

> 状态：设计稿 v1（2026-08-27）。决策依据见 §9；前沿参考见 §7。
> 配套现状文档：`docs/架构设计文档.md`（现行 DNG 参照架构）、`docs/tech_debt.md`（质量债台账）。

---

## 0. 定位与原则

**目标**：把渲染逻辑从"DNG SDK 参照实现"演进为"自有渲染体系"——不是推翻重写，而是逐层替换底座，全程被现有质量门保护。

**四条原则**：
1. **电影工业式分层**：输入变换（IDT）→ 场景 referred 工作空间 → 创意变换层 → 输出变换（ODT）。DCP 降级为**互操作导入格式**，不再是内部渲染逻辑的源头。
2. **确定性优先**：与产品定位（测量→决策→渲染的可解释闭环 + 规则引擎 + LLM 副驾）一致——任何阶段运行时保持确定性、可参数化、可金样本锁定。学习成分只出现在"标定期"与"可选后端"，且受转正治理（§5）。
3. **安全网先行**：金样本门（RAW gate 12 features + SYNTH gate）、native 逐位等价测试、`scripts/run_ab_regression.py` 语料级 A/B 是每次换底座的前置与验收条件。这套资产在 2026-08 两轮深审中已验证可靠。
4. **每层独立可回退**：阶段间无硬依赖，任一层替换出问题可回退到 DNG 路径（DCP 解析永远保留）。

---

## 1. 现状盘点：DNG 底座 vs 已自研资产

| 层 | 现状 | 归属 | 替换优先级 |
|---|---|---|---|
| 曝光 | 二维标定表（med_log2×wb_B，19 结点）+ tanh 肩部滚降 + tier 无关探针 | **自研**（成熟） | — |
| 白平衡 | warmth 拟合曲线（5 结点实测标定）+ as_shot 回退链 | **自研** | — |
| 皮肤 | Lab 椭圆 + 引导滤波 + 分割掩码联动 | **自研** | 编辑域随阶段一迁移 |
| 风格 | .cube LUT + 胶片卡系统（19 张） | **自研** | 不动（输出端） |
| 解码 | rawpy（AHD 家族）+ native cfa_half 分箱 | 参照 dcraw | 阶段三可选 |
| **色彩变换** | DCP 矩阵链（ForwardMatrix/Bradford/1/T 插值/CameraCalibration） | **DNG 参照** | ★ 阶段一 |
| **HueSatMap** | HSV 三线性表（色彩科学最弱环节） | **DNG 参照** | ★ 阶段一 |
| **RGBTone/影调表** | 曲线采样方式 | **DNG 参照** | 阶段一（部分已自研：六键/tanh） |
| 工作空间 | ProPhoto(ROMM) | DNG 惯例 | 阶段一引入编辑空间分离 |

数学核心已经两轮数值复算验证正确（DCP 矩阵链/Bradford 级联/HSM 三线性/LUT 四面体，恒等表误差 1e-7 量级）——**替换的理由不是"错了"，是"想有自己的"**：摆脱 Adobe look 语义、消除 HSV 类操作的固有缺陷、让标定体系可端到端优化。

---

## 2. 目标架构

```
RAW 解码 ──► IDT（输入变换）──► 场景 referred 空间 ──► 创意变换层 ──► ODT（输出）──► 编码
              │                    │                    │                │
              │ DCP 解析保留        │ linear sRGB        │ Oklab/LCh      │ sRGB/16bit
              │ root-poly CCM      │ (主链不动)          │ 编辑域(阶段一)  │ LUT(不动)
              │ (阶段一并联)        │                    │ 掩码区域调整    │
              │                    │                    │ (M1 region_*)  │
              ▼                    ▼                    ▼                ▼
         [可微标定期：阶段二全链端到端优化，产出确定性表/曲线，运行时零变化]
```

关键设计决策：
- **主链空间不动**（linear sRGB/ProPhoto）：渲染主链、LUT、native 内核全部保持，避免全量重写。
- **编辑空间分离**：人向色彩操作（色相/饱和/分离色调/肤色）在 Oklab/LCh 域进行，进出主链做转换——这是 HSV 类缺陷的根治点，改动面最小。
- **DCP 双轨期**：IDT 先并联 root-poly CCM（同一语料拟合，ΔE 对照），数据说话后再切默认。

---

## 3. 阶段一：色彩操作层迁 Oklab/LCh + 根多项式 CCM（预计 2-3 周）

### 3.1 编辑空间：Oklab/OKLCh

**为什么是 Oklab**（Björn Ottosson 2020，图像处理界近年最大共识）：
- 感知均匀性碾压 HSV/HSV 变体——现管线的已知缺陷在 Oklab 天然消失：
  - hue 环绕接缝（huesat 深审确认的 0/255 边界处理）→ OKLCh 色相角连续；
  - 饱和度上限截断（S>1 提前压回，深审 S8 项）→ OKLCh 无此边界语义；
  - 高光区色相漂移（HSV 对亮度变化敏感）→ Oklab 明度/色度/色相正交。
- 转换是纯矩阵+三次多项式（无查表、可 native 化、逐位可验证）。

**模块迁移映射**：

| 现模块 | 现域 | 迁移后 | 要点 |
|---|---|---|---|
| hsl（8 带通） | gamma HSV | OKLCh 带通（按色相角分区） | 带/宽度语义重定义；UI 滑杆量纲随之（前端联动） |
| split_tone | gamma RGB 混合 | Oklab 色相轴两极着色 | 高光/阴影 tint 的感知线性化 |
| skin（椭圆+trim） | Lab(D65) | OKLCh 域重拟合椭圆 | **椭圆需用现有语料重拟合**（Lab→OKLab 不是平移）；colorcal 的 scene_skin_trim 同步 |
| huesat(DCP HSM) | HSV 三线性表 | 阶段一保留（DCP 双轨）；阶段二起用 OKLCh 连续形变替代 | HSM 表内容可转换为 OKLCh 控制点（离线转换脚本） |

**验收**：新色彩层金样本基线（走既有 generate+reviewer 流程）；语料 A/B（同一调整意图下 HSV 版 vs OKLCh 版的 ΔE 分布与人评）；Oklab 转换内核 native 逐位等价测试（对齐 colorcal F32 模式）。

### 3.2 色彩变换：根多项式 CCM 并联 DCP

- Finlayson & Xu 根多项式回归（root-polynomial color correction）：对曝光不敏感（纯 3×3 矩阵对曝光误差线性放大），精度普遍优于 3×3 一档。
- 实施线：用厦门+春节语料 + 标定靶（如无可控靶，用相机 JPEG 输出作参考的弱监督线）拟合 RP-CCM；`pixo.meta` 已有 EXIF/分组基础设施。
- **并联评估**：IDT 出口同时算 DCP 矩阵与 RP-CCM 两版，语料级 ΔE2000(median/p95) 对照——数据优于 DCP 且人评不劣，则 RP-CCM 转默认，DCP 降为 profile 内置回退。
- 现有矩阵链代码保留（作为 DCP 双轨），新增 `core/rp_ccm.py` + 拟合脚本。

### 3.3 影调：补齐自研曲线体系

- 现状已大半自研（六键/tanh 肩部/lrfit 通道）；补：filmic/ACES-RRT 风格渲染变换作为 tone stage 可选 `eotf` 模式（业界开源参考实现多，数学简单）。
- RGBTone 采样方式随 HSM 一并在阶段二退役。

---

## 4. 阶段二：可微标定（预计 2 周）

**现状**：warmth 曲线、曝光二维表、中性曲线各自散点独立拟合——参数间耦合（WB 影响 EV 决策、影响中性轴）无法联合优化。

**目标**：标定期把管线写成可微函数（离线工具，torch 或纯 numpy 自动微分；**torch 只进 scripts/ 标定脚本，运行时零依赖**——符合既有隔离纪律），语料端到端联合优化：

```
loss = Σ_corpora [ ΔE2000(render(raw, θ), reference) + λ·scene_constraints(θ) ]
θ = { warmth knots, exposure table nodes, neutral curves, RP-CCM 系数, skin ellipse }
```

**关键设计**：优化产出仍是**确定性查找表/曲线/系数**，运行时管线一个字节不变——可微只活在标定期，产品确定性完全保留。

**参考**：reference 来源三选一（按可得性）：相机 JPEG（弱监督）、专家修图终稿（loop 产物回灌）、色卡实拍（最准，需一次拍摄 session）。

**验收**：标定残差下降量化报告；全量金样本按新表重生成 + reviewer 流程；`ab_regression` 全语料分带统计不劣化。

---

## 5. 阶段三：可插拔学习后端（按需，治理框架先行）

组件候选：联合去马赛克降噪（仅全幅导出受益）、光照估计（illuminant estimation）。

**治理框架（复用 2026-08 已建立的模式）**：
- 权重许可白名单：MIT/Apache only，登记 `model_licenses.json`；
- import 隔离门禁：扩展 `test_heavy_imports_isolated_in_adapters` 模式；
- 开关：env opt-in（对齐 `PIXO_SEGMENTER`/`PIXO_GSAM_ENABLED` 惯例）；
- **默认关 + 三证据转正**：①语料 A/B 收益量化（ab_regression）②确定性方案（固定推理后端/线程，或退出金样本门只进质量抽样门的双轨）③域外降级语义（异常检测+回退传统路径且回退可见）。三证据齐 → 讨论转默认开。

**明确不做**：端到端 learned ISP 替换主管线（见 §9 决策记录）。

---

## 6. 与质量门禁体系的协同（每阶段操作手册）

| 阶段动作 | 金样本 | native 等价 | 语料 A/B |
|---|---|---|---|
| Oklab 编辑层上线 | 新基线（generate+reviewer 流程） | Oklab 转换内核严格等价 | 调整意图对照 |
| RP-CCM 切默认 | RAW gate 全量重生成 | RP-CCM 纯 Python 起步（性能允许则后置 native） | ΔE2000 对照报告 |
| 可微标定产出新表 | 全量重生成 | 不涉及（表驱动） | 残差+分带统计 |
| 学习后端转正 | 不进金样本（双轨） | 不涉及 | 强制 |

---

## 7. 前沿参考

- 深度 ISP 综述（ACM 2025）：https://dl.acm.org/doi/10.1145/3708516
- ISPFormer（小波 Transformer RAW→sRGB, 2025）：https://www.sciencedirect.com/science/article/abs/pii/S0925231225017564
- Dark-ISP（暗光 Bayer 直处理, 2025）：https://arxiv.org/html/2509.09183v1
- Learnable CCM（BMVC 2024）：https://bmva-archive.org.uk/bmvc/2024/papers/Paper_911/paper.pdf
- CCMNet（ICCV 2025）：https://iccv.thecvf.com/virtual/2025/poster/1865
- 可微 ISP 概念综述：https://www.emergentmind.com/topics/differentiable-image-signal-processor-isp
- Oklab 原文：https://bottosson.github.io/posts/oklab/
- Finlayson et al., Root-Polynomial Colour Correction（IEEE TIP 2015）
- CVPR 2025 AISP workshop（RAW 处理数据/赛题）：https://github.com/mv-lab/AISP

---

## 8. 里程碑

| 里程碑 | 内容 | 前置 |
|---|---|---|
| M-O1 | Oklab 转换内核（Python+native）+ hsl/split_tone 迁移 + 新基线 | 无（可立即开工） |
| M-O2 | skin/colorcal 编辑域重拟合 + huesat 双轨转换脚本 | M-O1 |
| M-O3 | RP-CCM 拟合脚本 + 并联评估报告 | 语料（已备） |
| M-D1 | 可微标定框架 + 联合优化首跑 | M-O3（RP-CCM 系数入 θ） |
| M-D2 | 标定产出上线（新表+基线+A/B） | M-D1 |
| M-L* | 学习后端按需逐个走转正流程 | §5 治理 |

---

## 9. 决策记录

1. **不走端到端 learned ISP**：与产品定位（可解释闭环、参数可控、金样本门禁）正面冲突；3400+ 张语料不足以训练；deep-ISP 系成果（ISPFormer 等）作为组件级参考而非架构参考。**确定性与可解释性是 Pixo 的差异化资产，不换。**
2. **主链空间不动，只动编辑空间与 IDT**：改动面/风险收益比最优；native 内核资产全部保留。
3. **DCP 永不删除**：作为 IDT 互操作格式与回退路径，双轨期由数据决定默认。
4. **可微只进标定期**：运行时确定性是红线。
5. NC 许可权重维持 `PIXO_ALLOW_RESTRICTED` 门控；开源发布口径变更时重审（当前项目方向：开源、发布合规后议）。
