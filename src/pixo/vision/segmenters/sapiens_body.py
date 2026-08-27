"""pixo.vision.segmenters.sapiens_body —— Sapiens 部位解析适配器（t91 + t99 守卫）。

Meta Sapiens 分割家族（facebook/sapiens-seg-*，Humans300K 28 类语义），
暴露 hair/skin/clothes/body 四个部位 prompt。许可 CC-BY-NC-4.0
（Sapiens2 License 口径）：开源项目可用，商用分发需替换或隔离——
已登记 model_licenses.json（internal_development_only，NC 特性
区别于 MIT/Apache 可分发后端）。第三方推理(torch/transformers)
只存在于本文件（t90 隔离纪律）。

hair 掩码同时为人像抠图预留通道（下游 matting 任务消费）。

t99 守卫：类别组索引常量必须与模型真实 id2label 一致，否则告警+拒用
该组（防静默污染磨皮/抠图）。索引常量按 sapiens-seg 28 类权威标签表
（Humans-300K，0=Background）设定，并在加载后经 config.id2label /
label2id / meta 标签表核验；body=全部非背景类并集，不依赖索引表，
鲁棒于类别表微调，恒可用。
"""
from __future__ import annotations

import logging
import os

import numpy as np

from ..base import BaseSegmenter
from ..exceptions import PromptNotSupportedError
from .common import LazyBackendMixin, to_binary_mask

_LOG = logging.getLogger(__name__)

DEFAULT_CKPT = os.environ.get(
    "PIXO_SAPIENS_MODEL", "facebook/sapiens-seg-0.3b"
)
SUPPORTED = ("hair", "skin", "clothes", "body")

# sapiens-seg 28 类权威标签表（Humans-300K，0=Background）。
# 来源：facebook/sapiens-seg-* 同族 transformers 版 id2label
# （onnx-community/sapiens-seg-0.3b/config.json）。
_CANON_LABELS: tuple[str, ...] = (
    "Background", "Apparel", "Face Neck", "Hair",
    "Left Foot", "Left Hand", "Left Lower Arm", "Left Lower Leg",
    "Left Shoe", "Left Sock", "Left Upper Arm", "Left Upper Leg",
    "Lower Clothing", "Right Foot", "Right Hand", "Right Lower Arm",
    "Right Lower Leg", "Right Shoe", "Right Sock", "Right Upper Arm",
    "Right Upper Leg", "Torso", "Upper Clothing", "Lower Lip",
    "Upper Lip", "Lower Teeth", "Upper Teeth", "Tongue",
)

# 各部位组的类索引（0=背景），与 _CANON_LABELS 一一对应：
#   hair=(3,) 对应 "Hair"
#   skin=裸肤部位(面/颈/躯干/四肢/手足/唇)
#   clothes=衣物与配件(上衣/下装/鞋/袜等)
# body 组不在此表——恒为非零全并集（见 _part_masks）。
_PART_CLASS_GROUPS: dict[str, tuple[int, ...]] = {
    "hair": (3,),
    "skin": (2, 4, 5, 6, 7, 10, 11, 13, 14, 15, 16, 19, 20, 21, 23, 24),
    "clothes": (1, 8, 9, 12, 17, 18, 22),
}

# 部位标签关键词分类器（t99 守卫按标签语义分类，对拼写变体鲁棒）。
_GROUP_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hair": ("hair",),
    "skin": ("face", "neck", "torso", "arm", "leg", "foot",
             "hand", "lip", "skin"),
    "clothes": (
        "apparel", "cloth", "shirt", "coat", "pant", "jeans", "dress",
        "skirt", "sock", "shoe", "hat", "scarf", "glove", "belt", "bag",
        "sunglass", "glasses", "jewel",
    ),
}


def _part_group_of(label: str) -> str | None:
    """单条标签 → 部位组（hair/skin/clothes）或 None（背景/非人体部位）。"""
    lab = (label or "").strip().lower()
    if not lab or lab == "background":
        return None
    for group in ("hair", "skin", "clothes"):
        for kw in _GROUP_KEYWORDS[group]:
            if kw in lab:
                return group
    return None


def _groups_from_labels(id2label: dict[int, str]) -> dict[str, tuple[int, ...]]:
    """按标签语义把 id2label 映射为各部位组索引表。"""
    out: dict[str, list[int]] = {}
    for idx, label in id2label.items():
        group = _part_group_of(str(label))
        if group:
            out.setdefault(group, []).append(int(idx))
    return {k: tuple(sorted(v)) for k, v in out.items()}


def _extract_id2label(config) -> dict[int, str] | None:
    """从 model config（含 meta 键）提取 id→label 映射；无法解析返回 None。

    支持 config.id2label / config.label2id（反推）/ config.meta 下的
    id2label/labels/label_names 键。
    """
    if config is None:
        return None
    id2l: dict = {}
    for attr in ("id2label", "id2LABEL"):
        val = getattr(config, attr, None)
        if isinstance(val, dict) and val:
            id2l = val
            break
    else:
        l2i = getattr(config, "label2id", None)
        if isinstance(l2i, dict) and l2i:
            id2l = {v: k for k, v in l2i.items()}
        else:
            meta = getattr(config, "meta", None)
            if isinstance(meta, dict):
                for key in ("id2label", "labels", "label_names"):
                    val = meta.get(key)
                    if isinstance(val, dict) and val:
                        id2l = val
                        break
    if not isinstance(id2l, dict) or not id2l:
        return None
    out: dict[int, str] = {}
    for k, v in id2l.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            # label2id 方向：值即索引
            try:
                out[int(v)] = str(k).strip()
            except (TypeError, ValueError):
                pass
            continue
        try:
            out[int(k)] = str(v).strip()
        except (TypeError, ValueError):
            continue
    return out if out else None



