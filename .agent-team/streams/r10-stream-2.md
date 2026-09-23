# R10 stream-2 —— oklch 第二批切换（skin+colorcal 缺省翻转）

> dev-2 · 2026-09-07 · 状态：**代码+断言已落，四项验证已跑完；1 项停报发现（film_pro_400h 存量卡破线）+ RAW 基线需重生成——等队长裁决后收口**

## 1. 代码 diff（落点两处，除断言修订外零行为改动）

| 文件 | diff |
|---|---|
| `src/pixo/render/modules/skin.py` | default_params `"color_domain": "hsv"` → `"oklch"`（schema/模块/行内注释 3 处语义同步） |
| `src/pixo/render/modules/color_cal.py` | default_params 末键 `"hsv"` → `"oklch"`（注释注明 F10 第二批 + native oklch v1.5.0 前置） |

## 2. 断言修订清单（2 项，零删除）

| 测试 | 修订语义 |
|---|---|
| `test_skin.py::test_skin_stage_registered_order_and_domain` | 缺省表期望 `color_domain` "hsv"→"oklch"（t52 §3.4 预告的「skin 那 1 项」，第一批不动、本批翻转） |
| `test_native_colorcal.py::test_full_path_float_precision_sentinel` | 指针显式化：cfg 补 `"color_domain": "hsv"`——本哨兵锁 Lab 链精度（W4 结论口径）；oklch 链精度由 `test_native_colorcal_oklch.py` 专属覆盖（内核↔纯 Python 参考、掩码隔离逐位） |

**F09 同源/parity 测试零修订自动绿 ✓**（3 passed，`git diff` 零改动——它们只翻 HslStage，与 skin/colorcal 无关，同源设计兑现）。其余 hsl/split_tone 缺省断言（第一批修订件）零再动。

## 3. 四项验证证据

### a) gate --check —— ⚠️ 2 处漂移（1 预期 + 1 计划外，已归因）
```
default_dispatch.sha256: b3352650… → ab12b0d4…   （case1，预期：四 stage 全缺省三度观测）
region_adjust.sha256:    afbd7ebe… → d354ff83…   （计划外，见归因）
```
- **case2 (card_portra_400) 及其余 17 条零漂 ✓**（A1 卡级锚定未破）
- **region_adjust 归因**（进程内单翻实验）：**100% 由 colorcal 翻转驱动**——仅回翻 colorcal 即复现全量漂移 max|Δ|=0.00708（≈1.8/255）；仅回翻 skin 贡献恰为 0（该 case 合成图的标准肤色补丁上两椭圆掩码全等）。机理：colorcal 双 native 内核（Lab vs OKLab 域）在该 case 链上真实输入的 ULP/色域处理域差被下游放大。
- 定性：region_adjust case（F15 资产）ride 在 DEFAULT_STAGES 缺省链上，任何上游缺省翻转必漂——与 case1 同族（缺省链可观测性），非 A1 破线。**该 case 与 case1 一样需要 v3 重生成（基线归队长）**；中期建议（下轮，非本批）：该 case 的 params 显式钉上游涉域 stage，使其只观测 region_adjust 自身内核。

### b) 23 存量卡渲染字节级 —— ❌ **22/23，film_pro_400h 破线（停报项）**
- 22 张 vs ef4473d 态基线（f10 manifest + tester manifest 双对照一致）：float32 字节级全等。
- **film_pro_400h（唯一无 skin 键的存量卡）漂移**：
  - 机制铁证：进程内把 skin 缺省回翻 hsv → 渲染 sha **精确回到基线** 5c22aab9…（漂移 100% 由 skin 缺省翻转引起）
  - 根因：F07 钉域口径=「凡带键即钉」，该卡 params 无 skin 键（F07 计数 skin=22 的那个特例）→ skin 未钉 → 批 2 翻转后其默认磨皮从旧 Lab 椭圆切到重拟合 OKLab 椭圆
  - 量级：max|RGB|=0.179；**ΔE2000 max 19.6 / median 0.144；>JND(2.3) 像素 516/12288（4.2%）**
- **修复选项（队长裁决，涉及 F07 口径扩展=卡 JSON 变更，dev-2 未动）**：
  1. （最小修，建议）film_pro_400h 补 `"skin": {"color_domain": "hsv"}`——merge 自动补 enabled/strength 缺省，与旧行为逐位同，恢复 23/23；F07 口径扩展为「无 skin 键卡单点补钉」并在 test_film_cards_oklch 计数同步（skin 22→23）
  2. 接受漂移更新基线——破 A1「存量卡零迁移」承诺，不建议

### c) RAW 金样本 24 case —— ❌ 24/24 FAIL（u8_max 2–33），已归因
```
wb_as_shot/exposure_auto/compose_param/clarity_default × 6 样本 全 FAIL
u8_max 按样本: night_lowlight 30 / day_normal 17 / high_key_bright 20 /
portrait_tele 22 / wide_angle 13 / high_contrast 3（四特征同值——链尾同一渲染）
```
- **归因（进程内三组分离实验，工具 sanity 全回翻=PASS 排除假阳性）**：
  - 仅回翻 skin（colorcal=oklch）→ **24/24 PASS**
  - 仅回翻 colorcal（skin=oklch）→ FAIL，逐 case 数值与双翻完全一致
  - ⇒ **漂移 100% 由 skin 缺省翻转驱动；colorcal 翻转在 RAW 默认链零独立贡献**
