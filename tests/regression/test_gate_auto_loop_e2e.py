"""Gate: R21 F05 —— 服务层装配件的**真 RAW** 闭环端到端门禁（A-B）。

依据 `.agent-team/design-r21.md` §4（唯一门禁依据）：

- 文件级 ``pytest.mark.gate`` ⇒ 被 CR-05 的 ``-m gate`` 选中；
- 用例级 ``pytest.mark.gate_e2e`` ⇒ 被 ``tests/regression/conftest.py`` 的
  skip→fail 规则豁免（仅该 marker 允许 skip）；
- **独立 env** ``PIXO_GATE_AUTOLOOP_RAW``（NEF 路径）——**不复用**
  ``RAW_PATH``：复用会连带激活 ``test_gate_e2e_perf.py`` 的 30s 单张性能
  门禁，而真 RAW 单次闭环实测 ≈73s（exploration §5.6）⇒ 必挂。

运行（必须经 ``python -m pytest``：``import pixo`` 依赖 ``tests/conftest.py``
把 ``src`` 插入 ``sys.path``）::

    $env:PIXO_GATE_AUTOLOOP_RAW='K:\\data\\photo\\0711\\raw\\DSC_5236.NEF'
    python -m pytest tests/regression/test_gate_auto_loop_e2e.py -q -m gate

装配口径（design §4，逐条固定）：``rules=_load_auto_loop_rules(prompts)``
（装配层 11 条内置规则）、真分割器 ``MultiModelSegmenter``、
``manual_on_unreliable=False``（库层缺省 True 会让首轮转 MANUAL_REVIEW）、
``preview_long_edge=1024``、``max_iterations=PIXO_GATE_AUTOLOOP_MAX_ITER``
（缺省 2）；**不设** ``PIXO_ALLOW_RESTRICTED``（``sapiens`` 权重本机缺失，
exploration §5.4/§6.10）。

断言集（design §4 五条）：
  1. ``state == "ACCEPTED"``
  2. ``params`` 非空 + ``rule_ids`` 非空。**口径经队长 2026-09-10 裁决修订**：
     原「取最后一条 decide 事件」会**漏掉
     早期命中** —— 末轮是否命中取决于该轮指标是否跨过阈值，实测 DSC_5236
     末条为空、DSC_5237 末条命中，两种形态都存在，见下）：
     ``rule_ids`` = 全 trace 中所有 ``event_type=="decide"`` 事件
     ``value["rule_ids"]`` 的**并集**（保持首次出现顺序、去重）。
     **不钉死具体 rule_id**——``saturation_high_rule`` 仅 ~1% 余量
     （exploration §5.7/§6.7）。
  3. ``final_image`` 与「仅渲染基线」（同 backend ``render_full({})``）存在
     像素差（同 shape/dtype）
  4. ``final_measurement["global"]["highlight_clip_ratio"] <= 0.03``
  5. ``trace_events`` 含 ``param_update`` 且 ``len(measurements) >= 2``
  6. **聚合自洽（正控）**：服务侧提取口径（``PixoServiceRuntime._auto_loop_rule_ids``）
     == ``_auto_loop_rule_ids_by_iteration`` 的逐轮并集 == 本门禁的并集口径
     （同序去重逐项相等），且逐轮条目与 trace 的 decide 事件一一对应

**为什么是并集而非「最后一条」**（首跑 FAILED 的实测结论，QA 增量复核已定稿）：
末轮 ``rule_ids=[]`` 有**两条都合法**的空路径 ——
① **本次实测触发的路径 = 末轮规则自然不命中（不是短路）**：
``iteration >= max_iterations`` 走 ``check_termination`` 的 ``last_iteration``
分支，该分支返回 ``should_stop=False``（``engine.py:977-989``，t107 off-by-one
注释明写「末轮规则**必须**触发一次」）⇒ ``decide()`` 不短路、照常评估规则
（``engine.py:1165-1173``）。实测（`tmp-r21-gate-run3.txt`）：末轮 decide
``{decision:'adjust_and_continue', last_iteration:True, rule_ids:[],
colorfulness_proxy:5.8936}`` —— 首轮 ``saturation_high_rule`` 命中
（``colorfulness_proxy`` 6.1888 ≥ 阈值 6.13）并落地
``colorcal.saturation=-0.15``，末轮该指标已降到 5.8936 < 6.13 ⇒ **该轮确实
无规则命中**，``rule_ids=[]`` 语义正确。
② 另一条合法空路径：``check_termination`` 返回 ``should_stop=True``
（如 ``low_improvement``/``targets_met``）时 ``decide()`` 在
``engine.py:1147-1163`` 短路返回 ``rule_ids=[]`` + 原样透传 params（本次未触发）。

⇒ 缺陷不在 engine，而在「取最后一条」这个**提取口径**：它**不是**必然为空
（D1 三样本实测 DSC_5237 末轮**命中**、末条非空），而是**会漏掉早期命中**：
末轮命中与否取决于该轮指标是否跨过阈值。服务侧
``runtime._auto_loop_rule_ids`` 已按队长 2026-09-10 裁决 A 同源修订为并集 +
追加 ``rule_ids_by_iteration`` 诊断字段。

离线纪律：跑前设 ``HF_HUB_OFFLINE=1`` / ``TRANSFORMERS_OFFLINE=1``（权重已在
本机缓存，避免任何下载；``rfdetr`` 走 ``~/.roboflow`` 本地文件）。用
``monkeypatch.setenv`` 设置以避免污染同进程的其它测试。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gate

_REPO = Path(__file__).resolve().parents[2]
_DCP = (
    _REPO / "resources" / "dcp"
    / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"
)

# 独立 env：绝不复用 RAW_PATH（会连带激活 30s 性能门禁）。
_RAW = os.environ.get("PIXO_GATE_AUTOLOOP_RAW", "")
_MAX_ITER = int(os.environ.get("PIXO_GATE_AUTOLOOP_MAX_ITER", "2"))

_PROMPTS = ("face", "sky", "plant")
_QC_OVERFLOW_MAX = 0.03  # 与 engine.py:81 / loop.py:1745-1749 同源阈值


def _decide_events(result) -> list[dict]:
    """逐条 ``event_type=="decide"`` 事件摘要（诊断「哪一轮命中、哪一轮终止」）。

    队长 2026-09-10 裁决要求门禁输出该诊断面：真 RAW 末轮 decide 走
    ``last_iteration`` 分支（``engine.py:977-989``，``should_stop=False``）
    **照常评估规则**，只是该轮规则自然不命中（``rule_ids=[]``）—— 只看
    「最后一条」无法看出**前面哪一轮命中过**。
    """
    events: list[dict] = []
    for event in result.trace_events or []:
        if not isinstance(event, dict):
            continue
        if event.get("event_type") != "decide":
            continue
        value = event.get("value")
        if not isinstance(value, dict):
            continue
        metrics = value.get("metrics") or {}
        events.append({
            "iteration": value.get("iteration"),
            "decision": value.get("decision"),
            "rule_ids": [str(r) for r in (value.get("rule_ids") or [])],
            "last_iteration": bool(value.get("last_iteration")),
            "colorfulness_proxy": metrics.get("colorfulness_proxy"),
        })
    return events


def _decide_rule_ids_union(result) -> list[str]:
    """全 trace ``decide`` 事件 ``value["rule_ids"]`` 的并集（首次出现序、去重）。

    口径经队长 2026-09-10 裁决修订（design §2.2/§4 断言② 同源修订）。
    """
    union: list[str] = []
    for event in _decide_events(result):
        for rule_id in event["rule_ids"]:
            if rule_id not in union:
                union.append(rule_id)
    return union


def _last_decide_event(result) -> dict:
    """最后一条 decide trace（失败时进断言消息，便于定位）。"""
    found: dict = {}
    for event in result.trace_events or []:
        if isinstance(event, dict) and event.get("event_type") == "decide":
            value = event.get("value")
            if isinstance(value, dict):
                found = value
    return found


@pytest.mark.gate_e2e
@pytest.mark.skipif(not _RAW, reason="PIXO_GATE_AUTOLOOP_RAW not set")
def test_real_raw_auto_loop_end_to_end(monkeypatch):
    """真 RAW 闭环五条断言（design §4）。"""
    # ---- 离线：禁止任何权重下载（权重已在本机缓存） ----
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    # 显式关掉「关闭规则」开关：门禁必须跑在默认规则注入路径上。
    monkeypatch.delenv("PIXO_RULES", raising=False)
    # 不设 PIXO_ALLOW_RESTRICTED（sapiens 权重缺失）。

    from pixo.pipeline.loop import RawRenderBackend, SinglePhotoLoop
    from pixo.render.core.calibration import load_dcp
    from pixo.service.runtime import _load_auto_loop_rules
    from pixo.vision.segmenters.multi_router import MultiModelSegmenter

    raw_path = Path(_RAW)
    assert raw_path.exists(), f"PIXO_GATE_AUTOLOOP_RAW 指向的文件不存在: {raw_path}"
    assert _DCP.exists(), f"DCP 不存在: {_DCP}"

    rules = _load_auto_loop_rules(_PROMPTS)
    assert rules, "装配层默认规则集为空：F02 注入失效"
    print(f"[R21-F05] rules_count={len(rules)}")

    segmenter = MultiModelSegmenter()
    prof = load_dcp(_DCP)
    # 同一 backend 对象既供 loop 渲染，也供「仅渲染基线」重渲。
    backend = RawRenderBackend(raw_path, prof)

    loop = SinglePhotoLoop(
        render_backend=backend,
        segmenter=segmenter,
        rules=rules,
        preview_long_edge=1024,
        max_iterations=_MAX_ITER,
        prompts=list(_PROMPTS),
        manual_on_unreliable=False,
    )
    result = loop.run(
        "gate_autoloop_e2e", raw_path=str(raw_path), max_iterations=_MAX_ITER
    )

    decide_events = _decide_events(result)
    rule_ids = _decide_rule_ids_union(result)
    decide_ev = _last_decide_event(result)
    event_types = [
        e.get("event_type") for e in (result.trace_events or [])
        if isinstance(e, dict)
    ]
    global_m = (result.final_measurement or {}).get("global") or {}
    print(
        "[R21-F05] "
        + json.dumps(
            {
                "state": result.state,
                "reason": result.reason,
                "iteration": result.iteration,
                "rules_count": len(rules),
                "params": result.params,
                "rule_ids": rule_ids,
                "rule_ids_last_nonempty": next(
                    (e["rule_ids"] for e in reversed(decide_events)
                     if e["rule_ids"]), []
                ),
                "trace_event_count": len(result.trace_events or []),
                "measurements": len(result.measurements or []),
                "has_param_update": "param_update" in event_types,
                "highlight_clip_ratio": global_m.get("highlight_clip_ratio"),
                "colorfulness_proxy": (result.final_measurement or {}).get(
                    "colorfulness_proxy"
                ),
                "segmenter_last_degraded": list(
                    getattr(segmenter, "last_degraded", []) or []
                ),
            },
            ensure_ascii=False,
            default=str,
        )
    )
    # 诊断面（队长 2026-09-10 裁决要求）：逐条 decide —— 哪一轮命中、哪一轮终止。
    print(
        "[R21-F05-decide-events] "
        + json.dumps(decide_events, ensure_ascii=False, default=str)
    )

    # ---- ① 状态必须 ACCEPTED（不放宽；MANUAL_REVIEW 时把证据带出来） ----
    assert result.state == "ACCEPTED", (
        f"闭环终态 {result.state!r} != 'ACCEPTED'（reason={result.reason!r}；"
        f"最后一条 decide={decide_ev!r}；"
        f"trace_event_types={event_types!r}）"
    )

    # ---- ② params 非空 + rule_ids 非空（全 trace decide 并集口径，不钉死 rule_id） ----
    assert result.params, f"决策参数为空：params={result.params!r}"
    assert rule_ids, (
        "rule_ids 结构性为空：全 trace 的 decide 事件均未命中任何规则"
        f"（逐条 decide={decide_events!r}）"
    )

    # ---- ③ 与「仅渲染基线」存在像素差（同 backend、不传决策参数） ----
    final = result.final_image
    assert final is not None, "final_image 为 None（闭环未产出全分辨率结果）"
    baseline = backend.render_full({})
    assert final.shape == baseline.shape, (
        f"final_image shape={final.shape} 与基线 shape={baseline.shape} 不一致"
    )
    assert final.dtype == baseline.dtype, (
        f"final_image dtype={final.dtype} 与基线 dtype={baseline.dtype} 不一致"
    )
    diff_px = int(np.count_nonzero(final != baseline))
    print(f"[R21-F05] baseline_pixel_diff={diff_px}")
    assert np.any(final != baseline), (
        "final_image 与「仅渲染基线」逐像素完全相同：决策参数未落地到渲染"
    )

    # ---- ④ FINAL_QC 高光溢出 ≤ 3% ----
    ratio = global_m.get("highlight_clip_ratio")
    assert ratio is not None, (
        f"final_measurement['global'] 缺 highlight_clip_ratio（keys="
        f"{sorted((result.final_measurement or {}).keys())!r}）"
    )
    assert float(ratio) <= _QC_OVERFLOW_MAX, (
        f"FINAL_QC 高光溢出 {float(ratio):.4f} > {_QC_OVERFLOW_MAX}"
    )

    # ---- ⑤ trace 含 param_update 且 measurements >= 2 ----
    assert "param_update" in event_types, (
        f"trace_events 缺 param_update（实际类型={sorted(set(event_types))!r}）"
    )
    assert len(result.measurements or []) >= 2, (
        f"preview measurements 长度 {len(result.measurements or [])} < 2"
        f"（max_iterations={_MAX_ITER}）"
    )

    # ---- ⑥ 聚合自洽（正控，design §4-6）：服务提取口径 == 逐轮并集 == 门禁口径 ----
    from pixo.service.runtime import PixoServiceRuntime

    by_iteration = PixoServiceRuntime._auto_loop_rule_ids_by_iteration(result)
    service_union = PixoServiceRuntime._auto_loop_rule_ids(result)
    print(
        "[R21-F05-rule-ids-by-iteration] "
        + json.dumps(by_iteration, ensure_ascii=False, default=str)
    )
    assert [item["iteration"] for item in by_iteration] == [
        event["iteration"] for event in decide_events
    ], "rule_ids_by_iteration 的逐轮条目与 trace 的 decide 事件不一一对应"
    merged: list[str] = []
    for item in by_iteration:
        for rule_id in item["rule_ids"]:
            if rule_id not in merged:
                merged.append(rule_id)
    assert service_union == merged, (
        f"服务 rule_ids={service_union!r} != rule_ids_by_iteration 逐轮并集="
        f"{merged!r}（聚合口径不自洽）"
    )
    assert service_union == rule_ids, (
        f"服务口径 {service_union!r} != 门禁并集口径 {rule_ids!r}"
    )

    # 末轮机制形态（正控，design §4-6 / 队长 2026-09-10 更正版）：
    # 末轮走 last_iteration 分支 ⇒ should_stop=False ⇒ 规则**照常评估**
    # （engine.py:977-989 t107 off-by-one），绝不是 engine.py:1147-1163 短路。
    last_round = decide_events[-1]
    assert last_round["last_iteration"] is True, (
        f"末轮 decide 未带 last_iteration 标记：{last_round!r}"
    )
    assert last_round["decision"] == "adjust_and_continue", (
        f"末轮 decide 走了 should_stop 短路（{last_round!r}）—— t107 off-by-one "
        "要求末轮规则必须触发一次"
    )
    # 语料相关观测（**不是**不变量）：本设计语料 DSC_5236 上首轮命中
    # saturation_high_rule 后 colorfulness_proxy 自 6.1888 降到 5.8936 < 6.13
    # ⇒ 末轮规则自然不命中，但并集必须保住**早期命中**。换语料时仅打印不判。
    if raw_path.name.upper() == "DSC_5236.NEF":
        assert last_round["rule_ids"] == [], (
            f"DSC_5236 末轮规则自然不命中的实测形态被打破：{last_round!r}"
        )
        assert rule_ids, "DSC_5236 并集为空：早期命中被丢失"


def test_rule_ids_aggregation_negative_and_positive_control():
    """断言 7 镜像（design §4-7，单元级、无 RAW、必跑）。

    主责用例在 ``tests/integration/test_auto_loop_api.py``（承接方 dev-1）；
    本镜像保证单独跑 ``-m gate`` 门禁文件时该口径同样被钉住：
      ① 空 trace / 全部 decide ``rule_ids=[]`` → 必须 ``[]``（不伪造命中）；
      ② 首轮命中 + 末轮为空 → 必须返回首轮命中（不丢早期命中）。
    注意：本用例**不**断言「末轮必空」——末轮走 ``last_iteration`` 分支照常
    评估规则（``engine.py:977-989``），空与不空都合法。
    """
    from types import SimpleNamespace

    from pixo.service.runtime import PixoServiceRuntime

    empty_trace = SimpleNamespace(trace_events=[])
    assert PixoServiceRuntime._auto_loop_rule_ids(empty_trace) == []
    assert PixoServiceRuntime._auto_loop_rule_ids_by_iteration(empty_trace) == []

    no_hit = SimpleNamespace(trace_events=[
        {"event_type": "meta_extracted", "value": {}},
        {"event_type": "decide", "value": {"iteration": 1, "rule_ids": []}},
        {"event_type": "param_update", "value": 0.0},
        {"event_type": "decide",
         "value": {"iteration": 2, "rule_ids": [], "last_iteration": True}},
    ])
    assert PixoServiceRuntime._auto_loop_rule_ids(no_hit) == []
    assert PixoServiceRuntime._auto_loop_rule_ids_by_iteration(no_hit) == [
        {"iteration": 1, "rule_ids": []},
        {"iteration": 2, "rule_ids": []},
    ]

    early_hit = SimpleNamespace(trace_events=[
        {"event_type": "decide",
         "value": {"iteration": 1, "rule_ids": ["hit", "hit2"]}},
        {"event_type": "decide",
         "value": {"iteration": 2, "rule_ids": [], "last_iteration": True}},
        # 重复命中去重 + 保持首次出现顺序
        {"event_type": "decide",
         "value": {"iteration": 3, "rule_ids": ["hit2", "hit3"]}},
    ])
    assert PixoServiceRuntime._auto_loop_rule_ids(early_hit) == [
        "hit", "hit2", "hit3"]
