"""docs/tech_debt.md 限定条件的运行时断言（tech-debt 批次）。

把清单中『已清偿』『仅在 YY 条件下可用』类条目固化为可执行断言——
被意外触发（清偿复发/限定失效）即告警；纯人决策与条件触发类条目
（DNG clean-room 复审、门禁口径扩展、公式守卫日落、外部评审 backlog
四个子项等）不可机器断言，不在此列。

覆盖映射（条目号按 docs/tech_debt.md）：
  - test_restricted_model_backends_gated_out_of_router_by_default
      ← 条目 1 关联约束：usage=internal_development_only 的后端
        （uniface/sapiens）默认不进 multi 路由，PIXO_ALLOW_RESTRICTED=1
        显式放行
  - test_cleared_items_stay_cleared
      ← 条目 1（YOLOE AGPL 清偿防复活）+ 条目 6（src/render shim 已移除）
        + 条目 8/10b（VibranceStage 废弃占位，显式调用抛 NotImplementedError）
  - test_model_license_registry_paths_resolve
      ← 条目 3（model_licenses.json 与当前路径同步，防悬空复发）
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import pixo
from pixo.vision.segmenters.multi_router import (
    ROUTE_TABLE,
    MultiModelSegmenter,
    restricted_backend_names,
)

_SRC_PIXO = Path(pixo.__file__).resolve().parent      # .../src/pixo
_REPO_ROOT = _SRC_PIXO.parent.parent                  # .../（仓库根）


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """隔离 shell 环境: 默认分支必须在受限门控生效前提下验证。"""
    monkeypatch.delenv("PIXO_ALLOW_RESTRICTED", raising=False)


def test_restricted_model_backends_gated_out_of_router_by_default(monkeypatch):
    """条目 1 关联约束: 受限后端默认不进路由; PIXO_ALLOW_RESTRICTED=1 放行。"""
    restricted = restricted_backend_names()
    # 台账登记在位 (tech_debt 点名 uniface/sapiens); 缺登记 = 合规台账欠账
    assert {"uniface", "sapiens"} <= restricted, (
        f"model_licenses.json 应将 uniface/sapiens 登记为 "
        f"internal_development_only, 实际 restricted={restricted!r}")

    reachable = MultiModelSegmenter().routed_backend_names()
    assert not (reachable & restricted), (
        f"默认构造下受限后端不应可达: 受限={sorted(restricted)}, "
        f"路由可达={sorted(reachable & restricted)}")

    # 放行机制在位: 显式放行后路由表恢复全量 (restricted 集合不再剔除)
    monkeypatch.setenv("PIXO_ALLOW_RESTRICTED", "1")
    assert MultiModelSegmenter().route_table == dict(ROUTE_TABLE)
    assert not ({"uniface", "sapiens"} & set(
        MultiModelSegmenter()._restricted)), "显式放行后不应再剔除受限后端"


def test_cleared_items_stay_cleared():
    """已清偿项防复活: YOLOE (条目1) / src/render shim (条目6) / VibranceStage
    废弃守卫 (条目8 t66 + 10b)。"""
    # 条目 1: YOLOE 适配器与其代码级引用不得复活 (注释/文档中的清偿说明允许)
    assert not (_SRC_PIXO / "vision" / "segmenters" / "yoloe.py").exists()
    assert "yoloe" not in {b.lower() for b in ROUTE_TABLE.values()}
    code_hit = []
    for py in _SRC_PIXO.rglob("*.py"):
        for lineno, line in enumerate(
                py.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "yoloe" not in line.lower() or line.lstrip().startswith("#"):
                continue
            if re.search(r"^\s*(from|import)\s", line, re.I) or \
                    "PIXO_SEGMENTER" in line:
                code_hit.append(f"{py.relative_to(_SRC_PIXO)}:{lineno}: {line}")
    assert not code_hit, f"YOLOE 代码级残留复发: {code_hit}"

    # 条目 6: src/render 兼容 shim 不得回归
    assert not _SRC_PIXO.parent.joinpath("render").exists(), (
        "src/render 兼容 shim 复发 (859082f 已移除, 统一 pixo.*)")

    # 条目 8/10b: VibranceStage 废弃占位的强制守卫在位
    from pixo.render.modules.reshape import VibranceStage
    with pytest.raises(NotImplementedError, match="colorcal"):
        VibranceStage().process(None)


def test_model_license_registry_paths_resolve():
    """条目 3: model_licenses.json 登记的模型路径与当前路径同步 (无悬空)。"""
    data = json.loads((_REPO_ROOT / "model_licenses.json").read_text(
        encoding="utf-8"))
    dangling = []
    for entry in data.get("models", []):
        for key in ("path", "local_path", "file"):
            rel = entry.get(key)
            if rel and not (_REPO_ROOT / rel).exists():
                dangling.append(f"{entry.get('name')}: {key}={rel}")
    assert not dangling, f"model_licenses.json 悬空路径 (登记未同步): {dangling}"
