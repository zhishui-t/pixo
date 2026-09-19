# R23 · 引擎基线中性化: 打开 RAW = LR 打开 DNG 的中性态

日期: 2026-09-14 ｜ 依据: `engine_responsibility_boundary.md`（引擎只提供能力，不负责使用能力）

---

## 0. 结论速览

1. **6 处越权默认全部清理**: 打开 RAW 时引擎现在只做 3 件基线事 ——
   解码 / as-shot 白平衡 + DCP 色矩阵 / 输出编码 (linear→gamma)。
   不再自动测光、不再自动加暖、不再自动提亮、不再自动加清晰度、不再自动磨皮、不再自动锐化降噪。
2. **配置侧 34 个文件的隐式继承被显式化**（+35 行，diff 每文件 1 行）。
3. **单元测试 18 → 1**（残留 1 项为既有精度断言问题，与本次无关）。
4. ⚠️ **回归暴露两个更深的问题**（不是改动引入的，是改动**揭示**的）:
   - 中性链与相机 JPEG 的差距 **不是"引擎不准"**，而是**缺一条基座影调曲线（recipe）**；
   - `tone.profile_curve` 这个本该承担该曲线的槽位**本身是坏的**。

---

## 1. 引擎改动清单

| 文件 | 项 | 改前 | 改后 | 定性 |
|---|---|---|---|---|
| `pipeline/graph.py:53` | 基类 `wants()` | `return True` | `return False` | **根因**：不覆盖即无条件执行 |
| `modules/exposure.py` | `mode` | `"auto"`（每张自测光） | `"baseline"`（仅 DCP BaselineExposureOffset） | 编辑动作 → 基线 |
| `modules/exposure.py` | `subject_mode` | `"box"`（生产无框注入，静默回退） | `"full"` | 消死门控 |
| `modules/exposure.py` | 新增 `wants()` | 继承 `True` | `mode != "off"` | 显式声明 |
| `modules/white_balance.py` | `warmth` | `0.9`（"对齐 LR"的观感增益） | `0.0` | 编辑动作 → 归零 |
| `modules/white_balance.py` | 新增 `wants()` | 继承 `True` | **恒 `True`** | 它兼负 `linear_cam→linear_rgb` **域转换** |
| `modules/tone_map.py` | `brightness` | `0.25`（补相机偏暗的补丁） | `0.0` | 编辑动作 → 归零 |
| `modules/tone_map.py` | `contrast` / `shoulder` | `0.12` / `0.35` | `0.0` | 只在 `use_filmic` 分支消费的**死参数** |
| `modules/tone_map.py` | 新增 `wants()` | 继承 `True` | **恒 `True`** | 它是 `linear→gamma` **输出编码**（域转换） |
| `modules/reshape.py:71` | `clarity.enabled` | `True`(0.3) | `False` | 编辑动作 → 关（能力位保留） |
| `modules/skin.py:80` | `skin.enabled` | `True`(0.5) | `False` | 编辑动作 → 关（能力位保留） |
| `modules/refine.py:181` | **新增 `enabled` 键** | 无该键（`{"refine":{"enabled":false}}` 不生效） | `False` + 新增 `wants()` | 修配置陷阱 |
| `modules/compose.py` | 新增 `wants()` | 继承 `True` | 仅在显式请求构图时 | 显式声明 |
| `modules/color_cal.py` | 新增 `wants()` | 继承 `True`（连带触发**每机 CCT 中性轴自动标定**） | 仅显式请求时 | 自动定参数 → 关 |
| `modules/skin.py:24` | 过期注释 | "默认管线不包含本 Stage" | 改为"在链上但默认关" | 修文档 |

**新的默认链实际执行步**（`wants` 判定实测）:

```
exposure ✓(baseline)  whitebalance ✓(域转换)  tone ✓(输出编码)
compose ✗  huesat ✗  dehaze ✗  clarity ✗  colorcal ✗  calibration ✗
hsl ✗  split_tone ✗  skin ✗  region_adjust ✗  stylize ✗  refine ✗
```

---

## 2. 配置侧配套（34 文件 / +35 行）

