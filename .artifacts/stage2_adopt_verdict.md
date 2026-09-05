# 阶段二新表入库终审报告（t37）—— GO/NO-GO + 回退演练

- 日期：2026-09-04 · 执行：qa（长安）
- 审计对象：t36 采纳批次（`.artifacts/stage2_adopt_report.md`）——calib_out 四件入库正式位 + calib_prev 备份 + 金样本 SOP + cal_ev_weights 修复
- 前置：t35 QA 终审 GO（`stage2_qa_verdict.md`，条件①SOP/②泛化边界/③p95 上限）；队长拍板路径 1（先行单相机采纳）
- 独立复核动作：三方 sha256 校验、gate_cases.py 全文审查、金样本双向零敏感实证、src/frontend diff 审计、optimize.py 修复 diff 审查、回退演练全链（回退→探针→回滚→终态复原）、全量回归复跑

---

## 1. 总结论：**GO** ✅（入库成立；1 项非阻塞 gap + 2 项已知边界均已留痕）

t36 报告六步声明全部经独立复核属实。四件替换逐位一致、备份完整可回退（演练实证）、金样本 SOP 全步骤执行、src 代码零改动、全量 1297 绿（QA 复跑 173s 一致）。任务书抽验项「新金样本至少一个 case hash 与旧基线不同」经双向实证判定为**不适用**——金样本对标定表零敏感是门禁覆盖缺口（t36 §5 已如实上报），非造假或新表未生效。

---

## 2. 逐项核对结果

### 2.1 四件替换逐位一致 ✅ + 备份完整 ✅

| 组件 | 正式位 == calib_out | calib_prev == git HEAD |
|---|---|---|
| warmth_curve.json | sha256 一致 ✅ | git hash-object 一致 + JSON 语义相等 ✅ |
| target_offset.json | 一致 ✅ | 一致 ✅ |
| z5ii_neutral_trim.json | 一致 ✅ | 一致 ✅ |
| rp_ccm_nikon_z5_2.json | 一致 ✅ | 一致 ✅ |
| skin_oklab.json（未动） | 一致 ✅ | —（新旧相同，符合设计） |

- **口径注记**：裸字节 sha256 对比 git HEAD 会因 `core.autocrlf=true`（磁盘 CRLF vs 仓库 blob LF）产生伪差；本审计以 `git hash-object`（同 clean 过滤）+ load-JSON 语义相等双重复核——t36「cp 时校验 sha256 与 git HEAD 一致」的声明在 git 口径下成立。
- **备份可回退性**：不只看文件——回退演练（§4）实证拷回后运行时新进程立即读到旧表值，无缓存阻碍。

### 2.2 金样本 SOP 全步骤 ✅（签注/数量守卫/全量绿）

| SOP 步骤 | t36 声明 | QA 复核 |
|---|---|---|
| 入库前 --check 基线自洽 | ✅ | 报告记录在案（时序合理） |
| 入库后 --check 零漂移 | 15 features 一致 | QA 两次复跑 `--check` 均 OK（含 sha 逐文件校验 + reviewer 非 pending 硬守卫）✅ |
| 重生成 .npy 字节不变 | 仅 manifest.reviewer 变化 | git status：15 个 .npy 全部与 HEAD 无 diff；manifest.json diff 仅 reviewer 字段，签注非 pending、含归因说明与回退指引 ✅ |
| 数量守卫 | 15 features | manifest 15 条目 + 15 个 .npy tracked ✅ |
| 全量回归 | 1297 passed | **QA 复跑：1297 passed / 4 skipped / 1 xfailed（173s）** ✅ |

### 2.3 抽验项裁决：金样本 hash 与旧基线**全部相同**——判定不适用，归因独立成立

任务书预期「对新表敏感的 4/5 组件至少一个 case 的 hash 与旧基线不同」。实测相反：**15 个 .npy 与旧基线字节一致**。三重独立验证裁决这不是造假：

