# -*- coding: utf-8 -*-
"""test_lr_export —— LR 真值导出脚本离线单测 (不连真实 LR)。

覆盖 (设计 dsh-plan-task-p4 04-task-plan T8):
  - corpus_scan.json 读取 (dict/list 两种缓存形态);
  - wb_B 分层选片: 暖尾全部 / 中带 1.9~2.2 优先 / 冷色抽样 3 张;
  - 清单渲染与 list/dry-run CLI 输出;
  - export 管线: mock 桥接客户端, 验证 备份→reset→export→meta 顺序与产物;
  - 桥接客户端协议 (本地 socket 双端口, 模拟 responseNeedsRebind 重连)。
"""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest

from rawlab.tools.lr_export_corpus import (
    WARM_TAIL_MIN,
    MID_LO,
    MID_HI,
    COOL_SAMPLE_N,
    load_scan,
    band_of,
    is_mid_band,
    select_corpus,
    render_manifest,
    extract_meta,
    run_export,
    resolve_photo_id,
    _restorable_settings,
    LrBridgeClient,
    main,
)


# ── helpers ──────────────────────────────────────────────────────────────

def row(path, wb_b):
    return {"path": str(path), "wb": [1.0, 1.0, wb_b], "wb_b": wb_b,
            "raw_mean": 0.1}


def rows_from(values):
    return [row(f"K:\\data\\photo\\DSC_{i:04d}.NEF", v)
            for i, v in enumerate(values)]


class FakeLrClient:
    """离线 mock 桥接客户端: 记录调用序列, 按 catalog 应答。"""

    def __init__(self, catalog=None):
        # catalog: stem -> (photo_id, develop_settings)
        self.catalog = catalog or {}
        self.calls = []

    def _rec(self, action, **kw):
        self.calls.append((action, kw))

    def ping(self):
        self._rec("ping")
        return {"ok": True, "result": {}, "error": None}

    def search_photos(self, filename=None, limit=100):
        self._rec("search_photos", filename=filename, limit=limit)
        stem = (filename or "").replace(".NEF", "")
        if stem in self.catalog:
            pid, _ = self.catalog[stem]
            return {"ok": True,
                    "result": {"count": 1, "photos": [
                        {"id": pid, "path": f"K:\\data\\photo\\{stem}.NEF",
                         "filename": filename}]},
                    "error": None}
        return {"ok": True, "result": {"count": 0, "photos": []},
                "error": None}

    def get_develop_settings(self, photo_id):
        self._rec("get_develop_settings", photo_id=photo_id)
        for stem, (pid, settings) in self.catalog.items():
            if pid == photo_id:
                return {"ok": True, "result": {"success": True,
                                               "photo_id": photo_id,
                                               "settings": settings},
                        "error": None}
        return {"ok": False, "result": None, "error": "Photo not found"}

    def set_develop_settings(self, photo_id, settings):
        self._rec("set_develop_settings", photo_id=photo_id,
                  settings=dict(settings or {}))
        if any(pid == photo_id for pid, _ in self.catalog.values()):
            return {"ok": True, "result": {"success": True,
                                           "photo_id": photo_id},
                    "error": None}
        return {"ok": False, "result": None, "error": "Photo not found"}

    def reset_develop_settings(self, photo_id):
        self._rec("reset_develop_settings", photo_id=photo_id)
        if any(pid == photo_id for pid, _ in self.catalog.values()):
            return {"ok": True, "result": {"success": True,
                                           "photo_id": photo_id},
                    "error": None}
        return {"ok": False, "result": None, "error": "Photo not found"}

    def export_photos(self, photo_ids, destination, format="jpeg", quality=95,
                      width=None, height=None):
        self._rec("export_photos", photo_ids=list(photo_ids),
                  destination=destination, format=format, quality=quality,
                  width=width, height=height)
        out = Path(destination)
        for pid in photo_ids:
            for stem, (spid, _) in self.catalog.items():
                if spid == pid:
                    (out / f"{stem}.jpg").write_bytes(b"\xff\xd8fake-jpeg")
        return {"ok": True,
                "result": {"success": True, "exported": len(photo_ids),
                           "destination": str(destination),
                           "message": "ok"},
                "error": None}

    def close(self):
        self._rec("close")


# ── load_scan ────────────────────────────────────────────────────────────

def test_load_scan_dict_format(tmp_path):
    f = tmp_path / "scan.json"
    f.write_text(json.dumps({"dirs": ["K:\\data\\photo\\0711"],
                             "rows": [row("K:\\a\\DSC_1.NEF", 1.8),
                                      row("K:\\a\\DSC_2.NEF", 2.1)]},
                            ensure_ascii=False), encoding="utf-8")
    rows = load_scan(f)
    assert len(rows) == 2
    assert rows[0]["wb_b"] == 1.8


