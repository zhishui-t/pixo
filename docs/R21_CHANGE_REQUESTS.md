# R21 后续修改要求（Change Requests）

> 基线：HEAD `58d780b`，工作树干净，`origin/master`（`f357b35`）落后 **43 个提交**。
> 本文所有结论来自本轮实测（文件哈希对拍 / 规则触发探针 / 全仓调用点 grep），
> 并**更正上一轮口述中的一处错误结论**（§0 必读）。

---

## 0. 结论更正：不存在「阶段二新表待入库」这道工序

上一轮说「可微标定的新表躺在 `configs/color/calib_out/` 没入库，生产还在跑旧表」——**这是错的**。
实测哈希对拍（MD5 前 10 位）：

| calib_out 文件 | MD5 | 生产对应文件 | MD5 | 判定 |
|---|---|---|---|---|
| `rp_ccm_nikon_z5_2.json` | `0C10E3C36D` | `configs/color/rp_ccm_nikon_z5_2.json` | `0C10E3C36D` | **已同源** |
| `target_offset.json` | `9BB3A6AA87` | `src/pixo/render/target_offset.json` | `9BB3A6AA87` | **已同源** |
| `z5ii_neutral_trim.json` | `D7B5670171` | `resources/camera_profiles/z5ii_neutral_trim.json` | `D7B5670171` | **已同源** |
| `skin_oklab.json` | `72997E4C` | `configs/color/skin_oklab.json` | `7CC07802` | 生产**更新**（R19 重拟合，多出 `SKIN_OKLAB_*` 常数与椭圆几何字段） |
| `warmth_curve.json` | 9-04 旧版 | `configs/calibration/warmth_curve.json` | 9-08 R20 扩域版 | 生产**更新** |
| `rp_ccm_by_group.json` | `341968C1` | 运行时零引用（仅 `scripts/calib/*` 消费） | — | 实验产物 |

**结论**：`calib_out/` 是陈旧快照（legacy 目录），不是待入库的候选表。原计划里的
「先做阶段二入库」应整条删除；色彩线只剩两条实项 —— CR-12（RP-CCM 未接运行时）、
CR-13（skin OKLab 缺金样本）。

---

## 1. 证据基线（本轮实测，非推断）

| 事实 | 证据来源 | 结果 |
|---|---|---|
| 服务层 decide 规则**零触发** | 探针 `.artifacts/_probe_metric_shape2.py` | 裸 measurement → **0/11 条**，`params={}` |
| 成因①：指标嵌在 `global`/`regions` 下 | `vision/measure.py:574-581` vs `pipeline/loop.py:521-551` | 规则读扁平键，service 传嵌套报告 |
| 成因②：`measure()` 不产 proxies | `vision/measure.py:548`（无 `compute_proxy_metrics`）、仅 `loop.py:1352`/`batch.py:675` 调 | `haze_proxy`/`colorfulness_proxy`/`tonal_range` 在服务路径**根本不存在** |
| `SinglePhotoLoop` 无生产入口 | `grep -r SinglePhotoLoop src/pixo/service` | 仅 `service/loop.py` 纯转发 shim；`app.py`/`runtime.py` 零引用 |
| `DEFAULT_RULES` 未进生产 | `grep -r DEFAULT_RULES` | 消费者只有 `scripts/auto_real_edit.py` + `tests/` |
| `denoise`/`sharpen` 空占位 | `render/modules/reshape.py:113-134` | `wants()` 恒 `False` |
| 美学评分器签名不符 | `pipeline/batch.py:318`（只有 `.score()`）vs `pipeline/loop.py:907`、`render/geometry/smart_crop.py:194`（都按可调用对象 `scorer(...)` 使用） | 注入后每轮静默跳过、选片恒 fallback（测试用 lambda 掩盖） |
| `apply_intents`（LUT/场景唯一注入点）零调用 | `render/pipeline/intents.py:187` | `src/` 内无任何 import |
| RP-CCM 未接运行时 | `grep -r "apply_rp_ccm("` | 调用点只有 `scripts/calib/*` 与 `tests/` |
| 前端 `decidePhoto` 定义了但零调用 | `frontend/src/api/client.ts:157` | 仅定义处 1 处命中 |
| 静默降级面 | `grep -c "except Exception" src/pixo` | **131** 处 |
| 胶片卡资产 | `configs/styles/films/` | 25 个 JSON |

