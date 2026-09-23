# 任务书（task-brief）— Pixo 第二十一轮（R21）：闭环插电（M0）

> 队长 2026-09-08 拟定；卡点①确认物。
> CR 依据：`docs/R21_CHANGE_REQUESTS.md`（本会话实测产出，含对上一轮结论的更正）。
> （R9 任务书已归档为 `task-brief-r09.md`）

## 目标

把已经造好但**没有生产入口**的修图闭环 `SinglePhotoLoop` 接进 FastAPI 服务层，
让「测量 → 决策 → 回写渲染 → QC → 反馈再入环」这条环在**产品路径**上真正跑起来：
一张真 RAW 进来，服务端自己决策参数、自己迭代、自己出图，并留下可审计 trace。

一句话：**让 AI 驾驶从「脚本里能跑」变成「服务上能跑」。**

## 背景与现有材料

### 已完成前置（本轮开工前）
- **CR-14 已执行**：本地 43 个提交（R9–R20）已推送，`origin/master == 58d780b`，ahead=0。
- **结论更正**：`configs/color/calib_out/` 是**陈旧快照**（非待入库新表）——哈希对拍见 `docs/R21_CHANGE_REQUESTS.md` §0。本轮不碰它。

### 现状（实测证据，均有探针/调用点支撑）
| 事实 | 证据 |
|---|---|
| 服务层 decide 规则**零触发** | 探针 `.artifacts/_probe_metric_shape2.py`：裸 measurement → 0/11 条，`params={}` |
| 成因①：指标嵌在 `global`/`regions` 下 | `src/pixo/vision/measure.py:574-581` vs `src/pixo/pipeline/loop.py:521-551` |
| 成因②：`measure()` 不产 proxies | `measure.py:548` 无 `compute_proxy_metrics`；仅 `loop.py:1352`/`batch.py:675` 调用 |
| `SinglePhotoLoop` 无生产入口 | `src/pixo/service/` 仅 `loop.py` 纯转发 shim；`app.py`/`runtime.py` 零引用 |
| `DEFAULT_RULES` 未进生产 | 消费者只有 `scripts/auto_real_edit.py` + `tests/` |
| 美学评分器签名不符 | `pipeline/batch.py:318`（只有 `.score()`）vs `pipeline/loop.py:907/912`、`render/geometry/smart_crop.py:194`（按可调用对象用） |
| 前端 `decidePhoto` 定义但零调用 | `frontend/src/api/client.ts:157` |

### 可复用材料
- 闭环本体与 E2E 骨架：`src/pixo/pipeline/loop.py`、`tests/integration/test_loop_e2e.py`（合成图 + MockSegmenter 全覆盖）
- **参考实现**（当前唯一跑真闭环的脚本）：`scripts/auto_real_edit.py` —— 已示范 `RawRenderBackend` + `MultiModelSegmenter` + `VisionMeasure` + `DEFAULT_RULES` 的正确装配
- 真实语料：`K:\data\photo\0711\raw\DSC_5236.NEF`（**0711\raw 下 765 个 NEF**；`K:\data\photo` 全库 3428 个，含 `2026春节`/`厦门`；⚠ `src/pixo/render/bench/*.json` 里的 `K:\data\photo\corpus_a\raw\...` 是**失效旧路径**）
- 服务层契约：`src/pixo/service/runtime.py`、`src/pixo/service/app.py`、转发层 `src/pixo/service/loop.py`
- 观感对照资产：`exports/auto/`（79 个文件）

## 范围（功能清单）

