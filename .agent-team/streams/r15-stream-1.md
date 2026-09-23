# r15-stream-1 报告（dev-1）— 54 张语料 region 规则试水观察

> 2026-09-07 · R13 入包系数（sky -0.25 / plant 0.2 / 护栏 area<0.70）的复权数据回收。零生产代码改动。

## 做了什么

- 采集脚本 `.artifacts/_r15_region_trial54.py`：语料 = `iter_corpus("exports/auto/full_scan")`
  同源枚举 **54 张**（hsm_oklch_eval 同款布局，RAW 全部在机）；双轨 SinglePhotoLoop
  （A=DEFAULT 剔除 region / B=DEFAULT 全量试水），真分割栈 segformer+rfdetr，
  prompts=["sky","plant"]，manual_on_unreliable=False；**增量 checkpoint**（每样本
  落盘，环境两次中断后台任务后断点续跑补齐，54/54 零错误）。
- 聚合脚本 `.artifacts/_r15_region_trial54_aggregate.py`（含口径重分类：运行中
  进程的 blocked 混入同值去重轮，以 area_ratio 原始值拆分护栏拦截 vs 去重）。
- 运行成本：预估 45 min（50s/样本），**实际 ~120s/样本、总计算 ~108 min**
  （双轨 × 3 轮 × (渲染+真分割+测量) + FINAL_QC 全图渲染），分三段执行。

## 核心数据（全表见 `.artifacts/region_trial_54.md`）

| 维度 | 结果 |
|---|---|
| 触发率 | **28/54（52%）**：sky 17 / plant 26 / 零触发 26（夜景等无区域内容） |
| 参数量级 | median 0.137 EV / p90 0.371 / **max 0.422（无一超 ±0.5）** |
| 护栏拦截 | **0/54**（触发轮 area 中位 0.169、max 0.575——本语料未触 0.70；护栏休眠保险态，拦截价值由 R13 high_contrast 个案背书） |
| QC 达标率 | **48% → 57%（净 +9pp）**：7 救回（escalate_2x→pass）/ 2 回退（pass→escalate_2x） |
| ΔE（触发样本） | median 1.60 / p90 2.53 / max 2.96 |
| S-4 吞轮 | plant 正向决定 35 次中高溢出（≥2.5%）决定 **2 次、吞 2 次（2/2）**；整体频率 2/35=6%，自恢复一轮 |

## 归因（复权建议的关键）

- **7 张救回全部由 sky 压暗驱动**（sky_EV -0.26~-0.36；其中 DSC_5243/5245
  为纯 sky 触发，sky-only 层 QC 0→2 全正）。
- **2 张回退（DSC_5276/5277，同场景连拍）均为 sky+plant 共火**：plant
  +0.13 EV 作用于 35~38% 暗部植被区推高溢出至二次超标——plant 提亮是
  回退疑似主因（sky 压暗方向相反）。plant-only 层（15 张）QC 中性。
- S-4 whipsaw：5276/5277 it1 压制 → it2 溢出回落 → 提亮落地 → 推高溢出
  → 二次超标（吞一轮反而延迟了暴露）。

## 复权建议：**c) 中间值——分层复权**

- **sky 复权全量（-0.25→-0.5）**：零回退 + 7 救回主驱动 + 纯 sky 层全正。
- **plant 维持试水（0.2）**：收益未证（plant-only 层 QC 中性）且回退/
  S-4 whipsaw 均与 plant 提亮共现；plant-only 层 15 张提供持续观察面。
- 若要求单一系数：先 plant 减半至 0.1（回退主因），sky 维持试水，
  sky 复权置后单独议。

## 文件

- `.artifacts/region_trial_54.md`（正式报告）+ `region_trial_54.json`（机读）
- `.artifacts/_r15_region_trial54.py` / `_r15_region_trial54_aggregate.py`（复现）

## 遗留

1. plant 回退机理（提亮推高溢出）如需根治：规则加「溢出条件负联动」
   （preview_overflow_ratio 高时 plant 提亮自动降档）——规则层可表达，
   留下轮议。
2. S-4 引擎豁免议题与 plant 规则强耦合，维持 R13 暂缓结论。
3. 后台任务环境时长上限（~55-60min）两次中断采集——长跑评估建议
   分段执行或由队长侧无上限会话跑。

---

## R15 裁决落地（同日追加）：分层复权执行（sky 全量 / plant 续观察）

### 落地内容

| 文件 | 变更 |
|---|---|
| `src/pixo/decide/rules/region_rules.yaml` | sky 公式 `-0.25→-0.5` 复权全量；plant 维持 0.2；头注改「R15 分层复权」沿革（54 张数据指向 region_trial_54.md） |
| `configs/rules/region_rules.yaml` | 镜像逐字节同步 |
| `tests/unit/test_decide_region_wiring.py` | 钉死断言同步：sky 触发期望 -0.375→**-0.75**、系数串 `-0.25 *`→`-0.5 *`、docstring 改 R15 分层复权依据 |

### 回放抽验（9 张关键样本，`.artifacts/region_replay_spot.json`）

| 样本 | A→B QC | sky 落地值（复权后） | 判读 |
|---|---|---|---|
| DSC_5243（纯 sky 救回） | 二超标 → **pass** | -0.804 / -0.623 | 救回保持，量级恰为试水 2× |
| DSC_5245（纯 sky 救回） | 二超标 → **pass** | -0.811 / -0.628 | 同上 |
| wide_angle（救回） | 二超标 → **pass** | -0.710 / -0.547 | 救回保持 |
| DSC_5276（回退） | pass → **二超标（复认）** | -0.596 / plant +0.130 | sky 复权未恶化新失败模式，回退仍在 |
| DSC_5277（回退） | pass → **二超标（复认）** | -0.610 / plant +0.131 | 同上 |
| night_lowlight（锚） | 二超标 → 二超标 | 无触发 | ΔE 逐位 0 ✓ |
| high_contrast（护栏边界） | pass → pass | 无触发 | area 0.996≥0.70 持续拦截 ✓ |
| day_normal | 二超标 → 二超标 | -0.836 / -0.643 | 全量级恢复（与 R13 首测一致） |
| portrait_tele | 二超标 → 二超标 | -0.584 / plant +0.033 | plant 不变 ✓ |

### 判读（如实呈报）

1. sky 全量级精确恢复（落地值 = 试水值 × 2，误差 <1%）；plant 逐位不变。
2. 2 张纯 sky 救回 + wide_angle 救回在复权后**全部保持 pass**。
3. **回退 2 张（DSC_5276/5277）复权后仍回退**——escalate 触发因素是高光
   溢出二次超标，plant +0.13 EV（35~38% 暗区提亮）与 sky 压暗共火下依然
   越线；sky 复权未使其恶化也未救回。处置建议维持 R15 报告 §遗留 1
   （plant 提亮的溢出负联动，规则层可表达，留下轮），并入 plant 观察
   窗记录。
4. S-4 吞轮签名复认：DSC_5276/5277 it1（ovf 3.5%）plant it2 状态 0.0 →
   it3 状态 +0.130（溢出回落自恢复），与 R13 一致。
