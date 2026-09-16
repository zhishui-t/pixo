# 感知质量门禁提案（CR-15 #7 / tech_debt 条目 7）— 提案，不实施

> 起草：`dev-ledger`（R22 stream-2b，2026-09-10）。状态：**提案**（本轮只落文档，不改代码/不接 CI）。
> 依据：`docs/tech_debt.md` 条目 7（金样本门禁仅防像素漂移，不衡量与相机原图的观感差距）、
> CR-15 #7、`.agent-team/exploration-r22.md §9.2`（可复用资产）。
> 行数上限 120（本文件按可执行口径写，不写愿景）。

## 1. 现状缺口（实测）

| 面 | 现状 | 缺口 |
|---|---|---|
| 金样本 gate | `tests/regression/goldens/gate_cases.py:25-42` = **21 个合成 feature**（纯函数/`build_default_pipeline` 快照）；阈值 `src/pixo/render/tools/gate_golden.py:35` = **8bit max\|Δ\|≤1/255、16bit ≤1/65535** | 只防**像素漂移**；输入是合成数组，**不含相机参考**，故对"观感变差"零敏感 |
| 语料级 A/B | `scripts/run_ab_regression.py` → `docs/metrics/ab_regression.md`（44 张三层抽样；分带阈值：室内 dE≤12 / 夜景 dE≤20 / 高调 \|dL\|≤6 且 clip≤cam×1.5 / 其余 \|dL\|≤8；基线 **13/44 超限**） | 是**人工报告**，无 CI 判据；且该报告的色差口径是 `ab_vs_camera_thumb.py:43` 的 **cv2 u8 Lab 欧氏范数（ΔE76）**，与 src 单源 ΔE2000 **不可混用** |
| 感知工具单源 | `src/pixo/pipeline/perceptual.py:32 JND_DELTA_E=2.3`、`:58 delta_e_2000`（Sharma 2005）、`:113 delta_e_median`、`:129 JndConvergenceTracker` | 已有单源，但**未接入任何门禁** |

## 2. 复用资产（不重复造）

| 资产 | 位置 | 本提案用法 |
|---|---|---|
| ΔE2000 + JND 单源 | `pipeline/perceptual.py:32/58/113` | 判据唯一色差实现；**禁**再引入 cv2 Lab 欧氏 |
| 相机内嵌预览取图 | `scripts/ab_vs_camera_thumb.py:13-30 cam_thumb()`（含 EXIF 旋转）+ `Renderer.render_preview_full(long_edge=1024)` | 参考图与"我们"两条渲染线的取图契约 |
| 分层语料回归框架 | `scripts/run_ab_regression.py`、`docs/metrics/ab_regression.md` | 语料/分层/分带口径 + 基线超限样本 |
| 归因分类 | `docs/metrics/ab_highlight_stress.md:35`（文件/层/ΔE/dL/da/db/clip 比值/归因） | 失败样本的**归因矩阵**（风格意图 vs 缺陷） |
| 分布档 | `docs/metrics/proxy_distribution.md`、`scorer_distribution.md` | 美学阈值**锚定分位来源**（只作软告警，见 §5） |
| gate 骨架 | `gate_cases.py` + `gate_golden.py --check` + `tests/regression/test_gate_golden.py` | 见 §4：**本层不复用 pixel gate**，只复用"门禁=可复跑命令+留证"的形态 |

## 3. 判据（三层，全部可执行/可复跑）

统一口径：**同图、同 long_edge（1024 preview）、±1 次渲染、无参数差异**；参考 = 相机内嵌预览
（`cam_thumb`）；色差一律 `delta_e_2000`；分位数取逐照片 median 后再取语料 p50/p90（与
`eval_rp_ccm_ab.py` 的"逐照片 median → 语料分位"口径一致）。

| 层 | 判据 | 阈值来源 |
|---|---|---|
| **L1 语料分位** | ΔE2000 **median(p50) 相对基线不劣化 ≥15%**；**p90 不得劣化** | 阈值形态沿用 `docs/OWN_PIPELINE_STAGE2_DESIGN.md:38` 的 RP-CCM 转正门槛（median≥15% / p95 不劣化）族；**基线数值须本轮之后专门标定**（见 §6），禁止凭空写死 |
| **L2 单张回归** | 单张 median 回归 **>1 JND（2.3 ΔE2000）** 的**张数不得超过基线张数** | JND 单源 `perceptual.py:32`；>1 JND 口径同 stage2 门槛第 2 项 |
| **L3 结构性副判据** | \|dL\| 与 clip_hi 比值沿用既有分带（室内/夜景/高调/常规，见 §1 表） | `docs/metrics/ab_regression.md:7-9`（**ΔE76 口径**，迁移到 ΔE2000 时须同时重标） |
| **L4 美学** | 只出 `soft_warnings`，**不作硬门禁** | CR-11 红线（`aesthetic_accept_threshold` 非硬门禁）；`scorer_distribution.md` 记录跨域不可比结论 |

