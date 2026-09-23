# 测试报告（test-report.md）— Pixo 第九轮战役

> tester 出具 2026-09-07T03:14+08:00。被测版本：master @ **fc2bfa8**（工作树无代码脏区，仅 .artifacts 未跟踪哈希存证）。
> 回归基线：**1396 passed / 5 skipped / 1 xfailed**（.agent-team/baseline-f02.md @ f357b35，qa 已签认）。
> 测试计划：.agent-team/test-plan.md（F-ID×测试映射，批次 B1~B9 与本报告证据一一对应）。
> 所有结论均出自本报告所列命令的真实输出；无运行证据处如实标「未验证」。

---

## 0. 结论速览

| 维度 | 结果 |
|------|------|
| 全量回归 | **1474 passed / 5 skipped / 1 xfailed，0 failed**（189.22s）——基线 1396 → 1474（**+78，全部为本轮新增测试，逐项对账见 §2**）；skip 5/5 与基线 qa 复核清单逐条相同；xfailed 1 不变 |
| 专项测试（B1~B6/B9） | 全绿：M1 域 86、oklch 域 94、清债域 99 passed/2 skip（已知良性）、邻域 158 |
| RAW 金样本 | **24/24 case PASS，u8_max=0、u16_max=0（逐位零漂移）**（F06 基线重生成后 + F10 切换后双证据） |
| gate 金样本 | `--check` → **CHECK: OK（20 features 与现有 manifest 一致）**，F10 后 v2 基线零漂移 |
| A1 存量卡逐位 | **23/23 卡 float32 sha256 字节级一致**（tester 独立复跑 vs 钉域前基线 vs dev F10 存证，三方全等） |
| 前端 | `tsc --noEmit` 零错误；unit **11 pass / 0 fail** |
| 阻断性 bug | **0** |
| 遗留观察 | 2 项非阻断（§6：F11 .md 报告落盘时点、gate 基线 reviewer 字段治理——后者 qa 已在 .f10_ok 处理） |

---

## 1. F-ID 逐项判定与证据

判定口径：**PASS=有本人执行证据**；**PASS(移交)=文档/证据型，主责 qa 总审，tester 只核存在性/连带断言**；**部分/未验证=明示缺口与原因**。

### F01 changelog 历史批补写 — PASS(移交 qa 总审)
- writer 交付：docs/changelog.md 顶部 11 条目覆盖 31/31 commit（08-27~09-05），commit 清单核对表见 `.agent-team/streams/writer.md`。
- tester 未逐条核对事实数字（主责 qa 总审）；writer 自证「验收数字来源全部可溯源」清单在案。

### F02 全量基线存证 — PASS(既有存证)
- 证据：`.agent-team/baseline-f02.md`（1396/5/1 @ f357b35，qa 独立复跑 -rs 签认 2026-09-07T01:03:32+08:00）。本轮 tester 全量结果见 §2，基线不降。

### F03 FairFace 彻底移除 — PASS
- B3 定向：`python -m pytest tests/unit/test_vision_extras.py test_vision_router_semantics.py test_vision_manifests.py test_vision_segmenter.py test_vision_measure.py test_multimodel_segmenter.py test_sapiens_body.py test_learned_isolation.py test_model_licenses.py test_tech_debt_invariants.py -q`
  → **99 passed, 2 skipped in 9.22s**（2 skip 为基线既有良性项，见 §3）
- 防复活 grep（本机实跑）：
  - `grep -rin "fairface" src/ configs/` → **0 命中**
  - `grep -rin "fairface" tests/` → 仅 1 行：`test_vision_manifests.py:38: assert "fairface-onnx" not in ids`（防复活断言本体，design 明示口径）
  - `ls src/pixo/vision/person.py` → No such file（整文件已删）
- 台账：docs/tech_debt.md 条目 14「FairFace 移除（已清偿，2026-09-07 F03）」在案（L155）。

### F04 gsam 彻底移除 — PASS
- 同 B3 批次：99 passed 含 `test_multimodel_segmenter.py`（未知 prompt 零掩码+warn-once 新语义、纯未知不上抛、单组全败仍上抛）与 `test_grounded_sam_removed` 防复活。
- 防复活 grep（本机实跑）：
  - `grep -rin "gsam\|grounded_sam" src/ configs/` → **0 命中**
  - tests/ 仅 5 行，全为防复活断言/docstring（test_grounded_sam_removed 等）
  - `ls src/pixo/vision/segmenters/grounded_sam.py` → No such file
