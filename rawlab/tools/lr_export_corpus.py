# -*- coding: utf-8 -*-
"""lr_export_corpus —— LR 真值批量导出 (桥接分层选片)。

用途 (设计: dsh-plan-task-p4 01-functional-design F-06 / 04-task-plan T8):
  从 corpus_scan.json (全库扫描缓存, 含每张的相机 WB 蓝系数 wb_B) 按 wb_B
  分层选片, 通过 Lightroom lightroom-mcp 桥接把选中照片以 **As Shot 无编辑**
  状态导出为 JPEG 真值语料 (长边 1600, q95), 每张附 <stem>.meta.json
  (LR temp/tint/exposure) 与 reset 前备份 <stem>.settings_backup.json。

分层选片规则 (wb_B = 相机 WB 蓝系数, G=1):
  - 暖尾: wb_B ≥ 1.8 → **全部** (暖度标定的锚区, 0376 即 wb_B=2.287);
  - 中带: 1.9 ~ 2.2 → **优先** (暖度标定的唯一盲区, warmth-model 预研
    "中带 1.9~2.2 零样本"; 清单中排最前, --max 预算超限时最先保留);
  - 冷色: wb_B < 1.8 → 等距**抽样 3 张** (确定性分层, 覆盖冷端到暖界)。

桥接 (复用 guanlan 的 lightroom-mcp 协议逻辑, 见
  K:\\work\\project\\guanlan\\src\\mcp\\lr_client.py 与 debug/_wb_probe.py):
  - 双 TCP: 请求 58763 (写) / 响应 58764 (读), JSON 行协议,
    每消息 hello=token 鉴权 (token 文件默认
    ~/.config/lightroom-mcp/token);
  - responseNeedsRebind: 新请求客户端接入会触发插件把响应 socket 顶掉,
    客户端必须 "重连直到稳定" (2 s 存活窗校验); 读中途掉线则重连后重发
    (读操作幂等; 导出等写操作掉线时不自动重发, 防重复导出);
  - photo_id 一律按字符串处理 (LR localIdentifier)。

模式:
  list   选片 → 打印清单 + 写入 <out-dir>/selection.json
  dry-run 选片 → 只打印清单, 不连接 LR, 不写文件
  export 选片 → 连桥接: ping → 逐张 search 定位 → 备份 settings →
          reset_develop_settings → [--camera-profile 固定 CameraProfile]
          → export_photos (长边1600 q95) → <stem>.meta.json
          → [--restore 恢复原 settings]; 不在 LR 目录的照片跳过并提示
          import_photos

用法:
  python rawlab/tools/lr_export_corpus.py --mode dry-run
  python rawlab/tools/lr_export_corpus.py --mode export \
      --out-dir rawlab/out/profile_fit/lr_corpus
"""
from __future__ import annotations

import argparse
import json
import math
import socket
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent.parent

# ── 常量 (对齐 03-specification §2.2 与 guanlan 桥接) ──────────────────────
DEFAULT_SCAN = ROOT / "rawlab" / "out" / "profile_fit" / "corpus_scan.json"
DEFAULT_OUT_DIR = ROOT / "rawlab" / "out" / "profile_fit" / "lr_corpus"
DEFAULT_TOKEN = Path.home() / ".config" / "lightroom-mcp" / "token"

HOST = "127.0.0.1"
REQ_PORT = 58763       # 插件 receive: 客户端发请求
RESP_PORT = 58764      # 插件 send: 客户端收响应
LONG_EDGE = 1600       # 导出长边 (max 约束语义)
QUALITY = 95           # JPEG 质量

# 分层选片常数
WARM_TAIL_MIN = 1.8    # 暖尾: wb_B ≥ 1.8 全部

