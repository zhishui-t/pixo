# 感知质量门禁提案（tech_debt #7 评估材料，F19，只提案不实施）

- 任务：F19（Wave1 并行）· 输入：`docs/tech_debt.md:61-65`、`scripts/ab_vs_camera_thumb.py`、`.artifacts/` 评估报告、`tests/regression/test_gate_golden.py`
- 方法：只读盘点 + 既有评估数据取证；**不做决策**，阈值均为「从现有数据推导的建议值」，最终口径由队长/用户定
- 日期：2026-09-07

---

## ① 现状：gate 口径 vs 感知维度的差距

### 1.1 现有 gate 到底锁什么（文件:行）

| 层 | 机制 | 口径 | 来源 |
|---|---|---|---|
| L2 golden | 17 个合成 case，sha256+逐位比对 | 确定性路径逐位；cv2 路径 max\|Δ\|≤1e-6；8-bit ≤1/255 | `tests/regression/test_gate_golden.py:73-75`、`FUNCTION_GATE_SPEC.md §6`（:293-300） |
| L3 e2e | 预览 vs 全质量 / native vs python / 参数单调性 | p50≤2/255、p99≤10/255（1024 档）；f32≤1e-6；RAW_PATH 缺失 skip | `FUNCTION_GATE_SPEC.md §7`（:295-307）、`tests/regression/test_gate_e2e_ab.py:17-19` |
| L2 标定敏感 | exposure_cal_auto / warmth_cal_auto 触达正式标定表 | 换表 hash 必变 | `.artifacts/gate_calibration_coverage.md` §2 |
| 相机参照对照 | **无** | `scripts/ab_vs_camera_thumb.py` 是手工脚本，不在任何 gate 内 | 下节盘点 |

**差距的本质**：现有全部层回答的是「这次改动是否改变了输出 / 是否与基线一致」，没有任何层回答「默认渲染离相机观感有多远、这个距离是否劣化」。两层缺口相互叠加：
- L2 金样本是合成图、且经实测对**运行时分派级变化零敏感**（翻转 4 个 Stage 缺省后 `test_gate_golden.py` 全绿）——`oklch_default_eval.md:69-76` 自己命名为「守卫盲区」；
- L3 的 A-B 是「我们自己 vs 我们自己」（预览 vs 全质量），无外部真值锚。

### 1.2 `scripts/ab_vs_camera_thumb.py` 能力盘点（78 行）

| 能力 | 位置 | 状态 |
|---|---|---|
| 相机内嵌缩略图提取（JPEG/RGB）+ EXIF 逆旋转 | `ab_vs_camera_thumb.py:13-30` | 可用 |
| ΔE 计算：**CIELAB ΔE76**（cv2 LAB 欧氏范数），非 ΔE2000 | `:33-34,42-43` | 可用但口径与评估线不一致（见风险 §3） |
| 指标：dE mean/p50 + dL/da/db 均值 + clip_hi/clip_lo 双侧占比 | `:44-53` | 可用；clip/中性轴指标与 tech_debt #9 验收口径同族 |
| 默认 5 张回归样张 + 高调缺口线 | `:63-68` | 语料路径硬编码为 `<corpus>/...` 占位（本机不存在则打印 missing），**不可移植** |
| b=0.25 调整变体对照 | `:76-78` | 仅演示用途 |
| 产物落盘 / JSON / 退出码 | 无 | **缺失**——纯 stdout，无 gate 接口 |
| DCP 选择：`resources/dcp` glob 排序取第一个 | `:60` | 脆弱（增删 DCP 文件会静默换基准） |

### 1.3 7 维美学评分器能力盘点