- 台账：tech_debt.md 条目 15 在案（L165）。

### F05 lr_baseline 处置 — PASS(记债 c，零代码改动)
- 调查证据：stream-1.md §F05（启用面 6 条逐链证据：manifest 无运行时读者/卡体系不含/默认链 warm_sat 短路/唯一消费者=测量脚本）。
- 台账：tech_debt.md 条目 16「记债，2026-09-07 F05」在案（L181）；`grep -c lr_baseline docs/tech_debt.md` → 3 命中。
- 断言：`test_tech_debt_invariants.py` 在 B3 批次内绿。

### F06 RAW 金样本团队重验 — PASS（tester 复跑证据）
- 历史：qa 首验 24/24 FAIL（基线 stale，golden-reverify.md §1）→ 基线重生成 b187d27 → `.f10_ok` 记录 24/24 PASS。
- tester 独立复跑（F10 切换落定后，fc2bfa8）：
  ```
  python src/pixo/render/tools/gate_golden.py compare --samples D:/tmp/pixo_t108/samples.json
    --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512
  ```
  → 4 features（wb_as_shot_default / exposure_auto_default / compose_param / clarity_default）× 6 samples **24/24 PASS，逐 case u8_max=0、u16_max=0**，`RESULT: PASS`。
  运行期 stderr 仅 1 条良性告警（wb_B=1.490 域外端点垫片，与 qa 首验记录同源）。

### F07 存量 23 卡显式钉 hsv — PASS
- B2 定向：`python -m pytest tests/unit/test_film_cards_oklch.py -q` → **8 passed**（钉域不变量+逐 stage 计数钉死 {hsl:12, split_tone:12, skin:22, colorcal:23}+合并等价转型测试）。
- A1 渲染逐位（tester 独立复跑，见 §4 B4）：`PYTHONPATH=src python .artifacts/_f07_pin_hsv_render_check.py .artifacts/tester_f10_hashes_after.json` → `cards=23 pinned_stage_entries=69`（69=12+12+22+23，与 design qa 实测口径吻合）；与 `f07_render_hashes_before.json`（钉域前）及 `f10_render_hashes_after.json`（dev F10 存证）比对 **23/23 卡 sha256_float32+shape 全等**。

### F08 gate 缺省分派 case + 存量卡 golden — PASS
- B1b：`python -m pytest tests/regression/test_gate_golden.py tests/regression/test_goldens_v0.py tests/unit/test_gate_golden_tool.py tests/regression/test_gate_coverage.py -m "gate and not gate_e2e" -q` → **10 passed, 16 deselected**（deselected 均为 e2e 标记，非失败）。
- `test_gate_golden.py:35` 断言 `len(features) == 20`；manifest 实测 20 features，含 `default_dispatch`（缺省分派观测点）、`card_portra_400`（卡级 A1 golden）、`region_adjust`（F15）。

### F09 patch_protocol 同源化 + canonical 透出 — PASS
- B2 定向：`python -m pytest tests/unit/test_patch_protocol.py -q` → **29 passed**（含同源翻转自证 / patch↔运行时 parity / 归属域源等式——F10 后零修订自动绿，本批实跑证实）。
- B2b：`python -m pytest tests/integration/test_preview_session.py -q -m "not e2e"` → **21 passed**（含 `test_canonical_params_expose_color_domain`）。

### F10 oklch 第一批切换 — PASS（qa .f10_ok 门禁 + tester 复验双签）
- B2 定向四文件：hsl_oklch **18** + split_tone_oklab **18** + film_cards_oklch **8** + patch_protocol **29** = **73 passed**（缺省断言修订后形态：缺省输出参照 oklch 内核逐位、hsv 对照组显式化）。
- 验证链 b（卡级 A1）：§4 B4 → 23/23 逐位一致。
- 验证链 c（RAW 复跑）：F06 节 → 24/24 PASS u8=0。
- 验证链 d（缺省分派 case v2）：B6 `python tests/regression/goldens/generate_gate_goldens.py --check` → **`[gate_goldens] CHECK: OK（20 features 与现有 manifest 一致）`**（v1→v2 治理由队长执行、qa 于 .f10_ok 核验「仅 default_dispatch 条目变更，v2=b3352650…，其余 19 条目字节未动」）。
- 门禁：`.f10_ok`（qa，2026-09-07T02:58:55+08:00，四条全过 PASS）。

