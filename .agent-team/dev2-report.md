workbuddy_session_id: wbdy-050cdcf1-514

# R31 · dev-2 报告（F3 三臂测量 + F4 矫正裁决执行）

- 角色：dev-2（F3 测量 / F4 矫正）
- 日期：2026-09-22
- 依据：`.agent-team/design.md` **v2.1**（唯一真相源，§2/§3/§4/§6）
- 会话：`wbdy-050cdcf1-514`（本报告）；前序会话 `wbdy-f48ab025-8df` 已失效（上下文丢弃，本报告不依赖其对话历史）
- 本报告性质：阶段 5 前半 · 黑板文件，供 reviewer / tester / 队长读取
- 结论一句话：**F3 verdict=correct（ΔL 与 Spearman 双双 FAIL）→ 触发 F4；F4 三候选（a/b/c）均不达 §3 矫正后目标 → 执行 §3 失败路径：不写盘，default_look 保持现状。** 仓内零写入。

---

## 1. 元信息与口径来源

| 项 | 值 |
|---|---|
| 阶段 | F3 三臂测量 + F4 矫正候选对比 |
| 目标 | RAW 打开色彩对齐 DNG 渲染（design §2 公平口径：每臂自己的默认打开语义） |
| 依据文件 | `.agent-team/design.md` v2.1（2026-09-22） |
| Python | 3.12.10 |
| 库版本 | rawpy 0.27.0 / cv2 5.0.0 / numpy 2.5.1 / scipy 1.18.0 / PIL 12.3.0 |
| 语料 | `K:/data/photo`（递归 `*.NEF`，剔 `._` AppleDouble，共 4053 张） |
| 样本 | n=48（同 pick 算法重建，清单内嵌 §7） |
| 工作根 | `K:/work/project/pixo` |

> 编号隔离：`.agent-team/design.md §8` 声明的组队前残留（`R31_enabled_wiring.md` 等）与本轮产物无关，本报告不引用、不动。

---

## 2. F3 三臂测量（口径 + 执行）

### 2.1 口径摘要（design §2 公式块逐字引用，design.md:35-48）

> **度量（公式写死，全程 float，无二次量化）**：
> ```
> 每臂每片:
>   img → (u16 时) u8f = u16 / 65535.0 * 255.0        # float, 不取整
>   rgb01 = u8f / 255.0 → cv2.cvtColor(RGB2LAB, float32 输入)
>        # OpenCV float Lab: L∈[0,100], a/b∈[-127,127]
>   L8 = L * 2.55; a8 = a + 128; b8 = b + 128          # 转仓内 8 位标度, 保持 float
> 几何归一（唯一算法）: 各臂输出先 resize 长边→512 (INTER_AREA),
>   再中心裁 min(h,w)×min(h,w) 方形; 朝向三臂同侧（均按 EXIF 转正）。
> 逐片: ΔL = median(L8_arm_crop) − median(L8_dng_crop)  (Δa/Δb 同式)
> 主判据量: median_over_photos( |Δ_photo| )             # 先逐片绝对值再跨片中位
> 分布表: 在逐片**有符号** Δ 上报 p10/p50/p90/IQR/min/max
> ΔE76 换算: L100=L8/2.55, a=a8−128, b=b8−128 (对齐 fit_tone_curve.py:106-111)
> ```

- **几何归一常量**：long_edge=512、插值 INTER_AREA、中心裁正方形（`environment.constants`）。
- **主判据量**：`median_over_photos(|Δ_photo|)`（先逐片绝对、再跨片中位）。
- **d*** 定义：`d* = pixo − DNG`；RT 为参考量 `Δ(RT−DNG)` / `Δ(RT−pixo)`（`meta.delta_definition`）。

### 2.2 三臂发生器口径

| 臂 | 发生器 | 口径 |
|---|---|---|
| **pixo** | `Renderer.render_preview_full(long_edge=1024, params=default_look)` | 现网默认观感；DCP=`resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp`；输出 8-bit；已 EXIF 转正（`api.py _apply_orientation`） |
| **RT** | `rawtherapee-cli -o <dir> -t -Y -d -c <file>`（`-d` 无参 flag；`-c` 最后；subprocess 列表形式，无 shell 拼接） | 实测 exe `C:/Program Files/RawTherapee/5.13/rawtherapee-cli.exe`，版本 `RawTherapee, version 5.13, command line.`；`-t` 默认 16-bit TIFF；`-d` = 启用 RT Default Processing Profile；输出 profile_guess=srgb, is_srgb=true, deviation_nonsrgb=false（无口径偏离） |
| **DNG** | `dng_validate` 默认渲染（WriteTIFF 路径，经 `_r31_dng_render.render_dng_to_tiff`） | DNG SDK **1.7**；as-shot WB + 嵌入 profile + sRGB + 基线曝光；**全分辨率**（design §5 禁预览级）；输出 8-bit sRGB TIFF |

