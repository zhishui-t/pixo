"""Pixo Decide —— 确定性规则引擎 (P1-3)。

依据 ``docs/架构设计文档.md`` §9 与 ``docs/PIXO_ARCH_ALIGN_REVIEW.md`` P1-3。

核心职责:
  - YAML/字典规则 schema 求值: priority / condition / action
    (formula / clamp / step_decay / conflict_policy)
  - 优先级链: 用户锁定 > 用户软偏好 > 风格卡片 > 系统默认
  - 参数锁定、冲突消歧、曝光方向限幅
  - 终止判断: 目标达标 / 最大3轮 / 连续两轮改善不足 / 不可修复 / 锁定转人工
  - FINAL_QC 回退: 超标时 Exposure -0.15 EV 一次, 锁定或二次超标转 MANUAL_REVIEW

设计约束:
  - 纯 Python, 不引入新依赖, 无随机。
  - 公式使用受限 ``eval``, 仅暴露 math 常用函数和当前变量。
  - 输出 schema 对齐 §9.3: decision / params / reasons / rule_ids /
    unreliable_regions。
"""
from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Iterable, Optional

__all__ = [
    "DecideError",
    "FormulaError",
    "RuleEngine",
    "decide",
    "evaluate_rules",
    "resolve_conflicts",
    "apply_rules",
    "apply_rules_detailed",
    "check_termination",
    "qc_rollback",
    "load_rules",
]


# ---------------------------------------------------------------------------
# 异常 / 常量
# ---------------------------------------------------------------------------

class DecideError(ValueError):
    """规则引擎配置或求值错误。"""


class FormulaError(DecideError):
    """规则公式无法求值。"""


# 优先级链基础权重; 数值 priority 会直接覆盖这些档位。
_PRIORITY_LEVELS = {
    "user_locked": 10000,
    "user_lock": 10000,
    "user_preference": 9000,
    "style_card": 6000,
    "system_default": 3000,
    "default": 3000,
    "high": 9000,
    "medium": 6000,
    "low": 3000,
}

# 曝光方向限幅阈值 (preview 溢出率)
_EXPOSURE_CLIP_THRESHOLD = 0.025

# FINAL_QC 高光溢出阈值
_QC_OVERFLOW_THRESHOLD = 0.03

# 曝光参数别名
_EXPOSURE_PARAM_NAMES = (
    "exposure",
    "exposure_ev",
    "exposureev",
    "ev",
    "Exposure",
    "Exposure2012",
)


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------

def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _get_path(container: Any, path: str, default: Any = None):
    """从 dict 中按点路径取值。"""
    if isinstance(container, dict) and path in container:
        return container[path]
    if isinstance(path, str) and "." in path:
        cur = container
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur
    return default


def _metric_value(metrics: Optional[dict], name: str):
    """从 metrics 大字典中解析规则引用的指标，支持简单别名。"""
    if not isinstance(metrics, dict) or not name:
        return None
    if name in metrics:
        return metrics[name]
    if name.startswith("metrics."):
        return _metric_value(metrics, name[len("metrics."):])
    nested = metrics.get("metrics")
    if isinstance(nested, dict):
        return _metric_value(nested, name)
    # 支持 preview / final 等分组
    return _get_path(metrics, name)


def _locked_params(context: dict, explicit: Any = None) -> set:
    """从多种输入形式统一获取锁定参数集合。"""
    if explicit is not None:
        return {str(x) for x in _as_list(explicit)}
    raw = (
        context.get("locked_params")
        or context.get("locked")
        or context.get("user_locked")
        or context.get("user_locked_params")
        or context.get("params_locked")
        or []
    )
    return {str(x) for x in _as_list(raw)}


def load_rules(source: Any) -> list[dict]:
    """加载规则。

    支持:
      - dict（单条规则）或 list[dict]（规则列表）;
      - JSON 文件;
      - YAML 文件（若环境中已安装 PyYAML；未安装时抛出 DecideError）。
    """
    if isinstance(source, dict):
        return [source]
    if isinstance(source, list):
        return [r for r in source if isinstance(r, dict)]
    path = Path(str(source))
    if not path.exists():
        raise DecideError(f"规则文件不存在: {path}")
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise DecideError("加载 YAML 规则需要 PyYAML，当前未安装") from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    raise DecideError(f"规则文件格式不符: {path}")


