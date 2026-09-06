"""vision 模块缺陷修复批单测（假件驱动，零真实权重下载）。

覆盖：
  - multi_router 降级语义：全败抛 SegmenterUnavailable / 部分降级零掩码 +
    last_degraded 可查 / 非可用性异常保持 best-effort 零掩码；
  - 健康可见性：health() 遍历路由表全量后端（未实例化 available=None）、
    vision_health() multi_router 聚合条目、available() 轻量探测不触发加载；
  - warmup 遍历路由表全量后端（假件断言被实例化）+ 显式禁用后端跳过；
  - 合规门控：model_licenses.json usage 过滤（假 JSON + env monkeypatch）；
  - 开放词汇后端已移除（防复活见 test_grounded_sam_removed）：
    未知 prompt 零掩码 + warn-once（语义见 test_multimodel_segmenter.py）。
"""
from __future__ import annotations

import importlib
import json
import logging

import numpy as np
import pytest

import pixo.vision.segmenters
from pixo.vision.exceptions import SegmenterUnavailable
from pixo.vision.segmenters.multi_router import (
    MultiModelSegmenter,
    restricted_backend_names,
)

IMG = np.zeros((8, 12, 3), dtype=np.uint8)


def _fake_backend(ok=True):
    class _Fake:
        def segment(self, image_rgb, prompts):
            if not ok:
                raise SegmenterUnavailable("simulated-down")
            return {p: np.full(image_rgb.shape[:2], 255, np.uint8)
                    for p in prompts}
    return _Fake()


# ---------- 1. multi_router 降级语义 ----------

def test_all_groups_unavailable_raises():
    """请求的全部 prompt 组后端均 SegmenterUnavailable → 重新抛（契约）。"""
    router = MultiModelSegmenter(backends={
        "rfdetr": _fake_backend(ok=False),
        "segformer": _fake_backend(ok=False),
    })
    with pytest.raises(SegmenterUnavailable):
        router.segment(IMG, ["person", "sky"])
    assert set(router.last_degraded) == {"rfdetr", "segformer"}


def test_partial_degrade_zero_mask_and_last_degraded():
    """部分组失败：失败组零掩码、成功组正常，last_degraded 记录失败组。"""
    router = MultiModelSegmenter(backends={
        "rfdetr": _fake_backend(ok=False),
        "segformer": _fake_backend(ok=True),
    })
    out = router.segment(IMG, ["person", "sky"])
    assert not out["person"].any()
    assert out["sky"].all()
    assert router.last_degraded == ["rfdetr"]
    # 健康可查：_backend_errors 带 Backend 级错误详情
    assert "rfdetr" in router._backend_errors


def test_non_availability_exception_stays_best_effort():
    """非 SegmenterUnavailable 异常（即便单组）不上抛：best-effort 零掩码。"""
    class _Bug:
        def segment(self, image_rgb, prompts):
            raise ValueError("backend bug")
    router = MultiModelSegmenter(backends={"segformer": _Bug()})
    out = router.segment(IMG, ["sky"])
    assert not out["sky"].any()          # 契约形状保持，不抛 ValueError
    assert router.last_degraded == ["segformer"]


def test_router_detect_boxes_warns_once(caplog):
    """路由器 detect_boxes 后端失败：best-effort {} + 每 backend 一次 warning。"""
    class _Down:
        def segment(self, image_rgb, prompts):
            return {}
        def detect_boxes(self, image_rgb, prompts):
            raise RuntimeError("detect-down")
    router = MultiModelSegmenter(backends={"rfdetr": _Down()})
    with caplog.at_level(logging.WARNING):
        assert router.detect_boxes(IMG, ["person"]) == {}
        assert router.detect_boxes(IMG, ["person"]) == {}
    assert caplog.text.count("detect_boxes 失败") == 1


def test_rfdetr_detect_boxes_warns_once(caplog, monkeypatch):
    """rfdetr 适配器 detect_boxes 静默 {} 补 warning（语义保留）。"""
    from pixo.vision.segmenters.rfdetr_person import RFDetrPersonSegmenter

    seg = RFDetrPersonSegmenter()

    def _boom():
        raise RuntimeError("simulated-down")

    monkeypatch.setattr(seg, "_ensure_loaded", _boom)
    with caplog.at_level(logging.WARNING):
        assert seg.detect_boxes(IMG, ["person"]) == {}
        assert seg.detect_boxes(IMG, ["person"]) == {}
    assert caplog.text.count("detect_boxes 失败") == 1


# ---------- 3. 健康可见性 ----------

