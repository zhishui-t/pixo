# 阶段二新表入库报告 —— §5 路径 1（先行单相机采纳，队长已拍板）

- 日期：2026-09-04
- 执行：tester-1（长安）
- 前置：t35 QA 终审 GO（.artifacts/stage2_qa_verdict.md）；t34 红线报告（stage2_gate_report.md，对照档分支）
- 入库内容：calib_out/ 四件 → 正式位置（skin_oklab 新旧相同未动）

## 结论（TL;DR）

**入库完成，六步全过。** 全量回归 1297 绿；入库位与对照档语义等价（双轨 ΔE 4.251 = 4.251 逐位一致）；新表收益保持（全语料端到端 ΔE2000 median 旧表 6.649 → 新表 4.251，**54/54 逐照片改善、零反转**）。

**过程中抓住并修复一个 t32 遗留实质问题**（详见 §4）：`cal_ev_weights` 与运行时 `_cal_ev` 在重复 wb 键上的取值分歧被 `test_real_table_bitwise`（真实表逐位校验）在新表上首次暴露——已修复 scripts 侧并 12 万次对拍归零；src 代码零改动。

**另确认一个门禁覆盖缺口需上报**（详见 §5）：gate 金样本对四个标定表**零敏感**（替换前后 15 features 全部逐位一致）——gate 合成用例不触达 warmth/neutral/exposure 表/rp_ccm 的 auto 标定路径，「金样本按新表重生成」红线在当前 case 集合下是空洞的。

## 1. 旧表备份 ✅

四个被替换正式表 → `configs/color/calib_prev/`（含 README 回退说明）。skin_oklab.json 新旧相同不在备份范围（目录内一份为补齐 θ 五源加载所需，README 已注明）。

## 2. 新表入库 ✅（双重逐位校验）

| calib_out 源 | 正式位置 | sha256 | load JSON |
|---|---|---|---|
| warmth_curve.json | configs/calibration/warmth_curve.json | 一致 | 逐位一致 |
| target_offset.json | src/pixo/render/target_offset.json | 一致 | 逐位一致 |
| z5ii_neutral_trim.json | resources/camera_profiles/z5ii_neutral_trim.json | 一致 | 逐位一致 |
| rp_ccm_nikon_z5_2.json | configs/color/rp_ccm_nikon_z5_2.json | 一致 | 逐位一致 |

**运行时加载链验证**（防「没读到新表」假象）：经运行时真实加载函数逐表读出，与 calib_out 数值逐位一致——`white_balance._load_warm_cal`（warmth 5×4 结点）、`calibration_store.load_json`（target_offset cal_table）、`calibration.camera_neutral_trim`（neutral a/b 曲线）、`rp_ccm.load_rp_ccm`（matrix 3×6）。

**src 红线说明**：`src/pixo/render/target_offset.json` 是**数据文件替换**，非代码改动——`git diff -- 'src/pixo/render/*.py'` 为 0，运行时 Python 代码零变化，阶段一「src/pixo/render 零 torch import」等红线不受影响。该表的正式位置本就在包内（`_cal_ev` 模块级加载），替换是表入库的唯一途径。

## 3. 金样本重生成 ✅（0 漂移 + reviewer 签注）

严格按 t34 §3.3 SOP 执行（G-4 坑规避：`--out` 显式传 `tests/regression/goldens/gate`）：

```
python tests/regression/goldens/generate_gate_goldens.py --check --out tests/regression/goldens/gate
python tests/regression/goldens/generate_gate_goldens.py --out tests/regression/goldens/gate
```
（以上为当时执行记录；G-4 修复后 `--out` 与 `PYTHONPATH=src` 均可省略）

| 步骤 | 结果 |
|---|---|
| 入库前 --check | OK（15 features 基线自洽——证明生成器与现行金样本一致，后续漂移可归因于新表） |
| 入库后 --check | **OK，15 features 零漂移**（意外，见 §5） |
| 正式重生成 | 15 features 写盘，.npy 与旧基线字节级相同（manifest diff 仅 reviewer 字段） |
| reviewer 签注 | 已注入 manifest.reviewer（非 pending，--check 复验 OK；签注含 0 漂移归因说明） |

## 4. 全量回归 ✅（1297 绿，过程中抓到并修复一个真问题）

```
1297 passed, 4 skipped, 1 xfailed, 13 warnings in 200.03s
```

**首跑 1 failed**：`test_calib_optimize.py::TestCalEvWeights::test_real_table_bitwise`（t32 所写，用真实表对 `optimize.cal_ev_weights` vs 运行时 `_cal_ev` 做逐位校验）。

