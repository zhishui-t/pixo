# RAW 金样本团队重验报告（F06）— gate_defaults 4 features × 6 样本

> 执行：qa｜2026-09-07T01:03:32+08:00｜HEAD = master @ f357b35（工作树干净，仅 .gitignore 加忽略 .agent-team/，与金样本无关）
> 任务：用户拍板的金样本终审方式，关闭 `t108-auto-verified (主代理复核, 待用户终审)` 挂起项。
> 命令：`python src/pixo/render/tools/gate_golden.py compare --samples D:/tmp/pixo_t108/samples.json --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512`

## 1. 结论速览

**24/24 FAIL（0 PASS）——真漂移（非样本缺失），按规程阻断 F10，报队长裁决。**

漂移定性：**基线过期（stale baseline）**，非本轮回归——基线生成（0e8d2a5，08-27 09:14）落后
当前 HEAD 30+ 提交，期间含 6 个已各自验收的**运行时级**渲染变更（时间线见 §4）；
该基线族未接入 pytest（grep tests/ 零引用，手动工具门禁），故 1396 全量绿与本 FAIL 不矛盾。

## 2. 基线完整性（先于像素判读）

- 磁盘基线 = git 提交原件：49 文件（48 npy + manifest.json）全部 git 跟踪，
  `git status data/golden/` 干净，基线自 0e8d2a5 后未被改动。
- sha256 独立复核（工具同口径 = 数组字节 `ascontiguousarray(arr).tobytes()`，工具源码
  gate_golden.py:158-159；compare 侧 :350-353 同法重算）：**48/48 全匹配，0 不匹配**。
- 运行期 stderr 仅 1 条良性告警：`[whitebalance] wb_B=1.490 超出暖度标定适用域
  [1.758, 2.398] (configs/calibration/warmth_curve.json); 仍用曲线`——此适用域来自
  3fbe56d（09-04 20:20 新表入库），**直接证明当前运行时加载的是基线生成之后更换的标定表**。

## 3. 逐 case 结果（u8 阈值 ≤1/255；u16 列为参考）

| feature / sample | u8_max | u16_max | verdict |
|---|---:|---:|:---:|
| wb_as_shot_default/night_lowlight | 55 | 14029 | FAIL |
| wb_as_shot_default/day_normal | 55 | 14202 | FAIL |
| wb_as_shot_default/high_key_bright | 41 | 10670 | FAIL |
| wb_as_shot_default/portrait_tele | 91 | 23442 | FAIL |
| wb_as_shot_default/wide_angle | 57 | 14556 | FAIL |
| wb_as_shot_default/high_contrast | 62 | 15849 | FAIL |
| exposure_auto_default/night_lowlight | 55 | 14029 | FAIL |
| exposure_auto_default/day_normal | 55 | 14202 | FAIL |
| exposure_auto_default/high_key_bright | 41 | 10670 | FAIL |
| exposure_auto_default/portrait_tele | 91 | 23442 | FAIL |
| exposure_auto_default/wide_angle | 57 | 14556 | FAIL |
| exposure_auto_default/high_contrast | 62 | 15849 | FAIL |
| compose_param/night_lowlight | 53 | 13627 | FAIL |
| compose_param/day_normal | 54 | 13658 | FAIL |
| compose_param/high_key_bright | 40 | 10083 | FAIL |
| compose_param/portrait_tele | 92 | 23570 | FAIL |
| compose_param/wide_angle | 57 | 14430 | FAIL |
| compose_param/high_contrast | 62 | 15714 | FAIL |
| clarity_default/night_lowlight | 55 | 14029 | FAIL |
| clarity_default/day_normal | 55 | 14202 | FAIL |
| clarity_default/high_key_bright | 41 | 10670 | FAIL |
| clarity_default/portrait_tele | 91 | 23442 | FAIL |
| clarity_default/wide_angle | 57 | 14556 | FAIL |
| clarity_default/high_contrast | 62 | 15849 | FAIL |