### F11 skin+colorcal 意图级 A/B — **部分（数据已落盘，.md 报告未落盘——tester 执行时点 03:14）**
- 落盘证据：`.artifacts/skin_colorcal_oklch_ab.json`（03:10 落盘， tester 报告出具前 4 分钟，任务仍在收尾中）+ 复现脚本 `_f11_skin_colorcal_ab.py`。JSON summary 实测摘录：n_images=8，`skin_none_verdict: "不劣于(小值)"`，native/py 中位耗时 9.92ms/140.83ms（14.2x）；cc_rows 含金样本组逐意图数据。
- **缺口**：design 要求的 `.artifacts/skin_colorcal_oklch_ab.md`（人读报告，per 维度明确「不劣于/劣于」结论）截至 03:14 未落盘——**未验证其最终结论完整性**，移交 qa 总审核对（预计 dev-2 正在成文）。

### F12 region_adjust stage — PASS
- B1：`python -m pytest tests/unit/test_region_adjust.py -q` → **32 passed**（合成掩码逐像素数值断言 / enabled=False 全链逐位零影响 / wants 门控 7 用例 / NaN 掩码降级不污染 / 重叠区域顺序合成三重断言 / 注册全链冒烟——含 M1 评审批 I-3/I-4 修复测试）。
- 链序断言：test_phase1_chain / test_pipeline / test_build_project_graph 在 B9 批次内绿（DEFAULT_STAGES 15 段含 region_adjust order=57）。

### F13 掩码通道 preview/export 双线注入 — PASS
- B1：`python -m pytest tests/unit/test_region_masks_channel.py -q` → **23 passed**（适配器三入口 / post-compose 坐标 / 缓存指纹透传与失效 / px-rect 跨分辨率失配钉现状[记债条目 17] / fake 签名兼容）。
- export 线：`tests/integration/test_export.py` 在 B9 批次内绿（158 passed 内含）。
- spike 证据：`.agent-team/streams/hard-problems.md`（Q1~Q5 全过，两线 EV 口径漂移 0.0048 EV）。

### F14 decide region.* 接线 — PASS
- B1：`python -m pytest tests/unit/test_decide_region_wiring.py -q` → **21 passed**（映射 8 + 指标键 3 + YAML 4 + e2e 2——含真 SinglePhotoLoop 掩码→测量→决策→渲染→测量闭环、crop 采纳后掩码失效、S-5 reliability 门控、I-1 compose 变化指纹失效）。
- strict lint 回归：`test_tone_clarity_rules.py` 在 B9 批次内绿（默认规则包在键宇宙注册后仍全 lint 通过）。

### F15 M1 验收资产 — PASS
- B1b gate golden 全绿（10 passed 含 20-features 守卫 / sha256 一致 / --check 零漂移 / 逐 feature 快照比对）。
- B6 `--check` → OK（20 features）。render/README.md 模块清单含 region_adjust（stream-3 自证，tester 抽验 README 计数 18 与 modules 文件数一致未单列命令——形态性核查移交 qa 抽查）。

### F16 THIRD_PARTY_NOTICES.md — PASS(移交 qa 总审事实核查)
- 存在性：仓库根 `THIRD_PARTY_NOTICES.md`（19,241 bytes，2026-09-07 01:38），头部注明素材唯一来源 `.agent-team/research/license-inventory.md`。
- 连带断言：`test_model_licenses.py` 在 B3 批次内绿。

### F17 scipy/PyYAML 依赖声明 — PASS(移交 qa 总审)
- 本机实查：`requirements.txt:7 pyyaml>=6.0`（必装）；`pyproject.toml:17 pyyaml>=6.0` + `:32-35 scipy` 注释「可选项（render/core/color.py 懒 import）」+ requirements.txt:10 注释「可选: scipy（标定/拟合工作流）」。与 design 口径（PyYAML 必装/scipy 可选）一致。
- 生效性连带：`test_tone_clarity_rules.py` 绿（YAML 规则加载路径真实走通）。