**问题**: 会话路径 `render/web/session.py:522` 用 `build_default_pipeline`（全 15 stage），
所以配置里写的不论 `stages` 列不列，`refine`/`skin`/`clarity` 的块都会生效。
这些配方此前是"写了强度、没写 enabled"，靠**引擎默认 enabled=True** 才跑起来 —— 引擎一改就静默失效。

**规则**（只补最小信息、不动任何数值）:

- 块内**有**实质参数（sharpen / color_domain …）但无 `enabled` ⇒ 作者意图要用 ⇒ 补 `"enabled": true`
- 空块 `{}` ⇒ "无意见" ⇒ 保持默认关（`neutral.json` / `acr_standard.json` 属此类，**故意不补**）

结果: 34 文件 / 35 处，`git diff --stat` = `34 files changed, 35 insertions(+), 3 deletions(-)`。
脚本 `.artifacts/_neutralize_configs.py`（文本级插入，非 JSON 重序列化，保证每文件 diff 仅 1 行；含合法性自检）。

---

## 3. 实测归因: 每个越权动作改了多少像素

`.artifacts/_baseline_neutralize_ab.py`（n=8，中性链 − 旧默认链，Lab u8 尺度）

| 变体 | Δpix% | dL | da | db |
|---|---:|---:|---:|---:|
| **曝光自动测光** | 100.00 | **−46.06** | −0.39 | −0.40 |
| 暖度 +0.9 | 99.01 | +0.25 | **−2.36** | −0.99 |
| 提亮 +0.25EV | 99.92 | **−4.96** | +0.02 | −0.08 |
| 清晰度 0.3 | 93.87 | −0.02 | +0.01 | −0.02 |
| 磨皮 | 91.29 | +0.06 | +0.03 | +0.07 |
| 锐化+降噪+去饱和 | 42.61 | −0.01 | +0.03 | +0.01 |
| **全部旧默认合计** | 100.00 | **−52.78** | −2.38 | −2.11 |

**读法**: 曝光自动测光一个人贡献了 dL −46（旧链比中性链亮 46/255 ≈ 18% 亮度），是最大头；
三个纹理类算子改动 42%–94% 的像素，但 Lab 均值几乎为 0 —— 再次确认它们**落在色准尺子的盲区**。

---

## 4. 回归结果

### 4.1 单元测试

| | 失败数 |
|---|---:|
| 改动前 | 0（基线） |
| 改动后首轮 | 18 |
| 修复后 | **1** |

18 项逐条定性:

- **真 bug（本次引入，已修）**: `white_balance.wants()` 初版按 `mode!="off"` 判定 ⇒
  `mode="off"` 时跳过 ⇒ 链停在 `linear_cam` ⇒ `tone` 报"域不匹配"。
  **`white_balance` 兼负 `linear_cam→linear_rgb` 域转换，必须恒跑**（已改为 `return True`）。
  同一处修复连带转绿 `test_huesat_domain`(3) / `test_native_fallback`(1) / `test_region_masks_channel`(2)。
- **断言旧默认（已更新为新契约）**: `test_skin`(enabled True→False)、
  `test_wb_temp_tint`(6 项: warmth 0.9→0.0；暖度机制用例改为**显式**声明 `warmth: 0.9`)、
  `test_exposure::test_max_ev_clamp`(显式 `mode="auto"`)、
  `test_pipeline`(2 项: 假 Stage 补 `wants`；probe 落盘清单改为 `01_whitebalance / 02_tone`)。
- **既有问题（与本次无关，未动）**: `test_llm_shadow::test_shadow_threshold_configurable_flips_verdict`——
  `src/pixo/pipeline/loop.py:1355` 把分数 `round(x, 6)`，测试却拿 `0.5*abs(current)` 比，
  差 5e-7 > 默认容差 1.6e-7。**纯断言精度问题，属 decide/loop 域**。

### 4.2 F01 三口径（vs 相机内嵌 JPEG）

