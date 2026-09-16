"""docs/tech_debt.md 限定条件的运行时断言（tech-debt 批次）。

把清单中『已清偿』『仅在 YY 条件下可用』类条目固化为可执行断言——
被意外触发（清偿复发/限定失效）即告警；纯人决策与条件触发类条目
（DNG clean-room 复审、门禁口径扩展、外部评审 backlog 四个子项等）
不可机器断言，不在此列。

覆盖映射（条目号按 docs/tech_debt.md）：
  - test_restricted_model_backends_gated_out_of_router_by_default
      ← 条目 1 关联约束：usage=internal_development_only 的后端
        （uniface/sapiens）默认不进 multi 路由，PIXO_ALLOW_RESTRICTED=1
        显式放行
  - test_cleared_items_stay_cleared
      ← 条目 1（YOLOE AGPL 清偿防复活）+ 条目 6（src/render shim 已移除）
        + 条目 8/10b（VibranceStage 废弃占位，显式调用抛 NotImplementedError）
  - test_model_license_registry_paths_resolve
      ← 条目 3（两个许可台账登记路径与当前路径同步，防悬空复发）**R22 加固**
  - test_model_license_registry_guard_is_falsifiable
      ← 条目 3 负控（证明断言非空转：路径改坏 ⇒ 必红）
  - test_vision_model_path_or_source_resolution_rules
      ← 条目 3（`vision_models.json` 的 `path_or_source` 解析规则）
  - test_vision_models_guanlan_root_env_branch_is_pending
      ← 条目 3 负控（`$GUANLAN_ROOT` 形态在环境变量缺失时必须判「待核验」）

R22 #3 加固说明（原断言空转的根因）：
  旧实现只查根台账 `model_licenses.json` 的 `path`/`local_path`/`file` 三键，
  而该文件 **6 条全部用 `files`（数组）登记** ⇒ 实际被检查路径数 = 0，断言空转。
  加固后的四层：
    ① `files[]` 逐项相对仓库根存在性（悬空即红）；
    ② 交付形态与事实一致：`delivery=in_repo` ⇒ `files` 必须非空；
       `files: []` 只允许出现在带显式外部标记（`delivery=external_*`）且
       `notes` 非空的条目上；期望表 `_MUST_BE_IN_REPO` 钉死唯一的仓内交付物；
    ③ `vision_models.json` 的 `path_or_source` 按写死的解析规则处理
       （见该用例 docstring），`$VAR` 未设置 ⇒ 判「待核验」并报红，不静默通过；
    ④ 负控：临时副本改坏路径 ⇒ 生产断言必红（不触碰仓库文件）。
"""
from __future__ import annotations

import json
import os
import re
import sys
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

# 台账文件位置（模块常量：负控用例用 monkeypatch 换成临时副本，不碰仓库文件）
_LICENSE_PATH = _REPO_ROOT / "model_licenses.json"
_VISION_MODELS_PATH = _SRC_PIXO / "manifests" / "vision_models.json"

# 交付形态显式标记（R22 层 2）：in_repo = 随本仓/随 wheel 分发的仓内文件；
# external_* = 运行时外部下载（不落仓）——后者才允许 files: []。
_IN_REPO = "in_repo"
_EXTERNAL_DELIVERIES = ("external_hub_download", "external_pip_download")

# 期望表（R22 层 2）：声明「随本仓/随 wheel 分发」的条目 —— files[] 必须非空。
# 依据 THIRD_PARTY_NOTICES.md §3 M1 + §5（aesthetic_scorer.pt 随 wheel 分发）。
# 其余条目（clip/uniface/rfdetr/segformer/sapiens）为运行时下载，不落仓。
_MUST_BE_IN_REPO = {"aesthetic_scorer.pt"}

# path_or_source 中的仓内路径形态（相对仓库根 / 盘符绝对路径）
_REPO_PATH_RE = re.compile(r"^([A-Za-z]:[\\/]|\.{1,2}[\\/]|resources[\\/]|src[\\/]|configs[\\/])")


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


