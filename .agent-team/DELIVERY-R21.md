# DELIVERY-R21 —— Pixo 第二十一轮：闭环插电（M0）

> 队长 2026-09-10 呈报。**QA 总审已通过并签章（`.qa_ok` / `.r21_ok`，ISO `2026-09-10T22:54:49+08:00`，0 阻塞项）**。
> 状态：**卡点③待用户验收**。

## 一、本轮目标与达成

把已造好但**无生产入口**的 `SinglePhotoLoop` 闭环接进 FastAPI 服务层，让「测量→决策→回写渲染→QC→反馈再入环」在生产路径上真正跑起来。

**达成（真 RAW 实证）**：`POST /api/photos/{id}/auto-loop` →
`state=ACCEPTED` / `params={"colorcal":{"saturation":-0.15}}` / `rule_ids=["saturation_high_rule"]` /
与「仅渲染基线」像素差 **56,293,263** / 高光溢出 **0.025923 ≤ 0.03** / `trace_event_count=12`。

## 二、功能交付（F01~F05）

| F-ID | 交付 | 验收证据 |
|------|------|----------|
| F01 | `run_auto_loop()` + `POST /api/photos/{id}/auto-loop`（202；`sync=true` 200）+ `GET /api/auto-loop/{task_id}`；每 photo 单飞；失败语义 404/400/不裸抛 500 | `tests/integration/test_auto_loop_api.py` **20 passed**（含 FastAPI `TestClient` 真实 HTTP 往返） |
| F02 | `_load_auto_loop_rules()` 加载 11 条 `DEFAULT_RULES`；`PIXO_RULES=off/0/false/no` → `[]`；库层缺省仍空 | 同上 + 探针（`0/false/off/no/OFF/" off "` 全 0；恢复 11；`lib_default_rules=[]`） |
| F03 | `pipeline/metrics.py` 公共 API（`metrics_for_decide` / `METRIC_KEYS` / `metric_universe` / `merge_proxy_metrics`）+ service 顶层合并 proxies + `decide_photo` 展平传 rules | `tests/unit/test_metrics_for_decide_public.py` **14 passed**；负控：只传 `METRIC_KEYS` 必抛 `DecideError`（须 `metric_universe` 22 键） |
| F04 | `_PixoScorerAdapter.__call__` 返回 dict（`overall` + dimensions + 溯源字段） | `tests/unit/test_scorer_adapter_callable.py` **6 passed**（跨层注入 loop 与 `suggest_crop`；反面样本返回本体则 TypeError） |
| F05 | E2E 门禁（双 marker + 独立 env）+ 真 RAW 证据 | 门禁 **2 passed**；全量 **1574 passed / 0 failed**；金样本双路零漂移 |

## 三、关键过程事件（诚实记录）

1. **门禁首跑 FAILED，拦下一个会漏到线上的口径缺陷**：服务层 `rule_ids` 取"最后一条 decide 事件"，
   而末轮规则**自然不命中**时（首轮 `saturation_high_rule` 已把 `colorfulness_proxy` 从 6.1888 压到
   5.8936）该事件为空 ⇒ **真照片上恒返回 `rule_ids: []`**，而开发单测（合成 18 例）全绿。
   → 队长裁决 A（改服务层口径为**全 trace decide 事件并集**），**不修** `engine`（末轮无规则应用是
   正确语义，透传历史 rule_ids 会让 trace 失真）。契约修订 R1 记入 `design-r21.md §7`，
   已由 `QA-checker` 增量复核通过（`.design_ok` 条目 #1）。
2. **三处判断错误被团队纠正**（复盘留存）：
   - 队长首版 R1 归因写"末轮短路"，**错**：`iteration>=max_iterations` 的 `last_iteration` 分支返回
     `should_stop=False`、规则照跑（`engine.py:977-989`，t107 off-by-one）。
   - 队长提议用 `PIXO_GATE_AUTOLOOP_MAX_ITER=1` 作负控，**错**：该轮同样照跑规则，会得出"聚合伪造命中"。
   - tester 指出 design 措辞"旧口径必挂"**偏强**：`DSC_5237` 末轮就是命中的（5.8847→6.1472），
     旧口径在该样本上会通过。已限定为"末轮自然不命中的样本"。
