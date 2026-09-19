# R24 · profile_curve 槽位域修复 + recipe v1

日期: 2026-09-19 ｜ 依据: `R23_baseline_neutralize.md` §5 两个深层问题
（§5.2 槽位是坏的 = 必须先查的缺陷；§5.1 缺基座影调曲线 recipe）

---

## 0. 结论速览

1. **域假设实证成立（判据先行，探针后改码）**：ProfileToneCurve 是 Adobe 管线里的
   **linear→linear 场景曲线**（施于输出编码之前），不是完整 linear→gamma 映射。
   同一中性链上 V6（EOTF∘curve 复合）对比 V1（曲线替代编码，旧行为）：
   **A 36.37→13.58 / B 37.37→14.69 / C_raw 38.42→17.11 / cc 0.89→0.97**（n=23 有效）。
   且 V6 比 V0 中性链（A 28.65）好一倍——复合 Adobe 曲线补上的正是 R23 §5.1
   所述"基座影调曲线缺口"的曲线形状部分。
2. **生产修复**：`_get_profile_lut` 返回**复合 LUT** `base∘curve`（16384 级预构，
   热路径仍单次 gather，native/ABI 不动）；缓存键升级 `(id(prof), eotf, gamma)`
   （旧单键在多 eotf 下会张冠李戴）。
3. **锚定同源**：`curve_anchor_target` 改复合语义（先基座解码得目标线性值、再反查
   曲线；新增 `srgb_decode`/`base_curve_decode`）；`exposure._auto_ev` 读 tone 层
   实际配置（`ctx.params_for("tone")`）——profile_curve 开才咨询曲线，eotf/gamma 同源。
4. **lrfit 静默回退可观测化**：标定缺失回退 sRGB 曲线基时记
   `record_degradation("render.tone_map.lrfit_calibration_missing")`（R23 探针
   V5==V0 之谜防复发）；悬空引用 `tools/fit_lr_tone_v2.py`（迁移中被删）找回改造为
   `tools/fit_tone_curve.py`。
5. **recipe 槽位接线**：`eotf="recipe"`（v3 同构 gains+共享曲线，目标=相机内嵌
   JPEG）；**默认链不动**（R23 中性纪律），标定文件按评估结论决定是否入包。

---

## 1. 探针实证（`.artifacts/_r24_compose_probe.py` → `_r24_compose_probe.json`）

V6 用 monkeypatch 复合 `base_lut(profile_lut(x))`（与生产修复同构），生产代码零改动：

| 变体 | A 整图 | B 16×16 | C_raw | C_al | cc | our_p05 | our_p995 | cam_p995 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| V0 中性(现默认) | 28.65 | 30.30 | 31.41 | 32.70 | 0.96 | 7 | 154 | 248 |
| V1 +profile_curve(旧行为) | 36.37 | 37.37 | 38.42 | 40.11 | **0.89** | 1 | 200 | 248 |
| **V6 复合(EOTF∘curve)** | **13.58** | **14.69** | **17.11** | **18.43** | **0.97** | 13 | 229 | 248 |
| V4 旧默认全链(对照) | 4.60 | 7.71 | 11.38 | 13.22 | 0.97 | 19 | 254 | 248 |

判据（计划 Part 1.1）: V6 显著优于 V1 ✓ 且 cc ≥ 0.90 ✓ ⇒ 假设成立，进生产修复。
V6 vs V4 差距 = 相机 auto-brightening 部分（R23 §5.1 已证），属 recipe/曝光锚定
责任，不属曲线域责任。

## 2. 代码改动清单

| 文件 | 改动 |
|---|---|
| `src/pixo/render/modules/tone_map.py` | `_get_profile_lut(prof, eotf, gamma)` 复合 base∘curve；缓存键 (id, eotf, gamma)；lrfit/recipe 分支合并 `_get_tone_fit(kind)`（两缓存分立保 monkeypatch 兼容）；标定缺失记降级；param_schema choices + recipe；docstring 改述（2026-08-16 A/B 证据链重注） |
| `src/pixo/render/core/curves.py` | 新增 `srgb_decode`/`base_curve_decode`；`curve_anchor_target(prof, eotf, gamma)` 复合语义；模块头更正（基座=曲线基，ProfileToneCurve 为复合槽位） |
| `src/pixo/render/modules/exposure.py` | `_auto_ev` 锚点读 `ctx.params_for("tone")` 与 tone 层实际配置同源；mode 文档更正（R23 后默认 baseline） |
| `src/pixo/render/tools/fit_tone_curve.py` | 新增（rawlab v4 工具 git a9c1ddf 找回改造）：中性渲染 srgb_decode 反解线性 → 相机 thumb 合并 CDF 曲线 + gains 网格搜索 + 留出集分布级评估 |
| `tests/unit/test_curves.py` | 翻转 `curve_anchor_target`×3 / `tone_stage_applies_profile_curve` 为复合断言；新增复合不变量（恒等曲线==曲线基、单调、白→白）+ 缓存键用例 |
| `tests/unit/test_exposure.py` | `test_anchor_midgray_maps_to_117` 翻转（power22 精确回 0.18 / srgb 精确解码） |
| `tests/unit/test_render_degradation.py` | 新增 lrfit 标定缺失 → 降级条目用例 |
| `tests/integration/test_render_perf_fixes.py` | 缓存测试适配新键结构 + 变体独立条目断言 |
| `.artifacts/_r24_compose_probe.py` / `_r24_two_tier_ref.py` | 本轮探针（假设实证 / 两分参照集） |

