"""t45 —— dsh.chat 真实客户端（可降级）单测。

三分支：成功 / 超时二次失败降级 / 未配置降级；断言降级路径 source 标记。
"""
from __future__ import annotations

import json

import pytest

from pixo.agent import tools as tools_mod
from pixo.agent.tools import call_tool

ENV_KEYS = ("PIXO_DSH_CHAT_URL", "PIXO_DSH_CHAT_KEY", "PIXO_DSH_CHAT_MODEL")


class _FakeResp:
    """urlopen 返回的上下文管理器假响应。"""

    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("PIXO_DSH_CHAT_URL", "http://fake.local/v1")
    monkeypatch.setenv("PIXO_DSH_CHAT_KEY", "sk-test")
    monkeypatch.setenv("PIXO_DSH_CHAT_MODEL", "dummy-model")


def test_real_success(monkeypatch, configured):
    """配置齐全 + 响应正常 → 真实应答，source=pixo.agent.tools.dsh_chat_real。"""
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["auth"] = request.get_header("Authorization")
        return _FakeResp(
            {"choices": [{"message": {"content": "real-reply"}}]}
        )

    monkeypatch.setattr(tools_mod.urllib.request, "urlopen", fake_urlopen)
    result = call_tool("dsh.chat", text="hi")

    assert result["ok"] is True
    assert result["text"] == "real-reply"
    assert result["source"] == "pixo.agent.tools.dsh_chat_real"
    assert result["retries_used"] == 0
    assert seen["url"] == "http://fake.local/v1/chat/completions"
    assert seen["timeout"] == tools_mod._DSH_CHAT_TIMEOUT_S == 10.0
    assert seen["auth"] == "Bearer sk-test"


def test_retry_once_then_success(monkeypatch, configured):
    """第一次失败 → 自动重试 1 次成功（retries_used=1）。"""
    attempts = {"n": 0}

    def flaky_urlopen(request, timeout=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("first-try-timeout")
        return _FakeResp({"choices": [{"message": {"content": "second"}}]})

    monkeypatch.setattr(tools_mod.urllib.request, "urlopen", flaky_urlopen)
    result = call_tool("dsh.chat", text="hi")

    assert attempts["n"] == 2
    assert result["source"] == "pixo.agent.tools.dsh_chat_real"
    assert result["text"] == "second"
    assert result["retries_used"] == 1


def test_double_failure_degrades_to_placeholder(monkeypatch, configured, caplog):
    """两次失败 → 占位应答带 error 字段与 source=placeholder，不抛错。"""
    attempts = {"n": 0}

    def always_fail(request, timeout=None):
        attempts["n"] += 1
        raise TimeoutError("endpoint-down")

    monkeypatch.setattr(tools_mod.urllib.request, "urlopen", always_fail)
    result = call_tool("dsh.chat", text="hello")

    assert attempts["n"] == tools_mod._DSH_CHAT_MAX_ATTEMPTS == 2
    assert result["ok"] is True
    assert result["role"] == "agent_placeholder"
    assert result["source"] == "placeholder"
    assert "error" in result and "TimeoutError" in result["error"]
    assert "已收到 DSH 消息: hello" in result["text"]
    warns = [r for r in caplog.records
             if r.levelname == "WARNING" and "请求失败" in r.getMessage()]
    assert len(warns) == 2


def test_unconfigured_falls_back_without_http(monkeypatch):
    """任一环境变量缺失 → 直接占位(source=placeholder)，零网络调用。"""
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)

    calls = {"n": 0}

    def spy_urlopen(request, timeout=None):
        calls["n"] += 1
        raise AssertionError("未配置时不应发起网络请求")

    monkeypatch.setattr(tools_mod.urllib.request, "urlopen", spy_urlopen)
    result = call_tool("dsh.chat", text="offline")

    assert calls["n"] == 0
    assert result["source"] == "placeholder"
    assert result["ok"] is True
    assert "offline" in result["text"]