1. **gate_cases.py 全文审查**（5.9KB，15 用例逐个看）：全部为「纯函数 + 显式参数」合成构造——exposure case 用显式 `knee=0.9`、whitebalance 用 DCP 温转换 `temp_tint_to_wb(5000,10)`、calibration 用显式 usercal 参数；无一调用 `_cal_ev` / `apply_warmth` 文件曲线分支 / `camera_neutral_trim` / `load_rp_ccm`——四个标定表的 auto 生效路径不在任何 case 内。
2. **双向零敏感实证（本审计新增）**：回退演练中把 calib_prev 旧表放回正式位后跑 `--check`——**仍 15 features OK**。无论新表旧表，金样本都不变。
3. **新表确在加载链生效**：探针三路径（`_load_warm_cal` / `_load_cal_table`+`_cal_ev` / `load_rp_ccm`）新旧表读数分明（§4 表格），排除「没读到新表」假象。

**结论**：t34「新表替换后金样本必然失配」的推断确认修正为不成立；t36 §5 上报的门禁覆盖缺口属实且重要——当前金样本不锁标定数据，标定路径回归仅由单测层（`test_real_table_bitwise` 等真实表逐位对拍）锁定。本次入库恰由该单测抓住 cal_ev_weights 训练-部署 gap（首跑 1 failed → 修复 → 12 万次对拍归零 → 全绿），单测门的价值已被实战证明。**遗留 L-1：给标定 auto 路径补 gate case**（合成输入 + 从正式表读参数），使金样本真正锁住标定数据。

### 2.4 运行时零变化审计 ✅

- **src 代码零改动**：`git diff -- 'src/**/*.py'` 0 行；src/ 下唯一变化 = `src/pixo/render/target_offset.json`（数据文件替换）。t36 已书面说明其正当性：该表正式位置本在包内（`_cal_ev` 模块级加载），替换是表入库的唯一途径，不构成代码变化。
- **frontend 零改动**：git status 干净。
- **scripts/calib/optimize.py 修复范围审查**（+35 行）：diff 全部集中于 `cal_ev_weights` 的 wb 段权重构造与注释（np.interp 重复键全语义对齐：左钳取组首/右钳与精确命中取组尾/开区间端点取组边界），无其他语义改动，与报告 §4 一致；与表回退无关（对齐运行时的正确性修复，回退后应保留——t36 §7 已注明）。

### 2.5 风险留痕（t35 终审条件②③）⚠️ gap——不阻塞，本节补齐书面化

t36 报告中「单相机」仅出现于标题（"先行单相机采纳，队长已拍板"）与 §6 G-5 门槛项 ❌，**无 t35 条件②③ 要求的专门风险段**。裁决：不阻塞 GO（队长拍板语境已含"先行单相机"认知），但采纳报告应补留痕（遗留 L-3）。在此书面化补齐：

> **泛化边界（书面留痕，t35 条件②）**：新表拟合与全部验证基于**单相机（NIKON Z5_2）+ 单 DCP 基线（Nikon Z 5 2 RawLab LR Adobe Standard）**语料；跨相机/跨 DCP 泛化未验证。端到端 +36.1%（6.649→4.251，54/54 逐照片改善）是**该设备基线内**的收益。第二台相机语料到位后必须复验（G-5 门槛第 4 项同此要求）；若复验失败，按 §4 回退步骤可整体回退旧表。
>
> **收益上限认知（t35 条件③）**：端到端 p95 绝对值仍 15.0（中位 4.25），高误差尾部改善有限（+10.4% 量级）；"+36.1%" 不可外推为用户可感知的质变，属首跑摸底水平。

---

## 3. 全量回归复核 ✅

```
QA 复跑（入库终态）：1297 passed, 4 skipped, 1 xfailed, 13 warnings in 173.05s
```

与 t36 报告（200s 同结果）一致；含 `test_real_table_bitwise`（新表逐位校验，修复后）在内的 calib 64 项全绿。

---

## 4. 回退演练（实测可行 ✅，终态逐位复原）

**流程**（按 t36 §7 步骤 1 实测，步骤 2 以 `--check` 代验——见下注）：

