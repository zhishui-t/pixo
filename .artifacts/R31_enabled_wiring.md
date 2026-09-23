# R31 · 前端 enabled 接线断点修复 + 参数契约两端收敛

日期：2026-09-21 ｜ 起点：R31 状态盘点点名的「下一轮最该动的」事项
对象：`K:/data/photo/西安/0711/raw/DSC_5236.NEF`（经 `tests/_corpus_paths.REAL_A`）

---

## A. 病灶

R23 把 clarity/skin/refine/dehaze/hsl/calibration/split_tone/region_adjust 的
`enabled` 归到 `False`（引擎只提供能力、不猜意图，`Stage.wants()` 基类默认 False）。
但**调用方没有跟上**：前端 `AdjustmentsPanel.patch()` 只发

```ts
patchProjectParam(projectId, { [stage]: { [param]: 值 } }, 'user')   // 无 enabled
```

⇒ `wants()` 恒 `False` ⇒ **清晰度 / 去朦胧 / 色彩校准 / 分离色调 / 磨皮 / HSL /
锐化 / 降噪 八组滑杆「调了没效果」**。

### 修在哪一层（判据）

| 层 | 能不能修 | 理由 |
|---|---|---|
| 引擎内自动开启 | ❌ | 正是 R23 移除的越权；引擎读 `enabled`，不猜「用户拖了滑杆」 |
| 前端补发 `enabled:true` | ❌ | 把引擎 schema 泄漏给 UI；任何新调用方都要重学一遍 |
| **调用方边界（服务层）** | ✅ | 「提交了参数」→「声明执行该 Stage」是**调用方意图翻译**，与 `__style`/`__scene` 控制键**同一层**（两者也在 `service/runtime.py` 解析） |

判据固化：**门控与否由 `param_schema` 是否声明 `enabled` 键决定（数据驱动）**，
不硬编码 stage 名单 —— 今日门控 9 个：`calibration / clarity / dehaze / hsl /
huesat / refine / region_adjust / skin / split_tone`。

---

## B. 修复清单

| # | 文件 | 问题 | 处置 |
|---|---|---|---|
| 1 | `render/web/session.py` | 缺「参数 ⇒ 意图」翻译 | 新增 **`translate_param_intents(patch)`**：① 门控 Stage 桶内含非 `enabled` 参数且未显式给 `enabled` ⇒ 注入 `True`；② `whitebalance` 给了 `temp`/`tint` 且未给 `mode` ⇒ 注入 `"manual"`。返回**新 dict**，不写回入参；**不覆盖**显式 `enabled`/`mode`；**不改数值** |
| 2 | `service/runtime.py` | 翻译未接线 | 在**卡·场景装配之后**、`session.update_params` 之前调用 ⇒ 卡里显式声明的 `enabled`/`mode` 优先，翻译只补空缺 |
| 3 | `pipeline/graph.py` | `float_or_str` 的 Stage 分支只放行 `numeric_seq` ⇒ `hsl.bands = list[dict]` **被渲染期拒绝**（栅栏却放行）⇒ 一动 HSL 面板就 400 | 补放行**结构序列**与 **dict**（元素结构由消费方自校验） |
| 4 | `graph.py` + `web/session.py` | `float_or_str` 的 dict 形态两端不同款：栅栏放行**任意** dict、Stage 只放行曲线 dict ⇒ 危险方向（栅栏放行 ⇒ 渲染期 500） | 抽 **`curve_dict_problem()`**（模块级、无依赖）为**唯一同源判据**，两端都调它；空 dict 保持两端一致的「no-op 放行」 |
| 5 | `modules/white_balance.py` + `modules/exposure.py` | WB 解析有**两份同源实现**（渲染线 `WhiteBalanceStage.process` / 测光探针线 `_probe_linear_srgb`）⇒ 改其一即静默分叉（探针按 A 组 WB 测光、实际按 B 组出图） | 抽 **`resolve_wb(ctx, p, image=None)`**；渲染线传 `self.p` 偏函数、探针线传 `params_for("whitebalance").get` + 降采样图 `small`（仅供 `auto` 分支取样） |
| 6 | `service/runtime.py` | **跨会话参数污染**：`_load_default_look()` 浅拷贝 `dict(cache)`，内层 stage 桶与模块级缓存**同一对象**，而 `_deep_merge` 是**原地**合并 ⇒ 用户改一次参数就改写缓存，**后续新建的会话继承上一次的编辑** | 两处返回改 `copy.deepcopy(...)`。实测：S1 置 `whitebalance=manual/temp7000` ⇒ S2（全新会话）初始参数即为该值；修后 S2 = `as_shot/temp=None` ✅ |
| 7 | `modules/hsl.py` | `bands` 的两种等价形态（`list[dict]` / JSON 串）未在 schema 处写清 | 注释补齐（**仅注释，零行为变化**） |