| 口径 | 旧默认链 (n=798) | **新中性链 (n=79)** | 探针 V4 旧链 (n=24) | 探针 V0 中性 (n=24) |
|---|---:|---:|---:|---:|
| A 整图系统色偏 | 5.02 | **27.65** | 4.60 | 28.65 |
| B 16×16 分块 | 8.26 | **29.34** | 7.71 | 30.30 |
| C_raw 逐像素 | 12.55 | **30.73** | 11.38 | 31.41 |
| cc 对齐 | 0.975 | 0.959 | 0.97 | 0.96 |

端点: 白点 p99.5 由 **252 → 139**（相机 239）。

⚠️ **这个数字不能读成"引擎变差了"** —— 见 §5.1。

---

## 5. 回归暴露的两个深层问题

### 5.1 中性链的差距 = 缺 recipe，不是引擎不准

**对照实验**（同一张 DSC_5236.NEF，libraw 自带渲染）:

| 渲染 | 中位 | p99.5 | max |
|---|---:|---:|---:|
| 我们 (中性链输出的线性域) | 0.0131 | 0.2247 | 0.5086 |
| libraw 线性（相机 WB，**关闭**自动亮度） | 0.0178 | 0.2857 | 0.5658 |
| libraw 默认渲染（**开**自动亮度 + gamma 2.4） | 80/255 | 255 | 255 |
| 相机内嵌 JPEG | — | 239 | — |

- 我们的线性解码与 libraw 的线性解码**基本一致**（p99.5 差 0.35 EV，max 差 0.15 EV）
  ⇒ **没有"解码偏暗"的 bug**。
- 相机 JPEG 之所以亮，是因为相机管线自带 **auto-brightening + Picture Control 曲线**；
  libraw 一开 `auto_bright` 同样跳到 p99.5=255。
- 旧链的 `exposure mode="auto"` 在做的，正是这件事（把中位拉到锚点，实测约 +2.5 EV，
  撞 `max_ev` 上限）—— 所以它**不只是越权，还在替相机管线打工**。

**结论（与既有记忆一致，现在有了直接证据）**: 参照必须一分为二 ——

- **引擎准度** = 中性实现 vs 另一中性实现/物理真值 ⇒ 现在这一口径**是好的**；
- **recipe 匹配度** = recipe 输出 vs 相机 JPEG ⇒ 差多少，取决于 recipe 做多少。
  **`A 27.65` 量的是这个缺口的大小，不是引擎的误差。**

⇒ F01 尺子的参照集（`exports/auto/color_check/` 里 md5 相同的那批）**必须重造**：
  引擎准度需要"中性参照"，recipe 匹配度才用相机 JPEG。

### 5.2 `tone.profile_curve` 槽位是坏的

同一条中性链上只改 tone 的开关（n=24）:

| 变体 | A | B | C_raw | C_al | cc |
|---|---:|---:|---:|---:|---:|
| V0 中性（现默认） | 28.65 | 30.30 | 31.41 | 32.70 | 0.96 |
| **V1 +profile_curve=True** | **36.37** | 37.37 | 38.42 | 40.11 | **0.89** |
| V2 +brightness=0.25 | 26.44 | 27.99 | 29.05 | 30.10 | 0.96 |
| V3 profile_curve + bri .25 | 32.36 | 33.30 | 35.00 | 36.02 | 0.90 |
| V4 旧默认全链 | 4.60 | 7.71 | 11.38 | 13.22 | 0.97 |
| V5 profile_curve=True + eotf=lrfit | 28.65 | 30.30 | 31.41 | 32.70 | 0.96 |

两点:

1. **打开槽位反而更差**（A 28.65→36.37），且 **cc 由 0.96 掉到 0.89 才 0.01 就破 0.90 门** ⇒
   不是"少了一点"的程度，是**逐像素结构都对不上**了。这是必须先查的缺陷，不是可选项。
   候选（待验）: `_get_profile_lut()` 把 DCP `ProfileToneCurve` 当**完整的 linear→gamma 映射**
   替代 `_get_base_lut`，而 Adobe 管线里该曲线是 **linear→linear**，之后再走 EOTF。