def test_health_reports_uninstantiated_as_unknown(monkeypatch):
    """health() 遍历路由表全量后端名；未实例化 available=None（unknown）。"""
    monkeypatch.setenv("PIXO_ALLOW_RESTRICTED", "1")
    router = MultiModelSegmenter()  # 不注入任何后端：全部未实例化
    health = router.health()
    names = set(router.routed_backend_names())
    assert names <= set(health)
    for name in names:
        assert health[name]["available"] is None, name
        assert health[name]["loaded"] is False
    assert health["last_degraded"] == []


def test_health_reports_degraded_and_last_error(monkeypatch):
    """已实例化后端的 degraded/last_error 进 health；last_degraded 可查。"""
    monkeypatch.setenv("PIXO_ALLOW_RESTRICTED", "1")
    down = _fake_backend(ok=False)
    router = MultiModelSegmenter(backends={"uniface": down})
    with pytest.raises(SegmenterUnavailable):
        router.segment(IMG, ["face"])
    health = router.health()
    entry = health["uniface"]
    assert health["last_degraded"] == ["uniface"]
    assert entry["last_error"] and "simulated-down" in entry["last_error"]
    # 混合实例化状态：rfdetr 未实例化 → unknown
    assert health["rfdetr"]["available"] is None


def test_vision_health_includes_multi_router_aggregate():
    """vision_health() 补 multi_router 聚合条目（各后端 loaded/degraded/last_error）。"""
    from pixo.vision.health import vision_health

    health = vision_health()
    aggregate = health["models"]["multi_router"]
    assert aggregate["name"] == "MultiModelSegmenter"
    backends = aggregate["backends"]
    assert backends, "聚合条目应含各路由后端"
    for entry in backends.values():
        for key in ("available", "loaded", "degraded", "last_error"):
            assert key in entry
    assert aggregate["last_degraded"] == []


def test_available_probe_is_light_and_import_based(monkeypatch):
    """LazyBackendMixin.available() 仅 import 探测 + 已加载标记，不触发 _load。"""
    from pixo.vision.segmenters.uniface_face import UniFaceSegmenter

    ad = UniFaceSegmenter()

    def _boom():
        raise AssertionError("available/_probe 禁止触发 _load 完整加载")

    monkeypatch.setattr(ad, "_load", _boom)
    # 依赖缺失路径（伪造不可 import 的模块名）→ False；全程不触发 _load
    monkeypatch.setattr(
        type(ad), "_PROBE_IMPORTS", ("definitely_missing_module_xyz",))
    assert ad.available() is False
    # 空探测集合=无重依赖声明 → True（仅已加载标记检查）
    monkeypatch.setattr(type(ad), "_PROBE_IMPORTS", ())
    assert ad.available() is True
    # 已加载标记短路：不再探测
    ad._loaded = True
    monkeypatch.setattr(
        type(ad), "_PROBE_IMPORTS", ("definitely_missing_module_xyz",))
    assert ad.available() is True
    ad._loaded = False
    # 永久降级 → False
    ad._degraded = True
    assert ad.available() is False


def test_available_false_when_declared_deps_missing(monkeypatch):
    """声明 _PROBE_IMPORTS 的依赖 import 失败 → available False（轻量路径）。"""
    from pixo.vision.segmenters import uniface_face

    monkeypatch.setattr(
        uniface_face.UniFaceSegmenter, "_PROBE_IMPORTS",
        ("definitely_missing_module_xyz",))
    assert uniface_face.UniFaceSegmenter().available() is False


# ---------- 4. warmup 遍历 ----------

def test_warmup_instantiates_all_routed_backends(monkeypatch):
    """warmup 遍历路由表全量后端并逐个实例化（假后端断言被实例化+预热）。"""
    monkeypatch.setenv("PIXO_ALLOW_RESTRICTED", "1")
    monkeypatch.setenv("PIXO_SEGMENTER_WARMUP", "1")
    router = MultiModelSegmenter()
    names = router.routed_backend_names()
    instantiated: list[str] = []
    reports: dict[str, dict] = {}

    class _Stub:
        def __init__(self, name):
            self.name = name

        def segment(self, image_rgb, prompts):
            return {}

        def warmup(self, image=None):
            reports[self.name] = {"warmed": True}
            return {"warmed": True}

    def _fake_get(name):
        if name not in router.backends:
            instantiated.append(name)
            router.backends[name] = _Stub(name)
        return router.backends[name]

    router._get = _fake_get
    report = router.warmup(IMG)
    assert set(instantiated) == names  # warmup 逐个实例化全部路由后端
    for name in names:
        assert report[name] == {"warmed": True}, name


def test_warmup_skips_disabled_backend(monkeypatch):
    """显式 enabled()=False 的后端被 warmup 跳过（不触发重权重加载）。"""
    router = MultiModelSegmenter()

    class _Stub:
        def __init__(self, name):
            self.name = name

        def segment(self, image_rgb, prompts):
            return {}

        def warmup(self, image=None):
            return {"warmed": True}

    class _Disabled(_Stub):
        def enabled(self):
            return False

    names = router.routed_backend_names()
    for name in names:
        router.backends[name] = _Stub(name)
    router.backends["segformer"] = _Disabled("segformer")
    report = router.warmup(IMG)
    assert report["segformer"].get("skipped") is True
    assert report["segformer"].get("warmed") is not True


