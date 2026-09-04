"""learned/ 目录 import 隔离门禁（阶段三 OWN_PIPELINE_STAGE3_DESIGN §1）。

防"商未建先铺门"：src/pixo/render/learned/ 是学习后端的未来落位目录
（阶段三红线：本阶段只建 scripts/ 原型，**不建**该目录）。本门禁在目录
落地即自动生效——其内部任何 .py 文件（含函数内懒 import，AST 全量扫描）
不得 import torch/torchvision/transformers，只许 numpy/cv2 级轻依赖；
未来真需要 torch 时须像 vision/segmenters 一样隔离在 adapter 层
（tests/unit/test_vision_segmenter.py::test_heavy_imports_isolated_in_
adapters 同法），届时将实现移出 learned/ 或经 QA 评审立显式豁免清单。

目录不存在时整门 skip——铺门不设卡，防守商目录未建导致全量红。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LEARNED_DIR = REPO_ROOT / "src" / "pixo" / "render" / "learned"

# 学习栈重依赖根名：torch 家族（torch/torchvision）+ transformers。
# rfdetr 等 vision 检测依赖由 vision 侧隔离门管辖，不在此重复。
BANNED_ROOTS = {"torch", "torchvision", "transformers"}


def _banned_import_hits(py_file: Path) -> list[str]:
    """单文件 AST 扫描 → 违规 import 描述列表（含函数内懒 import）。"""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BANNED_ROOTS:
                    hits.append(f"{py_file}:{node.lineno} import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in BANNED_ROOTS:
                hits.append(
                    f"{py_file}:{node.lineno} from {node.module} import ...")
    return hits


def test_learned_dir_import_isolation():
    """learned/ 目录存在时：零 torch/transformers import（只许 numpy/cv2）。"""
    if not LEARNED_DIR.is_dir():
        pytest.skip(
            "src/pixo/render/learned/ 未建（阶段三红线：本阶段只建 scripts 原型"
            "不建该目录）——隔离门预铺，目录落地即生效")
    all_hits: list[str] = []
    for py_file in sorted(LEARNED_DIR.rglob("*.py")):
        all_hits.extend(_banned_import_hits(py_file))
    assert not all_hits, (
        "learned/ 内禁止 import torch/torchvision/transformers（只许 numpy/cv2；"
        "需要重依赖时像 vision/segmenters 一样隔离在 adapter 层）：\n"
        + "\n".join(all_hits))


def test_gate_detects_lazy_import_inside_function(tmp_path):
    """门禁自检：函数内懒 import（segmenter 惯用逃逸手法）也必须被捕获。"""
    probe = tmp_path / "fake_learned.py"
    probe.write_text(
        "import numpy as np\n"
        "def load():\n"
        "    import torch            # 懒 import\n"
        "    from transformers import AutoModel  # 懒 from-import\n"
        "    import torchvision.transforms as T  # torch 家族\n"
        "    return np.zeros(1)\n",
        encoding="utf-8")
    hits = _banned_import_hits(probe)
    assert len(hits) == 3, hits
    assert any("torch" in h for h in hits)
    assert any("transformers" in h for h in hits)
    assert any("torchvision" in h for h in hits)


def test_gate_allows_numpy_cv2_and_pixo(tmp_path):
    """门禁自检：numpy/cv2/pixo 相对 import 与 stdlib 零误报。"""
    probe = tmp_path / "ok_learned.py"
    probe.write_text(
        "import cv2\n"
        "import numpy as np\n"
        "import json\n"
        "from pixo.render.core import color\n"
        "from . import sibling\n"
        "from ..adapter import bridge\n",
        encoding="utf-8")
    assert _banned_import_hits(probe) == []


def test_gate_rejects_syntax_error_file(tmp_path):
    """解析失败的文件必须报错而非静默放行（损坏文件不绕过门禁）。"""
    probe = tmp_path / "broken.py"
    probe.write_text("def ( broken", encoding="utf-8")
    with pytest.raises(SyntaxError):
        _banned_import_hits(probe)