关键形态证据：wb_as_shot / exposure_auto / clarity 三组每样本 u8_max·u16_max **逐值相同**
（如 portrait_tele 三组均 91/23442）——三条 feature 变体只改各自 stage 参数，差异完全来自
**公共默认链**（解码/白平衡/曝光/影调等全局路径），排除单 stage 偶发回归；compose 因裁剪
像面对齐略有差（92 vs 91）同量级。u8 max 40-92 / 255 为全局可见量级，与「整链演进而非局部回归」一致。

## 4. 漂移源时间线（基线后的运行时级渲染变更，全部已各自验收）

| 提交 | 时间 | 变更 | 与基线关系 |
|---|---|---|---|
| **0e8d2a5** | **08-27 09:14** | t108 基线生成（本基线） | — |
| 3925b69 | 08-27 10:04 | colorcal Lab 路径 float 化（0.81-1.08 ΔE 级回收） | 基线后 **50 分钟** |
| 4388f37 | 08-27 11:10 | stylize LUT native float 四面体内核（精度回收） | 同日 |
| e3c8f7c | 08-27 11:11 | 标定加载统一治理 | 同日 |
| f48d453 | 08-27 11:11 | 管线框架 domain 后验/ctx.mode/精度修复 | 同日 |
| bca52ed | 09-04 10:24 | 阶段一自研渲染管线（Oklab 双轨 + RP-CCM 并联，默认链主切换） | 最大默认路径变更 |
| 3fbe56d | 09-04 20:20 | 标定新表入库 configs + cal_ev_weights 修复 | §2 stderr 域告警即其证 |
| f357b35（HEAD） | 09-05 09:32 | t64 HSM→OKLCh 接线收口（huesat 默认关，本基线路径不触） | 无关（列全供排查） |

即：**基线与 HEAD 匹配的窗口不足 1 小时**。其后每个提交均有独立验收（阶段一 QA GO、
阶段二终审 GO、t64 全量回归绿），漂移是**已验收演进的累积**，本报告未发现任何未验收/回归性变更的迹象。

## 5. 对 F10 的阻断与放行条件

- 按任务规程：真漂移 → **阻断 F10（oklch 第一批切换）**，直至下列任一路径完成：
  1. **推荐路径**：队长在 pre-F10 的 HEAD 重生成 gate_defaults 基线（generate 权在队长，
     本任务未执行）→ qa 复跑 compare 预期 24/24 PASS → 更新 manifest reviewer 关闭挂起项
     → F10 放行；F10 切换后再复跑 compare，以新基线判「零漂移」（设计 F10 验证链 c 项原语义恢复）。
  2. **备选（须队长明示采纳）**：不重生基线，F10 验证链 c 项改为相对判据——「切换前后各跑
     一次本 compare，两组逐 case u8/u16 漂移向量完全相等」。可判 F10 自身零影响，但弱于
     金样本绝对语义，且挂起项（reviewer 终审）仍需重生成才能关闭。

## 6. manifest reviewer 字段处置声明

**未更新**（保持 `t108-auto-verified (主代理复核, 待用户终审)`）。原因：本轮重验结论为
FAIL，在基线重生成并复验 PASS 前写入 `qa-reverified 2026-09-07` 会构成「通过性」虚假戳记
（qa 纪律：不带病放行）。待 §5 路径 1 完成后由 qa 落笔。

## 7. 附：F02 基线 skip 清单核对（队长托付项）

全量复跑 `python -m pytest tests -q -m "not e2e" -rs`：**1396 passed / 5 skipped / 1 xfailed，
191.48s**——与队长存证一致。5 个 skip（全部良性，环境/治理类）：

1. test_gate_e2e_ab.py:20 — RAW_PATH not set（语料 env，历史）
2. test_gate_e2e_perf.py:49 — RAW_PATH not set（历史）
3. test_learned_isolation.py:48 — `src/pixo/render/learned/` 未建（阶段三红线预铺隔离门，目录落地即生效）
4. test_proxy_metrics.py:113 — got empty parameter set (raw_path)（语料未注入 env）
5. test_sapiens_body.py:267 — 无 sapiens 本地权重（PIXO_SAPIENS_MODEL 未设）

**4→5 的新增项 = 第 3 项**（test_learned_isolation.py:48），引入提交 3bcccd3（09-04 23:11，
阶段三首块）——晚于 09-04 QA 终审运行（171s 那次）当日晚间落库，故当时仍为 4 skip；
为**主动预铺的门禁 skip**（治理设计如此），非测试腐化。签认已落 baseline-f02.md。

