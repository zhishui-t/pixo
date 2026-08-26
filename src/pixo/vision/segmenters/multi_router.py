"""pixo.vision.segmenters.multi_router —— prompt 路由多模型 Segmenter。

契约不变：segment(image_rgb, prompts) -> dict[str, 0/255 uint8 mask]。
路由：face->uniface | person/subject->rfdetr |
sky/plant/mountain/tree/grass->segformer | hair/skin/clothes/body->sapiens |
其余->grounded_sam(可选，默认关闭)。
降级语义（exceptions.py 契约）：
  - 后端抛 SegmenterUnavailable 时：部分 prompt 组失败→该组零掩码 +
    每 backend 一次 warning + last_degraded 记录（健康可查）；
  - 请求的**全部** prompt 组后端均不可用→重新抛 SegmenterUnavailable，
    让 loop 升级 manual_review（禁止把模型错误当作"未检出"零掩码）。
  - 非可用性异常仍按 best-effort 零掩码降级（契约形状保持）。
合规门控：构造时读仓库根 model_licenses.json，usage=internal_development_only
的后端仅在 PIXO_ALLOW_RESTRICTED=1 时注册进路由表，否则跳过并告警
（JSON 解析失败不阻断：全注册+告警）。
测试可经 backends= 注入假件；不注入则按需实例化真实适配器。
（yoloe 后端不在此路由表：AGPL/重依赖，不在默认实例化集，见 yoloe.py。）
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np

from ..base import BaseSegmenter
from ..exceptions import SegmenterUnavailable
from .common import warmup_enabled, zeros_mask

_LOGGER = logging.getLogger(__name__)

# 完整（未门控）prompt 路由表；路由实例按合规门控裁剪副本。
ROUTE_TABLE: dict[str, str] = {
    "face": "uniface",
    "person": "rfdetr", "subject": "rfdetr",
    "sky": "segformer", "plant": "segformer",
    "mountain": "segformer", "tree": "segformer", "grass": "segformer",
    "hair": "sapiens", "skin": "sapiens",
    "clothes": "sapiens", "body": "sapiens",
}
# 未命中显式路由的开放词汇后端（默认关闭，PIXO_GSAM_ENABLED=1 开启）。
DEFAULT_ROUTE = "gsam"

# 路由后端名 -> model_licenses.json 条目名（合规门控依据）。
_LICENSE_BACKENDS: dict[str, str] = {
    "uniface": "uniface-face-parsing",
    "sapiens": "facebook/sapiens-seg-0.3b",
    # yoloe（YOLOE-26L-seg，internal_development_only）不在路由表，
    # 由 runtime PIXO_SEGMENTER=yoloe 显式选用，不经此门控。
}

_LICENSES_WARNED = False


def _licenses_path() -> Path:
    """model_licenses.json 路径：PIXO_MODEL_LICENSES 可覆写（测试），缺省仓库根。"""
    env = os.environ.get("PIXO_MODEL_LICENSES")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[4] / "model_licenses.json"


def restricted_backend_names(path: Path | None = None) -> set[str]:
    """解析 usage=internal_development_only 的路由后端名集合。

    JSON 缺失/解析失败不阻断：返回空集（全注册）并告警一次。
    """
    global _LICENSES_WARNED
    target = path if path is not None else _licenses_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        entries = data["models"]
        restricted = {
            backend
            for backend, model_name in _LICENSE_BACKENDS.items()
            for item in entries
            if item.get("name") == model_name
            and item.get("usage") == "internal_development_only"
        }
        return restricted
    except Exception as exc:  # noqa: BLE001 - 门控失败不阻断路由构造
        if not _LICENSES_WARNED:
            _LICENSES_WARNED = True
            _LOGGER.warning(
                "[pixo.vision.segmenters] model_licenses.json 读取失败"
                "(%s: %s)，合规门控跳过（全部后端注册）",
                type(exc).__name__, exc,
            )
        return set()


def route_of(prompt_lower: str) -> str:
    """canonical 路由（未门控全量表）；实例路由见 _route_of。"""
    return ROUTE_TABLE.get(prompt_lower, DEFAULT_ROUTE)


class MultiModelSegmenter(BaseSegmenter):
    """按 prompt 路由的多模型 Segmenter（t90）。"""

    def __init__(self, backends: dict | None = None) -> None:
        self.backends: dict = dict(backends or {})
        self._warned_backends: set = set()
        # 合规门控：internal_development_only 后端默认不注册，
        # PIXO_ALLOW_RESTRICTED=1 显式放行。
        self._restricted: set[str] = set()
        if os.environ.get("PIXO_ALLOW_RESTRICTED", "0") != "1":
            self._restricted = restricted_backend_names()
        self.route_table: dict[str, str] = {
            p: b for p, b in ROUTE_TABLE.items()
            if b not in self._restricted
        }
        for name in sorted(self._restricted):
            _LOGGER.warning(
                "[pixo.vision.segmenters] 后端 %s 许可为 "
                "internal_development_only，未注册进路由表；"
                "如需内部研发启用请设 PIXO_ALLOW_RESTRICTED=1", name)
        # 降级可见性（健康可查）：最近一次 segment 周期内不可用的后端名。
        self.last_degraded: list[str] = []
        self._backend_errors: dict[str, str] = {}

    # ---- 路由 ----

    def _route_of(self, prompt_lower: str) -> str:
        return self.route_table.get(prompt_lower, DEFAULT_ROUTE)

    def routed_backend_names(self) -> set[str]:
        """当前路由表可达的全量后端名（含默认路由 gsam）。"""
        return set(self.route_table.values()) | {DEFAULT_ROUTE}

    def _get(self, name: str):
        if name in self.backends:
            return self.backends[name]
        if name == "uniface":
            from .uniface_face import UniFaceSegmenter
            self.backends[name] = UniFaceSegmenter()
        elif name == "rfdetr":
            from .rfdetr_person import RFDetrPersonSegmenter
            self.backends[name] = RFDetrPersonSegmenter()
        elif name == "segformer":
            from .segformer_scenes import SegFormerSceneSegmenter
            self.backends[name] = SegFormerSceneSegmenter()
        elif name == "gsam":
            from .grounded_sam import GroundedSAMSegmenter
            self.backends[name] = GroundedSAMSegmenter()
        elif name == "sapiens":
            from .sapiens_body import SapiensBodySegmenter
            self.backends[name] = SapiensBodySegmenter()
        else:  # pragma: no cover
            raise KeyError(name)
        return self.backends[name]

    def _warn_once(self, key: str, msg: str) -> None:
        if key not in self._warned_backends:
            self._warned_backends.add(key)
            _LOGGER.warning("[pixo.vision.segmenters] %s", msg)

    def _record_degrade(self, backend_name: str, exc: Exception) -> None:
        """记录后端降级（last_degraded / 每 backend 一次 warning）。"""
        if backend_name not in self.last_degraded:
            self.last_degraded.append(backend_name)
        self._backend_errors[backend_name] = (
            f"{type(exc).__name__}: {exc}")

    def segment(self, image_rgb: np.ndarray, prompts: list[str]) -> dict:
        self.validate_image(image_rgb)
        # t91：prompt 键规范化小写——路由(_route_of)与输出掩码键统一契约，
        # 各后端收到的均为小写规范化键（如 HAIR->hair）。
        norm = [p.lower() for p in self.normalize_prompts(prompts)]
        h, w = image_rgb.shape[:2]

        groups: dict[str, list[str]] = {}
        for p in norm:
            groups.setdefault(self._route_of(p.lower()), []).append(p)

        out: dict = {}
        unavailable: dict[str, Exception] = {}
        for backend_name, plist in groups.items():
            try:
                backend = self._get(backend_name)
                out.update(backend.segment(image_rgb, plist))
            except SegmenterUnavailable as exc:
                unavailable[backend_name] = exc
                self._record_degrade(backend_name, exc)
                self._warn_once(
                    f"backend:{backend_name}",
                    f"后端 {backend_name} 不可用，{len(plist)} 个 prompt "
                    f"零掩码降级 ({type(exc).__name__}: {exc})")
                for p in plist:
                    out[p] = zeros_mask(h, w)
            except Exception as exc:  # noqa: BLE001 - 非可用性异常 best-effort 降级
                self._record_degrade(backend_name, exc)
                self._warn_once(
                    f"backend:{backend_name}",
                    f"后端 {backend_name} 推理异常，{len(plist)} 个 prompt "
                    f"零掩码降级 ({type(exc).__name__}: {exc})")
                for p in plist:
                    out[p] = zeros_mask(h, w)

        if unavailable and set(unavailable) == set(groups):
            # 请求的全部 prompt 组后端均不可用 -> 按 exceptions.py 契约
            # 上抛 SegmenterUnavailable（loop 捕获后升级 manual_review）。
            names = ", ".join(sorted(unavailable))
            raise SegmenterUnavailable(
                f"全部请求的 prompt 组后端不可用（{names}）："
                f"{unavailable[sorted(unavailable)[0]]}")

        for p in norm:
            if p not in out:
                self._warn_once(f"missing:{p}",
                                f"prompt {p!r} 无后端返回，零掩码降级")
                out[p] = zeros_mask(h, w)
        return out

    def detect_boxes(self, image_rgb: np.ndarray,
                     prompts: list[str]) -> dict[str, list[list[float]]]:
        """原生框直供（t92）：仅路由到具备检测头的后端（当前=rfdetr）。

        返回 {prompt: [[x0,y0,x1,y1] 归一化]}；无后端支持/失败的 prompt
        不出现在结果中——调用方据此回退 mask_bbox（best-effort 语义，
        失败仅每 backend 一次 warning，不抛）。
        """
        self.validate_image(image_rgb)
        norm = self.normalize_prompts(prompts)
        groups: dict[str, list[str]] = {}
        for p in norm:
            route = self._route_of(p.lower())
            if route == "rfdetr":
                groups.setdefault("rfdetr", []).append(p)
        out: dict = {}
        for name, plist in groups.items():
            try:
                backend = self._get(name)
                det = getattr(backend, "detect_boxes", None)
                if callable(det):
                    res = det(image_rgb, plist)
                    if isinstance(res, dict):
                        out.update(res)
            except Exception as exc:  # noqa: BLE001 - 原生框失败回退 mask_bbox
                self._warn_once(
                    f"detect:{name}",
                    f"后端 {name} detect_boxes 失败，回退 mask_bbox "
                    f"({type(exc).__name__}: {exc})")
                continue
        return out

    def warmup(self, image: np.ndarray | None = None) -> dict:
        """预热路由表**全量**后端（逐个实例化后 warmup）。

        各后端自身受 PIXO_SEGMENTER_WARMUP 门控与懒加载保护；
        显式 enabled()=False 的后端（如默认关闭的 gsam）跳过预热。
        yoloe 不在路由表（AGPL/重依赖，不在默认实例化集），不预热。
        """
        if not warmup_enabled():
            return {"skipped": True}
        report = {}
        for name in sorted(self.routed_backend_names()):
            try:
                b = self._get(name)
            except Exception as exc:  # noqa: BLE001 - 实例化失败记录后继续
                report[name] = {"warmed": False,
                                "error": f"{type(exc).__name__}: {exc}"}
                continue
            if hasattr(b, "enabled") and not b.enabled():
                report[name] = {"warmed": False, "skipped": True,
                                "reason": "disabled"}
                continue
            if hasattr(b, "warmup"):
                report[name] = b.warmup(image)
            else:
                report[name] = {"warmed": False, "reason": "no-warmup-api"}
        return report

    def health(self) -> dict:
        """路由表全量后端健康：未实例化报 available=None（unknown）。

        已实例化条目含 loaded/degraded/last_error 与各后端 warmup 信息；
        last_degraded 并入输出（最近 segment 周期的降级后端名列表）。
        """
        out: dict = {"last_degraded": list(self.last_degraded)}
        for name in sorted(self.routed_backend_names()):
            b = self.backends.get(name)
            if b is None:
                out[name] = {
                    "available": None,  # 未实例化：unknown，不假装可用
                    "loaded": False,
                    "degraded": None,
                    "last_error": None,
                }
                continue
            entry: dict = {
                "available": (bool(b.available())
                              if hasattr(b, "available") else True),
                "loaded": bool(getattr(b, "_loaded", False)),
                "degraded": bool(getattr(b, "_degraded", False)),
                "last_error": (getattr(b, "_error", None)
                               or self._backend_errors.get(name)),
            }
            if hasattr(b, "warmup_health"):
                entry.update(b.warmup_health())
            if entry["degraded"]:
                entry["available"] = False
            out[name] = entry
        return out
