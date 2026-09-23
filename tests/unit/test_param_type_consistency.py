"""param_schema 两端解释器一致性 —— 栅栏 vs 渲染期（契约测试）。

`param_schema` 有两个独立解释器：
  ① 渲染期 `pipeline.graph.Stage._validate_param`（`Stage.p()` 调用）
  ② 栅栏期 `render/web/session._check_value`（HTTP 400 前拦截）

两者是**同一份 schema 的两个实现**，同名 type 分支语义必须逐字对齐。历史上
失配过两次，都以"用户点一下面板就报错"的形式暴露：
  - `float_or_str` 的 Stage 分支只放行 numeric_seq，而栅栏放行任意 list
    ⇒ `hsl.bands = list[dict]` 被渲染期拒绝（2026-09-21 修）；
  - `float_or_str` 的栅栏放行任意 dict，而 Stage 只放行曲线 dict
    ⇒ 栅栏放行、渲染期 500（2026-09-21 修，判据收敛到
    `graph.curve_dict_problem`）。

本文件锁定两条性质：
  **A. 危险方向必须为空**：`栅栏放行 ∧ 渲染期拒绝` = 空集。
     （危险，因为栅栏是 400 的门；它放行就意味着渲染期炸成 500。）
  **B. 常规值两端必须严格一致**：对普通 Python 值（plain），
     `栅栏放行 ⇔ 渲染期放行`。
     允许的例外只有「栅栏更严」这一安全方向，且必须属于已列举的特例类
     （NaN/Inf、numpy 标量、Fraction、`stylize.lut` 的设计性拒绝）。

不覆盖：`None` 语义（= 取消该键覆盖）由两端的**调用方**各自短路
（`Stage.p()` 与 `_check_value` 都在值非 None 时才校验），不属于类型层契约，
故探针里不含 None。
"""
from __future__ import annotations

from fractions import Fraction

import numpy as np
import pytest

from pixo.render.params import PARAM_SCHEMAS
from pixo.render.pipeline.graph import Stage
from pixo.render.web.session import ParamValidationError, _check_value


class _ProbeStage(Stage):
    """仅用于调用 `_validate_param` 的最小 Stage（不注册、不渲染）。"""

    name = "_probe"

    def process(self, ctx):        # pragma: no cover - 永不调用
        raise AssertionError("探针 Stage 不应被渲染")


_STAGE = _ProbeStage()

# 探针 kind：plain = 普通 Python 值（两端必须严格一致）；
#           标注特例 = 已知的「栅栏更严」安全方向（见模块 docstring B）。
PLAIN = "plain"
K_FLOAT_EXTRA = "nan/inf"      # 栅栏查 isfinite，Stage 不查
K_NUMPY = "numpy-scalar"       # 栅栏用 isinstance(…, (int,float)) 不认 numpy 标量
K_FRACTION = "fraction"        # 栅栏不认 Fraction，Stage 用 numbers.Real 认
K_STYLIZE_LUT = "stylize.lut"  # 栅栏设计性拒绝（无 LUT 资产，见 R22 F04）

# 允许出现的「栅栏更严」特例类
ALLOWED_FENCE_ONLY_KINDS = {K_FLOAT_EXTRA, K_NUMPY, K_FRACTION, K_STYLIZE_LUT}