- 机理（修正队长预判「无人像理论≈0」）：skin 缺省 enabled=True + 无 scene 分类时 3% 门限，而**旧 Lab 椭圆在这些图上大面积误判肤色**（F11 实测 night_lowlight A 覆盖 79%、wide_angle 53%）→ 磨皮实际作用于默认链；重拟合 OKLab 椭圆改变作用区 → 输出变化（u8 至 33）。方向上是**修正旧椭圆过度磨皮**（F11: OKLab 误报更低），属预期语义变化，但量级不是 ≈0。
- **处置（队长）**：RAW 基线 b187d27 → 重生成新基线 + 留 v_old→v_new u8 差异对比（本报告已留全量数值）；若需「RAW 零漂先行验证」，A 组实验（仅切 colorcal）证明 colorcal 单切零漂——可作为分步切换的备选路径数据。

### d) colorcal oklch 性能验收 —— ✅ PASS
```
缺省参数 512px:  hsv native 30.8 ms | oklch 31.2 ms  → 1.02×
意图参数 512px:  hsv native 10.9 ms | oklch 21.6 ms  → 1.99×
对照 F11 Python 路径 131 ms → 实测 31.2 ms，native 量级验收线（<40ms）PASS
```

## 4. 定向测试汇总
- tests/unit：1295 passed / **1 failed（test_theta_io::test_skin_angle_initial_keeps_fit_convention）** / 3 skipped / 1 xfailed
  - 该失败经 stash 验证**先于本次改动存在**（dca189c 重拟合改 SKIN_OKLAB_ANGLE 0.191122→0.196323 rad，测试仍钉旧角 10.9505°，运行时已 11.2485°）——dev-1 范围遗留，记转办
- tests/integration（not e2e）：112 passed
- tests/regression/test_gate_golden（gate and not gate_e2e）：2 passed + 2 FAILED（case1+region_adjust 基线待 v3，设计内过渡态）

## 5. 等队长裁决清单
1. **film_pro_400h 补 skin 钉**（选项 1 建议采纳→卡 JSON 一行 + F07 测试计数 22→23）→ 恢复验证 b 23/23
2. **RAW 基线 gate_defaults 重生成**（skin 翻转的预期语义变化，u8 对比数据已留证）
3. **gate 合成 case1 + region_adjust v3 重生成**（region_adjust 漂移归因报告见 §3a）
4. theta_io 旧角度断言转 dev-1（或记债）
5. 以上落定后 R10 定向复验 + qa 专项门禁收口

## 6. 复现命令
```
python tests/regression/goldens/generate_gate_goldens.py --check
PYTHONPATH=src python .artifacts/_f07_pin_hsv_render_check.py <out.json>
python src/pixo/render/tools/gate_golden.py compare --samples D:/tmp/pixo_t108/samples.json --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512
python -m pytest tests/unit/test_patch_protocol.py tests/unit/test_skin.py tests/unit/test_native_colorcal.py -q
```

---

## 7. 三项裁决执行（R10 收口）

### 裁决 1：film_pro_400h 补 skin 钉（最小修采纳）——✅ 23/23 恢复
- `configs/styles/films/film_pro_400h.json`：params 增 `"skin": {"color_domain": "hsv"}`（colorcal 与 stylize 之间，沿卡序约定；merge 自动补 enabled/strength 缺省 → 与旧行为逐位同）
- **复验**：`_f07_pin_hsv_render_check.py` 重跑 → vs f10 manifest 与 tester (ef4473d) manifest **均 23/23 float32 字节级全等**；film_pro_400h sha 回基线 `5c22aab9…`，钉域条目 69→70（该卡 pinned=[skin, colorcal]）
- F07 不变量计数同步：`test_film_cards_oklch` skin 22→23（docstring 注明 R10 裁决缘由）
- 定向：test_film_cards_oklch + test_film_cards 36 passed

### 裁决 3 附带：theta_io 旧拟合角断言修复（授权归 F10 断言族）
- `tests/unit/test_theta_io.py::test_skin_angle_initial_keeps_fit_convention`：
  硬编码 10.9505（旧拟合 0.191122 rad）→ **11.2485**（= round(degrees(0.196323),4)，dca189c 重拟合初值源 configs/color/skin_oklab.json 的现值，已验证 round4==源文件值）——dev-1 更新源文件漏改断言，非行为问题

### 队长并行件复验（基线落盘后）
- gate 合成金样本 v3：`--check` → **CHECK: OK（20 features 与现有 manifest 一致）**；test_gate_golden（gate and not gate_e2e）**4 passed**（断言已随 F15 后口径为 20）
- RAW gate_defaults v_new：compare → **24/24 PASS（u8_max=0 全零漂）**

### 最终定向汇总（R10 收口态）
- tests/unit：**1296 passed, 3 skipped, 1 xfailed, 0 failed**（含 theta_io 修复）
- tests/integration（not e2e）：**112 passed**
- tests/regression/test_gate_golden（gate and not gate_e2e）：**4 passed**
- 23 存量卡：**23/23 字节级不变**（双基线对照）