- 维度：overall / quality / composition / lighting / color / depth_of_field / content（`src/pixo/vision/aesthetic.py:19-27`）；权重在盘 `resources/models/aesthetic/aesthetic_scorer.pt`；torch 为**懒加载可缺席**（`aesthetic.py:74`，不在 `requirements.txt`/`requirements-dev.txt` 中，实测两文件均无 torch）。
- 接线：loop 美学维度（`src/pixo/pipeline/loop.py:659-695,743-761`）+ batch 选片（`src/pixo/pipeline/batch.py:72-132,223-252`，缺省 MockAestheticScorer）。
- **分布标定已完成且有硬结论**（`docs/metrics/scorer_distribution.md`）：
  - 实拍域 overall：p25=−0.63 / p50=−0.41 / p75=−0.16；**带符号原始分**，「绝对阈值必须以本表经验分布为准」；
  - 文档化推荐：accept_threshold ≈ **−0.4**、stagnation_eps ≈ **0.1**（loop 采纳语义，非 gate 阈值）；
  - 冷启动 15.8s、稳态单张 ~20ms；
  - **t98 关键结论**：合成域退化阶梯 Spearman ρ=0.03、非单调——「域内相对排名只宜作弱参考，不得作硬性质检门槛」；t58 制度化「跨域禁比」。tech_debt #11（`docs/tech_debt.md:100-105`）同结论。
- 推论（对提案直接构成约束）：**评分器作为 gate 只能作用于真实语料层，且只能作回归带（paired 对照），不能作绝对分数线**。

### 1.4 可复用的评估基建（零新增依赖即可达）

- ΔE2000（Sharma 2005，含 `--selftest` 文献对自检）：`scripts/eval_rp_ccm_ab.py`，已被 `scripts/ab_intent_compare.py:59`、`scripts/hsm_oklch_eval.py:47` 复用 import；
- 语料级评估先例：hsm_oklch_eval 54 张 @512/stride3 全程 257s（三轨）；rp_ccm_ab 54 张双轨；
- RAW_PATH 缺失即 skip 的豁免纪律：`tests/regression/conftest.py:15`、`test_gate_e2e_ab.py:5-8`。

### 1.5 阈值标定可用的现有数据（.artifacts 取证）

| 数据 | 数值 | 含义 | 来源 |
|---|---|---|---|
| **默认路径（DCP A 轨）vs 相机参照** | ΔE2000 median **5.946** / p95 **15.928**（54 张，曝光增益对齐，窗 [0.01,0.90]，512/stride3） | 现状基线：**默认渲染现在就离相机 ~2.6 JND（median）** → 绝对 JND 上限线一立就红，只能立回归带 | `eval_rp_ccm_ab_nikon_z5_2_20260904_235522.md` §总体 |
| 同报告逐照片分布 | A 轨 median 4.036~10.618（跨照片极差 ~6.6） | 阈值必须逐照片冻结基线，不能只锁池化值 | 同上 §分照片 |
| huesat 开启轨 vs 相机 | A↔R median 20.257 / p95 31.228 | look 语义差异量级（Adobe look ≠ 机内链路），证明**风格化渲染不能进绝对 ΔE 门** | `hsm_oklch_eval.md:14` |
| JND 口径 | 两套并存：JND=1.0（`ab_intent_report.md:8`「p95 地板 1.0 = JND」、`stage1_qa_verdict.md:48`）vs JND=2.3（`calib_run.md:67`「1 JND (2.3)」、`hsm_oklch_eval.md:12` 10.890=4.73 JND） | **口径冲突，提案落地前需统一**（本文以 2.3=严格 / 1.0=宽松并列给出） | 见来源列 |
| 既有转默认验收线建议 | median 改善 ≥15%、无单照片 median 回归 >1 JND、总体 p95 不劣化、≥2 相机复验 | 仓库内已有的「回归带」先例，可直接移植为 gate 口径 | `stage1_qa_verdict.md:51` |
| clip/中性轴预算 | clip_hi ≤2.5%、\|dL\| ≤4、da/db ±6 | tech_debt #9 标定验收已用的感知预算，clip 通道可直接沿用 | `docs/tech_debt.md:70,77-79` |
| 评分器回归带素材 | 实拍 overall p75−p25=0.47；head 输出粒度粗（stagnation_eps 建议 0.1） | paired 回归带建议 ±0.15/照片、池化 ±0.10 | `scorer_distribution.md` §阈值建议 |

