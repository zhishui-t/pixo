# F14 decide region.* 接线定向门禁（M1 收官）

> 审核人：qa｜2026-09-07T01:52:58+08:00
> 对象：stream-3 交付（F14），黑板 streams/stream-3.md F14 节
> 基线：d25f70c（F16 已提交）+ 共享树（dev-2 F08 在飞 gate 文件禁碰；dev-2 F09 已开改 patch_protocol.py）
> 方法：接线分支逐行审 + 键宇宙与生产 flatten 面交叉核对 + 裁决点源级/经验双验 + e2e 断言逐行审 + 三组复跑

## 结论：**PASS**（F14 批可与 F15 攒 M1 收官批）

修复记录：**0 处**（F14 域内未发现需修复缺陷）
**共享树红旗 1 条（非 F14 引起）**：test_patch_protocol.py 11 红 = dev-2 F09 在飞中途态，见 §6。

---

## 1. 接线核对（`region.<prompt>.<param>` 映射特例）

`_apply_decide_params` region 分支（loop.py :585-604）逐行审：
| 审核点 | 证据 | 结论 |
|---|---|---|
| 嵌套写入+联动 | `out["region_adjust"]["regions"][prompt][param]=v` + `bucket["enabled"]=True`（沿 dehaze :567-570 同款）；`test_region_exposure_key_maps_and_enables` 断言嵌套落位+enabled+**不留悬空顶层键** | ✅ |
| 值域钳制 | `max(-limit, min(limit, float(v)))`，exposure ±2 / saturation ±1 与 stage param_schema 同域；`test_region_key_out_of_range_clamped` 双向断言（5.0→2.0、-3.5→-1.0）——stage `_regions()` 对越界 raise ValueError，钳制防规则输出炸渲染链 | ✅ |
| 畸形键不吞 | 分支条件严格（恰好 2 点+非空 prompt+参数名∈枚举）；少段/多段/未知参数/空 prompt 四类落既有「informational 顶层保留+warning」路径，`test_region_malformed_keys_stay_informational` 四键逐一断言不吞 | ✅ |
| 桶链被占 | region_adjust 非 dict / regions 非 dict / entry 非 dict 三级兜底均退回顶层扁平键（t51 语义），`test_region_bucket_occupied_falls_back_flat` 钉死 | ✅ |
| 既有桶保留/覆盖语义 | 多区域共存+既有区域不破坏+同参数 set 覆盖（多轮确定性），两用例钉死 | ✅ |

## 2. 指标键宇宙完整注册（dev-3 自挖真问题，核验属实）

- **问题真实性**：decide/engine.py:445 注释证实「键宇宙非空 → load_rules 全进程 strict lint」；
  只注册 region 键会让默认包（tone_clarity 的 condition.all 引 haze_proxy/tonal_range）加载即炸——
  dev-3 首版实犯、全量 unit 跑出（14 errors）后修正为注册完整宇宙。教训真实且已闭环。✅
- **宇宙完整性交叉核对**：注册集 = `_metrics_for_decide` 全部固定产出键
  （mean_luminance/highlight_clip_ratio/shadow_clip_ratio/contrast/preview_highlight_clip_estimate/
  preview_overflow_ratio + haze_proxy/colorfulness_proxy/tonal_range）+ crop_suggestion_applicable
  （loop.py:1295 实产，qa grep 证实）+ 按 prompts 的区域四键——与生产 flatten 面一一对应，无缺漏。✅
- **回归钉死**：`test_default_rules_still_lint_after_loop_construction`（构造 loop 后默认包仍可加载）+
  `test_registered_keys_admit_rule_formula_reference`（region 公式 lint 放行）+ 
  `test_loop_construction_registers_region_metric_keys`。✅

## 3. 陷阱纪律

- **params 面 JSON 纯净**：`test_region_params_stay_json_serializable`——映射产物
  `json.dumps(allow_nan=False)` 往返不抛 + 幂等；掩码 ndarray 只走 `ctx.state["region_masks"]`
  （F13 通道），永不进 params → `_param_fingerprint` 不受影响。✅
- **坐标系**：region.* 只落 params（prompt 字符串键），掩码坐标适配完全在 F13 适配器内，
  F14 改动零接触掩码数组（diff 证实仅注册表/联动区 3 hunks，掩码区未碰）。✅

## 4. e2e 闭环真实性（M1 语义正确性核心证据，逐行审）