def _rule_priority(rule: dict) -> float:
    """计算规则优先级；显式 priority 优先，其次 level/source 档位。"""
    if "priority" in rule and rule["priority"] is not None:
        raw = rule["priority"]
        if isinstance(raw, (int, float)):
            return float(raw)
        key = str(raw).lower()
        if key in _PRIORITY_LEVELS:
            return float(_PRIORITY_LEVELS[key])
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 0.0
    level = rule.get("level") or rule.get("source") or rule.get("tier") or "default"
    key = str(level).lower()
    return float(_PRIORITY_LEVELS.get(key, 0.0))


def _current_param(params: Optional[dict], param: str) -> float:
    """读取当前参数值，兼容扁平参数名和嵌套 stage 字典。"""
    if not isinstance(params, dict):
        return 0.0
    if param in params:
        try:
            return float(params[param])
        except (TypeError, ValueError):
            return 0.0
    for key, value in params.items():
        if key == param:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0
        if isinstance(value, dict) and param in value:
            try:
                return float(value[param])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _set_param(params: dict, param: str, value: float) -> dict:
    """设置参数（返回新 dict，不修改入参）。"""
    out = copy.deepcopy(params) if params else {}
    out[param] = float(value)
    return out


def _clamp(value: float, rng: Any) -> float:
    if rng is None:
        return float(value)
    try:
        lo, hi = rng[0], rng[1]
    except (TypeError, ValueError, IndexError):
        return float(value)
    if lo is not None and value < float(lo):
        return float(lo)
    if hi is not None and value > float(hi):
        return float(hi)
    return float(value)


# ---------------------------------------------------------------------------
# 条件 / 公式
# ---------------------------------------------------------------------------

def _condition_met(condition: Optional[dict], metrics: Optional[dict]) -> bool:
    """判断规则条件是否满足。条件缺失视为满足。"""
    if not condition:
        return True
    metric = _metric_value(metrics, str(condition.get("metric", "")))
    op = str(condition.get("op", "gt")).lower()
    value = condition.get("value")

    if metric is None:
        # 缺失指标不触发条件（除非显式 eq None 场景未在本期支持）。
        return False

    try:
        mv = float(metric)
        tv = float(value)
    except (TypeError, ValueError):
        # 非数值比较走字符串兼容。
        mv = str(metric)
        tv = str(value)

    if op in ("lt", "<"):
        return mv < tv
    if op in ("le", "<=", "lte"):
        return mv <= tv
    if op in ("gt", ">"):
        return mv > tv
    if op in ("ge", ">=", "gte"):
        return mv >= tv
    if op in ("eq", "==", "="):
        return mv == tv
    if op in ("ne", "!=", "<>"):
        return mv != tv
    if op == "between":
        try:
            lo, hi = float(value[0]), float(value[1])
            return lo <= float(metric) <= hi
        except (TypeError, ValueError, IndexError):
            return False
    if op == "in":
        return metric in _as_list(value)
    raise DecideError(f"未知条件操作符: {op!r}")


_FORMULA_FUNCS = {
    "abs": abs,
    "min": min,
    "max": max,
    "round": round,
    "pow": pow,
    "log": math.log,
    "log2": math.log2,
    "log10": math.log10,
    "exp": math.exp,
    "sqrt": math.sqrt,
    "floor": math.floor,
    "ceil": math.ceil,
}


def _eval_formula(expr: str, variables: dict) -> float:
    """安全求值受限公式表达式。"""
    if not isinstance(expr, str) or not expr.strip():
        raise FormulaError("公式为空")
    namespace = {
        "__builtins__": {},
        **_FORMULA_FUNCS,
        **variables,
    }
    try:
        result = eval(compile(expr, "<pixo_decide_formula>", "eval"), namespace, {})
        return float(result)
    except Exception as exc:
        raise FormulaError(f"公式求值失败: {expr!r} ({exc})") from exc


def _resolve_target(rule: dict, context: dict, condition: Optional[dict]) -> Optional[float]:
    """确定公式中的 target 变量。"""
    action = rule.get("action", {})
    if action.get("target") is not None:
        try:
            return float(action["target"])
        except (TypeError, ValueError):
            return None
    targets = context.get("targets") or {}
    metric = None
    if condition and condition.get("metric"):
        metric = str(condition["metric"])
    if isinstance(targets, dict) and metric and metric in targets:
        tv = targets[metric]
        if isinstance(tv, dict):
            tv = tv.get("value", tv.get("target"))
        try:
            return float(tv)
        except (TypeError, ValueError):
            return None
    if isinstance(targets, list):
        for t in targets:
            if isinstance(t, dict) and t.get("metric") == metric:
                try:
                    return float(t.get("value", t.get("target")))
                except (TypeError, ValueError):
                    return None
    # 回退: 条件 value 作为 target
    if condition and condition.get("value") is not None:
        try:
            return float(condition["value"])
        except (TypeError, ValueError):
            return None
    return None