def test_load_scan_list_format(tmp_path):
    f = tmp_path / "scan.json"
    f.write_text(json.dumps([row("K:\\a\\DSC_1.NEF", 1.9)],
                            ensure_ascii=False), encoding="utf-8")
    rows = load_scan(f)
    assert len(rows) == 1
    assert rows[0]["wb_b"] == 1.9


def test_load_scan_skips_invalid_rows(tmp_path):
    f = tmp_path / "scan.json"
    f.write_text(json.dumps([row("K:\\a\\DSC_1.NEF", 1.8),
                             {"path": "K:\\a\\no_wb.NEF"},
                             {"wb_b": 2.0},            # 无 path
                             {"path": "K:\\a\\bad.NEF", "wb_b": "NaN"},
                             "garbage"]), encoding="utf-8")
    rows = load_scan(f)
    assert [r["path"] for r in rows] == ["K:\\a\\DSC_1.NEF"]


def test_load_scan_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_scan(tmp_path / "nope.json")


# ── 分层分类 ─────────────────────────────────────────────────────────────

def test_band_classification_boundaries():
    assert band_of(1.79) == "cool"
    assert band_of(1.8) == "warm"          # 暖尾含端点
    assert band_of(3.04) == "warm"
    assert is_mid_band(1.89) is False
    assert is_mid_band(1.9) is True        # 中带含下端点
    assert is_mid_band(2.0) is True
    assert is_mid_band(2.2) is True        # 中带含上端点
    assert is_mid_band(2.21) is False


# ── select_corpus ────────────────────────────────────────────────────────

def test_select_warm_tail_all_included():
    rows = rows_from([1.3, 1.6, 1.8, 1.85, 2.0, 2.3, 3.0, 1.2])
    sel = select_corpus(rows)
    warm = [e for e in sel if e["layer"] == "warm"]
    assert len(warm) == 5
    assert {round(e["wb_b"], 3) for e in warm} == {1.8, 1.85, 2.0, 2.3, 3.0}


def test_select_mid_band_first_and_flagged():
    rows = rows_from([2.0, 2.5, 1.9, 2.2, 3.0, 1.5])  # mid: 1.9/2.0/2.2
    sel = select_corpus(rows)
    mid = [e for e in sel if e["mid"]]
    assert len(mid) == 3
    assert {round(e["wb_b"], 3) for e in mid} == {1.9, 2.0, 2.2}
    # 中带优先: 排最前且按 wb_B 升序
    assert sel[0]["stem"] == "DSC_0002"
    assert sel[1]["stem"] == "DSC_0000"
    assert sel[2]["stem"] == "DSC_0003"
    # 暖尾其余 (非中带) 紧随其后, 按 wb_B 升序
    assert [e["stem"] for e in sel if e["layer"] == "warm" and not e["mid"]] \
        == ["DSC_0001", "DSC_0004"]
    for e in mid:
        assert e["priority"] is True and e["mid"] is True


def test_select_cool_sample_exactly_three_deterministic():
    # 覆盖冷端(1.0)到暖界(<1.8)的全冷色区
    rows = rows_from([round(1.0 + i * 0.008, 4) for i in range(100)])
    sel1 = select_corpus(rows)
    sel2 = select_corpus(rows)
    cool1 = [e for e in sel1 if e["layer"] == "cool"]
    assert len(cool1) == COOL_SAMPLE_N == 3
    assert [e["stem"] for e in cool1] == [e["stem"] for e in
                                          [e for e in sel2 if e["layer"] == "cool"]]
    # 等距覆盖冷端到暖界, 全部 < 1.8
    assert all(e["wb_b"] < WARM_TAIL_MIN for e in cool1)
    assert cool1[0]["wb_b"] < cool1[-1]["wb_b"]
    # 首个为最冷, 末个靠近暖界
    assert cool1[0]["wb_b"] == min(e["wb_b"] for e in rows)
    assert cool1[-1]["wb_b"] > 1.75


def test_select_cool_less_than_three_takes_all():
    rows = rows_from([1.3, 1.6])
    sel = select_corpus(rows)
    cool = [e for e in sel if e["layer"] == "cool"]
    assert len(cool) == 2


def test_select_no_cool_rows():
    rows = rows_from([2.0, 2.5])
    sel = select_corpus(rows)
    assert [e["layer"] for e in sel] == ["warm", "warm"]