# ---------------------------------------------------------------------------
# 条目 3（R22 加固）：许可台账登记路径 + 交付形态一致性
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _check_model_licenses(path: Path | None = None,
                          root: Path | None = None) -> dict:
    """根台账 `model_licenses.json` 检查（层 ① 悬空 + 层 ② 交付形态一致）。

    返回 {"dangling": [...], "incomplete": [...], "checked_paths": int}。
    `checked_paths` 供「断言非空转」自检（== 0 时该用例本身失去意义）。
    """
    path = Path(path or _LICENSE_PATH)
    root = Path(root or _REPO_ROOT)
    entries = _load_json(path).get("models", [])
    dangling: list[str] = []
    incomplete: list[str] = []
    checked = 0
    for entry in entries:
        name = entry.get("name", "?")
        files = entry.get("files")
        delivery = entry.get("delivery")
        if not isinstance(files, list):
            incomplete.append(
                f"{name}: files 必须是列表, 实际 {type(files).__name__}")
            continue
        if delivery not in (_IN_REPO, *_EXTERNAL_DELIVERIES):
            incomplete.append(
                f"{name}: 缺显式交付形态标记 delivery（允许 "
                f"{_IN_REPO!r} / {list(_EXTERNAL_DELIVERIES)}），实际 {delivery!r}")
            continue
        for rel in files:
            checked += 1
            if not (root / rel).exists():
                dangling.append(f"{name}: files={rel}（相对仓库根不存在）")
        if delivery == _IN_REPO and not files:
            incomplete.append(
                f"{name}: delivery=in_repo（声明仓内/随 wheel 交付）但 files 为空")
        if delivery != _IN_REPO:
            if files:
                incomplete.append(
                    f"{name}: delivery={delivery}（外部下载）却登记了仓内路径 {files}")
            if not str(entry.get("notes") or "").strip():
                incomplete.append(f"{name}: 外部交付条目缺 notes 原因说明")
    return {"dangling": dangling, "incomplete": incomplete,
            "checked_paths": checked}


def test_model_license_registry_paths_resolve():
    """条目 3（R22 加固）: 许可台账登记的仓内路径与当前路径同步（无悬空），
    且交付形态（in_repo / external_*）与 files[] 事实一致。

    覆盖：`files[]` 逐项相对仓库根存在性；`delivery=in_repo` ⇒ 非空；
    外部条目的显式标记 + notes。不覆盖：法律判断本身（许可条款真伪 = 人工核验，
    THIRD_PARTY_NOTICES §7 速查表）。
    """
    result = _check_model_licenses()
    assert result["checked_paths"] >= 1, (
        "断言空转：model_licenses.json 无任何 files[] 路径被检查（条目不完整）")
    assert not result["dangling"], (
        f"model_licenses.json 台账悬空路径（登记未同步）: {result['dangling']}")
    assert not result["incomplete"], (
        f"model_licenses.json 交付形态登记不一致: {result['incomplete']}")

    # 层 ② 期望表：声明随本仓/随 wheel 分发的条目必须登记非空 files
    by_name = {e.get("name"): e for e in _load_json(_LICENSE_PATH)["models"]}
    for name in sorted(_MUST_BE_IN_REPO):
        entry = by_name.get(name)
        assert entry is not None, (
            f"期望随本仓交付的条目 {name!r} 未登记（应登记文件路径）")
        assert entry.get("delivery") == _IN_REPO and entry.get("files"), (
            f"{name!r} 应登记为 delivery={_IN_REPO} 且 files 非空，实际 "
            f"delivery={entry.get('delivery')!r} files={entry.get('files')!r}")


def test_model_license_registry_guard_is_falsifiable(tmp_path, monkeypatch):
    """条目 3 负控（层 ④）: 把 aesthetic_scorer.pt 的路径改成不存在的值
    ⇒ 生产断言 `test_model_license_registry_paths_resolve` **必红**。

    用临时副本 + monkeypatch 模块常量，**不触碰仓库文件**（负控仅证明守卫
    可被证伪，即断言非空转）。
    """
    data = _load_json(_LICENSE_PATH)
    mutated = 0
    for entry in data["models"]:
        if entry.get("name") == "aesthetic_scorer.pt":
            entry["files"] = ["resources/models/aesthetic/__不存在__.pt"]
            mutated += 1
    assert mutated == 1, "负控前置失败：model_licenses.json 未找到 aesthetic_scorer.pt"
    bad = tmp_path / "model_licenses.json"
    bad.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "_LICENSE_PATH", bad)
    with pytest.raises(AssertionError, match="悬空"):
        test_model_license_registry_paths_resolve()


# ---------------------------------------------------------------------------
# 条目 3（R22 加固）：vision_models.json 的 path_or_source 解析规则
# ---------------------------------------------------------------------------

