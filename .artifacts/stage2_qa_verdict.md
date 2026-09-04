# 阶段二 QA 终审报告（t35）—— GO/NO-GO + 运行时零变化审计 + G-5 复核

- 日期：2026-09-04 · 执行：qa（长安）
- 基线提交：`bca52ed`（阶段一收口）
- 审计依据：docs/OWN_PIPELINE_STAGE2_DESIGN.md §5 验收门 + 铁律（运行时零变化）
- 审计对象：t30-t34 全部交付（surrogate_fidelity.md / calib_run.md / stage2_eval.md+json / stage2_gate_report.md / scripts/calib/ / configs/color/calib_out/ / 3 个新单测）
- 独立复核动作：git 全仓 diff 审计、torch 隔离扫描、calib 单测复跑、eval_stage2.py 缓存重放比对、G-5 分照片回归簇重算、per-group 系数漂移量化

---

## 1. 总结论：**GO** ✅（阶段二交付验收通过；新表采纳为后续决策，见 §5 建议）

设计目标「可微标定首跑 + G-5 收口」达成：§5 四门 **3 门过 + 红线门中金样本项按预案走对照档分支**（不豁免，闭环条件明确）；运行时零变化铁律 **零违反**。产出质量上，t32/t33 两条独立路径的数值交叉一致（端到端 6.658→4.244、G-5 A/B/C 三轨逐位相同），且 QA 本轮重放再次复现（§2.4）。

---

## 2. §5 验收门逐项核对（对应 t30-t34 交付）

| # | 验收门 | 标准 | 交付/报告 | QA 核对结果 |
|---|---|---|---|---|
| 1 | 保真门 | surrogate vs 真实管线 ΔE2000 median ≤0.05 / p95 ≤0.3，语料 ≥10 张，先于优化 | t30 `.artifacts/surrogate_fidelity.md`（2026-09-04 11:43，早于任何优化运行 13:31） | ✅ **PASS**：median 0.0000 / p95 0.0000（12 张评估 ≥10）；max 1.74 为个别像素级 u8 量化边界，门定义看 median/p95。时序核实：保真门先于首跑训练（ckpt 时间戳 13:31 > 门报告 11:43），「不过门禁止优化」纪律成立 |
| 2 | 标定收益 | 真 ΔE2000 before/after median 改善量化报告（不设硬线，首跑摸底） | t32 `.artifacts/calib_run.md` 真值对照 + checkpoint 轨迹；t33 `.artifacts/stage2_eval.md` 独立双轨复算 | ✅ **已量化且双源一致**：端到端 median 6.658→4.244（**+36.3%**）、p95 16.788→15.037（+10.4%）、mean 7.889→5.790；**54/54 张照片 median 全部改善，无一张回归**；checkpoint 轨迹单调下降（6.658→5.758→…→4.962→4.244），L-BFGS 无回滚记录。t33 独立重算与 t32 ckpt 历史逐位一致，QA 重放再次一致（见 #4） |
| 3 | 红线 | ① 金样本按新表重生成（reviewer 流程）② 全量 pytest 绿 ③ src/pixo/render git diff 为零 | t34 `.artifacts/stage2_gate_report.md` | ⚠️ **②③ ✅ / ① ⏸ 对照档分支**（详见 §3 与 t34 §3）：②1297 passed / 4 skipped / 1 xfailed（288s，与 t32 基线逐字一致）；③QA 独立复核 `git diff -- src/` 0 行 + status 空。①新表仅在未跟踪的 `configs/color/calib_out/`（6 文件），正式 configs 未替换、无入库提交——金样本是运行时输出快照，对照档不进加载链，重生成无意义；t34 已附 4/5 组件实质差异的敏感性证据（rp matrix / warmth 5 结点 / 中性 a,b 曲线 / target_offset cal_table 均不同，仅 skin 未动）+ 入库后补验 SOP（含 G-4 的 --out 历史路径坑）。**本轮不视为「金样本已按新表验证」，闭环条件 = 队长确认入库 → SOP → 全量绿** |
| 4 | 可复现 | seed + 语料清单 + 缓存 npz，`--resume` 重放一致 | t32 落盘 seed=20260904 + 54 张语料清单（4 拍摄日去重）+ `.artifacts/calib_opt_samples.npz`（121MB）+ `.artifacts/calib_ckpt.pt` + `calib_run_curves.json`；单测锁定确定性 | ✅ **QA 独立重放通过**：本轮运行 `python scripts/calib/eval_stage2.py`（缓存重放，35.9s），输出 JSON 与 t33 落盘版本**除时间戳字段外逐位一致**（含端到端 A/B 全指标、G-5 五轨 A0/A/B/C/D、门槛线布尔、分带统计）。θ 一致性链完整：calib_out == ckpt state_dict（重放时自动断言通过）。训练侧确定性由 t32 单测锁定（seed 2 步 Adam 逐位一致，64 项 calib 单测本轮复跑全绿 62s）。t31（theta_io）无独立 .artifacts 报告，其验证由 test_theta_io.py roundtrip 逐位恒等单测承担——符合设计（§2 只要求上下料契约） |