> DNG 全分辨率输出尺寸实测：6048×4032（PIL mode RGB，8-bit），未压缩 TIFF 73,167,096 B（≈73MB/张），`render_elapsed_s≈9.8`。

### 2.3 执行方式（长活切片化）

- 引擎 ACP 通道跑长批处理曾两次崩溃（本环境已知问题）→ **全部长活切片化**：`--slice i --nslices 6` + `--merge` 逐片落盘（`_r31_parts/`），每条命令 ≤8 分钟，中途崩溃可从盘上 part 续算。
- **n=48（manifest 48 片）**：48/48 有效、跳片 0。
- **sanity（跨臂朝向 dhash 四角比对，design §88）**：仅 1 处异常——`K:/data/photo/厦门/103XM_04/DSC_2890.NEF` 的 **RT 臂** rot180 hamming=98（阈值 96）→ 该片 **RT 臂跳过并留痕**（`n_rt_ok=47`）。**RT 臂不入判据（design §3），故不影响 verdict。**
- **RT 渲染回退**：RT 上 RT 臂输出 16-bit TIFF，PIL 读会截断 → 探针改用 `cv2.IMREAD_UNCHANGED` 保真读取（`per_photo.rt_meta.read`）。
- **临时大文件纪律**：RT / DNG 全分辨率 TIFF（可达 ~73MB/张）渲染后**读入内存即删**；任何时刻盘上至多 1 张全分辨率 TIFF；结束 rmtree 临时目录（`temp_cleanup.executed=true`，`rt_tiffs_deleted=48` / `dng_tiffs_deleted=48`）。

### 2.4 wb_B DNG 转换不变性佐证（design §3）

| 项 | 值 |
|---|---|
| 对照片 | `K:/data/photo/2026春节/DSC_0352.NEF` ↔ `.artifacts/_r31_refs/DSC_0352.dng` |
| wb_B (源 NEF) | 1.7578125 |
| wb_B (DNG) | 1.7578121423721313 |
| Δ | **3.5762786865234375e-07** |

⇒ DNG 转换不改变相机 as-shot WB（`wb_B := rawpy.camera_whitebalance[2] / [1]`，源 NEF）。

---

## 3. F3 分布表与判据块

数据源：`.artifacts/_r31_three_arm.json`（本报告数据均由此 JSON 提取，非凭记忆）。

### 3.1 分布表（逐片有符号 Δ，p10/p50/p90/IQR/min/max + median|Δ|）

**pixo − DNG**（n=48）：

| Δ | p10 | p50 | p90 | IQR | min | max | median\|Δ\| |
|---|---|---|---|---|---|---|---|
| ΔL | −26.252 | −11.191 | 10.106 | 22.192 | −31.504 | 13.500 | **13.438** |
| Δa | −0.940 | −0.062 | 0.619 | 0.604 | −2.259 | 4.381 | **0.231** |
| Δb | −1.123 | 0.105 | 1.526 | 1.002 | −3.958 | 2.065 | **0.514** |

**RT − DNG**（n=47，参考量，不入判据）：

| Δ | p10 | p50 | p90 | IQR | min | max | median\|Δ\| |
|---|---|---|---|---|---|---|---|
| ΔL | 16.274 | 35.352 | 52.200 | 9.979 | 0.570 | 64.020 | **35.352** |
| Δa | −0.735 | 0.116 | 2.006 | 0.854 | −4.838 | 9.388 | **0.441** |
| Δb | −1.383 | −0.062 | 4.441 | 1.349 | −4.761 | 6.946 | **0.714** |

**RT − pixo**（n=47，参考量）：

