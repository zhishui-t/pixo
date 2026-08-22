# tests

Pixo 测试根目录（Phase D）。

目录规划：
- `unit/`：纯单元测试，不依赖真实 RAW/服务/多模块闭环。
- `integration/`：服务、闭环、批量、多模块集成测试。
- `regression/`：gate 功能门禁、金样本回归、性能门禁。

运行：
```bash
# 全量（不含 e2e）
python -m pytest tests -q -m "not e2e"

# 单元 / 集成 / 回归
python -m pytest tests/unit -q
python -m pytest tests/integration -q
python -m pytest tests/regression -q -m "gate and not gate_e2e"
```

旧路径 `src/render/tests` 保留为兼容 shim，新代码请使用 `tests/`。
