# R15 测试报告 —— 预览掩码供给（region supply）+ 分层复权

> tester 2026-09-08。被测版本：master @ 6f8f9c4（R14 已提交）+ 工作树 R15 未提交改动
> （`src/pixo/service/runtime.py`、双 `region_rules.yaml`、`tests/unit/test_decide_region_wiring.py`、新增 `tests/integration/test_region_supply.py`，与 r15-stream-2 一致）。
> 开测前置：r15-stream-1.md（54 张试水+复权建议）、r15-stream-2.md（供给实现+7 测试）齐全，准予开测。
> 测试资产（可重复执行）：`.artifacts/_r15_supply_e2e.py`（服务级四相位）、`.artifacts/_r15_phaseC_diag.py`（B1 归因诊断）。

## 0. 结论一览

| 项 | 结果 |
|----|------|
| 1a 供给集成测试复跑（test_region_supply.py） | **7/7 passed**（含真权重 e2e，未 skip） |
| 1b 服务级闭环（真实 uvicorn HTTP，四相位） | **14/15 passed**——唯一 FAIL 即 **Bug B1 的正确检出** |
| 2 复权断言（test_decide_region_wiring.py） | **26/26 passed**（任务书写"40"，实际收集 26，见 2.1）；双镜像 sha256 一致；三要素断言在位 |
| 3 全量回归 `python -m pytest tests -q -m "not e2e"` | **1522 passed, 5 skipped, 1 xfailed, 0 failed**（= R14 基线 1515 + 供给 7） |

**判定：复权断言与全量回归 GO；供给功能链路（懒触发/缓存/降级/mock 死锁/缺省关）GO；但状态语义存在 P1 虚报（Bug B1：全零掩码被报 available=True），退 dev-2 修复后须回归 `_r15_supply_e2e.py` 相位 C。**

---

## 1. 供给 e2e

### 1.1 集成测试复跑

```
$ python -m pytest tests/integration/test_region_supply.py -v --tb=short
test_supply_default_off PASSED                        # 缺省关：不尝试分割
test_supply_lazy_once_then_cached PASSED              # 懒触发一次→缓存（calls==1）
test_supply_mock_segmenter_never_attempts PASSED      # mock 永不尝试
test_supply_empty_masks_reports_segmenter_no_masks PASSED
test_supply_failure_degrades_without_error PASSED     # 异常降级不重试
test_supply_then_patch_then_render_uses_masks PASSED  # patch 不重分割
test_real_weights_supply_e2e PASSED                   # 真权重+真 RAW
======================== 7 passed, 1 warning in 20.20s ========================
```

### 1.2 服务级闭环（真实 uvicorn HTTP，非 TestClient）

脚本 `.artifacts/_r15_supply_e2e.py`：每相位独立 runtime/app（env 构造前设置），httpx 走真实 socket，渲染对比用 png16 无损。

```
$ python .artifacts/_r15_supply_e2e.py
R15 supply service e2e: 14/15 passed, 1 failed
```

| 相位 | 环境 | 验证点 | 结果 |
|----|----|----|----|
| A 缺省关 | supply 未设 + mock | GET /region → `available=False, reason=masks_not_injected`；`session.region_masks` 保持 None（未尝试） | PASS |
| B 开但 mock | `PIXO_REGION_SUPPLY=1` + mock | 门禁死锁 `segmenter_type=="multi"` → 永不尝试（region_masks None） | PASS |
| C 开+multi 真权重 | `PIXO_REGION_SUPPLY=1 PIXO_SEGMENTER=multi` | 首次 GET /region 懒触发分割 4.62s → `available=True, prompts=['face','plant','sky']`（排序）；`region_masks_source=segmenter`；PUT region_adjust → canonical 回读 -0.5 + 响应 region 节 available；二次 GET 0.00s（缓存不重分割） | PASS（除渲染变化项=B1 检出） |
| D Route B 合成掩码闭环 | 同上 + 合成半图掩码注入 | 掩码区 Δ=-10.68、亮度比 0.8532 ≈ 2^(-0.5/2.2)=0.8542（±15%）；非掩码区 x≥128 逐位不变 | PASS |