def _compute_action(
    rule: dict,
    metrics: Optional[dict],
    params: Optional[dict],
    context: dict,
    iteration: int,
) -> dict:
    """计算单条规则产生的参数新值。"""
    action = rule.get("action") or {}
    param = action.get("param")
    if not param:
        raise DecideError(f"规则 {rule.get('rule_id')!r} 缺少 action.param")

    param_current = _current_param(params, param)
    condition = rule.get("condition")
    target = _resolve_target(rule, context, condition)
    metric_current = None
    if condition and condition.get("metric"):
        metric_current = _metric_value(metrics, str(condition["metric"]))
    # 公式中的 current 优先取条件指标当前值（文档示例语义），
    # 参数当前值通过 param_current 传递，供 delta 模式累加。
    formula_current = float(metric_current) if metric_current is not None else param_current
    variables = {
        "current": formula_current,
        "param_current": param_current,
        "param": param_current,
        "metric": metric_current,
        "metric_value": metric_current,
        "target": target if target is not None else formula_current,
        "value": action.get("value", 0),
        **dict(metrics or {}),
        **dict(context.get("targets") or {}),
    }

    step_decay = action.get("step_decay")
    fraction = 1.0
    if step_decay is not None:
        try:
            fraction = float(step_decay) ** max(0, int(iteration) - 1)
        except (TypeError, ValueError, OverflowError):
            fraction = 1.0

    formula = action.get("formula")
    mode = str(action.get("mode", "")).lower()
    if not mode:
        mode = "delta" if formula else "set"

    if formula:
        raw = _eval_formula(formula, variables)
    else:
        raw = float(action.get("value", 0) or 0)

    if mode == "delta":
        new_value = param_current + raw * fraction
    elif mode == "set":
        # set 模式默认不按 iteration 缩放；如显式 step_decay，可按比例收敛。
        new_value = raw * fraction if step_decay is not None else raw
    else:
        raise DecideError(f"未知 action.mode: {mode!r}")

    rng = action.get("clamp")
    new_value = _clamp(new_value, rng)

    return {
        "param": param,
        "current": param_current,
        "metric_current": metric_current,
        "raw_value": raw,
        "applied_fraction": fraction,
        "new_value": new_value,
        "mode": mode,
    }


# ---------------------------------------------------------------------------
# 规则求值 / 冲突消歧 / 应用
# ---------------------------------------------------------------------------

def _format_reason(rule: dict, computed: dict) -> str:
    rule_id = rule.get("rule_id", "unknown")
    param = computed["param"]
    value = computed["new_value"]
    condition = rule.get("condition") or {}
    metric = condition.get("metric")
    if metric:
        metric_value = computed.get("metric_current")
        op = condition.get("op")
        threshold = condition.get("value")
        return (
            f"{metric}={metric_value} {op} {threshold} -> "
            f"{rule_id}: {param} -> {value:.4f}"
        )
    return f"规则 {rule_id}: {param} -> {value:.4f}"


def evaluate_rules(
    rules: Iterable[dict],
    metrics: Optional[dict],
    *,
    context: Optional[dict] = None,
    params: Optional[dict] = None,
    iteration: int = 1,
    locked_params: Optional[Iterable[str]] = None,
) -> list[dict]:
    """求值所有命中条件的规则（未做同参冲突消歧）。"""
    context = context or {}
    params = params or {}
    locked = _locked_params(context, locked_params)
    results: list[dict] = []

    for rule in rules or []:
        if not isinstance(rule, dict):
            continue
        if rule.get("enabled") is False:
            continue
        if not _condition_met(rule.get("condition"), metrics):
            continue
        action = rule.get("action") or {}
        param = action.get("param")
        if param and str(param) in locked:
            continue
        try:
            computed = _compute_action(rule, metrics, params, context, iteration)
        except DecideError:
            # 单条规则失败不拖垮整轮；由上层决定是否记录。
            continue
        results.append({
            "rule_id": rule.get("rule_id", "unknown"),
            "priority": _rule_priority(rule),
            "param": computed["param"],
            "current": computed["current"],
            "raw_value": computed["raw_value"],
            "applied_fraction": computed["applied_fraction"],
            "value": computed["new_value"],
            "reason": _format_reason(rule, computed),
            "rule": rule,
        })
    return results