## 3. 受影响面（语义修复的预期后果）

- **默认链逐位零漂移**：profile_curve 默认 False、eotf 默认 srgb ⇒ 复合路径不进
  默认链。gate 金样本 21 features 零漂移实证（`tests/regression` 全绿含
  `test_gate_golden` run_check）。
- **7 张风格卡输出改变**（lr_baseline / lr_adobe_standard_baseline /
  lr_camera_standard_baseline / preview_baseline v1-v3 / acr_standard，
  均开 `profile_curve: true`）：Adobe look 从"替代编码"改为正确复合——暗部不再
  塌陷（V1 our_p05=1 → V6 13），白点回到 229（相机 248）。changelog 已注。
- **exposure auto 模式锚点**（非默认）：无曲线时 srgb 精确解码 0.1778 取代名义
  0.18（Δ0.017EV，亚 JND）；开 profile_curve 时锚点按复合曲线反查（自洽）。

## 4. 回归收口

- 全量（junitxml）: **1690+96 passed / 2 failed→1 failed 已修**（缓存测试适配）；
  唯一余留 `test_llm_shadow::test_shadow_threshold_configurable_flips_verdict`
  为 R23 §7 在册既有遗留（断言精度问题，非本轮）。
- 专项: test_curves / test_exposure / test_tone_sixkey / test_user_curve /
  test_render_degradation / test_render_perf_fixes / test_gate_curves /
  test_gate_golden 全绿。

## 5. recipe v1（两分参照集 + 拟合）

### 5.1 拟合（`tools/fit_tone_curve.py`，4053 张语料采样 120 = train 84 / holdout 36）

方法：中性链渲染 srgb_decode 精确反解线性 → 相机 thumb 合并亮度 CDF 匹配出共享
曲线 → gains 联合网格搜索（判据 a*/b* 中位 + HSV S 均值，v4 同款）。
量纲教训：thumb 为 u8 须先 /255（漏归一会把曲线拟成恒 1 全白，首轮实跑踩过）。

| 集 | A_med | A_p90 | dL_med | 白点 p995 |
|---|---:|---:|---:|---:|
| train (84) | 4.08 | 7.72 | -0.76 | 232.5 |
| **holdout (36)** | **4.33** | 6.68 | -0.82 | 233.5 |

train/holdout 差 0.25 无过拟合；gains R=0.900 G=1.000 B=1.000。

### 5.2 两分参照集探针（`_r24_two_tier_ref.py`，n=24 真机）

**Tier 1 引擎准度**（中性参照 = libraw 线性：相机 WB / 关自动亮度 / gamma=1）：
ev_med median **-0.66EV**、p90 -0.58EV（跨片散布 ~±0.08EV）——系统性**尺度差**
（解码归一/wb 乘子口径），非逐片失准；逐片一致性才是该层读数。
（R23 §5.1 单张口径 med -0.44EV 同向同级。）

**Tier 2 recipe 匹配度**（相机 JPEG 参照，median ΔE76）：

| 变体 | A | B | C_raw | cc | our_p995 |
|---|---:|---:|---:|---:|---:|
| V0 中性（默认链） | 28.65 | 30.30 | 31.41 | 0.96 | 154 |
| V6 复合（R24 生产 profile_curve） | 13.58 | 14.69 | 17.11 | 0.97 | 229 |
| **VR eotf=recipe（生产管线端到端）** | **3.59** | **6.75** | **10.93** | **0.98** | 239 |

VR **超过旧默认全链**（R23 实测 V4: A 4.60——靠 auto 测光 +2.5EV + warmth + clarity
+ skin + refine 堆出来的）而 recipe 仅"一条曲线 + 三个增益"，且默认链保持中性。
白点 239 ≈ 相机 239/248。**达标 ⇒ 标定入包** `src/pixo/render/recipe_tone_curve.json`
（pyproject package-data 同步），默认 eotf 仍 srgb（用不用由风格卡/调用方决定）。

附带修复（实跑暴露）：fit 分支逐通道 2D 调 `_apply_lut` 触发 native (H,W,3) 断言的
降级回退（旧 lrfit 分支同形代码、以前从未真跑过）——改整图单次调用，降级清零。

## 6. 待队长复核

- recipe 标定已按评估结论入包（§5.2 达标）；如不认可可删
  `src/pixo/render/recipe_tone_curve.json` + pyproject 两行，槽位退化为
  可观测回退（有降级条目），代码不依赖文件存在。
- 7 张风格卡输出变化接受与否（语义修复预期后果，见 §3）。
- F01 旧参照集（exports/auto/color_check/）建议归档标记 superseded，
  由 `_r24_two_tier_ref.py` 口径接管（本轮未动旧目录）。
