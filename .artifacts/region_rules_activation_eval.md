# region 规则激活评估（R13）—— region_sky_exposure_001 / plant_exposure_002 真实语料实测

> 2026-09-07 · dev-1 · M1「管道通水 → 阀门打开」证据件。
> 零生产代码改动；评估脚本 `.artifacts/_r13_region_rules_eval.py`
> （双轨闭环）+ `.artifacts/_r13_region_pure_effect.py`（纯区域效应归一）。
> 机读：`.artifacts/region_rules_activation_eval.json` / `region_rules_pure_effect.json`。

## 1. 评估设置

- 语料：RAW 金样本 6 张（`D:/tmp/pixo_t108/samples.json`：night_lowlight /
  day_normal / high_key_bright / portrait_tele / wide_angle / high_contrast）。
- 真分割栈：`MultiModelSegmenter`（路由 rfdetr+segformer；uniface/sapiens NC
  门控自动缺席——sky/plant 走 segformer **无需** `PIXO_ALLOW_RESTRICTED=1`；
  segformer 权重本机缓存命中）。
- 链路：`SinglePhotoLoop(prof=load_dcp(DCP), prompts=["sky","plant"],
  manual_on_unreliable=False)`，`masks_cache → region_masks`（F13 通道）→
  region_adjust 执行位；A 轨 = DEFAULT_RULES（5 文件 9 规则），B 轨 = A +
  region_rules.yaml（2 规则）；max_iterations=3, preview 512。
- 口径注记：`manual_on_unreliable=True`（生产默认）下 4/6 样本因请求区域
  真实缺失（area=0 → unreliable）在 it1 即 manual_review（保守契约）；
  评估置 False 以便观测，region 规则自身 S-5 reliable 闸不受影响。

## 2. 触发率与参数量级

| 样本 | sky 规则 | plant 规则 | sky_lum (it1) | plant_lum (it1) | region.exposure 实际写值 |
|---|---|---|---:|---:|---|
| night_lowlight | 否（夜空 lum<150，**正判**） | 否 | — | — | 无（A=B 逐位，ΔE=0） |
| day_normal | **是**（250.7） | 否 | 250.7 | — | -0.836 → -0.643 → -0.683 EV |
| high_key_bright | **是**（170.2） | 否 | 170.2 | — | -0.568 EV |
| portrait_tele | **是**（175.1） | **是**（61.8） | 175.1 | 61.8 | sky -0.584 / plant +0.066 |
| wide_angle | **是**（213.0） | 否 | 213.0 | — | -0.710 → -0.547 EV |
| high_contrast | **是**（155.7）——**99.6% 覆盖，见 §4 误伤** | 否 | 155.7 | — | -0.519 EV |

- **触发率：sky 5/6（83%）**，唯一不触发 = 夜景（条件语义正判，零误触发）；
  **plant 1/6**（暗部植被仅在 portrait_tele 检出）。
- 参数量级：sky 写值 **-0.52 ~ -0.84 EV**（clamp [-2,0] 未触顶）；
  plant **+0.047 ~ +0.066 EV**（clamp [0,2] 未触顶）。
- 收敛性：mode=set 每轮按当前亮度重写，实测温和震荡（day_normal
  -0.836→-0.643→-0.683 随 lum 250.7→193→204.8 波动），确定性不累积 ✓。

## 3. 渲染效果

### 3.1 全闭环效应（A 轨 vs B 轨终图，含全局规则链耦合）

| 样本 | ΔE76 mean | p95 | 变化像素 | 终局差异 |
|---|---:|---:|---:|---|
| night_lowlight | 0.0 | 0.0 | 0% | 双轨同为 FINAL_QC 二次超标（区域规则未参与） |
| day_normal | 2.470 | 10.71 | 24.5% | 双轨均二次超标（天空压暗不足以救回） |
| high_key_bright | 4.529 | 8.66 | 96.6% | 双轨均达标跑满 |
| portrait_tele | 3.920 | 9.29 | 52.2% | 双轨均二次超标 |
| wide_angle | 6.521 | 11.13 | 98.9% | **A 二次超标转人工 ↔ B 达标跑满——天空压暗救回 FINAL_QC** |
| high_contrast | 8.097 | 8.29 | 99.7% | 双轨均达标 |

注意：ΔE 为**全闭环轨迹效应**——天空压暗改变全局亮度/溢出 → 全局规则链
（saturation_high/dehaze/highlight_protect…）连锁分叉，非纯区域作用。

