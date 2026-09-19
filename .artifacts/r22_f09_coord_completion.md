# R22 F09 `compose.coord` 归一化 —— 未完成部分的收口记录

日期：2026-09-14　触发：R23 基线中性化跑回归时暴露　裁决：队长（用户）选「修（含翻转用例）」+「保持 `norm` 缺省」

## 0. 背景：F09 是什么、停在哪

R22 F09 = `compose` free 矩形从**本画布像素**改为**全幅相对 [0,1]**（tech_debt #17 清偿），
带一个 legacy 开关 `compose.coord: "norm"(新缺省) | "px"(旧语义, deprecated)`。

设计文档 `.agent-team/design-r22.md` §2.4/§3 明确了：落点（`compute_crop_rect` 唯一同源点）、
纯函数缺省保持 `"px"`（公开 API 零变化）、Stage 缺省 `"norm"`、**以及需要同步的测试面与调用点**。

**实际状态：代码改了、同步没做完**（R22 全未提交，无 `.r22_ok` / 无 `DELIVERY-R22.md`）。
其自身 §2.3 与 §3 已列出但**未执行**的同步项，正是本轮暴露的三处缺陷。

## 1. 发现的三处缺陷（全部为 F09 迁移未完成）

### 1.1 掩码 shape 预测线未透传 `coord` ⇒ 两线静默分叉
- `region_masks.py:_post_compose_shape` 调 `compute_crop_rect` **不传 `coord`** ⇒ 落纯函数缺省 `"px"`；
  渲染线 `ComposeStage.process` 是 `self.p(ctx,"coord","norm")` ⇒ **渲染按相对、掩码按像素**。
- F09 §2.3 原文要求：「`region_masks.py:51-60` 必须显式传 `coord=cp.get("coord","norm")`（否则预测线仍按 px → 分叉）」。
- 触发条件 = loop 公开 API 的常见写法（传 px 矩形且不声明 `coord`）。

**修复**：`region_masks.py` 补 `coord=str(cp.get("coord", "norm") or "norm")`（缺省对齐 Stage 的 `"norm"`）。

### 1.2 `adopt_crop` 写回像素值但不声明 `coord` ⇒ 采纳裁剪建议后取景退化
- `loop.py` adopt_crop 段用 `rect_norm_to_px(...)` 把建议矩形转成**全幅像素**写回，**不设 `coord`**。
- 在 `coord` 缺省 `"norm"` 下这些像素值被按**相对值**解释 ⇒ **输出 1×1**。
- 且 px 以真全幅（如 6048）为基准，预览帧（如 1024）下相对窗不同 —— 正是 #17 的失配。
- `crop_suggestion["rect"]` **本就是** `[x0,y0,x1,y1] ∈ [0,1]`，换算纯属多余。

**探针实证**（`.artifacts/_r23_adopt_crop_probe.py`，源 64×64、建议 `[0.1,0.1,0.9,0.9]`）：

| | 写回的 compose | `compute_crop_rect` 结果 | 最终画面 |
|---|---|---|---|
| 修复前 | `{mode:free, x:6, y:6, width:52, height:52}`（无 coord） | 按 norm 解释 → `(63,63,1,1)` | **`(1,1,3)`** |
| 修复后 | `{mode:free, coord:"norm", x:0.1, y:0.1, width:0.8, height:0.8}` | `(6,6,51,51)` | **`(51,51,3)`** |

> `compose.py:71` 的 warn-once 告警**已如实打出**（`free 矩形 (6.0, 6.0, 52.0, 52.0) 存在 |值|>1`），
> 但它**只告警、不阻止**，且模块级 flag 使同一渲染的第二条线不再打 → 极易漏读。

**修复**：adopt_crop 直接落 `norm`（去掉 `rect_norm_to_px` 换算，显式写 `"coord": "norm"`）。
副作用：`rect_norm_to_px` 在本段失去调用点（与 `rect_px_to_norm` 同样成为零调用工具）。
保留不删（F09 §2.4 视其为迁移工具；删留由 F09 owner 定）。

### 1.3 两处测试硬断言旧 px 值（F09 §2.4/§3 已列、未做）
- `tests/regression/test_gate_compose.py:81/92/149`（另 118/135 语义中性但同面）
- `tests/integration/test_loop_e2e.py:69`
- `tests/unit/test_crop_wiring.py:173-178 / 201-209`（dev-geom 侦察补入，设计文档原文标注「含硬断言」）
- `tests/unit/test_region_masks_channel.py:640-675`（**F09 标注的「有意翻转」用例**）

