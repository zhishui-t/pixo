# R22 流 2（dev-2）交付报告 — F03 关键路径静默降级可观测 + F08 skin OKLab 一致性**只读复核销账**

> 依据：`.agent-team/design-r22.md`（**唯一实现依据**，§0 P4/P8、§1 F03/F08、§3 文件域、§4 可观测靶子、§5 风险）+ `.agent-team/exploration-r22.md` §4.2（13 条清单）/§7（skin 现状）。
> 状态：**完成**（F03 落地 + 定向测试通过；F08 销账结论成立、零代码新增）。
> 未提交 git（纪律要求）。未跑全量回归（tester 第 10 阶段）。

## 0. 一句话结论

F03 已按「L1 render 侧采集 + L2 `vision/health.py` 暴露」两层落地：exploration §4.2 的 **13 条关键路径**（14 个 except 落点，其中 #10 标定表有「损坏」与「校验失败」两个入口）全部从静默回退升级为结构化降级事件（含 source/kind/path/reason/detail/exception/count/时间戳），**版本门合法拒绝（DLL<1.6.0 的 oklch 内核）与真异常在代码层显式区分**（不误告警，反向控制单测把守）；`vision_health()` 纯增量新增 `render_degraded*` 键、不改既有 status/ready 语义。F08 复核：CR-13 三项（六常数逐位锁定、angle↔rad、skin_oklch/skin_oklch_softband gate case）**真实存在且全绿，无缺口**，本轮不新增任何实现。

文件域核对（`git status --porcelain` 实测，仅列本流文件）：

- 改：`src/pixo/render/modules/reshape.py`、`refine.py`、`exposure.py`、`tone_map.py`、`white_balance.py`、`src/pixo/render/modules/color_cal.py`、`src/pixo/render/core/lut3d.py`、`src/pixo/render/web/session.py`（**全部且仅 13 条关键路径的 except 处 + 各文件 1 行 import**）、`src/pixo/vision/health.py`
- 新增：`src/pixo/render/degradation.py`（L1 承载点，见 §4 偏差-1）、`tests/unit/test_render_degradation.py`
- **未触碰**：`src/pixo/pipeline/**`、`src/pixo/decide/**`、`src/pixo/service/**`、`tests/regression/**`、`configs/**`、`frontend/**`、`src/pixo/render/_native/**`

---

## 1. 改动清单

### 1.1 L1 采集层（新挂点，范式对齐 `vision/health.py:82-126` 的 `last_degraded`）

`src/pixo/render/degradation.py`（新建，仅依赖标准库，可被 `vision` 侧轻量 import）：

| 位置 | 内容 |
|---|---|
| `:81-99` | `classify_native_failure(exc)` → `version_gate` / `native_unavailable` / `exception` / `fallback` |
| `:101-104` | `is_expected_failure(exc)` = 版本门合法拒绝 |
| `:124-185` | `record_degradation(source, exc, *, path, reason, detail, kind)`：条目字段 `source/kind/path/reason/detail/exception/expected/count/first_seen/last_seen/timestamp`；**warn-once 节流**（同 key 只 1 条 `log.warning`，之后 debug；版本门只 debug）；条目上限 `MAX_ENTRIES=64` |
| `:193-213` | `render_degraded_entries()` / `version_gate_rejections()` / `render_degradation_report()`（返回副本，外部改动不污染登记表） |
| `:215-220` | `clear_render_degradations()`（测试隔离钩子） |
| `:53-67` | `MAX_ENTRIES=64`；`_VERSION_GATE_MARKERS=("需 DLL >=", "DLL 未导出")`；`_NATIVE_UNAVAILABLE_MARKERS=("native DLL unavailable",)` |

### 1.2 13 条关键路径逐条（文件行 → 改动 → 区分逻辑）

