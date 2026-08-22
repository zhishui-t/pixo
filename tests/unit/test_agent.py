"""Phase C 单元测试：pixo.agent 基础行为。

覆盖：
  - import pixo.agent / pixo.agent
  - orchestrator 兼容 re-export
  - tools 注册与调用
  - burst_selection 基本选帧
  - prompts 可加载
"""
from __future__ import annotations

import pixo.agent as agent
from pixo.agent import (
    BatchPipeline,
    BurstFrame,
    SinglePhotoLoop,
    ToolRegistry,
    call_tool,
    create_default_registry,
    run_single_photo_loop,
    select_burst_frames,
)
from pixo.agent.prompts import SYSTEM_PROMPT, TOOL_PROMPT


def test_import_pixo_agent():
    """模块可导入且具备核心符号。"""
    assert agent.PixoOrchestrator is not None
    assert callable(agent.run_photo)
    assert callable(agent.run_batch)
    assert callable(agent.select_burst_frames)


def test_render_agent_alias():
    """render shim 应可将 pixo.agent 转发到 pixo.agent。"""
    import pixo.agent as render_agent
    assert render_agent.call_tool == agent.call_tool


def test_orchestrator_re_exports_existing_pipeline():
    """orchestrator 应保持 pixo.pipeline 兼容符号。"""
    assert SinglePhotoLoop is not None
    assert BatchPipeline is not None
    assert callable(run_single_photo_loop)


def test_tools_default_registry():
    """默认工具注册表应包含 service / dsh / burst / orchestrator。"""
    registry = create_default_registry()
    names = {spec.name for spec in registry.list()}
    assert "service.health" in names
    assert "service.photos" in names
    assert "dsh.chat" in names
    assert "burst.select_frames" in names
    assert "orchestrator.run_photo" in names


def test_call_tool_dsh_placeholder():
    """call_tool 可调用 DSH 占位工具。"""
    result = call_tool("dsh.chat", text="测试消息")
    assert result["ok"] is True
    assert "测试消息" in result["text"]


def test_tool_registry_custom():
    """自定义工具可注册/列出/调用。"""
    registry = ToolRegistry()
    registry.register("echo", lambda value: value, description="echo")
    assert registry.call("echo", value=42) == 42
    assert registry.list()[0].name == "echo"


def test_burst_selection_top_n():
    """无图像输入时按美学分选 TopN。"""
    frames = [
        BurstFrame("a", aesthetic=4.8),
        BurstFrame("b", aesthetic=4.5),
        BurstFrame("c", aesthetic=4.2),
        BurstFrame("d", aesthetic=3.9),
    ]
    results = select_burst_frames(frames, top_n=2)
    recommended = [r.photo_id for r in results if r.status == "recommended"]
    assert recommended == ["a", "b"]
    assert {r.photo_id for r in results if r.status == "hard_rejected"} == set()


def test_burst_selection_hard_reject():
    """显式 hard_filter_passed=False 应淘汰。"""
    frames = [
        BurstFrame("bad", aesthetic=5.0, hard_filter_passed=False),
        BurstFrame("good", aesthetic=4.0, hard_filter_passed=True),
    ]
    results = select_burst_frames(frames, top_n=1)
    by_id = {r.photo_id: r for r in results}
    assert by_id["bad"].status == "hard_rejected"
    assert by_id["good"].status == "recommended"


def test_prompts_loaded():
    """提示词文件应可读取且非空。"""
    assert "Pixo Agent" in SYSTEM_PROMPT
    assert "orchestrator.run_photo" in TOOL_PROMPT
