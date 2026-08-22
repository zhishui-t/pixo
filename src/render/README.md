# render 兼容 shim

本目录为 `pixo.render` 迁移期间的顶层兼容 shim。实际渲染引擎代码与详细文档位于：

- 包：`src/pixo/render/`
- README：`src/pixo/render/README.md`

现有 `import render.*` 通过本 shim 转发到 `pixo.render.*` / `pixo.vision.*` / `pixo.meta.*`。
