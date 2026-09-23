"""pixo.service.runtime —— Pixo 本地服务运行时。

持有照片、预览会话、状态机、导出任务与测量/决策入口，供 FastAPI
应用层调用。一期为进程内内存存储，不引入数据库/重型任务框架。
"""
from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

from pixo.meta import extract
from pixo.decide import decide
from pixo.decide.rules import DEFAULT_RULES, load_rules
from pixo.state import PhotoStateMachine
from pixo.pipeline.loop import RawRenderBackend
from pixo.render.web.export import ExportManager
from pixo.render.web.session import (ParamValidationError, RawPreviewSession,
                                     merge_param_patches,
                                     translate_param_intents)
from pixo.vision import MockSegmenter, VisionMeasure, vision_health

_LOGGER = logging.getLogger(__name__)

# 支持的相机 RAW 扩展名（一期扫描/导入）。
SUPPORTED_EXTENSIONS = {
    ".nef", ".nrw", ".dng", ".arw", ".cr2", ".cr3", ".orf", ".raf",
    ".rw2", ".pef", ".srw", ".raw", ".erf", ".mrw", ".x3f",
}

# 默认 DCP 路径：优先使用仓库内置 Nikon Z 5 基线。
_DEFAULT_DCP = (
    Path(__file__).resolve().parents[3]
    / "resources"
    / "dcp"
    / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
)

# 会话 LRU 上限缺省值（env PIXO_MAX_SESSIONS 可调）。
_DEFAULT_MAX_SESSIONS = 8

# 分割器类型 → 测量标记 detection_version（mock 时响应里明确可见）。
_DETECTION_VERSIONS = {
    "mock": "mock_v1",
    "multi": "multi_v1",
}

# R15 region 掩码供给: env PIXO_REGION_SUPPLY（缺省**关**）。
# 实测成本 (本机, PIXO_SEGMENTER=multi): 首次 segment 17.7s (权重冷加载
# 主导, 208 文件 + segformer 首推), 进程热后 0.73s/次 —— 按 "成本 <1s 才
# 建议默认开" 的裁决标准不满足, 故显式开启制; 常驻服务 + 热权重场景由
# 运维设 PIXO_REGION_SUPPLY=1 启用 (热态 0.73s)。
# mock segmenter 环境永不尝试 (R14 契约: 零掩码 + 不可用, 不装可用)。
_REGION_SUPPLY_ENV = "PIXO_REGION_SUPPLY"
_REGION_SUPPLY_EDGE = 512      # 分割输入渲染长边 (掩码经适配器分辨率无关)
_REGION_PROMPTS = ("face", "sky", "plant")


# ---------------------------------------------------------------------------
# R22 F04/F05 —— 参数装配控制键（风格卡注入 / 场景预设）
# ---------------------------------------------------------------------------
# 走既有 PUT /api/sessions/{id}/params 通道的**控制键**：服务层解析后装配
# 成普通 stage 参数再深合并（不新增端点，前端仍只用既有 patchParam 通路）。
#   __style: 风格卡 id（configs/styles/films/*.json 文件名 stem）
#   __scene: 场景预设 id（configs/styles/scenes.json 键集）
_CONTROL_STYLE = "__style"
_CONTROL_SCENE = "__scene"


def _bad_request(message: str) -> Exception:
    """服务层 400：HTTP 面抛 FastAPI HTTPException（app 层不拦 ValueError），
    缺 fastapi（纯库调用方）时退 ValueError。"""
    try:
        from fastapi import HTTPException
    except Exception:  # noqa: BLE001 — 库面无 fastapi 时的降级
        return ValueError(message)
    return HTTPException(status_code=400, detail=message)


def _registered_stage_names() -> set[str]:
    """已注册 Stage 名集合（栅栏派生源，与 param_schema 同源）。"""
    from pixo.render.params import PARAM_SCHEMAS

    return set(PARAM_SCHEMAS)


def _style_card_params(style_id: str) -> dict[str, dict]:
    """风格卡 id → 卡的 params（stage → 参数桶）；未知 id 抛 400。

    卡源 = `StyleCard.from_films_dir()`（`configs/styles/films` 目录白名单）；
    卡的 `stages` 列表同时校验：出现未注册 stage 名即 400（卡源漂移守卫）。
    25 张卡实测全部来自 param_schema 已声明键（见 stream 报告），故本注入
    不会被 F04 栅栏误拒。
    """
    from pixo.know.cards import StyleCard

    cards = StyleCard.from_films_dir()
    for card in cards:
        if card.get("style_id") != style_id:
            continue
        stages = [str(s) for s in (card.get("stages") or [])]
        unknown = sorted(set(stages) - _registered_stage_names())
        if unknown:
            raise _bad_request(
                f"风格卡 '{style_id}' 声明了未注册的 stage {unknown}，拒绝注入")
        params = card.get("params")
        if not isinstance(params, dict):
            raise _bad_request(f"风格卡 '{style_id}' 缺 params 节，无法注入")
        return {k: dict(v) for k, v in params.items() if isinstance(v, dict)}
    raise _bad_request(
        f"未知风格卡 '{style_id}'（可用: "
        f"{sorted(c.get('style_id') for c in cards)}）")


def _scene_preset_params(scene_id: str) -> dict[str, dict]:
    """场景预设 id → params 覆盖（apply_scene_preset）；未知 id / 带 LUT 抛 400。

    复用 `apply_scene_preset`（进程内缓存的 `load_scene_presets`）；本函数
    先按 `load_scene_presets()` 键集做白名单判定，避免只依赖告警回退。
    6 个预设 `lut` 全为 null ⇒ 纯 params 覆盖（design §1 F05）。
    """
    from pixo.render.pipeline.scene_apply import (apply_scene_preset,
                                                 load_scene_presets)

    presets = load_scene_presets()
    if scene_id not in presets:
        raise _bad_request(
            f"未知场景预设 '{scene_id}'（可用: {sorted(presets)}）")
    params, lut = apply_scene_preset(scene_id)
    if lut:
        raise _bad_request(
            f"场景预设 '{scene_id}' 携带 LUT '{lut}'，本轮不支持 LUT 注入"
            f"（仓内无 .cube 资产）")
    return {k: dict(v) for k, v in params.items() if isinstance(v, dict)}


def _region_supply_enabled() -> bool:
    """PIXO_REGION_SUPPLY 开关解析: 缺省关; "1/true/on" (任意大小写) 开。"""
    raw = os.environ.get(_REGION_SUPPLY_ENV, "").strip().lower()
    return raw in {"1", "true", "on"}


def _mask_has_signal(mask) -> bool:
    """R15 P1: 掩码有效性判定 —— 存在非零像素即有信号。

    全零/空 → False（供给不注入, 不虚报可用）。uint8 0/255 与
    float 0..1 两契约形态均适用。
    刻意**不** try/except（r15 门禁教训: 初版漏 import numpy 曾被自身
    except 吞成恒 False）——判定函数裸奔, 不可数值化的坏掩码数据显式
    上抛, 由 _ensure_session_region_masks 外层 except 归类
    segmenter_error 降级, 而非伪装成「分割成功但无掩码」
    （segmenter_no_masks 两语义不混）。
    """
    arr = np.asarray(mask)
    if arr.size == 0:
        return False
    return bool(np.any(arr != 0))


# R16 segmenter 启动预热: env PIXO_SEGMENTER_WARMUP（沿 PIXO_SCORER_WARMUP
# 惯例: "0/false/off/no" 关, **缺省开**）。预热内容 = multi 后端权重加载 +
# 小图首推理（真预热而非 import）——吸收 R15 实测的冷启 17.7s（服务启动
# 后台线程完成, 用户首次供给/测量即热态 0.73s）。非阻塞: 预热线程不挡
# 主服务（app lifespan 以 daemon 线程启动, 不 join）。NC 门控: 预热经
# MultiModelSegmenter 常规路由, PIXO_ALLOW_RESTRICTED 未放行时受限后端
# 天然不在路由表（与注册语义同源, 无需单独门禁）。
_WARMUP_DISABLED = {"0", "false", "off", "no"}
_SEGMENTER_WARMUP_ENV = "PIXO_SEGMENTER_WARMUP"
_SEGMENTER_WARM_PROMPTS = ("sky", "plant", "person")   # 覆盖 segformer+rfdetr
_SEGMENTER_WARM_EDGE = 64     # 预热推理小图长边（加载是成本大头, 图越小越好）


def _segmenter_warmup_enabled() -> bool:
    """PIXO_SEGMENTER_WARMUP 解析: 缺省开; "0/false/off/no" 关。"""
    return os.environ.get(_SEGMENTER_WARMUP_ENV, "1").strip().lower() \
        not in _WARMUP_DISABLED


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    """读 env 整型配置；缺失/非法时回退缺省值。"""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        _LOGGER.warning("env %s=%r 非法，回退缺省 %d", name, raw, default)
        return default