## 8. 复现命令（首轮，对 08-27 旧基线）

```
python src/pixo/render/tools/gate_golden.py compare --samples D:/tmp/pixo_t108/samples.json --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512
```
（首轮输出 RESULT: FAIL，详见 §1-§4；基线 sha256 复核口径见 §2）

---

## 9. 重生成与复验（终轮）— F06 收口

> 队长裁决执行：基线已在 pre-F10 工作树重生成，qa 于 2026-09-07T01:06:58+08:00 复验收口。

### 9.1 重生成基线构成（qa 独立核对，非仅采信声明）

- **树构成**：HEAD = f357b35（未新提交），工作树增量 = F03 vision 删除面
  （`src/pixo/vision/person.py` 删除；health.py / __init__.py / manifests/vision_models.json /
  3 个 vision 测试 / LEARNED_BACKEND_GOVERNANCE.md 修改）+ F01/F18 文档（changelog.md /
  tech_debt.md）+ 基线 48 npy 与 manifest 重生成 + .gitignore（忽略 .agent-team/）。
- **零渲染链改动核对**：`git status -- src/pixo/render/ src/pixo/pipeline/ configs/` 为空——
  重生成树对渲染链/管线/标定 configs 零改动，与队长声明一致（vision 域不在渲染链上）。
- **manifest**：reviewer 曾为 `round9-regen@f357b35 (队长重生成, 待qa复验)`；4 features ×
  6 samples、long_edge 512 结构不变；manifest 落盘时间 2026-09-07T01:05:54。
- **生成命令**（generate 形态，工具 docstring 多样本口径）：
  ```
  python src/pixo/render/tools/gate_golden.py generate --samples D:/tmp/pixo_t108/samples.json --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512 --features wb_as_shot_default,exposure_auto_default,compose_param,clarity_default --reviewer "round9-regen@f357b35 (队长重生成, 待qa复验)"
  ```
  （生成由队长执行；qa 复核的是产物构成与下述复验结果）

### 9.2 复验结果：24/24 PASS，逐位一致

```
python src/pixo/render/tools/gate_golden.py compare --samples D:/tmp/pixo_t108/samples.json --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512
```
- 4 features（wb_as_shot_default / exposure_auto_default / compose_param / clarity_default）
  × 6 样本（night_lowlight / day_normal / high_key_bright / portrait_tele / wide_angle /
  high_contrast）= **24/24 PASS，u8_max = 0 且 u16_max = 0（全 case 逐位一致）**，
  RESULT: PASS——同树生成-比对的确定性成立，重生成基线与当前渲染逐位吻合。
- 独立 sha256 复核（数组字节口径，同 §2）：重生成基线 **48/48 匹配** manifest 记录。
- 运行期 stderr 仅 1 条既有良性告警（warmth 适用域外垫片，同 §2，与首轮一致）。

### 9.3 挂起项关闭声明

`data/golden/reference/render_bench/goldens/gate_defaults/manifest.json` 的
`t108-auto-verified (主代理复核, 待用户终审)` 挂起项**关闭**：用户拍板的终审方式
（本轮团队重验）已由本报告双轮完成（首轮 FAIL 定位基线过期 → 队长重生成 → 终轮 24/24
逐位 PASS）。manifest.reviewer 终值（qa 落笔）：

**`qa-reverified 2026-09-07 (regen@f357b35)`**

### 9.4 F10 放行判定

**F06 → F10 依赖解除，F10 放行。**依据：
1. 设计 F10 验证链 c 项「RAW 金样本复跑绿」的前置（基线新鲜且当前树 24/24 逐位 PASS）已就绪；
2. F10 落点（hsl.py:34 / split_tone.py:38-43 的 default_params）不在四条 RAW 默认路径的
   参数面内（wb as_shot / exposure auto / compose / clarity，hsl/split_tone 缺省 enabled=False
   且无显式参数），预期切换后复跑仍逐位零漂移——该复跑作为 F10 专项门禁证据之一执行；
3. 首轮 §5 的阻断条件（基线过期）已由队长重生成消除。

