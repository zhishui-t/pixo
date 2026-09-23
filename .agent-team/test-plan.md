# 测试计划（test-plan.md）— Pixo 第九轮战役

> tester 拟定 2026-09-07。范围：F01~F20 全量测试验证。
> 被测版本：master @ **fc2bfa8**（工作树仅 .artifacts 下 3 个未跟踪哈希存证，无代码脏区）。
> 回归基线：**1396 passed / 5 skipped / 1 xfailed**（.agent-team/baseline-f02.md，master@f357b35 存证，qa 已复核签认）。
> 红线：0 failed；passed 不低于基线；skip/xfailed 变动逐项说明。
> 入口（约束沿任务书）：全量 `python -m pytest tests -q -m "not e2e"`；分域 unit / integration / regression `-m "gate and not gate_e2e"`；前端 `cd frontend && npm run typecheck && npm run test:unit`。

## 1. F-ID × 测试映射表

| F-ID | 功能 | 验证方式 | 覆盖测试 / 门禁 | 执行人 |
|------|------|----------|----------------|--------|
| F01 | changelog 历史批补写（08-27~09-05） | 文档型（qa 总审覆盖）；tester 抽验事实锚点 | qa 总审；writer.md commit 清单核对表（31/31） | qa |
| F02 | 全量基线存证 | 已有存证+qa 复核签认 | .agent-team/baseline-f02.md（1396/5/1，qa 独立复跑 -rs 签认） | 队长+qa（已完成） |
| F03 | FairFace 彻底移除 | 定向测试+grep 防复活 | `test_vision_extras.py` `test_vision_router_semantics.py` `test_vision_manifests.py` `test_vision_segmenter.py` `test_vision_measure.py` `test_model_licenses.py` `test_tech_debt_invariants.py`；`grep -ri fairface src/ configs/` 零活引用 | tester |
| F04 | gsam 彻底移除 | 定向测试+grep 防复活+降级语义 | `test_multimodel_segmenter.py` `test_vision_router_semantics.py`（test_grounded_sam_removed）`test_sapiens_body.py`；`grep -ri "gsam\|grounded_sam" src/ configs/` 零活引用 | tester |
| F05 | lr_baseline float 化处置 | 调查型（记债 c，零代码改动） | `test_tech_debt_invariants.py`（条目 16 台账断言）；调查证据由 qa 总审复核 | tester（台账断言）+qa |
| F06 | RAW 金样本团队重验 | 工具实测（compare 24 case） | `gate_golden.py compare`（F06 前基线重生成 b187d27，F10 后复跑=双证据）；`.agent-team/golden-reverify.md` | qa（前）+tester（F10 后复跑） |
| F07 | 存量 23 卡显式钉 hsv | 不变量测试+A1 渲染逐位 | `test_film_cards_oklch.py`（8 用例：钉域不变量/计数钉死/合并等价）；`.artifacts/_f07_pin_hsv_render_check.py` 23 卡 sha256 对比（tester 复跑） | tester |
| F08 | gate 缺省分派 case+存量卡 golden | gate 金样本测试 | `test_gate_golden.py` -m "gate and not gate_e2e"（20 features 含 default_dispatch+card_portra_400）；`generate_gate_goldens.py --check` | tester |
| F09 | patch_protocol 同源化+canonical 透出 | 单测+集成 | `test_patch_protocol.py`（同源翻转自证/parity）；`test_preview_session.py`（canonical 透出） | tester |
| F10 | oklch 第一批切换（hsl+split_tone） | 缺省断言+A1 双证据+RAW 复跑 | `test_hsl_oklch.py` `test_split_tone_oklab.py` `test_film_cards_oklch.py` `test_patch_protocol.py`；gate --check 零漂移；RAW compare PASS；`.f10_ok` 门禁（qa 已签） | tester（复验） |
| F11 | skin+colorcal 意图级 A/B | 证据产出型 | `.artifacts/skin_colorcal_oklch_ab.md` 落盘核查（**执行时点未落盘，标未验证**，见 test-report） | qa 总审核查 |
| F12 | region_adjust stage | 单测（30+ 用例） | `test_region_adjust.py`（数值断言/enabled=False 零影响/wants 门控/NaN 降级/顺序合成） | tester |
| F13 | 掩码通道 preview/export 双线注入 | 单测+集成 | `test_region_masks_channel.py`（23 用例）；`test_export.py`；spike 证据 hard-problems.md | tester |
| F14 | decide region.* 接线 | 单测+e2e 闭环 | `test_decide_region_wiring.py`（21 用例，含真 SinglePhotoLoop 闭环+crop 采纳掩码失效）；`test_tone_clarity_rules.py`（strict lint 回归） | tester |
| F15 | M1 验收资产 | gate 金样本+harness | `test_gate_golden.py`（20 features 断言）；`test_goldens_v0.py` `test_gate_golden_tool.py`；`generate_gate_goldens.py --check`；render/README 清单核查 | tester |
| F16 | THIRD_PARTY_NOTICES.md 编制 | 文档型（qa 总审覆盖） | qa 总审；`test_model_licenses.py` 既有断言不红（tester 附带执行） | qa+tester |
| F17 | scipy/PyYAML 依赖声明 | 文档型（qa 总审覆盖）+配置生效 | qa 总审；`pip show pyyaml`+decide 规则加载测试（`test_tone_clarity_rules.py` 隐式覆盖 PyYAML 硬依赖） | qa+tester |
| F18 | DNG SDK clean-room 复审评估 | 调研文档型 | qa 总审（research/dng-sdk-review.md 落盘核查） | qa |
| F19 | 感知质量门禁提案 | 提案文档型（可选） | qa 总审（research/perceptual-gate-proposal.md 落盘核查） | qa |
| F20 | changelog 本轮批次 | 文档型（qa 总审覆盖） | qa 总审 | qa |

