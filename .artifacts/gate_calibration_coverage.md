# gate 金样本标定覆盖缺口关闭报告（t38）

- 日期：2026-09-04
- 执行：tester-1（长安）
- 缺口来源：t36 §5 / t37 上报——gate 金样本对四个标定表零敏感（前置 15 case 均为「纯函数 + 显式参数」构造，不触达 warmth 曲线 / exposure auto / target_offset 插值 / rp_ccm 路径，换表金样本纹丝不动）
- 报告：.artifacts/gate_calibration_coverage.md（本文件）

## 结论（TL;DR）

**缺口已关闭（warmth + exposure 表两个运行时路径），门禁有效性经双向演练实证。** rp_ccm 因运行时未接线（src 零调用点）无从触达，按任务预案如实记录、留待接线后补 case。全量回归绿。

| 验收项 | 结果 |
|---|---|
| 新增 case 触达 auto 标定路径 | ✅ `exposure_cal_auto`（曝光表）+ `warmth_cal_auto`（warmth 曲线） |
| 换表敏感性实证（旧表 vs 新表输出 hash 不同） | ✅ 两 case 均敏感 |
| 新基线入库（G-4 规避 + reviewer 签注 + 数量守卫同步） | ✅ 17 features |
| 回退演练（拷回旧表 → --check 报漂移 → 回滚 → OK） | ✅ 精确 2 处漂移 / 恢复 OK |
| 全量回归 | ✅ 1297 passed / 4 skipped / 1 xfailed（338.8s） |

## 1. 新增 case 设计

### 1.1 `exposure_cal_auto`（触达正式曝光表）

走 `ExposureStage._auto_ev(ctx)` **完整 auto 决策链**：固定网格 med 探针（真 DCP `cam→sRGB`，与运行时同链路）→ 二维表 `src/pixo/render/target_offset.json` 的 med 主键插值 + `ctx.state["camera_wb"]` 驱动的 wb_B 邻域二次插值（`ev_mode = cal_table_2d`）。

- 场景：64×64 平坦场（常数 0.04 + 种子微扰动，rng seed 20260904），探针 med = **−4.5413**，落在表结点密集段（−4.632/−4.555/−4.478…），非端点钳位——表 ev 列变化直接进入插值结果；
- `wb_B = 1.5`（camera_wb [2.0, 1.0, 1.5]），落在邻域内 wb 插值段 1.371~1.506；
- ev 应用与现有 exposure case 同式（线性增益 `2**ev` + `soft_highlight_rolloff(knee=0.9)`）。

### 1.2 `warmth_cal_auto`（触达正式 warmth 分桶曲线）

`_load_warm_cal(configs/calibration/warmth_curve.json)` 读正式表 → `apply_warmth` 曲线分支（优先于内置斜率模型）得三通道增益 → 乘种子线性 cam RGB（运行时同式）。**表缺失/非法时 raise 而非静默回退**——防止表被移除后 case 退化为斜率模型仍产出"稳定"基线、制造仍在锁表的假象。

- `wb_B = 2.0`，取结点 1.8027~2.3984 插值段（增益 [1.454, 0.926, 1.806] 非恒等，对结点值敏感）。

### 1.3 rp_ccm：运行时未接线，无从触达（如实记录）

`apply_rp_ccm`/`load_rp_ccm` 在 `src/pixo/render` **零调用点**（仅 `core/rp_ccm.py` 自身与 scripts/calib 标定侧使用）——运行时渲染链尚未接 rp 并联（t30 的并联在 scripts/calib/diff_core 代理侧）。任务预案「若现有 case 未触达 rp 加载链，可用同一 case 的存在性验证」不适用于 gate case（其产出是数组快照而非断言）；rp 表替换当前不影响任何运行时渲染输出，**等运行时接线后随接线批次补第三个 case**（建议形态：stylize 前线性域并联点直调 `load_rp_ccm(正式表)` + `apply_rp_ccm`，场景取 rp 特征敏感的色块图）。

## 2. 换表敏感性实证 ✅

同一 case 代码，分别以 `calib_prev`（入库前旧表快照）与现行新表运行，输出 hash：

