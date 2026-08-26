"""P3b —— LLM 参数补丁校验器（LLM 建议进系统的唯一闸门）。

补丁 JSON 结构（list[dict]）::

    [{"param": "stage.param", "op": "set|delta", "value": number,
      "reason": str, "rule_ids": [str, ...]}, ...]

校验链（按序短路，拒绝理由确定）：
  1. 结构 schema：param/op/value 必备且类型正确；value 统一
     ``math.isfinite`` 校验（NaN/Infinity/-Infinity 一律拒绝——Python
     json.loads 默认接受这三类字面量，且 NaN 与任何比较均为 False，
     会静默绕过第 4 段越界预检）；
  2. ParamRef：拆解出的 stage 存在于 STAGE_REGISTRY，且 param 在该
     Stage 的 param_schema 中；decide 层扁平方言（如 exposure_ev）
     不接受；
  3. op 白名单：set | delta；
  4. clamp 预检：引擎同款 (min, max) 边界，越界即拒绝而非截断
     （拒绝理由更明确）；delta 在提供 current_params 时按目标值预检；
  5. 锁定拒绝：param 全键或其 stage 名属于 locked_params 时拒绝
     （用户锁定优先于一切建议）。

输出 PatchReview(accepted, rejected)；全部接受才可 apply。
apply_patches(params, review) 是纯函数：deepcopy 后落地——set 直接
赋值、delta 以现值（缺省 0.0）为基，落地值经引擎同款 clamp 截断兜底。
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from pixo.decide.engine import _clamp
from pixo.render import modules as _stage_modules  # noqa: F401 触发 Stage 注册
from pixo.render.pipeline.graph import STAGE_REGISTRY

__all__ = [
    "PatchReview",
    "ALLOWED_OPS",
    "review_patches",
    "apply_patches",
]

ALLOWED_OPS = ("set", "delta")
_REQUIRED_KEYS = ("param", "op", "value")


@dataclass
class PatchReview:
    """补丁批次校验结果分组。

    accepted: 原样通过校验的补丁项列表；
    rejected: [{"item": 原始项, "reason": 拒绝理由}, ...]。
    """

    accepted: list = field(default_factory=list)
    rejected: list = field(default_factory=list)

    @property
    def fully_accepted(self) -> bool:
        """是否全部接受（全部接受才可 apply）。"""
        return bool(self.accepted) and not self.rejected


def _reject(item: Any, reason: str) -> dict[str, Any]:
    return {"item": item, "reason": reason}


def _rng_for(stage: str, name: str):
    """查询 Stage param_schema 的 (min, max)；缺失返回 (None, None)。"""
    cls = STAGE_REGISTRY.get(stage)
    if cls is None:
        return (None, None)
    schema = getattr(cls, "param_schema", None) or {}
    entry = schema.get(name)
    if not isinstance(entry, dict):
        return (None, None)
    return (entry.get("min"), entry.get("max"))


def _validate_one(
    item: Any,
    locked: set,
    current_params: Mapping[str, Any] | None,
) -> str | None:
    """单条校验链；返回 None 表示通过，否则返回拒绝理由。"""
    # 1) 结构 schema
    if not isinstance(item, dict):
        return "补丁项必须是对象"
    for key in _REQUIRED_KEYS:
        if key not in item:
            return f"缺少必需字段 {key}"
    param = item["param"]
    value = item["value"]
    if not isinstance(param, str) or param.count(".") != 1:
        if param == "exposure_ev":
            return ("'exposure_ev' 是 Decide 层扁平方言，补丁协议只接受 "
                    "'stage.param' 形式（如 exposure.target_offset）")
        return f"param {param!r} 不符合 'stage.param' 形态"
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return f"value 必须是数值，实际 {value!r}"
    if not math.isfinite(value):
        # NaN/Infinity：json.loads 默认接受字面量，且 NaN 与任何比较均
        # 为 False，会静默绕过下方越界预检——必须在此显式拒绝
        return (f"value 必须是有限数值（拒绝 NaN/Infinity），"
                f"实际 {value!r}")
    stage, name = param.split(".", 1)

    # 2) ParamRef：stage 存在 + 参数在 schema 中
    cls = STAGE_REGISTRY.get(stage)
    if cls is None:
        return f"stage '{stage}' 未注册于 STAGE_REGISTRY"
    schema = getattr(cls, "param_schema", None) or {}
    if name not in schema:
        return f"参数 '{name}' 不在 stage '{stage}' 的 param_schema 中"

    # 3) op 白名单
    op = item["op"]
    if op not in ALLOWED_OPS:
        return f"op {op!r} 不在白名单 {list(ALLOWED_OPS)}"

    # 4) 引擎同款 clamp 预检（越界拒绝而非截断）
    lo, hi = _rng_for(stage, name)
    target = float(value)
    if op == "delta" and current_params:
        cur_bucket = current_params.get(stage)
        cur = cur_bucket.get(name, 0.0) if isinstance(cur_bucket, dict) else 0.0
        try:
            target = float(cur) + float(value)
        except (TypeError, ValueError):
            return f"delta 现值不可数值化：{stage}.{name}={cur!r}"
        if not math.isfinite(target):
            # 现值被污染（inf/nan）时目标值同样非有限：拒绝而非放行
            return (f"delta 目标值非有限（NaN/Infinity）："
                    f"{stage}.{name}: {cur!r} + {value!r}")
    if lo is not None and target < float(lo):
        return (f"数值越界：目标 {target} 低于 '{param}' 下界 {lo}"
                "（预检拒绝而非截断）")
    if hi is not None and target > float(hi):
        return (f"数值越界：目标 {target} 高于 '{param}' 上界 {hi}"
                "（预检拒绝而非截断）")

    # 5) 用户锁定优先
    if param in locked or stage in locked:
        return f"参数 '{param}' 已被用户锁定（锁定优先）"
    return None


def review_patches(
    patches: Any,
    *,
    locked_params: Sequence[str] | Iterable[str] | None = None,
    current_params: Mapping[str, Any] | None = None,
) -> PatchReview:
    """校验补丁批次，返回 accepted/rejected 分组。

    Args:
        patches: 补丁 JSON（list[dict]；单 dict 亦接受并视为单项批次）。
        locked_params: 用户锁定键（全键如 'tone.brightness' 或整段名
            如 'tone'，命中即拒）。
        current_params: 现行嵌套参数（可选）；提供时 delta 按目标值做
            越界预检。
    """
    if patches is None:
        return PatchReview()
    if isinstance(patches, dict):
        patches = [patches]
    if not isinstance(patches, (list, tuple)):
        return PatchReview(
            rejected=[_reject(patches, "补丁批次必须是 list[dict]")]
        )

    locked = {str(k) for k in (locked_params or [])}
    accepted: list = []
    rejected: list = []
    for item in patches:
        reason = _validate_one(item, locked, current_params)
        if reason is None:
            accepted.append(item)
        else:
            rejected.append(_reject(item, reason))
    return PatchReview(accepted=accepted, rejected=rejected)


def apply_patches(
    params: Mapping[str, Any] | None,
    review: PatchReview,
) -> dict[str, Any]:
    """把已通过校验的补丁落地到嵌套参数（纯函数，返回新 dict）。

    注意：当前无生产调用方（预留——建议态经人工确认后的落地入口）。

    set 直接赋值；delta 以现值（缺省 0.0）为基累加；落地值经引擎同款
    clamp 截断兜底（正常应已被 review 预检拦截越界）。NaN/Infinity 与
    不可数值化的项防御性跳过（clamp 对 NaN 失效——任何比较均为 False
    会原样放行），绝不落地。
    """
    out = copy.deepcopy(dict(params or {}))
    for item in review.accepted:
        stage, name = str(item["param"]).split(".", 1)
        bucket = out.setdefault(stage, {})
        if not isinstance(bucket, dict):
            bucket = out[stage] = {}
        lo, hi = _rng_for(stage, name)
        try:
            if item["op"] == "delta":
                new_value = float(bucket.get(name, 0.0)) + float(item["value"])
            else:
                new_value = float(item["value"])
        except (TypeError, ValueError):
            continue                   # 不可数值化：兜底跳过不落地
        if not math.isfinite(new_value):
            continue                   # NaN/Infinity 兜底：clamp 对其失效
        bucket[name] = _clamp(new_value, (lo, hi))
    return out