---

## 2. CR 清单

### 战役 A：闭环插电（P0，全部 S/M，风险可控）

#### CR-01 闭环生产入口
- **问题**：`POST /api/photos/{id}/decide` 是单轮空决策（`service/runtime.py:633`）；前端零调用；HTTP 层没有跑完整闭环的入口。
- **变更**：`service/runtime.py` 增 `run_auto_loop(photo_id, ...)` 装配 `SinglePhotoLoop` + `RawRenderBackend`；`app.py` 增 `POST /api/photos/{photo_id}/auto-loop`；**保留** `decide_photo` 原语义（不破坏既有契约）。
- **验收**：新增 `tests/integration/test_loop_wiring.py` —— 同 fixture 下返回 `rule_ids` 非空、`iterations ≥ 2`；curl 手测一次真 NEF。
- **风险**：单请求耗时上升（多轮渲染）→ 限制 `max_iterations` 或走后台任务。

#### CR-02 默认规则注入
- **变更**：由 service 装配层加载 `DEFAULT_RULES`（`PIXO_RULES=off` 可关）；**不**改 `SinglePhotoLoop(rules=None)` 的库层缺省（保持纯库语义）。
- **验收**：装配后同一 fixture 触发 ≥ 1 条规则；单测断言装配层 rules 非空、库层仍为空。

#### CR-03 指标口径单一来源
- **变更**：把 `pipeline/loop.py:_metrics_for_decide` 提升为公共 API（`pixo.pipeline.metrics_for_decide`），service 与 loop 共用；service 侧显式调用 `compute_proxy_metrics` 并合并进 measurement，消灭成因①②。
- **验收**：新增 lint 测试 —— 规则 `condition` 引用的每个 metric 键必须落在键宇宙（复用 `decide/engine.py:446` 的 `_METRIC_KEY_REGISTRY` 机制）。
- **风险**：跨层依赖方向（service→pipeline 已存在，`service/loop.py` 已是转发层）。

#### CR-04 评分器适配器签名
- **变更**：`_PixoScorerAdapter` 增 `__call__(image, masks=None)` 委托 `.score()`（推荐，一处修好两个契约：`loop.py:907/912` 与 `render/geometry/smart_crop.py:194` 都按可调用对象使用）；或 loop 侧改走 `.score()` **并**给 `suggest_crop` 传适配闭包。
- **验收**：新增单测 —— `make_default_scorer()` 注入 loop 后美学记录非空、`suggest_crop(scorer=...)` 不返回全 fallback（当前两者恒空/恒 fallback）。

#### CR-05 端到端门禁
- **变更**：新增 gate：真 RAW + `DEFAULT_RULES` 跑完整闭环 → 断言 ①`rule_ids` 非空 ②导出图与「仅渲染」基线存在像素差 ③QC 高光溢出 ≤3% ④trace 完整落盘。
- **验收**：`pytest -m gate` 通过，签章 `.r21_ok`。这一步把「应该通」变「验证过通」。

### 战役 B：干净（P1）

#### CR-06 噪声/细节指标入决策键宇宙
- **问题**：`measure_sharpness` 已产 `noise_ratio`/`detail_score`（`vision/measure.py:298-306`），但全局键宇宙（`loop.py:521-551`）不含它们，规则无法引用 —— 噪声是「看得见但系统不知道」的量。
- **变更**：展平 `detail.sharpness.noise_ratio`、`detail_score` 并注册 metric 键。
- **验收**：规则可引用（lint 放行）+ 新增 1 条阈值锚定实测分位的噪声规则。