# lightroom-mcp HandlerDevelop.lua 的 set_develop_settings 白名单。
# get_develop_settings 返回的完整 settings 含 EnableLensCorrections/SDR* 等
# 白名单外键, 原样写回会整包失败; 恢复前必须过滤。
RESTORE_DEVELOP_SETTING_KEYS = {
    "WhiteBalance", "Temperature", "Tint",
    "Exposure2012", "Contrast2012", "Highlights2012", "Shadows2012",
    "Whites2012", "Blacks2012", "Texture", "Clarity2012", "Dehaze",
    "Vibrance", "Saturation",
    "SaturationAdjustmentRed", "SaturationAdjustmentOrange",
    "SaturationAdjustmentYellow", "SaturationAdjustmentGreen",
    "SaturationAdjustmentAqua", "SaturationAdjustmentBlue",
    "SaturationAdjustmentPurple", "SaturationAdjustmentMagenta",
    "HueAdjustmentRed", "HueAdjustmentOrange", "HueAdjustmentYellow",
    "HueAdjustmentGreen", "HueAdjustmentAqua", "HueAdjustmentBlue",
    "HueAdjustmentPurple", "HueAdjustmentMagenta",
    "LuminanceAdjustmentRed", "LuminanceAdjustmentOrange",
    "LuminanceAdjustmentYellow", "LuminanceAdjustmentGreen",
    "LuminanceAdjustmentAqua", "LuminanceAdjustmentBlue",
    "LuminanceAdjustmentPurple", "LuminanceAdjustmentMagenta",
    "ParametricShadows", "ParametricDarks", "ParametricLights",
    "ParametricHighlights", "ParametricShadowSplit",
    "ParametricMidtoneSplit", "ParametricHighlightSplit",
    "ToneCurveName2012", "ToneCurvePV2012", "ToneCurvePV2012Red",
    "ToneCurvePV2012Green", "ToneCurvePV2012Blue",
    "SplitToningBalance", "SplitToningHighlightHue",
    "SplitToningHighlightSaturation", "SplitToningShadowHue",
    "SplitToningShadowSaturation", "ConvertToGrayscale",
    "Sharpness", "SharpenRadius", "SharpenDetail", "SharpenEdgeMasking",
    "LuminanceSmoothing", "LuminanceNoiseReductionDetail",
    "LuminanceNoiseReductionContrast", "ColorNoiseReduction",
    "ColorNoiseReductionDetail", "ColorNoiseReductionSmoothness",
    "LensProfileEnable", "LensManualDistortionAmount",
    "PerspectiveVertical", "PerspectiveHorizontal", "PerspectiveRotate",
    "PerspectiveScale", "PerspectiveAspect", "PerspectiveUpright",
    "PostCropVignetteAmount", "PostCropVignetteMidpoint",
    "PostCropVignetteRoundness", "PostCropVignetteFeather",
    "PostCropVignetteStyle", "GrainAmount", "GrainSize", "GrainFrequency",
    "CropTop", "CropLeft", "CropBottom", "CropRight", "CropAngle",
    "Look", "CameraProfile",
}


def _restorable_settings(settings: dict) -> dict:
    """过滤 get_develop_settings 返回中的白名单外键, 供 set_develop_settings 恢复。"""
    return {k: v for k, v in (settings or {}).items()
            if k in RESTORE_DEVELOP_SETTING_KEYS}
MID_LO, MID_HI = 1.9, 2.2   # 中带: 1.9~2.2 优先 (暖度标定盲区)
COOL_SAMPLE_N = 3      # 冷色等距抽样张数


# ─────────────────────────────────────────────────────────────────────────
# 语料读取与分层选片 (纯逻辑, 离线可测)
# ─────────────────────────────────────────────────────────────────────────