| # | 路径 / 位置（post-edit 行） | 改动（静默 → 结构化） | 区分逻辑 |
|---|---|---|---|
| 1 | clarity native · `render/modules/reshape.py:105`（`except`）/ `:107`（记录） | `except Exception:` 裸捕获 → `as exc` + `record_degradation("render.reshape.clarity_native", exc, detail="预览 clarity 回退纯 Python _clarity")`；回退 `_clarity` **不动** | 真异常类；回退目标写入 detail |
| 2 | refine native 导入 · `refine.py:208/210` | 记录 `render.refine.native_import`（整链退纯 Python） | 同上；`available()=False` 时不抛异常 → 不记录（native 未参与即无「切换」） |
| 3 | refine sat_protect · `refine.py:218/220` | 记录 `render.refine.sat_protect_native` | 同上 |
| 4 | refine sharpen · `refine.py:233/235` | 记录 `render.refine.sharpen_native` | 同上 |
| 5 | refine chroma(+highlight fused) · `refine.py:260/262` | 记录 `render.refine.chroma_native`（detail 点名 F02 主战场失真风险） | 同上 |
| 6 | refine highlight · `refine.py:276/278` | 记录 `render.refine.highlight_native` | 同上 |
| 7 | exposure native · `render/modules/exposure.py:462/464` | 记录 `render.exposure.native`（所有照片必经） | 同上 |
| 8 | tone LUT1D native · `tone_map.py:335/337` | 嵌套 `_apply_lut` 内记录 `render.tone_map.lut1d_native` | 同上 |
| 9 | WB matrix3 native · `white_balance.py:416/418` | 记录 `render.white_balance.matrix_native` | 同上 |
| 10a | warmth 标定表**损坏** · `white_balance.py:146-158`（`doc is None` 分支） | 新增 `Path(str(path)).is_file()` 判定：**存在却读不出** → `record_degradation(..., None, path=..., reason="calibration_unreadable", kind="fallback")` | **缺失 ≠ 降级**：`calibration_store` 明示「缺失文件是合法常态, 不告警」（`calibration_store.py:19-20`）⇒ 缺失不记；损坏记 |
| 10b | warmth 标定表**校验失败** · `white_balance.py:168/171` | `except Exception:` → `as exc` + `reason="calibration_invalid"` | 真异常类（结点校验失败） |
| 11 | colorcal native（hsv/oklch + gamut） · `color_cal.py:419/424` | `except Exception:` → `as exc` + `reason=classify_native_failure(exc)` + detail 含域（`hsv`/`oklch`） | **核心**：`RuntimeError("... 需 DLL >= 1.6.0 ...")` / `"DLL 未导出"` → `version_gate`（**不计 degraded、不告警**）；`native DLL unavailable` → `native_unavailable`（计 degraded）；其余 → `exception` |
| 12 | LUT3D native · `render/core/lut3d.py:188/190` | 原 `except Exception: pass`（连变量都不记）→ `as exc` + 记录 `render.lut3d.native`，仍落到 `self.lookup` 回退 | 真异常类 |
| 13 | 解码 native CFA · `render/web/session.py:204/207` | `except Exception:` → `as exc` + 记录 `render.io.decode_cfa_half`（`path=str(self.raw_path)`） | 真异常类；`img=None` 后走 rawpy AHD half 回退**不动** |

合计 **14 个 `record_degradation(` 落点**（grep 实测：reshape 1 / refine 5 / exposure 1 / tone_map 1 / white_balance 3 / color_cal 1 / lut3d 1 / session 1）。其余 119 处 `except Exception` **零改动**（含 exploration §4.2 补充的「次要关键」`core/io.py:180`、`core/huesat.py:341/355`，见 §5 遗留-1）。

### 1.3 L2 暴露层 · `src/pixo/vision/health.py`

| 位置 | 改动 |
|---|---|
| `:129-148` | 新增 `_render_degradation_info()`：函数内**惰性** `from ..render.degradation import render_degradation_report`（不破坏本模块「顶层不 import 重依赖」约定；import 失败返回空汇总 + `error`，不影响 vision 状态） |
| `:199-209` | 组装 `render_extra`：`render_degraded`(list) / `render_degraded_count` / `render_status`("degraded"\|"ok") / `render_version_gate_rejections`(list) / `render_version_gate_count`；异常时附 `render_degraded_error` |
| `:232` | 返回 dict 末尾 `**render_extra` —— **纯增量**，`status`/`ready`/`available`/`segmenter`/`models` 全部按原逻辑（`:194-231` 未改） |
| `:158-166` | docstring 记录新键语义 |

### 1.4 版本门 vs 真异常的判定依据（落到代码，可证伪）

