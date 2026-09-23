# R21 stream-2 交付报告 — F03 公共指标 API + F04 评分器适配器（dev-2）

> 角色：`dev-2`｜阶段 6（开发，两流并行）｜产出时间 2026-09-10
> 上游：`.agent-team/design-r21.md`（**唯一实现依据**；§2.1 / §2.4 / §3 / §4）+ `.agent-team/exploration-r21.md`（§3 / §4 / §6.5 / §6.8）+ `.agent-team/task-brief.md`
> 下游：`tester`（阶段 7）、`QA-checker`（阶段 8）
> **状态：F03 公共 API 与 F04 适配器签名修复全部落地；定向测试 20 passed，邻居回归 112 passed。未提交 git（由队长提交）。**

---

## 1. 改动清单

| # | 文件（域内） | 改动量 | 关键内容 | 对应验收 |
|---|--------------|--------|----------|----------|
| 1 | `src/pixo/pipeline/metrics.py`（**新建**，153 行） | 全部新增 | 四符号：`metrics_for_decide(measurement)` / `METRIC_KEYS`（10 键 = 6 global + 3 顶层代理 + `crop_suggestion_applicable`，**不含区域键**）/ `metric_universe(prompts=("face","sky","plant"))` / `merge_proxy_metrics(measurement, image_rgb)`；`compute_proxy_metrics` 从 `pixo.vision.measure` **直接**导入；无 `pixo.service` 依赖 | F03 ①②③④ |
| 2 | `src/pixo/pipeline/loop.py` | +8 / −30（含 +1 import） | 展平实体搬入 `metrics.py`，`_metrics_for_decide` 变薄 wrapper（保留函数名与 docstring）；模块内调用点不变（原 1393 → 现 **1371**，行号因压缩位移）；`__all__` 未动 | F03 |
| 3 | `src/pixo/pipeline/batch.py` | **仅新增** `__call__`（+30 / −0） | `__call__(self, image_rgb, masks=None) -> dict \| None`：`{"overall": s.overall, **s.dimensions, "source": s.source, "raw_overall": s.raw_overall, "domain_hint": s.domain_hint}`；`s is None → None`；`.score(image_rgb, meta)` 签名与实现**零改动** | F04 |
| 4 | `tests/unit/test_metrics_for_decide_public.py`（**新建**，303 行） | 14 用例 | 验收①~④ + 架构红线/导入来源守卫 | F03 ①②③④ |
| 5 | `tests/unit/test_scorer_adapter_callable.py`（**新建**，159 行） | 6 用例 | 跨层注入：真 `_PixoScorerAdapter`（固定假内层 scorer）→ `SinglePhotoLoop` + `suggest_crop` | F04 ①② |

### 1.1 关键 diff 摘要

`loop.py`（import + 实体搬迁）：
```diff
 from pixo.decide.engine import _locked_params
+from pixo.pipeline.metrics import metrics_for_decide
 from pixo.pipeline.perceptual import JndConvergenceTracker, delta_e_median
@@ def _metrics_for_decide(measurement: dict[str, Any]) -> dict[str, Any]:
-    """把完整测量报告展平为规则引擎可引用的指标 dict。"""
-    if not isinstance(measurement, dict):
-        return {}
-    global_metrics = measurement.get("global") or {}
-    ...                        # ← 30 行实体迁至 pipeline/metrics.py
-    return metrics
+    """把完整测量报告展平为规则引擎可引用的指标 dict。
+
+    R21/F03：实现已公共化为 :func:`pixo.pipeline.metrics.metrics_for_decide`
+    （service 侧装配共用同一口径）；本函数保留为薄 wrapper，维持既有模块内
+    调用点（loop.py:1393）与可能的既有导入不破。
+    """
+    return metrics_for_decide(measurement)
```

`batch.py`（`.score()` 之后、`class MockAgentSelector` 之前插入，无删改）：
```python
    def __call__(
        self,
        image_rgb: np.ndarray,
        masks: dict[str, np.ndarray] | None = None,
    ) -> dict[str, Any] | None:
        """可调用契约（R21/F04）：``scorer(image, masks) -> dict | None``。…"""
        del masks  # 真评分器不消费掩码（同 .score 的 meta 语义）
        s = self.score(image_rgb)
        if s is None:  # 防御：当前 .score 不会返回 None，保持契约完整
            return None
        return {
            "overall": s.overall,
            **s.dimensions,
            "source": s.source,
            "raw_overall": s.raw_overall,
            "domain_hint": s.domain_hint,
        }
```