#### CR-07 亮度降噪落地
- **问题**：`DenoiseStage.wants()` 恒 `False`；真正在跑的是 `refine` 的色度降噪，高 ISO 亮度颗粒无解 —— 「干净」这条腿唯一能力性缺口。
- **变更**：实现亮度降噪（优先 native 内核 + Python 等价位回退）；参数 `denoise.luminance_strength`/`detail_preserve`；按 `noise_ratio` 自适应；**默认值须 A/B 数据裁决后才可开启**。
- **验收**：≥20 张高 ISO 语料 A/B —— `noise_ratio` 降 ≥30% 且 `detail_score` 降 ≤10%，金样本 gate 无回归；DLL 版本 +1 并做新旧快照对拍。
- **风险**：新增 native 内核 ⇒ 逐位等价 + 版本门控纪律；可能触发金样本重生成。

#### CR-08 静默降级可观测
- **问题**：131 处 `except Exception` 吞异常，内核/标定/模型降级无声。
- **变更**：分级处置 —— 关键路径（native 调用、标定/LUT/模型加载、分割器）改 `log.warning` + 结构化 degraded 列表（挂 `vision/health.py` 或 render trace）；纯回退路径维持现状。
- **验收**：人为破坏一个标定文件 → health 端点暴露 degraded 条目（新增测试）。

### 战役 C：风格化最后一公里（P1）

#### CR-09 风格卡 LUT 注入生产路径
- **问题**：`configs/styles/films/` 25 张 JSON 可用，但唯一注入点 `apply_intents()` 在 `src/` 内零调用，前端也无入口 —— 资产齐全、断在最后一米。
- **变更**：service 参数装配支持 `style.lut_path`/`style.lut_strength`（白名单 + 路径限制在 `configs/styles/films` 内）；`GET /api/styles/films` 列表；前端样式选择器（**简约，按用户偏好：不做列表式堆砌大卡片**）。
- **验收**：带 `lut_path` 的渲染请求使 stylize 生效（像素差 + trace）；越界路径被拒。

#### CR-10 场景预设路径（P2）
- `configs/styles/scenes.json` 6 个场景预设目前同样只挂在 `apply_intents` 上；与 CR-09 合并或紧随其后。

### 战役 D：QC 与色彩收尾（P1/P2）

#### CR-11 多轴 QC 扩容
- **问题**：`_qc_outcome` 只看高光溢出（阈值 3%），`targets` 生产默认空 —— 只防过曝的质检撑不起「通透干净风格化」验收。
- **变更**：QC 报告增加清晰度/噪声/色彩（对参考 ΔE）轴；**分级**：硬门禁仍只保留像素/溢出，其余轴先做软告警落库。
- **红线**：美学 `color` head 修复前，`aesthetic_accept_threshold` **不得**作为硬门禁（依据：完全去饱和 color 分反而升高、加蓝偏 overall 反而升高）。
- **验收**：回归集 QC 报告含多轴字段，且不改变既有 ACCEPT/REJECT 判定（除非显式开启）。

#### CR-12 RP-CCM 运行时切换或显式否决（P2）
- 二选一：A 在 DCP 后接入 `apply_rp_ccm`（A/B 证据 median −7.7% 已有）；B 明确否决并登记结论。禁止长期停留在「并联评估态」。

**勘误（2026-09-10，R22 实测更正；手法同本文 §0）**：

- **原文所引证据已失效**：`median −7.7%` 出自 **2026-08-28** 旧系数报告
  `.artifacts/eval_rp_ccm_ab_nikon_z5_2_20260828_232324.md:14-16`
  （A 6.151 / B 5.675，**B−A = −0.475（−7.7%）**；`:77` 结论 B 更优 **45/54**）——
  该报告评测的是**阶段一中性弱监督拟合**的旧系数，不是现行生产系数。
- **翻转事实**：`configs/color/rp_ccm_nikon_z5_2.json` 于 **2026-09-04** 被 commit
  **`3fbe56d`**（"新表入库正式 configs（阶段二终审路径1）"）换成阶段二**联合优化**系数；
  同脚本（`scripts/eval_rp_ccm_ab.py`，`:73 --ccm-dir` 缺省 `configs/color` = **生产位**）
  同语料（54 张）复评 = `.artifacts/eval_rp_ccm_ab_nikon_z5_2_20260904_235522.md:14-16`：
  A 5.946 / B 7.093，**B−A = +1.147（+19.3%）**，p95 **+0.783（+4.9%）**；
  `:77` 结论 B 更优仅 **22/54**。