### 契约变更（1 处，显式记录）

**`whitebalance.mode="manual"` 且缺 `temp`**：旧行为 = 直接 `ValueError`；
新行为 = **以相机 as-shot CCT 播种**（LR 同义：切到 Manual 时 Temp/Tint 由
As Shot 播种）。播种基准由 RAW + DCP 唯一确定 ⇒ 属**域转换**不是观感猜测，
引擎可以自己算。只有「连基准都取不到」（无 `raw` 且无 `state["camera_wb"]`）
才报错。收益：UI 只拖**色调**滑杆（不发 temp）也成立。

---

## C. 证据

### C1. 端到端探针（真实 HTTP 通道：`POST /api/photos` → `.../sessions` → `PUT .../params` → `GET .../image`）

`V0` = 会话基线；`V1` = 只发参数值（**模拟前端 `patch()`**）；`V2` = 追加 `enabled:true`。
`d` = 平均绝对差（0..255），`px` = 差异像素占比。判定「生效」= `V1` 与基线不同
且**与 V2 逐位一致**（说明翻译器把 V1 补成了 V2）。

```
控件                         判定    V1(仅参数)                V2(+enabled)
clarity.strength            生效    d=3.37  px=50.1%        d=3.37  px=50.1%
refine.sharpen              生效    d=1.07  px=14.7%        d=1.07  px=14.7%
refine.chroma_denoise       生效    d=0.95  px=23.4%        d=0.95  px=23.4%
hsl.bands(red sat)          生效    d=0.30  px= 5.2%        d=0.30  px= 5.2%
dehaze.strength             生效    d=12.20 px=96.6%        d=12.20 px=96.6%
calibration.red_sat         生效    d=3.60  px=47.0%        d=3.60  px=47.0%
split_tone.highlights_sat   生效    d=8.43  px=69.4%        d=8.43  px=69.4%
skin.strength               生效    d=3.18  px=46.8%        d=3.18  px=46.8%
exposure.mode (对照)         生效    d=28.96 px=99.9%        d=28.96 px=99.9%
whitebalance.tint (对照)     生效    d=1.34  px=39.8%        d=1.34  px=39.8%
tone.contrast (对照)         ⚠️ 同   d=0.00  px= 0.0%        d=0.00  px= 0.0%
```

第二轮（补测）：

```
tone.highlights             无效果  d=0.00  px= 0%     ← 见 D1
tone.shadows                生效    d=3.93  px=33%
whitebalance.tint(仅)       生效    d=3.38  px=94%     ← 由 400 变为生效
wb.temp+mode=manual         生效    d=13.78 px=99%
hsl.bands(单带)              生效    d=0.30  px= 5%
region_adjust.sky.exp       无效果  d=0.00  px= 0%     ← 见 D3
```

`hsl.bands` **两种形态**（`list[dict]` 与 JSON 串）均 `PUT 200` + `GET 200`。