3. **QA 总审揪出并修好 1 处证据脚本误标（FIX-3）**：tester 的 `tmp-r21-d1-table.txt` 把探针字段
   `rule_ids_last_nonempty` 改名当 `union_rule_ids`，**不是真并集**（`DSC_5238` 真并集多首轮
   `dehaze_rule_030`，与同表逐轮列自相矛盾）。已修 extractor 重算并单列 `last_nonempty_rule_ids`
   （原件备份 `tmp-r21-d1-table-orig.txt`）。**产品代码无此问题**（并集实现与门禁断言⑥自洽）。
   另修 2 处测试 docstring 措辞（删掉被禁的"末轮恒空"不变量表述）。
4. **过程失误（非产品）**：tester 首次 D1 探针与 pytest 并发 → 45MP float64 渲染 `ArrayMemoryError`；
   真 RAW 全分辨率渲染**必须串行**，已复跑正常并沉淀入记忆。

## 四、验收数字（QA 本会话独立复跑，非采信报告）

| 项 | 结果 | 口径 |
|---|---|---|
| 全量回归 | **1574 passed / 0 failed** / 6 skipped / 1 xfailed（212.66s；另一次 251.99s 同结果） | `python -m pytest tests -q -m "not e2e"`；R20 红线 1533（+41 = 新增用例） |
| F05 真 RAW 门禁 | **2 passed in 124.06s** | 独立 env `PIXO_GATE_AUTOLOOP_RAW` + `-m gate` |
| 金样本零漂移 | 合成 gate **7 passed**；真 RAW compare **24/24 PASS（u8_max=0 / u16_max=0）** | `test_gate_golden.py` + `gate_golden.py compare`，`data/` 零改动 |
| 定向 | **40 passed**（20 + 14 + 6） | 三文件批跑 26.15s（队长亦复核一次同结果） |
| D1 三样本余量 | 5236 **+0.96%**（末轮空）/ 5237 **+0.28%**（末轮命中）/ 5238 **+7.06%**；3/3 并集非空 | 阈值 `colorfulness_proxy ≥ 6.13`（`color_rules.yaml:22-31`，p75=6.1292） |

## 五、角色与模型（实际生效情况）

| 角色 | 任务 | 档位（角色库固化） | 结果 |
|------|------|-------------------|------|
| `researcher` | 前期探索（466 行） | GLM-5.3-Flash max | 成功：3 条改变设计前提的发现 + 2 处 CR-04 纠正 + 8 遗留 |
| `dev-1` | F01/F02/F03 接线 + R1 修复 | GLM-5.3-Flash max | 成功：20 passed（含 R1 机制用例） |
| `dev-2` | F03 公共 API + F04 | GLM-5.3-Flash max | 成功：20 passed（+37 消费方回归） |
| `tester` | F05 门禁 + 全量回归 + D1 证据 | GLM-5.3-Flash max | 成功：门禁 2 passed、全量 1574/0；1 处证据脚本误标经 QA 修正 |
| `QA-checker` | 设计审核 + R1 增量复核 + 交付总审 | GLM-5.3 max | 设计 10 处修订；R1 复核通过并纠正归因；总审 0 阻塞放行 |
| 队长 | 澄清/设计/裁决/提交/交付 | — | — |

> 说明：各 subagent 的 provider/model 由宿主按角色配置注入；本表按角色库声明填写，**未逐实例验证运行时实际模型**（保守标注）。

## 六、遗留与后续

**本轮新债（已写入 `docs/tech_debt.md`）**
- **#20** auto-loop 与 `/decide` 缓存、`/timeline` 不联动（刻意不回写，避免双写不一致；后果：跑完 `/timeline` 仍显示 RAW_PENDING）
- **#21** auto-loop 无任务级超时/取消；任务表无淘汰、跨 photo 排队无 `queued` 态

**总审续排候选（未编号，见 tech_debt 同节）**：后台 segmenter 预热未持推断锁、`build/lib/pixo` 陈旧副本漂移、`crop_suggestion_applicable|available` 并存、`preview_cold_baseline.json` 坏 JSON、`preview_v16_nef_baseline_*.json` 失效 corpus_a 路径、`auto_real_edit.py` 扫描根占位符。

**下一轮建议（M1）**：CR-06 噪声/细节指标入决策键宇宙 → CR-07 亮度降噪落地（唯一能力性缺口）→ CR-09 风格卡 LUT 生产注入。

## 七、卡点③（用户验收）

- （待用户确认）