- **门槛线实测**（`docs/OWN_PIPELINE_STAGE2_DESIGN.md:38`：median 改善 ≥15% /
  无单照片 median 回归 >1 JND / 总体 p95 不劣化 / **≥2 相机**复验）：
  现行系数 **0/4 通过**；第二相机语料本机不可得（门槛第 4 项物理不可达）。
- **结论更正**：CR-12 的"二选一"取 **B（显式否决）**，理由并非"门槛未达标"这么轻，而是
  **本条所引 `−7.7%` 证据已被 2026-09-04 同脚本复评推翻为 `+19.3%`**。
  否决落档：`docs/tech_debt.md` 条目 22；`src/pixo/render/core/rp_ccm.py` docstring 顶部
  同步标注「已评估并否决，不进运行时」；代码与单测**保留**为未来中性语境重拟合的基础。
  复核触发条件：中性语境下新 A/B median 改善 ≥15% 且 p95 不劣化，或第二台相机语料入库后复验通过。

#### CR-13 G-1 skin OKLab 金样本（P2）
- 增加 `SKIN_OKLAB_*` 常数 ↔ `configs/color/skin_oklab.json` 一致性单测 + 1 个金样本 case（防 tech_debt #18 同类双源失同步复发）。

### 战役 E：发布与债务（P0/P2）

#### CR-14 推送远端（P0，零风险）
- `git push origin master`；验收：`origin/master == 58d780b`（43 提交、180 提交总量，R9–R20 目前仅存本地）。

#### CR-15 台账治理（P2）
- #3 许可登记冲突（aesthetic「需核验」+旧路径 vs MIT 定论；segformer `publishable`/`status` 自相矛盾；DCP×6 再分发）—— 发布前必收；
- #7 感知质量门禁提案；#12 公式守卫（前置未到，维持）；#17 compose free 像素矩形跨分辨率失准（独立战役，见下）；#10 重复编号重排。

#### 独立战役（需用户裁决）：tech_debt #17
`compose` free 模式裁剪矩形用全画布像素坐标 ⇒ 同参数跨分辨率取景不同、掩码落点错位可达 10% 画幅宽。这是唯一「用户可感知且会出错」的未清债务；清偿 = px→相对坐标归一化 + 存量卡与用户参数迁移。**建议单开一轮，不与其他 CR 混做。**

---

## 3. 建议执行顺序

| 阶段 | 内容 | 说明 |
|---|---|---|
| **M0** | CR-14 → CR-01 → CR-02 → CR-03 → CR-04 → CR-05 | 闭环插电；全部 S/M，前置已就绪，做完就能第一次看到「AI 自己修完一张图」 |
| **M1** | CR-06 → CR-07 → CR-09 | 补「干净」与「风格化」两条腿 |
| **M2** | CR-11 → CR-12/13 → CR-08 → CR-15 | QC 扩容、色彩收尾、可观测、债务 |
| **独立** | #17 compose 坐标归一化 | 用户拍板后单开 |

## 4. 明确不做（避免重蹈）

1. **不做端到端 learned ISP** —— 与「可解释闭环 + 规则引擎」的产品定位冲突。
2. **不在美学 color head 修复前开启美学硬门禁。**
3. **不在闭环跑通前继续深挖色彩标定** —— 边际收益递减（阶段二 36% 已是大头），当前瓶颈是「没插电」而非「不够准」。

---

## 附：本轮新增证据文件（未跟踪，`.artifacts/`）

- `.artifacts/_probe_metric_shape.py` —— 嵌套/扁平指标形态对比探针；
- `.artifacts/_probe_metric_shape2.py` —— 忠实 measurement 结构 + `_metrics_for_decide` 对比探针（0/11 触发的直接证据）；
- `.artifacts/_probe_rules_keys.py` —— 11 条默认规则的 condition 键清单。
