# 阶段二 §5 红线验收报告 —— 新表全量回归（t34）

- 日期：2026-09-04
- 执行：tester-1（长安）
- 基线提交：`bca52ed`（feat(render): 阶段一自研渲染管线）
- 设计依据：docs/OWN_PIPELINE_STAGE2_DESIGN.md §5 验收门「红线」行

## 结论（TL;DR）

**红线三项：2 过 + 1 按预案分支处理（不豁免，待入库后补验）。**

| # | 红线项 | 判定 | 说明 |
|---|---|---|---|
| 1 | 金样本按新表重生成（reviewer 流程） | ⏸ **本轮 N/A（对照档分支）** | 队长未确认入库，新表仅在 `configs/color/calib_out/`（对照档），正式 configs 未替换。按任务预案：**本轮金样本不重生成**，只验现行表回归不变（见 §2），入库后须按 §5 SOP 补验 |
| 2 | 全量 pytest 绿 | ✅ **1297 passed / 4 skipped / 1 xfailed**（288s，与 t32 基线逐字一致） | `python -m pytest tests/unit tests/regression tests/integration` |
| 3 | `src/pixo/render` git diff 为零 | ✅ **0 行 diff / status 空** | 运行时零变化达成：新表只进 configs（且是 calib_out 对照目录）；测试前后各复核一次，无测试副作用 |

## 1. 红线 3：运行时零变化（✅）

- `git diff -- src/pixo/render` = 0 行；`git status --porcelain src/` 为空。
- 全仓 `src/` 无任何修改（t32 后从未触碰）；测试全量运行前后各复核一次，无副作用。
- 未发现任何「需要改 src 才能接新表」的情况——θ 载体（warmth/exposure/neutral/rp/skin）全部经现行加载链读 configs，无需上报队长的代码变更。

## 2. 红线 2：全量回归（✅ 现行表不变）

```
1297 passed, 4 skipped, 1 xfailed, 13 warnings in 288.46s (0:04:48)
```

- 与 t32 交付时报告的基线（1297/4/1）**逐字一致**，含 `tests/regression/` 全部金样本门（test_gate_golden、test_gate_calibration、test_gate_e2e_ab 等 20 个门文件）——证明本轮所有新产物（scripts/calib/、calib_out/、三个新单测文件）对现行运行时**零回归**。
- warnings 13 条均为既有环境警告（starlette/torch jit 弃用 + 1 条测试内 requires_grad 标量转换提示），非本次引入的功能性问题。

## 3. 红线 1：金样本重生成 —— 对照档分支（⏸ N/A，附敏感性证据）

### 3.1 决策事实链（为什么本轮不重生成）

任务预案：「金样本重生成需队长先确认新表入库位置（calib_out 对照档 vs 替换正式 configs）——若为对照档则本轮金样本不重生成，只验现行表回归不变」。

仓库现状核查（2026-09-04）：

| 检查 | 结果 |
|---|---|
| `git diff --stat configs/`（正式表全部） | **空**（正式 configs 未被替换） |
| `configs/color/calib_out/` | 未跟踪新目录（6 个文件），即对照档 |
| `git log` 最近提交 | `bca52ed`（阶段一收口），无新表入库提交 |

→ **新表当前为对照档，正式表未替换**，按预案走「不重生成」分支。现行表回归不变已由 §2 全绿覆盖。

### 3.2 敏感性证据：金样本对新表锁得住（入库后必然触发重生成）

对 calib_out 新表 vs 正式表逐组件 JSON 对比：

| 组件 | 正式位置 | calib_out 新表 | 差异 |
|---|---|---|---|
| RP-CCM | `configs/color/rp_ccm_nikon_z5_2.json` | 同名 | **matrix 实质不同** |
| warmth 曲线 | `configs/calibration/warmth_curve.json` | `warmth_curve.json` | **5 结点 RGB 增益实质不同**（如首结点 [0.951, 1.000, 1.000] → [1.174, 0.919, 0.889]） |
| 中性裁剪 | `resources/camera_profiles/z5ii_neutral_trim.json` | `z5ii_neutral_trim.json` | **a/b 曲线 7 结点实质不同**（如 a[0] −2.0 → −1.499） |
| target_offset | `src/pixo/render/target_offset.json` | `target_offset.json` | **cal_table 第三列实质不同**（如 1.094 → 1.409） |
| skin 椭圆 | `configs/color/skin_oklab.json` | 同名 | 相同（阶段二未动 skin，合理） |

4/5 组件实质变化 → 新表替换正式 configs 后，现行金样本**必然**失配，红线 1 的重生成+reviewer 流程在入库时不可跳过。

### 3.3 入库后的补验 SOP（含 G-4 已知坑）

新表入库（替换正式 configs）当日，tester 须执行：

```bash
# 合成金样本入口是 tests/regression/goldens/generate_gate_goldens.py（注意:
# render/tools/gate_golden.py 是另一套 RAW golden 生成器, 条目结构互不兼容,
# 勿混用——本报告初版此处误写为 tools 入口）。G-4 已修复（默认路径改正确 +
# src 路径自举）, 现行命令无需 PYTHONPATH 与显式 --out:
python tests/regression/goldens/generate_gate_goldens.py --check
python tests/regression/goldens/generate_gate_goldens.py
# 之后走 reviewer 人工审查入库（阶段一 §112 行流程），再跑全量 pytest
python -m pytest tests/unit tests/regression tests/integration
```

注意：金样本是**运行时输出**快照，重生成须以「新表已替换进正式 configs」的状态运行（calib_out 对照档不进加载链，对生成器无效果）。

## 4. 验收门其余两项关联状态（引用 t32/t30 产出，非本轮范围）

- 保真门：surrogate vs 真实管线 ΔE median ≤0.05 / p95 ≤0.3 —— 见 `.artifacts/surrogate_fidelity.md`（t30）。
- 标定收益：真值 ΔE2000 median 6.658→4.244（+36.3%）—— 见 `.artifacts/calib_run.md`（t32）。
- 可复现：seed + 语料清单 + `calib_opt_samples.npz` + `--resume` 重放逐位一致（t32 单测锁定）。

## 5. 下游提示（t35 QA 终审）

1. QA 审计 git diff 时，`configs/color/calib_out/`、`scripts/calib/`、三个新单测、本文档均属阶段二**预期新增**，`src/pixo/render` 零改动是红线达成证据而非遗漏。
2. 红线 1 的闭环条件 = 队长确认入库方案 → 执行 §3.3 SOP → 全量绿。当前状态请勿视为「金样本已按新表验证」。
3. 若入库采取「逐组件灰度」（如先转 RP-CCM 不转 warmth），金样本须在**每个灰度步**重生成一次，不建议合并跳步。
