"""t67 —— 评分器常驻预热单测（假件驱动，不加载真模型）。

覆盖：开关关闭跳过、启用路径 warmed/耗时入 health、加载失败不推理、
重复 warmup 复用已加载状态（_load 仅一次）、宽松冷启阈值断言。
"""
from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pixo.vision.aesthetic import PixoAestheticScorer, _warmup_enabled


def _scorer() -> PixoAestheticScorer:
    return PixoAestheticScorer(model_path="definitely-missing.pt")


def test_env_switch_disabled(monkeypatch):
    """④PIXO_SCORER_WARMUP=0 → 跳过且不触模型加载。"""
    monkeypatch.setenv("PIXO_SCORER_WARMUP", "0")
    assert _warmup_enabled() is False

    s = _scorer()
    calls = {"ensure": 0}

    def _spy_ensure():
        calls["ensure"] += 1
        return True

    s._ensure = _spy_ensure  # type: ignore[assignment]
    info = s.warmup()

    assert info["skipped"] is True and info["warmed"] is False
    assert calls["ensure"] == 0
    health = s.health_info()
    assert health["warmed"] is False and health["warmup_ms"] is None


def test_enabled_by_default_and_warmed(monkeypatch):
    """默认启用：_ensure+dummy 推理后 warmed=True，耗时入 health_info。"""
    monkeypatch.delenv("PIXO_SCORER_WARMUP", raising=False)
    assert _warmup_enabled() is True

    s = _scorer()
    seen = {}
    s._ensure = lambda: True  # type: ignore[assignment]

    def _fake_score(img):
        seen["img_shape"] = np.asarray(img).shape
        return {"overall": -0.4}

    s.score = _fake_score  # type: ignore[assignment]
    info = s.warmup()

    assert info["warmed"] is True and info["skipped"] is False
    assert isinstance(info["warmup_ms"], float) and info["warmup_ms"] >= 0.0
    assert seen["img_shape"][2] == 3
    health = s.health_info()
    assert health["warmed"] is True
    assert health["warmup_ms"] == pytest.approx(info["warmup_ms"])


def test_load_failure_skips_inference(monkeypatch):
    """权重缺失/加载失败 → 不做推理，warmed=False，不抛错。"""
    monkeypatch.setenv("PIXO_SCORER_WARMUP", "1")
    s = _scorer()
    score_calls = {"n": 0}

    s._ensure = lambda: False  # type: ignore[assignment]

    def _no_score(img):
        score_calls["n"] += 1
        return None

    s.score = _no_score  # type: ignore[assignment]
    info = s.warmup()

    assert info["warmed"] is False and info["loaded_model"] is False
    assert score_calls["n"] == 0


def test_repeated_warmup_reuses_loaded_state():
    """两次 warmup 只触发一次底层 _load（常驻复用）；宽松阈值 <15.8s 冷启。"""
    class _CountingScorer(PixoAestheticScorer):
        load_calls = 0

        def _load(self):  # 模拟真实加载成本
            type(self).load_calls += 1
            self._ready = True

        def score(self, image_rgb):
            if not self._ready:
                self._ensure()
            return {"overall": -0.4}

    s = _CountingScorer(model_path="stub.pt")
    first = s.warmup()
    second = s.warmup()

    assert _CountingScorer.load_calls == 1
    assert first["warmed"] and second["warmed"]
    # 宽松断言：预热后耗时远小于 t58 记录的冷启 ~15.8s
    assert first["warmup_ms"] < 15800
    assert second["warmup_ms"] <= first["warmup_ms"] + 100


def test_service_app_registers_startup_hook(monkeypatch):
    """②service 启动序列接入：create_app 经 lifespan 在启动期调用预热。"""
    from pixo.service import app as app_mod

    calls: list[dict] = []
    monkeypatch.setattr(
        app_mod,
        "warm_aesthetic_scorer",
        lambda: calls.append({"warmed": True}) or {"warmed": True},
    )

    app = app_mod.create_app()
    # on_event("startup") 已迁移为 lifespan：不再注册独立 startup 钩子。
    assert app.router.on_startup == []
    with TestClient(app):
        assert len(calls) == 1  # lifespan 启动段恰好调用一次预热