def _part_masks(seg: np.ndarray, keys: tuple[str, ...]) -> dict[str, np.ndarray]:
    """纯函数：28 类 argmap -> 各部位 0/255 原始掩码（可单测，不依赖 torch）。"""
    person = (seg != 0).astype(np.uint8) * 255
    out: dict[str, np.ndarray] = {}
    for k in keys:
        if k == "body":
            out[k] = person
        else:
            out[k] = np.isin(seg, _PART_CLASS_GROUPS[k]).astype(np.uint8) * 255
    return out


class SapiensBodySegmenter(LazyBackendMixin, BaseSegmenter):
    """Sapiens 部位分割适配器：prompt 路由表中的 sapiens 后端。"""

    PROMPT_KEYS = SUPPORTED

    # 轻量探测：仅检查依赖可 import（不触发 from_pretrained）。
    _PROBE_IMPORTS = ("torch", "transformers")

    def __init__(self, ckpt: str | None = None) -> None:
        self.ckpt = ckpt or DEFAULT_CKPT
        self._proc = None
        self._model = None
        # t99 守卫状态
        self._disabled: set[str] = set()
        self._groups_verified: bool = False
        self._id2label: dict[int, str] | None = None
        self._verify_report: dict[str, bool] = {}

    def _load(self) -> None:
        import torch  # noqa: F401  本文件内允许（隔离纪律）
        from transformers import (AutoImageProcessor,
                                  AutoModelForSemanticSegmentation)

        self._proc = AutoImageProcessor.from_pretrained(self.ckpt)
        self._model = AutoModelForSemanticSegmentation.from_pretrained(self.ckpt)
        self._model.eval()

    def _warn(self, msg: str) -> None:
        _LOG.warning("[pixo.vision.segmenters] %s", msg)

    def _ensure_loaded(self) -> bool:
        ok = super()._ensure_loaded()
        if ok and not self._groups_verified:
            self._groups_verified = True
            try:
                self._verify_part_groups()
            except Exception as exc:  # noqa: BLE001 - 核验异常不阻断加载
                self._warn(f"id2label 核验异常，hair/skin/clothes 拒用: "
                           f"{type(exc).__name__}: {exc}")
                self._disabled |= set(SUPPORTED) - {"body"}
        return ok

    def _verify_part_groups(self) -> None:
        """加载后按模型 id2label 校验 _PART_CLASS_GROUPS 常量；不一致告警+拒用。"""
        self._id2label = _extract_id2label(
            getattr(self._model, "config", None))
        if not self._id2label:
            self._warn("Sapiens id2label 不可用（config/meta 无标签表），"
                       "hair/skin/clothes 索引未核验——拒用该三组，body 保留")
            self._disabled |= set(SUPPORTED) - {"body"}
            return
        model_groups = _groups_from_labels(self._id2label)
        for group in ("hair", "skin", "clothes"):
            expected = set(_PART_CLASS_GROUPS.get(group, ()))
            actual = set(model_groups.get(group, ()))
            if expected == actual:
                self._verify_report[group] = True
                continue
            miss = sorted(expected - actual)
            extra = sorted(actual - expected)
            self._verify_report[group] = False
            self._disabled.add(group)
            self._warn(
                f"Sapiens {group} 索引与模型 id2label 不一致"
                f"（配置缺 {miss}、含多余 {extra}），拒用该组")
        # body 无索引常量（非零并集），恒可用
        self._verify_report["body"] = True

    def _supported(self, prompts: list[str]) -> list[str]:
        norm = self.normalize_prompts(prompts)
        kept = [p for p in norm if p.lower() in SUPPORTED]
        dropped = [p for p in norm if p.lower() not in SUPPORTED]
        if dropped and not kept:
            raise PromptNotSupportedError(
                f"Sapiens 仅支持 {SUPPORTED}，收到 {dropped}"
            )
        return kept

    def segment(self, image_rgb: np.ndarray, prompts: list[str]) -> dict:
        self.validate_image(image_rgb)
        norm = self.normalize_prompts(prompts)
        supported = [p for p in norm if p.lower() in SUPPORTED]
        unsupported = [p for p in norm if p.lower() not in SUPPORTED]
        if unsupported and not supported:
            raise PromptNotSupportedError(
                f"Sapiens 仅支持 {SUPPORTED}，收到 {unsupported}"
            )
        # 加载并触发 id2label 核验；核验可能禁用部分组（body 恒可用）。
        self._ensure_loaded()
        kept = [p for p in supported if p.lower() not in self._disabled]
        if not kept:
            return {}
        h, w = image_rgb.shape[:2]

        import torch

        inputs = self._proc(images=image_rgb[..., :3], return_tensors="pt")
        with torch.no_grad():
            logits = self._model(**inputs).logits
        up = torch.nn.functional.interpolate(
            logits, size=(h, w), mode="bilinear", align_corners=False)
        seg = up.argmax(dim=1)[0].cpu().numpy()
        raw = _part_masks(seg, tuple(k.lower() for k in kept))
        return {k: to_binary_mask(m, h, w) for k, m in raw.items()}