def _now_iso() -> str:
    """生成带时区的 ISO 时间戳。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# R21 F01/F02：闭环（auto-loop）装配层配置与规则注入
# ---------------------------------------------------------------------------

# auto-loop 迭代数：env PIXO_LOOP_MAX_ITERATIONS 可覆盖缺省 3，硬上限 5。
# 依据 R21 探索：单张真 RAW 闭环实测 43.95–107.4s，其中全分辨率 FINAL_QC
# 渲染占 ~98%（probe6 73.09s），迭代数几乎不涨总时长（每轮只是 preview +
# 测量），上限用于兜底资源占用。R26 #21：任务级取消/截止已补（协作粒度 =
# 迭代边界，见 _AutoLoopControl；渲染本体仍无中断点）。
_AUTO_LOOP_DEFAULT_ITERATIONS = 3
_AUTO_LOOP_MAX_ITERATIONS_CAP = 5
_AUTO_LOOP_ITERATIONS_ENV = "PIXO_LOOP_MAX_ITERATIONS"
# 缺省 prompt 组（与 region 供给 / decide_photo 同源）。
_AUTO_LOOP_PROMPTS = ("face", "sky", "plant")
# F02：env PIXO_RULES ∈ {0,false,off,no}（任意大小写）关闭装配层默认规则注入。
_RULES_DISABLED = {"0", "false", "off", "no"}
# mock 分割器留痕标记：掩码为合成，结论不可信（exploration §5.5/风险 6.3）。
_DEGRADED_MOCK_SEGMENTER = "mock_segmenter"


def _auto_loop_default_iterations() -> int:
    """auto-loop 缺省迭代数：env PIXO_LOOP_MAX_ITERATIONS 覆盖 + 硬上限裁剪。

    非法值由 ``_env_int`` 回退缺省并告警；超过硬上限 5 时按上限裁剪
    （env 是运维旋钮，不抛异常打断服务）。
    """
    raw = _env_int(
        _AUTO_LOOP_ITERATIONS_ENV, _AUTO_LOOP_DEFAULT_ITERATIONS, minimum=1
    )
    if raw > _AUTO_LOOP_MAX_ITERATIONS_CAP:
        _LOGGER.warning(
            "env %s=%d 超过硬上限 %d，按上限裁剪",
            _AUTO_LOOP_ITERATIONS_ENV, raw, _AUTO_LOOP_MAX_ITERATIONS_CAP,
        )
        return _AUTO_LOOP_MAX_ITERATIONS_CAP
    return raw


def _validate_max_iterations(value: Any) -> int:
    """校验显式传入的 max_iterations：非整数 / bool / ≤0 / >5 → ValueError。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"max_iterations 必须是整数: {value!r}")
    if value <= 0 or value > _AUTO_LOOP_MAX_ITERATIONS_CAP:
        raise ValueError(
            f"max_iterations 必须在 1..{_AUTO_LOOP_MAX_ITERATIONS_CAP} "
            f"之间: {value}"
        )
    return value