依据 = native 封装（`render/_native/__init__.py`）的**三类声明式 RuntimeError 文本**（异常类型无法区分，三者都是 `RuntimeError`）：

1. `:1049-1053` colorcal oklch 内核 `if _version is None or _version < (1,6,0) or not hasattr(...)` → `"native colorcal oklch F32 kernel unavailable (需 DLL >= 1.6.0, 实际 ...)"` ⇒ `version_gate`；
2. `:617/655/675/698/723/765/817/847/955/984/1080/1116/1136/1165/1197/1226/1264` 各内核 `raise RuntimeError("native XXX kernel unavailable (DLL 未导出)")` ⇒ `version_gate`；
3. `_require_lib():516-518` `"native DLL unavailable: ..."`（DLL 缺失/加载失败，整条加速链缺席）⇒ `native_unavailable`（**记 degraded**，与版本门区分）。

版本门事件进独立通道（`version_gate_rejections()`），**不产生 warning、不进 `render_degraded`**；`render/modules/color_cal.py:419-428`（except 落点 + 注释）把该判定写进调用点。脆弱点（文本匹配）用单测锁死 3 类标记 → 见 §2-E1。

---

## 2. 自测证据（命令 → 输出关键行 → 结论）

> 全部输出重定向到文件后读取（未用 `| Select-Object`），`$env:PYTHONIOENCODING='utf-8'` + `cmd /c "..."` 保证落盘为 UTF-8。

| 编号 | 命令 | 输出关键行 | 结论 | 证据文件 |
|---|---|---|---|---|
| E0 | `python .agent-team/tmp-r22d2-probe.py` | `'version_gate' <- RuntimeError('... 需 DLL >= 1.6.0 ...')`；`degraded entries = 1`；`render_degraded_count = 1` / `render_status = 'degraded'`；`status/ready 未变 = 'not_ready'/False`；`degraded = 0, version_gate = 1`；`PROBE-OK` | L1+L2 端到端联通、三类判定正确、版本门不进 degraded | `.agent-team/tmp-r22d2-probe.txt` |
| E1 | `python -m pytest tests/unit/test_render_degradation.py -v` | 10 条逐名 `PASSED`（含 `test_version_gate_rejection_not_degraded`、`test_corrupt_warmth_curve_via_stage_then_health_exposes_degraded`、`test_missing_warmth_curve_copy_not_degraded`、`test_native_unavailable_is_degraded_not_version_gate`）；`10 passed in 17.56s` | **F03 定向单测全绿**（正向靶子 + 反向控制 + 边界 + 节流/去重 + 快照隔离 + health 纯增量守卫） | `.agent-team/tmp-r22d2-f03-verbose.txt`、`.agent-team/tmp-r22d2-pytest1.txt`（`10 passed in 12.67s`） |
| E2 | `python -m pytest tests/unit/test_native_fallback.py test_native_exceptions.py test_native_refine.py test_native_colorcal.py test_native_colorcal_oklch.py test_lut_native.py test_native_decode.py test_pipeline.py test_skin.py test_vision_segmenter.py test_vision_extras.py test_vision_router_semantics.py -q` | `144 passed in 45.70s` | 被改 8 个模块 + health 的既有单测零回归（native 回退/异常、colorcal oklch、refine、lut3d、decode、wb 链、vision_health 三件套） | `.agent-team/tmp-r22d2-f03-related.txt` |
| E3 | `python -m pytest tests/unit/test_refine.py test_lut.py test_wb_temp_tint.py test_wb_manual_exposure.py test_exposure.py test_exposure_caltable.py test_tone_sixkey.py test_native_stage_kernels.py test_native_warm_sat.py test_native_oklab.py test_native_hsv.py test_native_abi.py test_phase1_chain.py test_pipeline_runner.py test_pipeline_config.py test_curves.py test_colorcal_direction.py -q` | `187 passed in 48.32s` | 第二批相关单测零回归 | `.agent-team/tmp-r22d2-f03-related2.txt` |
| E4 | `python -m pytest tests/regression/test_gate_colorcal.py test_gate_refine.py test_gate_exposure.py test_gate_native_equivalence.py -q` | `15 passed in 0.85s` | 像素级门禁（native↔Python 等价）在上游未改行为下仍绿 | `.agent-team/tmp-r22d2-f03-gates.txt` |
| E5 | `python -m pytest tests/unit/test_skin_oklab.py tests/regression/test_gate_golden.py -q`（design §4 F08 判据命令） | `25 passed in 49.23s`（18 + 7） | F08 复核主证据（见 §3） | `.agent-team/tmp-r22d2-f08.txt` |
| E6 | `python .agent-team/tmp-r22d2-f08-probe.py` | 见 §3 逐行引用；`generate_gate_goldens.run_check(rc) = 0`；`F08-PROBE-DONE` | F08 三项独立复核（逐位/换算/gate case 与基线） | `.agent-team/tmp-r22d2-f08-probe-out.txt` |

