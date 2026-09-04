"""t31 θ 上下料单测 (OWN_PIPELINE_STAGE2_DESIGN §2)。

验证: 五组件从现有 configs 加载 (形状/字段名与 src/pixo 加载代码对齐)、
load→save→load 往返**数值逐位**恒等 + 非 θ 字段 doc 值级全等、θ 变异按原
schema 落到对应 JSON 字段、原始 configs 防覆盖守卫、非法参数校验路径、CLI。

权威依据: white_balance._check_warmth_curve / exposure._load_cal_table /
calibration.camera_look_curves / core.rp_ccm.RPCCM.from_dict / core.skin 常数。
"""
from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

_SPECS_PATH = Path(__file__).resolve().parents[2] / "scripts" / "calib" / "theta_io.py"
_spec = importlib.util.spec_from_file_location("theta_io", _SPECS_PATH)
theta_io = importlib.util.module_from_spec(_spec)
# dataclass 处理期会查 sys.modules[cls.__module__], 须先注册再执行
sys.modules["theta_io"] = theta_io
_spec.loader.exec_module(theta_io)


@pytest.fixture()
def theta():
    return theta_io.load_theta()


def _raw(key) -> dict:
    return json.loads(theta_io.DEFAULT_SOURCES[key].read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 初值加载 (与现有 configs 字段名/形状对齐)
# ---------------------------------------------------------------------------

def test_default_sources_exist():
    for key, path in theta_io.DEFAULT_SOURCES.items():
        assert path.is_file(), f"{key} 初值源缺失: {path}"


def test_load_theta_shapes_and_values(theta):
    assert theta.warmth_knots.shape == (5, 4)          # warmth_knots[5]
    assert theta.exposure_table.ndim == 2
    assert theta.exposure_table.shape[1] == 3          # [m_log2, wb_B, ev] 二维表
    assert theta.probe_hi.shape == theta.exposure_table.shape
    assert theta.neutral_default.shape == (2, 7)       # a/b 曲线 7 点
    assert theta.neutral_by_cct.shape[1:] == (2, 7)
    assert theta.neutral_cct.shape[0] == theta.neutral_by_cct.shape[0]
    assert theta.rp_ccm_coeff.shape == (3, 6)          # rp_ccm_coeff[18]
    assert theta.rp_ccm_degree == 2
    assert theta.skin_ellipse.shape == (5,)            # skin_ellipse[5]

    assert theta.warmth_knots[0].tolist() == _raw("warmth_knots")["knots"][0]
    assert (theta.exposure_table[0].tolist()
            == _raw("exposure_table")["cal_table"][0])
    assert theta.rp_ccm_coeff[0, 0] == _raw("rp_ccm_coeff")["matrix"][0][0]
    assert theta.skin_ellipse.tolist() == [
        _raw("skin_ellipse")["constants"][k] for k in
        ("SKIN_OKLAB_A", "SKIN_OKLAB_B", "SKIN_OKLAB_MAJOR",
         "SKIN_OKLAB_MINOR", "SKIN_OKLAB_ANGLE")]
    assert theta.warmth_domain == tuple(
        _raw("warmth_knots")["_domain"]["wb_B"])


# ---------------------------------------------------------------------------
# 验收门: load→save→load 数值逐位恒等 + 非 θ 字段全等
# ---------------------------------------------------------------------------

def test_roundtrip_bitwise_and_doc_equal(theta, tmp_path):
    report = theta_io.roundtrip_check(tmp_path)
    assert report["ok"], report
    for key in theta_io.SOURCE_KEYS:
        assert report[key]["theta_bitwise"] is True, key
        assert report[key]["doc_value_equal"] is True, key
    assert (Path(report["rp_ccm_coeff"]["path"]).parent == tmp_path)


def test_roundtrip_arrays_bitwise(theta, tmp_path):
    out = theta_io.save_theta(theta, tmp_path)
    rt = theta_io.load_theta(out)
    for name in ("warmth_knots", "exposure_table", "rp_ccm_coeff", "skin_ellipse"):
        assert theta_io.bitwise_equal(getattr(theta, name), getattr(rt, name)), name
    assert theta_io.bitwise_equal(theta.neutral_default, rt.neutral_default)
    assert theta_io.bitwise_equal(theta.neutral_cct, rt.neutral_cct)
    assert theta_io.bitwise_equal(theta.neutral_by_cct, rt.neutral_by_cct)
    assert theta.warmth_domain == rt.warmth_domain


def test_resave_idempotent_bytes(tmp_path):
    """二次写回 (含从 calib_out 重载后写回) 字节幂等 —— t32 checkpoint 语义。"""
    first = theta_io.save_theta(theta_io.load_theta(), tmp_path)
    second = theta_io.save_theta(theta_io.load_theta(first), tmp_path)
    for key in theta_io.SOURCE_KEYS:
        assert first[key].read_bytes() == second[key].read_bytes(), key


# ---------------------------------------------------------------------------
# 防覆盖守卫 (对照留档红线)
# ---------------------------------------------------------------------------

def test_save_refuses_original_config_dirs(theta):
    with pytest.raises(ValueError, match="拒绝覆盖原始标定文件"):
        theta_io.save_theta(theta, theta_io.DEFAULT_SOURCES["warmth_knots"].parent)
    with pytest.raises(ValueError, match="拒绝覆盖原始标定文件"):
        theta_io.save_theta(theta, theta_io.DEFAULT_SOURCES["rp_ccm_coeff"].parent)


def test_save_creates_nested_out_dir(theta, tmp_path):
    out = theta_io.save_theta(theta, tmp_path / "a" / "calib_out")
    assert all(p.is_file() for p in out.values())


# ---------------------------------------------------------------------------
# θ 变异 → 原 schema 落盘字段
# ---------------------------------------------------------------------------

def test_mutation_propagates_to_original_schema(theta, tmp_path):
    theta.warmth_knots[0, 1] = 1.2
    theta.exposure_table[3, 2] = 0.75
    theta.neutral_default[0, 2] = -3.5
    theta.neutral_by_cct[0, 1, 4] = 4.5
    theta.rp_ccm_coeff[1, 3] = -0.123
    theta.skin_ellipse[0] = 0.02
    out = theta_io.save_theta(theta, tmp_path)

    assert json.loads(out["warmth_knots"].read_text(encoding="utf-8"))["knots"][0][1] == 1.2
    assert json.loads(out["exposure_table"].read_text(encoding="utf-8"))["cal_table"][3][2] == 0.75
    nd = json.loads(out["neutral_curves"].read_text(encoding="utf-8"))
    assert nd["default"]["neutral_a_curve"][2] == -3.5
    assert nd["by_cct"][0][1]["neutral_b_curve"][4] == 4.5
    assert json.loads(out["rp_ccm_coeff"].read_text(encoding="utf-8"))["matrix"][1][3] == -0.123
    skin = json.loads(out["skin_ellipse"].read_text(encoding="utf-8"))
    assert skin["constants"]["SKIN_OKLAB_A"] == 0.02
    assert skin["new_ellipse_fit"]["center_a"] == 0.02


def test_skin_angle_roundtrip_arbitrary_value(theta, tmp_path):
    """任意优化后的角度: constants 弧度权威逐位往返; angle_deg 写法为
    "4 位小数惯例(无损往返时)" 或 "全精度" 二者之一, 均不影响重载恒等。"""
    angle = 0.3456789
    theta.skin_ellipse[4] = angle
    out = theta_io.save_theta(theta, tmp_path)
    rt = theta_io.load_theta(out)
    assert rt.skin_ellipse[4] == angle
    doc = json.loads(out["skin_ellipse"].read_text(encoding="utf-8"))
    assert doc["constants"]["SKIN_OKLAB_ANGLE"] == angle
    deg = doc["new_ellipse_fit"]["angle_deg"]
    assert deg in (round(math.degrees(angle), 4), math.degrees(angle))


def test_skin_angle_initial_keeps_fit_convention(theta, tmp_path):
    """初值角度经 4 位小数惯例无损往返时沿用惯例写法 (对照 diff 零噪声)。"""
    out = theta_io.save_theta(theta, tmp_path)
    doc = json.loads(out["skin_ellipse"].read_text(encoding="utf-8"))
    assert doc["new_ellipse_fit"]["angle_deg"] == 10.9505
    assert doc["new_ellipse_fit"]["angle_deg"] == _raw("skin_ellipse")[
        "new_ellipse_fit"]["angle_deg"]


def test_non_theta_fields_preserved(theta, tmp_path):
    """meta/_domain/probe_hi 等非 θ 字段原样保留 (对照留档 diff 只见 θ)。"""
    out = theta_io.save_theta(theta, tmp_path)
    for key in theta_io.SOURCE_KEYS:
        assert json.loads(out[key].read_text(encoding="utf-8")) == _raw(key)


# ---------------------------------------------------------------------------
# 非法参数校验 (与运行时加载规则对齐)
# ---------------------------------------------------------------------------

def _mutated_theta(theta, attr, value):
    setattr(theta, attr, value)
    return theta


def test_validate_intercepts_mutated_theta(tmp_path):
    bad = theta_io.load_theta()
    bad.warmth_knots[1, 1] = 1.6                      # 增益越界 [0.5, 1.5]
    with pytest.raises(ValueError, match="增益"):
        theta_io.save_theta(bad, tmp_path)
    bad2 = theta_io.load_theta()
    bad2.skin_ellipse[2] = 0.0                        # 轴长非正
    with pytest.raises(ValueError, match="轴长"):
        theta_io.save_theta(bad2, tmp_path)


@pytest.mark.parametrize("mutate,match", [
    (lambda d: d["warmth_knots"].__setitem__(
        "knots", [[2.0, 1.0, 1.0, 1.0], [1.9, 1.0, 1.0, 1.0]]), "严格递增"),
    (lambda d: d["warmth_knots"].__setitem__(
        "knots", [[1.7, 1.7, 1.0, 1.0], [1.8, 1.0, 1.0, 1.0]]), "增益"),
    (lambda d: d["exposure_table"].__setitem__(
        "cal_table", [[-6.0, 1.7, 1.0], [-5.0, 1.7, 1.0]]), "cal_table"),
    (lambda d: d["exposure_table"]["cal_table"].__setitem__(
        0, [-6.0, 1.7]), "cal_table"),
    (lambda d: d["neutral_curves"]["default"].__setitem__(
        "neutral_b_curve", [0.0, 1.0]), "长度"),
    (lambda d: d["rp_ccm_coeff"].__setitem__(
        "matrix", [[1.0] * 5] * 3), "matrix"),
    (lambda d: d["rp_ccm_coeff"].__setitem__(
        "terms", ["r", "g", "b"]), "项集"),
    (lambda d: d["skin_ellipse"]["constants"].__setitem__(
        "SKIN_OKLAB_MAJOR", 0.0), "轴长"),
])
def test_theta_from_docs_validation(theta, mutate, match):
    docs = {k: _raw(k) for k in theta_io.SOURCE_KEYS}
    mutate(docs)
    with pytest.raises(ValueError, match=match):
        theta_io._theta_from_docs(docs)


def test_load_theta_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        theta_io.load_theta({"skin_ellipse": tmp_path / "nope.json"})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_main_roundtrip(tmp_path, capsys):
    out_dir = tmp_path / "calib_out"
    rc = theta_io.main(["--out", str(out_dir)])
    assert rc == 0
    for name in theta_io.OUT_NAMES.values():
        assert (out_dir / name).is_file()
    assert "PASS" in capsys.readouterr().out