### 1.2 文件域合规（`git status --short`）

本次改动**仅**：`M src/pixo/pipeline/batch.py`、`M src/pixo/pipeline/loop.py`、`?? src/pixo/pipeline/metrics.py`、`?? tests/unit/test_metrics_for_decide_public.py`、`?? tests/unit/test_scorer_adapter_callable.py`。
`src/pixo/service/app.py` / `runtime.py` / `tests/integration/test_auto_loop_api.py` 的改动是 **dev-1（stream-1）** 的并行产物，dev-2 **未触碰**。未执行任何 git 写操作。

---

## 2. 自测证据（每条验收一行）

| 验收条目 | 命令 | 输出关键行 | 结论 |
|---|---|---|---|
| **F03①** 公共函数 = loop 旧行为逐键一致 | `python -m pytest tests/unit/test_metrics_for_decide_public.py -q` | `14 passed in 2.25s`；`test_public_flatten_matches_frozen_legacy_expectation PASSED`（对**冻结的 17 键期望 dict** 全等，非与 wrapper 自比；另断言 `not_exported_key` / `mask_version` / `global` / `regions` 不泄漏） | ✅ 一致 |
| **F03②** `metric_universe` 覆盖 region_rules 全部引用键 | 同上 + 探针 `D:\tmp\pixo_r21_dev2_probe.py` | 探针：`METRIC_KEYS(10)`、`metric_universe(22) 新增区域键 = [face_*, plant_*, sky_* 各 4 键]`；`test_metric_universe_covers_region_rules_references PASSED`（从 yaml 解析 condition.all[].metric + formula AST 标识符，`referenced - universe - 公式白名单 = ∅`，且反护栏断言 `sky_*/plant_*/preview_overflow_ratio` 确实被引用） | ✅ 覆盖 |
| **F03②负控** 只传 `METRIC_KEYS` 会抛 `DecideError` | `$env:PYTHONPATH='K:\work\project\pixo\src'; python D:\tmp\pixo_r21_dev2_probe.py` | `registry_before = []`；`只传 METRIC_KEYS -> DecideError: 规则公式标识符校验失败: 规则 region_sky_exposure_001: 公式引用未知标识符 'sky_luminance' … ; condition.all 引用未知指标 'sky_luminance'/'sky_area_ratio'/'sky_reliable' …` | ✅ 设计 §2.1 论断成立 |
| **F03③** 显式 `metric_keys=metric_universe(...)` 后 6 文件全加载 | 同上探针 + `test_default_rules_load_with_explicit_metric_universe` | `OK exposure_rule_001.yaml rules=1` / `highlight_protect_rule_002.yaml rules=1` / `crop_suggest_rule_003.yaml rules=1` / `tone_clarity_rules.yaml rules=4` / `color_rules.yaml rules=2` / `region_rules.yaml rules=2`；`DEFAULT_RULES files=6 total_rules=11` | ✅ 无 `DecideError` |
| **F03④** `merge_proxy_metrics` 顶层落位 | `test_merge_proxy_metrics_lands_on_measurement_top_level` PASSED | 断言：`out is measurement`（原地）、每个代理键 `measurement[key] == value`（**顶层**）、`key not in measurement["global"]`、随后 `metrics_for_decide(measurement)[key] == value`（规则引擎可见）；另有非法图（`None` / 2D 数组）不改动 measurement | ✅ 顶层 |
| **F03 架构红线** `pipeline/` 不 import `pixo.service` | `test_metrics_module_does_not_import_service` PASSED | 对 `metrics.__file__` 源码正则扫描 `^\s*(from\|import)\s+pixo\.service` 无命中 | ✅ 无反向依赖 |
| **F03 导入来源** `compute_proxy_metrics` 取自 `pixo.vision.measure` | `test_proxy_metrics_imported_from_vision_measure` PASSED | `metrics_mod.compute_proxy_metrics is pixo.vision.measure.compute_proxy_metrics` → True | ✅ |
| **F03 loop 薄 wrapper 不破既有调用** | `grep _metrics_for_decide src/pixo/pipeline/loop.py` + `test_loop_alias_delegates_to_public_function` PASSED | 定义 `loop.py:522`、委派 `:529`、调用点 `:1371`（`metrics = _metrics_for_decide(measurement)`）语义不变；`tests/` 对私有名的引用仅新测试（`import _metrics_for_decide` 做同源断言） | ✅ |
| **F04①** `__call__` 返回 dict + 溯源字段 | `python -m pytest tests/unit/test_scorer_adapter_callable.py -q` | `6 passed in 4.89s`；探针：`hasattr(__call__) = True`、`call_type = dict`、`keys = ['domain_hint','overall','quality','raw_overall','source']`、`float(overall) = 2.915 \| source = pixo \| raw_overall = -0.47 \| domain_hint = None` | ✅ |
| **F04②** 禁止返回 `AestheticScore` 本体（否则 500） | `test_call_returns_dict_not_dataclass_and_floats_cleanly` PASSED + 反面对照 | 反面样本：`naive_callable -> RAISED TypeError: float() argument must be a string or a real number, not 'AestheticScore'`（在 `_NaiveCallable` 子类返回本体时复现）⇒ 证明 dict 形态是**必需**而非风格选择 | ✅ |
| **F04③** `.score(image_rgb, meta)` 签名不变 | `test_batch_contract_score_signature_unchanged` PASSED | `adapter.score(img, {"photo_id":"x"})` 返回 `AestheticScore`、`source == "pixo"` | ✅ |
| **F04 验收①** 注入 `SinglePhotoLoop` → `final_measurement["aesthetic"]` 非空 | `test_same_adapter_serves_loop_and_suggest_crop` PASSED；探针 `pixo_r21_dev2_probe_f04.py` | `loop state = ACCEPTED \| iters = 3`；`measurements aesthetic = [{overall 2.915, quality 3.309, source pixo, raw_overall -0.47, domain_hint None} ×3]`；`final_measurement aesthetic = {...}` 非空 | ✅ |
| **F04 验收②** 同一 adapter → `suggest_crop(scorer=adapter)` → `parts.scorer` 非空 | 同上 | `suggest_crop best parts = {'center':1.0,'thirds':0.0,'headroom':0.5,'coverage':0.5,'scorer':1.0} \| fallback = None`；断言写 `cands[0]["parts"].get("scorer") is not None`（**未**用「非 fallback」——断裂态 `fallback=False/None` 而 `scorer=None`，会误判通过，已用 `test_callable_contract_is_load_bearing_for_loop` 固化该反例） | ✅ |
| **无顺序依赖** 两个新文件各自单独跑 | `pytest tests/unit/test_metrics_for_decide_public.py -q` / `pytest tests/unit/test_scorer_adapter_callable.py -q` | `14 passed in 2.25s` / `6 passed in 4.89s` | ✅ |
| **改动文件直接消费者的邻居回归** | `python -m pytest tests/unit/test_loop_aesthetic.py tests/unit/test_scorer_calibration.py tests/unit/test_smart_crop.py tests/unit/test_aesthetic_wiring.py tests/unit/test_crop_wiring.py tests/unit/test_scorer_synthetic_probes.py tests/unit/test_loop_param_mapping.py tests/unit/test_scorer_input_domain.py tests/unit/test_loop_termination.py tests/unit/test_loop_replay.py tests/unit/test_loop_style_cards.py -q` | `112 passed in 19.95s` | ✅ 零回归 |
| **合并跑（交付口径）** | `python -m pytest tests/unit/test_metrics_for_decide_public.py tests/unit/test_scorer_adapter_callable.py -q` | `20 passed in 3.00s` | ✅ |