def resolve_conflicts(results: Iterable[dict]) -> list[dict]:
    """同 action.param 冲突消歧：高优先级胜出；同优先级保留先出现者。"""
    by_param: dict[str, dict] = {}
    for res in results:
        param = res.get("param")
        if not param:
            continue
        existing = by_param.get(param)
        if existing is None or res["priority"] > existing["priority"]:
            by_param[param] = res
    return list(by_param.values())


def _exposure_limiter_active(context: dict) -> bool:
    for key in (
        "preview_overflow_ratio",
        "preview_clip_ratio",
        "clip_ratio",
        "overflow_ratio",
    ):
        value = context.get(key)
        if value is not None:
            try:
                return float(value) >= _EXPOSURE_CLIP_THRESHOLD
            except (TypeError, ValueError):
                continue
    return False


def _is_exposure_param(param: str) -> bool:
    low = str(param).lower()
    return any(name.lower() == low for name in _EXPOSURE_PARAM_NAMES) or "exposure" in low


def _apply_exposure_limiter(param: str, new_value: float, current: float, context: dict):
    """preview 溢出率 ≥2.5% 时，Exposure 只允许负向/保持。"""
    if _exposure_limiter_active(context) and _is_exposure_param(param):
        if new_value > current:
            return current, True
    return new_value, False


def _apply_rules_internal(
    rules: Iterable[dict],
    metrics: Optional[dict],
    params: Optional[dict],
    context: dict,
    iteration: int = 1,
    locked_params: Optional[Iterable[str]] = None,
) -> tuple[dict, list[dict]]:
    results = evaluate_rules(
        rules,
        metrics,
        context=context,
        params=params,
        iteration=iteration,
        locked_params=locked_params,
    )
    selected = resolve_conflicts(results)
    out = copy.deepcopy(params) if params else {}
    applied: list[dict] = []

    for res in selected:
        param = res["param"]
        current = _current_param(out, param)
        new_value, limited = _apply_exposure_limiter(
            param, float(res["value"]), current, context
        )
        out = _set_param(out, param, new_value)
        applied.append({
            **res,
            "value": new_value,
            "limited_by_exposure": limited,
        })
    return out, applied


def apply_rules(
    rules: Iterable[dict],
    metrics: Optional[dict],
    params: Optional[dict],
    *,
    context: Optional[dict] = None,
    iteration: int = 1,
    locked_params: Optional[Iterable[str]] = None,
) -> dict:
    """应用规则并返回新参数 dict（单入口，供上层直接使用）。"""
    context = context or {}
    out, _ = _apply_rules_internal(
        rules, metrics, params, context,
        iteration=iteration, locked_params=locked_params,
    )
    return out


def apply_rules_detailed(
    rules: Iterable[dict],
    metrics: Optional[dict],
    params: Optional[dict],
    *,
    context: Optional[dict] = None,
    iteration: int = 1,
    locked_params: Optional[Iterable[str]] = None,
) -> tuple[dict, list[dict]]:
    """应用规则，返回 (新参数 dict, 已应用规则详情)。"""
    context = context or {}
    return _apply_rules_internal(
        rules, metrics, params, context,
        iteration=iteration, locked_params=locked_params,
    )


# ---------------------------------------------------------------------------
# 终止判断
# ---------------------------------------------------------------------------

def _normalize_targets(context: dict) -> list[dict]:
    targets = context.get("targets") or []
    if isinstance(targets, dict):
        out = []
        for metric, spec in targets.items():
            if isinstance(spec, dict):
                out.append({"metric": metric, **spec})
            else:
                out.append({
                    "metric": metric,
                    "value": spec,
                    "tolerance": (context.get("tolerances") or {}).get(metric, 0.0),
                })
        return out
    return [t for t in targets if isinstance(t, dict)]


def _target_met(target: dict, metrics: Optional[dict]) -> bool:
    metric = target.get("metric")
    value = _metric_value(metrics, str(metric))
    if value is None:
        return False
    try:
        mv = float(value)
        tv = float(target.get("value", target.get("target")))
    except (TypeError, ValueError):
        return False
    tolerance = float(target.get("tolerance", 0.0) or 0.0)
    op = str(target.get("op", "")).lower()
    if op in ("le", "<=", "max"):
        return mv <= tv + tolerance
    if op in ("ge", ">=", "min"):
        return mv >= tv - tolerance
    return abs(mv - tv) <= tolerance


