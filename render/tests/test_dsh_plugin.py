"""P2-1 单元测试：DSH pixo.* 工具插件。

插件本体为 ESM（pixo/dsh/pixo-tools.mjs），这里通过 Node 内置测试运行
mock pixo-service 调用用例，并在 Python 侧做最小静态契约校验。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN = REPO_ROOT / "pixo" / "dsh" / "pixo-tools.mjs"
NODE_TEST = REPO_ROOT / "pixo" / "dsh" / "test-pixo-tools.mjs"

REQUIRED_TOOLS = [
    "pixo.vision.health",
    "pixo.vision.segment",
    "pixo.vision.measure",
    "pixo.meta.extract",
    "pixo.render.preview",
    "pixo.render.final",
    "pixo.decide.decide",
    "pixo.state.get",
    "pixo.state.history",
    "pixo.review.submit",
    "pixo.trace.query",
]


def test_plugin_file_and_required_tools_present():
    """插件文件存在且包含全部要求的工具名。"""
    assert PLUGIN.exists(), f"缺少插件文件: {PLUGIN}"
    source = PLUGIN.read_text(encoding="utf-8")
    for name in REQUIRED_TOOLS:
        assert name in source, f"插件中缺少工具定义: {name}"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js 不可用")
def test_node_mock_service_tests_pass():
    """运行 Node mock service 单测，验证工具 schema/参数/返回映射。"""
    result = subprocess.run(
        ["node", "--test", str(NODE_TEST)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"DSH 插件 Node 测试失败:\n{result.stdout}\n{result.stderr}"
