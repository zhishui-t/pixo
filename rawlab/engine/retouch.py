"""engine.retouch —— RetouchAgent 调度器 (阶段3, T3)。

职责 (软件设计 §2 / 规格 §1):
  - 把「分析 → 场景预设 → 意见编辑 → 全链渲染 → 视觉报告 → 落盘」编排成
    可多轮反馈的会话调度器, 并支持位精确回放 (确定性, ADR-13/14/16)。
  - 首轮 retouch() 做一次 probe 渲染 + 主体检测 + 场景分类;
    反馈轮 apply_feedback() 复用首轮 ctx.state 的框与 scene (不重检),
    仅每 3 轮 (round_idx % 3 == 0 且 > 0) 强制重分析一次。
  - 会话状态自持 (dict), 可导出 JSON / 落盘 / 重放。

设计约束:
  - 不修改引擎 Stage 数学; 不引入新第三方依赖。
  - probe 渲染 (旧链路 render half_size) 与最终渲染 (build_default_pipeline)
    各自独立成方法 (_render_probe / _render_final), 便于测试 monkeypatch 成
    合成小图, 避免真实 NEF 依赖; 也可经构造参数 probe_fn / engine_fn 注入。
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import cv2
import numpy as np

from rawlab.vision_report import build_vision_report

from .analyze import run_analysis
from .core import StageContext
from .intents import EditIntent, apply_intents, parse_feedback
from .scene_apply import apply_scene_preset

# 默认输出基目录: rawlab/out/retouch/<stem>/ (包目录内)
_RAWLAB_DIR = Path(__file__).resolve().parent.parent

# 强制重分析周期 (反馈轮每 3 轮重跑一次 detect+classify)
_REANALYZE_EVERY = 3


def _jsonable(obj):
    """递归把 numpy 标量 / 元组转成 JSON 原生类型 (会话 JSON 序列化用)。"""
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


@dataclass
class RetouchResult:
    """单轮修图结果。

    image_path   : 落盘 JPEG 路径。
    report       : build_vision_report 输出 dict。
    params       : 本轮最终引擎参数 (场景预设 + 累计意见合并后)。
    scene        : 生效场景 id (None = 基座默认)。
    subject_boxes: 归一化 [l, t, r, b] 主体框 (本会话 ctx.state 最新值)。
    round_idx    : 轮次 (首轮 0, 每次反馈 +1)。
    ev           : 曝光 EV (exposure.mode), 无则 None。
    """
    image_path: Union[str, Path]
    report: Dict[str, Any]
    params: Dict[str, Any]
    scene: Optional[str]
    subject_boxes: List[List[float]]
    round_idx: int
    ev: Optional[float]


class RetouchAgent:
    """修图会话调度器: 分析 → 场景 → 意见 → 渲染 → 报告 → 落盘, 支持反馈与回放。"""

    def __init__(self, prof, out_dir: Optional[Union[str, Path]] = None,
                 detect: bool = True,
                 probe_fn=None, engine_fn=None):
        self.prof = prof
        self.out_dir = out_dir          # None → retouch() 时按 <stem> 计算默认目录
        self.detect = detect
        self._probe_fn = probe_fn        # 可选注入: (raw_path, prof) -> RGB uint8
        self._engine_fn = engine_fn      # 可选注入: (raw_path, prof, params) -> RGB uint8

        # 会话状态 (自持 dict; retouch() 时初始化)
        self._ctx: Optional[StageContext] = None
        self._raw_path: Optional[Path] = None
        self._stem: str = ""
        self._out_dir: Optional[Path] = None
        self._round_idx: int = 0
        self._scene: Optional[str] = None
        self._base_params: Dict[str, Any] = {}
        self._intents: List[EditIntent] = []
        self._initial_intents: List[Dict[str, Any]] = []
        self._params: Dict[str, Any] = {}
        self._feedback: List[str] = []
        self._rounds: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ 分析/渲染 (可注入, 独立方法)

    def _render_probe(self, raw_path: Path) -> np.ndarray:
        """probe 渲染 (旧链路, half_size) → 8bit RGB, 供检测/分类。"""
        if self._probe_fn is not None:
            return self._probe_fn(raw_path, self.prof)
        from rawlab.render import render
        return render(raw_path, self.prof, half_size=True)

    def _render_final(self, params: Dict[str, Any]) -> np.ndarray:
        """全链渲染 (build_default_pipeline) → 8bit RGB。"""
        if self._engine_fn is not None:
            return self._engine_fn(self._raw_path, self.prof, params)
        from rawlab.engine import build_default_pipeline
        pipe = build_default_pipeline(self.prof, params=params)
        return pipe.run_file(self._raw_path, half_size=True)

    def _analyze(self, probe: np.ndarray) -> None:
        """首轮 / 强制重分析: detect + classify 写回 ctx.state。"""
        run_analysis(self._ctx, rgb8=probe, detect=self.detect, classify=True)

    # ------------------------------------------------------------------ 场景/参数

    @staticmethod
    def _resolve_scene(scene: Optional[str], ctx: StageContext) -> Optional[str]:
        """解析生效场景: "auto" → 分析出的 scene id (无则 None); 其余原样。"""
        if scene == "auto":
            sid = (ctx.state.get("scene") or {}).get("id")
            return sid if sid else None
        return scene

    @staticmethod
    def _scene_params(scene: Optional[str]) -> Dict[str, Any]:
        """场景 id → 引擎参数覆盖 (与 apply_scene_preset 合并; 无场景 → 空)。"""
        params: Dict[str, Any] = {}
        if scene:
            sp, lut = apply_scene_preset(scene)
            for st, kv in sp.items():
                params.setdefault(st, {}).update(dict(kv))
            if lut:
                params.setdefault("stylize", {})["lut_path"] = lut
        return params

    # ------------------------------------------------------------------ 会话生命周期

    def _init_session(self, raw_path, out_dir) -> None:
        self._raw_path = Path(raw_path)
        self._stem = self._raw_path.stem
        self._out_dir = (Path(out_dir) if out_dir is not None
                         else _RAWLAB_DIR / "out" / "retouch" / self._stem)
        self._ctx = StageContext(self._raw_path, prof=self.prof)
        self._round_idx = 0
        self._scene = None
        self._base_params = {}
        self._intents = []
        self._initial_intents = []
        self._params = {}
        self._feedback = []
        self._rounds = []

    def _write_output(self, rgb8: np.ndarray) -> Path:
        """RGB → JPEG 落盘 <out_dir>/<stem>_r<round>.jpg, 返回路径。"""
        out = self._out_dir
        out.mkdir(parents=True, exist_ok=True)
        bgr = cv2.cvtColor(rgb8, cv2.COLOR_RGB2BGR)
        path = out / f"{self._stem}_r{self._round_idx}.jpg"
        cv2.imwrite(str(path), bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
        return path

    def _render_round(self, feedback: Optional[str]) -> RetouchResult:
        """渲染当前参数 → 报告 → 落盘 → 记录轮次 → 返回结果。

        报告的主体检测复用会话 ctx.state 的框 (不重复 YOLOE, ADR-15)。
        """
        rgb8 = self._render_final(self._params)
        bgr8 = cv2.cvtColor(rgb8, cv2.COLOR_RGB2BGR)
        report = build_vision_report(
            bgr8,
            subject_boxes=self._ctx.state.get("subject_boxes"),
            face_boxes=self._ctx.state.get("face_boxes"))
        image_path = self._write_output(rgb8)

        ev = self._params.get("exposure", {}).get("mode")
        boxes = [list(b) for b in self._ctx.state.get("subject_boxes", [])]
        result = RetouchResult(
            image_path=image_path,
            report=report,
            params=copy.deepcopy(self._params),
            scene=self._scene,
            subject_boxes=boxes,
            round_idx=self._round_idx,
            ev=float(ev) if ev is not None else None,
        )
        self._rounds.append({
            "round_idx": self._round_idx,
            "params": _jsonable(self._params),
            "scene": self._scene,
            "image_path": str(image_path),
            "ev": result.ev,
            "feedback": feedback,
        })
        return result

    # ------------------------------------------------------------------ 主入口

    def retouch(self, raw_path, intents: Optional[List[EditIntent]] = None,
                scene: str = "auto") -> RetouchResult:
        """首轮修图 (round 0)。

        流程: probe 渲染 → 分析 (detect+classify) → 解析场景 → 场景预设参数
        → 合并意见 → 全链渲染 → 视觉报告 → 落盘。
        """
        self._init_session(raw_path, self.out_dir)
        intents = list(intents or [])
        self._initial_intents = [_jsonable(asdict(it)) for it in intents]

        probe = self._render_probe(self._raw_path)
        self._analyze(probe)

        self._scene = self._resolve_scene(scene, self._ctx)
        self._base_params = self._scene_params(self._scene)
        self._intents = intents
        self._params = apply_intents(self._base_params, self._intents)

        return self._render_round(feedback=None)

    def apply_feedback(self, text: str) -> RetouchResult:
        """意见反馈轮: 解析意见 → 会话累计合并 → 重渲染 (round_idx +1)。

        分析复用: detect/classify 仅首轮做一次; 反馈轮复用 ctx.state 的框与
        scene; 每 3 轮 (round_idx % 3 == 0 且 > 0) 强制重分析。
        """
        if self._ctx is None:
            raise RuntimeError("尚未 retouch, 无法应用反馈")

        new_intents = parse_feedback(text)
        self._intents.extend(new_intents)
        self._feedback.append(text)
        self._round_idx += 1

        if self._round_idx % _REANALYZE_EVERY == 0 and self._round_idx > 0:
            probe = self._render_probe(self._raw_path)
            self._analyze(probe)
        # 其余轮: 复用 ctx.state 的框与 scene (不重检/重分类)

        self._params = apply_intents(self._base_params, self._intents)
        return self._render_round(feedback=text)

    # ------------------------------------------------------------------ 会话导出 / 回放

    def to_session_json(self) -> Dict[str, Any]:
        """会话状态 → JSON 友好 dict (编辑序列 / 每轮参数 / scene / 产物路径)。"""
        if self._ctx is None:
            raise RuntimeError("尚未 retouch, 无会话可导出")
        return {
            "raw_path": str(self._raw_path),
            "stem": self._stem,
            "out_dir": str(self._out_dir),
            "scene": self._scene,
            "initial_intents": _jsonable(self._initial_intents),
            "intents": _jsonable([asdict(it) for it in self._intents]),
            "feedback": list(self._feedback),
            "final_params": _jsonable(self._params),
            "rounds": _jsonable(self._rounds),
            "final_image": (self._rounds[-1]["image_path"]
                            if self._rounds else None),
        }

    def save_session(self, path) -> Path:
        """导出会话 JSON 并落盘, 返回写入路径。"""
        data = self.to_session_json()
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")
        return p

    @staticmethod
    def _load_session(session_json_or_path) -> Dict[str, Any]:
        if isinstance(session_json_or_path, dict):
            return session_json_or_path
        p = Path(session_json_or_path)
        return json.loads(p.read_text(encoding="utf-8"))

    @classmethod
    def replay(cls, session_json_or_path, prof,
               out_dir: Optional[Union[str, Path]] = None) -> RetouchResult:
        """回放编辑序列, 位精确同图 (断言确定性)。

        重建会话 → 首轮 retouch (复用已解析 scene + 初始意见) → 逐条重放
        feedback → 用最终参数重渲染两次并断言位精确一致, 且参数与记录一致。
        """
        data = cls._load_session(session_json_or_path)
        agent = cls(prof, out_dir=out_dir)

        initial = [EditIntent(**d) for d in data.get("initial_intents", [])]
        result = agent.retouch(data["raw_path"], intents=initial,
                               scene=data["scene"])
        for fb in data.get("feedback", []):
            result = agent.apply_feedback(fb)

        # 确定性断言: 最终参数重渲染两次必须位精确一致
        img_a = agent._render_final(agent._params)
        img_b = agent._render_final(agent._params)
        if not np.array_equal(np.asarray(img_a), np.asarray(img_b)):
            raise AssertionError("replay 重渲染非确定 (两次渲染位不同)")

        # 参数必须与记录一致 (无漂移)
        if _jsonable(agent._params) != _jsonable(data.get("final_params")):
            raise AssertionError("replay 参数与记录漂移")

        return result
