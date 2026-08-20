"""pytest 基建: 统一引导。

职责:
  - 确保 `import rawlab.*` 在任意入口/工作目录下可用: 将仓库根目录插入 sys.path。
  - 说明测试约定与共享工具。

运行约定:
    python -m pytest rawlab/tests -q        # 全量
    python -m pytest rawlab/tests/<file> -q # 单文件
"""
from __future__ import annotations

import sys
from pathlib import Path

# rawlab/tests/conftest.py -> parents[2] = 仓库根 (rawlab 包所在目录)
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def pytest_configure(config):
    # 注册 e2e 标记 (test_e2e / test_preset_cli 用; 无真实 NEF 数据时跳过)
    config.addinivalue_line("markers",
                            "e2e: 需真实 NEF 数据的端到端测试 (无数据时 skip)")
    config.addinivalue_line("markers",
                            "regression: 金样本 DNG 回归 (数据存在时执行, 缺失时 skip)")
    config.addinivalue_line("markers",
                            "regression: 金样本 DNG 回归测试 (无数据时 skip)")
