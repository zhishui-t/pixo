# R31 · DNG 对齐线关闭记录

日期：2026-09-24 ｜ 裁决：用户「我们用 rawTherapee 了 那么没必要需要 dng 了吧」（两连确认）

## 关闭范围

1. **候选 c 仲裁 → 关闭为"不接"**：default_look 保持现状（R30 形态）；候选 c 曲线
   （median|ΔL| 4.453 vs 现状 13.44，holdout dL_med=0.10）留档 .artifacts/
   _r31_recipe_dng_target.json 与 git 历史，不接线。R31 §3 失败路径至此走完
   终态（零写入 + 用户裁决关线）。
2. **dng_validate 参照发生器退役**：R31 三臂测量收官（n=48：色度 PASS 0.23/0.51、
   亮度 median|ΔL| 13.44、Spearman 0.479），数据留档；发生器本体与批转产物在
   仓外（K:/work/project/dngsdk、.artifacts/_r31_refs，gitignored）随盘处置，不再维护。
3. **验证口径切换**：后续 Adobe 系色彩相关实施（如 T8 P0#1 LookTable 消费）的
   验收改用「LR 双锚点（white_balance.py 冻存 0376/5236）+ RT 参照臂（RT 施加
   LookTable 的渲染对照）」弱化口径；dng_validate 尺子不再使用。

## 不受影响项（同属 T8 台账）

- P0×3 实施轮本身照排（LookTable 消费 / guided-filter 局部恢复 / 预览线 flip bug）
  ——零件搬运与验收口径是两回事。
- R32 战役成果与 render-core-integration 分支不受影响。

## 留痕

- 用户裁决记录：本文件头部引文（2026-09-24 会话）。
- R31 全链证据：.agent-team/{task-brief-r31,design-r31,dev2-report}.md +
  commit a8f7890（三臂测量基线入库）。