2. **V5 与 V0 逐位相同** ⇒ `eotf="lrfit"` 分支的标定文件缺失，
   `_get_lrfit()` 返回 None 直接回退曲线基。印证既有记录 "`tone` 的 `lr_tone_curve.json` **缺失**"。

⇒ F03（去灰 / 基座曲线）的**前置任务**就是这条：修 `profile_curve` 的施加域与曲线源。

---

## 6. 能力清单核对（用户口径）

| 能力 | 状态 |
|---|---|
| 曝光 | ✅ `exposure`（`mode` = 数值 / `"auto"` / `"baseline"` / `"off"`） |
| 白平衡 | ✅ `white_balance`（`mode="manual"` + temp/tint） |
| HSL | ✅ `hsl` |
| 分离色调 | ✅ `split_tone` |
| 曲线 | ✅ `tone.user_curve`（rgb/red/green/blue/luminance） |
| 蒙版 | ✅ `region_adjust`（M1 级） |
| **直方图** | ❌ **无独立 API**（全库只有 `vision/geometry.py`、`tone_map.py` 提及；R23 F02 待建） |

---

## 7. 回归收口（2026-09-14 完成）

**全量结果**：`tests/unit + tests/regression + tests/integration` = **1697 项**（用 `--junitxml` 取结构化结果，
因 pytest 的文本汇总段在本机被临时目录清理打断）：

| 范围 | 用例 | 失败 | 跳过 |
|---|---:|---:|---:|
| `tests/unit` | 1460 | **1** | 4 |
| `tests/regression` + `tests/integration` | 237 | **0** | 3 |

**唯一可复现失败 = 既有遗留、与 R23/F09 均无关**：

| 失败项 | 归属 | 成因 |
|---|---|---|
| `tests/unit/test_llm_shadow.py::test_shadow_threshold_configurable_flips_verdict` | 既有 | `pipeline/loop.py:1355` 把分数 `round(x,6)`，测试拿 `0.5*abs(current)` 比，差 5e-7 > 默认容差 1.6e-7（纯断言精度） |

另：`tests/integration/test_segmenter_warmup.py::test_warmup_absorbs_cold_start_and_nonblocking`
在一次全量跑中因 `huggingface.co` 网络 `[SSL: UNEXPECTED_EOF_WHILE_READING]` 失败，
**隔离复跑通过** ⇒ 判定为**网络 flaky**，非真实缺陷。

跳过 3 项均为需真 RAW 的 gate 用例（`test_gate_auto_loop_e2e` /
`test_gate_e2e_ab` / `test_gate_e2e_perf`），unit 侧 4 项跳过为既有条件跳过。

### 7.1 本轮自身引发的 5 项失败已全部修完

| 失败项 | 归属 | 修法 |
|---|---|---|
| `test_gate_golden` 2 项（3 feature 漂移） | **R23**（预期） | 重生成金样本（见 §7.2） |
| `test_gate_compose` 3 项 | R22 F09 漏改 | `_run_compose` 统一 `params.setdefault("coord","px")` |
| `test_loop_e2e::test_single_photo_loop_…` | R22 F09 漏改 | compose_params 补 `"coord":"px"` |
| `test_loop_e2e::test_qc_overflow_…` | **R23**（副产品） | 改用例自带增益 `_OVERFLOW_PARAMS={"tone":{"brightness":0.5}}`（0.92×2^0.5≈1.30），**与引擎默认值解耦** |

> F09 三项的归属证据：`design-r22.md` §2.4 已列出同步面
> `test_gate_compose.py:81/92/118/135/149`、`test_loop_e2e.py:69` —— **代码改了、测试没跟着改**
> （R22 全未提交）。`compose.py:71` 的 warn-once 告警在失败日志里如实打出。

### 7.2 金样本重生成（R23 批次）

- **3/21 变化**：`default_dispatch`（契约即「观测缺省翻转」，预期）、
  `card_portra_400` + `region_adjust`（走 `build_default_pipeline` 全默认链，随 tone/exposure/WB 连带）；