- `test_e2e_region_rule_closed_loop`：**真 SinglePhotoLoop.run + 真 load_rules(region_rules.yaml) +
  MockSegmenter 掩码 + 真 decide**——三层断言：①trace decide 事件 rule_ids 含
  region_sky_exposure_001；②result.params 嵌套落位+enabled+JSON 纯净；③**闭环回读**：loop 自身
  测量链 sky 亮度降幅 >5（掩码→测量→决策→映射→渲染→测量全环）。✅ 真实闭环
- `test_e2e_region_effect_is_localized_pixel_change`：sky 核心区（rows 0-20）变暗 +
  **远离羽化带地面行（rows 40-64）逐位不变**（np.array_equal）——F12 软混合 m=0 恒等 +
  羽化纪律的像素级证明。✅ 局部性成立

## 5. 裁决核验（region 规则不入 DEFAULT_RULES）

- **源级**：`decide/rules/__init__.py` DEFAULT_RULES 仍 5 条（exposure/highlight/crop/tone_clarity/
  color），无 region_rules.yaml；5 个默认规则文件 grep 零 region 引用 → 默认 decide 输出不可能
  含 region 键。✅
- **代码路径**：新增 elif 仅匹配良构 region.\* 键，非 region 键走原分支不变；指标键注册仅影响
  lint 不影响规则求值。✅
- **镜像**：configs/rules/region_rules.yaml 与 src 副本 `cmp` 逐字节一致，且有测试钉死。✅
- **qa 裁决意见**：保守选择（不入默认包）**正确**——region 规则一旦入默认包，任何带掩码渲染的
  默认 decide 都会开始改默认出图（行为默认变更），须独立批准；首版显式加载语义合 M1 验收定位。

## 6. 复跑与共享树红旗

```
tests/unit/test_decide_region_wiring.py                    → 17 passed（0.52s）
邻域 236 组（黑板清单）                                    → 226 passed / 10 failed
  └ 失败 100% 集中 test_patch_protocol.py（bands 通道族）
邻域排除 test_patch_protocol.py                            → 210 passed / 0 failed ✅
tests/unit/test_build_project_graph.py                     → 18 passed（F12 尾巴已修 ✅）
```
- **红旗定位（非 F14）**：`src/pixo/agent/patch_protocol.py` 当前为 **M（dev-2 F09 在飞中途态）**，
  :214 `return _bands_reject_reason(value, stage)` 引用未绑定局部变量 `stage` →
  `UnboundLocalError`，单文件独跑即 11 红（与执行顺序无关，qa 三种顺序复现）。dev-3 报 236 全绿
  时该文件尚未被开改——**失败为共享树并行 F09 中途态，不属 F14**。
- 处置：不在本门禁修（F09 域，dev-2 在飞）；**F09 定向门禁须复验该 11 项转绿**，若 F09 交付时
  仍红即为阻断项。已知会队长。

## 7. 观察项（不阻断）

1. `register_metric_keys` 进程级单调增长（构造 loop 永久加键）：合 t40 守卫设计（生产键集），
   strict lint 语义仍成立；测试隔离层面未见实证风险（dev-3 全量 unit 1276 绿 + qa 复跑绿）。
2. exposure 限流器波及 region.\*.exposure 正向提亮（既有 `_is_exposure_param` 语义，黑板遗留 2
   已登记，天空压暗场景不受影响）。
3. region 键 delta 累加基线恒 0（v1 已知，首版规则 mode=set 规避，黑板遗留 3）。

## 8. commit 放行清单

- **F14 批**：loop.py（region 分支 + `_REGION_*` 常量 + `__init__` 键宇宙注册——注册表/联动区，
  掩码区零触碰）+ src/pixo/decide/rules/region_rules.yaml + configs/rules/ 镜像 +
  tests/unit/test_decide_region_wiring.py（17 例）+ tests/unit/test_build_project_graph.py（F12 尾巴
  一行机械修）
- 可与 F15（gate_cases region case + harness samples + render/README）攒 M1 收官批；
  F08 批（在飞 gate 文件）与 F14 批文件不相交
- 前置提醒：F09 交付前共享树带 patch_protocol 11 红（§6），分批 commit 时注意勿混入

> 门禁章：qa 2026-09-07T01:52:58+08:00 — F14 PASS，零修复，裁决核验通过（默认行为零变化，
> 保守不入默认包正确）；M1 三块（F12/F13/F14）门禁全部收官。
