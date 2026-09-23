# 测试报告（test-report-r22.md）— Pixo 第二十二轮（R22）

> 角色：`tester`（第 10 阶段）｜工作目录 `K:\work\project\pixo`（Windows / PowerShell **5.1**）
> 状态：**进行中** —— §0 预备节已落（判据证据，**保号不删**）；第 1~9 节待 Wave2/Wave3 齐备、队长通知后统一执行填入。
> 依据：`.agent-team/test-plan-r22.md`（本报告逐条对应其 §1~§7）、`.agent-team/design-r22.md`（唯一验收依据）
> 红线：全量 **≥1574 passed / 0 failed**；金样本既有 21 features 逐位零漂移
> 纪律：不改 `src/**`；不提交 git；RAW 渲染与 pytest 严格错峰、单进程串行

---

## §0 预备节（判据证据 · 保号，先落不删）

### 0.1 降噪 A/B 执行状态 = **SUSPENDED**（队长 2026-09-10 指令，立即生效）

| 项 | 状态 |
|---|---|
| 全量 A/B 渲染（32 张 ×2 次全幅 ≈78min） | **未执行**（未烧预算）；队长拍板判据口径后再跑 |
| 暂停原因 | 判据 `noise↓≥30% 且 detail↓≤10%` 疑似**本身不可判定**（见 §0.2），队长正在向用户拍板三选一：解耦指标 / 下调阈值 / 能力+默认关+记债 |
| 已就绪（通知即可跑） | 语料清单 `.artifacts/r22-noise-ab/corpus-iso.json`（32 张 + 逐张 EV）；分块调用模板与结果表模板（`test-plan-r22.md §2.3`）；串行/错峰纪律已固化 |
| 依赖关系 | A/B 的**证据面不依赖 Wave2 交付**（仅取数脚本需 super-dev 的 F02 脚本）；暂停纯因判据未定 |

### 0.2 判据证据：`noise_ratio` 与 `detail_score` **同源耦合**（保号）

**指标定义**（`src/pixo/vision/measure.py:287-307`，逐字口径）：

```
lap_raw      = var(Laplacian(gray, CV_64F))                 # gray = u8 灰度
d            = lap_denoised = var(Laplacian(medianBlur(gray,5), CV_64F))
noise_ratio  = clip((lap_raw − d) / max(lap_raw, 1e-6), 0, 1)  =  1 − d / lap_raw
detail_score = d
```

⇒ **两轴不是独立指标**：`noise_ratio` 只由 `d / lap_raw` 之比定义，而 `detail_score` 就是 `d` 本身 ⇒ 任何去噪动作同时移动分子与分母，**两者在同一次去噪里耦合**。

**数据**（`.artifacts/r22-f02-spike/spike_report.json`，**全幅 4040×6064**，DSC_5314，baseline `r0 = 0.97` / `d0 = 6.5`；`R = lap_raw`，`R1/R0` 由 `(d1/d0)·((1−r0)/(1−r1))` 反推）：

| 变体 | `noise_ratio↓` | `detail_score↓` | 反推 `R1/R0` | `R`（lap_raw）↓ | 判据 `≥30% 且 ≤10%` |
|---|---|---|---|---|---|
| bilateral `preserve=0.00` | 23.61% | **66.46%** | 0.0388 | **96.11%** | ❌（detail 侧） |
| bilateral `preserve=0.25` | 6.62% | **58.92%** | 0.1308 | 86.92% | ❌（双侧） |
| bilateral `preserve=0.50` | 2.11% | **45.69%** | 0.3226 | 67.74% | ❌（双侧） |
| guided `preserve=0.00` | 12.22% | **75.69%** | 0.0491 | 95.09% | ❌（双侧） |
| gaussian（参考） | 29.65% | **79.85%** | 0.0190 | 98.10% | ❌（detail 侧，noise 亦差 0.35pp） |

**判据是否可判定的充要式（本报告给出的定量推导）**

记 `r0 = 1 − d0/R0`。要求 `r1 ≤ 0.7·r0` 且 `d1 ≥ 0.9·d0`：

```
r1 ≤ 0.7 r0  ⇔  1 − d1/R1 ≤ 0.7 (1 − d0/R0)
             ⇔  d1/R1 ≥ 0.3 + 0.7·(d0/R0)
再代入 d1 ≥ 0.9 d0  ⇒  R1 ≤ 0.9·d0 / (0.3 + 0.7·(1−r0))
又 R0 = d0/(1−r0)  ⇒  【R1/R0 ≤ 0.9·(1−r0) / (0.3 + 0.7·(1−r0))】
```

`r0 = 0.97` 代入：`R1/R0 ≤ 0.9×0.03 / (0.3 + 0.7×0.03) = 0.027/0.321 = **0.0841**`
⇒ **`lap_raw`（raw 高频能量）必须下降 ≥ 91.6%，而 `d`（中值滤波后高频能量）只能降 ≤ 10%。**

**实证对照**：最优变体（bilateral `preserve=0.00`）已把 `R` 砍到 **3.88%（↓96.11%）——超过 91.6% 的要求**，但 `d` 同幅下跌 **66.46%** ⇒ 失败点**只在 detail 侧**。而 `R` 与 `d` 是同一张图的高频能量统计 ⇒「砍掉 91.6% 的 `R`、同时 `d` 稳住 ≥90%」在本指标对下**不可得**。

⇒ **结论（证据层，非实现结论）**：CR-07 的「`noise_ratio`↓≥30% **且** `detail_score`↓≤10%」在高基线 `r0` 图像上**不可判定**，属**判据设计问题**；`super-dev` 的算子实现（bilateral/guided）在 `R` 侧指标上甚至**超额**达标。

**边界与诚实标注（影响拍板路径，务请连同结论阅读）**