def check_termination(context: dict) -> dict:
    """判断是否终止迭代，返回 is_stop / decision / reason。"""
    context = context or {}
    metrics = context.get("metrics") or {}
    targets = _normalize_targets(context)
    unreliable = context.get("unreliable_regions") or context.get("unreliable") or []

    if unreliable and context.get("manual_on_unreliable", True):
        return {
            "should_stop": True,
            "decision": "manual_review",
            "reason": "关键区域不可靠，无法执行确定性规则",
            "reason_code": "unreliable",
        }

    if context.get("irreparable") or context.get("unrepairable"):
        return {
            "should_stop": True,
            "decision": "manual_review",
            "reason": "检测到不可修复信号",
            "reason_code": "irreparable",
        }

    locked = _locked_params(context)
    target_params = context.get("target_params") or []
    if locked and target_params:
        # 锁定参数涉及目标且目标未达成 -> 无法继续自动修正
        blocked = [p for p in _as_list(target_params) if str(p) in locked]
        if blocked and targets and not all(_target_met(t, metrics) for t in targets):
            return {
                "should_stop": True,
                "decision": "manual_review",
                "reason": f"用户锁定参数 {blocked} 导致无法自动达标",
                "reason_code": "user_locked_unmet",
            }

    if context.get("targets_reached") or context.get("goal_reached"):
        return {
            "should_stop": True,
            "decision": "stopped",
            "reason": "目标已达标",
            "reason_code": "targets_met",
        }

    if targets and all(_target_met(t, metrics) for t in targets):
        return {
            "should_stop": True,
            "decision": "stopped",
            "reason": "所有目标指标进入容差范围",
            "reason_code": "targets_met",
        }

    max_iterations = int(context.get("max_iterations", 3))
    iteration = int(context.get("iteration", 1))
    if iteration >= max_iterations:
        return {
            "should_stop": True,
            "decision": "stopped",
            "reason": f"达到最大迭代轮数 ({max_iterations})",
            "reason_code": "max_iterations",
        }

    threshold = float(context.get("improvement_threshold", 0.1))
    history = context.get("improvement_history") or []
    if len(history) >= 2:
        try:
            last_two = [float(v) for v in history[-2:]]
            if all(v < threshold for v in last_two):
                return {
                    "should_stop": True,
                    "decision": "stopped",
                    "reason": "连续两轮改善低于阈值",
                    "reason_code": "low_improvement",
                }
        except (TypeError, ValueError):
            pass
    prev = context.get("previous_improvement")
    cur = context.get("improvement")
    if prev is not None and cur is not None:
        try:
            if float(prev) < threshold and float(cur) < threshold:
                return {
                    "should_stop": True,
                    "decision": "stopped",
                    "reason": "连续两轮改善低于阈值",
                    "reason_code": "low_improvement",
                }
        except (TypeError, ValueError):
            pass

    return {
        "should_stop": False,
        "decision": "adjust_and_continue",
        "reason": None,
        "reason_code": None,
    }


# ---------------------------------------------------------------------------
# FINAL_QC 回退
# ---------------------------------------------------------------------------

def _find_exposure_param(params: dict) -> Optional[str]:
    if not isinstance(params, dict):
        return None
    # 优先普通扁平键
    for name in _EXPOSURE_PARAM_NAMES:
        if name in params:
            return name
    for key in params:
        if _is_exposure_param(str(key)):
            return key
    return None