### C2. 尺子自检（证明一致性测试**有牙**）

`.artifacts/_r31_ruler_selfcheck.py` 把两处已修的分叉**回退成旧语义**再跑同一
探针矩阵（`tests/unit/test_param_type_consistency.py` 的性质断言）：

```
[现状 (已修)]                危险方向命中   0 条
[回退 hsl.bands 序列放行]     危险方向命中  60 条 / 20 个键
[回退 栅栏 dict 结构检查]     危险方向命中 100 条 / 20 个键
```

—— 修复前，**全部 20 个 `float_or_str` 键**在「非数值 list」与「非曲线 dict」
两个方向都是「栅栏放行、渲染期拒绝」。今日暴露的只有 `hsl.bands`（唯一被前端
送 list 的键），其余 19 个是潜伏地雷。

### C3. 回归

| 项 | 结果 |
|---|---|
| 全量 `pytest tests/` | **1730 tests / 0 failed / 0 errors / 7 skipped / 1 xfailed**（junitxml 口径；4m27s） |
| skip 明细 | 全部环境门或设计性（`PIXO_GATE_AUTOLOOP_RAW` / `RAW_PATH` / sapiens 权重 / OpenCV WebP 阈值 / `learned/` 目录未建），**无静默假绿** |
| 新增用例 | `tests/unit/test_param_intents_translate.py`（29 条）、`tests/unit/test_param_type_consistency.py`（6 条，含全 schema 探针矩阵） |
| 契约更新 | `test_wb_manual_exposure.py` / `test_wb_temp_tint.py` 的「缺 temp 必抛」改为「as-shot 播种 + 无基准才抛」 |

### C4. 预览↔导出 parity（主动核查 R28 教训）

导出线 `web/export.py` 复用 `RawPreviewSession.canonical_params()`，而后者
`merged.update(copy.deepcopy(self.params[stage]))` 读的正是**会话内已翻译**的参数
⇒ 两线**由构造保证同款**，不会重演「预览按 A 组、导出按 B 组」的分叉。

---

## D. 本轮发现、**未修**（需裁决）

### D1. 🔴 `tone` 六键域错配（最重的一条）—— 「滑杆存在但无效果」第二类

用 monkeypatch 抓 `tone._apply_sixkey` 的**真实输入**（`linear_rgb`，512 长边）：

```
L 分位:  p50=0.0139   p90=0.0473   p99=0.1681   p99.9=0.2758   max=0.3414
```

| 键 | 带通 `(lo, hi)` | 实测覆盖率 |
|---|---|---|
| highlights | `[0.55, 0.78]` | **0.000%** ← 死参数 |
| whites | `[0.75, 0.90]` | **0.000%** ← 死参数 |
| shadows | `[0.00, 0.14]` | **98.510%** ← 近乎全局增益，非区域隔离 |
| blacks | `[0.00, 0.08]` | **95.750%** ← 同上 |

**根因假设（属「旧标定 × 新底」家族，第 4 次）**：带通常数诞生于 rawlux 迁移期
（`git log -S "0.55, 0.78"` → `a9c1ddf`），**早于 R24（profile_curve 域修复）与
R28（`decode_raw` 恢复真线性）**。R28 的结论里已写明"以旧导出为基准的对照需重造"，
但没提「以旧尺度标定的**硬编码阈值**」要一并复核 —— 六键就是漏网的那一处。

**同类扫描**：`tone_map / clarity / dehaze / exposure / reshape / color_cal` 中
只有这一处（`exposure` 的 `sat_mask >= 0.985` 是传感器饱和判定，在真线性下反而
正确）⇒ 单点、有界。

**两个候选修法**（都属观感变更，需你裁决）：

