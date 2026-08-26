"""P2-1 单元测试：DSH pixo.* 工具插件。

插件本体为 ESM（pixo/dsh/pixo-tools.mjs），这里通过 Node 内置测试运行
mock pixo-service 调用用例，并在 Python 侧做最小静态契约校验。
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2] / "src"
PLUGIN = REPO_ROOT / "pixo" / "dsh" / "pixo-tools.mjs"
NODE_TEST = REPO_ROOT / "pixo" / "dsh" / "test-pixo-tools.mjs"

REQUIRED_TOOLS = [
    "pixo.vision.health",
    "pixo.decide.decide",
    "pixo.state.get",
    "pixo.state.history",
]

# 已删除的死端点工具（服务路由不存在）与重复工具（trace.query 与
# state.history 打同一 URL），防止回归。
REMOVED_TOOLS = [
    "pixo.vision.segment",
    "pixo.vision.measure",
    "pixo.meta.extract",
    "pixo.render.preview",
    "pixo.render.final",
    "pixo.review.submit",
    "pixo.trace.query",
]


def test_plugin_file_and_required_tools_present():
    """插件文件存在且只包含真实路由对应的工具名。"""
    assert PLUGIN.exists(), f"缺少插件文件: {PLUGIN}"
    source = PLUGIN.read_text(encoding="utf-8")
    for name in REQUIRED_TOOLS:
        assert name in source, f"插件中缺少工具定义: {name}"
    for name in REMOVED_TOOLS:
        assert name not in source, f"插件中仍存在已删除的工具定义: {name}"


def test_plugin_default_base_url_matches_service_port():
    """默认 baseUrl 与 service/__main__.py 的 uvicorn 端口 8000 一致。"""
    source = PLUGIN.read_text(encoding="utf-8")
    assert "http://127.0.0.1:8000" in source, "默认 baseUrl 应为 http://127.0.0.1:8000"
    assert "9777" not in source, "旧的 9777 端口应全部清理"


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
