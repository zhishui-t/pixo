# Pixo 自研渲染管线 · 阶段三详细设计（M-L 学习后端治理 + 光照估计首组件）

> 状态：详细设计 v1（2026-09-04，队长架构师）。
> 上游：路线图 §5（治理框架先行 + 组件按需）、阶段二终审 GO（新表已上线）。
> 纪律红线：**不做端到端 learned ISP**（路线图决策记录 1）；学习组件默认关 + 三证据转正；torch/权重只进 scripts/ 与 vision 栈隔离层。

---

## 0. 目标

1. **治理框架固化**：把 2026-08 已建立的四个治理模式（许可白名单 / import 隔离 / env opt-in / 三证据转正）模板化为可复用门禁，供后续学习组件统一走。
2. **光照估计首组件**（illuminant estimation）：弱监督语料上验证"学习型光源色温估计"能否比现行 DCP+as_shot 链更准——只产评估报告，不接运行时。

## 1. 治理框架四门禁（固化既有模式）

| 门禁 | 既有资产 | 固化动作 |
|---|---|---|
| **许可白名单** | `manifests/vision_models.json`（license 字段 + `test_model_licenses.py` schema 测试） | 补一条白名单常量（MIT/Apache only）进测试：非白名单 license 硬拒 |
| **import 隔离** | `test_heavy_imports_isolated_in_adapters` 模式（torch 只进 vision/segmenter 各自隔离层） | 补一条 src 全仓扫描测试模板：`learned/` 新目录纳入隔离面 |
| **env opt-in** | `PIXO_SEGMENTER` / `PIXO_GSAM_ENABLED` / `PIXO_ALLOW_RESTRICTED` 惯例 | 统一约定文档（哪个前缀、缺省值语义、测试如何覆盖关态） |
| **三证据转正** | 阶段一 §5 治理文字（①A/B 收益量化 ②确定性方案 ③域外降级） | 写成 checklist 模板：`docs/LEARNED_BACKEND_PROMOTION.md` |

## 2. 光照估计首组件（评估原型）

- **问题**：现行 WB 链 = DCP as_shot neutral → warmth 曲线微调。as_shot 是相机出厂记录，非拍摄时实况——低色温人造光下 as_shot 可能偏离实际光源。
- **假设**：语料驱动的光源色温估计（如灰世界/灰边缘/神经网络均可，首版用经典统计法即可）→ 若 ΔE2000 对照显示估计 CCT 比 as_shot 更接近相机 JPEG 实况，学习组件有价值；否则如实报告无收益。
- **实施**：`scripts/illumination_est/`——三件经典法（Gray-World / Gray-Edge / PCA-based）纯 numpy 实现 + 语料评估：估计 CCT vs as_shot CCT，以相机 JPEG 为参照算 WB 后渲染 ΔE2000（复用 eval_rp_ccm_ab 口径）。**不接运行时**。
- **验收**：语料级 ΔE 对照报告 + 三证据转正初评（若收益 <1 JND 则明确"无转正价值"）。

## 3. 红线

- 学习组件目录 `src/pixo/render/learned/`（若未来接运行时）须 import 隔离 + env opt-in + 默认关——本阶段只建 scripts 原型，不建该目录。
- 权重不入仓（manifest 登记）。
- 全量回归绿 + src 渲染零 diff（本阶段除治理测试模板外不碰 src）。

## 4. 任务拆解

```
t42 治理框架固化 (developer-2) ─┬→ t44 QA 终审+转正初评 (qa)
t43 光照估计原型+评估 (developer-3) ─┘
```
