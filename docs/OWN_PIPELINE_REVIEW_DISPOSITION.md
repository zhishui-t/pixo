# 外部评审意见处置表（12 条）

- 日期：2026-09-04 · 执行：qa（长安）
- 核对基准：commit `3fbe56d`（新表入库批）+ 工作树在途批次（t40 patch 闸门 oklch 校验、标定 gate case 补缺、scorer 守卫测试——处置表内如实区分"已提交"与"在途"）
- 纪律：每条结论附证据链接（源码 文件:行号 / 测试名 / 报告路径），全部经本轮逐条实证，不凭印象判。
- 汇总：**已达成 6（②⑥⑦⑨⑩⑫）· 部分达成 5（③④⑤⑧⑪）· 驳回 1（①）**；backlog 登记 4 项（③④⑤⑧，已写入 `docs/tech_debt.md` §13）。

| # | 意见摘要 | 处置 |
|---|---|---|
| ① | cbrt 用多项式/Remez 逼近 | **驳回** |
| ② | (a,b) 向量空间避免 hue 环绕 | **已达成**（等价实现） |
| ③ | UI 滑杆非线性传递函数 | **部分达成** → backlog P3 |
| ④ | RP-CCM 拟合 Tikhonov/线性回退罚 | **部分达成** → backlog（条件触发） |
| ⑤ | ±1EV 压力测试 | **部分达成** → backlog |
| ⑥ | 软代理 + 前向硬验证 | **已达成**（强于建议） |
| ⑦ | 分阶段预热 + Hessian 监控 | **已达成**（监控项有实证豁免理由） |
| ⑧ | 参考图低频加权去 ISP 风格 | **部分达成** → backlog |
| ⑨ | 评分器始终接 sRGB | **已达成**（守卫测试在途） |
| ⑩ | 规则引擎语义迁移审查 | **已达成** |
| ⑪ | LLM patch 闸门 oklch 范围校验 | **部分达成**（t40 在途收口） |
| ⑫ | 里程碑拆分 | **已达成** |

---

## 逐条实证

### ① cbrt 多项式逼近 —— 驳回

**理由**：cbrt 选型目标是与 numpy **位对齐**而非性能，换 Remez 会直接打破 native↔Python 逐位等价硬门；评审未提供任何 profiling 依据。

证据：
- `src/pixo/render/native/src/oklab.h:12` — 头注释明言选型理由："pow/cbrt 走 CRT (api-ms-win-crt-math -> ucrtbase), 与 numpy 同一实现"；
- `src/pixo/render/native/src/oklab.cpp:104-107` — 正向 `std::cbrt`（注释"与 np.cbrt 同 CRT 实现"）；`:140-144` — 逆向立方用 `std::pow(x,3.0)` 并注释"三次连乘会有 1 ULP 级差异, **禁止改写**"；
- `src/pixo/render/core/oklab.py:116` — Python 侧 `np.cbrt` 同源对应；
- `tests/unit/test_native_oklab.py:37-48` — `_assert_bits_equal`：float 按 uint32/64 **位型视图**比较（非 allclose），换任何近似多项式必红；`:67-84` 随机 100 万像素正逆向逐位、`:91-101` 33³ 网格双向、`:104/:117` 边界/越域；10 个测试全过（`.artifacts/stage1_qa_verdict.md:23`）；
- profiling 证据：**未找到**（全仓搜 "profil/perf/热点/hotspot" 与 cbrt 同现 0 命中；`docs/OWN_PIPELINE_STAGE1_DESIGN.md` 中 cbrt 仅谈数值语义）。评审建议缺少成立前提。

### ② (a,b) 向量空间避免角度环绕 —— 已达成（等价实现）

实现以"环状角距 + 余弦窗"达成与建议等价的环绕免疫，且 hue 重建/移位在向量语义上闭环：