### F18 DNG SDK clean-room 复审评估 — PASS(移交 qa 总审，不做决策)
- 存在性：`.agent-team/research/dng-sdk-review.md` 落盘。

### F19 感知质量门禁提案 — PASS(移交 qa 总审，不实施)
- 存在性：`.agent-team/research/perceptual-gate-proposal.md` 落盘。

### F20 changelog 本轮批次 — PASS(移交 qa 总审)
- 时序依赖：F20 成文在 qa-final 之后（writer 收尾件），tester 不阻塞；qa 总审时核对覆盖至最新 commit。

---

## 2. 全量回归（B7）——对齐基线

```
python -m pytest tests -q -m "not e2e" -rs
→ 1474 passed, 5 skipped, 1 xfailed, 13 warnings in 189.22s (0:03:09)
```

- **vs 基线 1396/5/1：passed +78，skip 5→5（逐条相同），xfailed 1→1，failed 0。红线全过。**
- 13 warnings 与基线存证同类（fastapi testclient 弃用提示 / torch requires_grad 1 条 / torch.jit.script 11 条），无新增类别。
- **+78 逐项对账**（git diff f357b35..HEAD -- tests/ 实测 def 计数）：
  | 来源 | 运行时增量 |
  |---|---|
  | test_region_adjust.py（新增，27 def 含参数化） | +32 |
  | test_region_masks_channel.py（新增） | +23 |
  | test_decide_region_wiring.py（新增） | +21 |
  | test_film_cards_oklch.py（7→8） | +1 |
  | test_preview_session.py（20→21，F09 canonical 确认） | +1 |
  | test_multimodel_segmenter.py（11→12，F04 新语义） | +1 |
  | test_patch_protocol.py（20→23 def，F09 +3） | +3 |
  | test_vision_extras.py（6→5，F03 删 fairface 用例） | −1 |
  | test_vision_router_semantics.py（21→18，F03 删懒加载节 3 用例） | −3 |
  | **合计** | **+78 = 1396+78 = 1474** ✔ |

## 3. skip / xfailed 清单（与基线 qa 复核逐条对照）

| # | 位置 | 原因 | 与基线一致 |
|---|------|------|-----------|
| 1 | tests/regression/test_gate_e2e_ab.py:20 | RAW_PATH 未设 | ✔ |
| 2 | tests/regression/test_gate_e2e_perf.py:49 | RAW_PATH 未设 | ✔ |
| 3 | tests/unit/test_learned_isolation.py:48 | learned/ 目录未建（隔离门预铺） | ✔ |
| 4 | tests/unit/test_proxy_metrics.py:113 | 空参数集（语料未注入 env） | ✔ |
| 5 | tests/unit/test_sapiens_body.py:266 | 无本地 sapiens 权重 | ✔ |
| x | xfailed 1 项 | 不变 | ✔ |

无新增 skip、无 skip 复活为 fail、无 xfail 转 pass。

## 4. 专项批次汇总（命令与结果索引）

