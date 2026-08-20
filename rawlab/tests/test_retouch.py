"""T3 单元测试: RetouchAgent 调度器 (rawlab/engine/retouch.py)。

覆盖 (验收 / 任务 T3):
  - retouch(): 首轮分析一次, 场景解析 (auto / 显式), 结果字段齐全, JPEG 落盘
  - apply_feedback(): 反馈轮复用分析 (检测次数=1), 每 3 轮强制重分析
  - 参数累计正确 (两次 "更亮一点" = ev 步长 × 阻尼 累积)
  - 会话 JSON 可存/载 (编辑序列 / 每轮参数 / scene / 产物路径)
  - replay: 重放编辑序列位精确同图 (断言确定性)
  - detect=False 跳过检测

约定: probe 渲染与最终渲染分别 monkeypatch RetouchAgent._render_probe /
_render_final 成合成小图 (免真实 NEF); vision_report 内部另有 detect_subjects
绑定 (import 期), 故另行 monkeypatch build_vision_report 以隔离检测计数。

运行: python -m pytest rawlab/tests/test_retouch.py -q
"""
from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

import rawlab.engine.retouch as retouch_mod
from rawlab import vision_bridge
from rawlab.engine.retouch import RetouchAgent

# 固定检测框 (monkeypatch 返回)
_FIXED_SUBJ = [[0.0, 0.0, 0.5, 1.0], [0.6, 0.0, 1.0, 0.4]]
_FIXED_FACES = [[0.25, 0.0, 0.75, 0.5]]


def _green_probe(h=16, w=16):
    """合成绿图 probe → classify_scene 命中 landscape。"""
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 0] = 40
    img[:, :, 1] = 180
    img[:, :, 2] = 40
    return img


def _patch_agent(monkeypatch, tmp_path, *, out_dir=None, probe=None, detect_fake=True):
    """统一打桩: 检测计数 + 固定报告 + 合成 probe/final, 返回 (agent, detect_calls)。"""
    calls = []

    def fake_detect(bgr8):
        assert bgr8.dtype == np.uint8 and bgr8.shape[2] == 3
        calls.append(np.asarray(bgr8).copy())
        return (_FIXED_SUBJ, _FIXED_FACES)

    if detect_fake:
        monkeypatch.setattr(vision_bridge, "detect_subjects", fake_detect)

    # 隔离 vision_report 内部对 detect_subjects 的 (import 期绑定的) 调用
    monkeypatch.setattr(
        retouch_mod, "build_vision_report",
        lambda bgr8, subject_boxes=None, face_boxes=None:
            {"subject": {"count": 1, "persons": 1, "items": []},
             "tone": {"brightness": float(np.asarray(bgr8).mean())}})

    if probe is None:
        probe = np.zeros((16, 16, 3), dtype=np.uint8)
    monkeypatch.setattr(RetouchAgent, "_render_probe",
                        lambda self, raw_path: np.asarray(probe).copy())

    def fake_final(self, params):
        # 让输出像素编码 ev, 保证「参数一致 → 图一致」可被位精确比较
        ev = params.get("exposure", {}).get("mode")
        val = 100 + int(round((float(ev) if ev is not None else 0.0) * 100))
        return np.full((8, 8, 3), min(max(val, 0), 255), dtype=np.uint8)

    monkeypatch.setattr(RetouchAgent, "_render_final", fake_final)

    agent = RetouchAgent(prof=None, out_dir=out_dir)
    return agent, calls


# ---------------------------------------------------------------------------
# retouch() 首轮
# ---------------------------------------------------------------------------

def test_retouch_initial_round_and_fields(monkeypatch, tmp_path):
    agent, calls = _patch_agent(monkeypatch, tmp_path, out_dir=tmp_path / "out")
    r = agent.retouch("test.nef", scene="portrait")

    assert r.round_idx == 0
    assert r.scene == "portrait"
    assert r.subject_boxes == _FIXED_SUBJ
    assert r.ev is None
    assert isinstance(r.report, dict)
    assert r.params["tone"]["contrast"] == 0.08  # portrait 预设
    assert r.image_path.exists()
    assert r.image_path.name == "test_r0.jpg"
    assert len(calls) == 1  # 首轮检测一次


def test_retouch_scene_auto_resolves_from_analysis(monkeypatch, tmp_path):
    agent, _ = _patch_agent(monkeypatch, tmp_path, out_dir=tmp_path / "out",
                            probe=_green_probe())
    r = agent.retouch("test.nef", scene="auto")
    # 绿图 → classify_scene 命中 landscape
    assert r.scene == "landscape"
    assert r.params["tone"]["contrast"] == 0.18


def test_retouch_explicit_scene_overrides_analysis(monkeypatch, tmp_path):
    agent, _ = _patch_agent(monkeypatch, tmp_path, out_dir=tmp_path / "out",
                            probe=_green_probe())
    r = agent.retouch("test.nef", scene="mono")
    assert r.scene == "mono"
    assert r.params["colorcal"]["saturation"] == -1.0


def test_retouch_detect_false_skips_detection(monkeypatch, tmp_path):
    agent, calls = _patch_agent(monkeypatch, tmp_path, out_dir=tmp_path / "out",
                                detect_fake=False)
    agent.detect = False
    r = agent.retouch("test.nef", scene="portrait")
    assert r.subject_boxes == []
    assert calls == []


