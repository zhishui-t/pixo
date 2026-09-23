# r13-stream-1 报告（dev-1）— region 规则激活评估

> 2026-09-07 · M1「管道通水 → 阀门打开」证据件。零生产代码改动。

## 做了什么

1. **评估脚本两件**（`.artifacts/`，不入库生产面）：
   - `_r13_region_rules_eval.py`：6 张 RAW 金样本 × A/B 双轨 SinglePhotoLoop
     （A=DEFAULT_RULES 9 规则基座 / B=+region_rules 2 规则激活），真分割栈
     `MultiModelSegmenter`（segformer+rfdetr 真权重，sky/plant 无需 NC 门控
     令牌），F13 region_masks 通道全链，max_iterations=3, preview 512。
   - `_r13_region_pure_effect.py`：纯区域效应归一——B 轨终态参数做两次
     RawPreviewSession 渲染，唯一变量 = region_adjust 执行位（剥离全闭环
     轨迹发散）。
2. **诊断修正三处**（均为评估脚本自身问题）：load_rules 的 list 入参按
   「规则字典列表」解析（路径须逐文件装载）；loop 的 prof 须为 `load_dcp`
   装载后 profile 对象；`manual_on_unreliable=True`（生产默认）下请求区域
   真实缺失（area=0）的 4/6 样本在 it1 即 manual_review——评估置 False
   观测，交由 region 规则自身 S-5 reliable 闸。

## 核心数据（详见 `.artifacts/region_rules_activation_eval.md`）

| 项 | 结果 |
|---|---|
| sky 规则触发率 | **5/6**（唯一不触发=夜景 lum<150，条件正判零误触） |
| plant 规则触发率 | **1/6**（portrait_tele 暗部植被 lum 61.8<70） |
| 参数量级 | sky **-0.52~-0.84 EV**、plant **+0.047~+0.066 EV**（clamp 均未触顶）；mode=set 每轮按当前亮度重写，温和震荡不累积 |
| 纯区域效应 | ΔE76 mean 3.15~7.80、变化像素 43~99.7%（与掩码覆盖成正比——大面积分区曝光语义） |
| 正向实证 | wide_angle：A 轨 FINAL_QC 二次超标转人工 ↔ B 轨天空压暗 0.55~0.71 EV 后**达标跑满 3 轮** |
| S-4 交互（F14 遗留实锤） | portrait_tele it1 overflow 11.1% → plant 正向 +0.047 被压回 0.0；it2 溢出归零后 +0.066 自恢复——吞一轮、方向保守、sky 负向不受影响 |
| 误伤面（最高优先发现） | **high_contrast 被 segformer 判 99.6% sky → 全画面压暗 0.52 EV（ΔE7.80/99.7% 像素）**——与 R11 skin 90% 覆盖同族：区域语义在极端覆盖下失效；另 portrait_tele 天空掩码 40.6%（人像虚化背景）被规则压暗属创作语义灰区 |
| night 零误触 | ΔE=0.0 逐位相同 |

## 入包建议：b+) 条件入包（先 YAML 覆盖率护栏，再降量试水）

- a) 直接入：否——99.6% 覆盖全画面压暗是实测误伤，裸入会打大面积天空构图。
- c) 暂缓：过保守——wide_angle 正向实证（救回人工复核）+ night 零误触。
- **建议动作**：
  1. 规则 condition 补 `sky_area_ratio lt 0.70` / `plant_area_ratio lt 0.70`
     （键已注册，**YAML 零代码**）。实证回放：high_contrast 被拦，
     portrait/wide_angle 不受影响。阈值依据同 R11 skin cap 的实测间隙逻辑。
  2. 试水：公式系数减半或 clamp 收紧（[-1,0]/[0,1]），观察窗后复权。
  3. S-4 引擎豁免（region.* 排除出溢出限流）暂缓立项——实测自恢复非阻断，
     随试水观察高溢出场景频度。
  4. 护栏落地后重跑本评估脚本复验触发面（预期 high_contrast 转零触发）。

## 文件

- `.artifacts/region_rules_activation_eval.md`（评估报告）+
  `.artifacts/region_rules_activation_eval.json` / `region_rules_pure_effect.json`（机读）