| F-ID | 功能 | 对应 CR | 优先级 | 备注 |
|------|------|---------|--------|------|
| F01 | 闭环生产入口：服务层装配 `SinglePhotoLoop` + `RawRenderBackend`，新增 HTTP 入口 | CR-01 | 必须 | **不得破坏** `decide_photo` 既有单轮语义与响应字段 |
| F02 | 默认规则注入：装配层加载 `DEFAULT_RULES`，`PIXO_RULES=off` 可关 | CR-02 | 必须 | 库层 `SinglePhotoLoop(rules=None)` 缺省**保持空**（纯库语义） |
| F03 | 指标口径单一来源：`_metrics_for_decide` 提升为公共 API，service 与 loop 共用；service 侧补齐 `compute_proxy_metrics` | CR-03 | 必须 | 消除成因①②；加规则 metric 键 lint |
| F04 | 评分器适配器签名：`_PixoScorerAdapter` 支持可调用契约 | CR-04 | 必须 | 一处修好 `loop.py:907/912` 与 `smart_crop.py:194` |
| F05 | 端到端门禁：真 RAW 跑完整闭环，断言决策落地 + 像素差 + QC 达标 + trace 完整 | CR-05 | 必须 | 签章 `.r21_ok`（qa 执笔） |

## 非目标（本次明确不做）

- CR-06/07（噪声指标入决策 / 亮度降噪落地）—— M1，含 native 内核与金样本重生成
- CR-09/10（风格 LUT / 场景预设接线）、CR-11（多轴 QC）、CR-12/13（RP-CCM、skin 金样本）
- **前端零改动**：不接 `decidePhoto`、不做样式选择器
- 不改渲染算子、不重生成金样本、不动 `configs/color/calib_out/`
- 不引入端到端 learned ISP（与可解释闭环定位冲突）

## 约束

- **技术栈**：Python 3.12 / FastAPI（`src/pixo/service/`）、pytest；src-layout（`sys.path` 含 `src`）
- **架构**：
  - 库层 `pipeline/` 不得反向依赖 service 层；公共 API 提取落 `pipeline/`（或 `decide/`）
  - 保留 `decide_photo` 现有响应字段（`photo_id`/`state`/`iteration`/`measurement`/`decision`）
  - 新端点走 `app.py` 既有路由注册风格
  - 闭环多轮渲染耗时长：端点须可控（`max_iterations` 上限 + 明确超时/后台策略）
- **测试**：
  - 新增测试必须有运行证据；`tester` 的通过结论必须附命令与输出
  - 全量回归基线：**1533 passed / 0 failed**（R20 签章口径）不降
  - 金样本 gate（`src/pixo/render/tools/gate_golden.py`）零漂移（本轮不应改渲染像素路径）
- **环境**：Windows / PowerShell；工作目录 `K:\work\project\pixo`
- **额度纪律**：dev/tester/researcher = Flash 档；只跑定向测试，全量回归由 tester/qa 统一执行一次
- **文件域互斥**：见 `team-manifest.md`「文件域仲裁」节（两开发流不得同改一个文件）
- **纪律**：小步快跑，改前先读现状；同一操作失败 2 次立即升级 `super-dev`，禁止原样重试

## 完成标准（可验证）

1. F01~F05 全部实现，且 `tester` 给出**带命令与输出**的验证结论（功能 + 端到端）；
2. 真 RAW（`K:\data\photo\0711\raw\DSC_5236.NEF`）经服务端闭环接口跑通：决策参数非空、`rule_ids` 非空、导出图与「仅渲染」基线存在像素差、QC 高光溢出 ≤3%、trace 完整；
3. 新增/修改代码有对应测试（正常路径 + 关键边界 + 异常路径）；
4. 全量回归 ≥ 1533 passed / 0 failed，金样本 gate 零漂移；
5. `qa-checker` 总审放行并签章 `.qa_ok`（含审核人 / 覆盖 F-ID / ISO 时间戳 / 结论）；
6. `docs/changelog.md` 追加 R21 条目；`.agent-team/DELIVERY-R21.md` 交付呈报。

## 用户确认

- 2026-09-10：范围=M0 闭环插电；人马=DSH 原生 agent-team 角色；CR-14 立即推送 —— 三项已确认（Clarify 轮）
- 2026-09-10：**任务书 + 花名册 + 工作流 + DAG 已批准（卡点①通过）**