def _numeric_probes(schema, kinds=(PLAIN, K_FLOAT_EXTRA, K_NUMPY, K_FRACTION)):
    """数值类探针：含界内/越界点 + 各特例 kind。"""
    probes = []
    lo, hi = schema.get("min"), schema.get("max")
    base = [0.0, 1.0, -1.0, 100.0, 0, 3]
    if lo is not None:
        base.append(float(lo))
        base.append(float(lo) - 1.0)
    if hi is not None:
        base.append(float(hi))
        base.append(float(hi) + 1.0)
    if lo is not None and hi is not None:
        base.append(float(lo) + 0.5 * (float(hi) - float(lo)))
    for v in base:
        probes.append((v, PLAIN))
    if K_FLOAT_EXTRA in kinds:
        probes += [(float("nan"), K_FLOAT_EXTRA), (float("inf"), K_FLOAT_EXTRA),
                   (float("-inf"), K_FLOAT_EXTRA)]
    if K_NUMPY in kinds:
        probes += [(np.float32(1.0), K_NUMPY), (np.float64(1.0), K_NUMPY),
                   (np.int64(1), K_NUMPY)]
    if K_FRACTION in kinds:
        probes.append((Fraction(1, 2), K_FRACTION))
    # 类型不符的 plain 值（两端都应拒）
    probes += [(True, PLAIN), (False, PLAIN), ("1.0", PLAIN),
               ("auto", PLAIN), ([1.0], PLAIN), ({}, PLAIN), ((), PLAIN)]
    return probes


def _probes_for(stage: str, key: str, schema: dict):
    typ = schema.get("type")
    if typ in ("float", "int"):
        probes = _numeric_probes(schema)
    elif typ == "bool":
        probes = [(True, PLAIN), (False, PLAIN), (1, PLAIN), (0, PLAIN),
                  ("true", PLAIN), ("", PLAIN), ([], PLAIN)]
    elif typ == "str":
        probes = [("", PLAIN), ("x", PLAIN), ("auto", PLAIN), (1, PLAIN),
                  (True, PLAIN), ([], PLAIN), ({}, PLAIN)]
    elif typ == "float_or_str":
        probes = _numeric_probes(schema) + [
            ("", PLAIN), ("auto", PLAIN), ("3:2", PLAIN), ("not json", PLAIN),
            # 数值向量 / 嵌套数值向量（whitebalance.mode、warmth_curve）
            ([1.0, 2.0], PLAIN), ([1.0], PLAIN), ([], PLAIN),
            ([[0.0, 0.0], [1.0, 1.0]], PLAIN), ((), PLAIN),
            # 结构数组（hsl.bands 的 list[dict]）
            ([{"name": "red", "hue_center": 0.0, "width": 0.1}], PLAIN),
            ([{"name": "red"}, {"name": "blue"}], PLAIN),
            ([1.0, "x"], PLAIN),
            # 曲线 dict（合法）
            ({"rgb": [[0.0, 0.0], [1.0, 1.0]]}, PLAIN),
            ({"red": [[0.0, 0.0], [1.0, 1.0]]}, PLAIN),
            ({}, PLAIN),
            # 曲线 dict（非法）—— 两端必须同时拒绝
            ({"foo": [[0.0, 0.0], [1.0, 1.0]]}, PLAIN),
            ({"red": []}, PLAIN),
            ({"red": 1}, PLAIN),
            ({"a": 1}, PLAIN),
            ({"rgb": []}, PLAIN),
        ]
    elif typ == "dict":
        probes = [({}, PLAIN), ({"sky": {"exposure": 0.2}}, PLAIN),
                  ([], PLAIN), ("x", PLAIN), (1, PLAIN), (True, PLAIN)]
    else:                                   # "any" / 未声明
        probes = [(1.0, PLAIN), ("x", PLAIN), ([1.0], PLAIN), ({}, PLAIN),
                  ([], PLAIN)]
    # 枚举：补一个合法取值与一个非法取值
    if "choices" in schema:
        probes = [(schema["choices"][0], PLAIN),
                  ("__not_a_choice__", PLAIN)] + probes
    # stylize.lut 是栅栏侧的设计性特例（先于类型分支拒绝）
    if stage == "stylize" and str(key).lower() == "lut":
        probes = [(v, K_STYLIZE_LUT) for v, _ in probes]
    return probes


def _fence_ok(stage: str, key: str, value, schema: dict) -> bool:
    try:
        _check_value(stage, key, value, schema)
        return True
    except ParamValidationError:
        return False


