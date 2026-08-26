"""pixo.vision.person —— FairFace 年龄/性别辅助接口。

迁移自 guanlan src/vision/fairface_age.py，做 Pixo 轻量适配：
  - 输入人脸 RGB 图，输出 (age_bucket, gender, confidence)；
  - onnxruntime 懒加载，模型/依赖缺失时返回 None/未就绪；
  - 不引入规则/数据管道业务。

模型许可说明：
  - fairface.onnx 来自 yakhyo/fairface-onnx，许可为 CC BY 4.0；
  - 年龄/性别仅用于辅助上下文与复核排序，不进入硬决策。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np

AGE_LABELS = [
    "0-2", "3-9", "10-19", "20-29", "30-39", "40-49", "50-59", "60-69", "70+",
]
GENDER_LABELS = ["Male", "Female"]
_AGE_BUCKET_MAP = {
    "0-2": "child",
    "3-9": "child",
    "10-19": "teen",
    "20-29": "adult",
    "30-39": "adult",
    "40-49": "adult",
    "50-59": "adult",
    "60-69": "elderly",
    "70+": "elderly",
}

_IMG_SIZE = 224
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def _default_model_path() -> str:
    """解析默认 FairFace 模型路径。"""
    env = os.environ.get("PIXO_FAIRFACE_MODEL")
    if env:
        return env
    return str(Path(__file__).resolve().parents[2] / "models" / "fairface.onnx")


def _has_ort() -> bool:
    """检查 onnxruntime 是否可用。"""
    try:
        import onnxruntime  # noqa: F401
    except Exception:
        return False
    return True


class FairFaceAge:
    """FairFace 年龄/性别预测轻量封装。

    懒加载：__init__ 只存配置，首次 predict_face 才加载 ONNX 会话；
    加载失败缓存结果（_load_failed）避免反复重试。
    """

    def __init__(self, model_path: str | None = None) -> None:
        self.model_path = model_path or _default_model_path()
        self.session: Any = None
        self.input_name: str | None = None
        self.output_names: list[str] = []
        self._error: str | None = None
        self._load_failed = False

    def _ensure_loaded(self) -> None:
        """首次预测时加载会话；失败缓存（_load_failed）不再重试。"""
        if self.session is not None or self._load_failed:
            return
        self._load()
        if self.session is None:
            self._load_failed = True

    def _load(self) -> None:
        """加载 ONNX 会话（模型/依赖缺失时置 _error，session 保持 None）。"""
        if not os.path.exists(self.model_path) or not _has_ort():
            self._error = "缺少 fairface.onnx 或 onnxruntime"
            return
        try:
            import onnxruntime as ort

            providers = ["CPUExecutionProvider"]
            try:
                available = set(ort.get_available_providers())
                if "CUDAExecutionProvider" in available:
                    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            except Exception:
                pass
            self.session = ort.InferenceSession(
                self.model_path, providers=providers
            )
            self.input_name = self.session.get_inputs()[0].name
            self.output_names = [o.name for o in self.session.get_outputs()]
        except Exception as exc:
            self._error = str(exc)
            self.session = None

    def __bool__(self) -> bool:
        return self.session is not None

    @property
    def ready(self) -> bool:
        """模型是否就绪。"""
        return self.session is not None

    def preprocess(self, face_rgb: np.ndarray) -> np.ndarray:
        """人脸 RGB → 224x224 归一化 NCHW blob。"""
        import cv2

        img = cv2.resize(face_rgb, (_IMG_SIZE, _IMG_SIZE))
        img = img.astype(np.float32) / 255.0
        img = (img - _MEAN) / _STD
        img = np.transpose(img, (2, 0, 1))
        return np.expand_dims(img, axis=0)

    def predict_face(
        self,
        face_rgb: np.ndarray,
    ) -> tuple[str, str, float] | None:
        """预测单张人脸。

        Returns:
            (age_bucket, gender, confidence) 或 None。
        """
        if face_rgb is None:
            return None
        if self.session is None:
            self._ensure_loaded()
            if self.session is None:
                return None
        try:
            if min(face_rgb.shape[:2]) < 16:
                return None
            blob = self.preprocess(face_rgb)
            outputs = self.session.run(self.output_names, {self.input_name: blob})
            # FairFace 输出顺序: race, gender, age
            age_logits = outputs[2][0]
            gender_logits = outputs[1][0]
            age_idx = int(np.argmax(age_logits))
            gender_idx = int(np.argmax(gender_logits))
            age_label = AGE_LABELS[age_idx]
            bucket = _AGE_BUCKET_MAP.get(age_label, "adult")
            gender = "male" if GENDER_LABELS[gender_idx] == "Male" else "female"
            exp = np.exp(age_logits - np.max(age_logits))
            confidence = float(np.max(exp) / exp.sum())
            return bucket, gender, confidence
        except Exception:
            return None

    def health_info(self) -> dict[str, Any]:
        """返回健康信息。"""
        return {
            "name": "FairFaceAge",
            "type": "real",
            "provider": "onnxruntime",
            "available": _has_ort() and os.path.exists(self.model_path),
            "ready": self.ready,
            "loaded": self.ready,
            "version": None,
            "model_path": self.model_path,
            "detail": (
                "FairFace 模型已就绪。"
                if self.ready
                else f"未就绪：{self._error or '缺少模型或依赖'}"
            ),
        }


_fairface: FairFaceAge | None = None


def _shared_fairface() -> FairFaceAge:
    """模块级单例（对齐 aesthetic.py 单例/缓存风格）。

    构造只存配置不触发加载；predict_face 才懒加载 ONNX 会话。
    """
    global _fairface
    if _fairface is None:
        _fairface = FairFaceAge()
    return _fairface


def get_fairface_age() -> FairFaceAge | None:
    """进程级 FairFace 单例；未就绪（未加载/加载失败）时返回 None。"""
    inst = _shared_fairface()
    return inst if inst.ready else None


def fairface_health_info() -> dict[str, Any]:
    """构造 FairFace 健康信息（复用模块级单例，不触发加载）。"""
    return _shared_fairface().health_info()


__all__ = [
    "FairFaceAge",
    "get_fairface_age",
    "fairface_health_info",
    "AGE_LABELS",
]