**小结**：验收门无造假迹象、无口径偷换；两处需要队长知情的边界（红线①对照档分支、G-5 单相机）均已被交付方如实标注而非掩盖。

---

## 3. 运行时零变化审计（git 全仓）

### 3.1 审计结果

| 检查项 | 结果 |
|---|---|
| `git diff HEAD --stat`（全仓 tracked） | **仅 `scripts/README.md` +7 行**（阶段二 calib/ 五脚本文档小节，属 scripts 允许范围，内容核对无误述） |
| `git diff -- src/` + `git status --porcelain -- src/` | **空** ✅（不只 src/pixo/render，整个 src 零改动） |
| frontend（目录存在、非嵌套 git 仓库） | **零改动** ✅（status 空；frontend/src 全量扫描零 torch 引用） |
| `src/pixo/render` torch 隔离 | **120 个源文件零 torch import** ✅（torch 只进 scripts/，隔离纪律达成） |
| 正式 configs（configs/color、configs/calibration、resources/camera_profiles、src 内嵌表） | **零覆盖零修改** ✅（t34 敏感性对比的「正式位置」列全部原样；新表只落未跟踪的 calib_out/） |
| 运行时行为 | 全量回归 1297 绿 + 金样本门全过（t34）⇒ 现行运行时输出与阶段一收口时逐位不变 |

### 3.2 新增物清单（全部未跟踪，属阶段二预期新增）

| 目录/文件 | 内容 | 判定 |
|---|---|---|
| `scripts/calib/`（5 脚本） | diff_core / surrogate_fidelity / theta_io / optimize / eval_stage2 | ✅ 允许范围 |
| `configs/color/calib_out/`（6 JSON） | 五组件新表 + rp_ccm_by_group | ✅ 允许范围（对照档，不进加载链） |
| `docs/OWN_PIPELINE_STAGE2_DESIGN.md` | 本阶段设计文档 | ✅ 允许范围 |
| `.artifacts/`（7 新文件） | 4 报告 + ckpt.pt + npz 缓存 + curves.json | ✅ 允许范围 |
| `tests/unit/test_diff_core.py` / `test_theta_io.py` / `test_calib_optimize.py` | 64 项单测 | ⚠️ **范围观察项**：超出任务描述枚举的「scripts/+configs/+docs/.artifacts」四类，但属测试资产而非运行时代码，设计铁律实质红线（src 零改动 + configs 不覆盖）未破，且 t30-t32 交付明示含单测、t34 报告已预告。判定：可接受，建议队长入库时将其纳入提交范围一并确认（遗留 #6） |

### 3.3 结论

**运行时零变化铁律：达成，零违反。** 唯一 tracked 改动是 scripts/README.md 文档行；无任何一处需要「改 src 才能接新表」的迹象（t34 同结论，QA 独立复核一致）。

---

## 4. G-5 门槛线结论复核（分组拟合是否消除回归簇）

### 4.1 门槛线四项（B 轨全局系数 = 转默认候选；t32/t33 双源一致，QA 重放复核一致）