| 批次 | 命令（工作目录 K:\work\project\pixo） | 结果 |
|------|--------------------------------------|------|
| B1 M1 单测 | `python -m pytest tests/unit/test_region_adjust.py tests/unit/test_region_masks_channel.py tests/unit/test_decide_region_wiring.py -q` | **76 passed in 1.24s** |
| B1b gate 金样本 | `python -m pytest tests/regression/test_gate_golden.py tests/regression/test_goldens_v0.py tests/unit/test_gate_golden_tool.py tests/regression/test_gate_coverage.py -m "gate and not gate_e2e" -q` | **10 passed, 16 deselected in 25.07s** |
| B2 oklch 域 | `python -m pytest tests/unit/test_hsl_oklch.py tests/unit/test_split_tone_oklab.py tests/unit/test_film_cards_oklch.py tests/unit/test_patch_protocol.py -q` | **73 passed in 1.25s**（分文件 18/18/8/29） |
| B2b canonical | `python -m pytest tests/integration/test_preview_session.py -q -m "not e2e"` | **21 passed in 0.67s** |
| B3 清债域 | vision+segmenter+licenses+tech_debt 十文件 `-q` | **99 passed, 2 skipped in 9.22s** |
| B4 A1 逐位 | `PYTHONPATH=src python .artifacts/_f07_pin_hsv_render_check.py .artifacts/tester_f10_hashes_after.json` + 三方 sha256 比对 | `cards=23 pinned_stage_entries=69`；**23/23 全等（tester=F10 存证=钉域前基线）** |
| B5 RAW 金样本 | `python src/pixo/render/tools/gate_golden.py compare --samples D:/tmp/pixo_t108/samples.json --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512` | **24/24 PASS，u8_max=0/u16_max=0，RESULT: PASS** |
| B6 gate --check | `python tests/regression/goldens/generate_gate_goldens.py --check` | **CHECK: OK（20 features 与现有 manifest 一致）** |
| B7 全量 | `python -m pytest tests -q -m "not e2e" -rs` | **1474 passed, 5 skipped, 1 xfailed in 189.22s** |
| B8 前端 | `cd frontend && npm run typecheck && npm run test:unit` | tsc 零错误；**11 pass / 0 fail** |
| B9 邻域 | loop/decide/export/链序 12 文件 `-q -m "not e2e"` | **158 passed in 4.34s** |

### B4 比对方法说明（透明记录）
tester 首次比对用整值相等误报 23/23 mismatch——定位为 manifest 新增元数据字段 `pinned_hsv_stages`（钉域前为空数组、钉域后记录钉了哪些 stage，属钉域动作自身的记录字段）所致；仅比对渲染实质字段 `sha256_float32`+`shape` 后 23/23 全等。dev 两份存证（f07_before / f10_after）同样仅差该元数据字段，与 stream-2「23/23 全等」结论一致。**非 bug**，比对口径已在本节留证。

## 5. bug 清单

**阻断/重要/一般：0 项。**

无需退回任何开发流的缺陷。过程中两项非 bug 观察：
1. §4 B4 比对口径（元数据字段 vs 渲染字段）——tester 方法论记录，不涉代码。
2. F11 交付形态缺口（.md 未落盘，§1 F11）——流程项非代码缺陷，移交 qa 总审跟踪。

## 6. 遗留与移交 qa 总审清单

1. **F11 `.artifacts/skin_colorcal_oklch_ab.md` 未落盘**（JSON 已在 03:10 落盘，skin 维度结论「不劣于(小值)」已在 summary；colorcal 维度结论需人读报告确认）——qa 总审核对最终成文。
2. F01/F16/F17/F18/F19/F20 的文档事实核查（数字溯源/许可准确性/覆盖完整性）——主责 qa 总审（tester 已核存在性与连带断言）。
3. stream-2 遗留：gate manifest reviewer 字段治理（.f10_ok 已记录 qa 处理方式）；卡 JSON `stages` 信息性字段与真实链序不一致（范围外记 observations，未动）。
4. stream-3 遗留（评审裁决记债/留后，均有测试或台账钉住）：region_rules 未入 DEFAULT_RULES；I-2 px-rect 跨分辨率（tech_debt 条目 17 + 钉现状测试）；S-4 限流器波及 region.*（未入默认包无生产影响）；I-1 v2 重分割；S-6/S-7/S-8。
5. LLM env 三件套 e2e：用户未提供 env（任务书非目标），**未验证**——非本轮范围。

## 7. 测试资产

- 测试计划：`K:\work\project\pixo\.agent-team\test-plan.md`
- 本报告：`K:\work\project\pixo\.agent-team\test-report.md`
- A1 复验产物：`K:\work\project\pixo\.artifacts\tester_f10_hashes_after.json`（复现：`PYTHONPATH=src python .artifacts/_f07_pin_hsv_render_check.py <out>`）
- 全部命令均可在 master@fc2bfa8 工作树原样复跑。

---
> tester 章：2026-09-07T03:14+08:00 —— F01~F20 全量测试验证完成：全量 1474 passed / 5 skipped / 1 xfailed（0 failed，基线不降 +78 全部对账），专项四域全绿，RAW 24/24 逐位零漂移，阻断性 bug 0。移交 qa 总审。