| case | 旧表 hash(前16) | 新表 hash(前16) | 判定 |
|---|---|---|---|
| exposure_cal_auto | `1160800a8fc04b2e` | `97e7e5311be333f3` | 敏感 ✅ |
| warmth_cal_auto | `a72728539e31acea` | `c3e3a7a2aa69ee31` | 敏感 ✅ |

exposure case 输出逐像素差 max ≈ 0.0097（u8 量化约 2.5 级）——敏感且量级合理（两表在该 med/wb 邻域的 ev 差异不大）。旧表在正式位置运行时逐位复现了 t36 §3 的重建基线（`1160800a…` 与演练轮一致）。

**方法论坑（已绕过并记录）**：exposure 表加载有模块级缓存 `_cached_table`（进程级静态资源语义）。同进程内换表必须置 `exposure_mod._cached_table = None` 再验，否则第二次读到旧缓存、误判「不敏感」；`generate_gate_goldens.py` 每次独立进程运行，无此问题。金样本门对表替换的有效性因此依赖**跨进程**运行（现行生成器/pytest 均满足）。

## 3. 基线入库与签注 ✅

- `--check`（生成前）：检出恰好 2 处「新增 feature」，**前置 15 case 重算零漂移**（新代码对既有 case 零干扰的证明）；
- 正式生成：`python tests/regression/goldens/generate_gate_goldens.py --out tests/regression/goldens/gate`（当时 G-4 未修复，需显式传参 + PYTHONPATH；修复后两者均可省略），17 features 写盘，.npy sha256 与 manifest 逐文件核验一致；
- reviewer 签注：已注入 manifest.reviewer（批次说明 + 敏感性实证结论 + rp_ccm 未接线注记），`--check` 复验 OK；
- 数量守卫同步：`tests/regression/test_gate_golden.py` 断言 15 → **17**（附批次注释）。

## 4. 回退演练 ✅（门没白装的直接证据）

```
拷回 calib_prev 旧表 → --check:
  exposure_cal_auto.sha256: afefa19f… -> d9455407…
  warmth_cal_auto.sha256:   5a95845c… -> 756ab009…
  CHECK: DRIFT (exit=1)                       ← 门触发，恰好两个新 case
回滚新表（字节级校验 OK）→ --check: OK (exit=0) ← 恢复
```

此后**任何**标定表替换（正式位置 warmth_curve.json / target_offset.json 变动）都会被金样本门在 `pytest tests/regression` 阶段当场拦截，reviewer 流程不再是空转。

## 5. 全量回归 ✅

```
1297 passed, 4 skipped, 1 xfailed, 13 warnings in 338.81s
```

用例总数与上轮一致：新 case 并入既有 golden 校验函数（`test_manifest_schema_and_files` 数量断言 15→17、`test_baseline_files_match_manifest_sha256` 遍历全部条目），非新增测试函数。两个新 case 的输出已在新基线中锁定，任何一方变动（实现或标定表）都会被 `tests/regression` 当场拦截。

## 6. 改动清单

- M `tests/regression/goldens/gate_cases.py`（FEATURES +2、`_CalAutoRaw` 桩、两个 case 分支）
- M `tests/regression/goldens/gate/manifest.json`（17 条目 + reviewer 签注）
- ?? `tests/regression/goldens/gate/exposure_cal_auto.npy`、`warmth_cal_auto.npy`（新基线）
- M `tests/regression/test_gate_golden.py`（数量守卫 15→17）
- 未改动：src/（红线零 diff 维持）、configs/（本轮不动表）

## 7. 遗留与建议

1. rp_ccm 运行时接线后补第三个标定 case（§1.3）；
2. `neutral_trim`/`skin` 表当前无 auto 运行时路径差异可锁（skin 表阶段二未变；neutral_trim 同为 auto 路径但经由 `camera_neutral_trim(prof)` 的 DCP name 查表——如需覆盖可循 exposure_cal_auto 模式加 case，本轮未做，建议随下次标定表替换一并补）；
3. 敏感性实验若将来在进程内做（如治理脚本），记得清 `_cached_table`/`calibration_store.reset()`（§2 方法论坑）。