- **其余 18 逐位不变**（逐个 `.npy` `cmp` 实证）；manifest 改动面精确 = 3 处 `sha256` + `reviewer` 一行。
- 旧基线备份 `.artifacts/gate_goldens_backup_r23/`（22 文件）。
- ⚠️ 生成器 `build_manifest()` 把 `reviewer` **硬写 `"pending"`**，会覆盖历史批次史 ⇒
  已用 `.artifacts/_r23_manifest_reviewer.py` 从备份取回历史再追加 R23 批次记录（**待队长复核签字**）。

## 8. R22 F09 归一化收口（队长裁决后执行）

> 裁决：① 掩码线缺陷 → **「修（含翻转用例）」**；② `compose.coord` 缺省 → **「保持 `norm`（F09 原设计）」**。
> 全文独立记录 `.artifacts/r22_f09_coord_completion.md`。

### 8.1 掩码预测线未透传 `coord`（已修）
`region_masks._post_compose_shape` 调 `compute_crop_rect` **不传 `coord`** ⇒ 落纯函数缺省 `"px"`，
而渲染线是 `"norm"` ⇒ **静默分叉**。F09 §2.3 原文要求透传，**未做**。
→ 已补 `coord=str(cp.get("coord","norm") or "norm")`。

### 8.2 `adopt_crop` 写回 px 但不声明 `coord` ⇒ 采纳后输出 1×1（新发现，已修）
`loop.py` adopt_crop 段经 `rect_norm_to_px` 转"全幅像素"写回、**不设 `coord`** ⇒ 被按相对值解释。
**探针实测**（源 64×64、建议 `[0.1,0.1,0.9,0.9]`）：修复前 `final_image.shape=(1,1,3)` → 修复后 `(51,51,3)`。
→ 已改为直接落 `norm` 四元组 + 显式 `"coord":"norm"`（`crop_suggestion["rect"]` 本就是归一化值）。
**盲区已补**：`test_e2e_crop_adoption_drops_region_masks` 原只断言 `mode=="free"`，现补几何断言。

### 8.3 测试同步（F09 §2.4/§3 已列但未执行）
`test_gate_compose.py`（3 项）、`test_loop_e2e.py:69`、`test_crop_wiring.py`（2 项硬断言）、
`test_region_masks_channel.py`（**F09 标注的「有意翻转」用例**，已按 docstring 契约翻转为
「两 tier 相对裁剪窗一致」+ 保留 px 判别力对照）。
统一口径：**legacy px 调用方须显式声明 `coord="px"`**；采纳/写回线一律落 `norm`。

### 8.4 `compose.coord` 缺省保持 `"norm"`（队长裁定）
纯函数缺省仍 `"px"`（公开 API 不变）；仓内持久化 px 矩形 ≈ 0 处（F09 侦察 P5）。
⇒ 仓外调用方若传 px 矩形且不声明 `coord`，取景会变；`compose.py:71` warn-once 兜底。

**验证**：`test_crop_wiring` + `test_decide_region_wiring` + `test_region_masks_channel` +
`test_compose_autolevel` + `test_gate_compose` + `test_loop_e2e` = **82 passed**。

## 9. 遗留 / 下一步

1. **F03 前置**: 修 `tone.profile_curve` 的施加域与曲线源（§5.2 证据）。
2. **F01 参照集重造**: "引擎准度"需中性参照，"recipe 匹配度"才用相机 JPEG（§5.1）。
3. **相机 recipe 落地形态**: 把"像相机预览"做成 `configs/recipes/*.json`
   （基座影调曲线 + WB trim + 暖度），**数据而非代码常量**；
   `tone.user_curve` + `curve_lut_from_points` 已具备载体。
4. **既有遗留**: `loop.py:1355` 的 `round(x,6)` 与测试自算值不一致（§7 表）。

## 8. 产物

- 探针: `_baseline_neutralize_ab.py` / `_f01_tone_slot_probe.py` / `_neutralize_configs.py` / `_patch_wb_tests.py`
- 数据: `_baseline_neutralize_ab.json` / `_f01_tone_slot_probe.json` / `f01_batch_summary.md`
- 日志: `_f01_neutral.log` / `_unit_v2.log` / `_integ_v.log`
- 旧基线备份: `oldschool_f01_batch_*`
