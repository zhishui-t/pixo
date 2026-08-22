# Changelog

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