def load_scan(path: str | Path) -> List[dict]:
    """读 corpus_scan.json, 返回 [{path, wb, wb_b, raw_mean, ...}]。

    兼容两种缓存形态: {"dirs": [...], "rows": [...]} (scan_library 写出)
    与裸数组 (旧格式); 缺 wb_b/path 或 wb_b 非法数值的行被跳过。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"scan 文件不存在: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    rows = data["rows"] if isinstance(data, dict) else data
    out: List[dict] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("path") is None or r.get("wb_b") is None:
            continue
        try:
            wb_b = float(r["wb_b"])
        except (TypeError, ValueError):
            continue
        if not math.isfinite(wb_b):
            continue
        row = dict(r)
        row["wb_b"] = wb_b
        out.append(row)
    return out


def band_of(wb_b: float, warm_min: float = WARM_TAIL_MIN) -> str:
    """wb_B → 分层标签: 'warm' (暖尾, ≥warm_min) | 'cool' (其余)。"""
    return "warm" if wb_b >= warm_min else "cool"


def is_mid_band(wb_b: float, mid: tuple = (MID_LO, MID_HI)) -> bool:
    """是否属于优先中带 1.9~2.2 (暖度标定盲区, 暖尾的子集)。"""
    lo, hi = mid
    return lo <= wb_b <= hi


def _even_spread(n: int, k: int) -> List[int]:
    """从长度为 n 的有序序列取 k 个等距下标 (确定性分层抽样)。"""
    if n <= 0 or k <= 0:
        return []
    if k >= n:
        return list(range(n))
    if k == 1:
        return [n // 2]
    idx = [int(i * (n - 1) / (k - 1) + 0.5) for i in range(k)]
    return sorted(set(idx))[:k]


def _annotate(row: dict, layer: str) -> dict:
    e = dict(row)
    e["stem"] = Path(row["path"]).stem
    e["layer"] = layer
    e["mid"] = is_mid_band(row["wb_b"])
    e["priority"] = e["mid"]  # 中带优先
    return e


def _apply_budget(entries: List[dict], max_total: int,
                  mid: tuple = (MID_LO, MID_HI)) -> List[dict]:
    """超预算时按优先级截断: 中带优先 > 暖尾其余 (wb_B 降序, 极端优先)
    > 冷色抽样。中带子集永远最先保留。"""
    mid_band = [e for e in entries if e["mid"]]
    warm_rest = [e for e in entries if e["layer"] == "warm" and not e["mid"]]
    cool = [e for e in entries if e["layer"] == "cool"]
    warm_rest_sorted = sorted(warm_rest, key=lambda e: -e["wb_b"])
    ordered = mid_band + warm_rest_sorted + cool
    return ordered[:max_total]


def select_corpus(rows: Sequence[dict], warm_min: float = WARM_TAIL_MIN,
                  mid: tuple = (MID_LO, MID_HI), cool_n: int = COOL_SAMPLE_N,
                  max_total: Optional[int] = None) -> List[dict]:
    """按 wb_B 分层选片: 暖尾全部 + 中带优先 + 冷色抽样 3 张。

    输出顺序: 中带(1.9~2.2, 优先) → 暖尾其余(按 wb_B 升序) → 冷色抽样
    (按 wb_B 升序)。每条带 layer/mid/priority 注解。确定性, 无随机。
    """
    rows = [r for r in rows if isinstance(r, dict) and r.get("wb_b") is not None]
    warm = sorted((r for r in rows if r["wb_b"] >= warm_min),
                  key=lambda r: (r["wb_b"], r.get("path", "")))
    cool = sorted((r for r in rows if r["wb_b"] < warm_min),
                  key=lambda r: (r["wb_b"], r.get("path", "")))

    entries: List[dict] = []
    mid_band: List[dict] = []
    for r in warm:
        e = _annotate(r, "warm")
        (mid_band if e["mid"] else entries).append(e)
    # 中带优先排最前, 其余暖尾按 wb_B 升序
    entries = mid_band + entries
    for r in _even_sample(cool, cool_n):
        entries.append(_annotate(r, "cool"))

    if max_total is not None and len(entries) > max_total:
        entries = _apply_budget(entries, max_total, mid)
    return entries


def _even_sample(rows: Sequence[dict], n: int) -> List[dict]:
    """对已排序 rows 取 n 个等距样本 (保序)。"""
    if n <= 0 or not rows:
        return []
    return [rows[i] for i in _even_spread(len(rows), n)]


def render_manifest(entries: Sequence[dict]) -> str:
    """渲染选片清单文本 (list / dry-run 输出)。"""
    n_warm = sum(1 for e in entries if e["layer"] == "warm")
    n_mid = sum(1 for e in entries if e["mid"])
    n_cool = len(entries) - n_warm
    lines = [
        "LR 真值选片清单 (wb_B 分层)",
        "=" * 78,
    ]
    for i, e in enumerate(entries, 1):
        if e["mid"]:
            tag = "中带优先"
        elif e["layer"] == "warm":
            tag = "暖尾"
        else:
            tag = "冷色抽样"
        lines.append(
            f"[{i:>3}] {tag:<5} wb_B={e['wb_b']:.4f}  {e['stem']:<14} {e['path']}")
    wb_all = sorted(e["wb_b"] for e in entries)
    rng = (f"{wb_all[0]:.4f}~{wb_all[-1]:.4f}" if wb_all else "-")
    lines.append("=" * 78)
    lines.append(
        f"合计 {len(entries)} 张 | 暖尾 {n_warm} (含中带优先 {n_mid}) | "
        f"冷色抽样 {n_cool} | wb_B {rng}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# lightroom-mcp 桥接客户端 (同步, 协议复用 guanlan)
# ─────────────────────────────────────────────────────────────────────────

def _read_token(token_path: str | Path) -> Optional[str]:
    try:
        tok = Path(token_path).read_text(encoding="utf-8").strip()
        return tok or None
    except Exception:
        return None


def _env(ok: bool, result, error: Optional[str]) -> dict:
    return {"ok": bool(ok), "result": result, "error": error}


class LrBridgeClient:
    """直连 lightroom-mcp Lua 插件双 TCP socket 的同步客户端。

    协议对齐 guanlan (src/mcp/lr_client.py + debug/_wb_probe.py):
      请求 :58763  {"hello": token, "id": rid, "action": ..., "params": {...}}\\n
      响应 :58764  {"id": rid, "result": {...}} | {"id": rid, "error": "..."}\\n
    responseNeedsRebind: 请求 socket 接入会触发插件把响应 socket 顶掉,
    故每次发送前确保响应 socket "重连直到稳定" (2 s 存活窗); 读中途掉线
    则重连并重发 (retry_on_drop=True 的幂等读); 写操作 (export) 掉线不重发。
    返回统一 envelope {"ok", "result", "error"} (对齐 guanlan LrAsyncClient)。
    """

    def __init__(self, token_path: str | Path = DEFAULT_TOKEN, host: str = HOST,
                 req_port: int = REQ_PORT, resp_port: int = RESP_PORT,
                 timeout: float = 60.0, stable_seconds: float = 2.0,
                 verify_interval: float = 15.0,
                 max_resp_attempts: int = 40, max_call_attempts: int = 6):
        self._token_path = Path(token_path)
        self._host = host
        self._req_port = req_port
        self._resp_port = resp_port
        self._timeout = timeout
        self._stable_seconds = stable_seconds
        self._verify_interval = verify_interval
        self._max_resp_attempts = max_resp_attempts
        self._max_call_attempts = max_call_attempts
        self._token: Optional[str] = None
        self._req: Optional[socket.socket] = None
        self._resp: Optional[socket.socket] = None
        self._buf = b""
        self._seq = 0
        self._last_verified = 0.0

    # ── 会话 ──────────────────────────────────────────────

    def connect(self) -> None:
        self._token = _read_token(self._token_path)
        if not self._token:
            print("[bridge] 警告: token 为空, 请求将被 Lua 端静默丢弃 (超时)",
                  file=sys.stderr)
        self._req = socket.create_connection((self._host, self._req_port),
                                             timeout=10.0)
        if not self._ensure_resp():
            raise ConnectionError("response socket never stable")

    def close(self) -> None:
        for s in (self._req, self._resp):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass
        self._req = None
        self._resp = None
        self._buf = b""

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ── 底层: 响应 socket 稳定重连 ──────────────────────────

    def _drop_resp(self) -> None:
        if self._resp is not None:
            try:
                self._resp.close()
            except OSError:
                pass
        self._resp = None
        self._buf = b""
        self._last_verified = 0.0

    def _ensure_resp(self) -> bool:
        """响应 socket 就绪。已连且近期验证过 → 快速存活检查 (15 s 间隔内);
        否则走完整 2 s 稳定窗 (重连直到稳定)。"""
        now = time.time()
        if self._resp is not None and \
                (now - self._last_verified) < self._verify_interval:
            self._resp.settimeout(0.15)
            try:
                d = self._resp.recv(1)
            except socket.timeout:
                self._resp.settimeout(None)
                return True
            except OSError:
                self._drop_resp()
            else:
                if d:
                    self._buf += d
                    self._resp.settimeout(None)
                    return True
                self._drop_resp()

        for _ in range(self._max_resp_attempts):
            if self._resp is None:
                try:
                    self._resp = socket.create_connection(
                        (self._host, self._resp_port), timeout=5.0)
                except OSError:
                    time.sleep(0.5)
                    continue
            s = self._resp
            s.settimeout(0.2)
            ok, t0 = True, time.time()
            while time.time() - t0 < self._stable_seconds:
                try:
                    d = s.recv(1)
                except socket.timeout:
                    pass
                except OSError:
                    ok = False
                    break
                else:
                    if d == b"":
                        ok = False
                        break
                    self._buf += d
                time.sleep(0.05)
            if ok:
                s.settimeout(None)
                self._last_verified = time.time()
                return True
            self._drop_resp()
            time.sleep(1.0)
        return False

    def _readline(self) -> bytes:
        while b"\n" not in self._buf:
            if self._resp is None:
                raise ConnectionError("response socket closed")
            data = self._resp.recv(65536)
            if not data:
                raise ConnectionError("response socket closed")
            self._buf += data
        line, self._buf = self._buf.split(b"\n", 1)
        return line.strip()

    # ── 底层: 请求/响应 ─────────────────────────────────────

    def call(self, action: str, params: Optional[dict] = None,
             timeout: Optional[float] = None,
             retry_on_drop: bool = True) -> dict:
        timeout = timeout if timeout is not None else self._timeout
        params = params or {}
        if self._req is None:
            self.connect()
        for attempt in range(self._max_call_attempts):
            if not self._ensure_resp():
                return _env(False, None, "response socket never stable")
            if self._req is None:
                try:
                    self._req = socket.create_connection(
                        (self._host, self._req_port), timeout=10.0)
                except OSError as e:
                    return _env(False, None, f"request socket failed: {e}")
            self._seq += 1
            rid = f"lr_{int(time.time() * 1000)}_{self._seq}"
            payload = json.dumps(
                {"hello": self._token, "id": rid,
                 "action": action, "params": params},
                ensure_ascii=False) + "\n"
            try:
                self._req.sendall(payload.encode("utf-8"))
            except OSError:
                try:
                    self._req.close()
                except OSError:
                    pass
                self._req = None
                time.sleep(1.0)
                continue

            if self._resp is not None:
                self._resp.settimeout(5.0)
            deadline = time.time() + timeout
            dropped = False
            while time.time() < deadline:
                try:
                    line = self._readline()
                except ConnectionError:
                    dropped = True
                    break
                except socket.timeout:
                    continue
                except OSError:
                    dropped = True
                    break
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except Exception:
                    continue
                if msg.get("id") == rid:
                    if msg.get("error") is not None:
                        return _env(False, None, str(msg["error"]))
                    return _env(True, msg.get("result"), None)
            if dropped:
                self._drop_resp()
                if not retry_on_drop:
                    return _env(False, None,
                                f"response socket dropped during {action} "
                                f"(写操作不自动重发, 防重复)")
                continue  # 重连后重发 (读操作幂等)
            return _env(False, None,
                        f"timeout after {timeout:.0f}s (action={action})")
        return _env(False, None, "gave up after retries")

    # ── 动作 (photo_id 一律字符串) ───────────────────────────

    def ping(self) -> dict:
        return self.call("ping", {}, timeout=15.0)

    def search_photos(self, filename: Optional[str] = None,
                      limit: int = 100) -> dict:
        params: dict = {"limit": limit}
        if filename:
            params["filename"] = filename
        return self.call("search_photos", params, timeout=60.0)

    def get_develop_settings(self, photo_id) -> dict:
        return self.call("get_develop_settings",
                         {"photo_id": str(photo_id)}, timeout=60.0)

    def set_develop_settings(self, photo_id, settings: dict) -> dict:
        return self.call("set_develop_settings",
                         {"photo_id": str(photo_id),
                          "settings": dict(settings or {})},
                         timeout=120.0)

    def reset_develop_settings(self, photo_id) -> dict:
        return self.call("reset_develop_settings",
                         {"photo_id": str(photo_id)}, timeout=60.0)

    def export_photos(self, photo_ids, destination, format: str = "jpeg",
                      quality: int = 95, width: Optional[int] = None,
                      height: Optional[int] = None) -> dict:
        dest = Path(destination).resolve()
        dest.mkdir(parents=True, exist_ok=True)
        params: dict = {
            "photo_ids": [str(i) for i in photo_ids],
            "destination": str(dest),
            "format": format,
            "quality": int(quality),
        }
        if width:
            params["width"] = int(width)
        if height:
            params["height"] = int(height)
        return self.call("export_photos", params, timeout=300.0,
                         retry_on_drop=False)


# ─────────────────────────────────────────────────────────────────────────
# 导出管线 (client 可注入 mock, 离线可测)
# ─────────────────────────────────────────────────────────────────────────

def extract_meta(settings: dict) -> dict:
    """从 develop settings 提取 meta 字段 (temp/tint/exposure)。

    键兼容新旧两种写法 (Temperature/Temperature2012 等), 缺失时为 None。
    """
    def first(*keys):
        for k in keys:
            if k in settings and settings[k] is not None:
                return settings[k]
        return None
    return {
        "temperature": first("Temperature", "Temperature2012"),
        "tint": first("Tint", "Tint2012"),
        "exposure": first("Exposure2012", "Exposure"),
        "white_balance": first("WhiteBalance"),
    }


def _normalize_path(p: str) -> str:
    return str(p).lower().replace("/", "\\")


def resolve_photo_id(client, entry: dict) -> Optional[str]:
    """search_photos 按文件名定位 → 按路径精确匹配返回 LR photo_id (字符串)。

    匹配不上但只有唯一结果时接受之; 无结果/歧义 → None。
    """
    stem = entry["stem"]
    r = client.search_photos(filename=f"{stem}.NEF", limit=50)
    if not r.get("ok"):
        return None
    photos = (r.get("result") or {}).get("photos") or []
    want = _normalize_path(entry["path"])
    for p in photos:
        if p.get("path") and _normalize_path(p["path"]) == want:
            return str(p["id"])
    if len(photos) == 1:
        return str(photos[0]["id"])
    return None


def _wait_for_jpg(out_dir: Path, stem: str, timeout: float) -> Optional[Path]:
    t0 = time.time()
    while time.time() - t0 < timeout:
        for p in out_dir.glob("*.jpg"):
            if p.stem.lower() == stem.lower():
                return p
        time.sleep(0.5)
    return None


def run_export(entries: Sequence[dict], client, out_dir: str | Path,
               long_edge: int = LONG_EDGE, quality: int = QUALITY,
               backup: bool = True, wait_timeout: float = 30.0,
               camera_profile: str | None = None,
               restore: bool = False) -> dict:
    """对清单逐张执行: search 定位 → 备份 settings → reset →
    (可选) 固定 CameraProfile → export → meta → (可选) 恢复原 settings。

    返回报告 {"exported": [...], "skipped": [...], "failed": [...]}。
    破坏性顺序保证: 备份成功后才 reset, reset 成功后才 export;
    restore=True 时导出后写回备份 settings (CameraProfile 固定失败也会尝试恢复)。
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report: dict = {"exported": [], "skipped": [], "failed": []}
    total = len(entries)
    for i, e in enumerate(entries, 1):
        stem = e["stem"]
        tag = "中带优先" if e["mid"] else ("暖尾" if e["layer"] == "warm"
                                           else "冷色")
        photo_id = resolve_photo_id(client, e)
        if photo_id is None:
            report["skipped"].append({
                "stem": stem, "path": e["path"], "wb_b": e["wb_b"],
                "reason": "not_in_catalog"})
            print(f"[export] ({i}/{total}) {tag} {stem}: "
                  f"不在 LR 目录 (需先 import_photos)", flush=True)
            continue

        # 1) 备份原 develop settings (reset 前)
        r = client.get_develop_settings(photo_id)
        if not r.get("ok"):
            report["failed"].append({
                "stem": stem, "path": e["path"], "photo_id": photo_id,
                "step": "get_develop_settings", "error": r.get("error")})
            print(f"[export] ({i}/{total}) {tag} {stem}: "
                  f"读 settings 失败: {r.get('error')}", flush=True)
            continue
        settings = (r.get("result") or {}).get("settings") or {}
        backup_path = out / f"{stem}.settings_backup.json"
        if backup:
            backup_path.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2),
                encoding="utf-8")

        # 2) reset (破坏性, 已备份)
        r = client.reset_develop_settings(photo_id)
        if not r.get("ok"):
            report["failed"].append({
                "stem": stem, "path": e["path"], "photo_id": photo_id,
                "step": "reset_develop_settings", "error": r.get("error")})
            print(f"[export] ({i}/{total}) {tag} {stem}: "
                  f"reset 失败: {r.get('error')}", flush=True)
            continue

        # 2.5) 固定 CameraProfile (口径对齐: 拟合 Camera Standard 时用
        #      "Camera Standard v2"; 不传则保持 reset 后的 LR 默认 profile)
        if camera_profile:
            r = client.set_develop_settings(
                photo_id, {"CameraProfile": camera_profile})
            if not r.get("ok"):
                report["failed"].append({
                    "stem": stem, "path": e["path"], "photo_id": photo_id,
                    "step": "set_develop_settings(CameraProfile)",
                    "error": r.get("error")})
                print(f"[export] ({i}/{total}) {tag} {stem}: "
                      f"设置 CameraProfile={camera_profile} 失败: "
                      f"{r.get('error')}", flush=True)
                if restore:
                    rr = client.set_develop_settings(
                        photo_id, _restorable_settings(settings))
                    if not rr.get("ok"):
                        print(f"[export] ({i}/{total}) {tag} {stem}: "
                              f"恢复 settings 失败: {rr.get('error')}",
                              flush=True)
                continue

        # 3) export (长边 long_edge, q95)
        r = client.export_photos(
            [photo_id], str(out), format="jpeg", quality=quality,
            width=long_edge, height=long_edge)
        if not r.get("ok"):
            report["failed"].append({
                "stem": stem, "path": e["path"], "photo_id": photo_id,
                "step": "export_photos", "error": r.get("error")})
            print(f"[export] ({i}/{total}) {tag} {stem}: "
                  f"export 失败: {r.get('error')}", flush=True)
            continue

        # 4) meta (temp/tint/exposure 取自备份的原始 settings)
        meta = {
            "photo_id": photo_id,
            "path": e["path"],
            "stem": stem,
            "wb_b": e["wb_b"],
            "wb": e.get("wb"),
            "layer": e["layer"],
            "mid_band": bool(e["mid"]),
            "export": {"format": "jpeg", "quality": quality,
                       "long_edge": long_edge},
        }
        if camera_profile:
            meta["camera_profile"] = camera_profile
        meta.update(extract_meta(settings))
        (out / f"{stem}.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        jpg = _wait_for_jpg(out, stem, wait_timeout)
        if jpg is None:
            print(f"[export] ({i}/{total}) {tag} {stem}: "
                  f"导出完成但未在 {out} 找到 {stem}.jpg "
                  f"(检查 LR 导出文件名)", flush=True)
        report["exported"].append({
            "stem": stem, "photo_id": photo_id, "path": e["path"],
            "wb_b": e["wb_b"], "layer": e["layer"], "mid": bool(e["mid"]),
            "jpg": str(jpg) if jpg else None})
        print(f"[export] ({i}/{total}) {tag} {stem} (wb_B={e['wb_b']:.4f}) "
              f"→ 已导出", flush=True)

        # 4.5) 恢复导出前的 develop settings (不污染用户 LR 目录)
        if restore:
            rr = client.set_develop_settings(
                photo_id, _restorable_settings(settings))
            if not rr.get("ok"):
                print(f"[export] ({i}/{total}) {tag} {stem}: "
                      f"恢复 settings 失败: {rr.get('error')}", flush=True)
                report["restore_failed"] = report.get("restore_failed", [])
                report["restore_failed"].append({
                    "stem": stem, "photo_id": photo_id,
                    "error": rr.get("error")})
    return report


# ─────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────

def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(
        description="LR 真值批量导出 (wb_B 分层选片 + lightroom-mcp 桥接)")
    ap.add_argument("--scan", default=str(DEFAULT_SCAN),
                    help="corpus_scan.json 路径")
    ap.add_argument("--selection", default=None,
                    help="复用已有 selection.json 的 entries (不重新分层选片)")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                    help="导出/清单目录 (默认 rawlab/out/profile_fit/lr_corpus)")
    ap.add_argument("--mode", choices=["list", "dry-run", "export"],
                    default="list")
    ap.add_argument("--max", dest="max_total", type=int, default=None,
                    metavar="N", help="清单总上限 (默认不限); 超限时中带优先保留")
    ap.add_argument("--token", default=None,
                    help="lightroom-mcp token 文件 (默认 "
                         "~/.config/lightroom-mcp/token)")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--req-port", type=int, default=REQ_PORT)
    ap.add_argument("--resp-port", type=int, default=RESP_PORT)
    ap.add_argument("--long-edge", type=int, default=LONG_EDGE)
    ap.add_argument("--quality", type=int, default=QUALITY)
    ap.add_argument("--wait-timeout", type=float, default=30.0,
                    help="单张导出落盘等待秒数")
    ap.add_argument("--camera-profile", default=None,
                    help="reset 后固定 CameraProfile 再导出 (如 "
                         "\"Camera Standard v2\"; 不传保持 LR 默认)")
    ap.add_argument("--restore", action="store_true",
                    help="导出完成后把 develop settings 恢复为导出前状态")
    args = ap.parse_args(argv)

    scan = Path(args.scan)
    if not scan.exists():
        print(f"[error] scan 文件不存在: {scan}", file=sys.stderr)
        return 2
    if args.selection:
        sel_path = Path(args.selection)
        if not sel_path.exists():
            print(f"[error] selection 文件不存在: {sel_path}", file=sys.stderr)
            return 2
        sel_data = json.loads(sel_path.read_text(encoding="utf-8"))
        entries = sel_data.get("entries") or []
        print(f"[selection] 复用 {sel_path} 的 {len(entries)} 条 entries")
    else:
        rows = load_scan(scan)
        entries = select_corpus(rows, max_total=args.max_total)
    print(render_manifest(entries))

    if args.mode == "list":
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        sel = out_dir / "selection.json"
        sel.write_text(json.dumps(
            {"scan": str(scan), "mode": "list", "entries": entries},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n[list] 清单已写入 {sel}")
        return 0

    if args.mode == "dry-run":
        print("\n[dry-run] 未连接 LR — 以上为选片清单预览, 无任何文件写出")
        return 0

    # export
    token = args.token or str(DEFAULT_TOKEN)
    client = LrBridgeClient(token_path=token, host=args.host,
                            req_port=args.req_port, resp_port=args.resp_port)
    try:
        client.connect()
        p = client.ping()
        if not p.get("ok"):
            print(f"[export] ping 失败 (LR 未运行或端口不通): {p.get('error')}",
                  file=sys.stderr)
            return 1
        print(f"[export] 桥接在线 (ping ok) — 导出 {len(entries)} 张 → "
              f"{args.out_dir}")
        report = run_export(entries, client, args.out_dir,
                            long_edge=args.long_edge, quality=args.quality,
                            wait_timeout=args.wait_timeout,
                            camera_profile=args.camera_profile,
                            restore=args.restore)
        n_ok = len(report["exported"])
        n_skip = len(report["skipped"])
        n_fail = len(report["failed"])
        print(f"[export] 完成: 导出 {n_ok} 张, 跳过(不在 LR 目录) {n_skip} 张, "
              f"失败 {n_fail} 张")
        if n_skip:
            print("[export] 提示: 未导入目录的照片需先 lightroom-mcp "
                  "import_photos 再导出 (厦门 2407 张未导入)")
        for f in report["failed"]:
            print(f"  [failed] {f['stem']}: {f['step']} → {f['error']}")
        return 0 if n_fail == 0 else 2
    except ConnectionError as e:
        print(f"[export] 桥接连接失败: {e}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
