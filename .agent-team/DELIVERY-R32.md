# DELIVERY-R32 · RawTherapee 组件移植战役交付

日期：2026-09-24 ｜ 分支：render-core-integration @ fdd9d6f（8 提交）｜ 全量 1765 passed / 0 failed

## 交付物

| 类 | 内容 |
|---|---|
| 实现 ×7 提交 | T1 RCD native（2758a18）/ T2 DCP 对照（20fbbf2）/ T3 HaldCLUT（ee8e071）/ T4 曲线四模式（f5835ab）/ T5 Lab L* 直方图（1236d2b）/ T6 HSL/分色调（33abc4a）/ T7 match 曝光（bd40c37） |
| 台账 | T8 全模块清点 38 项裁决（r32-t8-ledger.md）——建议吸收 10 项（P0×3）带优先级/工作量/证据 |
| 报告 | R32_rt_component_campaign.md + changelog 第三十二轮 |
| 门禁 | .design_ok_r32_t1 / .qa_ok_r32_t1 / .qa_ok_r32_final（终检五项）；每步码检记录 design-review-r32.md §T1-T7 |

## 门禁摘要

- 默认链零漂移红线全程实证（七实现提交累计，golden+native 逐位等价+四步缺省回归锁）；
- 检视抓真错三起全回流修正（akima 双错 / T1 漏收测试文件 / T3 容差）；
- GPL 合规：rcd 原版权块+来源 commit 标注、NOTICES §8、胶片 CLUT 数据不入仓；
- 运维备注：WorkBuddy 引擎本任务族连续拒答，全程宿主兜底执行（各棒报告标注）。

## 待用户裁决（卡点④随批）

1. **R31 候选 c**（挂起）：DNG 对齐 default_look 中期改进（median 13.44→4.45）——接/不接；
2. **分支合并**：render-core-integration → master 时机（建议 P0×3 实施轮后合并，或现即合并）；
3. **后续轮排队**：P0×3 实施（LookTable 消费 / guided-filter 局部恢复 / 预览线 flip bug）→
   S1 分割进引擎 → S2 Compositor 图层。