- `src/pixo/render/core/hsl.py:60-69` — `_ring_mask`：`diff=(h-center)%360` 取环状角距 `min(diff, 360-diff)` + 升余弦窗，docstring"0/360 环绕连续 C1"；被 hsv（:99）、oklch（`hsl_oklch.py:136`）、usercal 三链路复用；
- `src/pixo/render/core/oklab.py:158-164` — `oklch_to_oklab` 以 `C·cos/C·sin` 向量式重建 (a,b)（"任意实数角度可入"）；`:152-154` — atan2 取 hue 后 `%360` + 360.0→0 折回（负角/浮点 mod 伪影显式处理）；
- 环绕测试 4 项：`tests/unit/test_hsl_oklch.py:125-133`（348° band +20° shift → 结果 ≈8°±0.5，无跳变）、`tests/unit/test_oklab.py:156-163`（361°≡1°、368°≡8°，atol 1e-9）、`tests/unit/test_hsl.py:95-98`（0/360 端点掩码一致 <1e-6）、`tests/unit/test_usercal.py:100-110`（center=0 时 1°/359° 对称处理）。

### ③ UI 滑杆传递函数 —— 部分达成 → backlog P3

- 已做：OKLCh 双刻度 + 色度锚点（显示层）——`frontend/src/theme/oklchScale.ts:46-49`（表 B 12 锚点，内核实测冻结）、`:60-101` 双向分段线性插值、`:104-119` 副刻度数据；`HueRing.tsx:179-184` 色相环双刻度；`HueSpectrumBar.tsx:76-88` 谱轨副尺；`HslBandRow.tsx:161-167` 色度 C 五档 marks（0 档"原色"加粗）。
- 差距：滑杆→参数值**线性直传**（`SliderParam.tsx:139-145`，commit 仅 clamp 无映射 `:71-75`）。
- **重要背景**：`docs/UI_OKLCH_SPEC.md:61` 有显式反向决策——"提交给后端的数值永远是当前域的原始角度，不做任何换算"（锚点插值仅显示）；感知均匀策略 = 切 OKLCh 域本身 + 内核 tanh 软限幅（spec :18），而非滑杆曲线。
- backlog 采纳前置条件：须先修订 UI_OKLCH_SPEC.md:61 既有决策（否则与设计冲突）。已登记 `docs/tech_debt.md` §13-1。

### ④ RP-CCM Tikhonov/线性回退罚 —— 部分达成 → backlog（条件触发）

- 已做的数值防护：
  - 99% 分位残差单轮裁剪：`scripts/fit_rp_ccm.py:164-186`（`robust_fit`）；`:166-171` docstring 实证记录**更激进裁剪反而加剧病态**（系数 ±23→±62）——可直接回应评审"为什么不是 95%"；
  - 逐照片 EV 增益对齐：`scripts/fit_rp_ccm.py:227-228`（标量 gain 对齐 + `:237` log2 记档）；评估同口径 `scripts/eval_rp_ccm_ab.py:193-194`；G-5 同式 `scripts/calib/optimize.py:743,756-757`；
  - 秩亏防护：`src/pixo/render/core/rp_ccm.py:215`（lstsq `rcond=None` 最小范数解）；G-5 用 Huber robust 损失（`optimize.py:767`）。
- 未做：Tikhonov/Frobenius 罚（全仓 `ridge|tikhonov|frobenius|penalty` 于拟合路径 0 命中；`optimize.py:324-341` 罚项字典无 rp_matrix 项）；线性回退罚（`identity_rp_ccm` 存在于 `rp_ccm.py:152-156` 但拟合侧零调用，无"残差超阈值→退恒等/线性"逻辑）。
- backlog 触发条件：新相机语料回归簇再现时启用（当前 NIKON Z5_2 端到端 54/54 改善零反转，无病态迹象）。关联在途：标定 gate case（`exposure_cal_auto`/`warmth_cal_auto`，工作树在途）落地后，换表/病态系数可被金样本感知。已登记 §13-2。

### ⑤ ±1EV 压力测试 —— 部分达成 → backlog