def test_select_budget_keeps_mid_first():
    rows = rows_from([2.0, 2.5, 1.9, 2.2, 3.0, 1.5, 1.2, 1.0, 1.7])
    sel = select_corpus(rows, max_total=4)
    assert len(sel) == 4
    # 中带 (1.9/2.0/2.2) 全部保留
    assert len([e for e in sel if e["mid"]]) == 3
    # 剩余 1 个名额给非中带暖尾中最极端 (wb_B 最高 3.0)
    rest = [e for e in sel if not e["mid"]]
    assert len(rest) == 1 and rest[0]["wb_b"] == 3.0


def test_select_empty_input():
    assert select_corpus([]) == []


# ── render_manifest ──────────────────────────────────────────────────────

def test_render_manifest_content():
    rows = rows_from([1.5, 2.05, 2.5])
    sel = select_corpus(rows)
    text = render_manifest(sel)
    assert "LR 真值选片清单" in text
    assert "中带优先" in text and "wb_B=2.0500" in text
    assert "冷色抽样" in text
    assert "合计 3 张" in text
    assert all(e["stem"] in text for e in sel)


# ── extract_meta ─────────────────────────────────────────────────────────

def test_extract_meta_2012_keys():
    settings = {"Temperature": 3300.0, "Tint": 27.0, "Exposure2012": 0.0,
                "WhiteBalance": "As Shot"}
    m = extract_meta(settings)
    assert m == {"temperature": 3300.0, "tint": 27.0, "exposure": 0.0,
                 "white_balance": "As Shot"}


def test_extract_meta_fallback_keys():
    m = extract_meta({"Temperature2012": 3450.0, "Tint2012": -5.0,
                      "Exposure": 1.28})
    assert m["temperature"] == 3450.0
    assert m["tint"] == -5.0
    assert m["exposure"] == 1.28


def test_extract_meta_missing():
    m = extract_meta({})
    assert m["temperature"] is None and m["tint"] is None \
        and m["exposure"] is None


# ── run_export (mock 桥接) ───────────────────────────────────────────────

def _make_entries(tmp_path):
    rows = [row(tmp_path / "DSC_0376.NEF", 2.287),
            row(tmp_path / "DSC_3001.NEF", 3.0),
            row(tmp_path / "DSC_0001.NEF", 1.5)]  # 不在目录
    return select_corpus(rows)


def test_run_export_flow_mock(tmp_path):
    out = tmp_path / "out"
    catalog = {
        "DSC_0376": ("102407",
                     {"Temperature": 3300.0, "Tint": 27.0,
                      "Exposure2012": 0.0, "WhiteBalance": "As Shot"}),
        "DSC_2001": ("102001",
                     {"Temperature": 3200.0, "Tint": 5.0,
                      "Exposure2012": 0.0}),
    }
    client = FakeLrClient(catalog)
    entries = select_corpus(
        [row("K:\\data\\photo\\2026春节\\DSC_0376.NEF", 2.287),
         row("K:\\data\\photo\\厦门\\103XM_04\\DSC_2001.NEF", 2.05),
         row("K:\\data\\photo\\0711\\raw\\DSC_5236.NEF", 1.791)])
    report = run_export(entries, client, out, wait_timeout=5.0)

    # 中带优先: DSC_2001 (mid) 排最前, 故先导出
    assert [x["stem"] for x in report["exported"]] == \
        ["DSC_2001", "DSC_0376"]
    assert [x["stem"] for x in report["skipped"]] == ["DSC_5236"]
    assert report["failed"] == []

    # 产物文件
    assert (out / "DSC_0376.jpg").exists()
    assert (out / "DSC_0376.meta.json").exists()
    assert (out / "DSC_0376.settings_backup.json").exists()
    assert (out / "DSC_2001.meta.json").exists()
    assert not (out / "DSC_5236.jpg").exists()

    # meta 内容: temp/tint/exposure
    meta = json.loads((out / "DSC_0376.meta.json").read_text(encoding="utf-8"))
    assert meta["temperature"] == 3300.0
    assert meta["tint"] == 27.0
    assert meta["exposure"] == 0.0
    assert meta["photo_id"] == "102407"
    assert meta["wb_b"] == 2.287 and meta["mid_band"] is False
    assert meta["layer"] == "warm"
    meta_mid = json.loads((out / "DSC_2001.meta.json")
                          .read_text(encoding="utf-8"))
    assert meta_mid["mid_band"] is True
    assert meta_mid["wb_b"] == 2.05 and meta_mid["temperature"] == 3200.0

    # 备份 = 原始 develop settings
    bak = json.loads((out / "DSC_0376.settings_backup.json")
                     .read_text(encoding="utf-8"))
    assert bak["Temperature"] == 3300.0

    # 调用顺序: 每张 备份(get) → reset → export
    actions = [a for a, _ in client.calls]
    i1 = actions.index("get_develop_settings")
    i2 = actions.index("reset_develop_settings")
    i3 = actions.index("export_photos")
    assert i1 < i2 < i3

    # export 参数: 长边约束 = 宽高同值, q95, jpeg
    _, kw = [c for c in client.calls if c[0] == "export_photos"][0]
    assert kw["width"] == 1600 and kw["height"] == 1600
    assert kw["quality"] == 95 and kw["format"] == "jpeg"
    assert kw["photo_ids"] == ["102001"]  # 第一张导出的是中带 DSC_2001