def _load_auto_loop_rules(
    prompts: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    """F02：装配层加载内置默认规则（env PIXO_RULES=0/false/off/no 关闭）。

    必须**显式**传 ``metric_keys=metric_universe(prompts)``：注册表非空时
    ``region_rules.yaml`` 的 ``sky_luminance`` / ``plant_luminance``
    （condition 与 formula 双引用）会抛 ``DecideError``。

    库层 ``SinglePhotoLoop(rules=None)`` 缺省保持空（纯库语义）——本函数是
    装配层注入点，不改 ``pipeline/``（dev-2 文件域）。
    """
    raw = os.environ.get("PIXO_RULES", "").strip().lower()
    if raw in _RULES_DISABLED:
        return []
    # R21 F03 公共 API（dev-2 并行交付）：惰性 import，避免 service 模块
    # 导入期与该文件的交付时序耦合。
    from pixo.pipeline.metrics import metric_universe

    universe = metric_universe(tuple(prompts or _AUTO_LOOP_PROMPTS))
    rules: list[dict[str, Any]] = []
    for path in DEFAULT_RULES:
        rules.extend(load_rules(path, metric_keys=universe))
    return rules


# ---------------------------------------------------------------------------
# R26 tech_debt #21 清偿：任务级协作控制（取消 + 截止）与任务表治理
# ---------------------------------------------------------------------------

# auto-loop 单任务截止时间（秒）：env PIXO_AUTO_LOOP_TIMEOUT_S，0=不设限
# （缺省保持 R21 行为）。截止粒度 = loop 的迭代边界（渲染本体无中断点）。
_AUTO_LOOP_TIMEOUT_ENV = "PIXO_AUTO_LOOP_TIMEOUT_S"
# 终态任务 TTL（秒）：env PIXO_AUTO_LOOP_TASK_TTL_S（下限 60 防误配成 0 秒淘汰）。
_AUTO_LOOP_TTL_ENV = "PIXO_AUTO_LOOP_TASK_TTL_S"
_AUTO_LOOP_TTL_DEFAULT = 1800.0
# 终态任务保留容量上限（超出按 finished 时间淘汰最老；活跃任务不受影响）。
_AUTO_LOOP_TASK_CAP = 200
# 任务终态集合（视图/取消/TTL 判定共用）。
_AUTO_LOOP_TERMINAL = frozenset({"done", "failed", "cancelled"})


class _AutoLoopControl:
    """auto-loop 任务级协作控制（tech_debt #21）。

    渲染无中断点 ⇒ 控制**只能**在 loop 的三个迭代边界生效
    （``SinglePhotoLoop.run(stop_check=...)``）；deadline_s ≤ 0 表示不设截止。
    should_stop 返回停止原因（"cancelled" / "deadline_exceeded"）或 None。
    """

    def __init__(self, deadline_s: float = 0.0) -> None:
        self._cancelled = threading.Event()
        deadline = float(deadline_s or 0.0)
        self._deadline = (
            time.monotonic() + deadline if deadline > 0.0 else None
        )

    def cancel(self) -> None:
        self._cancelled.set()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def timed_out(self) -> bool:
        return self._deadline is not None and time.monotonic() > self._deadline

    def should_stop(self) -> str | None:
        if self.cancelled:
            return "cancelled"
        if self.timed_out():
            return "deadline_exceeded"
        return None


def _auto_loop_timeout_s() -> float:
    """env PIXO_AUTO_LOOP_TIMEOUT_S → 截止秒数（非法回退 0=不设限）。"""
    raw = os.environ.get(_AUTO_LOOP_TIMEOUT_ENV, "").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        _LOGGER.warning("env %s=%r 非法，回退缺省 0（不设截止）",
                        _AUTO_LOOP_TIMEOUT_ENV, raw)
        return 0.0


def _auto_loop_task_ttl_s() -> float:
    """env PIXO_AUTO_LOOP_TASK_TTL_S → 终态任务 TTL 秒数（下限 60）。"""
    raw = os.environ.get(_AUTO_LOOP_TTL_ENV, "").strip()
    try:
        return max(60.0, float(raw))
    except ValueError:
        return _AUTO_LOOP_TTL_DEFAULT


# R30 B2 默认打开观感文件（北极星: 打开照片≈LR; 数据注入, 引擎默认不动）
_DEFAULT_LOOK_FILE = Path(__file__).resolve().parents[3] / "configs" / "styles" / "default_look.json"
_DEFAULT_LOOK_ENV = "PIXO_DEFAULT_LOOK"
_default_look_cache: dict | None = None


def _load_default_look() -> dict:
    """默认打开观感 params（进程内缓存; env=off 回 {}; 文件缺失回 {} + warning）。

    只在会话工厂消费（打开照片的初始 params）; auto-loop 自建闭环不受影响。

    ⚠️ 必须返回**深拷贝**（2026-09-21 修）：旧实现 `dict(cache)` 只拷外层，
    内层 stage 桶与模块级缓存**同一对象**；会话建好后 `_deep_merge` 是**原地
    合并** ⇒ 用户改一次参数就把缓存改写了，**后续新建的所有会话都继承上一次
    的编辑**（实测：S1 置 whitebalance=manual/temp7000 ⇒ S2 全新会话初始
    参数即为 manual/temp7000）。默认观感是「每张照片的初始数据」，不是共享
    可变状态。
    """
    global _default_look_cache
    if _default_look_cache is not None:
        return copy.deepcopy(_default_look_cache)
    raw = os.environ.get(_DEFAULT_LOOK_ENV, "").strip()
    if raw.lower() in ("off", "0", "false", "no"):
        _default_look_cache = {}
        return {}
    path = Path(raw) if raw else _DEFAULT_LOOK_FILE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        params = doc.get("params") if isinstance(doc, dict) else None
        _default_look_cache = dict(params) if isinstance(params, dict) else {}
    except Exception as exc:  # noqa: BLE001 - 观感缺失不阻断打开照片
        _LOGGER.warning("[pixo.runtime] 默认观感加载失败(回中性): %s (%s)",
                        path, exc)
        _default_look_cache = {}
    return copy.deepcopy(_default_look_cache)


# R26 tech_debt #20：状态机转移类事件（重放判定用，machine._auto_event_type 全集）
_AUTO_LOOP_TRANSITION_EVENTS = frozenset({
    "STATE_CHANGE", "AGENT_ESCALATED", "FINAL_QC_ACCEPT",
    "FINAL_QC_REJECT", "QC_ROLLBACK",
})


@dataclass
class PhotoRecord:
    """一张照片的服务端记录。"""

    photo_id: str
    path: Path
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now_iso)
    sessions: list[str] = field(default_factory=list)
    last_measurement: dict[str, Any] = field(default_factory=dict)
    last_decision: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可 JSON 序列化字典。"""
        return {
            "photo_id": self.photo_id,
            "path": str(self.path),
            "metadata": self.metadata,
            "created_at": self.created_at,
            "sessions": list(self.sessions),
            "last_measurement": self.last_measurement,
            "last_decision": self.last_decision,
        }


class PixoServiceRuntime:
    """Pixo 本地服务运行时，封装照片/会话/状态/导出/测量/决策。"""

    def __init__(
        self,
        profile: Any | None = None,
        profile_path: str | Path | None = None,
        work_dir: str | Path | None = None,
        session_factory: Callable[[PhotoRecord, str], Any] | None = None,
        export_manager: ExportManager | None = None,
    ) -> None:
        self.profile = profile
        if self.profile is None:
            from pixo.render.core.calibration import load_dcp

            dcp_path = Path(profile_path or _DEFAULT_DCP)
            self.profile = load_dcp(dcp_path)

        self.work_dir = Path(work_dir) if work_dir is not None else None
        self.export_manager = export_manager or ExportManager(
            self.profile, work_dir=self.work_dir
        )
        self.session_factory = session_factory or self._default_session_factory

        self.photos: dict[str, PhotoRecord] = {}
        # OrderedDict 维护 LRU 访问序：命中 move_to_end，逐出 popitem(last=False)。
        self.sessions: OrderedDict[str, Any] = OrderedDict()
        self.state_machines: dict[str, PhotoStateMachine] = {}
        # 会话 LRU 治理：上限 + session→photo 索引（避免线性反查）。
        self.max_sessions = _env_int("PIXO_MAX_SESSIONS", _DEFAULT_MAX_SESSIONS)
        self._session_photo: dict[str, str] = {}
        # FastAPI 线程池化路由下的 photos/sessions 并发变更锁。
        self._lock = threading.Lock()
        # R15 region 掩码供给的并发防重入锁（GET /region 并发触发单次分割）。
        self._region_supply_lock = threading.Lock()
        # R16 segmenter 推理锁: 预热与供给的 segment 调用互斥（后端懒加载
        # 非线程安全, 并发首推理会重复加载权重）——预热在锁内吸收冷启,
        # 供给持锁等待后即热态。
        self._segmenter_infer_lock = threading.Lock()
        # R16 预热状态（health 暴露, 沿 scorer health_info 惯例）:
        # pending → warming → done|skipped|failed。
        self.segmenter_warmup_info: dict[str, Any] = {"status": "pending"}

        # R21 F01：auto-loop 异步任务表（仿 ExportManager 先例：单 worker
        # 串行 + 任务 dict + 锁；**不复用** ExportManager 实例，职责分离）。
        # max_workers=1：全分辨率渲染内存开销大，串行；与「每 photo 单飞」
        # 双保险。_auto_loop_active 记录 photo_id → running task_id。
        self._auto_loop_tasks: dict[str, dict[str, Any]] = {}
        self._auto_loop_active: dict[str, str] = {}
        self._auto_loop_lock = threading.Lock()
        self._auto_loop_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="auto-loop"
        )

        # 测量分割器：env PIXO_SEGMENTER（mock|multi），缺省 mock
        # 保持现行为（避免意外下载/加载真实模型）。
        self._segmenter_requested = (
            os.environ.get("PIXO_SEGMENTER", "mock").strip().lower() or "mock"
        )
        self.segmenter_type = self._segmenter_requested
        self._segmenter = self._build_segmenter(self._segmenter_requested)

    # ---- 默认工厂 ----

    def _build_segmenter(self, requested: str) -> Any:
        """按类型构造分割器；multi 懒 import，不可用回退 mock 并告警。"""
        if requested == "mock":
            return MockSegmenter()
        try:
            if requested == "multi":
                from pixo.vision.segmenters.multi_router import (
                    MultiModelSegmenter,
                )

                seg = MultiModelSegmenter()
            else:
                raise ValueError(
                    f"未知 PIXO_SEGMENTER: {requested!r}（可选 mock|multi）"
                )
            self.segmenter_type = requested
            return seg
        except ImportError as exc:  # 仅捕获依赖缺失回退 mock，真实构造错误上抛
            self.segmenter_type = "mock"
            _LOGGER.warning(
                "PIXO_SEGMENTER=%s 构造失败(%s)，回退 MockSegmenter 假测量",
                requested, exc,
            )
            return MockSegmenter()

    def _default_session_factory(
        self,
        photo: PhotoRecord,
        session_id: str,
    ) -> RawPreviewSession:
        """创建真实 RawPreviewSession（服务层：开启 strict 参数栅栏）。

        R30 B2 默认打开观感：新会话初始 params 注入 default_look.json
        （北极星"打开照片≈LR"；数据注入, 引擎各 Stage 默认值不动）。
        用户 patch 经既有 _deep_merge 深合并覆盖（改任一键/关闭任一 stage）。
        env PIXO_DEFAULT_LOOK：'off' 回中性（R23 行为）；非空路径覆盖文件；
        文件缺失/非法回中性 + warning（不阻断打开照片）。
        """
        return RawPreviewSession(photo.path, self.profile,
                                 params=_load_default_look(),
                                 session_id=session_id,
                                 validate_params=True)

    # ---- 导入 / 照片 ----

    def _data_roots(self) -> list[Path]:
        """解析 PIXO_DATA_ROOT 白名单根目录（pathsep 分隔）。

        未显式配置时返回 [] 表示不限制（保持默认开发/测试行为）；
        显式配置后严格生效，拒绝白名单外的任意目录枚举。
        """
        raw = os.environ.get("PIXO_DATA_ROOT", "").strip()
        if not raw:
            return []
        return [
            Path(part).expanduser().resolve()
            for part in raw.split(os.pathsep) if part.strip()
        ]

    def _ensure_scannable(self, root: Path) -> None:
        """目录枚举白名单校验：显式配置 PIXO_DATA_ROOT 时拒绝白名单外路径。"""
        allowed = self._data_roots()
        if not allowed:                       # 未显式配置：不限制
            return
        for base in allowed:
            if root == base or base in root.parents:
                return
        raise ValueError(
            f"目录 {root} 不在 PIXO_DATA_ROOT 白名单内 "
            f"（允许: {[str(a) for a in allowed]}），拒绝枚举任意路径"
        )

    def scan_directory(self, directory: str | Path) -> list[dict[str, Any]]:
        """扫描白名单内目录，返回 RAW 候选文件清单（不创建记录）。"""
        root = Path(directory).expanduser().resolve()
        self._ensure_scannable(root)
        if not root.is_dir():
            raise ValueError(f"目录不存在: {root}")
        candidates: list[dict[str, Any]] = []
        for path in sorted(root.iterdir()):
            if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
                candidates.append({
                    "path": str(path),
                    "name": path.name,
                    "size": path.stat().st_size,
                })
        return candidates

    def create_photo(
        self,
        raw_path: str | Path,
        photo_id: str | None = None,
    ) -> PhotoRecord:
        """创建照片记录；路径不存在或无法读取时抛 ValueError。"""
        path = Path(raw_path).expanduser().resolve()
        # 与 scan_directory 同一套白名单：配置 PIXO_DATA_ROOT 后拒绝
        # 白名单外路径（未配置时不限制），避免枚举面收窄、读取面全开。
        self._ensure_scannable(path)
        if not path.is_file():
            raise ValueError(f"照片文件不存在: {path}")
        photo_id = photo_id or uuid.uuid4().hex[:12]
        if photo_id in self.photos:
            raise ValueError(f"photo_id 已存在: {photo_id}")

        try:
            metadata = extract(str(path))
        except Exception:  # noqa: BLE001 - 元数据失败不阻断导入
            metadata = {}

        photo = PhotoRecord(photo_id=photo_id, path=path, metadata=metadata)
        self.photos[photo_id] = photo
        self.state_machines[photo_id] = PhotoStateMachine(photo_id)
        return photo

    def get_photo(self, photo_id: str) -> PhotoRecord:
        """获取照片记录；不存在时抛 KeyError。"""
        if photo_id not in self.photos:
            raise KeyError(f"photo 不存在: {photo_id}")
        return self.photos[photo_id]

    def list_photos(self) -> list[PhotoRecord]:
        """按创建时间返回全部照片。"""
        return list(self.photos.values())

    def photo_dict(self, photo_id: str) -> dict[str, Any]:
        """返回含状态信息的照片详情。"""
        photo = self.get_photo(photo_id)
        data = photo.to_dict()
        sm = self.state_machines.get(photo_id)
        if sm is not None:
            data["state"] = sm.state
            data["iteration"] = sm.record.iteration
            data["next_action"] = sm.record.next_action
        return data

    # ---- 会话 ----

    def create_session(
        self,
        photo_id: str,
        session_id: str | None = None,
    ) -> Any:
        """为照片创建预览会话。"""
        photo = self.get_photo(photo_id)
        session_id = session_id or uuid.uuid4().hex[:16]
        with self._lock:
            if session_id in self.sessions:
                raise ValueError(f"session_id 已存在: {session_id}")
        session = self.session_factory(photo, session_id)
        evicted: list[tuple[str, Any]] = []
        with self._lock:
            self.sessions[session_id] = session
            self._session_photo[session_id] = photo_id
            photo.sessions.append(session_id)
            # 会话 LRU 治理（t107）：超上限逐出访问序最旧会话，同步清理
            # session→photo 索引与 photo.sessions，避免残留死 id 导致
            # decide_photo 取 sessions[-1] 后 get_session KeyError。
            while len(self.sessions) > self.max_sessions:
                old_id, old = self.sessions.popitem(last=False)
                old_photo_id = self._session_photo.pop(old_id, None)
                old_photo = (
                    self.photos.get(old_photo_id) if old_photo_id else None
                )
                if old_photo is not None and old_id in old_photo.sessions:
                    old_photo.sessions.remove(old_id)
                evicted.append((old_id, old))
        # 被逐出会话防御式 close()：释放 RawPreviewSession 的多级缓存与
        # 线程池，避免服务形态内存无界增长；放锁外避免持锁做 IO。
        for old_id, old in evicted:
            close = getattr(old, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:  # noqa: BLE001 - 关闭失败不阻断创建
                    _LOGGER.warning(
                        "[pixo.runtime] 会话 close 失败: %s", old_id)
        return session

    def get_session(self, session_id: str) -> Any:
        """获取会话并 LRU touch；不存在时抛 KeyError。"""
        with self._lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise KeyError(f"session 不存在: {session_id}")
            self.sessions.move_to_end(session_id)
            return session

    def session_dict(self, session_id: str) -> dict[str, Any]:
        """返回会话基础信息。"""
        session = self.get_session(session_id)
        return {
            "session_id": session.session_id,
            "photo_id": getattr(session, "photo_id", None),
            "generation": session.generation,
            "raw_path": str(session.raw_path),
        }

    def update_params(
        self,
        session_id: str,
        patch: dict[str, Any],
        source: str | None = None,
    ) -> dict[str, Any]:
        """深合并局部参数并递增 generation，同时记录 Trace。

        响应附 `region` 状态节（M1 前端 region 控件的可用性感知）：每次
        patch 后 UI 即可感知掩码是否可用（不可用时滑杆置灰而非静默失效）。

        R22 F04/F05 装配：patch 内的控制键 `__style`（风格卡 id）/`__scene`
        （场景预设 id）在此解析为 stage 参数覆盖，再与 patch 其余内容深合并
        （显式参数优先）。解析结果经会话栅栏校验（未知 stage/键/数值域/
        路径类 → HTTP 400）。两个控制键同时给出视为语义冲突 → 400。

        2026-09-21 追加「调用方边界意图翻译」：装配后过
        :func:`translate_param_intents` —— 显式参数 ⇒ 声明执行该 Stage
        （门控 Stage 补 `enabled=True`）、显式 `temp`/`tint` ⇒ 切 `manual`
        白平衡。这是**调用方边界**的职责（引擎只读 `enabled`，不猜意图），
        否则 UI 滑杆「调了没效果」。
        """
        session = self.get_session(session_id)
        patch = dict(patch or {})
        style_id = patch.pop(_CONTROL_STYLE, None)
        scene_id = patch.pop(_CONTROL_SCENE, None)
        if style_id is not None and scene_id is not None:
            raise _bad_request(
                f"'{_CONTROL_STYLE}' 与 '{_CONTROL_SCENE}' 不能同时提交"
                f"（一次装配一个来源）")
        control_traces: list[tuple[str, Any]] = []
        if scene_id is not None:
            scene_params = _scene_preset_params(str(scene_id))
            patch = merge_param_patches(scene_params, patch)
            control_traces.append((_CONTROL_SCENE, scene_id))
        if style_id is not None:
            card_params = _style_card_params(str(style_id))
            patch = merge_param_patches(card_params, patch)
            control_traces.append((_CONTROL_STYLE, style_id))
        # 调用方边界意图翻译（2026-09-21）：显式参数 ⇒ 声明执行该 Stage /
        # 显式 temp·tint ⇒ 切 manual 白平衡。放在卡·场景装配**之后**——卡里
        # 显式声明的 enabled/mode 优先，翻译只补空缺。引擎侧依旧零自动开启。
        patch = translate_param_intents(patch)
        try:
            generation = session.update_params(patch)
        except ParamValidationError as exc:
            # 栅栏拒绝 → 400（不落任何部分合并）
            raise _bad_request(str(exc)) from exc
        photo_id = self._photo_id_for_session(session_id)
        sm = self.state_machines.get(photo_id)
        if sm is not None:
            for key, value in control_traces:
                sm.add_trace(
                    event_type="param_patch",
                    param=str(key),
                    value=value,
                    new_value=value,
                    source=source or "api",
                )
            for key, value in patch.items():
                sm.add_trace(
                    event_type="param_patch",
                    param=str(key),
                    value=value,
                    new_value=value,
                    source=source or "api",
                )
        return {
            "session_id": session_id,
            "generation": generation,
            "params": dict(session.params),
            "canonical": session.canonical_params(),
            "region": self._region_status_of(session),
        }

    def _region_status_of(self, session: Any) -> dict[str, Any]:
        """会话 region 掩码状态节（M1, R14; R15 扩展供给来源语义）。

        - available: `session.region_masks`（F13 Route B 属性）非空 dict；
        - prompts: 掩码 prompt 有序列表（仅可用时）;
        - reason（不可用原因, R16 四分）:
          "masks_not_injected": 供给未开/未尝试（含 mock segmenter 环境）;
          "segmenter_warming": 供给开启且预热/另一供给持推理锁——非阻塞
          返回, 稍后重查即可热态供给;
          "segmenter_no_masks": 供给已尝试且分割成功, 但掩码全零/空
          （无有效区域 → HSM 不应用, 不虚报可用）;
          "segmenter_error": 分割异常降级（与"成功但全零"区分）。
        """
        masks = getattr(session, "region_masks", None)
        prompts = (
            sorted(str(k) for k in masks)
            if isinstance(masks, dict) and masks else []
        )
        available = bool(prompts)
        source = getattr(session, "region_masks_source", None)
        if available:
            reason = None
        elif source == "segmenter":
            reason = "segmenter_no_masks"
        elif source == "segmenter_error":
            reason = "segmenter_error"
        elif source == "warming":
            reason = "segmenter_warming"
        else:
            reason = "masks_not_injected"
        return {
            "available": available,
            "prompts": prompts,
            "reason": reason,
        }

    def region_status(self, session_id: str) -> dict[str, Any]:
        """查询会话 region 掩码状态；开启供给时懒触发一次分割（R15）。"""
        session = self.get_session(session_id)
        self._ensure_session_region_masks(session)
        return {
            "session_id": session.session_id,
            "generation": session.generation,
            **self._region_status_of(session),
        }

    # ---- R16: segmenter 启动预热 ----

    def warm_segmenter(self) -> dict[str, Any]:
        """R16: segmenter 启动预热 —— 后端加载 + 小图首推理（真预热）。

        由 app lifespan 以**非阻塞后台 daemon 线程**启动（冷启 ~18s 不挡
        主服务；本方法在线程内执行, 幂等——预热完成后重复调用直接返回）。
        返回预热信息 dict（同时写入 self.segmenter_warmup_info 供 health）。
        """
        info = self.segmenter_warmup_info
        if info.get("status") == "done":
            return dict(info)                     # 幂等（并发/重复预热）
        if not _segmenter_warmup_enabled():
            info.update(status="skipped", reason="env_off")
            return dict(info)
        if self.segmenter_type != "multi":
            # mock 无权重可加载, 预热无意义（R14/R15 契约: 不装可用）
            info.update(status="skipped",
                        reason=f"segmenter={self.segmenter_type}")
            return dict(info)
        info["status"] = "warming"
        t0 = time.perf_counter()
        try:
            img = np.full((_SEGMENTER_WARM_EDGE // 4 * 3,
                           _SEGMENTER_WARM_EDGE, 3), 128, dtype=np.uint8)
            with self._segmenter_infer_lock:
                out = self._segmenter.segment(
                    img, list(_SEGMENTER_WARM_PROMPTS))
            backends = sorted({
                self._segmenter.route_table.get(p)
                for p in _SEGMENTER_WARM_PROMPTS
            } - {None}) if hasattr(self._segmenter, "route_table") else []
            info.update(status="done",
                        duration_s=round(time.perf_counter() - t0, 2),
                        prompts=list(_SEGMENTER_WARM_PROMPTS),
                        backends=backends,
                        masked_prompts=sorted(out) if isinstance(out, dict) else [])
        except Exception as exc:  # noqa: BLE001 - 预热失败不挡服务
            info.update(status="failed",
                        duration_s=round(time.perf_counter() - t0, 2),
                        error=f"{type(exc).__name__}: {exc}")
            _LOGGER.warning("[pixo.runtime] segmenter 预热失败(不影响服务): %s",
                            exc)
        return dict(info)

    def _ensure_session_region_masks(self, session: Any) -> None:
        """R15: 预览会话掩码供给 —— 懒触发一次分割并 Route B 注入。

        语义与生命周期:
          - 每会话至多一次（session.region_masks 非 None 即视为已尝试,
            空 dict = "分割完成但无掩码", 同样不再重试）;
          - 掩码缓存沿 session（重渲染不重分割; region_masks 经
            region_masks.py 适配器分辨率无关适配, 透传纪律保 stage 缓存
            命中）;
          - 有效性判定 (R15 P1 修复): 注入前逐 prompt 检查非零像素 ——
            全零/空掩码不注入（避免状态虚报 available=True 而 UI 滑杆
            静默失效）; 仅保留有信号的 prompt（status.prompts 即真实
            可用面）; 与「分割异常降级」路径 reason 区分
            （segmenter_error vs segmenter_no_masks）;
          - 门槛: PIXO_REGION_SUPPLY 开 + segmenter_type=="multi"（mock
            环境零掩码 + 不可用, 不装可用 —— R14 契约不变）; 分割异常
            降级为空掩码 + warn（不炸状态端点）。
        """
        if getattr(session, "region_masks", None) is not None:
            return
        if not _region_supply_enabled() or self.segmenter_type != "multi":
            return
        # R16 非阻塞衔接: 推理锁被预热/另一供给持有时**立即返回**（预热不挡
        # 请求, status.reason="segmenter_warming" 供 UI 稍后重查），锁释放后
        # 的下次查询以热态执行供给。
        if not self._segmenter_infer_lock.acquire(blocking=False):
            session.region_masks_source = "warming"
            return
        try:
            with self._region_supply_lock:
                if getattr(session, "region_masks", None) is not None:
                    return                    # 并发 GET 下另一线程已完成
                try:
                    img = session.render(
                        long_edge=_REGION_SUPPLY_EDGE)
                    # 持推理锁内分割: 与预热互斥（后端懒加载非线程安全）。
                    masks = self._segmenter.segment(
                        img, list(_REGION_PROMPTS))
                    candidates = dict(masks) if isinstance(masks, dict) else {}
                    valid = {k: v for k, v in candidates.items()
                             if _mask_has_signal(v)}
                    if valid:
                        session.region_masks = valid
                        session.region_masks_source = "segmenter"
                        _LOGGER.info(
                            "[pixo.runtime] region 掩码供给完成: session=%s "
                            "prompts=%s", session.session_id, sorted(valid))
                    else:
                        # 全零/空: 分割成功但无有效区域 → HSM 不应用（不注入,
                        # 不虚报 available）
                        session.region_masks = {}
                        session.region_masks_source = "segmenter"
                        _LOGGER.info(
                            "[pixo.runtime] region 掩码供给: 分割成功但无有效"
                            "区域掩码, HSM 不应用: session=%s",
                            session.session_id)
                except Exception as exc:  # noqa: BLE001 - 失败不炸状态端点
                    session.region_masks = {}
                    session.region_masks_source = "segmenter_error"
                    _LOGGER.warning(
                        "[pixo.runtime] region 掩码供给失败 (降级为不可用): "
                        "session=%s %s: %s", session.session_id,
                        type(exc).__name__, exc)
        finally:
            self._segmenter_infer_lock.release()

    def _photo_id_for_session(self, session_id: str) -> str | None:
        """反查 photo_id：优先 session→photo 索引（O(1)），miss 再兜底扫描。"""
        photo_id = self._session_photo.get(session_id)
        if photo_id:
            return photo_id
        direct = getattr(self.sessions.get(session_id), "photo_id", None)
        if direct:
            return str(direct)
        for pid, photo in self.photos.items():
            if session_id in photo.sessions:
                return pid
        return None

    # ---- 测量 / 决策 ----

    def measure_session(
        self,
        session_id: str,
        long_edge: int = 1024,
    ) -> dict[str, Any]:
        """对当前会话渲染预览图并执行 Pixo Vision 整图测量。"""
        session = self.get_session(session_id)
        try:
            image = session.render(long_edge=int(long_edge))
        except Exception:  # noqa: BLE001 - 测量不应让 API 因渲染失败而中断
            image = None
        if image is None:
            return {
                "session_id": session_id,
                "generation": session.generation,
                "measurement": None,
                "error": "render_failed",
            }
        photo_id = self._photo_id_for_session(session_id)
        # 使用注入的分割器（env PIXO_SEGMENTER 构造），detection_version
        # 随实际生效的分割器类型标记，避免装饰性接线。
        masks = self._segmenter.segment(image, ["face", "sky", "plant"])
        measurement = VisionMeasure().measure(
            image,
            masks,
            image_id=photo_id,
            render_version="0.1.0",
            detection_version=_DETECTION_VERSIONS.get(
                self.segmenter_type, "mock_v1"
            ),
            mask_version="mask_v0.1",
        )
        # R21 F03：把 compute_proxy_metrics 的三代理键合并到 measurement
        # **顶层**（与 loop.py:1352-1354 / :1730-1732 同源同层），且必须在
        # 回写 photo.last_measurement（下一行）**之前**——否则 decide 侧
        # haze_proxy / colorfulness_proxy / tonal_range 恒缺（成因②），
        # color_rules / tone_clarity 的 proxy 规则永不触发。
        from pixo.pipeline.metrics import merge_proxy_metrics

        merged = merge_proxy_metrics(measurement, image)
        if isinstance(merged, dict):
            measurement = merged
        if photo_id is not None and photo_id in self.photos:
            self.photos[photo_id].last_measurement = measurement
        return {
            "session_id": session_id,
            "photo_id": photo_id,
            "generation": session.generation,
            "measurement": measurement,
        }

    def histogram_session(
        self,
        session_id: str,
        long_edge: int = 1024,
        bins: int = 256,
    ) -> dict[str, Any]:
        """对当前会话渲染预览并计算直方图（R25 F02，R23 §6 能力补齐）。

        与 measure_session 同错误语义：渲染失败不抛 5xx，返回 error 标记。
        直方图数组本体不进 measurement/decide（规则引擎只吃标量，见
        pipeline/metrics.py）；本方法仅供工作台反馈环（/histogram 端点）。
        """
        from pixo.vision.measure import compute_histogram

        session = self.get_session(session_id)
        try:
            image = session.render(long_edge=int(long_edge))
        except Exception:  # noqa: BLE001 - 直方图不应让 API 因渲染失败而中断
            image = None
        if image is None:
            return {
                "session_id": session_id,
                "generation": session.generation,
                "histogram": None,
                "error": "render_failed",
            }
        hist = compute_histogram(image, bins=int(bins))
        return {
            "session_id": session_id,
            "generation": session.generation,
            "histogram": hist,
        }

    def decide_photo(self, photo_id: str) -> dict[str, Any]:
        """获取照片当前状态并执行一轮 Decide（单轮语义：不迭代、不回写渲染）。

        R21 F03：metrics 走公共 API ``metrics_for_decide``（展平 global /
        regions / 顶层 proxies），并注入装配层默认规则（``PIXO_RULES=off``
        可关）。响应**字段集合不变**，仅 ``decision.params`` 由 ``{}`` 变
        非空（design-r21 §0 分叉1采纳 A2）。
        """
        photo = self.get_photo(photo_id)
        sm = self.state_machines.get(photo_id)
        session_id = photo.sessions[-1] if photo.sessions else None
        measurement: dict[str, Any] = {}
        params: dict[str, Any] = {}
        if session_id is not None:
            measure_result = self.measure_session(session_id)
            if measure_result.get("measurement") is not None:
                measurement = measure_result["measurement"]
            session = self.get_session(session_id)
            try:
                params = session.canonical_params()
            except Exception:  # noqa: BLE001
                params = dict(getattr(session, "params", {}))

        from pixo.pipeline.metrics import metrics_for_decide

        iteration = sm.record.iteration if sm is not None else 0
        result = decide({
            "metrics": metrics_for_decide(measurement),
            "params": params,
            "iteration": max(1, iteration + 1),
            "rules": _load_auto_loop_rules(_AUTO_LOOP_PROMPTS),
        })
        # 记录最近一次决策，供照片详情/后续规则读取（字段此前从不写入）。
        photo.last_decision = result
        return {
            "photo_id": photo_id,
            "state": sm.state if sm is not None else "UNKNOWN",
            "iteration": iteration,
            "measurement": measurement,
            "decision": result,
        }

    def timeline(self, photo_id: str) -> dict[str, Any]:
        """返回照片状态机当前状态与 Trace 事件流。"""
        photo = self.get_photo(photo_id)
        sm = self.state_machines.get(photo_id)
        events: list[dict[str, Any]] = []
        if sm is not None:
            events = [e.to_dict() for e in sm.history()]
        return {
            "photo_id": photo_id,
            "state": sm.state if sm is not None else "UNKNOWN",
            "iteration": sm.record.iteration if sm is not None else 0,
            "events": events,
        }

    # ---- 闭环（auto-loop，R21 F01/F02）----

    def run_auto_loop(
        self,
        photo_id: str,
        *,
        max_iterations: int | None = None,
        preview_long_edge: int = 1024,
        prompts: Sequence[str] | None = None,
        sync: bool = False,
    ) -> dict[str, Any]:
        """把单张闭环（SinglePhotoLoop + RawRenderBackend）接进服务层。

        装配规则（design-r21 §2.2 1~8，逐条固定）：
        ``RawRenderBackend(photo.path, self.profile)``、
        ``segmenter=self._segmenter``（显式，不依赖 loop 内部 mock 兜底）、
        ``rules=_load_auto_loop_rules(prompts)``、
        ``manual_on_unreliable=False``（库层缺省 True 会让首轮转
        MANUAL_REVIEW，规则全不落地）、``aesthetic_scorer=None``、
        ``targets={}``/``locked_params=[]``/``agent_suggest=False``/
        ``enable_style_cards=False``。**不读 preview session /
        canonical_params**——「无 session」不是错误（对齐 exploration §6.12）。

        Args:
            max_iterations: None → env PIXO_LOOP_MAX_ITERATIONS 或 3；显式
                传入时校验 1..5，非法抛 ValueError（API → 400）。
            preview_long_edge: preview 渲染长边（缺省 1024）。
            prompts: 区域 prompt 组，缺省 ("face","sky","plant")。
            sync: False → 提交后台任务，立即返回
                ``{task_id, status:"running", photo_id, segmenter_type}``；
                True → 阻塞至闭环结束，返回与 :meth:`auto_loop_status`
                同构的结果（异常同样落 ``status=failed``，不裸抛）。

        Returns:
            任务视图 dict；同 photo 已有 running 任务时返回既有 task_id。
        """
        photo = self.get_photo(photo_id)          # KeyError → 404
        iterations = (
            _auto_loop_default_iterations()
            if max_iterations is None
            else _validate_max_iterations(max_iterations)
        )
        prompts_tuple = tuple(prompts or _AUTO_LOOP_PROMPTS)
        degraded = (
            [_DEGRADED_MOCK_SEGMENTER]
            if self.segmenter_type == "mock" else []
        )

        with self._auto_loop_lock:
            # 每 photo 单飞：同 photo 已有 running 任务 → 不新起，返回既有
            # task_id（幂等，避免重复全分辨率渲染）。
            active_id = self._auto_loop_active.get(photo_id)
            if active_id is not None:
                active = self._auto_loop_tasks.get(active_id)
                # R26 #21：单飞口径含 queued（单 worker FIFO，排队任务同样
                # 占住该 photo 的"在途"名额，防重复提交）。
                if active is not None and active["status"] in ("queued", "running"):
                    return self._auto_loop_submit_view(active)
                self._auto_loop_active.pop(photo_id, None)

            self._prune_auto_loop_tasks()
            task_id = uuid.uuid4().hex
            task: dict[str, Any] = {
                "task_id": task_id,
                # R26 #21：提交即 queued，worker 领取时转 running（单 worker
                # FIFO 下旧口径"提交即 running"会虚报执行态）。
                "status": "queued",
                "photo_id": photo_id,
                "segmenter_type": self.segmenter_type,
                "degraded": degraded,
                "state": None,
                "iteration": 0,
                "params": {},
                "rule_ids": [],
                "rule_ids_by_iteration": [],
                "trace_event_count": 0,
                # R22/F06：多轴 QC 软告警槽（闭环跑完由 payload 覆写；
                # 未跑完/未跑到 FINAL_QC 时保持空列表）。
                "soft_warnings": [],
                "error": None,
                "duration": None,
                # R26 #21：任务表治理/审计三时间戳（iso；_finished_ts 供 TTL）
                "created_at": _now_iso(),
                "started_at": None,
                "finished_at": None,
                "cancel_requested": False,
                # 内部键（视图不透出）：协作控制句柄 + 终态 epoch
                "_control": _AutoLoopControl(_auto_loop_timeout_s()),
                "_finished_ts": None,
            }
            self._auto_loop_tasks[task_id] = task
            self._auto_loop_active[photo_id] = task_id
            control: _AutoLoopControl = task["_control"]

        if sync:
            self._execute_auto_loop(
                task_id, photo_id, str(photo.path), iterations,
                int(preview_long_edge), prompts_tuple, control,
            )
            return self.auto_loop_status(task_id)

        self._auto_loop_executor.submit(
            self._execute_auto_loop,
            task_id, photo_id, str(photo.path), iterations,
            int(preview_long_edge), prompts_tuple, control,
        )
        return self._auto_loop_submit_view(task)

    def auto_loop_status(self, task_id: str) -> dict[str, Any]:
        """查询 auto-loop 任务状态（未知 task_id → KeyError → 404）。"""
        with self._auto_loop_lock:
            task = self._auto_loop_tasks.get(task_id)
            if task is None:
                raise KeyError(f"auto-loop 任务不存在: {task_id}")
            return self._auto_loop_view(task)

    def cancel_auto_loop(self, task_id: str) -> dict[str, Any]:
        """R26 #21：请求取消 auto-loop 任务（协作粒度 = loop 迭代边界）。

        - 终态任务：幂等返回当前状态（cancel_requested=False）；
        - queued：直接落 cancelled（worker 领取时跳过）；
        - running：置取消标记，loop 在最近迭代边界停止（返回 cancelling
          语义，任务终态以 GET 轮询为准）。
        """
        with self._auto_loop_lock:
            task = self._auto_loop_tasks.get(task_id)
            if task is None:
                raise KeyError(f"auto-loop 任务不存在: {task_id}")
            if task["status"] in _AUTO_LOOP_TERMINAL:
                return {"task_id": task_id, "status": task["status"],
                        "cancel_requested": False}
            task["cancel_requested"] = True
            control = task.get("_control")
            if control is not None:
                control.cancel()
            if task["status"] == "queued":
                task.update(status="cancelled", finished_at=_now_iso(),
                            _finished_ts=time.time(), duration=0.0)
                if self._auto_loop_active.get(task["photo_id"]) == task_id:
                    self._auto_loop_active.pop(task["photo_id"], None)
                return {"task_id": task_id, "status": "cancelled",
                        "cancel_requested": True}
            return {"task_id": task_id, "status": "cancelling",
                    "cancel_requested": True,
                    "note": "已在最近迭代边界生效，终态以 GET 轮询为准"}

    def _prune_auto_loop_tasks(self) -> None:
        """R26 #21：终态任务治理（TTL + 容量上限；调用方持锁）。

        活跃（queued/running）任务永不淘汰；TTL 按 finished 时间计，
        容量超限时按最老优先淘汰。防任务表"只增不减"（#21 原文）。
        """
        now = time.time()
        ttl = _auto_loop_task_ttl_s()
        dead: list[tuple[float, str]] = []  # (finished_ts, task_id)
        alive_finished = 0
        for key, t in self._auto_loop_tasks.items():
            if t["status"] not in _AUTO_LOOP_TERMINAL:
                continue
            ts = t.get("_finished_ts")
            if ts is not None and (now - ts) > ttl:
                dead.append((ts, key))
                continue
            alive_finished += 1
        if alive_finished > _AUTO_LOOP_TASK_CAP:
            ordered = sorted(
                (t.get("_finished_ts") or 0.0, key)
                for key, t in self._auto_loop_tasks.items()
                if t["status"] in _AUTO_LOOP_TERMINAL
                and key not in {k for _, k in dead}
            )
            for _, key in ordered[: alive_finished - _AUTO_LOOP_TASK_CAP]:
                dead.append((0.0, key))
        for _, key in dead:
            self._auto_loop_tasks.pop(key, None)

    def _auto_loop_submit_view(self, task: dict[str, Any]) -> dict[str, Any]:
        """提交响应视图（202 缺省形态）。"""
        view: dict[str, Any] = {
            "task_id": task["task_id"],
            "status": task["status"],
            "photo_id": task["photo_id"],
            "segmenter_type": task["segmenter_type"],
        }
        if task["degraded"]:
            view["degraded"] = list(task["degraded"])
        return view

    def _auto_loop_view(self, task: dict[str, Any]) -> dict[str, Any]:
        """GET 轮询视图（含闭环结果字段；SYNC 与 GET 同构）。"""
        view: dict[str, Any] = {
            "task_id": task["task_id"],
            "status": task["status"],
            "photo_id": task["photo_id"],
            "segmenter_type": task["segmenter_type"],
            "state": task["state"],
            "iteration": task["iteration"],
            "params": dict(task["params"]),
            "rule_ids": list(task["rule_ids"]),
            "rule_ids_by_iteration": [
                {"iteration": item["iteration"],
                 "rule_ids": list(item["rule_ids"])}
                for item in task["rule_ids_by_iteration"]
            ],
            "trace_event_count": task["trace_event_count"],
            # R22/F06：多轴 QC 软告警（既有键一个不少、不改名；纯追加）。
            "soft_warnings": list(task["soft_warnings"]),
            "error": task["error"],
            "duration": task["duration"],
            # R26 #21：治理/审计时间戳 + 取消标记（纯追加键）。
            "created_at": task.get("created_at"),
            "started_at": task.get("started_at"),
            "finished_at": task.get("finished_at"),
            "cancel_requested": bool(task.get("cancel_requested")),
        }
        if task["degraded"]:
            view["degraded"] = list(task["degraded"])
        return view

    def _execute_auto_loop(
        self,
        task_id: str,
        photo_id: str,
        raw_path: str,
        max_iterations: int,
        preview_long_edge: int,
        prompts: tuple[str, ...],
        control: _AutoLoopControl | None = None,
    ) -> None:
        """后台线程体：装配 SinglePhotoLoop → run → 结果落任务表。

        **闭环内部异常不裸抛**：catch-all 记 ``status=failed`` +
        ``error = 异常类型: 首行``（异步与 sync 两路一致，HTTP 层不 500）。
        R26 #21：worker 领取时 queued→running；stop_check 协作停止落
        cancelled（用户取消）或 failed+timeout（截止超限）。
        R26 #20：成功终局（done）显式回写服务层（状态机重放 + trace 导入
        + last_decision 合成，见 _write_back_auto_loop）。
        """
        from pixo.pipeline.loop import SinglePhotoLoop

        with self._auto_loop_lock:
            task = self._auto_loop_tasks.get(task_id)
            if task is None:
                return
            if task["status"] == "cancelled":
                # 排队期间被取消：worker 直接跳过（终态已落）
                if self._auto_loop_active.get(photo_id) == task_id:
                    self._auto_loop_active.pop(photo_id, None)
                return
            task.update(status="running", started_at=_now_iso())

        started = time.monotonic()
        payload: dict[str, Any] | None = None
        error: str | None = None
        stopped_reason: str | None = None
        result: Any = None
        try:
            loop = SinglePhotoLoop(
                render_backend=RawRenderBackend(raw_path, self.profile),
                segmenter=self._segmenter,
                measurer=VisionMeasure(),
                rules=_load_auto_loop_rules(prompts),
                preview_long_edge=int(preview_long_edge),
                max_iterations=int(max_iterations),
                prompts=list(prompts),
                targets={},
                locked_params=[],
                manual_on_unreliable=False,
                aesthetic_scorer=None,
                agent_suggest=False,
                enable_style_cards=False,
            )
            result = loop.run(
                photo_id, raw_path=raw_path, max_iterations=int(max_iterations),
                stop_check=control.should_stop if control is not None else None,
            )
            stopped_reason = (result.metadata or {}).get("stop_reason") \
                if (result.metadata or {}).get("stopped") else None
            # 提取（含 trace rule_ids）放在同一 try 内：任何提取异常同样
            # 落 status=failed，不会把任务卡在 running。
            payload = {
                "state": result.state,
                "iteration": result.iteration,
                "params": dict(result.params or {}),
                "rule_ids": self._auto_loop_rule_ids(result),
                "rule_ids_by_iteration": (
                    self._auto_loop_rule_ids_by_iteration(result)
                ),
                "trace_event_count": len(result.trace_events or []),
                # R22/F06 多轴 QC 软告警透出（**追加**键：既有键一个不少、
                # 不改名）。来源 = loop 把 _qc_soft_warnings 结果写进
                # LoopResult.metadata；缺席（未跑到 FINAL_QC）时给空列表，
                # 前端/调用方形态稳定。软告警不参与任何判定。
                "soft_warnings": list(
                    (result.metadata or {}).get("soft_warnings") or []
                ),
                # R26 #20：回写 last_decision 的 reasons 用（同形 decide 输出）
                "reason": result.reason,
            }
        except Exception as exc:  # noqa: BLE001 - 闭环异常落任务表，不穿 HTTP
            first_line = (str(exc).splitlines() or [""])[0]
            error = f"{type(exc).__name__}: {first_line}"
            _LOGGER.warning(
                "[pixo.runtime] auto-loop 任务失败: task=%s photo=%s %s",
                task_id, photo_id, error,
            )

        duration = round(time.monotonic() - started, 3)
        with self._auto_loop_lock:
            task = self._auto_loop_tasks.get(task_id)
            if task is not None:
                if payload is not None and stopped_reason == "cancelled":
                    task.update(status="cancelled", error=None,
                                duration=duration, finished_at=_now_iso(),
                                _finished_ts=time.time(), **payload)
                elif payload is not None and stopped_reason is not None:
                    task.update(status="failed",
                                error="timeout: 截止时间在迭代边界超限",
                                duration=duration, finished_at=_now_iso(),
                                _finished_ts=time.time(), **payload)
                elif payload is not None:
                    task.update(status="done", error=None, duration=duration,
                                finished_at=_now_iso(),
                                _finished_ts=time.time(), **payload)
                else:
                    task.update(status="failed", error=error, duration=duration,
                                finished_at=_now_iso(),
                                _finished_ts=time.time())
                if self._auto_loop_active.get(task["photo_id"]) == task_id:
                    self._auto_loop_active.pop(task["photo_id"], None)

        # R26 #20：成功终局才回写（cancelled/failed 的部分结果不进缓存，
        # 防半态污染 /timeline 与 /decide）。
        if payload is not None and stopped_reason is None:
            try:
                self._write_back_auto_loop(
                    photo_id, task_id, payload, result.trace_events or []
                )
            except Exception as exc:  # noqa: BLE001 - 回写失败要可见，不静默
                _LOGGER.exception(
                    "[pixo.runtime] auto-loop 回写失败: task=%s photo=%s",
                    task_id, photo_id,
                )
                with self._auto_loop_lock:
                    t = self._auto_loop_tasks.get(task_id)
                    if t is not None and t["status"] == "done":
                        t.update(status="failed",
                                 error=f"write_back_failed: "
                                       f"{type(exc).__name__}: "
                                       f"{(str(exc).splitlines() or [''])[0]}")

    def _write_back_auto_loop(
        self,
        photo_id: str,
        task_id: str,
        payload: dict[str, Any],
        trace_events: list[dict[str, Any]],
    ) -> None:
        """R26 tech_debt #20 清偿：auto-loop 成功终局**显式**回写服务层。

        三件事（契约）：
        ① **状态机重放**：service SM 停在 RAW_PENDING（创建后从未流转）时，
           按 loop 的转移事件序列重放 ⇒ ``/timeline`` 与 ``photo.state``
           反映全程轨迹与终态（重放用 transition 自带轨迹落痕，时戳为重放
           时刻；loop 原始历史仍完整保留在任务 payload 的 trace 里）。
           SM 已离开 RAW_PENDING（重跑）则**不重放**（防非法转移），仅补
           一条 ``auto_loop_summary`` 事件 + 同步终态字段。
        ② **非状态事件导入**：decide/measure/param 等事件原样 add_trace，
           ``source="auto_loop"``（与用户编辑轨迹可区分）。
        ③ **last_decision 合成**：decide 引擎同形 dict（decision/params/
           reasons/rule_ids/unreliable_regions/last_iteration + 扩展键
           source/task_id/state），``GET /decide`` 原样透传。
        """
        sm = self.state_machines.get(photo_id)
        replayed = False
        if sm is not None:
            if sm.state == "RAW_PENDING":
                for event in trace_events:
                    if not isinstance(event, dict):
                        continue
                    event_type = event.get("event_type", "")
                    if event_type in _AUTO_LOOP_TRANSITION_EVENTS:
                        sm.transition(
                            str(event.get("new_value")),
                            reason=str(event.get("reason") or ""),
                        )
                    else:
                        sm.add_trace(
                            event_type=event_type,
                            reason=str(event.get("reason") or ""),
                            source="auto_loop",
                            param=event.get("param"),
                            value=event.get("value"),
                            old_value=event.get("old_value"),
                            new_value=event.get("new_value"),
                            rule_id=str(event.get("rule_id") or ""),
                            formula=str(event.get("formula") or ""),
                            iteration=int(event.get("iteration") or 0),
                            metadata=dict(event.get("metadata") or {}),
                        )
                # 同步终态字段（iteration/params 不在转移事件里，直接对齐）
                sm.record.iteration = int(payload["iteration"])
                sm.record.current_params = dict(payload["params"])
                replayed = True
            else:
                sm.add_trace(
                    event_type="auto_loop_summary",
                    reason="auto-loop 完成（SM 已离开 RAW_PENDING，不重放转移）",
                    source="auto_loop",
                    new_value=payload["state"],
                    iteration=int(payload["iteration"]),
                    metadata={"task_id": task_id,
                              "rule_ids": list(payload["rule_ids"])},
                )
                sm.record.iteration = int(payload["iteration"])
                sm.record.current_params = dict(payload["params"])

        photo = self.photos.get(photo_id)
        if photo is not None:
            photo.last_decision = {
                # decision 语义 = loop 终态（ACCEPTED/MANUAL_REVIEW），与
                # decide 引擎单轮动作词（adjust_and_continue…）不同词汇表，
                # 用 source="auto_loop" 显式区分（消费方按 source 分派）。
                "decision": payload["state"],
                "params": dict(payload["params"]),
                "reasons": [payload["reason"]],
                "rule_ids": list(payload["rule_ids"]),
                "unreliable_regions": [],
                "last_iteration": int(payload["iteration"]),
                "source": "auto_loop",
                "task_id": task_id,
                "state": payload["state"],
            }

    @staticmethod
    def _auto_loop_decide_events(result: Any) -> list[tuple[int, list[str]]]:
        """按 trace 顺序取所有 ``decide`` 事件的 ``(iteration, rule_ids)``。

        iteration 取 ``value["iteration"]``，缺失时回退 ``metadata["iteration"]``，
        再缺失时回退该 decide 事件的 1 起始序号（防御，正常 loop 两条都在）。
        """
        events: list[tuple[int, list[str]]] = []
        for index, event in enumerate(result.trace_events or [], start=1):
            if not isinstance(event, dict):
                continue
            if event.get("event_type") != "decide":
                continue
            value = event.get("value")
            value = value if isinstance(value, dict) else {}
            ids = [str(r) for r in (value.get("rule_ids") or [])]
            iteration = value.get("iteration")
            if isinstance(iteration, bool) or not isinstance(iteration, int):
                metadata = event.get("metadata")
                iteration = (
                    metadata.get("iteration")
                    if isinstance(metadata, dict) else None
                )
            if isinstance(iteration, bool) or not isinstance(iteration, int):
                iteration = index
            events.append((int(iteration), ids))
        return events

    @classmethod
    def _auto_loop_rule_ids(cls, result: Any) -> list[str]:
        """整轮闭环实际落地过的规则 = **全部** decide 事件 rule_ids 的并集。

        保持首次出现顺序、去重。

        **为什么不是「最后一条」decide 事件**（R21 修订 R1，归因已经 QA 更正）：
        闭环收敛后末轮 `decide()` 的规则**自然不命中** —— 首轮命中并写入参数后
        指标已回到阈值内（真 RAW 实测：`saturation_high_rule` 由
        `colorfulness_proxy` 6.19 ≥ 6.13 命中、写入 `saturation=-0.15`，末轮该
        指标降到 5.8936 < 6.13）。末轮**照常评估规则**：`iteration >= max_iterations`
        走的是 `last_iteration` 分支，返回 `should_stop=False`（`engine.py:977-989`
        的 t107 off-by-one 注释：末轮规则必须跑一次）⇒ `decide()` **不短路**，
        照常走 `_apply_rules_internal`（`engine.py:1165-1173`）后因无命中返回
        `rule_ids=[]`。此时取「最后一条」会让真 RAW 常规路径下 `rule_ids`
        结构性为空（tester F05 真 RAW 首跑即因此 FAILED）。

        另有一条**不同的**合法空路径：`check_termination` 判停（manual_review /
        stopped / targets_met 等）时 `decide()` 在 `engine.py:1147-1163` 短路返回
        `rule_ids=[]`（该轮确实未应用规则）——本次真 RAW 未走该路径，且引擎
        语义正确，本流不改 `decide/`。

        注意**不是** `LoopResult.decision`——后者是 `sm.state` 字符串
        （loop.py:1959）。
        """
        merged: list[str] = []
        seen: set[str] = set()
        for _iteration, ids in cls._auto_loop_decide_events(result):
            for rule_id in ids:
                if rule_id not in seen:
                    seen.add(rule_id)
                    merged.append(rule_id)
        return merged

    @classmethod
    def _auto_loop_rule_ids_by_iteration(
        cls, result: Any
    ) -> list[dict[str, Any]]:
        """诊断视图：每条 decide 事件 → ``{"iteration": int, "rule_ids": [...]}``。

        用于区分「哪一轮命中了什么」（并集看总量、本字段看逐轮分布）。
        """
        return [
            {"iteration": iteration, "rule_ids": list(ids)}
            for iteration, ids in cls._auto_loop_decide_events(result)
        ]

    # ---- 导出 ----

    def submit_export(
        self,
        session_id: str,
        fmt: str,
        quality: int | None = None,
        output_dir: str | Path | None = None,
        demosaic: str | None = None,
    ) -> dict[str, Any]:
        """提交导出任务。

        demosaic (R32-T1)：可选 "AHD"/"RCD"——导出请求体独立字段，经 session
        属性（ExportManager getattr 读取）转发全质量线，不进 params 白名单；
        None 保持 session 现值（缺省 "AHD"，默认链零漂移）。
        """
        session = self.get_session(session_id)
        if demosaic is not None:
            if demosaic not in ("AHD", "RCD"):
                raise ValueError(f"不支持的 demosaic 选项: {demosaic}")
            session.demosaic = demosaic
        task_id = self.export_manager.submit(
            session,
            fmt=fmt,
            quality=quality,
            output_dir=Path(output_dir) if output_dir is not None else None,
        )
        return {
            "task_id": task_id,
            "status": self.export_manager.status(task_id)["status"],
        }

    def export_status(self, task_id: str) -> dict[str, Any]:
        """查询导出任务状态。"""
        try:
            return self.export_manager.status(task_id)
        except KeyError as exc:
            raise KeyError(f"导出任务不存在: {task_id}") from exc

    # ---- 健康 ----

    def health(self) -> dict[str, Any]:
        """服务健康与依赖/模型状态。"""
        return {
            "status": "ok",
            "service": "pixo-service",
            "version": "0.1.0",
            "vision": vision_health(),
            "segmenter": {
                # t91：报告当前实际生效的分割器路由（构造失败回退后为 mock）。
                "router": self.segmenter_type,
                "part_prompts": ["hair", "skin", "clothes", "body"],
                # R16: 启动预热状态/耗时（沿 scorer health_info 惯例）。
                "warmup": dict(self.segmenter_warmup_info),
            },
            "photos": len(self.photos),
            "sessions": len(self.sessions),
        }


__all__ = [
    "PixoServiceRuntime",
    "PhotoRecord",
    "SUPPORTED_EXTENSIONS",
]