| Δ | p10 | p50 | p90 | IQR | min | max | median\|Δ\| |
|---|---|---|---|---|---|---|---|
| ΔL | 23.623 | 45.243 | 59.483 | 21.267 | 8.135 | 68.388 | **45.243** |
| Δa | −0.411 | 0.243 | 1.337 | 0.537 | −3.406 | 6.696 | **0.329** |
| Δb | −1.805 | 0.119 | 3.086 | 2.536 | −5.008 | 7.461 | **1.165** |

> 选型参考解读：RT 默认处理档相对 DNG 参照**中位提亮 +35.4 L8**（且相对 pixo +45.2），说明 DNG 参照整体比 RT 默认档更暗；RT 与目标差异远大于 pixo。

### 3.2 判据块（阈值字面常量 + 各比较结果，design §3）

判据（design.md:55-56，写死）：`median(|ΔL|) ≤ 5` **且** `median(|Δa|) ≤ 3` **且** `median(|Δb|) ≤ 3` **且** `|Spearman(逐片有符号 ΔL, wb_B)| < 0.3` → 判达标；任一不满足 → 执行 F4。

| 比较 | 实测 | 阈值 | 结果 |
|---|---|---|---|
| median(\|ΔL\|) | 13.438 | ≤ 5 | **FAIL** |
| median(\|Δa\|) | 0.231 | ≤ 3 | pass |
| median(\|Δb\|) | 0.514 | ≤ 3 | pass |
| \|Spearman(有符号ΔL, wb_B)\| | 0.4791 | < 0.3 | **FAIL** |

- **verdict = `correct`**（`criteria.verdict="correct"`, `correct_triggered=true`）→ **触发 F4**。
- 有符号 ΔL 分布：p50=−11.19、IQR=22.19、min=−31.50、max=+13.50 → 现网 default_look 相对 DNG 参照**系统性偏暗**（中位 −11.2）。
- 48/48 有效、0 跳片、0 sanity（pixo/DNG 侧无朝向异常）。

---

## 4. F4 三候选对比

### 4.1 三候选对比表（n=48，均 48/48 有效、0 跳片；`--skip-rt`，RT 不入判据）

| 候选 | 口径 | median\|ΔL\| | median\|Δa\| | median\|Δb\| | Spearman(有符号ΔL, wb_B) | ΔL 有符号 p50 | ΔL IQR | verdict |
|---|---|---|---|---|---|---|---|---|
| **a** | 现 default_look（`tone.profile_curve=true`，eotf=srgb，R30 接线） | 13.438 | 0.231 | 0.514 | 0.4791 | −11.19 | 22.19 | correct |
| **b** | 现 recipe（`tone.eotf="recipe"`，引擎现 `recipe_tone_curve.json` 旧相机曲线） | 29.975 | 1.745 | 1.141 | 0.4363 | **+29.98** | 12.12 | correct |
| **c** | 新 recipe（DNG 目标新曲线，eotf=recipe，进程内 override） | **4.453** | **0.225** | **0.435** | 0.5068 | +4.18 | 3.94 | correct |

- **候选 b 出局**：median|ΔL|=29.975，有符号 ΔL p50=**+29.98**、min=+4.02、max=+42.95 → **系统性 +30 提亮偏置**，明显劣于 a。旧相机曲线（相机 thumb 拟合目标）与 DNG 参照差距大，佐证"目标须换 DNG 渲染参照"。
- **候选 c 最优**：median|ΔL|=4.453，是唯一把 |ΔL| 压进 §3 达标线（≤5）的候选；ΔL IQR 仅 3.94（vs a 的 22.19，−82%），median|ΔL| 相对 a 降 66.9%。**但 4.453 > 3 → 未达 §3 矫正后目标。**
- 逐片 |ΔL| 尾部：c `p90=9.618 max=26.039`，`#(|ΔL|>5)=20/48`、`>10` 仅 `4/48`（a：`>5` 38、`>10` 29；b：`>5` 47、`>10` 45）。

### 4.2 候选 c 拟合 provenance 摘要

数据源：`.artifacts/_r31_recipe_dng_target.json`（v4 格式，sha256 `dc829833378c1a7cbc07d41e0f4a32329e0ec87f13bb370c2694cfc714caeafd`）。