1. 上式对**任意**图像与口径成立（只依赖 `r0`），**不依赖** spike 的算子选择；
2. `r0 = 0.97` 来自**解码图**基线；**渲染后全幅导出**（`final_measurement`）的 `r0/d0` **本轮尚未测量**——而这正是 A/B 的正式口径；
3. `r0` 越低判据越宽松：`r0 = 0.5` 时要求退化为 `R1/R0 ≤ 0.69`（**可判**）；`r0 = 0.6` → ≤0.62；`r0 = 0.97` → ≤0.084（**不可判**）。**判据可判定性完全由渲染后基线的 `r0` 决定**；
4. ⇒ **低成本建议**：拍板前先做**单张 2 次全幅渲染探针**（off/on，≈3–5min）取渲染后 `r0/d0`，代入上式即知判据可判定性；**远优于先烧 78min 再发现不可判**。若队长采纳，我可立即执行该单张探针（不改 `src/**`）。

### 0.3 语料独立复算 + ISO 口径勘误过程记录（队长已采纳）

| 项 | 命令 / 证据 | 结果 |
|---|---|---|
| 语料独立复算（**非转述**） | `.agent-team/tmp-r22t-iso-corpus.py`（生产 EXIF 路径 `pixo.meta.extract`，765 个 NEF）→ `.artifacts/r22-noise-ab/corpus-iso.json` | `NEF=765`、`parse_failed=0`、`ISO≥1600=36`、**`ISO≥3200=32`**；直方图与 exploration §1.5 **逐档一致**（100:8,125:202,200:102,320:240,800:99,3200:12,5000:5,6400:11,8000:2,12800:2 …） |
| **口径勘误（过程记录，防后人再踩）** | 实测源码 `src/pixo/meta/exif.py:452-457` | exploration §1.5 表述「`:457` 归一化为 `meta["iso"]`」**不准确**：ISO 实际在 **`meta["exposure"]["iso"]`**。**首版探针按顶层 `meta.get("iso")` 取键 ⇒ 765/765 全部得 `iso=-1`，输出「`ISO≥3200 = 0`」（假 0 命中）** —— 若不复核即会误判「语料不足、A/B 无法做」。修正取键层级后复跑得 32。**教训**：①探针取键层级必须读**字典组装处**核实，不采信报告转述；②「0 命中」先当**嫌疑**再当结论。 |
| 32 张 EV 清单（供 A/B 记 EV，A7 要求） | 同 `corpus-iso.json` | 含 `shutter/fnumber/program`；**欠曝警示帧**：ISO6400 的 `DSC_5292/5293/5295=1/800s`、`DSC_5294=1/640s`；ISO3200 的 `DSC_5260–5264=1/640s`；其余 1/15s–1/400s |

### 0.4 Wave1 复算达成项（不依赖判据与 Wave2）

| 项 | 命令（`cd K:\work\project\pixo`） | 输出关键行 | 结论 |
|---|---|---|---|
| 4 个关键单测复算 | `cmd /c "set PYTHONIOENCODING=utf-8&&python -m pytest tests/unit/test_noise_metric_keys.py tests/unit/test_qc_soft_warnings.py tests/unit/test_render_degradation.py tests/unit/test_metrics_for_decide_public.py -q > .agent-team\tmp-r22t-recompute-1.txt 2>&1"` | **`53 passed in 24.61s`**（14+15+10+14） | ✅ 与 dev 自述逐文件吻合；`test_metrics_for_decide_public.py` 已由 `2 failed` 转 **0**（A8 兑现） |
| 金样本基线规模 | `manifest.json` / `gate_cases.py:25-42` | `21 features`、`reviewer` 非 pending | ✅ 与 design §4 一致 |
| 当前工作树 | `git status --porcelain` | Wave1 全落 + Wave2（F04 测试 `test_f04_param_fence.py`/`test_f04_f05_injection.py`、F02 spike）在途 | 归因基线已记录 |

### 0.5 待执行批次（等队长通知；A/B 待判据拍板）

| 批 | 内容 | 状态 |
|---|---|---|
| B1 | **降噪 A/B 全量**（32 张 ×2 全幅） | **SUSPENDED**（判据待拍板；可选先跑「单张探针」取渲染后 `r0`，见 §0.2 边界-4） |
| B2 | F04 安全矩阵（越界→400 / 正向可写）+ `test_f04_*.py` | 待 Wave2 通知 |
| B3 | F02 定向（`test_denoise_*`）+ DLL 版本门/快照对拍 | 待 Wave2 通知 |
| B4 | F08 判据命令 `pytest tests/unit/test_skin_oklab.py tests/regression/test_gate_golden.py -q` | 待通知 |
| B5 | F07 grep + F10 台账（含**破坏性证伪**） | 待 Wave3 通知 |
| B6 | F09 几何专项 + 同步面 + 一致表达式（待 dev-geom） | 待通知 |
| B7 | 金样本 J1~J4（21 features 零漂移 + compose case 首次生成） | 待 Wave2/Wave3 |
| B9 | 全量回归 `pytest tests -q -m "not e2e"`（红线 ≥1574/0） | 待通知（A/B 结束后） |

---

## 1. F-ID 验收结果（F01~F10）— *待执行填入*

## 2. 金样本门禁 — *待执行填入*

## 3. 几何专项（F09）— *待执行填入*

## 4. 降噪 A/B（F02/A13）— *待判据拍板后填入*

## 5. F03 / F04 / F06 专项 — *待执行填入*

## 6. 全量回归（≥1574 passed / 0 failed）— *待执行填入*

## 7. 缺陷 — *待执行填入*

## 8. 遗留问题 / 移交 — *待执行填入*

## 9. 证据索引（命令 → 文件）— *待执行填入*