---

## ② 方案选项（三条路线）

### 路线 R1：ΔE 相机参照回归带（硬门禁，默认路径专用）

**口径定义**：
- 新增 L3.5 层 gate case（marker `gate` + `gate_e2e_camera`，沿用 RAW_PATH 类豁免纪律），输入 = 冻结语料清单（建议直接采 `exports/auto/full_scan` 54 张，机器本地盘路径经环境变量注入）；
- 渲染：`render_preview_full(long_edge=512)` 中性参数（**默认链，不开 huesat、不挂风格卡**）；
- 参照：RAW 内嵌缩略图 + EXIF 逆旋转（复用 `ab_vs_camera_thumb.cam_thumb`）；
- 指标：ΔE2000（复用 `eval_rp_ccm_ab.delta_e_2000`）逐照片 median/p95 + 池化值 + dL/da/db + clip_hi/clip_lo（复用 ab 脚本口径）；曝光增益对齐沿用 `calibrate_to_camera` 口径（与既有报告可比）；
- 基线：逐照片 54 行数字冻结入仓（JSON + reviewer 签注，照搬 golden manifest 的双签纪律，`test_gate_golden.py:39-41` 先例）。

**阈值建议（从 §1.5 数据推导）**：
| 项 | 建议线 | 依据 |
|---|---|---|
| 池化 median | ≤ 基线 ×1.15（5.946 → 6.84） | stage1 验收线「median 改善≥15%」反向用 |
| 逐照片 median 回归 | ≤ +1 JND=**2.3**（严）/ +**1.0**（宽） | `calib_run.md:67` vs `ab_intent_report.md:8`；两套口径需先拍板 |
| 池化 p95 | 不劣化 >5%（15.928 → 16.7） | rp 报告 B−A p95 波动 +4.9% 为自然噪声带 |
| clip_hi / \|dL\| | ≤2.5% / ≤4（每照片） | tech_debt #9 已清偿条目的同族预算 |
| 抖动余量 | 逐照片 median 自然抖动建议实测 3 次取极差后收紧 | 本提案未做重复性实测（**推测**，置信度中：rawpy/cv2 版本漂移是主要源） |

**计算成本**：54 张渲染 @512 ≈ 1.5-3 min + 缩略图解压 54×~1.3s ≈ 70s + ΔE2000 计算（stride3 抽样）可忽略 → **gate 时长 +3-6 min，仅 RAW 语料在位时**；CI 无语料环境 skip 不增时长。当前全量回归 189s（`gate_report.md:61`）/338.8s（`gate_calibration_coverage.md`）→ 全绿环境下变 6-12 分钟级。零新增依赖（numpy/cv2/rawpy/exifread 均已在 `requirements.txt`）。

### 路线 R2：美学分数回归带

**口径定义**：同一 R1 语料 harness 上，对每张默认渲染算 7 维分；冻结逐照片基线；gate 断言 = 逐照片 |Δoverall| ≤ **0.15** 且池化 median 漂移 ≤ **0.10**（依据：head 粒度粗 → stagnation_eps 0.1；实拍 IQR 0.47 的 1/3 作带）。

**硬约束（来自 §1.3）**：只能作 **paired 回归带**，不能作绝对分数线（accept_threshold −0.4 是 loop 采纳参数不是 gate 线）；**合成样本不可用**（ρ=0.03）；跨域禁比。

**计算成本**：稳态 54×20ms ≈ 1s + 冷启动 15.8s（常驻实例可摊薄）；**但环境前提是 torch 在位**——当前 `requirements*.txt` 无 torch，评分器懒加载缺席即返 None（`aesthetic.py:74`）。故 R2 落地必须二选一：① 加 optional extra（`pip install pixo[gate-aesthetic]`）+ torch 缺席时 skip（与 RAW_PATH 同纪律）；② gate 环境预装 torch。另需补 CLIP backbone 权重许可核验注记（`aesthetic.py` docstring 自述「MIT 类许可，需自行核验」——F16 合规包素材）。

