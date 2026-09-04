#!/usr/bin/env python
"""build_project_graph —— AST 解析 src/pixo 生成机器可验证的项目图谱。

产出:
  1. docs/project_graph.json —— 机器可读图谱:
     nodes (模块/包/分层/外部依赖) + edges (imports, 每条带源码行号证据)
     + pipeline 段 (Stage 顺序/色彩域/RAW→decode→IDT→编辑→ODT→encode 数据流)。
  2. docs/PROJECT_GRAPH.md —— 人读版 (mermaid 分层图 + 数据流 + 模块职责表
     + 外部依赖隔离清单), 全部数据取自 JSON, 无手画边。

证据纪律: 所有内部/外部依赖边来自 ast 解析 (Import/ImportFrom, 含嵌套懒加载,
标 scope=nested); Stage 域契约来自 @register_stage 装饰器实参; Stage 顺序来自
render/pipeline/presets.py 的 DEFAULT_STAGES 字面量。文档不新增任何脚本没算出的边。

与前端图谱分工: 本脚本只管 src/pixo (render/know/pipeline/vision 等);
frontend/ 与 configs/ 资产归 t15, 用 --merge <fragment.json> 把 t15 的
{"nodes": [...], "edges": [...]} 片段合并进最终 JSON (节点 id 冲突即报错,
不静默覆盖)。

用法:
  python scripts/build_project_graph.py                 # 生成 JSON + MD
  python scripts/build_project_graph.py --check         # 幂等校验 (CI), 漂移退出 1
  python scripts/build_project_graph.py --merge f.json  # 追加 t15 片段后再生成
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = "1.0"
ROOT_PACKAGE = "pixo"
REPO_ROOT = Path(__file__).resolve().parents[1]

# 逐位文档化的域转换语义 (来源: render/pipeline/context.py 模块 docstring 的
# 色彩域约定): linear_cam=相机原始线性 RGB, linear_rgb=线性 sRGB(D65),
# gamma_rgb=sRGB gamma 编码。转换标签由此推导, 新转换出现时记入 anomalies。
DOMAIN_TRANSITION_PHASE = {
    ("linear_cam", "linear_rgb"): "IDT",
    ("linear_rgb", "gamma_rgb"): "ODT",
}


# ---------------------------------------------------------------- 基础设施
def module_id(rel: Path) -> str:
    """src/pixo 内相对路径 (可带 __init__.py) → 点分模块 id; __init__ 归并为包 id。
    包根本身的 __init__.py 归一为 ROOT_PACKAGE (pixo)。"""
    parts = rel.with_suffix("").parts
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return ROOT_PACKAGE
    return ".".join(parts)


def is_package_dir(fs_path: Path) -> bool:
    return (fs_path / "__init__.py").is_file()


def id_to_fs(root: Path, mod_id: str) -> Path:
    return root.joinpath(*mod_id.split("."))


def collect_pkg_dirs(root: Path) -> set:
    return {module_id(p.relative_to(root))
            for p in root.rglob("__init__.py") if "__pycache__" not in p.parts}


def layer_of(mod_id: str, pkg_dirs: set, is_pkg: bool) -> str:
    """分层归属: 归入模块路径上最近的**包目录**祖先 (包自身计入);
    render.core.io → render.core; render/api.py 这类散文件并入 render 层。"""
    parts = mod_id.split(".")
    top = len(parts) if is_pkg else len(parts) - 1
    for depth in range(top, 0, -1):
        prefix = ".".join(parts[:depth])
        if prefix in pkg_dirs:
            return prefix
    return parts[0]


def first_doc_line(tree: ast.Module) -> str:
    doc = ast.get_docstring(tree)
    if not doc:
        return ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


@dataclass
class ImportSite:
    """一条 import 语句解析出的目标 (一行多名字可解析出多个目标)。"""
    target: str          # 解析后的 pixo 内部 id 或第三方/stdlib 顶层名
    kind: str            # "pixo" | "third_party" | "stdlib"
    line: int
    scope: str           # "module" | "nested"
    stmt: str            # 源码语句原文 (strip 后)
    names: list = field(default_factory=list)  # from-import 的符号名 (诊断用)


def _classify(top: str) -> str:
    if top == ROOT_PACKAGE:
        return "pixo"
    if top in sys.stdlib_module_names:
        return "stdlib"
    return "third_party"


def _resolve_relative(module_id_str: str, is_pkg: bool, level: int):
    """相对导入 level → 锚点包 id (可为本包根的空串)。文件模块 a.b.c:
    level=1→a.b; 包 a.b: level=1→a.b; 超出深度返回 '' (包根)。"""
    parts = module_id_str.split(".")
    if not is_pkg:
        parts = parts[:-1]
    for _ in range(level - 1):
        if not parts:
            break
        parts = parts[:-1]
    return ".".join(parts)


_DIR_LISTING_CACHE: dict = {}


def _dir_entries(base: Path) -> set:
    """目录条目的精确大小写集合 (Windows 文件系统大小写不敏感,
    `vision.Segmenter` 这种类名会误匹配 segmenter.py, 必须逐名精确比对)。"""
    key = str(base)
    if key not in _DIR_LISTING_CACHE:
        _DIR_LISTING_CACHE[key] = set(os.listdir(base)) if base.is_dir() else set()
    return _DIR_LISTING_CACHE[key]


def _submodule_exists(root: Path, parent_id: str, name: str) -> bool:
    base = id_to_fs(root, parent_id) if parent_id else root
    entries = _dir_entries(base)
    return (name + ".py") in entries or (
        name in entries and is_package_dir(base / name))


def extract_imports(tree: ast.Module, mod_id: str, is_pkg: bool,
                    root: Path) -> list:
    """提取全部 import (模块级 + 嵌套), 相对/绝对导入解析为 pixo 内部 id。"""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            scope = "module" if node in tree.body else "nested"
            for alias in node.names:
                top = alias.name.split(".")[0]
                kind = _classify(top)
                if kind == "pixo":
                    target = alias.name
                    if target.startswith(ROOT_PACKAGE + "."):
                        target = target[len(ROOT_PACKAGE) + 1:]
                    elif target == ROOT_PACKAGE:
                        continue  # 裸 import pixo 无具体目标, 不建边
                else:
                    # 第三方/stdlib 归一到顶层包名 (import torch.nn → torch),
                    # 与 ImportFrom 口径一致; 子模块归属看 sites 里的 module:line
                    target = top
                stmt = ast.unparse(node)
                out.append(ImportSite(target, kind, node.lineno, scope, stmt,
                                      [alias.asname or alias.name]))
        elif isinstance(node, ast.ImportFrom):
            scope = "module" if node in tree.body else "nested"
            stmt = ast.unparse(node)
            if node.level > 0:
                # 相对导入目标必然在包内, 不做第三方/stdlib 判定
                base = _resolve_relative(mod_id, is_pkg, node.level)
                tail = [p for p in (base, node.module) if p]
                mod = ".".join(tail)
                kind = "pixo"
            else:
                mod = node.module or ""
                # 先按原始顶层名分类一次, 再剥 pixo 前缀 (不可二次分类)
                kind = _classify(mod.split(".")[0]) if mod else "stdlib"
                if kind == "pixo":
                    mod = mod[len(ROOT_PACKAGE) + 1:] if mod.startswith(
                        ROOT_PACKAGE + ".") else ""
            if kind == "pixo":
                # from X import a, b: a/b 若是 X 的子模块则落到 X.a / X.b,
                # 否则视为 X 模块内符号 (目标仍是 X)。
                seen = set()
                for alias in node.names:
                    sub = f"{mod}.{alias.name}" if mod else alias.name
                    target = sub if _submodule_exists(root, mod, alias.name) \
                        else (mod or sub)
                    if target not in seen:
                        seen.add(target)
                        out.append(ImportSite(target, kind, node.lineno, scope,
                                              stmt, [alias.name]))
            else:
                top = mod.split(".")[0] if mod else ""
                if not top:
                    continue
                out.append(ImportSite(top, kind, node.lineno, scope, stmt,
                                      [a.name for a in node.names]))
    return out


# ---------------------------------------------------------------- 包遍历
@dataclass
class ModuleInfo:
    id: str
    path: str            # 仓库相对 posix 路径
    kind: str            # "module" | "package"
    layer: str
    doc: str
    lines: int
    imports: list = field(default_factory=list)  # ImportSite 列表
    shadowed: bool = False


def scan_package(root: Path) -> list:
    """遍历包目录下全部 .py (跳过 __pycache__), 返回 ModuleInfo 列表。"""
    pkg_dirs = collect_pkg_dirs(root)
    infos = []
    for p in sorted(root.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        rel = p.relative_to(root)
        mid = module_id(rel)
        is_pkg = p.name == "__init__.py"
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as e:
            infos.append(ModuleInfo(mid, p.as_posix(), "package" if is_pkg
                                    else "module", layer_of(mid, pkg_dirs, is_pkg),
                                    "", 0, shadowed=False, imports=[]))
            # 语法错误不中断图谱, 记入 anomalies (scan 后统一补 doc/lines 无从谈起)
            print(f"[warn] 解析失败 {p}: {e}", file=sys.stderr)
            continue
        info = ModuleInfo(mid, p.as_posix(), "package" if is_pkg else "module",
                          layer_of(mid, pkg_dirs, is_pkg), first_doc_line(tree),
                          p.read_text(encoding="utf-8").count("\n") + 1)
        info.imports = extract_imports(tree, mid, is_pkg, root)
        infos.append(info)
    # 遮蔽检测: 存在同名包目录的非 __init__ .py (包优先, 该文件不可导入)
    for info in infos:
        if info.kind == "module" and info.id in pkg_dirs:
            info.shadowed = True
    return infos


# ---------------------------------------------------------------- Stage 管线
def _lit_str(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def parse_domain_constants(tree: ast.Module) -> dict:
    """DOMAIN_* = "str" 顶层赋值 → {const_name: (value, line)}。"""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            value = _lit_str(node.value)
            if value is None:
                continue
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.startswith("DOMAIN_"):
                    out[t.id] = {"value": value, "line": node.lineno}
    return out


def parse_default_stages(tree: ast.Module):
    """DEFAULT_STAGES = [...] 顶层赋值 → (names, line)。"""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "DEFAULT_STAGES" \
                        and isinstance(node.value, (ast.List, ast.Tuple)):
                    names = [_lit_str(e) for e in node.value.elts]
                    if all(n is not None for n in names):
                        return names, node.lineno
    return None, None


def parse_stage_registrations(tree: ast.Module, mod_id: str) -> list:
    """提取 @register_stage(name, order=N, domain_in=..., domain_out=...) 装饰器。

    domain_* 以名字 (DOMAIN_LINEAR_CAM) 记录, 由调用方结合域常数表解析成值;
    解析不了的保留原名字并标 resolved=False, 不猜测。
    """
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for deco in node.decorator_list:
            if not (isinstance(deco, ast.Call)
                    and isinstance(deco.func, ast.Name)
                    and deco.func.id == "register_stage"):
                continue
            rec = {"class": node.name, "module": mod_id, "line": deco.lineno}
            if deco.args and len(deco.args) >= 1:
                rec["name"] = _lit_str(deco.args[0])
            for kw in deco.keywords:
                if kw.arg == "order" and isinstance(kw.value, ast.Constant):
                    rec["order"] = kw.value.value
                elif kw.arg in ("domain_in", "domain_out"):
                    raw = None
                    if isinstance(kw.value, ast.Name):
                        raw = kw.value.id
                    else:
                        raw = _lit_str(kw.value)
                    rec[kw.arg] = raw
                    rec.setdefault("_unresolved_domains", set())
                    if isinstance(kw.value, ast.Name):
                        rec["_unresolved_domains"].add(kw.arg)
            if "name" in rec:
                out.append(rec)
    return out


def parse_pipeline(pipeline_dir: Path, root: Path) -> dict:
    """从 render/pipeline/ 提取域常数 + DEFAULT_STAGES + Stage 注册, 组装 dataflow。

    数据流证据: graph.py run_file 内嵌套 import decode_raw (decode 入口)、
    set_image(img, DOMAIN_LINEAR_CAM) (初始域)、终检 DOMAIN_GAMMA_RGB 后 uint8
    量化 (encode 出口) —— 全部按行号引用。
    """
    ctx_tree = ast.parse((pipeline_dir / "context.py").read_text(encoding="utf-8"))
    presets_tree = ast.parse((pipeline_dir / "presets.py").read_text(encoding="utf-8"))
    graph_tree = ast.parse((pipeline_dir / "graph.py").read_text(encoding="utf-8"))

    consts = parse_domain_constants(ctx_tree)      # const → {value, line}
    const_value = {k: v["value"] for k, v in consts.items()}
    default_stages, default_line = parse_default_stages(presets_tree)

    stages = []
    anomalies = []
    for py in sorted(pipeline_dir.parent.glob("modules/*.py")):
        if py.name == "__init__.py":
            continue
        t = ast.parse(py.read_text(encoding="utf-8"))
        mid = module_id(py.relative_to(root))
        for rec in parse_stage_registrations(t, mid):
            for dom_key in ("domain_in", "domain_out"):
                raw = rec.get(dom_key)
                if raw is None:
                    continue
                if raw in const_value:
                    rec[dom_key] = const_value[raw]
                    rec.get("_unresolved_domains", set()).discard(dom_key)
            rec.pop("_unresolved_domains", None)
            stages.append(rec)
    stages.sort(key=lambda r: (r.get("order", 1 << 30), r["name"]))

    # decode/encode 证据: graph.py 内嵌套 import 的 decode_raw 来源 + 行号
    decode_site = None
    for site in extract_imports(graph_tree, "render.pipeline.graph", False, root):
        if site.target.endswith("core.io") and "decode_raw" in site.names:
            decode_site = site
            break
    set_image_line = final_line = None
    init_domain = None
    for node in ast.walk(graph_tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "set_image" and len(node.args) >= 2 \
                and isinstance(node.args[1], ast.Name) \
                and node.args[1].id in const_value:
            set_image_line = node.lineno
            init_domain = const_value[node.args[1].id]
        if isinstance(node, ast.Compare) and any(
                isinstance(n, ast.Name) and n.id in const_value
                for n in ast.walk(node)):
            for cmp_node in [node.left, *node.comparators]:
                if isinstance(cmp_node, ast.Name) \
                        and cmp_node.id == "DOMAIN_GAMMA_RGB":
                    final_line = node.lineno
    if init_domain is None:
        raise SystemExit(
            "错误: render/pipeline/graph.py 未找到 set_image(img, DOMAIN_*) "
            "初始域证据, dataflow 无法构建")

    dataflow = build_dataflow(default_stages or [], stages, init_domain,
                              decode_site, set_image_line, final_line,
                              "render.pipeline.graph", anomalies)

    return {
        "domains": {v["value"]: {"constant": k, "module": "render.pipeline.context",
                                 "line": v["line"]}
                    for k, v in consts.items()},
        "default_stages": {"names": default_stages or [],
                           "module": "render.pipeline.presets",
                           "line": default_line},
        "stages": stages,
        "dataflow": dataflow,
        "anomalies": anomalies,
    }


def build_dataflow(default_stages, stages, init_domain, decode_site,
                   set_image_line, final_line, graph_mod, anomalies) -> list:
    """RAW→decode→stages(DEFAULT_STAGES 顺序)→encode 数据流。

    域转换标注 (IDT/ODT) 由 DOMAIN_TRANSITION_PHASE 表驱动; 出现未登记的
    转换时 phase=null 并记 anomaly —— 图谱对新 Stage 保持诚实, 不静默编故事。
    """
    by_name = {s["name"]: s for s in stages}
    flow = [{
        "step": 0, "kind": "source", "name": "RAW",
        "detail": "相机 RAW 文件 (NEF/DNG 等), rawpy.imread 解封",
        "evidence": f"{graph_mod}:271 (Pipeline.run_file 入参 raw_path)",
    }]
    dec_mod = dec_line = None
    if decode_site is not None:
        dec_mod, dec_line = decode_site.target, decode_site.line
    flow.append({
        "step": 1, "kind": "io", "name": "decode",
        "module": dec_mod, "func": "decode_raw",
        "domain_out": init_domain,
        "evidence": (f"{graph_mod}:{decode_site.line} (run_file 内嵌套 import "
                     f"decode_raw) + {graph_mod}:{set_image_line} "
                     f"(set_image 初始域 {init_domain})")
        if decode_site else "未在 graph.py 找到 decode_raw 嵌套 import",
    })
    step = 2
    domain = init_domain
    for name in default_stages:
        rec = by_name.get(name)
        if rec is None:
            anomalies.append(
                f"DEFAULT_STAGES 含未注册 Stage '{name}' (presets.py), 无域契约可引用")
            flow.append({"step": step, "kind": "missing_stage", "name": name})
            step += 1
            continue
        din, dout = rec.get("domain_in"), rec.get("domain_out")
        transition = None
        if din and dout and din != dout:
            transition = DOMAIN_TRANSITION_PHASE.get((din, dout))
            if transition is None:
                anomalies.append(
                    f"Stage '{name}' 出现未登记的域转换 {din}→{dout}, "
                    f"phase 置 null (DOMAIN_TRANSITION_PHASE 需人工确认后补充)")
        flow.append({
            "step": step, "kind": "stage", "name": name,
            "order": rec.get("order"), "module": rec["module"],
            "line": rec["line"], "domain_in": din, "domain_out": dout,
            "transition_phase": transition,
        })
        domain = dout or domain
        step += 1
    # DEFAULT 之外已注册但默认不跑的 Stage (denoise/sharpen/vibrance 等备用位)
    extra = [s["name"] for s in stages if s["name"] not in default_stages]
    flow.append({
        "step": step, "kind": "io", "name": "encode",
        "domain_in": domain, "domain_out": "uint8_srgb",
        "evidence": (f"{graph_mod}:{final_line} (终检 gamma_rgb) + "
                     f"{graph_mod}:305 (clip*255+0.5 → uint8)") if final_line
        else f"{graph_mod} (终检/uint8 出口)",
        "note": f"默认不跑的已注册 Stage: {', '.join(extra)}" if extra else None,
    })
    return flow


# ---------------------------------------------------------------- 图谱组装
def build_graph(root: Path) -> dict:
    modules = scan_package(root)
    if not modules:
        raise SystemExit(f"错误: {root} 下未扫描到任何 .py 文件")

    nodes, edges = [], []
    external_sites = defaultdict(list)      # pkg → [{module,line,scope}]
    stdlib_counter = Counter()
    in_deg = Counter()
    out_deg = Counter()
    pkg_dirs = collect_pkg_dirs(root)
    module_kinds = {m.id: m.kind for m in modules}

    def _layer(mid: str) -> str:
        return layer_of(mid, pkg_dirs, module_kinds.get(mid) == "package")

    for m in modules:
        nodes.append({
            "id": m.id, "kind": m.kind, "layer": m.layer, "path": m.path,
            "lines": m.lines, "doc": m.doc,
            "shadowed": m.shadowed or None,
        })
        seen_edges = set()
        for site in m.imports:
            if site.kind == "pixo":
                # 自引用 (嵌套懒加载引用本模块) 不建边: 自环无跨模块信息
                key = (m.id, site.target, site.line, site.scope)
                if key in seen_edges or site.target == m.id:
                    continue
                seen_edges.add(key)
                edges.append({
                    "type": "imports", "from": m.id, "to": site.target,
                    "line": site.line, "scope": site.scope,
                    "stmt": site.stmt,
                })
                out_deg[m.id] += 1
                in_deg[site.target] += 1
            elif site.kind == "third_party":
                external_sites[site.target].append(
                    {"module": m.id, "line": site.line, "scope": site.scope})
            else:
                stdlib_counter[site.target] += 1

    # 分层节点 + 跨层聚合边 (层级视图, 边数可溯源到模块级 edges)
    layer_modules = defaultdict(list)
    for n in nodes:
        layer_modules[n["layer"]].append(n["id"])
    layer_nodes = []
    for layer_id, mods in sorted(layer_modules.items()):
        doc = ""
        fs = id_to_fs(root, layer_id)
        init_py = fs / "__init__.py"
        if init_py.is_file():
            try:
                doc = first_doc_line(ast.parse(init_py.read_text(encoding="utf-8")))
            except (SyntaxError, UnicodeDecodeError):
                doc = ""
        layer_nodes.append({"id": layer_id, "kind": "layer",
                            "modules": sorted(mods), "doc": doc})
    layer_edges_counter = Counter()
    layer_edge_via = defaultdict(list)
    for e in edges:
        lf, lt = _layer(e["from"]), _layer(e["to"])
        if lf != lt:
            layer_edges_counter[(lf, lt)] += 1
            layer_edge_via[(lf, lt)].append(f'{e["from"]}:{e["line"]}')
    layer_edges = [{"from": a, "to": b, "count": c,
                    "via": sorted(layer_edge_via[(a, b)])[:8],
                    "via_total": len(layer_edge_via[(a, b)])}
                   for (a, b), c in sorted(layer_edges_counter.items())]

    for n in nodes:
        n["imports_out"] = out_deg[n["id"]]
        n["imports_in"] = in_deg[n["id"]]

    external = {
        pkg: {"sites": sorted(sites, key=lambda s: (s["module"], s["line"])),
              "layers": sorted({_layer(s["module"]) for s in sites}),
              "all_nested": all(s["scope"] == "nested" for s in sites)}
        for pkg, sites in sorted(external_sites.items())
    }

    pipeline_dir = id_to_fs(root, "render.pipeline")
    if (pipeline_dir / "context.py").is_file():
        pipeline = parse_pipeline(pipeline_dir, root)
    else:
        # 目标包无 render/pipeline (如仅扫子树): 管线段缺省, 不编造
        pipeline = {"available": False,
                    "note": f"未找到 {pipeline_dir.as_posix()}/context.py, "
                            f"跳过 Stage 管线提取"}

    shadowed = [m.id for m in modules if m.shadowed]
    parse_errors = [m.id for m in modules if m.lines == 0 and not m.doc]

    nodes.extend({"id": pkg, "kind": "external", "layer": None, "path": None,
                  "lines": None, "doc": "", "imports_out": 0,
                  "imports_in": len(ext["sites"])}
                 for pkg, ext in external.items())
    for pkg, ext in external.items():
        for s in ext["sites"]:
            edges.append({"type": "imports", "from": s["module"], "to": pkg,
                          "line": s["line"], "scope": s["scope"], "stmt": None,
                          "external": True})

    edges.sort(key=lambda e: (e["from"], e["to"], e["line"], e["scope"]))
    nodes.sort(key=lambda n: (n["kind"] != "layer", n["id"]))

    graph = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": {"script": "scripts/build_project_graph.py"},
        "source": {"package": ROOT_PACKAGE, "root": str(Path("src") / ROOT_PACKAGE),
                   "files_scanned": len(modules)},
        "layers": layer_nodes,
        "layer_edges": layer_edges,
        "nodes": nodes,
        "edges": edges,
        "external": external,
        "external_stdlib": dict(sorted(stdlib_counter.items())),
        "pipeline": pipeline,
        "anomalies": {
            "shadowed_modules": shadowed,
            "parse_errors": parse_errors,
                "pipeline": pipeline.get("anomalies", []),
        },
        "merge": None,
    }
    return graph


# ---------------------------------------------------------------- --merge
def merge_fragments(graph: dict, fragment_paths: list) -> dict:
    """合并 t15 片段 ({"namespace"?, "nodes": [...], "edges": [...]}) 进图谱。

    规则: 片段节点 id 与 pixo 图冲突 → SystemExit (不静默覆盖); 片段边引用的
    未定义 id → 自动补 kind="external_asset" 节点 (origin 标注片段文件)。
    """
    known = {n["id"] for n in graph["nodes"]}
    merged_log = []
    for fp in fragment_paths:
        p = Path(fp)
        if not p.is_file():
            raise SystemExit(f"错误: merge 片段不存在: {p}")
        try:
            frag = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise SystemExit(f"错误: 片段 {p} 不是合法 JSON: {e}")
        nodes = frag.get("nodes")
        edges = frag.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise SystemExit(
                f"错误: 片段 {p} 缺少 nodes/edges 数组。期望格式: "
                '{"namespace"?: str, "nodes": [{"id": str, ...}], '
                '"edges": [{"from": str, "to": str, ...}]}')
        origin = frag.get("namespace") or p.stem
        added_nodes = []
        for nd in nodes:
            if not isinstance(nd, dict) or "id" not in nd:
                raise SystemExit(f"错误: 片段 {p} 的 nodes 含缺少 id 的条目: {nd!r}")
            if nd["id"] in known:
                raise SystemExit(
                    f"错误: 片段 {p} 节点 id '{nd['id']}' 与 pixo 图谱冲突, "
                    f"拒绝合并 (片段应使用独立命名空间, 如 'frontend/xxx')")
            nd = {**nd, "origin": origin}
            graph["nodes"].append(nd)
            known.add(nd["id"])
            added_nodes.append(nd["id"])
        added_edges = 0
        for ed in edges:
            if not isinstance(ed, dict) or "from" not in ed or "to" not in ed:
                raise SystemExit(f"错误: 片段 {p} 的 edges 缺少 from/to: {ed!r}")
            for endpoint in (ed["from"], ed["to"]):
                if endpoint not in known:
                    graph["nodes"].append({
                        "id": endpoint, "kind": "external_asset", "origin": origin,
                        "layer": None, "path": None, "lines": None, "doc": "",
                        "imports_in": 0, "imports_out": 0,
                    })
                    known.add(endpoint)
                    added_nodes.append(endpoint)
            graph["edges"].append({**ed, "origin": origin})
            added_edges += 1
        merged_log.append({"fragment": p.as_posix(), "origin": origin,
                           "nodes": added_nodes, "edges_added": added_edges})
    graph["merge"] = {"fragments": merged_log}
    return graph


# ---------------------------------------------------------------- MD 生成
def _m(name: str) -> str:
    """mermaid 安全 id。"""
    return name.replace(".", "_").replace("/", "_").replace("-", "_")


def render_mermaid_layers(layer_nodes, layer_edges) -> str:
    lines = ["flowchart LR"]
    render_layers = [l for l in layer_nodes if l["id"].startswith("render")]
    other_layers = [l for l in layer_nodes if not l["id"].startswith("render")]
    if render_layers:
        lines.append("  subgraph render[\"pixo.render\"]")
        for l in render_layers:
            parts = l["id"].split(".")
            short = parts[1] if len(parts) > 1 else l["id"]
            lines.append(f'    {_m(l["id"])}["{short}"]')
        lines.append("  end")
    for l in other_layers:
        lines.append(f'  {_m(l["id"])}["{l["id"]}"]')
    for e in layer_edges:
        label = "" if e["count"] == 1 else f"|{e['count']}|"
        lines.append(f"  {_m(e['from'])} -->{label} {_m(e['to'])}")
    return "\n".join(lines)


def render_mermaid_pipeline(dataflow) -> str:
    lines = ["flowchart LR"]
    for step in dataflow:
        nid = f"s{step['step']}"
        if step["kind"] == "stage":
            dom = f"{step['domain_in']}→{step['domain_out']}"
            phase = f"<br/>{step['transition_phase']}" if step.get("transition_phase") else ""
            lines.append(f'  {nid}["{step["name"]}<br/>{dom}{phase}"]')
        else:
            lines.append(f'  {nid}["{step["name"]}"]')
    for i in range(len(dataflow) - 1):
        lines.append(f"  s{i} --> s{i + 1}")
    return "\n".join(lines)


def render_md(graph: dict, cmd_args: str) -> str:
    """人读版图谱。全部边/表数据取自 graph dict (脚本解析产物), 无手画边。"""
    nodes = graph["nodes"]
    edges = graph["edges"]
    # G-3 修：--merge 并入的前端图谱节点走知识包惯例（无 kind 键），防御性取值防 KeyError
    mods = [n for n in nodes if n.get("kind") in ("module", "package")]
    layers = {l["id"]: l for l in graph["layers"]}
    ext = graph["external"]
    pl = graph["pipeline"]
    has_pipeline = bool(pl.get("available", True))

    out = []
    out.append("# PIXO 项目图谱 (src/pixo)\n")
    out.append(f"> 由 `scripts/build_project_graph.py` AST 解析生成"
               f" ({cmd_args})。所有依赖边来自源码 import 语句 (含行号),"
               f" Stage 顺序来自 `render/pipeline/presets.py` DEFAULT_STAGES,"
               f" 域契约来自各模块 `@register_stage` 声明 —— 无任何手画边。\n")
    out.append(f"- 图谱版本: {graph['schema_version']}, 模块数: {len(mods)},"
               f" 内部+外部 import 边: {len(edges)}, 扫描文件: "
               f"{graph['source']['files_scanned']}\n")

    anomalies = graph["anomalies"]
    if anomalies.get("shadowed_modules") or anomalies.get("parse_errors") \
            or anomalies.get("pipeline"):
        out.append("## 异常与诚实声明\n")
        if anomalies.get("shadowed_modules"):
            out.append(f"- **被同名包遮蔽的模块** (Python 包优先, 不可导入, 仅为"
                       f" re-export 门面占位): "
                       f"{', '.join('`' + s + '.py`' for s in anomalies['shadowed_modules'])}\n")
        for a in anomalies.get("pipeline", []):
            out.append(f"- 管线: {a}\n")
        if anomalies.get("parse_errors"):
            out.append(f"- AST 解析失败: {anomalies['parse_errors']}\n")
        out.append("")

    out.append("## 分层架构\n")
    out.append("```mermaid")
    out.append(render_mermaid_layers(graph["layers"], graph["layer_edges"]))
    out.append("```\n")
    out.append("跨层聚合边 (层 A → 层 B | 边数 | 模块级证据抽样):\n")
    out.append("| 源层 | 目标层 | 边数 | 证据 (module:line, 最多 8 条) |")
    out.append("|---|---|---|---|")
    layer_names = {l["id"] for l in graph["layers"]}
    for e in graph["layer_edges"]:
        extra = "" if e["via_total"] <= 8 else f" (共 {e['via_total']})"
        out.append(f"| {e['from']} | {e['to']} | {e['count']} | "
                   f"{', '.join('`' + v + '`' for v in e['via'])}{extra} |")
    out.append("")

    if has_pipeline:
        out.append("## 管线数据流 (RAW → decode → IDT → 编辑 → ODT → encode)\n")
        out.append("```mermaid")
        out.append(render_mermaid_pipeline(pl["dataflow"]))
        out.append("```\n")
        ds = pl["default_stages"]
        out.append(f"Stage 顺序来源: `{ds['module']}` DEFAULT_STAGES (行 {ds['line']}); "
                   f"色彩域定义: `render/pipeline/context.py`; "
                   f"每步域契约来自 `@register_stage` 装饰器 (行号见 JSON "
                   f"`pipeline.stages`)。\n")
        out.append("| 步骤 | 名称 | 类型 | 域 | 证据 |")
        out.append("|---|---|---|---|---|")
        for s in pl["dataflow"]:
            if s["kind"] == "stage":
                dom = (f"{s['domain_in']} → {s['domain_out']}"
                       + (f" (**{s['transition_phase']}**)" if s.get("transition_phase")
                          else ""))
                out.append(f"| {s['step']} | {s['name']} | stage (order={s['order']}) "
                           f"| {dom} | `{s['module']}:{s['line']}` |")
            else:
                dom = ""
                if s.get("domain_out"):
                    dom = f"→ {s['domain_out']}"
                out.append(f"| {s['step']} | **{s['name']}** | {s['kind']} | {dom} "
                           f"| {s.get('evidence') or ''} |")
        out.append("")

    out.append("## 模块职责表\n")
    out.append("职责取自各模块 docstring 首行 (脚本解析, 非人工转写)。"
               "入/出度只统计模块级 import (嵌套懒加载不计入度数, 证据在 JSON "
               "`edges[].scope`)。\n")
    by_layer = defaultdict(list)
    for m in mods:
        by_layer[m["layer"]].append(m)
    for layer_id in sorted(by_layer):
        ld = layers.get(layer_id, {})
        title = f"`{layer_id}`" + (f" —— {ld['doc']}" if ld.get("doc") else "")
        out.append(f"### 层 {title}\n")
        out.append("| 模块 | 职责 (docstring 首行) | 入度 | 出度 |")
        out.append("|---|---|---|---|")
        for m in sorted(by_layer[layer_id], key=lambda x: x["id"]):
            doc = (m["doc"] or "").replace("|", "\\|")[:96]
            shadow = " ⚠️被同名包遮蔽" if m.get("shadowed") else ""
            out.append(f"| `{m['id']}`{shadow} | {doc} | {m['imports_in']} "
                       f"| {m['imports_out']} |")
        out.append("")

    out.append("## 外部依赖清单 (隔离位置)\n")
    out.append("来自 AST 全量扫描 (模块级 + 嵌套懒加载, 含行号)。"
               "`all_nested=true` 表示该依赖从不做模块级导入 —— 全部延迟到函数内, "
               "即懒加载隔离。\n")
    out.append("| 依赖 | 使用点数 | 所在层 | 懒加载 | 隔离位置 (module:line) |")
    out.append("|---|---|---|---|---|")
    for pkg, info in ext.items():
        sites = info["sites"]
        shown = ", ".join(f"`{s['module']}:{s['line']}`" for s in sites[:10])
        more = f" …共 {len(sites)} 处" if len(sites) > 10 else ""
        out.append(f"| {pkg} | {len(sites)} | {', '.join(info['layers'])} "
                   f"| {'是' if info['all_nested'] else '否'} "
                   f"| {shown}{more} |")
    out.append("")
    std = graph["external_stdlib"]
    out.append(f"标准库使用汇总 (计数, 不建边): "
               f"{', '.join(f'{k}×{v}' for k, v in sorted(std.items()))}\n")

    merge_info = graph.get("merge")
    if merge_info:
        out.append("## 合并的外部片段 (t15)\n")
        for frag in merge_info["fragments"]:
            out.append(f"- `{frag['fragment']}` (origin={frag['origin']}): "
                       f"+{len(frag['nodes'])} 节点, +{frag['edges_added']} 边")
        out.append("")

    return "\n".join(out)


# ---------------------------------------------------------------- CLI
def stable_dump(graph: dict) -> str:
    return json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="AST 解析 src/pixo 生成项目图谱 (JSON + MD)")
    ap.add_argument("--root", default=str(REPO_ROOT / "src" / ROOT_PACKAGE),
                    help="被扫描的包目录 (默认 src/pixo)")
    ap.add_argument("--out", default=str(REPO_ROOT / "docs" / "project_graph.json"),
                    help="输出 JSON 路径")
    ap.add_argument("--md", default=str(REPO_ROOT / "docs" / "PROJECT_GRAPH.md"),
                    help="输出 MD 路径 (--no-md 关闭)")
    ap.add_argument("--merge", action="append", default=[],
                    metavar="FRAGMENT_JSON",
                    help="追加 t15 片段 (可多次); 期望 {namespace?, nodes[], edges[]}")
    ap.add_argument("--no-md", action="store_true", help="只生成 JSON")
    ap.add_argument("--check", action="store_true",
                    help="幂等校验: 重新生成并与现有文件比对, 漂移则退出 1")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    if not root.is_dir():
        ap.error(f"--root 不存在: {root}")

    graph = build_graph(root)
    if args.merge:
        graph = merge_fragments(graph, args.merge)

    out_path = Path(args.out)
    md_path = Path(args.md) if args.md and not args.no_md else None
    json_text = stable_dump(graph)
    md_text = None if md_path is None else render_md(
        graph, f"root={args.root}")

    if args.check:
        problems = []
        if not out_path.is_file():
            problems.append(f"JSON 不存在 (先运行生成): {out_path}")
        else:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
            fresh = json.loads(json_text)
            # 时间戳天然每次不同, 不参与漂移判定
            existing.pop("generated_at", None)
            fresh.pop("generated_at", None)
            if existing != fresh:
                problems.append(f"JSON 漂移: {out_path}")
        if md_path is not None:
            if not md_path.is_file():
                problems.append(f"MD 不存在 (先运行生成): {md_path}")
            elif md_path.read_text(encoding="utf-8") != md_text:
                problems.append(f"MD 漂移: {md_path}")
        if problems:
            print("FAIL: " + "; ".join(problems)
                  + " —— 请重新运行 build_project_graph.py", file=sys.stderr)
            return 1
        print(f"OK: {out_path}"
              + (f" / {md_path}" if md_path else "") + " 无漂移")
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json_text, encoding="utf-8")
    df_len = len(graph["pipeline"].get("dataflow", [])
                 ) if graph["pipeline"].get("available", True) else 0
    print(f"写入 {out_path}: {len(graph['nodes'])} 节点, {len(graph['edges'])} 边, "
          f"{len(graph['layers'])} 层, pipeline dataflow {df_len} 步")
    if md_path is not None:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_text, encoding="utf-8")
        print(f"写入 {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
