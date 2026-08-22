"""tests 根 pytest 基建（Phase D）。

职责:
  - 确保 `import pixo.render.*` / `import pixo.*` 可用：将 src 目录插入 sys.path。
  - 注册 e2e / regression / gate / gate_e2e markers。

运行约定:
    python -m pytest tests -q -m "not e2e"
    python -m pytest tests/unit -q
    python -m pytest tests/integration -q
    python -m pytest tests/regression -q -m "gate and not gate_e2e"
"""
from __future__ import annotations

import sys
from pathlib import Path

# tests/conftest.py -> 仓库根
ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


def pytest_configure(config):
    """注册测试 markers。"""
    config.addinivalue_line("markers",
                            "e2e: 需真实 NEF 数据的端到端测试 (无数据时 skip)")
    config.addinivalue_line("markers",
                            "regression: 金样本/回归测试（数据存在时执行，缺失时 skip）")
    config.addinivalue_line("markers",
                            "gate: pixo.render 功能门禁测试（失败阻塞合并）")
    config.addinivalue_line("markers",
                            "gate_e2e: 需真实 NEF 的门禁 A-B（RAW_PATH 缺省时 skip）")
