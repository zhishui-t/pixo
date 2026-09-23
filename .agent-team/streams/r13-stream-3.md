# streams/r13-stream-3.md — dev-3 · style_cards 接入 loop decide_context（R13）

> 2026-09-07 交付。任务：知识层→生产决策链最后一公里（"建成未接线"清单收尾）。

## 做了什么

### 1. decide_context 补 style_cards 键（`src/pixo/pipeline/loop.py`）
- `SinglePhotoLoop.__init__` 新增 `enable_style_cards: bool | None = None` 入参 +
  `self.enable_style_cards` / `self._style_cards` 字段：构造期加载一次（实例即
  缓存点，迭代间复用同一批 dict；know 层无缓存惯例——registry 每次现构，故
  loop 侧自缓存），加载失败降级空列表 + warning（知识层故障不阻断闭环，与
  引擎 `_style_card_rules` 的降级同向）。
- decide_context 构造区（:1397 附近）追加 `decide_context["style_cards"] =
  list(self._style_cards)`——schema = `card.to_dict()` dict 列表（test_know
  :140-154 权威用法）；关闭/空表时**键整体缺席**（decide 零感知，行为回退）。
- 模式沿 llm_suggestions/llm_shadow 先例：条件追加 + env 开关 + DI 优先。

### 2. 数据源与选择策略（证据）
- **卡源 = `know.load_style_cards()`（内置 6 张 builtin 卡）**：
  - `configs/styles/films` 的 23 张渲染卡（`StyleCard.from_films_dir`）schema
    为 `{stages,params,output}`，**无 recommended_adjustments**，经
    `style_card_to_decide_rules` 产出**零规则**——不是决策卡源；
  - builtin 卡是唯一带 recommended_adjustments 的卡源（t66 桥接目标），纯内存
    零 I/O；
  - 不用 `default_registry()`：会连带加载 graph+RAG（文件 I/O），decide 只需卡。
- **选择策略 = 全量喂卡 + 既有机制自然排序**：know 层**无** scene→卡匹配逻辑
  （grep 证据：卡侧只有 metadata.scenes 标签、图谱有 scene 节点但无匹配 API）。
  全量喂入后由三层既有机制兜底：① 卡规则的 if_* 条件按当图指标门控（不命中
  即 no-op）；② 同参冲突 resolve_conflicts 高优先级胜出、同优先级先到先得
  （规则列表序确定）；③ 用户锁定参数引擎硬保护。**实测证据见优先级测试**。

### 3. 开关 PIXO_STYLE_CARDS——**建议默认开**（证据，提请裁决）
- 开缺省开证据：
  1. t66 桥接（recommended_adjustments → level="style_card" 6000 规则）+
     test_know 引擎消费测试——桥的本意即激活，本次只是补上生产喂入口；
  2. 优先级链安全实测（见下）：用户锁定/软偏好恒压卡意图，锁定参数硬保护；
  3. 侵入面小：6 张内置卡条件全部依赖当图指标，常规图多数不命中即 no-op；
  4. 先例一致：PIXO_LLM_SHADOW 同为"advisory 层缺省开"。
- **反方向证据（同样实测，裁决必读）**：默认开**改变既有闭环结果**——
  `tests/integration/test_loop_e2e.py::test_qc_overflow_rolls_back_once_then_
  manual_review`（亮图 + 真实测量）：portra 卡 `if_highlight_clip_ratio_gt_
  0.03 → exposure_-0.15` 在 decide 轮提前压暗，溢出在 QC 前消失，原断言
  MANUAL_REVIEW 变 ACCEPTED。语义上这是卡的正常产品行为（过曝图自动压光），
  但它证明**默认开会改变既有生产路径的光度结果**（凡 bright image 走 loop
  decide 的场景）。该测试已按"隔离机制测试"原则加 `enable_style_cards=False`
  （QC 回退机制与卡意图解耦），**若裁决改默认关，去掉该参数即可，无需其他改动**。
- 次要噪声（内置卡 DSL 成熟度，非本批范围）：无键值 DSL 动作串（如
  `temp_-200_tint_+6`、`bw_mix_red_filter_+0.3`）每轮以顶层 informational 键
  落入 params（param_update 留痕，不产生渲染效果、不吞键）；well-formed 卡
  （dict 形态动作）零噪声（实测对照）。建议 know 层后续补 DSL 解析。

### 4. 优先级语义实测（决定 6000 级 vs 规则级）
| 冲突场景 | 结果 |
|----|----|
| 卡(6000) vs 系统默认规则(3000) 同参 exposure | **卡胜**（-0.15 落位，rule_ids 含卡） |
| 卡(6000) vs 用户软偏好规则(9000) 同参 | **用户规则胜**（+0.3 落位） |
| 用户锁定 exposure + 卡规则 | **硬保护**（参数不动，rule_ids 空） |