探针脚本写在**仓库外** `D:\tmp\`（`pixo_r21_dev2_probe.py` / `pixo_r21_dev2_probe_f04.py`），仅只读计算，未落仓库产物。全量回归未跑（按任务纪律由 `tester` 统一执行）。

---

## 3. 与 design 的偏差

| # | 偏差 | 理由 | 影响 |
|---|------|------|------|
| D-1 | `metrics_for_decide` 运行时判定用 `collections.abc.Mapping`（旧 loop 实现用 `dict`），region 判定同理 | design §2.1 签名即 `measurement: Mapping[str, Any]` | 对 dict 输入**逐键一致**（14 用例已证）；对非 dict 的 Mapping 输入是**放宽**（旧实现返回 `{}`）。唯一既有调用点传入 `VisionMeasure.measure()` 的 dict ⇒ 生产行为不变 |
| D-2 | 额外导出两个常量 `PROXY_METRIC_KEYS` / `REGION_METRIC_SUFFIXES` 并写入 `__all__` | 消除两处魔法元组字面量，供 dev-1 接线引用 | 纯追加，四符号契约不变 |
| D-3 | **未**把公共符号 re-export 到 `src/pixo/pipeline/__init__.py` | design §2.1 明示「是否 re-export 由 dev-2 自定，不影响契约」；且该文件不在 §3 stream-2 文件域内 | 调用方（dev-1）需 `from pixo.pipeline.metrics import metrics_for_decide, metric_universe, merge_proxy_metrics`（design §2.1 公共入口写法即如此） |
| D-4 | `_metrics_for_decide` 采用 **wrapper**（而非 `_metrics_for_decide = metrics_for_decide` 别名） | design §2.1 允许「薄别名或 wrapper」；wrapper 保留函数名/docstring，便于 `grep def _metrics_for_decide` 与既有导入面 | 行为等价，多一次函数调用（可忽略） |
| D-5 | `METRIC_KEYS` 只含 `crop_suggestion_applicable`，不含 loop 运行期另产的 `crop_suggestion_available` | design §2.1 明确对齐 loop.py:783-792 注册面（注册的是 `applicable`） | 与 design 一致；`available` 未注册一事登记为遗留（见 §4.3） |

无「缩小交付范围 / 放宽验收断言」类偏差。

---

## 4. 遗留问题（范围外，仅登记，未处理）

1. **`build/lib/pixo/**` 旧副本漂移（exploration §7.4 复核确认，范围外）**：`build/lib/pixo/pipeline/metrics.py` **不存在**，且 `build/lib/pixo/pipeline/loop.py` 仍是旧 `def _metrics_for_decide` 实体（旧实现），不含 wrapper 与 `metrics` 导入。若打包/导入误取 `build/lib`，`from pixo.pipeline.metrics import ...` 会 `ImportError`。需后续确认打包路径不会误取（本轮未动 build 产物，避免污染队长提交）。
2. **F03 的 service 侧接线归 dev-1（design §3 仲裁重申）**：`measure_session` 顶层合并 `merge_proxy_metrics`、`decide_photo` 展平并传 rules，均须由 stream-1 执行；且**必须显式** `load_rules(p, metric_keys=metric_universe(prompts))`（否则 `register_metric_keys` 全局 set 的顺序副作用会让严格/宽松不定，exploration §6.8）。两条流在 `decide_photo` 参数面会相遇，需队长在集成时确认 dev-1 用的是 `metric_universe(...)` 而非 `METRIC_KEYS`（后者必抛 `DecideError`，见 §2 负控证据）。
3. **指标命名不一致（既有，非本轮引入）**：loop 注册 `crop_suggestion_applicable`（loop.py:769），运行期另产 `crop_suggestion_available`（loop.py:1387）。当前无规则引用后者，未触发 lint，但两者并存易误用；本轮按 design 只注册 `applicable`，未动 `available`。
4. **`pixo.pipeline.metrics` 未进包级 `__init__` 导出面**（见 D-3）：若后续希望在 `pixo.pipeline` 顶层直接可用，需要文件域所有者（或队长裁决）修改 `pipeline/__init__.py`。
5. exploration-r21 §7 其余范围外项本轮未触碰：`render/bench/preview_cold_baseline.json` 坏 JSON、`preview_v16_nef_baseline_{cold,hot}.json` 失效 `corpus_a` 路径、`scripts/auto_real_edit.py` 语料根占位符、`src/pixo` 下 131 处 `except Exception` 静默降级、`task-brief.md:35` 语料计数口径（3428 vs 实测 765）。
6. **未跑全量回归**（纪律要求，由 `tester` 执行）：本报告只覆盖 dev-2 改动文件及其直接消费者的定向测试（20 + 112 passed）。