### 路线 R3：双通道（ΔE 硬门 + 美学软通道）

- R1 硬门禁原样；R2 降级为**报告通道**（JSON 落盘 + 超带打 WARN 不断言），积累 2-3 个批次数据后再议升硬；
- 产出形态：单脚本（建议 `scripts/gate_camera_ab.py`，gate 模式复用 ab_vs_camera_thumb 的提取/指标函数）+ JSON artifact + pytest 包装 + 基线冻结双签。

---

## ③ 风险：误报 / 漏报面

### R1（ΔE 硬门）

| 面 | 机理 | 缓解（供选项） |
|---|---|---|
| 误报：look 语义差异 | 默认 DCP 即 Adobe look，median 5.9~6.9/照片；huesat 类 look 开启时 15~32（`hsm_oklch_eval.md:14`） | 门只锁默认链；风格卡/huesat 渲染**排除在硬门外**（其 ΔE 大是设计意图：split_tone 扇区内 ΔE 14.5-21.4，`ab_intent_report.md:48-49`） |
| 误报：逐照片分布宽 | A 轨逐照片 median 4.0~10.6 极差 6.6（rp 报告 §分照片） | 逐照片冻结基线而非只锁池化值 |
| 误报：环境漂移 | rawpy/cv2 版本、缩略图 JPEG 质量、WhiteLevel 处理差异（Nikon 15892 特例，`src/pixo/render/core/io.py:352-358`） | 基线冻结时锁定依赖版本指纹（golden manifest 的 fixture 指纹先例，`FUNCTION_GATE_SPEC.md §6`） |
| 误报：口径混用 | ab 脚本 ΔE76 vs 评估线 ΔE2000 数值不可互换 | 统一 ΔE2000；ΔE76 仅作脚本内辅助打印 |
| 漏报：抽样盲区 | stride=3 只看 1/9 像素，局部 artifact（边缘振铃/坏点簇）可能漏检 | 局部结构问题由 L2/L3 既有像素层门兜底，本门定位「全局观感漂移」——分层互补而非重复 |
| 漏报：增益对齐掩盖曝光漂移 | 均值比对齐会把全局曝光变化对消 | 保留未对齐 dL 辅助守卫（预算 ±4） |
| 漏报：覆盖面 | 语料单相机（Nikon Z5）+ 有限场景；机器本地语料 → CI 恒 skip（与 L3 同一的空档） | 新相机语料补采属运营项；CI 侧可加「语料在位率」心跳上报（选项，非本提案范围） |

### R2（美学回归带）

| 面 | 机理 |
|---|---|
| 误报：跨域 | 合成/低纹理图分数不可比（t58 跨域禁比；t98 ρ=0.03）——**合成 gate 样本上此通道必须禁用** |
| 误报：绝对线 | 带符号分、12 张实拍全负（`scorer_distribution.md`），沿用 −0.4 作 gate 线会大面积误杀 |
| 漏报：退化不敏感 | 同场景退化阶梯打分非单调（σ4 得分反高于纯净样）——真实质量退化可能不触发 |
| 漏报/误报：风格卡 | 逐卡分数基线不存在（现有分布数据全是默认渲染）；风格卡渲染带未知 → 若套同一带宽必然噪声 |
| 环境误报 | torch 缺席/版本漂移、CLIP 权重缺席（懒加载返 None）→ 需显式 skip 语义而非静默 0 分 |

### R3

继承 R1 全部 + R2 的漏报面（软通道不阻断）；新增成本是报告信噪比管理（WARN 通道要避免狼来了）。另注意 L3 现有「RAW_PATH 单张」用例与本提案「语料批量」是两个规模，需避免命名/豁免语义混淆（`test_gate_e2e_ab.py:6-8`）。

---

## ④ 建议与工作量估算（供队长/用户决策）

