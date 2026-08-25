# Changelog

## 2026-08-23 — 修图质量 P0 修复与项目整理

- 修复：tone `brightness` 回归标定值 0.25（原 0.5 与标定注释矛盾）；
  exposure 新增低光保护参数（low_key_knee/keep/range）。
- 新增：场景自适应曝光标定表 `src/pixo/render/target_offset.json`（12 结点，
  以 RAW 内嵌相机缩略图为真值拟合）+ 拟合工具 `scripts/fit_target_offset.py`。
- 实测：室内 ΔE 38.8→9.2 / 33.6→9.8，夜景 46.5→16.5；全量测试 673 passed。
- 测试：loop_e2e 亮场夹具改为显式超亮，解除对引擎默认亮度的依赖。
- 整理：清理根目录残留日志；`.agent-teams/` 纳入 .gitignore；
  一次性实验脚本归档至 `scripts/experiments/`；重写 `scripts/README.md`。

## 2026-08-22 — Phase A/E 目录与资源整理

- `doc/` 改名 `docs/`，并更新全仓引用。
- 新增 `configs/`、`resources/`、`data/`、`tests/`、`scripts/` 骨架与 README。
- 静态资源迁移：
  - DCP → `resources/dcp/`
  - 相机标定 → `resources/camera_profiles/`
  - 风格/预设 → `configs/styles/`
  - 金样本 → `data/golden/`
- 补齐 Phase E 文件：渲染/视觉/批量诊断脚本、规则 YAML、Harness 包装模块、文档入口。

## 之前重要里程碑

- P1-1：`pixo.render` 命名空间迁移 + `render` shim。
- P1-5：单张闭环（compose → segment → preview×3 → FINAL_QC）。
- P1-6/7：pixo-service 与性能门禁。
- P2-2/3/4：批量/连拍、Web UI v1、复核与报告。
- P2-8：许可复审与发布阻断清单。