# ---------- 2/9. 开放词汇后端移除防复活 + 合规门控 ----------

def test_grounded_sam_removed():
    """gsam 已移除（防复活）：适配器不再可导入/不可按需属性访问。"""
    assert not hasattr(pixo.vision.segmenters, "GroundedSAMSegmenter")
    with pytest.raises(ImportError):
        importlib.import_module("pixo.vision.segmenters.grounded_sam")


def _write_fake_licenses(tmp_path, uniface_usage, sapiens_usage="redistribution_allowed_with_license_notice"):
    data = {
        "schema_version": "1.0",
        "models": [
            {"name": "uniface-face-parsing", "provider": "x",
             "license": "x", "files": [], "usage": uniface_usage,
             "status": uniface_usage},
            {"name": "facebook/sapiens-seg-0.3b", "provider": "x",
             "license": "x", "files": [], "usage": sapiens_usage,
             "status": sapiens_usage},
        ],
    }
    path = tmp_path / "model_licenses.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return str(path)


def test_gate_restricted_backends_by_default(tmp_path, monkeypatch, caplog):
    """internal_development_only 后端默认不注册进路由 + warning。"""
    monkeypatch.delenv("PIXO_ALLOW_RESTRICTED", raising=False)
    monkeypatch.setenv("PIXO_MODEL_LICENSES",
                       _write_fake_licenses(
                           tmp_path, "internal_development_only",
                           sapiens_usage="internal_development_only"))
    with caplog.at_level(logging.WARNING):
        router = MultiModelSegmenter()
    names = router.routed_backend_names()
    assert "uniface" not in names and "sapiens" not in names
    assert "rfdetr" in names and "segformer" in names
    assert router._route_of("face") is None      # 被门控条目跳过→无路由
    assert any("internal_development_only" in m for m in caplog.messages)


def test_gate_allows_restricted_with_env(tmp_path, monkeypatch):
    """PIXO_ALLOW_RESTRICTED=1 时受限后端照常注册。"""
    monkeypatch.setenv("PIXO_ALLOW_RESTRICTED", "1")
    monkeypatch.setenv("PIXO_MODEL_LICENSES",
                       _write_fake_licenses(tmp_path, "internal_development_only"))
    router = MultiModelSegmenter()
    assert "uniface" in router.routed_backend_names()
    assert router._route_of("face") == "uniface"


def test_gate_real_registry_restricts_uniface_and_sapiens(monkeypatch):
    """真实 model_licenses.json：uniface/sapiens 默认受限，rfdetr 等不受限。"""
    monkeypatch.delenv("PIXO_ALLOW_RESTRICTED", raising=False)
    monkeypatch.delenv("PIXO_MODEL_LICENSES", raising=False)
    router = MultiModelSegmenter()
    assert "uniface" not in router.routed_backend_names()
    assert "sapiens" not in router.routed_backend_names()
    assert {"rfdetr", "segformer"} <= router.routed_backend_names()
    assert "gsam" not in router.routed_backend_names()  # 已移除（防复活）


def test_gate_invalid_json_registers_all_with_warning(
        tmp_path, monkeypatch, caplog):
    """JSON 解析失败不阻断：全注册 + warning（一次）。"""
    import pixo.vision.segmenters.multi_router as router_mod

    monkeypatch.delenv("PIXO_ALLOW_RESTRICTED", raising=False)
    monkeypatch.setattr(router_mod, "_LICENSES_WARNED", False)
    bad = tmp_path / "model_licenses.json"
    bad.write_text("{not-json", encoding="utf-8")
    monkeypatch.setenv("PIXO_MODEL_LICENSES", str(bad))
    with caplog.at_level(logging.WARNING):
        router = MultiModelSegmenter()
        MultiModelSegmenter()  # 第二次不再重复告警
    assert "uniface" in router.routed_backend_names()  # 全注册
    assert "sapiens" in router.routed_backend_names()
    assert caplog.text.count("model_licenses.json 读取失败") == 1
    # restricted_backend_names 直接校验
    assert restricted_backend_names(bad) == set()


# ---------- 6. 注册补漏 ----------

def test_sapiens_registered_in_package():
    """segmenters/__init__ 按需导入补 SapiensBodySegmenter。"""
    from pixo.vision.segmenters import SapiensBodySegmenter  # noqa: F401
    from pixo.vision.segmenters import sapiens_body

    assert SapiensBodySegmenter is sapiens_body.SapiensBodySegmenter