**Phase C 的"渲染变化"FAIL 即 Bug B1 的正确检出**：真掩码全零时渲染零像素变化是正确的渲染行为，错在状态不该报 available（见第 4 节）。渲染链路本身由相位 D 证明无恙。

---

## 2. 复权断言

### 2.1 计数勘误

`test_decide_region_wiring.py` 实际收集 **26 项，26 passed**（0.61s）。任务书所写"40"与实际不符：R15 对该文件仅做**断言更新**（git diff：`-0.375`→`-0.75`、`"-0.25 *"`→`"-0.5 *"`、docstring 沿革），无新增用例（10 insertions / 9 deletions）。R13 记录 21 项，R14 warmth 批增至 26 项。

### 2.2 YAML 双镜像

```
$ sha256sum src/pixo/decide/rules/region_rules.yaml configs/rules/region_rules.yaml
4194f07ff48f78f9b592954ebcdb8acf785403e3062b913ffead9fd653581477  src/pixo/decide/rules/region_rules.yaml
4194f07ff48f78f9b592954ebcdb8acf785403e3062b913ffead9fd653581477  configs/rules/region_rules.yaml
```

测试层另有更强断言：`test_region_rules_yaml_loads_and_package_mirror_consistent` 钉死**字节级相等**（`read_bytes()` 比对）+ 双 rule_id 顺序。

### 2.3 三要素断言在位（`test_region_rules_activation_guard_and_trial_coefficients`）

| 要素 | 断言 | 位置 |
|----|----|----|
| sky 全量复权 -0.5 | `"-0.5 *" in formula`；行为断言 `test_sky_rule_fires_negative_compensation`：`-0.5*225/150 = -0.75`（pytest.approx） | wiring:272 / 226 |
| plant 维持试水 0.2 | `"0.2 *" in formula` | wiring:273 |
| 覆盖率护栏 0.70 | 两规则 `condition.all` 中 `area_ratio` 条件 `op=="lt"` 且 `value == approx(0.70)` | wiring:276-278 |
| （附带）DEFAULT_RULES 激活 | `region_rules.yaml` 在 `DEFAULT_RULES` | wiring:281 |

复权依据链在位：规则文件注释引用 `.artifacts/region_trial_54.md`（54 张，触发 28/54，零护栏拦截，QC 48%→57%）。

---

## 3. 全量回归

```
$ python -m pytest tests -q -m "not e2e"
1522 passed, 5 skipped, 1 xfailed, 13 warnings in 190.09s (0:03:10)
```

- 对齐预期：R14 基线 1515 + R15 新增 7（test_region_supply.py）= **1522 passed，0 failed**。
- wiring 断言更新零计数变化；5 skipped / 1 xfailed 与 R14 形态一致。

---

## 4. Bug 清单

### B1（P1，退 dev-2）：供给把全零掩码当有效掩码注入，状态 API 虚报 available=True

- **现象**：真权重供给（`PIXO_SEGMENTER=multi PIXO_REGION_SUPPLY=1`）对真实 RAW `DSC_5236.NEF` 分割后，三个 prompt 掩码**全部全零**（face/plant/sky 覆盖率均 0.0000，min=max=0），但 `GET /region` 返回 `available=True, prompts=['face','plant','sky'], reason=None`。UI 将呈现"掩码就绪 · 3 个区域"、三滑杆可操作，实际拖动任意滑杆渲染零像素变化——**R14 状态 API 要消灭的"滑杆调了静默失效"陷阱在供给路径复活**。
- **证据**（`.artifacts/_r15_phaseC_diag.py` 输出）：
  ```
  face:  shape=(341, 512) dtype=uint8 min=0 max=0 覆盖率=0.0000
  plant: shape=(341, 512) dtype=uint8 min=0 max=0 覆盖率=0.0000
  sky:   shape=(341, 512) dtype=uint8 min=0 max=0 覆盖率=0.0000
  192 级 patch(sky -0.5EV)前后: mean Δ=0.000000 逐位相同=True
  合成对照（半图 sky 掩码）: 左半 mean Δ=12.44（stage/适配器本身无恙）
  ```