# ---------------------------------------------------------------------------
# apply_feedback(): 复用分析 + 每 3 轮重分析 + 参数累计
# ---------------------------------------------------------------------------

def test_feedback_reuses_analysis_then_reanalyzes_every_3(monkeypatch, tmp_path):
    agent, calls = _patch_agent(monkeypatch, tmp_path, out_dir=tmp_path / "out")
    agent.retouch("test.nef", scene="portrait")
    assert len(calls) == 1

    agent.apply_feedback("更亮一点")
    assert len(calls) == 1, "反馈轮应复用首轮分析, 不重检"
    agent.apply_feedback("更亮一点")
    assert len(calls) == 1

    agent.apply_feedback("更亮一点")  # round 3 → 强制重分析
    assert len(calls) == 2, "第 3 轮应强制重分析"
    agent.apply_feedback("更亮一点")  # round 4 → 复用
    assert len(calls) == 2


def test_feedback_ev_accumulates(monkeypatch, tmp_path):
    agent, _ = _patch_agent(monkeypatch, tmp_path, out_dir=tmp_path / "out")
    r0 = agent.retouch("test.nef", scene="portrait")
    assert r0.ev is None

    r1 = agent.apply_feedback("更亮一点")
    assert r1.ev == pytest.approx(0.3 * 0.7)  # 步长 × 阻尼
    assert r1.round_idx == 1

    r2 = agent.apply_feedback("更亮一点")
    assert r2.ev == pytest.approx(2 * 0.3 * 0.7)
    assert r2.round_idx == 2

    # 输出文件名轮次递增
    assert r0.image_path.name == "test_r0.jpg"
    assert r1.image_path.name == "test_r1.jpg"
    assert r2.image_path.name == "test_r2.jpg"


def test_feedback_unknown_fragment_raises(monkeypatch, tmp_path):
    agent, _ = _patch_agent(monkeypatch, tmp_path, out_dir=tmp_path / "out")
    agent.retouch("test.nef", scene="portrait")
    with pytest.raises(Exception):
        agent.apply_feedback("量子态渲染")


def test_apply_feedback_before_retouch_raises(monkeypatch, tmp_path):
    agent, _ = _patch_agent(monkeypatch, tmp_path, out_dir=tmp_path / "out")
    with pytest.raises(RuntimeError):
        agent.apply_feedback("更亮一点")


# ---------------------------------------------------------------------------
# 会话 JSON 导出 / 载入
# ---------------------------------------------------------------------------

def test_session_json_save_and_load(monkeypatch, tmp_path):
    agent, _ = _patch_agent(monkeypatch, tmp_path, out_dir=tmp_path / "out")
    agent.retouch("test.nef", scene="portrait")
    agent.apply_feedback("更亮一点")
    agent.apply_feedback("更亮一点")

    data = agent.to_session_json()
    assert data["raw_path"].endswith("test.nef")
    assert data["scene"] == "portrait"
    assert data["feedback"] == ["更亮一点", "更亮一点"]
    assert len(data["rounds"]) == 3
    assert [r["round_idx"] for r in data["rounds"]] == [0, 1, 2]
    assert data["final_params"]["exposure"]["mode"] == pytest.approx(0.42)
    assert data["final_image"].endswith("test_r2.jpg")

    path = tmp_path / "session.json"
    saved = agent.save_session(path)
    assert saved.exists()
    loaded = json.loads(saved.read_text(encoding="utf-8"))
    assert loaded["final_params"]["exposure"]["mode"] == pytest.approx(0.42)
    assert loaded["feedback"] == ["更亮一点", "更亮一点"]


# ---------------------------------------------------------------------------
# replay: 位精确同图
# ---------------------------------------------------------------------------

def test_replay_bit_exact(monkeypatch, tmp_path):
    orig_dir = tmp_path / "orig"
    replay_dir = tmp_path / "replay"

    agent, _ = _patch_agent(monkeypatch, tmp_path, out_dir=orig_dir)
    agent.retouch("test.nef", scene="portrait")
    agent.apply_feedback("更亮一点")
    agent.apply_feedback("更亮一点")
    session_path = tmp_path / "session.json"
    agent.save_session(session_path)

    r2 = RetouchAgent.replay(session_path, prof=None, out_dir=replay_dir)

    assert r2.round_idx == 2
    assert r2.scene == "portrait"
    assert r2.ev == pytest.approx(0.42)
    assert r2.params == agent._params

    # 位精确: 原会话与回放最终图逐字节一致
    orig_jpg = orig_dir / "test_r2.jpg"
    replay_jpg = replay_dir / "test_r2.jpg"
    assert orig_jpg.read_bytes() == replay_jpg.read_bytes()

    # 像素级一致 (双重确认)
    a = cv2.imread(str(orig_jpg))
    b = cv2.imread(str(replay_jpg))
    assert a is not None and b is not None
    assert np.array_equal(a, b)


def test_replay_accepts_dict(monkeypatch, tmp_path):
    agent, _ = _patch_agent(monkeypatch, tmp_path, out_dir=tmp_path / "orig")
    agent.retouch("test.nef", scene="landscape")
    agent.apply_feedback("锐一点")

    data = agent.to_session_json()
    r2 = RetouchAgent.replay(data, prof=None, out_dir=tmp_path / "replay")
    assert r2.scene == "landscape"
    assert r2.round_idx == 1
    assert r2.params["refine"]["sharpen"] == pytest.approx(0.05 * 0.7)
