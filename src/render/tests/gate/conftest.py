"""gate 统一 fixtures（FUNCTION_GATE_SPEC §4）。"""
from __future__ import annotations

import numpy as np
import pytest


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """gate 内除 gate_e2e 外不允许 skip（FUNCTION_GATE_SPEC §9）。"""
    outcome = yield
    rep = outcome.get_result()
    if getattr(rep, "skipped", False) and "gate_e2e" not in item.keywords:
        rep.outcome = "failed"
        rep.longrepr = "gate 用例不允许 skip（仅 gate_e2e 缺 RAW_PATH 可豁免）"


@pytest.fixture()
def gray_ramp():
    """256×1 float32 线性 0→1 灰阶。"""
    return np.linspace(0.0, 1.0, 256, dtype=np.float32).reshape(256, 1)


@pytest.fixture()
def neutral_gray():
    """128×128，R=G=B 多档灰块。"""
    img = np.zeros((128, 128, 3), dtype=np.float32)
    for i, v in enumerate([0.0, 0.18, 0.5, 0.8, 1.0]):
        img[i * 25:(i + 1) * 25, :, :] = v
    return img


@pytest.fixture()
def color_steps():
    """8×8×3 六色阶 + 灰阶。"""
    colors = np.array([
        [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0],
        [0, 1, 1], [1, 0, 1], [0.5, 0.5, 0.5], [0, 0, 0],
    ], dtype=np.float32)
    return np.repeat(np.repeat(colors.reshape(8, 1, 3), 8, axis=1), 1, axis=0).reshape(8, 8, 3)


@pytest.fixture()
def skin_patch():
    """肤色 Lab 中心邻域 + 中性背景的 uint8 图。"""
    h, w = 64, 64
    img = np.full((h, w, 3), 128, dtype=np.uint8)
    # 粗略肤色 RGB
    img[16:48, 16:48] = (210, 155, 130)
    return img


@pytest.fixture()
def warm_highlight():
    img = np.full((64, 64, 3), 0.05, dtype=np.float32)
    img[28:36, 28:36] = (0.9, 0.3, 0.05)
    return img


@pytest.fixture()
def spot_on_dark():
    img = np.zeros((64, 64, 3), dtype=np.float32)
    img[30:34, 30:34] = 1.0
    return img


@pytest.fixture()
def random_small():
    return np.random.default_rng(20260820).random((64, 64, 3), dtype=np.float32)