| 阶段 | 动作 | 结果 |
|---|---|---|
| 0 | 新表基线：四表 sha256 + 运行时探针读数（`_load_warm_cal` 首结点 / `load_rp_ccm` matrix00 / `_load_cal_table`+`_cal_ev` 三组查询） | 基线存档 |
| 1 | calib_prev 四表拷回正式位 | 完成 |
| 2 | **新进程**探针（模拟回退后重启服务） | **读到旧表值 ✅**（下表） |
| 2' | 回退态 gate `--check` | **15 features OK**（双向零敏感实证） |
| 3 | calib_out 四表拷回正式位（回滚） | 完成 |
| 4 | 终态校验 | sha256 与基线**逐位一致** ✅ / 探针读数一致 ✅ / `--check` OK ✅ / git 状态与演练前一致 ✅ |

**回退生效证据**（新进程 = 无陈旧缓存，负缓存/mtime 失效机制在表替换后正确工作）：

| 读数 | 新表 | 旧表（calib_prev 回退态） |
|---|---|---|
| warmth 首结点增益 (r,g,b) | 1.1736, 0.9186, 0.8890 | **0.9508, 1.000, 1.000**（与 t34 旧表锚点 [0.951,1,1] 吻合） |
| rp_ccm matrix[0][0] | 2.3556 | 1.8133 |
| `_cal_ev` 三组探针 | 1.3902 | 1.5310 |

**演练结论**：t36 §7 回退步骤**可行**。两点补充进回退 SOP：
1. 真实回退时步骤 2（金样本重生成）的产物是零漂移 + reviewer 重置为 pending——**签注必须重写为回退批次语境**，否则签注文本与新表入库批次矛盾；
2. 鉴于已实证金样本对标定表零敏感，回退的实质验证点应放在**全量回归**（步骤 3，其中真实表逐位单测会自动校验旧表口径）与**运行时加载读数**（本演练探针方式），而非金样本。
3. 演练不改变仓库状态：终态 git status 与演练前逐位一致（6 M + calib_prev/ + stage2_adopt_* 产物），当前正式位仍为新表。

---

## 5. 遗留清单

| # | 级别 | 内容 | 责任方 |
|---|---|---|---|
| L-1 | **P2** | 门禁覆盖缺口（t36 §5 上报，本审计双向实证）：gate 金样本对四个标定表零敏感，「金样本按新表重生成」对标定路径是空洞红线——补标定 auto 路径 gate case（合成输入+从正式表读参数）。在此之前标定表回归仅由单测层锁定 | 阶段三测试线 |
| L-2 | **P2** | 单相机+单 DCP 泛化边界：第二台相机语料到位后复验（G-5 门槛第 4 项同源）；失败则按 §4 回退 | 语料+tester |
| L-3 | P3 | t36 采纳报告缺专门风险留痕段（t35 条件②③）——本报告 §2.5 已补齐书面化，建议回补进 adopt_report 或以本报告为准 | 维护批次 |
| L-4 | P3 | p95 绝对值 15.0（中位 4.25）的高误差尾部治理空间（首跑摸底上限） | 阶段三 |
| L-5 | P3 | calib_prev 备份目录未纳入 git（untracked）——入库提交时应连同 calib_prev 一起提交（否则回退依赖仅存在于工作区）；同批提交物：6 个 M 文件 + calib_prev/ + 本批次 .artifacts 报告 | 队长/提交批次 |

---

## 6. 复核动作清单（本报告全部证据可复现）

```bash
# 三方一致性（autocrlf 环境须用 git hash-object 口径）
sha256sum configs/color/calib_out/*.json            # vs 正式位四件
git hash-object configs/color/calib_prev/*.json     # vs git rev-parse HEAD:<正式位>

# 金样本守卫
python tests/regression/goldens/generate_gate_goldens.py --check --out tests/regression/goldens/gate
git status --porcelain -- 'tests/regression/goldens/gate/*.npy'   # 空 = 与 HEAD 字节一致

# 运行时零变化
git diff --stat -- 'src/**/*.py'                    # 空
git status --porcelain -- frontend/                 # 空

# 回退演练（见 §4；探针 = 新进程读 _load_warm_cal / load_rp_ccm / _load_cal_table+_cal_ev）

# 全量回归
python -m pytest tests/unit tests/regression tests/integration   # 1297 passed
```

判定基线 `bca52ed` + 本批次工作区改动（见 t36 §8 清单，经 QA 核对一致）。