def _classify_path_or_source(raw: str) -> tuple:
    """`path_or_source` 形态分类：

    - `$VAR/相对路径` → ("env", 变量名, 相对路径)
    - 仓内相对路径 / 盘符绝对路径 → ("repo", 路径字符串)
    - 其他（外部来源描述，如 "HuggingFace 缓存 ..."）→ ("external", 原字符串)
    """
    text = str(raw).strip()
    if text.startswith("$"):
        var, _, rest = text[1:].partition("/")
        return ("env", var, rest)
    if _REPO_PATH_RE.match(text):
        return ("repo", text)
    return ("external", text)


def _check_vision_model_paths(path: Path | None = None,
                              root: Path | None = None,
                              env: dict | None = None) -> dict:
    """`vision_models.json` 检查（层 ③）。

    返回 {"dangling": [...], "pending": [...], "unmarked": [...],
          "checked_paths": int}。`pending` = `$VAR` 解析不了 ⇒ 「待核验」，
    由用例显式报红（**不静默通过**）。
    """
    env = os.environ if env is None else env
    root = Path(root or _REPO_ROOT)
    entries = _load_json(Path(path or _VISION_MODELS_PATH)).get("models", [])
    dangling: list[str] = []
    pending: list[str] = []
    unmarked: list[str] = []
    checked = 0
    for entry in entries:
        mid = entry.get("id", "?")
        kind, *rest = _classify_path_or_source(entry.get("path_or_source"))
        if kind == "external":
            if entry.get("delivery") not in _EXTERNAL_DELIVERIES:
                unmarked.append(
                    f"{mid}: path_or_source={entry.get('path_or_source')!r} 非路径形态，"
                    f"但未标记外部交付（delivery={entry.get('delivery')!r}）")
            continue
        if kind == "env":
            var, rel = rest[0], rest[1]
            base = env.get(var)
            if not base:
                pending.append(
                    f"{mid}: path_or_source 依赖环境变量 ${var}（未设置）⇒ 待核验")
                continue
            target = Path(base) / rel
        else:
            target = root / rest[0]
        checked += 1
        if not target.exists():
            dangling.append(f"{mid}: path_or_source 解析为 {target} 但文件不存在")
    return {"dangling": dangling, "pending": pending, "unmarked": unmarked,
            "checked_paths": checked}


def test_vision_model_path_or_source_resolution_rules():
    """条目 3（R22 加固）: `vision_models.json` 的 `path_or_source` 解析规则。

    规则（写死在此，防后人误读）：
      1. `$VAR/相对路径` → 以环境变量 `VAR` 为基座解析；**`VAR` 未设置时判
         「待核验」并报红**，绝不静默通过（旧台账的
         `$GUANLAN_ROOT/models/aesthetic_scorer.pt` 即此形态；R22 已改为仓内
         相对路径 `resources/models/aesthetic/aesthetic_scorer.pt`）。
      2. 仓内相对路径（`resources/`、`src/`、`./`、`../`）或盘符绝对路径
         → 必须存在。
      3. 其他字符串（如 "HuggingFace 缓存 openai/clip-vit-base-patch32"）视为
         外部来源描述 ⇒ 条目必须带 `delivery=external_hub_download|external_pip_download`。
    """
    result = _check_vision_model_paths()
    assert result["checked_paths"] >= 1, (
        "断言空转：vision_models.json 无任何可解析路径被检查")
    assert not result["dangling"], (
        f"vision_models.json 路径悬空: {result['dangling']}")
    assert not result["pending"], (
        f"vision_models.json 待核验（显式报告，非静默通过）: {result['pending']}")
    assert not result["unmarked"], (
        f"vision_models.json 外部来源未显式标记: {result['unmarked']}")


def test_vision_models_guanlan_root_env_branch_is_pending(tmp_path, monkeypatch):
    """条目 3 负控（层 ③）: `$GUANLAN_ROOT` 形态在环境变量缺失时**必须判
    「待核验」**（老实现会静默跳过，本用例钉死该分支的行为）。"""
    doc = {
        "schema_version": "1.0",
        "models": [{
            "id": "legacy-env-path",
            "purpose": "负控",
            "path_or_source": "$GUANLAN_ROOT/models/aesthetic_scorer.pt",
            "license": "需核验",
            "publishable": False,
            "pixo_status": "legacy",
        }],
    }
    legacy = tmp_path / "vision_models.json"
    legacy.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "GUANLAN_ROOT"}
    result = _check_vision_model_paths(path=legacy, env=env)
    assert result["pending"], "未设置 $GUANLAN_ROOT 时不得静默通过，应判「待核验」"
    assert "待核验" in result["pending"][0]
    assert "GUANLAN_ROOT" in result["pending"][0]