## 2. tester 执行批次（本轮实际执行）

| 批次 | 命令 | 覆盖 F-ID |
|------|------|-----------|
| B1 M1 域专项 | `python -m pytest tests/unit/test_region_adjust.py tests/unit/test_region_masks_channel.py tests/unit/test_decide_region_wiring.py -q` + `python -m pytest tests/regression/test_gate_golden.py tests/regression/test_goldens_v0.py tests/unit/test_gate_golden_tool.py -m "gate and not gate_e2e" -q`（20 features） | F12 F13 F14 F15 F08 |
| B2 oklch 域专项 | `python -m pytest tests/unit/test_hsl_oklch.py tests/unit/test_split_tone_oklab.py tests/unit/test_film_cards_oklch.py tests/unit/test_patch_protocol.py -q` | F07 F09 F10 |
| B2b F09 canonical 透出 | `python -m pytest tests/integration/test_preview_session.py -q -m "not e2e"` | F09 |
| B3 清债域专项 | `python -m pytest tests/unit/test_vision_extras.py tests/unit/test_vision_router_semantics.py tests/unit/test_vision_manifests.py tests/unit/test_vision_segmenter.py tests/unit/test_vision_measure.py tests/unit/test_multimodel_segmenter.py tests/unit/test_sapiens_body.py tests/unit/test_learned_isolation.py tests/unit/test_model_licenses.py tests/unit/test_tech_debt_invariants.py -q` + grep 防复活×2 | F03 F04 F05 F16 部分 |
| B4 A1 渲染逐位复验 | `PYTHONPATH=src python .artifacts/_f07_pin_hsv_render_check.py .artifacts/tester_f10_hashes_after.json`，与 f07_render_hashes_before.json 逐卡对比 | F07 F10 |
| B5 RAW 金样本 | `python src/pixo/render/tools/gate_golden.py compare --samples D:/tmp/pixo_t108/samples.json --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512` | F06 F10 |
| B6 gate --check 零漂移 | `python tests/regression/goldens/generate_gate_goldens.py --check` | F08 F10 F15 |
| B7 全量回归 | `python -m pytest tests -q -m "not e2e"`（对齐基线 1396/5/1） | 全部 |
| B8 前端 | `cd frontend && npm run typecheck && npm run test:unit` | F13/F09 前端类型面（本轮前端未改动，回归确认） |
| B9 邻域回归抽查 | loop/decide/export 邻域 + decide 规则 strict lint | F14 F13 F09 |

## 3. 判定标准

- 各批次 0 failed，输出原样摘录入 test-report.md 证据节。
- 全量 passed ≥ 1396；skip/xfailed 变动逐条列出原因（对照 baseline-f02.md qa 复核的 5 项 skip 清单）。
- F10 后预期形态：gate `default_dispatch` 已切 oklch（v2 基线生效，--check 零漂移）；`card_portra_400` 与 RAW 24 case 零漂移；RAW 工具 4 features 默认路径不涉 hsl/split_tone 非零参数。
- 发现 bug：最小复现+定位流+期望/实际+证据，记入 test-report.md bug 清单；不修被测代码，报队长退回流。

## 4. 范围外/移交说明

- LLM env 三件套 e2e：用户未提供 env，不在本轮（任务书非目标）。
- F11 A/B 报告、F01/F16~F20 文档事实核查：主责 qa 总审，tester 只做落盘/配置存在性核查。
- RAW 语料在 `D:\tmp\pixo_t108\`（不入库）；金样本基线重生成权在队长单点（tester 只跑 compare，不生成）。