## 4. 与现有 gate 的关系（边界写死，防误接线）

1. **21 个 pixel feature 的 golden gate 不动**：其输入是合成确定性数组、输出逐位可比；
   本层输入是真实 RAW + 相机参考，**逐位不可比**，两者必须分层。
2. **不得**把本层塞进 `gate_golden.py --check`（会把 `u8_max=u16_max=0` 的零漂移口径污染成
   阈值口径，且使既有 21 features 的"逐位"语义失去意义）。
3. **不得**给 `gate_cases.py` 加"相机参考 case"：case 机制要求确定性输入（`gate_cases.py:1`
   docstring），相机内嵌预览不可在仓库内确定性复现。
4. 落地形态（建议）：`tests/regression/test_gate_perceptual.py`，`@pytest.mark.gate_e2e`
   （沿用仓库既有"需真实 RAW，路缺失即 skip"规约，见 `pyproject.toml:68-74` markers），
   判据逻辑放 `src/pixo/pipeline/perceptual.py` 的**新增纯函数**（`evaluate_perceptual_gate()`），
   使阈值可单测、可离线复算。
5. `.artifacts/gate_calibration_coverage.md:90` 的"rp_ccm 运行时接线后补第 3 个标定敏感 case"
   是**另一件事**（标定表敏感），不要与本层混做。

## 5. 失败处置（分级，先定处置再定阈值）

| 级别 | 触发 | 处置 |
|---|---|---|
| **硬失败（阻断合并）** | L1 median 劣化 ≥15%，或 L2 单张 >1JND 张数超基线，或 L3 \|dL\| 超带 | 门禁红 + 落 `docs/metrics/perceptual_gate_report.md`（逐样本 ΔE/dL/da/db/clip + 归因列） |
| **软告警（不阻断）** | L1 p90 劣化 0~15%；L4 美学分下降；clip 比值在分母（相机 clip_hi）**<0.05%** 时的外推 | 报告加"分母近零、比值无统计意义"标注，改用**绝对 clip 差**（`ab_regression.md:57` 结论 5） |
| **人工复核（不得自动判定）** | da/db 主导的结构性色偏（如 `ab_regression.md` 44 张中 1564/2690 型） | 按归因矩阵分类"风格意图 vs 缺陷"，由 reviewer/QA 判定；**禁止**自动改阈值 |

## 6. 阈值标定步骤（可执行；本轮不做，属落地轮次）

```powershell
# 0) 前置：语料路径（本机 0711/spring/xiamen 三层 44 张，见 ab_regression.md:4-5）
# 1) 现基线（ΔE76 口径，已有）：python scripts/run_ab_regression.py
# 2) 新口径基线（ΔE2000）：扩展脚本输出 delta_e_median / p50 / p90 / >1JND 张数
python scripts/run_ab_regression.py            # 产出 JSON 落 .artifacts/
# 3) 门限 = 基线 p50 × 0.85（即允许劣化 ≤15%）+ 基线 p90 上限；写入
#    docs/metrics/perceptual_gate_baseline.md（新增，含语料清单 + sha256 + 命令 + 分位表）
# 4) 冻结后 CI/门禁只跑 compare，不跑 generate
```

- **验收（提案自身）**：门限文件必须给出**语料 sha256 + 命令 + 分位表**（可复跑）；缺任一项即视为
  未标定，判据不生效。
- **成本（如实）**：按既有 preview 口径（long_edge=1024，44 张）+ 真 RAW 串行渲染纪律（R22 A7：
  禁与 pytest 并发）；本轮**未实测**全量耗时，落地时以脚本计时为准，超预算时降到既有分层
  抽样下限并在报告写明。

## 7. 非目标 / 开放项

- 不改 21 features golden、不改 `gate_golden --check` 语义、不新增第三方依赖（ΔE2000 已自研）。
- 不把美学分作硬门禁（CR-11）；不做 learned ISP/LLM 判图。
- 开放项：①`docs/metrics/ab_regression.md` 的 ΔE76 分带阈值**是否随本层重标**（建议重标并保留
  旧口径一版）；②语料 44 张是否需要扩到"高 ISO/夜景"专项子集（与 F02 降噪 A/B 语料复用）。
