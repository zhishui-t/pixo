"""pytest 基建: 统一引导。

职责:
  - 确保 `import render.*` / `import pixo.*` 可用: 将 src 目录插入 sys.path。
  - 说明测试约定与共享工具。

运行约定:
    python -m pytest src/render/tests -q        # 全量
    python -m pytest src/render/tests/<file> -q # 单文件
"""
from __future__ import annotations

import sys
from pathlib import Path

# src/render/tests/conftest.py -> parents[2] = src (pixo/render 所在目录)
SRC_ROOT = Path(__file__).resolve().parents[2]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def pytest_configure(config):
    # 注册 e2e 标记 (test_e2e / test_preset_cli 用; 无真实 NEF 数据时跳过)
    config.addinivalue_line("markers",
                            "e2e: 需真实 NEF 数据的端到端测试 (无数据时 skip)")
    config.addinivalue_line("markers",
                            "regression: 金样本 DNG 回归 (数据存在时执行, 缺失时 skip)")
    config.addinivalue_line("markers",
                            "regression: 金样本 DNG 回归测试 (无数据时 skip)")
    config.addinivalue_line("markers",
                            "gate: pixo.render 功能门禁测试（失败阻塞合并）")
    config.addinivalue_line("markers",
                            "gate_e2e: 需真实 NEF 的门禁 A-B（RAW_PATH 缺省时 skip）")
