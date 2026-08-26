"""t102 —— RF-DETR 导入与构造修复单测（monkeypatch，零真实权重下载）。

钉死：_load 走顶层 RFDETRSeg2XLarge（而非不存在的 rfdetr.RFDETRSeg）；
构造只传合法 ModelConfig 字段（pretrain_weights，无非法 pretrained kwarg）。
"""
from __future__ import annotations

import numpy as np
import pytest

from pixo.vision.segmenters.rfdetr_person import RFDetrPersonSegmenter


class _FakeRFDETR:
    """记录构造 kwargs 的假类（替代 RFDETRSeg2XLarge）。"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.predict_calls = []

    def predict(self, image, threshold=0.5, **kw):
        self.predict_calls.append((image, threshold))
        return _FakeDetections()


class _FakeDetections:
    mask = []
    xyxy = np.zeros((0, 4), dtype=np.float64)


def _install_fake(monkeypatch) -> list:
    """把 rfdetr.RFDETRSeg2XLarge 替换为工厂假件，返回已创建实例列表。"""
    import rfdetr

    created: list = []

    def factory(**kw):
        f = _FakeRFDETR(**kw)
        created.append(f)
        return f

    monkeypatch.setattr(rfdetr, "RFDETRSeg2XLarge", factory)
    # 若代码仍引用 rfdetr.RFDETRSeg → AttributeError（t102 缺陷原样）。
    monkeypatch.delattr(rfdetr, "RFDETRSeg", raising=False)
    return created


def test_load_uses_2xlarge_without_pretrained_kwarg(monkeypatch):
    """t102：_load 走 rfdetr 顶层 RFDETRSeg2XLarge 且无非法 pretrained kwarg。"""
    created = _install_fake(monkeypatch)

    seg = RFDetrPersonSegmenter()
    seg._ensure_loaded()

    assert len(created) == 1
    fake = created[0]
    assert seg._model is fake
    assert "pretrained" not in fake.kwargs, fake.kwargs
    assert fake.kwargs == {}


def test_load_model_uri_maps_to_pretrain_weights(monkeypatch):
    """t102：model_uri 映射到合法字段 pretrain_weights，而非非法 resolution=None。"""
    created = _install_fake(monkeypatch)

    seg = RFDetrPersonSegmenter(model_uri="K:/weights/rf-detr-seg-xxlarge.pt")
    seg._ensure_loaded()

    assert len(created) == 1
    fake = created[0]
    assert fake.kwargs == {"pretrain_weights": "K:/weights/rf-detr-seg-xxlarge.pt"}
    assert "resolution" not in fake.kwargs


def test_segment_with_fake_backend_returns_contract_mask(monkeypatch):
    """契约冒烟：假后端出零检出时按零掩码降级（形状保持、二值 0/255）。"""
    created = _install_fake(monkeypatch)

    seg = RFDetrPersonSegmenter()
    img = np.zeros((24, 32, 3), dtype=np.uint8)
    out = seg.segment(img, ["person"])
    assert "person" in out
    m = out["person"]
    assert m.shape == (24, 32)
    assert set(np.unique(m)) <= {0, 255}