- `.artifacts/_r13_region_rules_eval.py` / `_r13_region_pure_effect.py`（复现脚本）
- `.artifacts/r13_region_eval/{sample}_A.png|_B.png`（人评素材终图）

## 遗留

1. 护栏 YAML 修改属 configs/decide 规则文件变更——按「激活=改变 decide 默认
   行为」口径，与入包决策一并由队长裁决后落地（本任务零生产改动边界内不动）。
2. scene 分类器接线仍是长期项（R11 遗留）；region 规则现依赖 segformer
   语义类目 + reliable 闸 + （建议中）覆盖率护栏三层防线。
3. portrait_tele 双轨均 FINAL_QC 二次超标——与 region 无关的既有闭环行为
   （人像高光溢出），如需清偿另立议题。

---

## R13 裁决落地（同日追加）：b+ 条件入包执行

### 落地内容

| 文件 | 变更 |
|---|---|
| `src/pixo/decide/rules/region_rules.yaml` | ①两条规则 condition 补 `*_area_ratio lt 0.70` 覆盖率护栏；②公式系数减半（sky `-0.5→-0.25` / plant `0.4→0.2`，注释注明 R13 试水）；③头注改「已入 DEFAULT_RULES + 护栏/试水依据」 |
| `configs/rules/region_rules.yaml` | 镜像逐字节同步（diff=MIRROR-IDENTICAL） |
| `src/pixo/decide/rules/__init__.py` | `DEFAULT_RULES` += `region_rules.yaml`（M1 决策闭环激活；注释指向评估证据） |
| `tests/unit/test_decide_region_wiring.py` | 触发用例 metrics 补 `*_area_ratio`（隔离拦截因素）+ 期望值同步试水系数（-0.375/0.1）；**新增** `test_region_rules_activation_guard_and_trial_coefficients`（护栏/系数/入包三重钉死，复权须显式改断言）+ `_make_default_rules_region_loop` 工厂 + `test_e2e_region_rule_participates_under_default_rules_package`（真默认包闭环） |

注：工作树并行流（dev-2 warmth 批）亦同步了触发用例的 area_ratio/系数期望
（语义与本文一致，注释归因其批次）；reliable 闸用例的 metrics 补齐、激活
钉死断言与默认包 e2e 为本流补齐。

### 回放验证（修正基线定义后；三修过程见「回放脚本基线伪影」注记）

| 验收项 | 结果 |
|---|---|
| ① 护栏拦截 high_contrast | **触发 0**（it1/it2 sky_area=0.9958≥0.70 → 规则不在 rule_ids；ΔE=0 逐位） |
| ② 试水效果减半仍在 | day_normal ΔE 2.47→**1.36** / high_key 4.53→**3.00** / portrait 3.92→**1.80** / wide_angle 6.52→**4.84**（全系数→试水系数，量级约减半 ✓）；night_lowlight 持续零触发零漂移 |
| ③ portrait 溢出吞轮复认 | it1 overflow 11.1% → plant +0.047 被压 0.0（it2 状态落地值 0.0）；it2 溢出归零 → +0.033 正常落地（it3 状态）——**S-4 吞一轮自恢复复认**（落地值滞后决定一轮，按状态序列读） |
| e2e（真 DEFAULT_RULES） | `test_e2e_region_rule_participates_under_default_rules_package`：默认包下 region 规则进 rule_ids + region_adjust 落位 ✓ |

定向测试：`test_decide_region_wiring.py + test_tone_clarity_rules.py` → **40 passed**。

### 回放脚本基线伪影注记（重要，防后人误读）

首次回放 ΔE 全 0：**非渲染丢效果**——激活后 `DEFAULT_RULES` 已含 region_rules，
评估脚本的「A=DEFAULT_RULES 基线」与「B=+region」成为同一规则集（A 轨
region=True 实证）。已修脚本：A=DEFAULT_RULES **剔除** region_rules.yaml。
另：回放 A 轨 wide_angle 由 r13 首测的「FINAL_QC 二次超标」变为「达标」——
正是激活后 sky 压暗（-0.31 EV）在基线轨上的收益体现，与 B 轨实证互为印证。
纯区域效应复测（试水系数）：ΔE 1.48~2.05（.artifacts/region_rules_pure_effect.json）。