- **定位流**：segformer 纯类别匹配（`segformer_scenes.py:84` `np.isin(seg, ids)*255`，无覆盖率阈值），该 512 渲染帧无 sky/plant 类像素 → 全零掩码；face 无可用后端（uniface 合规门控未注册）→ 零掩码降级。`runtime.py _ensure_session_region_masks`：`if isinstance(masks, dict) and masks` —— 非空 dict 即注入，不查覆盖率；`_region_status_of`：`available = bool(prompts)` —— 不查掩码内容。dev-2 自己定义的 `segmenter_no_masks`（"供给已试、无区域掩码"）只认**空 dict**，零覆盖 dict 落入 available 分支。
- **期望/实际**：期望全零掩码不注入（或状态层过滤零覆盖 prompt）→ `available=False, reason="segmenter_no_masks"`；实际 `available=True` + 3 个假区域。
- **影响面**：数据相关——任何 segformer 找不到 prompt 类别的照片（正常场景，非边缘）都会触发。R15 试水语料 54 张中 26 张零区域内容，量级不可忽视。
- **修复方向建议**（归 dev-2）：注入前按覆盖率过滤（如 `mask.max() > 0`），全空落 `region_masks={}` → 既有 `segmenter_no_masks` 语义生效；或在 `_region_status_of` 过滤零覆盖 prompt。
- **回归要求**：修复后重跑 `python .artifacts/_r15_supply_e2e.py`，Phase C 渲染变化项须转为 PASS（全零掩码 → available=False），且 `test_supply_empty_masks_reports_segmenter_no_masks` 不回归。

### 观察项（非缺陷）

- O1：`test_real_weights_supply_e2e` 在供给后用**合成半图掩码覆盖** region_masks 再断言变暗（"收紧为左右半图, 断言可控"）；`test_supply_then_patch_then_render_uses_masks` 用 StubSegmenter 且不断言渲染像素。即 7 项测试的"渲染生效"证据全部跑在合成掩码上，真掩码渲染链路在本轮由 tester 服务级相位 C/D 首次覆盖——这正是 B1 的暴露路径。建议 dev-2 修复 B1 后在 e2e 中补一条"真掩码全零 → available=False"断言钉死语义。
- O2：`face` prompt 在默认合规门控下无后端（uniface 为 internal_development_only，需 `PIXO_ALLOW_RESTRICTED=1`），供给默认场景恒为零掩码降级 warn——供给 prompts 表可议是否默认剔除 face（产品决策，不强求）。
- O3：供给实测成本与 dev-2 报告同量级（本机冷分割 4.62s，进程热后更快；dev-2 报告 17.70s 冷/0.73s 热），缺省关裁决合理。

---

## 5. 复现命令汇总

| 项 | 命令 |
|----|----|
| 供给集成测试 | `python -m pytest tests/integration/test_region_supply.py -q` |
| 真权重 e2e 单跑 | `PIXO_SEGMENTER=multi PIXO_REGION_SUPPLY=1 python -m pytest "tests/integration/test_region_supply.py::test_real_weights_supply_e2e" -q -s` |
| 复权断言 | `python -m pytest tests/unit/test_decide_region_wiring.py -q` |
| 服务级四相位 | `python .artifacts/_r15_supply_e2e.py`（依赖 K:/data/photo/0711 语料与真权重） |
| B1 归因诊断 | `python .artifacts/_r15_phaseC_diag.py` |
| 双镜像 | `sha256sum src/pixo/decide/rules/region_rules.yaml configs/rules/region_rules.yaml` |
| 全量回归 | `python -m pytest tests -q -m "not e2e"` |