## 2. 本轮改动清单

| 文件 | 改动 |
|---|---|
| `src/pixo/render/pipeline/region_masks.py` | `_post_compose_shape` 透传 `coord`（缺省 `"norm"`）+ 注释 |
| `src/pixo/pipeline/loop.py` | adopt_crop 段直接落 `norm` 四元组 + 显式 `"coord":"norm"`；去掉 `rect_norm_to_px` 换算（该段） |
| `tests/regression/test_gate_compose.py` | `_run_compose` 统一 `params.setdefault("coord","px")`（单点声明 legacy 语义） |
| `tests/integration/test_loop_e2e.py` | compose_params 补 `"coord":"px"`；另修 QC 溢出用例（R23 副产品，见 §3） |
| `tests/unit/test_region_masks_channel.py` | `_FakeCompose` 透传 `coord`；**翻转** #17 用例为新不变量（相对窗一致）+ 判别力对照 |
| `tests/unit/test_crop_wiring.py` | 两处采纳断言由 px 改为 norm；docstring 注明语义翻转 |
| `tests/unit/test_decide_region_wiring.py` | `test_e2e_crop_adoption_drops_region_masks` **补几何断言**（原只断言 `mode=="free"` ⇒ 是 1.2 的盲区） |

## 3. 附带修复（R23 自身副产品，非 F09）

`tests/integration/test_loop_e2e.py::test_qc_overflow_rolls_back_once_then_manual_review`
原本靠 `tone` 缺省提亮把 0.92 顶过 1.0 才裁切；R23 把 `tone.brightness` 归零后不再溢出。
按该用例 docstring 自述的意图（「测试意图不再绑定引擎默认值」）改为**用例自带增益**：
`_OVERFLOW_PARAMS = {"tone": {"brightness": 0.5}}`（0.92 × 2^0.5 ≈ 1.30，必然裁切）。

## 4. 验证

| 范围 | 结果 |
|---|---|
| `test_crop_wiring` + `test_decide_region_wiring` + `test_region_masks_channel` + `test_compose_autolevel` + `test_gate_compose` + `test_loop_e2e` | **82 passed** |
| `test_decide_region_wiring::test_e2e_crop_adoption_…` 的 RuntimeWarning（`Mean of empty slice`） | **既有**，非本轮引入（临时还原 `coord="px"` 复现同样告警） |
| 全量 `unit + regression + integration` | 见 §5 |

## 5. 遗留 / 需 F09 owner 决策

1. **`compose.coord` 缺省 `"norm"` 保留**（队长裁定）。纯函数缺省仍 `"px"` ⇒
   仓外调用方若传 px 矩形且不声明 `coord`，取景会变（仓内持久化 px 矩形 ≈ 0 处，F09 侦察 P5）。
2. **三个工具函数现均零调用**（保留待 F09 owner 处置，删留未定）：
   - `rect_norm_to_px`（`loop.py:278`）—— 原仅被 adopt_crop 调用，改用 norm 后失去调用点；
   - `rect_px_to_norm`（`loop.py:265`）—— 原本即零调用（F09 侦察已记载）；
   - `_full_canvas_size`（`loop.py:1207`）—— 原被 adopt_crop 用于取真全幅像素基准；
     norm 写回不再需要它。F09 §2.4 曾称其为「B1 基准的唯一来源」，
     但那是在「px 写回」前提下；改为 norm 后该基准由 `crop_suggestion["rect"]` 自带。
   （三个函数均有单测覆盖其纯函数行为，`test_rect_converters_roundtrip` 仍绿。）
3. **归一化基准的正确性依据**：`_build_crop_suggestion` 在 `preview_img`（预览帧）上
   求框并交由 `suggest_crop` 归一化 ⇒ 该 rect 相对**预览帧**、与全幅**等比**
   ⇒ 直接作 norm 使用与分辨率无关，正确。旧路径把它映射回「真全幅像素」，
   恰好制造了 #17 的跨 tier 失配。
4. 掩码适配仍**只做 shape 对齐、不做坐标重映射**（`region_masks` 自述、F09 接受）。
   归一化后两 tier 相对窗一致，故 shape 对齐已足够；若未来支持非全幅归一化裁剪窗，
   需补真正的坐标重映射。
