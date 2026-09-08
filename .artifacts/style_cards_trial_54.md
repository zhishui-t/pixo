# style_cards 默认开否 —— 54 张语料双臂 loop 评估（R20）

- 日期：2026-09-08 · 任务：R20 · 供队长裁决（本报告不做决策）
- 执行：`.artifacts/style_cards_trial54.py`（54 照片 × 双臂 = 108 次 SinglePhotoLoop 全链，0 error；三次后台跑批经 checkpoint 续跑合成全量）+ `.artifacts/style_cards_trial54_aggregate.py`
- 双臂单变量：A = `enable_style_cards=False`（现状默认，R13 裁决）/ B = `enable_style_cards=True`；其余全生产缺省（DEFAULT_RULES 含 region_rules、prompts 缺省、max_iterations=3、compose 4:3、preview 512、MultiModelSegmenter）
- 机读：`.artifacts/style_cards_trial_54.json`

---

## 1. 结论（前置）

1. **建议：维持关（数据净负收益）**。开卡使 QC 达标率 **38.9% → 33.3%（−5.6pp）**：3 张 A 臂 pass 照片在 B 臂落入 **escalate_2x（MANUAL_REVIEW）**，0 张反向改善（无任何 escalate→pass 迁移）；state 迁移 ACCEPTED→MANUAL_REVIEW ×3。
2. **R13"提前压光"现象在语料级复现**：portra 卡 `if_highlight_clip_ratio_gt_0.03 → exposure_−0.15`（唯一有执行位的卡规则）在 **10/54 张**照片触发 22 次轮次、落位固定值 −0.15；其中 2 张实测"卡压光后溢出证据消失"（5276: 4.26%→2.79%、5277: 4.13%→2.61%），5277 的终态恰为 pass→escalate_2x 负迁移本人——卡片压光改变了闭环轨迹并触发二次超标。
3. **影响面**：54 张中 **10 张（18.5%）** 渲染被改变（变化子集 ΔE2000 median 1.93 / max 3.12，像素变化率 median 86%）；其余 44 张 ΔE=0。
4. **触发面质量差**：6 张 builtin 卡中 7 条规则在 **全部 54 张、每轮无条件触发**（cinestill 的 `if_night_neon`/`if_skin_too_cyan`、TriX/HP5 的 5 条——条件键不满足 `_parse_if_condition` 的 `if_<metric>_<op>_<value>` 解析式 → 条件缺失 → 无条件命中），且其动作参数**全部无执行位**（loop 降级为顶层 informational 键）——118 轮次 × 7 规则的 decide 噪声、零像素贡献。
5. **边界声明**：本结论仅针对**当前 6 张内置卡 v0**（规则式建议、条件解析器覆盖不全）在**本 54 张 Nikon 语料**上的表现；不外推到"风格卡概念本身"或未来人工策划的卡集。

---

## 2. 证据

### 2.1 QC 迁移表（54 张，A=现状 → B=开卡）

| A \ B | pass | escalate_2x | 合计 |
|---|---:|---:|---:|
| **pass** | 18 | **3 ← 负迁移** | 21 |
| **escalate_2x** | 0（无正迁移） | 33 | 33 |
| 合计 | 18 | 36 | 54 |

- 达标率：A 21/54 = **38.9%** → B 18/54 = **33.3%**。
- state 迁移：ACCEPTED→MANUAL_REVIEW ×3（51/54 不变）；`qc_rollback` 总数 A 35 → B 38；iterations A=B=3（max_iterations 顶格）。

### 2.2 三张负迁移照片（唯一 QC 变化方向）

| 照片 | A 终态 | B 终态 | B 触发 | 机制 |
|---|---|---|---|---|
| DSC_5277 | pass/ACCEPTED | **escalate_2x/MANUAL_REVIEW**（1 次 QC 回退） | it=1 portra 压光 −0.15（clip 3.50%>3%） | 溢出 4.13%→2.61%（证据消失）→ 渲染整体改变（ΔE 2.82、97.8% 像素变化）→ FINAL_QC 二次超标 |
| 其余 2 张 | pass | escalate_2x | 同 portra 规则族 | 同机制（10 张落位照片内） |

- 三张的 final exposure 落位：B 臂出现 `target_offset: −0.3` 类负向偏移（A 臂无）。
- 无一例 B 臂因卡片而"变好"：escalate_2x 的 33 张在两臂间无进出。

### 2.3 ΔE 影响面

| 指标 | 全体 (54) | 变化子集 (10) |
|---|---:|---:|
| ΔE2000 mean | median 0.000 / p95 2.452 / max 3.120 | median 1.928 / p90 3.026 / max 3.120 |
| 像素变化率 (≥1/255) | — | median 85.7% |

