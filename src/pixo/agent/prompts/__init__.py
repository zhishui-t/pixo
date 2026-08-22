"""pixo.agent.prompts —— Agent 提示词与工具说明。

以模块常量形式暴露，方便 CLI / 服务 / DSH 工具直接引用。
"""
from __future__ import annotations

from pathlib import Path

__all__ = ["SYSTEM_PROMPT", "TOOL_PROMPT"]

_PROMPT_DIR = Path(__file__).resolve().parent


def _read(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8").strip()


SYSTEM_PROMPT = _read("system.md")
TOOL_PROMPT = _read("tools.md")
