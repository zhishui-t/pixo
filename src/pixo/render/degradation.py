"""pixo.render.degradation —— 关键路径静默降级采集 (R22 F03, L1 采集层)。

背景 (R22 §0 P8 / CR-08): 全仓 132 处 ``except Exception`` 里只有 exploration
§4.2 列的 **13 条关键路径** 会静默切换到等价回退实现 (native 内核缺失、标定
表损坏、LUT/解码路径切换)。切换本身是设计行为, 但**用户/门禁看不到发生过**,
A/B 与金样本对拍的结论就可能建立在「其实是回退路径」的假前提上。

本模块提供最小承载点 (范式对齐 ``vision/health.py:82-126`` 的
``last_degraded`` / ``multi_router._warn_once`` 节流协议):

  L1 (本模块): ``record_degradation(source, exc, ...)`` 记录结构化事件 +
    warn-once 节流 (同 ``(source, path, kind)`` 只告警一次, 之后降为 debug)。
  L2 (``pixo.vision.health``): ``vision_health()`` 返回 dict 新增
    ``render_degraded`` / ``render_degraded_count`` /
    ``render_version_gate_rejections`` 键 (见 ``vision/health.py``)。

**「版本门合法拒绝」≠「真异常」** (设计 §1 F03 / §4.2 #11):
native 封装在 DLL 版本不足时会主动抛 ``RuntimeError`` (如 colorcal oklch 内核
``需 DLL >= 1.6.0``; 旧 DLL 缺符号时 ``DLL 未导出``) —— 那是**设计好的分层
回退**, 不是故障。把它记成 degraded 会造成每次渲染都误告警 (本机 DLL 版本
固定时 = 恒告警)。故:

  - ``version_gate`` (expected): 只进 ``version_gate_rejections`` 通道,
    **不**进 ``render_degraded``, 日志降为 debug (不产生 warning);
  - ``native_unavailable``: 整个 native DLL 未加载/加载失败 → 仍算**真降级**
    (加速链整体缺失, 可能是安装损坏), 进 degraded;
  - 其余异常 → ``exception``, 进 degraded。

线程安全 (一把锁覆盖读改); 条目上限 ``MAX_ENTRIES`` 防无界增长;
``clear_render_degradations()`` 供测试隔离。
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Iterable

__all__ = [
    "MAX_ENTRIES",
    "classify_native_failure",
    "is_expected_failure",
    "record_degradation",
    "render_degraded_entries",
    "version_gate_rejections",
    "render_degradation_report",
    "clear_render_degradations",
]

_LOGGER = logging.getLogger(__name__)

#: 结构化条目上限 (超出后只累加已有条目的 count, 不再新增)。
MAX_ENTRIES = 64

#: 版本门/符号门标记 (native 封装在版本不足时抛出的 RuntimeError 文本)。
#:   - "需 DLL >="  : 显式版本比较 (如 colorcal oklch 内核需 >= 1.6.0)
#:   - "DLL 未导出" : 旧 DLL 缺符号 (等价于版本不足)
_VERSION_GATE_MARKERS = ("需 DLL >=", "DLL 未导出")

#: 整库不可用标记 (DLL 文件缺失/加载失败) —— 与版本门区分: 这是真降级。
_NATIVE_UNAVAILABLE_MARKERS = ("native DLL unavailable",)

#: 事件类别
KIND_VERSION_GATE = "version_gate"
KIND_NATIVE_UNAVAILABLE = "native_unavailable"
KIND_EXCEPTION = "exception"
KIND_FALLBACK = "fallback"

_LOCK = threading.RLock()
#: key=(source, path, kind) -> 条目 dict (就地累加 count / last_seen)
_DEGRADED: "dict[tuple, dict[str, Any]]" = {}
_VERSION_GATES: "dict[tuple, dict[str, Any]]" = {}
#: 已告警过的 key (warn-once 节流; clear 时清空)
_WARNED: set = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def classify_native_failure(exc: BaseException | None) -> str:
    """按异常文本区分「版本门合法拒绝」/「整库不可用」/「真异常」。

    判定依据 = native 封装 (``render/_native/__init__.py``) 的三类**声明式**
    RuntimeError 文本, 而非异常类型 (三类都是 ``RuntimeError``):
      1. ``需 DLL >= X`` / ``DLL 未导出`` → ``version_gate`` (设计好的回退);
      2. ``native DLL unavailable``      → ``native_unavailable``;
      3. 其余                            → ``exception``。
    exc 为 None (无异常的结构化降级, 如标定表缺内容) → ``fallback``。
    """
    if exc is None:
        return KIND_FALLBACK
    text = f"{exc}"
    if any(m in text for m in _VERSION_GATE_MARKERS):
        return KIND_VERSION_GATE
    if any(m in text for m in _NATIVE_UNAVAILABLE_MARKERS):
        return KIND_NATIVE_UNAVAILABLE
    return KIND_EXCEPTION


def is_expected_failure(exc: BaseException | None) -> bool:
    """True = 版本门合法拒绝 (设计行为, 不计入 degraded)。"""
    return classify_native_failure(exc) == KIND_VERSION_GATE


def _make_entry(source: str, kind: str, path: str | None, reason: str,
                detail: str, exc: BaseException | None) -> dict[str, Any]:
    stamp = _now()
    return {
        "source": source,
        "kind": kind,
        "path": path,
        "reason": reason,
        "detail": detail,
        "exception": f"{type(exc).__name__}: {exc}" if exc is not None else None,
        "expected": kind == KIND_VERSION_GATE,
        "count": 1,
        "first_seen": stamp,
        "last_seen": stamp,
        "timestamp": stamp,
    }


def record_degradation(
    source: str,
    exc: BaseException | None = None,
    *,
    path: str | None = None,
    reason: str | None = None,
    detail: str = "",
    kind: str | None = None,
) -> dict[str, Any]:
    """记录一条关键路径降级事件, 返回条目副本 (就地累加去重后的最新态)。

    source : 稳定标识 (如 ``render.white_balance.warmth_curve``)
    exc    : 触发的异常; 无异常的结构化降级传 None
    path   : 涉及的资源路径 (标定文件/DLL/RAW), 可为 None
    reason : 短原因标签, 缺省 = kind (version_gate/native_unavailable/exception/fallback)
    detail : 人读补充说明 (回退到了什么)
    kind   : 显式覆盖类别 (缺省按 ``classify_native_failure(exc)`` 自动判定)

    仅 **非** 版本门拒绝的事件进 degraded 通道; 版本门拒绝进
    ``version_gate_rejections`` 通道并**不产生 warning 日志**。
    """
    if kind is None:
        kind = classify_native_failure(exc)
    if reason is None:
        reason = kind
    entry = _make_entry(source, kind, path, reason, detail, exc)
    key = (source, path, kind)
    with _LOCK:
        store = _VERSION_GATES if kind == KIND_VERSION_GATE else _DEGRADED
        existing = store.get(key)
        if existing is not None:
            existing["count"] += 1
            existing["last_seen"] = entry["last_seen"]
            existing["timestamp"] = entry["timestamp"]
            if exc is not None:
                existing["exception"] = entry["exception"]
            snapshot = dict(existing)
        elif len(store) >= MAX_ENTRIES:
            snapshot = dict(entry)
            snapshot["detail"] = (
                f"{detail} (已达条目上限 {MAX_ENTRIES}, 本条未登记)").strip()
        else:
            store[key] = entry
            snapshot = dict(entry)
        first_time = key not in _WARNED
        _WARNED.add(key)
    if first_time:
        if kind == KIND_VERSION_GATE:
            # 设计行为: 不告警 (否则每次渲染都刷 warning)。
            _LOGGER.debug(
                "[render-degraded] 版本门合法拒绝 source=%s path=%s (%s)",
                source, path, reason)
        else:
            _LOGGER.warning(
                "[render-degraded] 关键路径降级 source=%s kind=%s path=%s "
                "reason=%s exc=%s detail=%s",
                source, kind, path, reason, snapshot.get("exception"), detail)
    else:
        _LOGGER.debug(
            "[render-degraded] 重复降级 source=%s kind=%s count=%s",
            source, kind, snapshot.get("count"))
    return snapshot


def _copies(store: "dict[tuple, dict[str, Any]]") -> list[dict[str, Any]]:
    with _LOCK:
        return [dict(e) for e in store.values()]


def render_degraded_entries() -> list[dict[str, Any]]:
    """真降级条目 (按首次发生顺序; 返回副本)。"""
    return _copies(_DEGRADED)


def version_gate_rejections() -> list[dict[str, Any]]:
    """版本门合法拒绝条目 (独立通道, 不参与 degraded 判定; 返回副本)。"""
    return _copies(_VERSION_GATES)


def render_degradation_report() -> dict[str, Any]:
    """L2 暴露用的汇总结构 (来源/原因/时间戳 + 计数)。"""
    degraded = render_degraded_entries()
    gates = version_gate_rejections()
    return {
        "count": len(degraded),
        "entries": degraded,
        "version_gate_count": len(gates),
        "version_gate_rejections": gates,
    }


def clear_render_degradations() -> None:
    """清空全部条目与 warn-once 记录 (测试隔离钩子)。"""
    with _LOCK:
        _DEGRADED.clear()
        _VERSION_GATES.clear()
        _WARNED.clear()


def _sources(entries: Iterable[dict[str, Any]]) -> list[str]:
    """调试辅助: 取 source 列表。"""
    return [str(e.get("source")) for e in entries]