| 门槛 | 实测 | 判定 |
|---|---|---|
| median 改善 ≥15% | **+20.1%**（A 5.982 → B 4.777） | ✅ |
| 无单照片 median 回归 >1 JND（2.3） | 最差 **+0.815** | ✅ |
| 总体 p95 不劣化 | 15.417 → 15.306 | ✅ |
| ≥2 相机复验 | 1 台（NIKON Z5_2） | ❌（语料缺口，非指标缺口） |

### 4.2 回归簇治理复核（QA 依 calib_run.md 分照片表重算）

**阶段一遗留回归簇（stage1_qa_verdict §3：523x-5250 拍摄段 9/54 张，最大 +2.607）——已治理 ✅**
阶段二 B 轨下该簇全部照片转为大幅改善：DSC_5236~5239（−1.47~−1.83）、5240~5245（−1.25~−5.03）、5250（**−5.15**，恰为阶段一最差回归照片）。阶段一「单一全局矩阵对该簇失效」的问题被新基座（新表 warmth/neutral）+ 中性语境重拟合的全局系数消化。

**阶段二 B 轨自身回归（8 张，全部集中在 2026-02-14 低色温/人造光带 wb_B≥2.0）——未完全归零，但幅度可控**
最差 +0.815（DSC_0364），8/54 张均为 <1 JND 的轻微回归，门槛线第 2 项因此通过。（注：t33 任务总结消息中「9 张」为计数口误，正式报告 stage2_eval.md 未出现该数；QA 实测 8 张，DSC_0358 为 −0.006 改善。）

**C 轨分组拟合对该簇的治理效果——实质性压缩（−73%）✅，但非归零**

| 指标 | B 轨（全局） | C 轨（分组 rp_g） |
|---|---|---|
| 2026-02-14 组池化 median | 5.395 | **4.897** |
| 回归照片数（vs A） | 8 | 6 |
| 最差单照片回归 | +0.815 | **+0.224**（DSC_0367） |

8 张中 2 张完全消除（DSC_0355/0363 转为 C<A），其余压至 +0.005~+0.224。组间系数漂移实证：per-group vs 全局系数 max|Δ| = 0.177 / **0.193** / 0.070 / 0.090（2026-02-10 / 02-14 / 07-01 / 07-05）——**回归簇所在的 02-14 组恰为漂移最大组**，与「低色温场景需要不同色度校正」的物理逻辑自洽，支撑未来分簇门控路线（设计 §4：不接运行时，本轮仅留证据）。

### 4.3 G-5 复核结论

门槛线 **3/4 通过**，未过项为 ≥2 相机复验（语料单相机，属语料缺口而非指标缺口，t32/t33 均如实标注）。**分组拟合实质性治理了回归簇**：阶段一遗留簇全额消除；阶段二残余 8 张轻微回归（<1 JND）被分组系数压至 ≤+0.224，且漂移位置与簇位置自洽。**结论：RP-CCM 具备转默认的指标条件，但按门槛线自身要求，须待 ≥2 相机语料复验后再决策。**

---

## 5. 新表入库建议（**只建议，不决策**）

> 前提认知：新表（calib_out/）尚未走完入库验证链——金样本未按新表重生成（对照档分支）。以下建议的任何采纳动作都必须绑定 t34 §3.3 SOP 执行。

1. **全采纳路径（五组件新表 + 联合 rp\*）——建议采纳，附三项条件**。证据最有力：端到端真值 +36.3%、54/54 张改善、无一张回归，且经 t32 训练 / t33 独立评估 / QA 重放三源一致。条件：
   - ① 采纳当日执行 t34 §3.3 SOP（金样本重生成 + reviewer 人工审查 + 全量 pytest），4/5 组件实质差异必然触发金样本重生，不可跳过；若逐组件灰度入库，每个灰度步重生成一次；
   - ② 认知泛化边界：单相机（NIKON Z5_2）+ 单 DCP 基线的拟合，跨设备/跨 profile 未验证——第二台相机语料到位后应复验（同 G-5 门槛第 4 项）；
   - ③ p95 绝对值仍 15.0（端到端 +10.4%），高误差尾部改善有限，属首跑摸底的已知上限，不宜以「+36.3%」外推用户感知质变。