### 2.4 触发面（B 臂 trace，118 轮次样本）

| 规则 | 触发照片 | 轮次 | 执行位 |
|---|---:|---:|---|
| cinestill_800t_if_night_neon / if_skin_too_cyan | 54/54 | 118×2 | **无**（informational） |
| kodak_trix_400_if_monochrome / if_sky_flat | 54/54 | 118×2 | **无** |
| ilford_hp5_plus_if_flat_light / if_shadow_muddy / if_dmax_insufficient | 54/54 | 118×3 | **无** |
| **kodak_portra_400_if_highlight_clip_ratio_gt_0.03** | **10/54** | 22 | **有 → exposure −0.15**（唯一落位） |
| cinestill_800t_if_highlight_clip_ratio_gt_0.05 | 6/54 | 18 | 无（halation_glow informational） |

- 无条件触发的机理：`cards.py:320-337 _parse_if_condition` 只解析 `if_<metric>_<op>_<value>` 形式；`if_night_neon` 等标签式条件解析失败 → `condition=None` → 引擎无条件放行。日光照片上"夜景霓虹卡"每轮建议 = 卡 schema/解析器的覆盖缺口（非引擎缺陷）。
- portra 规则的落位值恒为卡面固定值 −0.15（与 QC 回退的曝光动作同幅同向），触发的 10 张 highlight_clip 3.5%~16.2%。

### 2.5 提前压光（R13 现象）语料级频率

- 溢出证据被卡消除：**2/54**（5276、5277，见 §2.2）；另有 5240-5245 高溢出组（clip 5.7%~16.2%）卡片连轮 −0.15 但溢出未降至阈下（证据未消失，终态与 A 臂同为 escalate_2x）。
- R13 集成测试记录的漂移方向（MANUAL_REVIEW→ACCEPTED）在本语料未出现；出现的是**反方向**（pass→MANUAL_REVIEW）——两种方向都源于同一机制：卡在 QC 之前改变图像，使 QC 所见不再是决策前的状态。

---

## 3. 三选一结论：**维持关（现状默认）**

- **默认开**：被数据否决——达标率 −5.6pp、3 负迁移/0 正迁移、7 条无条件规则对 100% 照片产生 decide 噪声。
- **需人工观感**：不适用——数据不是中性的（有单向显著的 QC 恶化）；"风格是主观的"论点只覆盖 ΔE 差异本身，不覆盖 QC 迁移损失。
- **维持关**：与 R13 裁决一致且现在有了语料级量化依据（R13 时只有集成测试个例）。`PIXO_STYLE_CARDS` 显式开启路径保持可用（功能本身无阻断性缺陷）。
- 若未来要重开评估，前置条件建议：① 卡 schema 的条件键全量可解析（消灭无条件触发）；② 每条建议声明执行位映射（无执行位的建议不进 decide_context）；③ portra 的 exposure 建议与 QC 回退动作去重（同一信号不重复处置）。满足后再跑同款双臂 trial。

---

## 4. 来源

- 实验脚本/数据：`.artifacts/style_cards_trial54.py`、`.artifacts/style_cards_trial54_aggregate.py`、`.artifacts/style_cards_trial_54.json`（54 runs 全量机读）
- 被测机制：`src/pixo/pipeline/loop.py:110-135`（PIXO_STYLE_CARDS 开关与 R13 裁决注释）、:764/:853-874/:1467-1471（enable_style_cards 注入 decide_context）、:12（引擎 FINAL_QC 回退=Exposure −0.15 一次）；`src/pixo/know/cards.py:147-300`（6 张 builtin 卡与 recommended_adjustments）、:320-350（_parse_if_condition/_parse_action——条件解析覆盖缺口的来源）、:353-379（卡→规则 priority 6000）
- R13 原始证据：`tests/unit/test_loop_style_cards.py:9-13`（"卡条件命中 → exposure 落位 → 渲染变暗"的闭环断言）与 `loop.py:116-119` 裁决注释（"QC 回退集成测试中 portra 卡提前压曝光，溢出在 QC 前消失，MANUAL_REVIEW 漂移为 ACCEPTED"）
- 方法基线：`.artifacts/_r15_region_trial54.py`（R15 双臂/checkpoint/qc_class 打法）、`.artifacts/region_trial_54.md`
- 推测项标注：①"信息性规则的 decide 噪声"对 LLM/agent 上下文的干扰未单独量化（本轮无 agent_suggest 臂）；②卡集 v1 的行为需另行评估（本结论限于 builtin v0，置信度高）；③达标率基线 38.9% 偏低属语料难度（33 张 escalate_2x），与本次单变量结论无关。