| 项 | 值 |
|---|---|
| version / target | 4 / `dng_render` |
| **gains** | **[1.0, 1.0, 1.0]** |
| 曲线 | **1024 点、单调=True**；端点 0.0 → 255.0；pt1/8/32/128/512 = 0.0 / 21.288 / 85.805 / 188.062 / 253.434 |
| 目标来源 | DNG 渲染参照目录 `.artifacts/_r31_tgt_tmp`（就绪 48/48，coverage 1.0） |
| 训练/验证切分 | **train 36 / holdout 12**（seed 20260919，holdout_frac 0.25，镜像 `fit_tone_curve.py:211-214`） |
| eval_train | n=36；`dL_med=−0.54 da_med=0.04 db_med=0.34 A_med=1.05 A_p90=2.44` |
| eval_holdout | n=12；**`dL_med=0.10 da_med=−0.07 db_med=0.38 A_med=1.76 A_p90=4.54`** |
| 跳过 | 0 |
| checks | `picklist_read/split_ok/curve_len_1024/curve_monotone/gains_len_3/eval_train_keys/eval_holdout_keys/not_writing_configs` 全 True |
| 拟合工具 | `.artifacts/_r31_fit_dng_target.py`（thin adapter，`importlib` 复用 `fit_tone_curve.py`，本体零改动） |

> 拟合内在一致性极好（holdout dL_med=0.10），但**逐片复测**（§4.1 c）仍留 p90=9.62 的尾部 → 拟合降了中位与主体，未消尾部（见 §6 仲裁事项 ii）。

### 4.3 候选 c 复测的 monkeypatch 路线说明（仓内零写入）