- 已做：曝光不变性单测——`tests/unit/test_rp_ccm.py:136-142` `test_features_scale_exactly_with_exposure`，`k∈{0.25,0.5,2.0,4.0}` 参数化，断言 `f(k·x)=k·f(x)` atol=1e-12（±2EV 即 k∈{0.25,4}）；`:145-156` apply 层 k=2 随机 4096×3 输出比率恒定 rtol 1e-5；文件头 :7-8 引用 Finlayson & Xu 权威出处。
- 未做：语料级 ±EV 偏移压力（确认不存在：`eval_rp_ccm_ab.py:190-194` 的 "ev" 是增益对齐口径非压力项；全 tests/ 搜 "压力/stress/ev_shift" 与 RP-CCM 无关命中）。
- backlog：54 张语料加 ±1EV 全局偏移重跑端到端 ΔE 的压力实验（验证曝光表/warmth 联动在极端 EV 下不崩）。已登记 §13-3。

### ⑥ 软代理 + 前向硬验证 —— 已达成（强于建议）

t30 保真门即该建议的完整实现，且附加了建议没有的每 checkpoint 真值回滚：

- 保真门（先于任何优化，时序实证见 `.artifacts/stage2_qa_verdict.md` §2.1）：`.artifacts/surrogate_fidelity.md` — surrogate vs 真实管线 `render_preview_full` ΔE2000 **median 0.0000 / p95 0.0000**（门限 0.05/0.3），12 张；
- 前向逐位复刻 / 反向平滑（同报告"可微近似"节）：tone LUT 前向最近邻逐位、clip 前向硬 clip、colorcal tint 前向 cv2 u8 逐位——前向与真实链位级一致，平滑只存在于反向梯度；
- 每 checkpoint 真值对照（训练看 proxy、决策看真值）：`.artifacts/calib_run.md` checkpoint 轨迹表（θ0→adam_40…→lbfgs_final 全程真值 ΔE2000）；
- L-BFGS 真值恶化自动回滚：`scripts/calib/optimize.py:919-925`（"proxy 下降 ≠ 真值改善 —— 回滚到 Adam 末点"）。

### ⑦ 分阶段预热 + Hessian 监控 —— 已达成（监控项有实证豁免）

- 已做：Adam(lr=1e-3)×200 预热 → L-BFGS(strong_wolfe)×40 精修（`scripts/calib/optimize.py:38,851-916`）+ 真值恶化回滚（:919-925）。
- Hessian 监控未做的豁免理由：收敛全程单调无异常——`.artifacts/calib_run.md` checkpoint 轨迹 6.658→5.758→5.397→…→4.962→4.244 单调下降、无回滚触发记录；L-BFGS 自带 history_size=50 曲率近似（optimize.py:890-891）。加显式 Hessian 监控无待解问题支撑，不采纳为待办。

### ⑧ 参考图低频加权去 ISP 风格 —— 部分达成 → backlog

- 已做：双侧线性窗 [0.01,0.90] 滤除暗部噪声/高光裁剪区（`scripts/fit_rp_ccm.py:44-46,149-157`；`scripts/calib/optimize.py:613-624` 同式，双侧同窗才留样）；几何对齐（EXIF 逆旋转 `fit_rp_ccm.py:106-121` + INTER_AREA `:141-143`）。
- 未做：低频/模糊/下采样加权（scripts/ 全搜 `lowfreq/lowpass/pyramid/gauss/blur/下采样` 0 命中）；采样为 stride 确定性网格（`fit_rp_ccm.py:152-153`）。
- backlog 备注：当前标定收益 +36.3% 下 ISP 风格残余属 p95 尾部（15.0）治理手段之一，与 L-4（p95 上限）同源。已登记 §13-4。

### ⑨ 评分器始终接 sRGB —— 已达成（建议的守卫测试已被采纳、在途）

- 架构证据：`src/pixo/pipeline/loop.py:972-973` `preview_img = backend.render_preview(...)` 唯一产地 → `:1016` 原变量直传 `_score_aesthetic` → `:710/:715` 零变换透传 `aesthetic_scorer`；管线终检强制 gamma 域→8bit sRGB（`render/pipeline/graph.py:300-304`、`runner.py:55-60` 域校验+量化）；
- 全调用点核对无一处喂中间态：`loop.py:1016`（preview）、`:1298`（full_img=render_full）、`:814`+`smart_crop.py:194`（preview 裁片）、`pipeline/batch.py:710`（item.image_rgb/rawpy 8bit）；模型契约本身 sRGB u8（`vision/aesthetic.py:220-224`）；
- 建议的显式守卫测试：**已在途未提交**——`tests/unit/test_scorer_input_domain.py`（docstring 明言"把外部评审假设固化为回归守卫"），三组断言：域真实生效（两域输出互异且异于关闭基线，防守卫空转）、编码域无关（两域输出 dtype/形状/值域一致）、loop 接线（记录型 scorer 收到的对象与后端产出 `is` 恒等）。

