"""R22 F04/F05 —— 服务层装配单测（风格卡注入 / 场景预设 / 栅栏 400）。

覆盖：
  - F04 卡参数注入：`{__style: <id>}` 经既有 PUT /params 深合并进会话参数
    （canonical 可见、generation+1、trace 留痕），25 张卡全部可注入；
  - F04 栅栏：未知 stage/键、数值域、路径类、枚举 → HTTP 400，且**不落
    部分合并**；既有参数仍可写（正向）；
  - F05 场景预设：6 个 id 全部可注入且 params 真实变化；未知 id →
    400；带 LUT 的预设 → 400（本轮纯 params 覆盖）；
  - 生产会话工厂开启 strict 栅栏；前端场景 id 常量与 scenes.json 同步。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from pixo.know.cards import StyleCard
from pixo.render.pipeline import scene_apply
from pixo.render.web.session import RawPreviewSession
from pixo.service import PixoServiceRuntime, create_app

REPO_ROOT = Path(__file__).resolve().parents[2]
SCENES_JSON = REPO_ROOT / "configs" / "styles" / "scenes.json"
FRONTEND_SCENES = (REPO_ROOT / "frontend" / "src" / "constants"
                   / "scenePresets.ts")


def _session_factory(photo, sid):
    """与生产同构：真实 RawPreviewSession + strict 栅栏（update_params
    不触解码，故无需真实 RAW 语料）。"""
    return RawPreviewSession(photo.path, None, session_id=sid,
                             validate_params=True)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """runtime + photo + session（真会话工厂）+ 场景缓存隔离。"""
    monkeypatch.setenv("PIXO_SCORER_WARMUP", "0")
    monkeypatch.setenv("PIXO_SEGMENTER_WARMUP", "0")
    scene_apply._reset_caches()
    rt = PixoServiceRuntime(profile=object(), work_dir=tmp_path / "exports",
                            session_factory=_session_factory)
    raw = tmp_path / "DSC_R22F04.NEF"
    raw.write_bytes(b"fake-raw")
    photo = rt.create_photo(str(raw))
    session = rt.create_session(photo.photo_id)
    yield rt, photo, session
    scene_apply._reset_caches()


# ---------------------------------------------------------------------------
# F04 卡参数注入
# ---------------------------------------------------------------------------

def test_style_card_injection_merges_params(env):
    """正向：`__style` 装配卡的 params（canonical 可见 + generation+1）。"""
    rt, photo, session = env
    resp = rt.update_params(session.session_id, {"__style": "fujifilm_astia"})

    assert resp["generation"] == 1
    canon = resp["canonical"]
    assert canon["tone"]["contrast"] == 0.14          # 卡的 tone
    assert canon["refine"]["chroma_denoise"] == 0.9   # 卡的 refine
    assert canon["colorcal"]["color_domain"] == "hsv"
    assert "stylize" not in resp["params"] or resp["params"]["stylize"] == {}


def test_all_film_cards_injectable(env):
    """正向：25 张卡逐张可注入（白名单 = 卡库目录 stem）。"""
    rt, _, session = env
    ids = [c["style_id"] for c in StyleCard.from_films_dir()]
    assert len(ids) == 25
    for style_id in ids:
        resp = rt.update_params(session.session_id, {"__style": style_id})
        assert resp["generation"] >= 1
        card = next(c for c in StyleCard.from_films_dir()
                    if c["style_id"] == style_id)
        for stage, bucket in card["params"].items():
            for key, value in bucket.items():
                assert resp["params"][stage][key] == value


def test_style_injection_records_trace(env):
    """留痕：控制键与装配后的 stage 桶各记一条 param_patch trace。"""
    rt, photo, session = env
    rt.update_params(session.session_id, {"__style": "fujifilm_astia"},
                     source="style_panel")
    sm = rt.state_machines[photo.photo_id]
    assert sm.history(param="__style", event_type="param_patch")
    assert sm.history(param="tone", event_type="param_patch")


def test_explicit_patch_overrides_card_value(env):
    """装配语义：卡的 params 为基，同请求内的显式参数优先。"""
    rt, _, session = env
    resp = rt.update_params(session.session_id,
                            {"__style": "fujifilm_astia",
                             "tone": {"contrast": 0.9}})
    assert resp["params"]["tone"]["contrast"] == 0.9
    assert resp["params"]["tone"]["toe"] == 0.18      # 卡的其他键保留
    assert resp["params"]["refine"]["sharpen"] == 0.3


def test_unknown_style_id_400(env):
    """反向：未知卡 id → 400（列出可用 id）。"""
    rt, _, session = env
    with pytest.raises(HTTPException) as exc:
        rt.update_params(session.session_id, {"__style": "nope_card"})
    assert exc.value.status_code == 400
    assert "未知风格卡" in str(exc.value.detail)
    assert "fujifilm_astia" in str(exc.value.detail)


# ---------------------------------------------------------------------------
# F05 场景预设
# ---------------------------------------------------------------------------

SCENE_EXPECT = {
    "portrait": {"tone": {"contrast": 0.08}},
    "landscape": {"tone": {"contrast": 0.18},
                  "colorcal": {"saturation": 0.15}},
    "night": {"tone": {"contrast": 0.06}},
    "street": {"tone": {"contrast": 0.12}},
    "food": {"tone": {"contrast": 0.10},
             "colorcal": {"saturation": 0.10}},
    "mono": {"colorcal": {"saturation": -1.0}},
}


@pytest.mark.parametrize("scene_id", sorted(SCENE_EXPECT))
def test_scene_preset_injection(env, scene_id):
    """正向：6 个场景预设均可注入且 params 按预设变化。"""
    rt, _, session = env
    resp = rt.update_params(session.session_id, {"__scene": scene_id})
    assert resp["generation"] == 1
    for stage, bucket in SCENE_EXPECT[scene_id].items():
        for key, value in bucket.items():
            assert resp["canonical"][stage][key] == value, (scene_id, stage, key)


def test_scene_preset_ids_match_scenes_json(env):
    """F05 白名单 = scenes.json 键集（6 个）。"""
    ids = sorted(json.loads(SCENES_JSON.read_text(encoding="utf-8")))
    assert ids == sorted(SCENE_EXPECT)


def test_unknown_scene_id_400(env):
    rt, _, session = env
    with pytest.raises(HTTPException) as exc:
        rt.update_params(session.session_id, {"__scene": "sunset"})
    assert exc.value.status_code == 400
    assert "未知场景预设" in str(exc.value.detail)
    assert "portrait" in str(exc.value.detail)


def test_scene_and_style_conflict_400(env):
    """反向：两个控制键同提交 = 语义冲突 → 400。"""
    rt, _, session = env
    with pytest.raises(HTTPException) as exc:
        rt.update_params(session.session_id,
                         {"__scene": "night", "__style": "fujifilm_astia"})
    assert exc.value.status_code == 400
    assert "不能同时提交" in str(exc.value.detail)


def test_scene_preset_with_lut_rejected(env, monkeypatch):
    """反向：预设携带非 null lut → 400（本轮无 .cube 资产）。"""
    rt, _, session = env
    monkeypatch.setattr(scene_apply, "_cache",
                        {"portrait": {"params": {"tone": {"contrast": 0.1}},
                                      "lut": "velvia"}})
    with pytest.raises(HTTPException) as exc:
        rt.update_params(session.session_id, {"__scene": "portrait"})
    assert exc.value.status_code == 400
    assert "LUT" in str(exc.value.detail)


# ---------------------------------------------------------------------------
# F04 栅栏（服务层）+ 既有参数正向
# ---------------------------------------------------------------------------

def test_existing_params_still_writable(env):
    """正向：既有前端调整参数经服务层仍可写（栅栏不误拒）。"""
    rt, _, session = env
    resp = rt.update_params(session.session_id, {
        "exposure": {"mode": 0.35},
        "tone": {"highlights": -0.2},
        "calibration": {"red_hue": -30.0},
        "split_tone": {"highlights_sat": 40.0, "shadows_hue": 200.0},
        "region_adjust": {"enabled": True,
                          "regions": {"sky": {"exposure": -0.5}}},
        "hsl": {"color_domain": "oklch",
                "bands": [{"name": "red", "hue_center": 29,
                           "hue_shift": 3.0}]},
    })
    assert resp["generation"] == 1
    assert resp["canonical"]["tone"]["highlights"] == -0.2
    assert resp["canonical"]["hsl"]["color_domain"] == "oklch"
    assert resp["canonical"]["region_adjust"]["regions"]["sky"]["exposure"] == -0.5


BAD_PATCHES = [
    ({"tone": {"contrast": 5.0}}, "越域数值"),
    ({"tone": {"highlights": -20.0}}, "越域负值"),
    ({"s1": {"x": 1}}, "未知 stage"),
    ({"tone": {"nope": 1}}, "未知键"),
    ({"stylize": {"lut_path": "/tmp/x.cube"}}, "lut_path"),
    ({"whitebalance": {"warm_cal_file": "C:/x.json"}}, "路径类键"),
    ({"colorcal": {"neutral_mode": "bogus"}}, "枚举越界"),
]


@pytest.mark.parametrize("patch,why", BAD_PATCHES, ids=[b[1] for b in BAD_PATCHES])
def test_fence_rejects_and_does_not_partially_merge(env, patch, why):
    """反向：非法 patch → 400 且会话参数/generation 零变化。"""
    rt, _, session = env
    before_params = dict(session.params)
    before_gen = session.generation
    with pytest.raises(HTTPException) as exc:
        rt.update_params(session.session_id, patch)
    assert exc.value.status_code == 400
    assert session.generation == before_gen
    assert dict(session.params) == before_params


def test_default_session_factory_enables_strict_fence(tmp_path):
    """生产装配守卫：默认会话工厂必须开 strict 栅栏。"""
    rt = PixoServiceRuntime(profile=object(), work_dir=tmp_path / "exports")
    raw = tmp_path / "DSC_PROD.NEF"
    raw.write_bytes(b"fake-raw")
    photo = rt.create_photo(str(raw))
    session = rt._default_session_factory(photo, "sid-prod")
    assert session.validate_params is True
    with pytest.raises(Exception):
        session.update_params({"s1": {"x": 1}})


# ---------------------------------------------------------------------------
# HTTP 面（FastAPI app）：400 与 200
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(env):
    rt, _, _ = env
    with TestClient(create_app(rt)) as test_client:
        yield test_client


def test_http_put_params_200_and_400(client, env):
    """HTTP 判据：合法（含卡/场景控制键）200；非法一律 400 + 可读 reason。"""
    _, _, session = env
    url = f"/api/sessions/{session.session_id}/params"

    ok_cases = [
        {"tone": {"highlights": -0.3}},
        {"exposure": {"mode": 0.5}},
        {"__style": "fujifilm_astia"},
        {"__scene": "night"},
    ]
    for body in ok_cases:
        resp = client.put(url, json=body)
        assert resp.status_code == 200, (body, resp.text)

    bad_cases = [
        ({"tone": {"contrast": 5}}, "越域"),
        ({"stylize": {"lut_path": "/tmp/x.cube"}}, "lut_path"),
        ({"s1": {"x": 1}}, "未知 stage"),
        ({"tone": {"nope": 1}}, "未知键"),
        ({"__style": "nope"}, "未知卡"),
        ({"__scene": "nope"}, "未知场景"),
        ({"whitebalance": {"warm_cal_file": "C:/x.json"}}, "路径类键"),
    ]
    for body, why in bad_cases:
        resp = client.put(url, json=body)
        assert resp.status_code == 400, (why, body, resp.status_code, resp.text)
        assert resp.json()["detail"]


def test_http_style_apply_visible_in_canonical(client, env):
    """端到端：PUT `__style` → canonical 回读卡的参数（前端「应用」的契约）。"""
    _, _, session = env
    url = f"/api/sessions/{session.session_id}/params"
    resp = client.put(url, json={"__style": "kodak_portra_400"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    card = next(c for c in StyleCard.from_films_dir()
                if c["style_id"] == "kodak_portra_400")
    for stage, bucket in card["params"].items():
        for key, value in bucket.items():
            assert body["canonical"][stage][key] == value, (stage, key)


# ---------------------------------------------------------------------------
# 前端常量与后端注册表同步（防漂移）
# ---------------------------------------------------------------------------

def test_frontend_scene_ids_match_scenes_json():
    """前端场景 id 常量必须与 scenes.json 键集一致（防两侧漂移）。"""
    assert FRONTEND_SCENES.is_file(), f"缺前端常量文件: {FRONTEND_SCENES}"
    text = FRONTEND_SCENES.read_text(encoding="utf-8")
    ids = set(re.findall(r"id:\s*'([a-z_]+)'", text))
    assert ids == set(json.loads(SCENES_JSON.read_text(encoding="utf-8")))
