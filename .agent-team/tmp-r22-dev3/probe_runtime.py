"""R22 dev-3 探针：runtime 层 F04/F05 装配 + HTTP 400 快速自检。"""
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from pixo.render.web.session import RawPreviewSession
from pixo.service import PixoServiceRuntime, create_app


def make_runtime(tmp: Path) -> PixoServiceRuntime:
    return PixoServiceRuntime(
        profile=object(),
        work_dir=tmp / "exports",
        session_factory=lambda photo, sid: RawPreviewSession(
            photo.path, None, session_id=sid, validate_params=True),
    )


tmp = Path(tempfile.mkdtemp())
rt = make_runtime(tmp)
raw = tmp / "DSC_0001.nef"
raw.write_bytes(b"fake-raw")
photo = rt.create_photo(str(raw))
sid = rt.create_session(photo.photo_id).session_id

r = rt.update_params(sid, {"__style": "fujifilm_astia"})
print("style apply gen =", r["generation"])
print("  tone   =", r["params"].get("tone"))
print("  refine =", r["params"].get("refine"))
print("  canonical.tone.contrast =", r["canonical"]["tone"]["contrast"])

for scene in ("portrait", "landscape", "night", "street", "food", "mono"):
    rr = rt.update_params(sid, {"__scene": scene})
    print(f"scene {scene}: gen={rr['generation']} "
          f"tone={rr['params'].get('tone')} colorcal={rr['params'].get('colorcal')}")

for bad, why in (({"__style": "nope"}, "未知卡"),
                 ({"__scene": "nope"}, "未知场景"),
                 ({"__style": "x", "__scene": "portrait"}, "双控制键"),
                 ({"tone": {"contrast": 5}}, "越域"),
                 ({"stylize": {"lut_path": "/x.cube"}}, "lut_path"),
                 ({"s1": {"x": 1}}, "未知 stage")):
    try:
        rt.update_params(sid, bad)
        print(f"[FAIL 被放行] {why}: {bad}")
    except Exception as exc:  # noqa: BLE001
        print(f"[OK 拒绝] {why}: {type(exc).__name__} status="
              f"{getattr(exc, 'status_code', None)} {getattr(exc, 'detail', exc)}")

r = rt.update_params(sid, {"tone": {"highlights": -0.3}, "exposure": {"mode": 0.5}})
print("既有参数正向 gen =", r["generation"], "params.tone =", r["params"]["tone"])

# HTTP 面
app = create_app(rt)
with TestClient(app) as client:
    for body, expect in (
            ({"tone": {"highlights": -0.3}}, 200),
            ({"tone": {"contrast": 5}}, 400),
            ({"stylize": {"lut_path": "/x.cube"}}, 400),
            ({"s1": {"x": 1}}, 400),
            ({"__style": "fujifilm_astia"}, 200),
            ({"__scene": "night"}, 200),
            ({"__scene": "nope"}, 400),
            ({"__style": "nope"}, 400),
            ({"__style": "x", "__scene": "night"}, 400),
    ):
        resp = client.put(f"/api/sessions/{sid}/params", json=body)
        flag = "OK" if resp.status_code == expect else "FAIL"
        print(f"[{flag}] PUT {body} -> {resp.status_code} (期望 {expect})"
              f" {str(resp.json())[:110]}")

# 生产会话工厂确实开栅栏
rt2 = PixoServiceRuntime(profile=object(), work_dir=tmp / "e2")
sess = rt2._default_session_factory(photo, "sid-x")
print("生产工厂 validate_params =", getattr(sess, "validate_params", None))
