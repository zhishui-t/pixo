# R25 · Tier-1 准度根因收口 + 直方图 API（R23 F02）

日期：2026-09-19 ｜ 上承：R24 两分参照集（`R24_profile_curve_compose.md` §5.2）
与 R23 §6 能力清单（直方图 ❌ 无独立 API）

---

## 0. 结论速览

1. **Tier-1 引擎准度疑云定案：不是缺陷**。R24 测得的 -0.66EV 系统尺度差，
   根因 = 当前 DCP 的 **BaselineExposureOffset（-0.6228EV）**——中性链
   `exposure mode="baseline"`（R23 "打开 RAW = LR 打开 DNG" 语义）把它乘进
   输出，而 libraw 线性参照不乘。**扣除后残差 ev_med median -0.024EV、
   p90 +0.06EV**（色彩矩阵/去马赛克级）⇒ 引擎纯解码与独立中性实现一致到
   1.7%，"解码偏暗/不准"的疑问彻底关闭。
2. **直方图 API 落地（R23 F02）**：`vision/measure.compute_histogram`
   纯函数（BT.709 luma + RGB 计数，256 桶 0-255 值域）→ 服务端点
   `GET /api/sessions/{id}/histogram?gen=` → 前端 AdjustmentsPanel 真直方图
   （替换 t8 时代的硬编码占位柱，按 generation 刷新、离线回退占位）。
3. **两路径曝光语义差异记录在案**（防未来误判为 bug）：DNG 复刻路径
   `render_dcp_linear` 的 `exposure_ramp`（core/tone.py:27-34）**负 EV 钳零**
   （欠曝补偿交给影调曲线，docstring 明文的 clean-room 设计）；预览/生产链
   `ExposureStage` 负 EV 全量乘。两条链语义不同是**有意**的，非缺陷。

---

## 1. F01 · Tier-1 尺度差根因实证（`.artifacts/_r25_tier1_probe.py`）

探查锁定候选 → 两臂实证（n=24 真机，DCP = LR Adobe Standard Baseline，
BaselineExposureOffset = -0.6228EV）：

| 臂 | 口径 | ev_med median | p10 / p90 | ev_p995 median |
|---|---|---:|---|---:|
| A 现状 | 我们线性（含 offset）vs libraw | **-0.6470** | -0.7204 / -0.5625 | -0.6252 |
| B 纯解码 | 我们线性 ÷ 2^offset vs libraw | **-0.0242** | -0.0976 / +0.0603 | -0.0024 |

判据（B 臂 |ev_med| < 0.1EV）**通过** ⇒ 根因定案。链路核对：

- 解码归一两侧完全同源（black/white 均出自 LibRaw：我们 decode_cfa_half 与
  libraw scale_colors 同口径 `(raw-black)/(white-black) × wb`，G=1 均无亮度归一）；
- 唯一系统性常数 = `exposure.py:420` 的 `prof.baseline_exposure_offset` 增益。

**语义定案（不翻 R23 的案）**：默认链维持 baseline 施加 DCP 基线曝光
（"中性 = LR 打开 DNG"，LR 确实会施加）；Tier-1 尺子口径修正为
**扣除基线曝光后对比**（`docs/metrics/r24_recipe_tone_fit.md` 已同步）。
R23 §5.1 单张实测的 -0.44EV（中位）同此根因，当时未追。

## 2. F02 · 直方图 API

| 层 | 落点 | 说明 |
|---|---|---|
| 算法 | `src/pixo/vision/measure.py::compute_histogram(image_rgb, bins=256)` | 复刻 `compute_proxy_metrics` 契约（`_to_float_rgb` 统一量纲、nan 防御、非法输入空 dict）；BT.709 luma（`_luminance`）+ RGB 三通道计数；末桶含右端点 |
| 服务 | `runtime.histogram_session` + `GET /api/sessions/{id}/histogram?gen=&long_edge=&bins=` | 照 measurements 模板（gen 过期 404、渲染失败返回 `histogram:null + error` 不抛 5xx）；`session.render` 走既有 stage 缓存 |
| 前端 | `types.ts` HistogramCounts/Data/Result + `client.getHistogram` + `api/index.fetchHistogram`（三态：数据/null）+ `AdjustmentsPanel` 真直方图 | 256 桶降采样 64 柱、按最大值归一；按 store 全局 generation 刷新（与预览图同 gen 键）；离线/失败回退原占位柱（不闪断策略同 getOriginalSource） |
| 边界 | **不进 decide 规则** | 数组本体不入 `metric_universe`（规则引擎只吃标量）；现有 tonal_range/shadow_clip_ratio 等已覆盖规则需要 |

测试：`test_proxy_metrics.py` +4（手算一致/饱和末桶/float-u8 CDF 口径/bins 守卫）；
`tests/integration/test_service_api.py::test_histogram_endpoint`（计数正确性、
自定义 bins、gen 过期 404、未知会话 404）。前端 `npm run build`（tsc --noEmit）通过。

## 3. 改动清单

| 文件 | 改动 |
|---|---|
| `src/pixo/vision/measure.py` | 新增 `compute_histogram`（+`__all__`） |
| `src/pixo/service/runtime.py` | 新增 `histogram_session`（measure_session 同错误语义） |
| `src/pixo/service/app.py` | 新增 histogram 端点 |
| `frontend/src/types.ts` / `api/client.ts` / `api/index.ts` / `components/AdjustmentsPanel.tsx` | 类型契约 + REST 封装 + 三态包装 + 真直方图接线 |
| `tests/unit/test_proxy_metrics.py` / `tests/integration/test_service_api.py` | 直方图单测 + 端点测试 |
| `docs/metrics/r24_recipe_tone_fit.md` | Tier-1 归因修正（尺度差 → BaselineExposureOffset 口径差） |
| `.artifacts/_r25_tier1_probe.py` / 本文件 | 探针 + 轮报 |

渲染链零改动（gate 金样本零漂移约束天然满足）。

## 4. 回归

全量 **1698 passed / 1 failed / 6 skipped / 1 xfailed**（唯一失败 = 在册遗留
`test_llm_shadow::test_shadow_threshold_configurable_flips_verdict`，R23 §7
登记的断言精度问题，与本轮无关）；junit 结构化结果
`.artifacts/_r25_full_suite.xml`。前端 `npm run build`（tsc --noEmit + vite）通过。

## 5. 待队长复核

- Tier-1 口径修正（扣除基线曝光后对比）是否如所拟记入 F01 尺子基线；
- 直方图是否需要进 measurement 报告本体（本轮判定不进——数组属 UI/测量层，
  rules 只吃标量；如需再议）。
