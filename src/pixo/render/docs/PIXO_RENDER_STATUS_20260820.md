# pixo.render 项目状态 (2026-08-20 收口)

## 已完成 (全部实测)
- Phase 0 底座: clean-room M1-M5, render 包迁移 (28+ 模块), render 公开面零 dng;
  5 张 input MAE ≤1e-5; ablation full engine_mae ≤8.1e-8; render_dcp 5607 mae≈3.97e-5。
- Phase 1 调整: 曝光六键(高光/阴影/Whites/Blacks 新增), 手动 WB temp/tint(物理正解),
  RGB+亮度用户曲线, HSL 八色段, 分离色调, 用户 RGB 校准; intents 全部接线。
- Phase 2/3 色彩与细节: saturation/vibrance, clarity/dehaze(原有), sharpen/denoise(refine 内嵌) 可用。
- Phase 4 P1: Renderer↔Pipeline 打通, batch-pipeline, Pipeline.to_config,
  refine 热点优化(逐位一致 +3.5%), 金样本 regression harness。
- Phase 4 P2: 快速预览 render_preview + preview_fast.json + CLI --preview。

## 关键验收数据
- pytest: 597 passed, 7 deselected (`-m 'not e2e'`)
- regression: 11 passed (5 张 input MAE + 5 张 full engine_mae + guard)
- ablation full: 5236=1.26e-8, 5607=8.10e-8, 5603=6.12e-8, 0364=2.87e-8, 0479=2.14e-8
- input MAE: 5236=4.41e-6, 5607=6.98e-6, 5603=7.76e-6, 0364=5.58e-6, 0479=5.16e-6

## 报告
- PIXO_RENDER_REFACTOR_FINAL_REVIEW.md (包迁移)
- CLEANROOM_M1..M5.md (clean-room)
- PIXO_RENDER_PHASE1_GAP.md / PIXO_RENDER_PHASE1_REVIEW.md
- PIXO_RENDER_PHASE4_GAP.md / PIXO_RENDER_PHASE4_REVIEW.md

## 原生迁移状态（已完成）
- render 全包源码 `grep -rIn "from render|import render" render` = 空；实现代码全部在 render。
- render 反向 shim，旧 import 全量可用；597 passed / 7 deselected；regression 11 passed；ablation full ≤8.1e-8。
- 提交：de1d20e → 27854ef → f1721c4 → b296776 → 2463947。

## 剩余可选方向
1. 性能: 真实 NEF 全分辨率 ~10.8s (目标 <5s); refine 热点, Numba 未安装;
   需用户决定: 安装 Numba / 允许 C++ / 允许轻微近似算法。
2. 真·原生迁移: render 目前是 render.engine 兼容 shim; 独立包需反向迁移实现代码。
3. 卫生收尾: 清理仓库根 _*.py 探针脚本; git 提交; 文档索引。