**建议（非决策）**：取 **R3 分期**——第一期只做 R1（ΔE 回归带硬门，默认链、真实语料、逐照片冻结基线），它直接关闭 `oklch_default_eval.md:74-76` 点名的「分派级变化金样本零观测」盲区，且零新增依赖、复用三件现成资产（ΔE2000 自检实现 / 语料评估脚本骨架 / golden 双签纪律）；第二期把美学维度接成 WARN 软通道；**不建议**美学分数作硬门禁（ρ=0.03 + 带符号分布 + 粒度粗三重证据不足）。

**工作量估算（人日，估算档位：粗粒度 ±50%）**：

| 项 | 内容 | 估算 |
|---|---|---|
| R1 | gate 脚本（gate 模式 + JSON 落盘 + 语料环境变量化）+ 54 张基线冻结与 reviewer 双签 + pytest case（marker/skip 纪律）+ FUNCTION_GATE_SPEC §7 增补 + tech_debt #7 注记 + ΔE 口径统一说明 | **1.5-2 人日** |
| R2（软通道） | 同 harness 接评分器（常驻实例预热）+ WARN 语义 + optional extra 与 torch 缺席 skip + CLIP 权重许可核验注记（联动 F16） | **+1 人日** |
| 前置杂项 | JND 口径统一拍板材料（1.0 vs 2.3 并列呈报）；ab_vs_camera_thumb.py 硬编码路径与 DCP glob 脆弱性顺手修正 | **+0.5 人日** |
| 合计（R3 分期） | 第一期 R1 + 前置；第二期 R2 | **2.5-3.5 人日** |

**决策问题清单**：
1. JND 取 1.0 还是 2.3（决定逐照片回归带宽，严/宽差 2.3 倍）；
2. 语料在位率：gate 语料盘（K:\data\photo）是否作为开发机常驻前提，CI 侧接受恒 skip；
3. 美学通道最终定位（软报告 / 升硬 / 不做）——建议待 R2 软通道积累 2-3 批次 paired 数据后再议；
4. 基线冻结的 reviewer 双签是否沿用 golden manifest 纪律（建议沿用）。

---

## 来源清单

**仓库（文件:行）**：`docs/tech_debt.md:61-65,70,77-79,90-105`；`scripts/ab_vs_camera_thumb.py:13-30,33-34,42-53,60,63-78`；`tests/regression/test_gate_golden.py:39-41,73-75`；`tests/regression/test_gate_e2e_ab.py:5-8,17-19`；`src/pixo/render/docs/FUNCTION_GATE_SPEC.md §6(:293-300) §7(:295-307)`；`src/pixo/vision/aesthetic.py:19-27,74`；`src/pixo/pipeline/loop.py:659-695,743-761`；`src/pixo/pipeline/batch.py:72-132,223-252`；`src/pixo/render/core/io.py:352-358`；`requirements.txt`、`requirements-dev.txt`（均无 torch）。

**评估数据（.artifacts 与 docs/metrics）**：`eval_rp_ccm_ab_nikon_z5_2_20260904_235522.md`（默认路径 ΔE 基线 5.946/15.928 + 逐照片分布）；`hsm_oklch_eval.md:12-14,26-83`（JND=2.3 口径、A↔R 20.257、逐照片 15-32）；`ab_intent_report.md:8,48-58`（JND=1.0 口径、扇区/误伤数据）；`stage1_qa_verdict.md:48,51`（转默认验收线先例）；`calib_run.md:67`（1 JND=2.3）；`scorer_distribution.md`（七维分布、accept/stagnation 建议值、合成域 ρ=0.03、冷启动/稳态耗时）；`gate_report.md:61`（1231 tests/189s）；`gate_calibration_coverage.md`（338.8s、标定敏感 case 先例）；`oklch_default_eval.md:69-76`（金样本分派盲区）。

**明确标注的推测**：逐照片回归带的环境抖动幅度未实测（§R1 缓解行，置信度中）；「CI 无语料恒 skip」的运营接受度未与用户确认（§④ 问题 2）；工作量估算为粗粒度 ±50%。