2. **仅转 RP-CCM 路径（G-5 B 轨全局系数）——建议暂缓**，等 ≥2 相机复验通过门槛线第 4 项后再决策（B 轨 4.777 vs 现行系数同基座 5.732 的优势明确，但门槛线是自设的完整验收线）。
3. **分组 rp（C 轨 4.236）——维持不接运行时**（设计 §4），作为阶段三分簇门控的输入证据保留于 calib_out/rp_ccm_by_group.json。
4. 建议顺序：补第二台相机语料 → 重跑 optimize/eval（`--resume` 缓存可复用部分解码成本）→ 复现收益量级 → 队长决策 → t34 SOP 闭环。若队长判断 +36.3% 收益已值得先行单相机采纳，路径 1 的条件 ①②③ 同样适用。

---

## 6. 遗留清单

| # | 级别 | 内容 | 建议责任方 |
|---|---|---|---|
| L-1 | **P1** | 红线①未闭环：金样本未按新表重生成（对照档分支）。闭环 = 队长确认入库方案 → t34 §3.3 SOP（PYTHONPATH=src + 显式 --out tests/regression/goldens/gate，G-4 坑）→ 全量绿。逐组件灰度则每步重生成 | 队长决策 + tester |
| L-2 | **P1** | G-5 门槛第 4 项：≥2 相机复验。语料仅 NIKON Z5_2 一台，需补第二台相机语料后重跑标定/评估（端到端与色度两口径） | 语料 + dev/tester |
| L-3 | P2 | 单 DCP 基线（Nikon Z 5_2 RawLab LR Adobe Standard）：跨 DCP 泛化未验证，全采纳时随 L-2 一并扩面 | 阶段三 |
| L-4 | P2 | calib_run.md 的 Δθ 表全 0 为 `--g5-only` 重放的表观假象（θ0 基座被重载为 calib_out），t33 已在 stage2_eval.md 尾段注记并以真·现行 configs 重算 Δθ（warmth 0.22 / 曝光 0.32EV / 中性 0.85 / rp 0.86）。**归档以 stage2_eval.md §1 为准**；optimize.py 后续可改 replay 模式恒用 DEFAULT_SOURCES 加载 θ0 | dev 维护批次 |
| L-5 | P3 | B 轨 2026-02-14 低色温带 8 张轻微回归（≤+0.815，<1 JND）：分组系数可压至 ≤+0.224，未来分簇门控（如按 wb_B 带选系数）候选路径，本轮按设计不接运行时 | 阶段三 |
| L-6 | P3 | tests/unit/ 3 个新单测超出任务描述枚举的新增四类（scripts/configs/docs/.artifacts）：实质为测试资产、红线未破，建议队长入库提交时纳入范围确认 | 队长 |
| L-7 | P3 | `.artifacts/calib_opt_samples.npz`（121MB）大文件：当前未跟踪、不会误入提交；若要长期可复现建议明示进 .gitignore 或移外部存储；ckpt.pt（53KB）同理 | 维护批次 |
| L-8 | P3 | 端到端 p95 绝对值仍 15.0（中位 4.2）：高误差尾部（极端曝光/高光场景照片）治理空间仍在，属首跑摸底上限而非缺陷 | 阶段三 |

---

## 7. QA 复现（本报告全部独立动作）

```bash
# 1. 运行时零变化审计
git diff HEAD --stat                      # 仅 scripts/README.md +7
git diff -- src/ && git status --porcelain -- src/ frontend/   # 均空
# torch 隔离：os.walk src/pixo/render 120 文件零 torch import；frontend/src 同

# 2. 单测复跑
python -m pytest tests/unit/test_calib_optimize.py tests/unit/test_diff_core.py tests/unit/test_theta_io.py -q
# -> 64 passed（62s）

# 3. 可复现门：缓存重放比对（与 t33 落盘 JSON 除 generated 时间戳外逐位一致）
python scripts/calib/eval_stage2.py       # 35.9s, G-5 3/4、端到端 +36.3% 复现

# 4. G-5 回归簇重算：解析 calib_run.md G-5 分照片表（54 行），
#    B 轨回归 8 张 / C 轨治理至最差 +0.224；per-group 漂移 0.07~0.19
```

seed=20260904 · 语料 exports/auto/full_scan 54 张（4 拍摄日）· 判定基线 `bca52ed`。