### 3.2 纯区域效应（同终态参数，唯一变量 region_adjust 执行位，归一渲染）

| 样本 | region 参数 | 掩码覆盖 | ΔE76 mean | p95 | 变化像素 |
|---|---|---|---:|---:|---:|
| portrait_tele | sky -0.584 / plant +0.059 | sky 40.6% / plant 6.9% | 3.149 | 9.219 | 49.0% |
| wide_angle | sky -0.575 | sky 42.1% / plant 3.7% | 3.780 | 9.175 | 43.1% |
| high_contrast | sky -0.519 | **sky 99.6%** | 7.797 | 8.153 | **99.7%** |

人评口径描述：effect = 天空/植被掩码区整体 ±0.5 EV 级别的曝光重塑
（天空可感知压暗、暗部植被轻微提亮），非局部斑点修补——**区域规则的
作用语义是「大面积分区曝光」，效果与覆盖面积成正比**。

## 4. 误伤面检查

1. **极端覆盖=全画面误伤（实锤，最高优先）**：high_contrast 被 segformer
   判定 **99.6% sky** → 规则把**全画面**压暗 0.52 EV（ΔE7.80，99.7% 像素）。
   与 R11 skin 90% 覆盖同族：**区域语义在极端覆盖下失效**（一张照片 99.6%
   是天空=构图已无意义，压暗=全图曝光偏移）。条件全过（lum 155.7>150、
   reliable=true——面积越大越可靠，S-5 闸反向放行）。
2. **人像背景压暗（语义灰区）**：portrait_tele 天空掩码 40.6%（tele 人像的
   虚化背景被归类 sky）→ 规则把人像背景压暗 0.58 EV。艺术上或可接受
   （背景压暗是常见人像手法），但这是**规则替用户做的创作决定**，需产品侧
   认可；plant +0.066 EV 亚 JND 无感。
3. **S-4 限流器交互（F14 遗留，实测复现）**：portrait_tele it1 overflow
   11.1%（≥2.5%）→ plant 正向提亮 +0.047 被压回 **0.0**（`engine.py:738`
   `"exposure" in "region.plant.exposure"` 子串命中）；it2 溢出归零后
   +0.066 正常落地——**自恢复但吞一轮**。sky 负向不受限流影响。
   引擎豁免（region.* 前缀排除）仍是待决项，但实测压制为暂时性且方向保守。
4. **无误触**：night_lowlight 零触发（夜空 <150）；day_normal 天空 lum
   250.7 触发 -0.84 EV 属条件语义内的正确压暗（大晴天过曝天空）。

## 5. 入包建议：**b+) 条件入包——先加覆盖率护栏（YAML 零代码），再降量试水**

- **a) 直接入 DEFAULT_RULES：否**。high_contrast 99.6% 覆盖全画面压暗是
  实测误伤，裸入包会把该样本类（大面积天空构图）整体压暗。
- **c) 暂缓：过保守**。wide_angle 实证正向价值（救回 FINAL_QC 人工复核），
  night 零误触，S-5/S-4 防线按设计工作。
- **建议动作（按序）**：
  1. **规则 condition 补覆盖率护栏（零代码）**：`sky_area_ratio lt 0.70` /
     `plant_area_ratio lt 0.70`（键已在宇宙注册）。实证回放：high_contrast
     （99.6%）被拦、portrait_tele（40.6%）/wide_angle（42.1%）不受影响。
     阈值依据同 R11 skin cap：合法区域覆盖与「整图误罩」之间存在实测间隙。
  2. **试水参数**：公式系数减半（sky -0.5→-0.25、plant 0.4→0.2）或 clamp
     收紧至 [-1.0, 0]/[0, 1.0]，观察窗后按数据复权。
  3. **S-4 引擎豁免**（region.* 前缀排除出溢出限流）：plant 实测吞一轮但
     自恢复，非阻断；随护栏试水一并观察，若连拍/高溢出场景频繁吞首亮则立项。
  4. 重跑本评估脚本验证护栏后的触发面（预期：high_contrast 转零触发，
     其余不变）。

## 6. 复现

```
python .artifacts/_r13_region_rules_eval.py          # 双轨闭环 6 样本 (~6min)
python .artifacts/_r13_region_pure_effect.py         # 纯区域效应归一 (~2min)
```
B 轨终图存 `.artifacts/r13_region_eval/{sample}_A.png|_B.png`（人评素材）。
依赖：segformer 权重 HF 缓存在机；RAW 本机路径同 F11。
