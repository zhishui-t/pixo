"""t21 审核盲点 A1/A2 收口 e2e：oklch 参数经 preview 接口往返渲染无错。

链路真实性：真实 FastAPI app + 真实 RawPreviewSession + 真实默认 12 级管线
（仓库内置 Nikon Z5_2 DCP），仅 RAW 解码层按 tests/integration/
test_preview_session.py 既有惯例打桩（合成彩色图 + 常量 camera_wb）。

接口字段对齐 t20 前端通道（frontend/src/api/client.ts）：
  POST /api/photos                         {path}
  POST /api/photos/{pid}/sessions
  PUT  /api/sessions/{sid}/params          body={...patch, __source}
  GET  /api/sessions/{sid}/canonical       深合并不滤键的回读
  GET  /api/sessions/{sid}/image           ?long_edge&fmt&quality&gen

覆盖:
  - oklch patch（hsl/split_tone color_domain）经 params→canonical→image
    全链往返，渲染无错且出图随域切换变化;
  - 非法 color_domain 经接口可见地失败（R22 F04 起：PUT /params 参数栅栏
    派生自 param_schema → 直接 400；渲染期 Stage 校验为第二道兜底）;
  - oklch_demo 胶片卡整卡 params 走同一通道渲染无错（盲点 A1 收口）。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import pixo.render.core.io as core_io
import pixo.render.web.session as sess_mod
from pixo.know.cards import StyleCard
from pixo.service import PixoServiceRuntime, create_app

ROOT = Path(__file__).resolve().parents[2]
_DCP = ROOT / "resources" / "dcp" / "Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp"

_OKLCH_PATCH = {
    "hsl": {"enabled": True, "smooth": 0.8, "color_domain": "oklch"},
    "split_tone": {
        "enabled": True, "color_domain": "oklch",
        "highlights_hue": 55, "highlights_sat": 8,
        "shadows_hue": 264, "shadows_sat": 6,
        "balance": 0.55, "strength": 0.5,
    },
}
_HSV_PATCH = {
    "hsl": {"color_domain": "hsv"},
    "split_tone": {"color_domain": "hsv"},
}


class _FakeRaw:
    def close(self):
        pass


def _synthetic_decode(raw=None, raw_path=None):
    """彩色渐变图（LINEAR_CAM 域入口，float [0,1]），覆盖多色相扇区。"""
    h = w = 64
    y, x = np.mgrid[0:h, 0:w]
    t = x / max(w - 1, 1)
    r = 0.15 + 0.7 * t
    g = 0.15 + 0.7 * (1.0 - t)
    b = 0.15 + 0.6 * np.abs(0.5 - t) * 2
    img = np.stack([r, g, b], axis=-1).astype(np.float32)
    return np.clip(img + 0.05 * np.sin(y / 4.0)[..., None], 0.0, 1.0)


@pytest.fixture(scope="module")
def prof():
    if not _DCP.is_file():
        pytest.skip(f"仓库内置 DCP 缺失: {_DCP}")
    from pixo.render.core.calibration import load_dcp

    return load_dcp(str(_DCP))


@pytest.fixture()
def client(tmp_path, monkeypatch, prof):
    """真实 runtime + 真实 RawPreviewSession，仅解码层打桩。"""
    monkeypatch.setattr(sess_mod.rawpy, "imread",
                        staticmethod(lambda path: _FakeRaw()))
    monkeypatch.setattr(sess_mod, "decode_cfa_half", _synthetic_decode)
    monkeypatch.setattr(core_io, "camera_neutral_wb",
                        lambda raw: np.array([1.0, 1.0, 1.0]))
    monkeypatch.setattr(core_io, "camera_neutral_wb_cached",
                        lambda raw, raw_path=None: np.array([1.0, 1.0, 1.0]))
    rt = PixoServiceRuntime(profile=prof, work_dir=tmp_path / "exports")
    with TestClient(create_app(rt)) as test_client:
        yield test_client


def _make_session(client: TestClient, tmp_path: Path) -> tuple[str, int]:
    raw = tmp_path / "DSC_OKLCH_E2E.NEF"
    raw.write_bytes(b"fake-raw")
    resp = client.post("/api/photos", json={"path": str(raw)})
    assert resp.status_code == 201, resp.text
    photo_id = resp.json()["photo"]["photo_id"]
    resp = client.post(f"/api/photos/{photo_id}/sessions")
    assert resp.status_code == 201, resp.text
    body = resp.json()["session"]
    return body["session_id"], body["generation"]


def _put_params(client: TestClient, sid: str, patch: dict) -> dict:
    resp = client.put(f"/api/sessions/{sid}/params",
                      json={**patch, "__source": "e2e_t21_oklch"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _get_image(client: TestClient, sid: str, gen: int) -> bytes:
    resp = client.get(
        f"/api/sessions/{sid}/image?long_edge=256&fmt=jpeg&quality=88&gen={gen}")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("image/jpeg")
    data = resp.content
    assert data[:3] == b"\xff\xd8\xff" and len(data) > 1000
    return data


# ---------------------------------------------------------------------------
# 场景 1：oklch patch 经 preview 接口往返渲染无错（t20 接口字段口径）
# ---------------------------------------------------------------------------

def test_oklch_patch_roundtrip_via_preview_api(client, tmp_path):
    sid, gen0 = _make_session(client, tmp_path)
    assert gen0 == 0

    # ① PUT oklch patch（深合并 + generation+1，__source 剥离进 Trace）
    body = _put_params(client, sid, _OKLCH_PATCH)
    assert body["generation"] == 1

    # ② canonical 回读：color_domain 深合并不滤键（t20 探测口径）
    canon = client.get(f"/api/sessions/{sid}/canonical").json()["canonical"]
    assert canon["hsl"]["color_domain"] == "oklch"
    assert canon["split_tone"]["color_domain"] == "oklch"

    # ③ oklch 域渲染无错（全 12 级真实管线）
    img_oklch = _get_image(client, sid, gen=1)

    # ④ 切回 hsv：出图必须变化（域参数真实到达渲染）
    body2 = _put_params(client, sid, _HSV_PATCH)
    assert body2["generation"] == 2
    canon2 = client.get(f"/api/sessions/{sid}/canonical").json()["canonical"]
    assert canon2["hsl"]["color_domain"] == "hsv"
    img_hsv = _get_image(client, sid, gen=2)
    assert img_oklch != img_hsv

    # ⑤ oklch 往返回路：再次切回仍无错
    body3 = _put_params(client, sid, _OKLCH_PATCH)
    assert body3["generation"] == 3
    assert _get_image(client, sid, gen=3) == img_oklch


def test_invalid_color_domain_fails_visibly(client, tmp_path):
    """非法域值经接口可见地失败：R22 F04 起在 PUT /params 处即 400。

    R22 前契约 = 「update_params 不拦截（无键过滤），非法值流到渲染期由
    Stage 校验 → 400」（本用例原实现）。design-r22 §5 风险行把
    `update_params` 零校验列为 **F04 必修**，§2.3 明确「stage 名 + 参数键 +
    数值域由 param_schema 派生，越界一律 400」⇒ 非法枚举现在被参数栅栏
    在入口拒绝（渲染期 Stage 校验仍作为第二道兜底）。
    """
    sid, _ = _make_session(client, tmp_path)
    resp = client.put(
        f"/api/sessions/{sid}/params",
        json={"hsl": {"enabled": True, "color_domain": "lab"},
              "__source": "e2e_t21_oklch"})
    assert resp.status_code == 400, resp.text
    assert "color_domain" in resp.text
    # 栅栏拒绝不落任何部分合并：generation 未推进、canonical 不含该键
    canon = client.get(f"/api/sessions/{sid}/canonical").json()
    assert canon["generation"] == 0
    assert canon["canonical"]["hsl"]["color_domain"] != "lab"


# ---------------------------------------------------------------------------
# 场景 2：oklch_demo 胶片卡整卡参数走同一通道（盲点 A1 收口）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sid_card", ["oklch_demo_warm_portrait",
                                      "oklch_demo_cool_landscape"])
def test_oklch_demo_film_card_via_preview_api(client, tmp_path, sid_card):
    cards = {c["style_id"]: c for c in StyleCard.from_films_dir()}
    card = cards[sid_card]
    sid, _ = _make_session(client, tmp_path)

    body = _put_params(client, sid, card["params"])
    gen = body["generation"]
    assert gen >= 1

    canon = client.get(f"/api/sessions/{sid}/canonical").json()["canonical"]
    assert canon["hsl"]["color_domain"] == "oklch"
    assert canon["split_tone"]["color_domain"] == "oklch"
    bands = json.loads(canon["hsl"]["bands"])
    assert len(bands) == 8 and all(b["domain"] == "oklch" for b in bands)

    _get_image(client, sid, gen=gen)