def test_run_export_photo_not_in_catalog(tmp_path):
    out = tmp_path / "out"
    client = FakeLrClient({})  # 空目录
    entries = select_corpus([row("K:\\a\\DSC_9999.NEF", 2.5)])
    report = run_export(entries, client, out, wait_timeout=2.0)
    assert report["exported"] == []
    assert report["skipped"][0]["reason"] == "not_in_catalog"
    assert list(out.glob("*")) == []  # 未写任何文件


def test_run_export_reset_failure_recorded(tmp_path):
    out = tmp_path / "out"

    class ResetFailClient(FakeLrClient):
        def reset_develop_settings(self, photo_id):
            self._rec("reset_develop_settings", photo_id=photo_id)
            return {"ok": False, "result": None, "error": "reset denied"}

    client = ResetFailClient({"DSC_0376": ("102407", {"Tint": 0.0})})
    entries = select_corpus([row("K:\\a\\DSC_0376.NEF", 2.287)])
    report = run_export(entries, client, out, wait_timeout=2.0)
    assert report["exported"] == []
    assert report["failed"][0]["step"] == "reset_develop_settings"
    # 备份已写 (reset 前), 但未导出
    assert (out / "DSC_0376.settings_backup.json").exists()
    assert not (out / "DSC_0376.jpg").exists()


def test_resolve_photo_id_path_match_and_unique_fallback():
    class C:
        def __init__(self, photos):
            self.photos = photos

        def search_photos(self, filename=None, limit=100):
            return {"ok": True, "result": {"photos": self.photos},
                    "error": None}

    entry = row("K:\\data\\photo\\2026春节\\DSC_0376.NEF", 2.287)
    entry["stem"] = "DSC_0376"
    # 路径精确匹配 (大小写不敏感)
    c = C([{"id": 1, "path": "k:\\DATA\\PHOTO\\2026春节\\DSC_0376.NEF"},
           {"id": 2, "path": "K:\\other\\DSC_0376.NEF"}])
    assert resolve_photo_id(c, entry) == "1"
    # 无路径匹配但唯一结果 → 接受
    c2 = C([{"id": "777", "path": "K:\\somewhere\\else\\DSC_0376.NEF"}])
    assert resolve_photo_id(c2, entry) == "777"
    # 无结果 → None
    assert resolve_photo_id(C([]), entry) is None


# ── CLI (list / dry-run) ─────────────────────────────────────────────────