**统计**：本轮定向执行 **10 + 144 + 187 + 15 + 25 = 381 passed / 0 failed / 0 skipped**（E1~E5；E6 为探针）。未跑全量回归、未跑真 RAW（纪律要求）。

### 2.1 关键用例的语义（供 tester 复算）

- `test_corrupt_warmth_curve_via_stage_then_health_exposes_degraded`：`tmp_path` 写截断 JSON 副本 → `StageContext(config={"stages":{"whitebalance":{"warm_cal_file": <副本>}}})` → `WhiteBalanceStage().run(ctx)` 不抛错 → `vision_health()["render_degraded_count"] == 1` 且 `["render_degraded"][0]["source"] == "render.white_balance.warmth_curve"`、`path` 为该副本、`render_version_gate_rejections == []`、`status` 仍由 segmenter readiness 决定。**验收靶子按要求用「写坏副本」，未触碰 `configs/**`。**
- `test_version_gate_rejection_not_degraded`（**反向控制，关键**）：`monkeypatch` `_native.available→True` + `colorcal_apply_lab_f32_oklch → raise RuntimeError("... 需 DLL >= 1.6.0 ...")` → 断言 `render_degraded_entries() == []`、`vision_health()["render_status"] == "ok"`、`version_gate_rejections()[0]["kind"] == "version_gate" and expected is True`、caplog 中**无** WARNING 级 `render-degraded`；再 `available→False` 直跑，断言回退输出与版本门回退**逐位相等**（`np.array_equal`）。
- `test_native_exception_records_degraded`：同路径改抛 `ValueError("simulated kernel crash")` → `kind == "exception"`、`expected is False`、`exception` 含原文、**有** WARNING 日志、health count=1、回退输出逐位等于禁 native 直跑。
- 自动 fixture `_isolated_degradation_state`：每条用例前后 `clear_render_degradations()` + `white_balance._reset_caches()`（含 `calibration_store.reset()`），避免进程级登记表互相污染。

---

## 3. F08 销账结论（只读复核，零代码新增）

### 3.1 复核项与证据