### ⑩ 规则引擎语义迁移 —— 已达成

- 阶段一 A4 审计结论（`.artifacts/stage1_qa_verdict.md:37`）：`_COLOR_PARAM_ALIASES` 仅映射 vibrance/saturation → colorcal（Lab 域增益，与 hsl `color_domain` 无关）；`_DOTTED_PARAM_REGISTRY` 无任何 hsl/split_tone 键（规则侧无域敏感执行位）；规则 yaml 中 split_tone 仅注释模板（strength 为双域同义混合权重）；VibranceStage 为废弃占位。**结论：域变更不影响 decide 环路**。
- 边界条件已登记：G-6（同报告 :62）——阶段二激活 split_tone 规则模板或新增 hue/sat 语义键时须过 color_domain 语义审查（hue 语义跨域不可换算）。

### ⑪ LLM patch 闸门 oklch 范围校验 —— 部分达成（t40 在途收口）

- 既有基础（已提交）：数值有限性（NaN/±Inf 拒，`src/pixo/agent/patch_protocol.py:185-189`）+ schema 驱动带界越界**拒绝而非截断**（:205-224；边界来自 Stage param_schema，`_rng_for` :74-83）+ op 白名单/结构/锁定参数等（:168-203,226-228）。
- 差距（评审指出的）：oklch 域特定合理域校验（如 hue∈[0,360)、色度量纲）原不存在——hsl stage schema 的 bands 无 min/max（`render/modules/hsl.py:24-31`），hue 硬界仅在引擎 `_validate_band`（`render/core/hsl.py:33-36`）。
- **t40 已在途（工作树未提交，+85 行实现 +86 行测试）**：`patch_protocol.py:96-101` `OKLCH_DIMENSION_DOC`（hue∈[0,360)/C 典型 0–0.33/L∈[0,1] 量纲文档）；`:104-134` `_oklch_band_issues`（hue_center 越 [0,360) **硬拒**并命名、saturation |v|>100 语义提示）；`:137-158` 拒绝理由携带域信息；`agent/suggest.py:42-53` 量纲文档拼入 LLM prompt（提示词侧预防）；专项测试 `tests/unit/test_patch_protocol.py:153-227`（380° 硬拒命名/360/-20/"29"/None/True/inf 参数化硬拒/sat=150 仅提示/hsv 域不检/文档嵌入断言）。处置：待 t40 提交后此条可闭为"已达成"。

### ⑫ 里程碑拆分建议 —— 已达成

- 路线图本就分阶段：`docs/PIXO_RENDER_OWN_PIPELINE.md:152-160` §8（M-O1 内核+迁移 → M-O2 → M-O3 RP-CCM → M-D1 可微标定 → M-D2 上线，含前置依赖列）；
- 实际执行比建议更细：M-O1 拆为**内核先行**（t1 native oklab，t19 逐位等价收口）+ **迁移批**（t3/t17，重组映射见 `.artifacts/stage1_qa_verdict.md` §5）；M-D1 拆为**软代理保真门先行**（t30，时间戳先于首跑训练 ckpt——`.artifacts/stage2_qa_verdict.md` §2.1）+ 优化（t32）；M-D2 入库独立成批且分两提交（`bc96a09` 阶段二主体零变化 / `3fbe56d` 入库+修复，见 git log）；
- M-O3 的遗留缺口（压力测试）由本表 ⑤ 承接登记，无失管项。

---

## 时效注记

本表核对期间工作树存在三组**在途未提交**修改（t40 patch 闸门 oklch 校验、标定 gate case 补缺 `gate_cases.py` + `exposure_cal_auto`/`warmth_cal_auto` 金样本、scorer 守卫测试），分别对应 ⑪、④ 关联、⑨ 的收口动作——处置表已按"已提交证据"与"在途证据"区分标注。已提交基准：`3fbe56d`。