### 5. e2e 闭环（`tests/unit/test_loop_style_cards.py`）
卡（monkeypatch 注入测试卡 `if_mean_luminance_lt_200 → exposure -0.15`）→
decide rule_ids 含 `r13_test_card_` 前缀 → `_apply_decide_params` 别名映射 →
exposure 桶 `auto target_offset=-0.15` → 合成渲染变暗（测量回读
`lum2 < lum1 - 1.0`，2^-0.15≈0.901）；关闭对照组两轮渲染逐位一致。
注：卡阈值按 tone gamma 编码后的 u8 均值（~151）设定，非线性域直推。

## 改了哪些文件
| 文件 | 改动 |
|----|----|
| `src/pixo/pipeline/loop.py` | `_STYLE_CARDS_ENV` + `style_cards_enabled()`；构造器入参/字段/加载降级；decide_context 追加 style_cards 键 |
| `tests/unit/test_loop_style_cards.py` | **新增** 11 用例 |
| `tests/integration/test_loop_e2e.py` | QC 回退测试加 `enable_style_cards=False` 隔离（见上裁决证据；若默认关裁决则移除该参数） |

## 如何验证（命令 + 输出摘要）
```
python -m pytest tests/unit/test_loop_style_cards.py -q   → 11 passed
python -m pytest tests/unit -q -m "not e2e"               → 1315 passed / 0 errors
python -m pytest tests/integration -q                     → 112 passed
```
（邻域 loop/know/region 套件含于 unit 全量：test_know / test_loop_* /
test_decide_region_wiring / test_region_adjust 全绿。）

## 遗留问题
1. **默认开关待队长裁决**：建议默认开（证据如上）；反证为 QC 回退集成测试
   的行为漂移（已隔离）。若改默认关：`style_cards_enabled` 返回值翻转 +
   移除集成测试的隔离参数，其余不动。
2. builtin 卡 DSL 成熟度：无键值动作串落为 informational 顶层键（不吞键
   惯例），每轮 param_update 略有噪声；建议 know 层后续补动作 DSL 解析
   （如 `temp_-200_tint_+6` → temp/tint 双参数），本轮不动。
3. 卡源目前仅 builtin；接入 films 渲染卡需先定义渲染卡→建议卡的映射
   （参数桶直译），属独立迭代。
4. 本轮未 commit（提交策略归队长）。

---

## 裁决执行：PIXO_STYLE_CARDS 默认改关（R13 队长裁决，2026-09-07）

### 处置
1. **默认值翻转**（`loop.py`）：`style_cards_enabled()` 未设置/空串 → **False**；
   显式开态值 = 非关态值非空串（"1"/"true"/"on"/"yes"）；显式关态值
   {"0","false","off","no"} 语义保持。模块注释/函数 docstring/构造器注释
   rationale 全部更新为裁决版（QC 回退漂移实证 → 激活留用户明示）。
2. **QC 回退测试还原默认态**：`tests/integration/test_loop_e2e.py::
   test_qc_overflow_rolls_back_once_then_manual_review` 移除
   `enable_style_cards=False` 隔离参数——默认关后该测试运行在接线前语义
   （MANUAL_REVIEW 断言原样通过，即「默认关 = 接线前逐位一致」的直接证据）。
3. **双态测试覆盖**（`tests/unit/test_loop_style_cards.py`，11 用例）：
   - 关态（默认）：decide_context 无 style_cards 键 + DI 显式关同样缺席 +
     know.load_style_cards **零触达**（never-touches 断言：默认关不产生任何
     知识层加载/IO）+ card 规则不触发 + 两轮渲染逐位一致对照；
   - 开态：env 激活（PIXO_STYLE_CARDS=1 全链：开关→加载→接线）+ DI 显式开 +
     卡条件命中 → rule_ids → 参数落位 → 渲染变暗 + 降级路径。
4. **裁决记录**：本节 + 代码注释三处 rationale；「默认开」列用户拍板项——
   打开方式 = env `PIXO_STYLE_CARDS=1`（或服务层构造入参 DI）。

### 与 dev-2 warmth 批的并发整合（如实记录）
共享树并发编辑：dev-2 的 warmth 批（region_adjust 扩 warmth 内核 +
REGION_PARAM_LIMITS 加 warmth + region_rules.yaml 加 area_ratio<0.7 护栏并
软化补偿系数 -0.5→-0.25 / 0.4→0.2）与我的默认关翻转在 loop.py 上发生两次
覆盖-重放。最终态：双方改动共存（style_cards 块重放应用 + warmth 分支/护栏
/系数以 dev-2 版本为准），我的 wiring 测试已同步其面积护栏与软化系数。

### 验证（命令 + 输出摘要）
```
python -m pytest tests/unit/test_loop_style_cards.py -q     → 11 passed（双态）
python -m pytest tests/unit -q -m "not e2e"                 → 1315 passed / 0 errors
python -m pytest tests/integration -q                       → 112 passed
  （含 QC 回退测试默认态原样通过 = 默认关与接线前行为逐位一致的链级证据）
```