def qc_rollback(context: dict) -> dict:
    """FINAL_QC 高光溢出超标时执行一次 Exposure -0.15 EV 回退。

    规则 ID: ``qc_rollback_rule``；锁定 Exposure 或二次超标转 MANUAL_REVIEW。
    """
    context = context or {}
    ratio = (
        context.get("qc_overflow_ratio")
        or context.get("final_qc_overflow_ratio")
        or context.get("final_qc_overflow")
        or 0.0
    )
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        ratio = 0.0

    params = copy.deepcopy(context.get("params") or {})
    locked = _locked_params(context)
    unreliable = context.get("unreliable_regions") or context.get("unreliable") or []

    if ratio <= _QC_OVERFLOW_THRESHOLD:
        return {
            "decision": "adjust_and_continue",
            "params": params,
            "reasons": [],
            "rule_ids": [],
            "unreliable_regions": list(unreliable),
        }

    count = int(context.get("qc_rollback_count", 0) or 0)
    if count >= 1:
        return {
            "decision": "manual_review",
            "params": params,
            "reasons": ["FINAL_QC 二次超标，停止自动回退"],
            "rule_ids": [],
            "unreliable_regions": list(unreliable),
        }

    exposure_param = _find_exposure_param(params)
    if exposure_param is None:
        exposure_param = "Exposure"
    if exposure_param in locked:
        return {
            "decision": "manual_review",
            "params": params,
            "reasons": ["用户锁定 Exposure，无法执行 QC 回退"],
            "rule_ids": ["qc_rollback_rule"],
            "unreliable_regions": list(unreliable),
        }

    current = _current_param(params, exposure_param)
    new_value = current - 0.15
    params = _set_param(params, exposure_param, new_value)
    return {
        "decision": "rollback",
        "params": params,
        "reasons": [f"FINAL_QC 高光溢出 {ratio:.2%} > 3%，Exposure -0.15 EV"],
        "rule_ids": ["qc_rollback_rule"],
        "unreliable_regions": list(unreliable),
        "rollback_applied": True,
        "qc_rollback_count": count + 1,
    }


# ---------------------------------------------------------------------------
# 顶层决策
# ---------------------------------------------------------------------------

def _output(decision: str, params: dict, reasons: list, rule_ids: list,
            context: dict) -> dict:
    return {
        "decision": decision,
        "params": params,
        "reasons": reasons,
        "rule_ids": rule_ids,
        "unreliable_regions": list(
            context.get("unreliable_regions") or context.get("unreliable") or []
        ),
    }


def _style_card_rules(context: dict) -> list[dict]:
    """从 context["style_cards"] 生成风格卡片建议规则。

    风格卡片优先级为 6000（style_card），低于用户锁定（10000）与
    用户软偏好（9000），满足 P2-6 的约束。
    """
    raw = context.get("style_cards") or []
    if not raw:
        return []
    try:
        from pixo.know.cards import build_style_card_rules
        return build_style_card_rules(raw)
    except Exception:
        # 知识层缺失/异常不应阻断 Decide，回退为空规则。
        return []


def decide(context: Optional[dict], rules: Optional[Iterable[dict]] = None) -> dict:
    """执行一轮确定性 Decide 决策。

    Args:
        context: 输入上下文，可含 metrics / params / rules / targets /
            style_cards / iteration / locked_params / preview_overflow_ratio 等。
        rules: 显式规则列表；缺省读 ``context["rules"]``，并追加
            ``context["style_cards"]`` 生成的风格卡片建议。
    """
    context = context or {}
    rules = list(rules) if rules is not None else list(context.get("rules") or [])
    rules.extend(_style_card_rules(context))

    # FINAL_QC 回退优先
    qc_value = (
        context.get("qc_overflow_ratio")
        or context.get("final_qc_overflow_ratio")
        or context.get("final_qc_overflow")
    )
    if qc_value is not None:
        try:
            if float(qc_value) > _QC_OVERFLOW_THRESHOLD:
                return qc_rollback(context)
        except (TypeError, ValueError):
            pass

    term = check_termination(context)
    if term["should_stop"]:
        return _output(
            term["decision"],
            copy.deepcopy(context.get("params") or {}),
            [term["reason"]] if term["reason"] else [],
            [],
            context,
        )

    params, applied = _apply_rules_internal(
        rules,
        context.get("metrics") or {},
        context.get("params") or {},
        context,
        iteration=int(context.get("iteration", 1)),
    )
    reasons = [a["reason"] for a in applied]
    rule_ids = [a["rule_id"] for a in applied]
    return _output("adjust_and_continue", params, reasons, rule_ids, context)


# ---------------------------------------------------------------------------
# 面向对象门面
# ---------------------------------------------------------------------------

class RuleEngine:
    """Pixo Decide 规则引擎门面。"""

    def __init__(self, rules: Optional[Iterable[dict]] = None):
        self.rules = list(rules or [])

    def decide(self, context: dict) -> dict:
        return decide(context, self.rules)

    def evaluate(self, metrics: dict, **kwargs) -> list[dict]:
        return evaluate_rules(self.rules, metrics, **kwargs)

    def apply(self, params: dict, metrics: dict, **kwargs) -> dict:
        return apply_rules(self.rules, metrics, params, **kwargs)