| 复核项 | 目标位置 | 证据（命令 → 关键输出） | 结论 |
|---|---|---|---|
| ① 六常数 ↔ `configs/color/skin_oklab.json` **IEEE754 逐位 ==** | `tests/unit/test_skin_oklab.py:354-383`（`_SKIN_OKLAB_JSON` 见 `:350-351`） | `pytest tests/unit/test_skin_oklab.py -v` → `::test_skin_oklab_constants_bitwise_locked_to_fit_json PASSED`（`18 passed in 3.07s`）；探针 A：`schema = pixo.skin_oklab.v1`，六行 `逐位== True`（例 `SKIN_OKLAB_SOFT_BAND code=0.31 hex=0x1.3d70a3d70a3d7p-2 json=0.31`），`六常数逐位一致 = True` | ✅ 真实存在且通过 |
| ② `angle`(rad) ↔ `angle_deg` | `test_skin_oklab.py:386-396` | 同上 `::test_skin_oklab_json_angle_deg_consistent_with_constant PASSED`；探针 B：`degrees(SKIN_OKLAB_ANGLE) = 11.248479` vs `json angle_deg = 11.2485`，`\|Δ\| = 2.07e-05`（容差 1e-3） | ✅ 真实存在且通过 |
| ③ gate case `skin_oklch` | `tests/regression/goldens/gate_cases.py:28`（FEATURES）+ `:257-263`（构造，注释「终审 G-1」） | 探针 C：`FEATURES 含 skin_oklch = True`、`FEATURES 总数 = 21`；`skin_oklch file=skin_oklch.npy shape=[64,64] dtype=float32 max\|Δ\|=0.000e+00 <=1e-6 True` | ✅ 真实存在且逐位一致 |
| ④ gate case `skin_oklch_softband` | `gate_cases.py:28` + `:264-269`（构造）+ `:79-116`（两射线 ×32 步软带探针） | 同上：`skin_oklch_softband ... max\|Δ\|=0.000e+00 True`；`skin`（对照）亦 0 | ✅ 真实存在且逐位一致 |
| ⑤ 金样本整体无漂移 | `tests/regression/goldens/gate/manifest.json`（21 features，`reviewer` 非空非 pending） | `pytest tests/regression/test_gate_golden.py -q` → `7 passed`（含 `test_generator_check_mode_reports_no_drift`、`test_current_output_matches_goldens` 遍历 21 features、3 条软带敏感性镜像）；探针 C：`[gate_goldens] CHECK: OK（21 features 与现有 manifest 一致）`、`run_check(rc) = 0` | ✅ 通过 |
| ⑥ native 侧无双源副本 | `src/pixo/render/_native/__init__.py:1004-1027`（`skin_oklab_ellipse()` 从单源 `core/skin.py SKIN_OKLAB_*` 构造 7 字段 ctypes 结构体）、`:1049` 版本门 ≥1.6.0 | 源码复核（R17 tech_debt #18 清偿） | ✅ 单源成立，CR-13「防双源失同步」只剩 `core/skin.py ↔ JSON` 一支（已被项 ①② 锁死） |

> 说明：`gate_cases.py` 的 `skin` case 用 u8 Lab 旧椭圆（`skin.py:31-35` 那族常数 ↔ JSON `baseline_ellipse.*`），与 OKLab 椭圆是**两套域**，不在 CR-13 范围，仅作对照（同样 `max|Δ|=0`）。

### 3.2 销账结论

- **已覆盖项**：CR-13/设计 §0 P4 所列三项（一致性单测六常数逐位锁定 + angle↔rad、gate case `skin_oklch`、gate case `skin_oklch_softband`）**全部真实存在且通过**，且软带 case 有 3 条敏感性镜像（非盲/带宽可观测/过渡带覆盖）——F08 **销账成立**，本轮**未新增任何 F08 代码**（`git status` 可证：无 skin 相关文件改动）。
- **缺口项**：CR-13 范围内**无缺口**。
- **唯一「仍有新价值」的候选（不在 CR-13 范围，交队长裁决）**：JSON `per_group_fit`（6 组，中心漂移 a∈[-0.006, 0.041]）尚未接线到运行时（当前只用单一全局椭圆）——这是**新能力**（阶段三），非 CR-13 缺陷；本轮**不改代码**，仅登记。

---

## 4. 偏差

1. **新增 `src/pixo/render/degradation.py`**：设计 §3 文件域写「`src/pixo/render/**`（仅 13 条关键路径的 except 处）」，而设计 §4.4 明确建议「L1 采集层 = `render/` 内**新增**模块级 `render_degradations` + `record_degradation` + warn-once」。我按 §4.4 落 L1 新模块，**其余 render 改动严格限于 13 条 except 处**（各文件仅多 1 行 import），未触碰 119 处非关键 except。若队长认为应把 L1 并入既有文件（如 `_native/__init__.py` 的 `load_error` 范式），请裁决后我再迁移。
2. **未改 `_native/__init__.py`**：版本门判定用「异常文本 + 声明式标记」而非新增异常类/改 native 封装（避免跨文件域 + 避免动 DLL 版本门语义）。代价 = 文本匹配脆弱 → 已用 `test_classify_native_failure_markers` 锁死三类标记，native 文案一旦变更该单测即红。
3. **未暴露到 `GET /api/health`**：design §4.4 给了「health dict 键 **或** `service/app.py` 透出」二选一；`src/pixo/service/**` 不在我的文件域 ⇒ 选 health dict 键。若 UI/接口需要，请队长派 dev-3 或后续轮次在 `app.py` 加透出（数据已在 `vision_health()` 里）。
4. **未跑全量回归**（纪律要求，仅定向）；且当前工作树同时存在 **dev-1（F01+F06）在途改动**（`pipeline/loop.py`、`pipeline/metrics.py`、`decide/*`、`service/runtime.py`、`tests/unit/test_noise_metric_keys.py`、`test_qc_soft_warnings.py`）——E2/E3 的 144+187 passed 是在**共享工作树**上取得的，覆盖了我改动面 + 这些在途改动面；归因请以我的文件域（§0 核对清单）为准。
5. `render_degraded` 是**进程级累积**登记表（设计 §4.4 口径）：断言「无降级」前必须 `clear_render_degradations()`（我的用例已用 autouse fixture 保证）。若要「单张照片归因」，需在 LoopResult/trace 携带 per-render 快照 —— 范围外，见 §5。
6. 真 RAW 全分辨率未跑、`configs/**` 未改（靶子用 tmp 副本 + monkeypatch），与纪律一致。