- **根因**（t32 遗留，旧表掩盖）：wb 二次插值邻域含**重复 wb 键行**时（新表实测 2 组：1.303×2、1.814×2，同组两行 med 差 0.012、ev 值被优化分化），`_cal_ev` 直接 `np.interp`（重复段：左钳取组首/右钳与精确命中取组尾），而 `cal_ev_weights` 折叠重复键一律留末位——旧表重复行 ev 相同（1.229）故逐位一致，新表值分化（1.3921 vs 1.4617）后分歧显形。t32 注释「取左」与折叠实现（留末位）本就自相矛盾。
- **修复**（仅 scripts/calib/optimize.py，src 不动）：`cal_ev_weights` 的 wb 段权重按 np.interp 全语义重写（严格钳位判断 + 精确命中取组尾 + 开区间端点取组边界）。**300 随机构表 × 400 查询 = 12 万次对拍零失配**。
- **影响量化**（npz 缓存 54 张实际 (med, wb) 查询）：旧法仅 1 张失配（DSC_5260，偏差 +0.0696 EV ≈ 1/14 档）；修复后 54/54 与运行时逐位一致。全语料端到端 median 由此从 t32 报告的 4.244 微移至 **4.251**（第三位小数，方向与结论不变；t33 评估复用同机制，其数值同此口径微移）。
- 该单测的设计（对**真实表**逐位校验）恰好构成训练前向 vs 部署口径的回归门——本次它抓住的正是训练-部署 gap，验证了其价值。

## 5. 门禁覆盖缺口（上报队长）

金样本对四个标定表**零敏感**：gate_cases.py 的 15 个 feature 全部是「纯函数 + 显式参数」合成用例（exposure case = `soft_highlight_rolloff` 显式 knee；whitebalance = DCP 温转换；calibration = 显式 usercal 参数），被替换表的生效路径（`_cal_ev` auto 曝光、`apply_warmth` 文件曲线分支、`camera_neutral_trim` auto、`apply_rp_ccm` pipeline 并联）无一在 case 内。**含义**：未来任何标定表替换（含本次）金样本都不会变，红线「金样本按新表重生成」不能作为标定路径的回归门——标定路径当前仅由单测锁定。t34 报告「新表替换后金样本必然失配」的推断据此**修正为不成立**（当时的表数据差异证据仍有效，但对金样本的敏感性推断错误）。建议后续：给 exposure-auto/warmth/neutral/rp 路径补 gate case（合成输入 + 从正式表读参数），使金样本真正锁住标定数据。

## 6. 抽验 ✅（θ* 轨方向一致，改善而非反转）

npz 缓存重放（54 张全量，评估双实现断言一致），三轨对照：

| 轨道 | 端到端 ΔE2000 median |
|---|---:|
| 旧表（calib_prev） | 6.649 |
| **新表（现行 configs，入库后）** | **4.251** |
| calib_out（对照档，应与上一行同） | 4.251（逐位一致 ✅） |

- 与 calib_run.md 锚点一致：旧表 6.649 ≈ t32 before 6.658；新表 4.251 ≈ t32 after 4.244（第三位小数差 = §4 修复效应），**方向与幅度保持（+36.1% 改善）**。
- 抽验 3 张逐照片（.artifacts/stage2_adopt_perphoto.json）：DSC_5260 7.970→4.263、DSC_5269 9.768→3.991、DSC_5270 9.823→3.964，全部改善；**全语料 54/54 逐照片改善、零反转**。
- G-5 色度口径（入库后复算）：A 5.958 → B 4.793（+19.6%），门槛线 3/4 过（单相机项仍 ❌，与 t32/t33 一致）。
- 产物：stage2_adopt_eval_A.{md,json}（现行 vs calib_out）、stage2_adopt_eval_prev.{md,json}（现行 vs calib_prev）、stage2_adopt_perphoto.json（逐照片）。

## 7. 回退步骤

```bash
# 1) 四表拷回原位置
cp configs/color/calib_prev/warmth_curve.json       configs/calibration/warmth_curve.json
cp configs/color/calib_prev/target_offset.json      src/pixo/render/target_offset.json
cp configs/color/calib_prev/z5ii_neutral_trim.json  resources/camera_profiles/z5ii_neutral_trim.json
cp configs/color/calib_prev/rp_ccm_nikon_z5_2.json  configs/color/rp_ccm_nikon_z5_2.json
# 2) 金样本按回退后的表重生成 + 更新 manifest.reviewer 签注
python tests/regression/goldens/generate_gate_goldens.py --out tests/regression/goldens/gate
# 3) 全量回归确认
python -m pytest tests/unit tests/regression tests/integration
```

注意：calib_prev 是旧表字节级快照（cp 时校验过 sha256 与 git HEAD 一致）；scripts/calib/optimize.py 的 cal_ev_weights 修复与表回退无关（它是对齐运行时的正确性修复），回退后应保留。

## 8. 本轮改动清单（git）

- M `configs/calibration/warmth_curve.json`、`configs/color/rp_ccm_nikon_z5_2.json`、`resources/camera_profiles/z5ii_neutral_trim.json`（新表入库）
- M `src/pixo/render/target_offset.json`（数据文件替换，*.py 零 diff）
- M `tests/regression/goldens/gate/manifest.json`（重生成 + reviewer 签注；15 个 .npy 字节不变）
- M `scripts/calib/optimize.py`（cal_ev_weights 重复键语义修复，见 §4）
- ?? `configs/color/calib_prev/`（旧表备份 + README）
- ?? `.artifacts/stage2_adopt_*`（本报告与评估产物）
