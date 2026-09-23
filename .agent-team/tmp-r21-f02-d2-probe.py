"""R21 F02 / F03 / D2 快速探针（只读，秒级，无真 RAW）。

- F02：`_load_auto_loop_rules` 计数 + 规则 id 清单；`PIXO_RULES` 各关闭值；
       库层 `SinglePhotoLoop()` 缺省仍 `rules == []`。
- F03：`METRIC_KEYS` / `metric_universe` 规模（键宇宙口径）。
- D2（design §7 追加非门禁观测）：`make_default_scorer()` 返回类型 + `callable()`。

运行：`python .agent-team/tmp-r21-f02-d2-probe.py`
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"K:\work\project\pixo") / "src"))
os.environ.pop("PIXO_RULES", None)

from pixo.service.runtime import _load_auto_loop_rules  # noqa: E402


def main() -> int:
    rules = _load_auto_loop_rules(("face", "sky", "plant"))
    print(json.dumps({
        "rules_count": len(rules),
        "rules_ids": [r.get("rule_id") for r in rules],
    }, ensure_ascii=False), flush=True)

    off_matrix = {}
    for value in ["0", "false", "off", "no", "OFF", "False", " off "]:
        os.environ["PIXO_RULES"] = value
        off_matrix[value] = len(_load_auto_loop_rules(("face", "sky", "plant")))
    os.environ.pop("PIXO_RULES", None)
    print(json.dumps({"rules_off_matrix": off_matrix,
                      "rules_on_again": len(_load_auto_loop_rules())},
                     ensure_ascii=False), flush=True)

    from pixo.pipeline.loop import SinglePhotoLoop  # noqa: E402
    print(json.dumps({"lib_default_rules": SinglePhotoLoop().rules},
                     ensure_ascii=False), flush=True)

    from pixo.pipeline.metrics import METRIC_KEYS, metric_universe  # noqa: E402
    print(json.dumps({
        "METRIC_KEYS_count": len(METRIC_KEYS),
        "METRIC_KEYS": sorted(METRIC_KEYS),
        "universe_count": len(metric_universe(("face", "sky", "plant"))),
    }, ensure_ascii=False), flush=True)

    # D2：非门禁观测（真/假分支；不参与 F04 验收）
    from pixo.pipeline.batch import make_default_scorer  # noqa: E402
    scorer = make_default_scorer()
    print(json.dumps({
        "default_scorer_type": type(scorer).__name__,
        "default_scorer_callable": callable(scorer),
        "default_scorer_has_call_attr": hasattr(type(scorer), "__call__"),
    }, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
