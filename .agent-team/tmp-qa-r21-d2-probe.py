"""QA 独立复算（只读）：D2 非门禁观测 —— make_default_scorer() 的类型与可调用性。

只读；输出 JSON 到 stdout。不写任何仓库业务文件。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
sys.path.insert(0, str(Path(r"K:\work\project\pixo") / "src"))

import numpy as np  # noqa: E402

from pixo.pipeline.batch import _PixoScorerAdapter, make_default_scorer  # noqa: E402

scorer = make_default_scorer()
img = np.full((64, 64, 3), 0.08, dtype=np.float32)
out = None
if callable(scorer):
    raw = scorer(img)
    out = {
        "return_type": type(raw).__name__,
        "keys": sorted(raw) if isinstance(raw, dict) else None,
    }

print(json.dumps({
    "default_scorer_type": type(scorer).__name__,
    "is_pixo_adapter": isinstance(scorer, _PixoScorerAdapter),
    "callable": callable(scorer),
    "has_call_attr": hasattr(scorer, "__call__"),
    "call_result": out,
}, ensure_ascii=False, default=str))