- 引擎 `src/pixo/render/modules/tone_map.py:62` **硬编码** `_RECIPE_CAL_FILE = .../recipe_tone_curve.json`；`ToneStage.param_schema` 无路径注入键，`eotf` 仅 `srgb/power22/lrfit/recipe` 四枚举 → **params 无法指向自定义 recipe 路径**。
- 队长 2026-09-22 **授权 monkeypatch 路线**（第二棒 A 裁决）：探针 `--recipe-override <json>` 在进程内 `import pixo.render.modules.tone_map`，保存原 `_RECIPE_CAL_FILE` → 指向 `.artifacts/_r31_recipe_dng_target.json` → 清 `tone_map._RECIPE_CACHE` 与 `calibration_store.reset()`（含负缓存）→ 渲染；`try/finally` 还原 + `atexit` 兜底（幂等）。
- 合规依据：这是**仓内既有测试手法**先例（`tests/unit/test_calibration_store.py:251`、`tests/unit/test_tone_sixkey.py:229`），**不落盘 src/**，仅进程内 —— 是实现 design §4「候选 c 参与对比」的唯一合规手段（先写引擎 recipe 或改 tone params schema 两条路均被拒绝）。
- 环境留痕：`environment.arms.pixo.recipe_override = {method:"monkeypatch tone_map._RECIPE_CAL_FILE（进程内，仓内零写入；队长 2026-09-22 授权）", file:..., sha256:"dc829833378c1a7c…", original_file:.../recipe_tone_curve.json, original_sha256:"b9b0bd77b3fbd311…"}`；`eotf_effective="recipe"`。
- 冒烟对照（n=2）：覆盖生效后 DSC_0352 pixo L 由候选 b 的 93.4 → 63.6（DNG=52.8）→ 确认 override 真实生效。

---

## 5. 判据执行结论（§3 失败路径）

- **§3 达标线**（L≤5 且 a≤3 且 b≤3 且 |Spearman|<0.3）：候选 c 前三项均过（4.453 / 0.225 / 0.435），但 **Spearman=0.5068 ≥ 0.3 → 不达标**（与 a/b 同）。
- **§3 矫正后目标**（L≤3 且 a≤2 且 b≤2）：**a / b / c 三者均不达**（c 的 |ΔL|=4.453 > 3；其余项达标）。
- ⇒ 命中 **design §3 失败路径（design.md:59-60）**：
  > 失败路径（三候选均不达矫正后目标）：**不写盘**、保留现状 default_look，数据与结论落报告、上报队长仲裁（援引 R18"失败路径合法"先例），**不擅自迭代**。
- **执行结果**：
  - **不写盘** —— 本棒（F4 全程）**仓内零写入**。
  - `configs/styles/default_look.json` **保持现状**：`tone.profile_curve: true` 与 `whitebalance.mode: "as_shot"` 两键**原样**（sha256 `252d80f2e70f820cf0007cb236ceae72ab2b8e53049c0c615797652ff1af0944`，mtime 2026-09-19）。
  - `src/pixo/render/recipe_tone_curve.json` **未动**（sha256 `b9b0bd77b3fbd3119c2ea32827988e6cc2efc6ffad59b9d5e59ed65ee848520b`，mtime 2026-09-19）。
  - 候选 c 曲线 `.artifacts/_r31_recipe_dng_target.json` **未接线**（仅落在 .artifacts/，供后续裁决）。

---

## 6. 仲裁请求事项（上报队长，附数据）

> 本轮**不改判据、不擅自迭代**；以下仅为供队长裁决的事项登记。

- **(i) c 的 Spearman=0.5068 在窄动态范围上的解读**：c 的有符号 ΔL 全落在 [−4.74, +26.04]、IQR=3.94；a 的 IQR=22.19。Spearman 在极窄动态范围上对"残余趋势/离群"高度敏感，与 a 的宽动态不可同尺度解读。判据字面写死为 `<0.3`，故**如实判 fail**。请裁决：是否影响**后续判据设计**（例如是否需对 |ΔL| 已达标者改用别的排序相关口径）——**本轮不动**。
- **(ii) c 相对 a 改进显著，是否值得专项处理 |ΔL| 尾部后再议接线**：median|ΔL| 13.438→4.453（−66.9%）、IQR 22.19→3.94（−82.3%）、|ΔL|>5 片数 38→20；但 c 尾部仍存 `p90=9.618`、`max=26.039`（4/48 片 |ΔL|>10）。是否组织专项压尾部（如按亮/暗段或按 wb_B 分层重拟合）后再议 recipe 接线。
- **(iii) tone_map recipe 路径硬编码（`tone_map.py:62`）**：params 无路径注入键，recipe 走固定路径 → 引擎若需"可参数化 recipe"属**引擎改动**，需**立项**（本棒按红线未动 src/）。请裁决是否立项。
- **(iv) manifest.json 与 picklist.json 双清单并存**：两者已验证 **48 片 NEF 逐条同序完全一致**（F4 拟合时亦以 picklist 复核 manifest）。建议 design §6 统一为单一清单以消歧义（本棒未改 design）。

---

## 7. 交接与产物清单

### 7.1 产物与 sha256（实际计算）

| 产物 | 大小 (B) | sha256 |
|---|---|---|
| `.artifacts/_r31_three_arm.json`（F3 正式） | 129,813 | `1e25f512a67dbbed794d3a17a3353dfca590d2c2ab38463a1d92810413188994` |
| `.artifacts/_r31_three_arm_cand_b.json` | 58,441 | `c8d805c6f767535329a663458c5939c62fef1419283afa6b2c01d9204955e87f` |
| `.artifacts/_r31_three_arm_cand_c.json` | 59,097 | `2bf95014bf55c8062bbc948929ec13f69a16cbc7da28a50d11a5d257bd7d82a9` |
| `.artifacts/_r31_recipe_dng_target.json`（候选 c 曲线，**未接线**） | 14,120 | `dc829833378c1a7cbc07d41e0f4a32329e0ec87f13bb370c2694cfc714caeafd` |
| `.artifacts/_r31_cand_b_params.json` | 918 | `d5398d1788af4d0d4d3de16479d27d4f20bf0d0477ca0d9b95f406c124f650a8` |
| `.artifacts/_r31_cand_c_params.json` | 1,031 | `082d9eb50be7cfc4a05ef4d549cd53a86fcf56bcbfe2f360c585d156cda0a434` |
| `.artifacts/_r31_three_arm.py`（探针源，含 F4 扩展） | 70,544 | `d667e9be8f52446dc5e3f104a7a1fcfdb3096fb79f85f90bab646a033c51a881` |
| `.artifacts/_r31_fit_dng_target.py`（拟合 adapter） | 20,474 | `34fee5debc6299b7b1ed5b4566bca3730e47283bf3af170cab20a1e8f546f22c` |
| `.artifacts/_r31_dng_render.py`（F1 渲染壳） | 10,919 | `dfa69be4105e5e5d723d3965931ec7742ca626b7b32d1f61535c0a105aba3f36` |
| `.artifacts/_r31_refs/manifest.json` | 12,539 | `fbf2f794709ab50a8c3ebd6b5345a6422fd6042c7bf3c302cfacb1f33b941cd6` |
| `.artifacts/_r31_refs/picklist.json` | 2,850 | `d0db6ebb704b2133d49d55a7a550b5ba6f209b30d289797c8551b12a020ef338` |

**分片产物（供 tester 复算）**：`.artifacts/_r31_parts/part_1..6.json`（F3）、`.artifacts/_r31_parts_b/part_1..6.json`（候选 b）、`.artifacts/_r31_parts_c/part_1..6.json`（候选 c）——每 part 记录 `dng_tiffs_deleted=8` 等 temp 清理字段。

**日志**：`_r31_fit_dng_target_run.log`、`_r31_cand_b_slice{12,34,56}.log`、`_r31_cand_c_slice{12,34,56}.log`。

### 7.2 后续棒次指引

1. **入库版脚本（design §6 B6）**：最终版 harness 以**无下划线前缀**入库（`.artifacts/r31_three_arm.py` / `r31_dng_render.py` 等），随报告同批提交并附 sha256。本棒**未**做重命名改造（属后续棒次）。
2. **正式报告 `R31_dng_alignment.md`**：由队长 / reviewer 定稿流程产出（本文件为阶段 5 前半黑板，非最终报告）。
3. 判据链（design.md:61）：dev-2 出数 → **reviewer 复核判据执行** → **tester 抽片复现**。请 reviewer 重点复核 §3 判据执行与 §5 失败路径执行；请 tester 用 `_r31_parts*/` 复算。
4. 仲裁（§6）未决前**不接线、不写盘**。

### 7.3 48 片清单（内嵌，design §1「清单内嵌使测量可复算」）

| # | name | nef_path |
|---|---|---|
| 1 | DSC_0352 | K:/data/photo/2026春节/DSC_0352.NEF |
| 2 | DSC_0436 | K:/data/photo/2026春节/DSC_0436.NEF |
| 3 | DSC_0520 | K:/data/photo/2026春节/DSC_0520.NEF |
| 4 | DSC_0605 | K:/data/photo/2026春节/DSC_0605.NEF |
| 5 | DSC_1615 | K:/data/photo/厦门/101XM_02/DSC_1615.NEF |
| 6 | DSC_1700 | K:/data/photo/厦门/101XM_02/DSC_1700.NEF |
| 7 | DSC_1784 | K:/data/photo/厦门/101XM_02/DSC_1784.NEF |
| 8 | DSC_1869 | K:/data/photo/厦门/101XM_02/DSC_1869.NEF |
| 9 | DSC_1953 | K:/data/photo/厦门/101XM_02/DSC_1953.NEF |
| 10 | DSC_2037 | K:/data/photo/厦门/101XM_02/DSC_2037.NEF |
| 11 | DSC_2122 | K:/data/photo/厦门/101XM_02/DSC_2122.NEF |
| 12 | DSC_2206 | K:/data/photo/厦门/101XM_02/DSC_2206.NEF |
| 13 | DSC_2291 | K:/data/photo/厦门/101XM_02/DSC_2291.NEF |
| 14 | DSC_2378 | K:/data/photo/厦门/101XM_02/DSC_2378.NEF |
| 15 | DSC_2463 | K:/data/photo/厦门/101XM_02/DSC_2463.NEF |
| 16 | DSC_2547 | K:/data/photo/厦门/102XM_03/DSC_2547.NEF |
| 17 | DSC_2632 | K:/data/photo/厦门/102XM_03/DSC_2632.NEF |
| 18 | DSC_2716 | K:/data/photo/厦门/102XM_03/DSC_2716.NEF |
| 19 | DSC_2803 | K:/data/photo/厦门/103XM_04/DSC_2803.NEF |
| 20 | DSC_2890 | K:/data/photo/厦门/103XM_04/DSC_2890.NEF |
| 21 | DSC_2974 | K:/data/photo/厦门/103XM_04/DSC_2974.NEF |
| 22 | DSC_0644 | K:/data/photo/厦门/1/DSC_0644.NEF |
| 23 | DSC_0728 | K:/data/photo/厦门/1/DSC_0728.NEF |
| 24 | DSC_0813 | K:/data/photo/厦门/1/DSC_0813.NEF |
| 25 | DSC_0897 | K:/data/photo/厦门/1/DSC_0897.NEF |
| 26 | DSC_0981 | K:/data/photo/厦门/1/DSC_0981.NEF |
| 27 | DSC_1066 | K:/data/photo/厦门/1/DSC_1066.NEF |
| 28 | DSC_1150 | K:/data/photo/厦门/1/DSC_1150.NEF |
| 29 | DSC_1235 | K:/data/photo/厦门/1/DSC_1235.NEF |
| 30 | DSC_1319 | K:/data/photo/厦门/1/DSC_1319.NEF |
| 31 | DSC_1404 | K:/data/photo/厦门/1/DSC_1404.NEF |
| 32 | DSC_1488 | K:/data/photo/厦门/1/DSC_1488.NEF |
| 33 | DSC_5278 | K:/data/photo/西安/0711/raw/DSC_5278.NEF |
| 34 | DSC_5362 | K:/data/photo/西安/0711/raw/DSC_5362.NEF |
| 35 | DSC_5446 | K:/data/photo/西安/0711/raw/DSC_5446.NEF |
| 36 | DSC_5531 | K:/data/photo/西安/0711/raw/DSC_5531.NEF |
| 37 | DSC_5615 | K:/data/photo/西安/0711/raw/DSC_5615.NEF |
| 38 | DSC_5700 | K:/data/photo/西安/0711/raw/DSC_5700.NEF |
| 39 | DSC_5788 | K:/data/photo/西安/0711/raw/DSC_5788.NEF |
| 40 | DSC_5873 | K:/data/photo/西安/0711/raw/DSC_5873.NEF |
| 41 | DSC_5957 | K:/data/photo/西安/0711/raw/DSC_5957.NEF |
| 42 | DSC_6041 | K:/data/photo/西安/20260912_qlysdwy/raw/DSC_6041.NEF |
| 43 | DSC_6126 | K:/data/photo/西安/20260912_qlysdwy/raw/DSC_6126.NEF |
| 44 | DSC_6210 | K:/data/photo/西安/20260912_qlysdwy/raw/DSC_6210.NEF |
| 45 | DSC_6295 | K:/data/photo/西安/20260912_qlysdwy/raw/DSC_6295.NEF |
| 46 | DSC_6382 | K:/data/photo/西安/20260912_qlysdwy/raw/DSC_6382.NEF |
| 47 | DSC_6467 | K:/data/photo/西安/20260912_qlysdwy/raw/DSC_6467.NEF |
| 48 | DSC_6556 | K:/data/photo/西安/20260912_qlysdwy/raw/DSC_6556.NEF |

> pick 算法：corpus 递归 `*.NEF`（大小写不敏感），剔 `._` AppleDouble，`sorted()` 字典序，等步长 `idx_i = floor(i*total/N)`（design §1）。

---

## 8. 红线自检

| 红线 | 核对 | 结果 |
|---|---|---|
| 引擎 `src/` 零改动（R23 纪律） | `git status --short src/` = 6 个 ` M`：`exposure.py / hsl.py / white_balance.py / graph.py / session.py / runtime.py`；**mtime 全为 2026-09-21（本棒之前既有，非本轮所改）** | PASS（本棒零改动） |
| 本棒不写 `configs/` | `git status --short configs/` **无输出**；`default_look.json` sha256 `252d80f2e70f820c…`（mtime 2026-09-19） | PASS（未动） |
| 本棒不写引擎 recipe | `src/pixo/render/recipe_tone_curve.json` sha256 `b9b0bd77b3fbd311…`（mtime 2026-09-19）；候选 c 曲线仅落 `.artifacts/` | PASS（未动） |
| 仓内零写入（F4 全程） | monkeypatch 仅进程内；无本棒新增/删改的跟踪文件 | PASS |
| 长活切片化 | F3 / 候选 b / 候选 c 均 6 切片 + merge；part 落盘可续 | PASS |
| 临时大文件纪律 | 每片渲染→读→即删；任一时点 ≤1 张全分辨率 TIFF | PASS |

> 说明：`git status` 另见 20 个并行工作流文件（`pyproject.toml`、`scripts/*`、`tests/*` 等），非本棒域，**未触碰**（与 junior-report 记录的并行工作流一致）。

---

## 9. 附：判据链状态

| 环节 | 责任 | 状态 |
|---|---|---|
| 出数（F3 + F4 三候选） | dev-2 | DONE（本报告） |
| 复核判据执行 | reviewer | PENDING（请重点审 §3 / §5） |
| 抽片复现 | tester-whitebox | PENDING（用 `_r31_parts*/` 复算） |
| 仲裁（§6 四项） | 队长 | PENDING |
