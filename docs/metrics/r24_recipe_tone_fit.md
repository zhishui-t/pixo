# R24 · 基座影调曲线（recipe）拟合与两分参照集

日期：2026-09-19 ｜ 工具：`src/pixo/render/tools/fit_tone_curve.py` ｜
探针：`.artifacts/_r24_two_tier_ref.py`、`.artifacts/_r24_compose_probe.py`
｜ 轮报：`.artifacts/R24_profile_curve_compose.md`

## 背景（R23 §5 两个深层问题）

1. `tone.profile_curve` 槽位把 DCP ProfileToneCurve 当完整 linear→gamma 替代基座
   EOTF；实际它是 Adobe 管线 **linear→linear 场景曲线**（施于输出编码前）。
2. 中性链 vs 相机 JPEG 的差距（A=27.65）量的是 **recipe 缺口**而非引擎误差——
   F01 参照必须两分：引擎准度用中性参照，recipe 匹配才用相机 JPEG。

## 域假设实证（改码前，n=24 真机）

| 变体 | A | B | C_raw | cc | our_p995 |
|---|---:|---:|---:|---:|---:|
| V0 中性（默认） | 28.65 | 30.30 | 31.41 | 0.96 | 154 |
| V1 曲线替代编码（旧行为） | 36.37 | 37.37 | 38.42 | **0.89** | 200 |
| V6 复合 EOTF∘curve | **13.58** | **14.69** | **17.11** | **0.97** | 229 |
| V4 旧默认全链（对照） | 4.60 | 7.71 | 11.38 | 0.97 | 254 |

⇒ 假设成立（V6 判定性优于 V1 且 cc 过 0.90 门），生产修复落地：
`_get_profile_lut` 返回复合 LUT `base∘curve`；缓存键 `(id(prof), eotf, gamma)`；
曝光锚定 `curve_anchor_target` 同步复合语义并经 `ctx.params_for("tone")` 与
tone 层配置同源。默认链逐位零漂移（gate 21 features 实证）；
7 张风格卡（lr_*/preview_*/acr_standard）输出变化为语义修复预期后果。

## recipe 拟合（4053 张语料采样 120 = train 84 / holdout 36）

方法：中性链渲染 srgb_decode 精确反解线性（tone 前全线性）→ 相机内嵌 JPEG
（rawpy.extract_thumb）合并亮度 CDF 匹配共享曲线 → 逐通道 gains 联合网格搜索
（判据 Lab a*/b* 中位 + HSV S 均值；承 rawlab v4 工具方法论，v1 逐通道曲线
烘焙 WB 的教训已吸收——共享曲线保中性）。

| 集 | A_med (ΔE76) | A_p90 | dL_med | 白点 p995 |
|---|---:|---:|---:|---:|
| train (84) | 4.08 | 7.72 | -0.76 | 232.5 |
| **holdout (36)** | **4.33** | 6.68 | -0.82 | 233.5 |

无过拟合（train/holdout 差 0.25）；gains = [0.900, 1.000, 1.000]。
达标 ⇒ 标定入包 `src/pixo/render/recipe_tone_curve.json`，`eotf="recipe"`
接入（默认链不动）。

## 两分参照集口径（F01 尺子新基线）

- **Tier 1 引擎准度**：中性链线性 vs libraw 线性（相机 WB / no_auto_bright /
  gamma=1）。n=24：ev_med median **-0.66EV**、p90 -0.58EV。
  **R25 根因定案**（`.artifacts/_r25_tier1_probe.py`，n=24 两臂实证）：该尺度差
  = 当前 DCP **BaselineExposureOffset（-0.6228EV）**——中性链
  `exposure mode="baseline"`（R23 "打开 RAW = LR 打开 DNG" 语义）把它乘进输出，
  而 libraw 参照不乘。**扣除该 offset 后残差 ev_med median -0.024EV / p90
  +0.06EV（色彩矩阵/去马赛克级）⇒ 引擎解码准度没有问题**。
  Tier-1 口径自此修正为**扣除基线曝光后对比**（引擎纯解码 vs libraw 纯解码）。
- **Tier 2 recipe 匹配**：生产管线端到端 vs 相机 JPEG：

| 变体 | A | B | C_raw | cc | our_p995 |
|---|---:|---:|---:|---:|---:|
| V0 中性（默认链） | 28.65 | 30.30 | 31.41 | 0.96 | 154 |
| V6 复合 profile_curve | 13.58 | 14.69 | 17.11 | 0.97 | 229 |
| **VR eotf=recipe** | **3.59** | **6.75** | **10.93** | **0.98** | **239** |

VR 超过旧默认全链（4.60，靠 auto 测光 +2.5EV + warmth + clarity + skin + refine），
白点 239 ≈ 相机。R23 §5.1 的 recipe 缺口以"一条曲线 + 三个增益"清偿，
且不回退 R23 中性化成果。

## 附带修复

- lrfit/recipe 标定缺失回退从静默改 `record_degradation`
  （`render.tone_map.{lrfit,recipe}_calibration_missing`）。
- fit 分支逐通道 2D `_apply_lut` 触发 native 降级回退 → 整图单次调用（降级清零）。
- 悬空引用 `tools/fit_lr_tone_v2.py`（迁移中被删）→ 找回改造为
  `render/tools/fit_tone_curve.py`。

## 复跑

```bash
python src/pixo/render/tools/fit_tone_curve.py --n 120          # 拟合（~4 分钟）
python .artifacts/_r24_two_tier_ref.py --n 24                   # 两分参照集
python .artifacts/_r24_compose_probe.py --n 24                  # 域假设复验
```

语料：`K:/data/photo`（4053 张 NEF，剔除 AppleDouble；已知 LibRaw 坏文件
自动跳过）。DCP：Nikon Z 5 2 RawLab LR Adobe Standard Baseline。