| 方案 | 做法 | 优点 | 代价 |
|---|---|---|---|
| **A（推荐）域对齐** | 六键搬到 **gamma/显示域**（EOTF 之后）做，阈值 `0.55/0.75/...` 在那里天然对应"高光/近白"（中灰 ≈ 0.5） | 与 LR 同构（LR 的 Highlights/Shadows 就跑在感知域）；**与"整链偏暗"这条未清偿债解耦** | 需重标定四条带的 `(lo, hi, rec)`；六键不再作用于线性域，`_apply_sixkey` 调用点要移位 |
| B 就地重标 | 保持线性域，把阈值压到实测分位（如 highlights `[0.10, 0.25]`） | 改动最小 | 阈值仍**绑定当前（偏暗）的亮度域** —— 亮度债一旦清偿就要再改一次；分位法对场景敏感（夜景/雪景会跑偏） |

> 注：本条与 R30 记的「亮度轴 ΔL −83.5（1/3 量程）」是同源症状的两面 ——
> 整链偏暗既让用户觉得"又暗又灰"，也让六键的高光带永远不命中。

### D2. 🟡 `tone.contrast` 在默认观感下无效果（filmic-only 参数）

探针实测 `tone.contrast` → `d=0.00 px=0%`。`contrast`/`shoulder` 只在
`use_filmic=True` 分支被消费（源码 `tone_map.py:357` 自述，**属已知设计**），
而默认 `use_filmic=False` ⇒ 默认观感下**对比度滑杆无效果**。

定性：**不是 bug，是「参数存在但门未开」** —— 与本次修的那一类（`enabled`
未接线）同源但不同因：这里缺的是 `use_filmic` 这个前置开关，而不是
`enabled`。裁决点：要么让 UI 把 `contrast` 的拖动解释为「开启 filmic」，
要么把该滑杆从默认面板隐藏。**本轮未动。**

### D3. 🟢 `region_adjust` 需掩码（**既有设计，不修**）

无 `state["region_masks"]` 即跳过 —— 是 F13 的既定语义（"无掩码 = 无区域效果"），
非缺陷。已由既有用例 `tests/unit/test_region_adjust.py::test_wants_masks_state_missing`
锁定（`enabled=True` + 有 regions + 无掩码 ⇒ `wants()==False`），本轮**未扩大改动面**。

### D4. 🟢 `compose.coord` 缺省 `"norm"` 的 warn-once（R31 前半段发现，仍未处理）

---

## E. 交付物

| 文件 | 说明 |
|---|---|
| `src/pixo/render/web/session.py` | `translate_param_intents` + 栅栏 `float_or_str` dict 收敛 |
| `src/pixo/service/runtime.py` | 翻译接线（卡·场景之后）+ `_load_default_look` 深拷贝 |
| `src/pixo/render/pipeline/graph.py` | `float_or_str` 补放行序列/dict + `curve_dict_problem` 共享判据 |
| `src/pixo/render/modules/white_balance.py` | `resolve_wb` 抽取；`process` 收敛为一行 |
| `src/pixo/render/modules/exposure.py` | 探针线 WB 收敛到 `resolve_wb` |
| `tests/unit/test_param_intents_translate.py` | 新增 29 条（意图翻译全契约） |
| `tests/unit/test_param_type_consistency.py` | 新增 6 条（两端类型语义 + 全 schema 探针矩阵） |
| `tests/unit/test_wb_manual_exposure.py`、`test_wb_temp_tint.py` | manual 缺 temp 播种契约 |
| `.artifacts/_r31_enabled_wiring_probe.py`、`_probe2.py`、`_r31_ruler_selfcheck.py` | 取证工具（可复跑） |

**复现**：

```bash
PYTHONPATH=src D:/Python/Python312/tools/python.exe -m pytest tests/ -q \
    --junitxml=.artifacts/_r31_full.xml
PYTHONPATH=src D:/Python/Python312/tools/python.exe .artifacts/_r31_enabled_wiring_probe.py
PYTHONPATH=src D:/Python/Python312/tools/python.exe .artifacts/_r31_ruler_selfcheck.py
```
