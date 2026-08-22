# Pixo Architecture

本文件是架构入口页，指向项目完整架构设计正文：

- 完整架构设计：[`架构设计文档.md`](架构设计文档.md)
- 架构对齐评审：[`PIXO_ARCH_ALIGN_REVIEW.md`](PIXO_ARCH_ALIGN_REVIEW.md)
- 前端设计：[`PIXO_FRONTEND_DESIGN.md`](PIXO_FRONTEND_DESIGN.md)
- 许可复审：[`PIXO_LICENSE_REVIEW.md`](PIXO_LICENSE_REVIEW.md)

## 顶层结构

- `src/pixo/`：实际 Python 包（render、vision、meta、pipeline、decide、state、review、service、harness 等）。
- `src/render/`：`render` 兼容 shim，转发到 `pixo.*`。
- `configs/`：规则、风格、相机配置。
- `resources/`：DCP、相机 profile、模型清单引用。
- `data/`：RAW、golden、temp 数据目录。
- `tests/`：Phase D 后的单元/集成/回归测试。
- `docs/`：设计/评审/技术债文档。