def _stage_ok(key: str, value, schema: dict) -> bool:
    try:
        _STAGE._validate_param(key, value, schema)
        return True
    except ValueError:
        return False


CASES = [(st, k, key_schema)
         for st, st_schema in sorted(PARAM_SCHEMAS.items())
         for k, key_schema in sorted(st_schema.items())]


def test_probe_matrix_covers_all_schema_keys():
    """前置守卫：探针矩阵覆盖每个 (stage, key, type)。"""
    n = sum(len(PARAM_SCHEMAS[st]) for st in PARAM_SCHEMAS)
    assert len(CASES) == n and n > 100


def test_no_fence_pass_render_reject():
    """性质 A（危险方向必须为空）：栅栏放行 ⇒ 渲染期必须放行。

    违反的后果：HTTP 层 200/400 判断通过，渲染期抛 ValueError-ish ⇒ 前端
    看到 500 或「调了没效果」之外的硬失败。
    """
    bad = []
    for stage, key, schema in CASES:
        for value, kind in _probes_for(stage, key, schema):
            if _fence_ok(stage, key, value, schema) and not _stage_ok(
                    key, value, schema):
                bad.append(f"{stage}.{key} ({schema.get('type')}) = "
                           f"{value!r} [{kind}]")
    assert not bad, ("栅栏放行但渲染期拒绝（危险方向）:\n  " + "\n  ".join(bad))


def test_plain_values_agree_exactly():
    """性质 B：普通 Python 值的两端判定必须一致（例外仅限已列举的特例类）。"""
    bad = []
    for stage, key, schema in CASES:
        for value, kind in _probes_for(stage, key, schema):
            f = _fence_ok(stage, key, value, schema)
            s = _stage_ok(key, value, schema)
            if f == s:
                continue
            if kind == PLAIN:
                bad.append(f"{stage}.{key} ({schema.get('type')}) = "
                           f"{value!r}  栅栏={f} 渲染期={s}")
            else:
                assert kind in ALLOWED_FENCE_ONLY_KINDS, (
                    f"未知特例类 {kind!r}: {stage}.{key} = {value!r}")
                assert not f and s, (
                    f"特例类 {kind!r} 出现在非安全方向: {stage}.{key} = {value!r}")
    assert not bad, ("普通值两端判定不一致:\n  " + "\n  ".join(bad))


def test_stylize_lut_rejected_by_fence_only():
    """stylize.lut 的栅栏拒绝是**设计性**的（仓内 0 个 .cube 资产）。"""
    schema = PARAM_SCHEMAS["stylize"]["lut"]
    assert _fence_ok("stylize", "lut", "any.cube", schema) is False
    assert _stage_ok("lut", "any.cube", schema) is True


def test_unknown_type_passes_both():
    """未声明 type 的 schema 两端都放行（仅走键存在性检查）。"""
    assert _fence_ok("x", "y", {"雪": 1}, {}) is True
    assert _stage_ok("y", {"雪": 1}, {}) is True


def test_curve_dict_judgement_is_shared():
    """曲线 dict 判据唯一同源：栅栏与 Stage 对同一组样本判定一致。"""
    from pixo.render.pipeline.graph import curve_dict_problem, is_curve_dict

    samples = [
        {"rgb": [[0.0, 0.0], [1.0, 1.0]]},
        {"red": [[0.0, 0.0], [1.0, 1.0]]},
        {"green": [[0, 0], [1, 1]], "blue": [[0, 0], [1, 1]]},
        {"luminance": [[0, 0], [1, 0.5]]},
        {},
        {"foo": [[0, 0], [1, 1]]},
        {"red": []},
        {"red": 1},
        {"red": [1, 2, 3]},
    ]
    for v in samples:
        assert is_curve_dict(v) is (curve_dict_problem(v) is None)
    # 两端对 float_or_str 键的结论一致
    schema = {"type": "float_or_str"}
    for v in samples:
        assert (_fence_ok("hsl", "bands", v, schema)
                == _stage_ok("bands", v, schema)), v
