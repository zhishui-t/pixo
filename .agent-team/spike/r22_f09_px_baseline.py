"""R22 F09 (tech_debt #17) —— legacy px 语义冻结基线探针。

用途（design A18 / 侦察报告 §2.4 L2）：
  * ``--write``：**改码前**执行，把 compose free/ratio/auto_level 的 px 语义
    （``compute_crop_rect`` 输出、``ComposeStage`` 元数据、输出像素 sha256、
    ``region_masks._post_compose_shape`` 预测）冻结成 JSON + 自哈希。
  * ``--check``：改码后执行，逐位比对；同时（若实现已支持 ``coord``）额外跑
    **零容差等价断言**：``coord="norm"`` ≡ 把参数换算成该画布像素后的 ``coord="px"``。

不改任何生产代码；不依赖真 RAW；全流程确定性（固定种子、无时间戳进入 payload）。
退出码：0 = 无漂移 / 1 = 有漂移 / 2 = 基线缺失或 payload 结构异常。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / ".artifacts" / "r22-f09-px-baseline.json"

# 与 tests/conftest.py:19-22 同款：直接把 src 入 sys.path（本机 pixo 非稳定
# editable 安装，`python -c "import pixo"` 会 ModuleNotFoundError）。
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# (w, h) —— 含 512 tier 短边 341（最小分母，容差最大）与导出全幅
CANVASES = [(640, 480), (64, 48), (512, 341), (1024, 683), (2048, 1365),
            (6048, 4032)]

# free 模式参数网格（含 0 哨兵 / 负值 / 越界 / .5 舍入边界）
FREE_PARAMS = [
    dict(x=0.0, y=0.0, width=0.0, height=0.0),        # default_params（全幅哨兵）
    dict(x=7.0, y=5.0, width=20.0, height=15.0),
    dict(x=7.5, y=5.5, width=20.5, height=15.5),      # 银行家舍入边界
    dict(x=-3.0, y=-4.0, width=20.0, height=15.0),    # 负起点 → 钳 0
    dict(x=1000.0, y=1000.0, width=20.0, height=15.0),  # 起点越界
    dict(x=0.0, y=0.0, width=100000.0, height=100000.0),  # 尺寸越界
    dict(x=10.0, y=10.0, width=0.5, height=0.5),      # 亚像素尺寸 → 钳 1px
    dict(x=10.0, y=10.0, width=-1.0, height=20.0),    # 负尺寸 → 全幅哨兵
    dict(x=10.0, y=10.0, width=20.0, height=None),    # None → 全幅哨兵
    dict(x=12.0, y=8.0, width=100.0, height=64.0),    # 右/下边界钳位
    dict(x=0.25, y=0.20, width=0.50, height=0.60),    # px 视角下的"小值"样本
]

RATIO_PARAMS = [
    dict(ratio="2:1", center=[0.5, 0.5]),
    dict(ratio="3:2", center=[0.3, 0.7]),
    dict(ratio="1:1", center=[0.0, 0.0]),
    dict(ratio=None, center=[0.5, 0.5]),
    dict(ratio="16:9", center=[1.0, 1.0]),
]

STAGE_CASES = [
    {"compose": {"mode": "free", "x": 7, "y": 5, "width": 20, "height": 15}},
    {"compose": {"mode": "free", "x": 0, "y": 0, "width": 0, "height": 0}},
    {"compose": {"mode": "free", "x": 3, "y": 4, "width": 24, "height": 18,
                 "rotation": 10.0, "horizontal_flip": True}},
    {"compose": {"mode": "ratio", "ratio": "2:1", "center": [0.5, 0.5]}},
    {"compose": {"mode": "auto_level", "rotation": 0.0}},
]


def _call(rect_fn, h, w, mode, **kw):
    return list(rect_fn(h, w, mode, **kw))


def build_payload() -> dict:
    import pixo.render.modules  # noqa: F401  触发 Stage 注册
    from pixo.render.modules.compose import ComposeStage, compute_crop_rect
    from pixo.render.pipeline.graph import DOMAIN_LINEAR_RGB, StageContext
    from pixo.render.pipeline.region_masks import _post_compose_shape

    payload: dict = {"rects": [], "stages": [], "post_compose_shape": []}

    # ① 纯函数 px 输出全表
    for (w, h) in CANVASES:
        for i, kw in enumerate(FREE_PARAMS):
            kw2 = dict(kw)
            payload["rects"].append({
                "tag": f"free/{w}x{h}/#{i}",
                "mode": "free",
                "x": kw2["x"], "y": kw2["y"],
                "width": kw2["width"], "height": kw2["height"],
                "rect": _call(compute_crop_rect, h, w, "free", **kw2),
            })
        for i, kw in enumerate(RATIO_PARAMS):
            payload["rects"].append({
                "tag": f"ratio/{w}x{h}/#{i}",
                "mode": "ratio", "ratio": kw["ratio"],
                "center": list(kw["center"]),
                "rect": _call(compute_crop_rect, h, w, "ratio", **kw),
            })
        payload["rects"].append({
            "tag": f"auto_level/{w}x{h}",
            "mode": "auto_level", "rect": _call(compute_crop_rect, h, w, "auto_level"),
        })

    # ② ComposeStage 元数据 + 输出像素 sha256（确定性合成图，无时间戳）
    rng = np.random.default_rng(20260910)
    img = rng.random((48, 64, 3), dtype=np.float32)
    for i, cfg in enumerate(STAGE_CASES):
        ctx = StageContext("baseline.NEF", config={"stages": dict(cfg)})
        ctx.set_image(img.copy(), DOMAIN_LINEAR_RGB)
        ComposeStage().run(ctx)
        geom = ctx.state["compose"]
        out = np.ascontiguousarray(ctx.image)
        payload["stages"].append({
            "tag": f"stage/#{i}", "config": cfg,
            "crop_rect": dict(geom["crop_rect"]),
            "original_size": list(geom["original_size"]),
            "final_size": list(geom["final_size"]),
            "out_shape": list(out.shape),
            "out_sha256": hashlib.sha256(out.tobytes()).hexdigest(),
        })

    # ③ 掩码 shape 预测（两线同源点）
    for i, cfg in enumerate(STAGE_CASES):
        cp = cfg["compose"]
        if cp.get("mode") != "free":
            continue
        for (w, h) in CANVASES[:4]:
            payload["post_compose_shape"].append({
                "tag": f"pcs/#{i}/{w}x{h}", "compose": cp, "in": [h, w],
                "out": list(_post_compose_shape((h, w), cp)),
            })

    return payload


def payload_sha(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")).encode("utf-8")).hexdigest()


def norm_equivalence_report() -> tuple[bool, list[str]]:
    """零容差等价断言（实现支持 coord 后才有意义）。"""
    from pixo.render.modules.compose import compute_crop_rect

    if "coord" not in compute_crop_rect.__code__.co_varnames:
        return True, ["[skip] compute_crop_rect 尚无 coord 形参（改码前）"]

    msgs, ok = [], True
    for (w, h) in CANVASES:
        for kw in FREE_PARAMS:
            if kw["width"] is None or kw["height"] is None:
                continue
            norm = dict(kw)
            px_kw = dict(x=norm["x"] * w, y=norm["y"] * h,
                         width=norm["width"] * w, height=norm["height"] * h)
            a = compute_crop_rect(h, w, "free", coord="norm", **norm)
            b = compute_crop_rect(h, w, "free", coord="px", **px_kw)
            if list(a) != list(b):
                ok = False
                msgs.append(f"[FAIL] {w}x{h} {norm}: norm={a} px={b}")
    msgs.append(f"[{'ok' if ok else 'FAIL'}] 零容差等价："
                f"{len(CANVASES) * len(FREE_PARAMS)} 组合")
    return ok, msgs


def cmd_write() -> int:
    payload = build_payload()
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    doc = {"sha256": payload_sha(payload), "payload": payload}
    BASELINE.write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")
    print(f"[baseline] wrote {BASELINE} sha256={doc['sha256']}")
    print(f"[baseline] rects={len(payload['rects'])} "
          f"stages={len(payload['stages'])} "
          f"post_compose_shape={len(payload['post_compose_shape'])}")
    return 0


def cmd_check() -> int:
    if not BASELINE.exists():
        print(f"[baseline] 缺失：{BASELINE}", file=sys.stderr)
        return 2
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    try:
        old = doc["payload"]
        old_sha = doc["sha256"]
    except KeyError:
        print("[baseline] payload/sha256 结构异常", file=sys.stderr)
        return 2
    new = build_payload()
    new_sha = payload_sha(new)

    drifts = []
    for key in ("rects", "stages", "post_compose_shape"):
        a, b = old.get(key), new.get(key)
        if len(a) != len(b):
            drifts.append(f"{key}: 条目数 {len(a)} -> {len(b)}")
            continue
        for x, y in zip(a, b):
            if x != y:
                drifts.append(f"{key} {x.get('tag')}: {x} -> {y}")

    for line in drifts[:20]:
        print(f"  DRIFT {line}")
    print(f"[baseline] payload sha256 {old_sha} -> {new_sha}")
    if drifts or old_sha != new_sha:
        print(f"[baseline] CHECK: DRIFT（{len(drifts)} 处）")
        return 1
    print("[baseline] CHECK: OK（legacy px 路径逐位不变）")

    ok, msgs = norm_equivalence_report()
    for m in msgs:
        print(f"  {m}")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="写基线（改码前执行）")
    ap.add_argument("--check", action="store_true", help="改码后逐位比对")
    args = ap.parse_args(argv)
    if args.check:
        return cmd_check()
    return cmd_write()


if __name__ == "__main__":
    raise SystemExit(main())