def test_main_list_mode_writes_selection(tmp_path, capsys):
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps({"rows": rows_from([1.5, 2.05, 2.5])},
                               ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "sel"
    rc = main(["--scan", str(scan), "--out-dir", str(out), "--mode", "list"])
    assert rc == 0
    sel = out / "selection.json"
    assert sel.exists()
    data = json.loads(sel.read_text(encoding="utf-8"))
    assert len(data["entries"]) == 3
    cap = capsys.readouterr()
    assert "LR 真值选片清单" in cap.out
    assert "中带优先" in cap.out


def test_main_dry_run_no_files(tmp_path, capsys):
    scan = tmp_path / "scan.json"
    scan.write_text(json.dumps({"rows": rows_from([1.5, 2.05, 2.5])},
                               ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "sel"
    rc = main(["--scan", str(scan), "--out-dir", str(out), "--mode", "dry-run"])
    assert rc == 0
    assert not out.exists()
    cap = capsys.readouterr()
    assert "dry-run" in cap.out and "未连接 LR" in cap.out


def test_main_missing_scan(tmp_path, capsys):
    rc = main(["--scan", str(tmp_path / "nope.json"), "--mode", "list"])
    assert rc == 2


# ── 桥接客户端协议 (本地 socket, 模拟 responseNeedsRebind) ───────────────

def test_bridge_client_reconnects_on_response_rebind(tmp_path):
    """本地双端口模拟插件: 每次应答后关闭响应 socket (模拟 rebind),
    客户端应重连直到稳定并完成两次调用。"""

    results = [{"pong": True}, {"count": 0, "photos": []}]
    ports = {}
    ready = threading.Event()

    def plugin_server():
        srv_req = socket.socket()
        srv_req.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv_req.bind(("127.0.0.1", 0))
        srv_req.listen(5)
        srv_resp = socket.socket()
        srv_resp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv_resp.bind(("127.0.0.1", 0))
        srv_resp.listen(5)
        ports["req"] = srv_req.getsockname()[1]
        ports["resp"] = srv_resp.getsockname()[1]
        ready.set()
        conns = [srv_req, srv_resp]
        try:
            req_conn, _ = srv_req.accept()
            req_conn.settimeout(10)
            conns.append(req_conn)
            for i, result in enumerate(results):
                # 每次调用客户端都会重建响应 socket (重连直到稳定)
                resp_conn, _ = srv_resp.accept()
                resp_conn.settimeout(10)
                conns.append(resp_conn)
                buf = b""
                while b"\n" not in buf:
                    d = req_conn.recv(4096)
                    if not d:
                        break
                    buf += d
                msg = json.loads(buf.decode("utf-8").strip())
                assert msg["hello"] == "test-token"
                assert msg["action"] in ("ping", "search_photos")
                resp_conn.sendall(
                    (json.dumps({"id": msg["id"], "result": result}) + "\n")
                    .encode("utf-8"))
                resp_conn.close()  # 模拟插件 rebind: 顶掉响应 socket
        finally:
            for c in conns:
                try:
                    c.close()
                except OSError:
                    pass

    t = threading.Thread(target=plugin_server, daemon=True)
    t.start()
    assert ready.wait(5.0), "plugin server 未就绪"

    token = tmp_path / "token"
    token.write_text("test-token", encoding="utf-8")
    # 缩短稳定窗/快速检查间隔, 避免测试过慢
    client = LrBridgeClient(token_path=token, host="127.0.0.1",
                            req_port=ports["req"], resp_port=ports["resp"],
                            timeout=10.0, stable_seconds=0.2,
                            verify_interval=0.05, max_resp_attempts=20)
    try:
        client.connect()
        r1 = client.ping()
        assert r1["ok"] is True and r1["result"] == {"pong": True}
        r2 = client.call("search_photos", {"limit": 100}, timeout=10.0)
        assert r2["ok"] is True and r2["result"]["count"] == 0
    finally:
        client.close()
    t.join(timeout=5.0)
    assert not t.is_alive()

def test_run_export_camera_profile_and_restore(tmp_path):
    """--camera-profile: reset 后先固定 CameraProfile 再导出;
    --restore: 导出成功后把原始 settings 写回 (顺序 get→reset→set→export→set)。"""
    out = tmp_path / "out"
    original = {"Temperature": 3300.0, "Tint": 27.0,
                "Exposure2012": 0.0, "CameraProfile": "Adobe Standard v2",
                "EnableLensCorrections": True,
                "SDRWhites": 0}
    client = FakeLrClient({"DSC_0376": ("102407", original)})
    entries = select_corpus([row("K:\a\DSC_0376.NEF", 2.287)])
    report = run_export(entries, client, out, wait_timeout=2.0,
                        camera_profile="Camera Standard v2", restore=True)

    assert report["exported"][0]["stem"] == "DSC_0376"
    actions = [a for a, _ in client.calls]
    i_get = actions.index("get_develop_settings")
    i_reset = actions.index("reset_develop_settings")
    set_calls = [i for i, a in enumerate(actions)
                 if a == "set_develop_settings"]
    i_export = actions.index("export_photos")
    assert i_get < i_reset < set_calls[0] < i_export < set_calls[1]
    # 第一次 set 只写 CameraProfile; 第二次 set 写回完整原始 settings
    _, kw1 = client.calls[set_calls[0]]
    assert kw1["settings"] == {"CameraProfile": "Camera Standard v2"}
    _, kw2 = client.calls[set_calls[1]]
    assert kw2["settings"] == _restorable_settings(original)
    assert "EnableLensCorrections" not in kw2["settings"]
    assert kw2["settings"]["CameraProfile"] == "Adobe Standard v2"
    meta = json.loads((out / "DSC_0376.meta.json").read_text(encoding="utf-8"))
    assert meta["camera_profile"] == "Camera Standard v2"

