"""build_project_graph 单元测试。

覆盖: 模块 id/相对导入解析/分层归属、import 边提取 (绝对/相对/第三方/stdlib/
嵌套懒加载/裸 import pixo)、Stage 注册与 dataflow (IDT/ODT/缺注册/未登记域
转换)、--merge (成功/冲突/非法片段/自动补 external_asset)、--check 幂等漂移,
以及真实仓库 src/pixo 的冒烟断言 (DEFAULT_STAGES/域契约/torch 隔离/边证据)。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "build_project_graph.py"
_spec = importlib.util.spec_from_file_location("build_project_graph", _SCRIPT)
bpg = importlib.util.module_from_spec(_spec)
sys.modules["build_project_graph"] = bpg  # dataclass 处理需要按名查模块
_spec.loader.exec_module(bpg)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_SRC = REPO_ROOT / "src" / "pixo"


# ---------------------------------------------------------------- 小工具
def _write_pkg(root: Path, files: dict) -> Path:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return root


EDGE_KEYS = ("from", "to", "line", "scope")


def _internal_edges(graph: dict) -> list:
    return [e for e in graph["edges"] if not e.get("external")]


def _find_edge(graph: dict, **kw) -> dict:
    for e in _internal_edges(graph):
        if all(e.get(k) == v for k, v in kw.items()):
            return e
    raise AssertionError(f"未找到边: {kw}")


# ---------------------------------------------------------------- 基础解析
def test_module_id_variants():
    assert bpg.module_id(Path("core/io.py")) == "core.io"
    assert bpg.module_id(Path("core/__init__.py")) == "core"
    assert bpg.module_id(Path("__init__.py")) == "pixo"  # 包根归一


def test_resolve_relative_levels():
    assert bpg._resolve_relative("render.core.io", False, 1) == "render.core"
    assert bpg._resolve_relative("render.core.io", False, 2) == "render"
    assert bpg._resolve_relative("render.core.io", False, 3) == ""
    assert bpg._resolve_relative("vision", True, 1) == "vision"
    # 文件模块 vision/base.py 的 `from ..x import y`: 宿主包 vision 再上一层 → 包根
    assert bpg._resolve_relative("vision.base", False, 2) == ""
    # 真实场景: render/modules/white_balance.py 的 `from ..pipeline.graph import ...`
    assert bpg._resolve_relative("render.modules.white_balance", False, 2) == "render"


def test_layer_of_nearest_package_ancestor():
    pkg_dirs = {"pixo", "render", "render.core", "render._native"}
    assert bpg.layer_of("render.core.io", pkg_dirs, False) == "render.core"
    assert bpg.layer_of("render.api", pkg_dirs, False) == "render"  # 散文件并入父包层
    assert bpg.layer_of("render", pkg_dirs, True) == "render"
    assert bpg.layer_of("render._native", pkg_dirs, True) == "render._native"
    assert bpg.layer_of("render.pipeline", pkg_dirs, False) == "render"  # 被遮蔽文件不冒充包层


# ---------------------------------------------------------------- import 边
@pytest.fixture()
def mini_pkg(tmp_path):
    return _write_pkg(tmp_path, {
        "__init__.py": '"""根包。"""\n',
        "alpha.py": (
            "import os\n"
            "import numpy as np\n"
            "import torch.nn as nn\n"
            "from . import beta\n"
            "from .beta import helper\n"
            "from .sub.gamma import G\n"
            "def f():\n"
            "    from .alpha import THING  # 嵌套懒加载\n"
            "    return THING\n"
        ),
        "beta.py": ("from pixo.alpha import THING\nTHING = 1\n"
                    "def helper():\n    return THING\n"
                    "def load_gamma():\n"
                    "    from .sub.gamma import G  # 嵌套跨模块懒加载\n"
                    "    return G\n"),
        "sub/__init__.py": "",
        "sub/gamma.py": "from ..alpha import THING\nG = 2\n",
    })


def test_extract_imports_classification_and_lines(mini_pkg):
    modules = {m.id: m for m in bpg.scan_package(mini_pkg)}
    alpha = modules["alpha"]
    sites = {(s.target, s.kind, s.scope): s for s in alpha.imports}
    assert ("os", "stdlib", "module") in sites
    assert ("numpy", "third_party", "module") in sites
    assert ("torch", "third_party", "module") in sites, "import torch.nn 应归一到 torch"
    assert ("sub.gamma", "pixo", "module") in sites
    assert ("alpha", "pixo", "nested") in sites, "函数内懒加载应标 nested"
    # alpha 有两条到 beta 的边 (from . import beta / from .beta import helper):
    # 行号 4 与 5, 各自带行内语句证据
    beta_lines = sorted(s.line for s in alpha.imports
                        if (s.target, s.kind, s.scope) == ("beta", "pixo", "module"))
    assert beta_lines == [4, 5]
    assert all("import" in s.stmt for s in alpha.imports)


def test_extract_imports_absolute_and_parent_relative(mini_pkg):
    modules = {m.id: m for m in bpg.scan_package(mini_pkg)}
    beta = modules["beta"]
    assert any(s.target == "alpha" and s.kind == "pixo" and s.line == 1
               for s in beta.imports)
    gamma = modules["sub.gamma"]
    assert any(s.target == "alpha" and s.kind == "pixo" and s.line == 1
               for s in gamma.imports), "level=2 相对导入应锚到包根"


def test_build_graph_internal_edges_and_external_nodes(mini_pkg):
    graph = bpg.build_graph(mini_pkg)
    e = _find_edge(graph, **{"from": "alpha", "to": "sub.gamma"})
    assert e["line"] == 6 and e["scope"] == "module"
    nested = _find_edge(graph, **{"from": "beta", "to": "sub.gamma"})
    assert nested["scope"] == "nested", "函数内跨模块懒加载应产出 nested 边"
    # 自引用不建边 (自环无跨模块信息, 建图规则刻意跳过)
    assert not [e for e in _internal_edges(graph) if e["from"] == e["to"]]
    ids = {n["id"] for n in graph["nodes"]}
    assert {"numpy", "torch"} <= ids, "第三方包应有 external 节点"
    for e in _internal_edges(graph):
        assert e["to"] in ids, f"内部边目标必须存在: {e}"
    assert graph["external"]["numpy"]["sites"][0]["module"] == "alpha"


def test_shadowed_module_detected(tmp_path):
    root = _write_pkg(tmp_path, {
        "__init__.py": "",
        "dup/__init__.py": '"""真包。"""\n',
        "dup.py": '"""被遮蔽的门面。"""\nfrom .dup import x\n',
    })
    graph = bpg.build_graph(root)
    assert graph["anomalies"]["shadowed_modules"] == ["dup"]
    shadow = next(n for n in graph["nodes"] if n["id"] == "dup" and n["kind"] == "module")
    assert shadow["shadowed"] is True


# ---------------------------------------------------------------- Stage 管线
PIPELINE_FILES = {
    "__init__.py": "",
    "render/__init__.py": '"""render。"""\n',
    "render/core/__init__.py": "",
    "render/core/io.py": "import rawpy\n\ndef decode_raw(p):\n    raise NotImplementedError\n",
    "render/pipeline/__init__.py": "",
    "render/pipeline/context.py": (
        'DOMAIN_LINEAR_CAM = "linear_cam"\n'
        'DOMAIN_LINEAR_RGB = "linear_rgb"\n'
        'DOMAIN_GAMMA_RGB = "gamma_rgb"\n'
    ),
    "render/pipeline/presets.py": (
        "from .graph import Pipeline\n"
        'DEFAULT_STAGES = ["exposure", "whitebalance", "tone"]\n'
    ),
    "render/pipeline/graph.py": (
        "class Pipeline:\n"
        "    def run_file(self, raw_path):\n"
        "        from pixo.render.core.io import decode_raw\n"
        "        img, raw = decode_raw(raw_path)\n"
        "        ctx.set_image(img, DOMAIN_LINEAR_CAM)\n"
        "        self.run(ctx)\n"
        "        if ctx.domain != DOMAIN_GAMMA_RGB:\n"
        "            raise RuntimeError('bad domain')\n"
        "        return (clip(out) * 255.0 + 0.5).astype(uint8)\n"
    ),
    "render/modules/__init__.py": "",
    "render/modules/exposure.py": (
        "from ..pipeline.graph import register_stage\n"
        "from ..pipeline.context import DOMAIN_LINEAR_CAM\n"
        '@register_stage("exposure", order=10,\n'
        "                domain_in=DOMAIN_LINEAR_CAM, domain_out=DOMAIN_LINEAR_CAM)\n"
        "class ExposureStage:\n    pass\n"
    ),
    "render/modules/white_balance.py": (
        "from ..pipeline.graph import register_stage\n"
        "from ..pipeline.context import DOMAIN_LINEAR_CAM, DOMAIN_LINEAR_RGB\n"
        '@register_stage("whitebalance", order=20,\n'
        "                domain_in=DOMAIN_LINEAR_CAM, domain_out=DOMAIN_LINEAR_RGB)\n"
        "class WhiteBalanceStage:\n    pass\n"
    ),
    "render/modules/tone_map.py": (
        "from ..pipeline.graph import register_stage\n"
        "from ..pipeline.context import DOMAIN_LINEAR_RGB, DOMAIN_GAMMA_RGB\n"
        '@register_stage("tone", order=30,\n'
        "                domain_in=DOMAIN_LINEAR_RGB, domain_out=DOMAIN_GAMMA_RGB)\n"
        "class ToneStage:\n    pass\n"
    ),
    "render/modules/extra.py": (
        "from ..pipeline.graph import register_stage\n"
        "from ..pipeline.context import DOMAIN_GAMMA_RGB\n"
        '@register_stage("bonus", order=99,\n'
        "                domain_in=DOMAIN_GAMMA_RGB, domain_out=DOMAIN_GAMMA_RGB)\n"
        "class BonusStage:\n    pass\n"
    ),
}


@pytest.fixture()
def render_pkg(tmp_path):
    return _write_pkg(tmp_path, PIPELINE_FILES)


def test_parse_pipeline_domains_and_stages(render_pkg):
    graph = bpg.build_graph(render_pkg)
    pl = graph["pipeline"]
    assert pl["domains"]["linear_cam"]["constant"] == "DOMAIN_LINEAR_CAM"
    assert pl["domains"]["linear_cam"]["line"] == 1
    assert pl["default_stages"]["names"] == ["exposure", "whitebalance", "tone"]
    assert pl["default_stages"]["line"] == 2
    by_name = {s["name"]: s for s in pl["stages"]}
    assert by_name["whitebalance"]["domain_in"] == "linear_cam"
    assert by_name["whitebalance"]["domain_out"] == "linear_rgb"
    assert by_name["bonus"]["order"] == 99, "DEFAULT 之外的注册 Stage 也要收录"


def test_dataflow_decode_stages_encode(render_pkg):
    graph = bpg.build_graph(render_pkg)
    steps = graph["pipeline"]["dataflow"]
    assert [s["kind"] for s in steps] == ["source", "io", "stage", "stage",
                                          "stage", "io"]
    assert steps[0]["name"] == "RAW"
    decode = steps[1]
    assert decode["module"] == "render.core.io" and decode["func"] == "decode_raw"
    assert decode["domain_out"] == "linear_cam"
    assert "graph.py" in decode["evidence"] or ":3" in decode["evidence"]
    phases = {s["name"]: s.get("transition_phase") for s in steps if s["kind"] == "stage"}
    assert phases["whitebalance"] == "IDT"
    assert phases["tone"] == "ODT"
    assert phases["exposure"] is None
    encode = steps[-1]
    assert encode["domain_in"] == "gamma_rgb"
    assert "bonus" in encode["note"]


def test_dataflow_missing_stage_registration(tmp_path):
    files = dict(PIPELINE_FILES)
    files["render/pipeline/presets.py"] = (
        'DEFAULT_STAGES = ["exposure", "ghost"]\n'
    )
    graph = bpg.build_graph(_write_pkg(tmp_path, files))
    steps = graph["pipeline"]["dataflow"]
    assert steps[-2]["kind"] == "missing_stage"
    assert steps[-2]["name"] == "ghost"
    assert any("ghost" in a for a in graph["anomalies"]["pipeline"])


def test_dataflow_unregistered_domain_transition(tmp_path):
    files = dict(PIPELINE_FILES)
    files["render/modules/white_balance.py"] = (
        "from ..pipeline.graph import register_stage\n"
        "from ..pipeline.context import DOMAIN_LINEAR_CAM, DOMAIN_GAMMA_RGB\n"
        '@register_stage("whitebalance", order=20,\n'
        "                domain_in=DOMAIN_LINEAR_CAM, domain_out=DOMAIN_GAMMA_RGB)\n"
        "class WhiteBalanceStage:\n    pass\n"
    )
    graph = bpg.build_graph(_write_pkg(tmp_path, files))
    wb = next(s for s in graph["pipeline"]["dataflow"]
              if s.get("name") == "whitebalance")
    assert wb["transition_phase"] is None, "未登记的转换不得编造 phase"
    assert any("whitebalance" in a for a in graph["anomalies"]["pipeline"])


def test_missing_initial_domain_evidence(tmp_path):
    files = dict(PIPELINE_FILES)
    files["render/pipeline/graph.py"] = "class Pipeline:\n    pass\n"
    with pytest.raises(SystemExit, match="set_image"):
        bpg.build_graph(_write_pkg(tmp_path, files))


# ---------------------------------------------------------------- --merge
def _base_graph(tmp_path):
    root = _write_pkg(tmp_path, {"__init__.py": ""})
    return bpg.build_graph(root), root


def test_merge_fragment_success(tmp_path):
    graph, _ = _base_graph(tmp_path)
    frag = tmp_path / "frag.json"
    frag.write_text(json.dumps({
        "namespace": "t15-frontend",
        "nodes": [{"id": "frontend/App.tsx", "kind": "asset"}],
        "edges": [{"from": "frontend/App.tsx", "to": "docs/graph.json",
                   "type": "consumes"}],
    }), encoding="utf-8")
    merged = bpg.merge_fragments(graph, [str(frag)])
    ids = {n["id"] for n in merged["nodes"]}
    assert "frontend/App.tsx" in ids and "docs/graph.json" in ids
    asset = next(n for n in merged["nodes"] if n["id"] == "docs/graph.json")
    assert asset["kind"] == "external_asset" and asset["origin"] == "t15-frontend"
    assert merged["merge"]["fragments"][0]["edges_added"] == 1


def test_merge_fragment_id_conflict_exits(tmp_path):
    graph, _ = _base_graph(tmp_path)
    frag = tmp_path / "conflict.json"
    frag.write_text(json.dumps({"nodes": [{"id": "pixo"}], "edges": []}),
                    encoding="utf-8")
    with pytest.raises(SystemExit, match="冲突"):
        bpg.merge_fragments(graph, [str(frag)])


def test_merge_fragment_invalid(tmp_path):
    graph, _ = _base_graph(tmp_path)
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("not json", encoding="utf-8")
    with pytest.raises(SystemExit, match="合法 JSON"):
        bpg.merge_fragments(graph, [str(bad_json)])
    bad_shape = tmp_path / "shape.json"
    bad_shape.write_text(json.dumps({"nodes": "nope"}), encoding="utf-8")
    with pytest.raises(SystemExit, match="nodes/edges"):
        bpg.merge_fragments(graph, [str(bad_shape)])
    with pytest.raises(SystemExit, match="不存在"):
        bpg.merge_fragments(graph, [str(tmp_path / "missing.json")])


# ---------------------------------------------------------------- CLI: --check
def test_main_generate_and_check(tmp_path):
    root = _write_pkg(tmp_path / "src", {"__init__.py": "",
                                         "m.py": "import os\n"})
    out = tmp_path / "graph.json"
    md = tmp_path / "graph.md"
    argv = ["--root", str(root), "--out", str(out), "--md", str(md)]
    assert bpg.main(argv) == 0
    assert out.is_file() and md.is_file()
    # 幂等: 重生成后 --check 应无漂移 (generated_at 不参与比较)
    assert bpg.main([*argv, "--check"]) == 0
    # 漂移: 篡改 JSON → 退出 1
    data = json.loads(out.read_text(encoding="utf-8"))
    data["schema_version"] = "9.9"
    out.write_text(json.dumps(data), encoding="utf-8")
    assert bpg.main([*argv, "--check"]) == 1
    # 漂移: 篡改 MD → 退出 1 (先恢复 JSON)
    assert bpg.main(argv) == 0
    md.write_text("# drifted\n", encoding="utf-8")
    assert bpg.main([*argv, "--check"]) == 1


def test_main_bad_root_errors(tmp_path):
    with pytest.raises(SystemExit):
        bpg.main(["--root", str(tmp_path / "nope"),
                  "--out", str(tmp_path / "g.json"), "--no-md"])


# ---------------------------------------------------------------- 真实仓库冒烟
@pytest.mark.skipif(not REAL_SRC.is_dir(), reason="仓库 src/pixo 不存在")
def test_real_repo_graph_invariants():
    graph = bpg.build_graph(REAL_SRC)
    assert graph["source"]["files_scanned"] >= 150
    assert graph["anomalies"]["shadowed_modules"] == ["render.pipeline"]
    assert graph["anomalies"]["parse_errors"] == []

    pl = graph["pipeline"]
    assert pl["default_stages"]["names"] == [
        "exposure", "whitebalance", "compose", "huesat", "tone", "dehaze",
        "clarity", "colorcal", "calibration", "hsl", "split_tone", "skin",
        "stylize", "refine"]
    by_name = {s["name"]: s for s in pl["stages"]}
    assert by_name["whitebalance"]["domain_in"] == "linear_cam"
    assert by_name["whitebalance"]["domain_out"] == "linear_rgb"
    assert by_name["tone"]["domain_in"] == "linear_rgb"
    assert by_name["tone"]["domain_out"] == "gamma_rgb"
    # DEFAULT_STAGES 之外还有备用注册位
    assert {"denoise", "sharpen", "vibrance"} <= set(by_name)

    steps = pl["dataflow"]
    assert steps[0]["name"] == "RAW"
    assert steps[1]["func"] == "decode_raw" and steps[1]["domain_out"] == "linear_cam"
    assert steps[-1]["name"] == "encode" and steps[-1]["domain_out"] == "uint8_srgb"
    stage_steps = [s for s in steps if s["kind"] == "stage"]
    assert [s["name"] for s in stage_steps] == pl["default_stages"]["names"]
    phases = {s["name"]: s["transition_phase"] for s in stage_steps}
    assert phases["whitebalance"] == "IDT" and phases["tone"] == "ODT"
    assert all(p is None for n, p in phases.items()
               if n not in ("whitebalance", "tone"))

    # 边证据完整性: 内部边目标都存在、行号为正、语句非空
    ids = {n["id"] for n in graph["nodes"]}
    for e in _internal_edges(graph):
        assert e["to"] in ids, e
        assert e["line"] > 0 and e["stmt"], e

    # torch 隔离: 全部懒加载嵌套 import, 且只出现在 vision 层
    torch_info = graph["external"]["torch"]
    assert torch_info["all_nested"] is True
    assert torch_info["sites"], "torch 使用点不应为空"
    assert all(s["module"].startswith("vision.") for s in torch_info["sites"])
    assert set(torch_info["layers"]) <= {"vision", "vision.segmenters"}

    md = bpg.render_md(graph, "root=test")
    assert "## 外部依赖清单" in md and "```mermaid" in md
    assert "IDT" in md and "ODT" in md