## 5. 遗留问题（范围外，交队长裁决）

1. **exploration §4.2「次要关键」两处未纳入（未改）**：`render/core/io.py:180`（`.npz` 解码缓存读失败 `except Exception: pass`）、`render/core/huesat.py:341/355`（native hsv/点云路径）。它们不在 13 条清单内，按「只改 13 条」边界保持原样；是否并入 F03 面（或留 R23）请队长定。
2. **per-render 归因**：当前登记表无「本次渲染」边界；若要 trace/响应里按单张照片看降级，需在 `pipeline/loop.py` 或渲染入口做 session 级切片（动 `pipeline/**`，不在本轮文件域）。
3. **`native_unavailable` 口径备选**：本实现把「DLL 缺失/加载失败」记为 degraded（真降级：加速链整体缺席）。若团队认为「无 DLL 的纯 Python 环境属合法常态、不应告警」，改 `_NATIVE_UNAVAILABLE_MARKERS` 语义即可（一处常量 + 改 1 条单测）。
4. **F08 阶段三候选**：`per_group_fit` 6 组椭圆未接线（新能力，非 CR-13 缺口，见 §3.2）。
5. **环境小坑（非本轮引入）**：仓库根 `python -c "import pixo"` 报 `ModuleNotFoundError`（editable 安装 `Location: D:\Python\Python312\tools\Lib\site-packages`，`Editable project location: K:\work\project\pixo`），但 `python -m pytest` 经 `tests/conftest.py:19-22` 插入 `src` 后可正常导入 —— 对其他流无影响，仅提示脚本要自带 `sys.path`（我的探针已如此）。另：pwsh 直接 `python ... > file` 落盘为 **UTF-16LE**，读文件前需 `PYTHONIOENCODING=utf-8` + `cmd /c` 才得 UTF-8。

## 6. 复现命令清单（tester 复算用）

```powershell
cd K:\work\project\pixo
$env:PYTHONIOENCODING='utf-8'
cmd /c "python -m pytest tests/unit/test_render_degradation.py -v > .agent-team\tmp-r22d2-f03-verbose.txt 2>&1"
cmd /c "python -m pytest tests/unit/test_skin_oklab.py tests/regression/test_gate_golden.py -q > .agent-team\tmp-r22d2-f08.txt 2>&1"   # design §4 F08 判据命令
cmd /c "python .agent-team\tmp-r22d2-f08-probe.py > .agent-team\tmp-r22d2-f08-probe-out.txt 2>&1"
cmd /c "python .agent-team\tmp-r22d2-probe.py > .agent-team\tmp-r22d2-probe.txt 2>&1"
```

**给 tester 的前置提示**：① `render_degraded` 为进程级累积态，断言为空前先 `pixo.render.degradation.clear_render_degradations()`（并把 `white_balance._reset_caches()` 一并调用）；② 版本门拒绝走 `version_gate_rejections()`，**不要**把它的存在当成 degraded 漏报；③ 破坏 `configs/calibration/warmth_curve.json` 时请用副本 + `warm_cal_file` 参数（本轮未改 configs），删除该文件属「合法常态」**不会**产生 degraded（设计口径，见 §1.2 #10a）。
