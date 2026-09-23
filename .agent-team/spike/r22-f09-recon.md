# R22 F09 只读侦察 —— tech_debt #17 compose free 模式 px→全幅归一化

> 执行者：teammate `dev-geom`（队长复用通道，本会话第二次续派含 3 点追加要求）
> 日期：2026-09-10　范围：**只读侦察 + 精确改动清单**
> 纪律声明：**未修改任何业务/测试/文档文件**（本文件是唯一写入）；未跑真 RAW；未提交 git；未创建任何脚本文件（探针用 `python -c` 单次执行）。
> 所有 `file:line` 均为本次实读行号（Wave1 已落地，行号相对 exploration-r22 有漂移，见 §0 勘误）。

---

## §0 勘误：design/exploration 的行号与清单更正（先看这条）

| 项 | design/exploration 原文 | 实读事实 | 影响 |
|----|------------------------|----------|------|
| `test_gate_compose.py` 路径 | design §1/§2.4 写 `tests/unit/test_gate_compose.py` | 实际在 **`tests/regression/test_gate_compose.py`**（8.5 KB，mtime 08-22） | 派单时别写错目录（已按 regression 域归 tester/dev-1 协调） |
| `src/pixo/render/pipeline/params.py` | 任务书列此路径 | **不存在**。schema 聚合处 = `src/pixo/render/params.py`（由 `STAGE_CLASSES` 类属性派生）；点分键注册表 = `loop.py:68 _DOTTED_PARAM_REGISTRY` | "params.py 如涉 schema"落点应为 `render/modules/compose.py:204` + 复核 `render/params.py` |
| adopt_crop 行号 | `loop.py:1612-1652` | 实际 **`loop.py:1765-1805`**（`crop_adopted` trace 在 `:1794-1805`） | — |
| `_full_canvas_size` | `loop.py:1054-1063` | 实际 **`loop.py:1207-1216`** | — |
| `crop_suggest` 缺省 | `loop.py:736` | 实际 **`:884`（签名）/`:958`（赋值）** | — |
| 测试同步面清单 | design §1 列 ~10 处 | **漏了 `tests/unit/test_crop_wiring.py:157-181 / 184-211`**（adopt_crop 的直接单测，硬断言 px 值）；另 `test_region_masks_channel.py:239-244`（`_FakeCompose`）依赖开关缺省，是否需改取决于方案（§2.3） | 改漏 → 回归红；且这是「采纳边界」最核心的用例 |
| `docs/架构设计文档.md:384-393` | "legacy `"crop"` px 示例" | 实读确认键名是 `"crop"`；本轮实测 **`"crop" in STAGE_CLASSES == False`**（无 crop stage，`render/geometry/crop_rotate.py` 只是再导出模块）⇒ **该示例键名与坐标语义双陈旧**，更正时应同时改成 `compose` | 只改坐标不改键名 → 示例仍不可用 |

其余 exploration 关键事实**本次复核全部成立**：`"crop"` 无 stage、`compute_crop_rect` 无 `coord` 形参、compose `param_schema` 11 键无 `coord`、`gate_cases.py` 对 `compose`/`crop` **零命中**、`configs/**` 与 `resources/**` 的 `*.json` 对 `"compose"` **零命中**、`frontend/src` 对 `crop|compose` **零命中**。

---

## §1 像素↔相对坐标的每一处读 / 写 / 校验点

### 1.1 换算与定义层（`src/pixo/render/modules/compose.py`）

| file:line | 类型 | 当前语义 |
|---|---|---|
| `compose.py:63-68` `compute_crop_rect(h,w,mode,ratio,center,x,y,width,height)` | **换算/读** | 签名无 `coord`；`x/y/width/height` 一律按**本画布像素**解释 |
| `compose.py:76-77` | **校验（哨兵）** | `width is None or height is None or width<=0 or height<=0` → 返回全幅 `(0,0,w,h)`。**`default_params` 的 `width=0` 走的就是这里** ⇒ 归一化后 `0*w=0` 仍命中 ⇒ 默认路径逐位不变 |
| `compose.py:78-81` | **换算** | `x0=int(round(x))` … `ch=int(round(height))`：**唯一量化点**（银行家舍入，误差 ≤0.5px） |
| `compose.py:82-85` | **校验（钳位）** | `x0∈[0,w-1]`、`y0∈[0,h-1]`、`cw∈[1,w-x0]`、`ch∈[1,h-y0]` ⇒ 右/下边界钳位最多吃掉 1px（§4 容差第二项来源） |
| `compose.py:88-108` (mode=ratio) | 读 | `center` **本来就是归一化**（`:102-103` `cx=center[0]*w`）⇒ ratio 路径跨分辨率天然一致（现存 `test_gate_compose.py:180-199` 即以相对窗断言） |
| `compose.py:110-111` (auto_level) | 读 | 恒全幅，与坐标语义无关（仅 rotation 生效） |
| `compose.py:204-217` `param_schema` | **校验** | 11 键，**无 `coord`** ⇒ 若不登记，HTTP 严格栅栏会以「未知参数键」400（见 1.4） |
| `compose.py:219-233` `default_params` | **写（默认）** | `mode=free, x=y=width=height=0.0` ⇒ 全幅；新语义的缺省值应落在这里 |
| `compose.py:268-277` `ComposeStage.process` | **读** | 生产渲染链**唯一**读取点：四值原样喂 `compute_crop_rect` |
| `compose.py:295-311` `ctx.state["compose"]` | **写（元数据）** | `crop_rect` 写**像素后值** + `original_size`/`final_size`；`crop_rect` 语义保持 px（消费方是 geometry 语义，不应改成归一化） |
| `compose.py:316-326` `results[-1].metrics` | 写（指标） | `crop` 同样写 px 后值 |

### 1.2 掩码 shape 预测层（第二读取点 —— 必须同源）

| file:line | 类型 | 当前语义 |
|---|---|---|
| `region_masks.py:36-44` `_post_compose_shape` docstring | — | 自证「与 `modules/compose.ComposeStage.process` 同源（`compute_crop_rect` 纯函数）」← **这是「开关只能放在 compute_crop_rect」的证据** |
| `region_masks.py:46-47` | 校验 | `compose_params` 空/None → 原样返回（无裁剪预测） |
| `region_masks.py:51-60` | **读** | 用**同一** `compute_crop_rect` 预测 `(ch,cw)`；**传 x/y/width/height 但不传任何模式开关的兄弟键** ⇒ 新增 `coord` 必须在此同步透传，否则两线分叉 |
| `region_masks.py:107-112` | **写** | 只做 `cv2.resize` 形状对齐，**无坐标重映射** ⇒ 坐标语义完全跟随 compose（归一化后自动跟随） |

### 1.3 loop 侧

| file:line | 类型 | 当前语义 |
|---|---|---|
| `loop.py:265-275` `rect_px_to_norm` | 换算工具 | **零调用**（本次 grep 仅定义处）→ 归一化后作为 adopt_crop 的 legacy 迁移工具获得首个调用点 |
| `loop.py:278-289` `rect_norm_to_px` | 换算工具 | 仅被 `loop.py:1775`（adopt_crop）调用 |
| `loop.py:505-519` `_compose_fingerprint` | **校验（缓存键）** | `json.dumps(compose, sort_keys=True)` 全量 ⇒ 新增 `coord` 键会改指纹（保守失效，安全）；序列化失败退 repr |
| `loop.py:1183-1205` `_sync_region_masks` | 校验/写 | 指纹变化 → `_region_masks_soft=None` + warn-once（"不作为优于错作为"） |
| `loop.py:1207-1216` `_full_canvas_size` | **读** | `backend.full_size()` 真全幅（`RawRenderBackend.full_size:415-427` 读 rawpy sizes，如 6048×4032）；未知退回预览尺寸（`SyntheticRenderBackend.full_size:334-337` 返回源图尺寸）← **B1 基准的唯一来源** |
| `loop.py:1765-1793` `adopt_crop` | **读+写** | 见 §6 专节 |
| `loop.py:1944-1946` `run(compose_params=...)` | **写（入参面）** | `_deep_merge(loop_params, {"compose": deepcopy(compose_params)})` ⇒ 公开 API 直接吃 compose dict |
| `loop.py:1957` | 读 | `compose_params` trace 事件记录 compose 值 |
| `loop.py:2095-2097` `_result` | 读 | `compose_geometry = params["compose"]`（**注意：回填的是 params dict，不是 stage 输出的 geom**，命名易误解） |
| `bench_e2e_loop.py:100-109` | 写（默认） | `mode=ratio` ⇒ **中性**，不需改 |

### 1.4 HTTP / 校验面

| file:line | 类型 | 当前语义 |
|---|---|---|
| `render/params.py:29-57` | 聚合 | `STAGE_CLASSES`/`PARAM_SCHEMAS`/`DEFAULT_PARAMS` 由类属性派生（加 schema 键即自动生效） |
| `web/session.py:152-161` `_param_schemas` | **校验（派生源）** | 白名单唯一派生源 = `PARAM_SCHEMAS`（R22 F04 已落地） |
| `web/session.py:253-296` `validate_param_patch` | **校验** | strict：未知 stage / **未知键 → `ParamValidationError`（→HTTP 400）**；`:247-250` 校验 `choices` 枚举 |
| `web/session.py:532-535`（预览线） | 读 | `params.get("compose")` → `adapt_state_extras(..., compose)`，compose dict **原样透传**（无需改） |
| `web/export.py:60-64`（导出线） | 读 | 同上（**两线同函数 = 两线一致的前提**） |
| `loop.py:382-384`（synthetic 线） | 读 | 同上 |
| `render/geometry/crop_rotate.py:4-17` | 公开导出 | `compute_crop_rect` 是**公开 API**（第二导出面）⇒ 形参默认值变更会外溢 |
| `session.py:172-190`（`update_params`） | 写 | `_deep_merge` 原样落 params（F04 栅栏在其上）；compose 的 px 值**不会报错**，只会被按新语义解释 |

### 1.5 存量面（实证 0）

| 面 | 命令 | 结果 |
|---|---|---|
| `configs/**/*.json` | grep `"compose"\|"crop"\|"mode": "free"` | **0 命中** |
| `resources/**/*.json` | 同上 | **0 命中** |
| `frontend/src` | grep `crop\|compose` | **0 命中** |
| `tests/regression/goldens/gate_cases.py` | grep `compose\|crop` | **0 命中**（21 features 全无 compose case）✅ 复核成立 |
| 代码内 free px 写入 | `src/` | 仅 `compose.py:222`（全 0 默认，语义中性）与 `loop.py:1789-1792`（adopt_crop） |
| `docs/架构设计文档.md:384-393` | 人工 | 1 处（键名 `"crop"` + px 值，双陈旧） |
| **条件性存量面（新发现）** | `src/pixo/state/store.py:93-127` `save_state` | `photo_states.current_params` **会持久化含 compose 的 params JSON**；`loop_replay.export_previews` 会拿 `current_params`/decide 快照**再次渲染**（`test_loop_replay.py:203-226`）。仅当某次运行 `crop_suggest=True`（adopt_crop 生效）时才会写入 px 矩形 —— 生产 `runtime.py` **从不传 `crop_suggest`**（grep 零命中，缺省 `loop.py:884/958 False`）⇒ 生产库无此类记录，**开发/测试库与外部调用方残留**需一次性核查（§6.3） |

---

## §2 `compose.coord` 开关落点与 legacy `px` 逐位不变回归策略

### 2.1 落点：**只能放在 `compute_crop_rect` 内部**（唯一同源点）

理由（有源码自证）：
1. 它同时被**渲染线**（`compose.py:268`）与**掩码 shape 预测线**（`region_masks.py:51`）调用，且 `region_masks.py:41-42` 与类 docstring 明写"同源"。
2. 若把换算写在 `ComposeStage.process` 里，`_post_compose_shape` 仍按 px 预测 → **编译期无感、运行时静默分叉**（shape 与裁剪窗再次错位），等于没还债。
3. 放在纯函数里，`coord` 与 `mode` 同级成为**参数语义的一部分**，两线天然一致。

### 2.2 推荐实现（方案 A′，逐行）

```python
# compose.py 63-86
def compute_crop_rect(h, w, mode, ratio=None, center=(0.5,0.5),
                      x=0.0, y=0.0, width=0.0, height=0.0,
                      coord: str = "px"):            # ← 尾置关键字参数
    """... mode=free 且 coord="norm": x/y/width/height 为**全幅相对 [0,1]**; coord="px": 本画布像素(legacy) ..."""
    if mode == "free" and coord == "norm":
        # None 早退必须在缩放之前（否则 None*w 抛 TypeError）
        if width is None or height is None:
            return 0, 0, w, h
        x = float(x) * w;  y = float(y) * h
        width = float(width) * w;  height = float(height) * h
    # ↓↓↓ 以下与现行代码**逐字不变**（含 76-77 哨兵与 82-85 钳位）↓↓↓
    if mode == "free":
        ...
```
配套 4 处（全部单行级）：
- `compose.py:204-217` + `"coord": {"type": "str", "choices": ["norm", "px"]}` —— **必须登记**，否则 HTTP 面 400、且 `self.p` 取不到 schema 校验；
- `compose.py:219-233` default_params + `"coord": "norm"` —— **新语义的唯一天缺省源**；
- `compose.py:268-277` + `coord=str(self.p(ctx, "coord", "norm"))`；
- `compose.py:235` 附近加 `import logging` + 模块级 `_LOGGER`，并在 `process` 里 `coord == "px"` 时 **warn-once**（放 process 不放纯函数：纯函数每渲染被调 2 次，会双打日志）。

**为什么纯函数默认取 `"px"` 而不是 `"norm"`（方案 A″ 的取舍）**：
- A′（推荐）：公开 API `compute_crop_rect`/`geometry.crop_rotate` 的默认行为**不变** ⇒ 未显式传 `coord` 的**任何调用方**（含仓外）行为零变化；新语义只从 `default_params` 一处进入生产链。代价：`region_masks.py:51-60` 必须显式传 `coord=cp.get("coord","norm")`（否则预测线仍按 px → 分叉），`test_region_masks_channel.py:239-244` 的 `_FakeCompose` 同理。
- A″（备选）：纯函数默认 `"norm"` ⇒ `region_masks.py` 真的**零改动**（不传即 norm，与 stage 缺省巧合一致），但公开纯函数缺省语义翻转；且 `_FakeCompose` 也得显式改才能与 stage 对齐（不传即 norm，看似巧合正确，但那是**隐式耦合**而非契约）。
- 结论：A′ 把"同源"从**默认值巧合**升级为**显式契约**，并让 legacy 行为在纯函数层就被冻结 ⇒ 与 §4「legacy px 路径行为不变（回归可证）」判据最贴合。**推荐 A′**；若队长采 A″，则必须补 §3 的守门测试 T-G1 以兜住隐式耦合。

### 2.3 三条调用点必须同步（A′ 下）

| 调用点 | 改动 |
|---|---|
| `compose.py:268-277` | + `coord=self.p(ctx,"coord","norm")` |
| `region_masks.py:51-60` | + `coord=str(cp.get("coord","norm"))` |
| `tests/unit/test_region_masks_channel.py:239-244`（`_FakeCompose.run`） | + `coord=str(cp.get("coord","norm"))`（**测试替身必须镜像 stage 契约**，否则该文件用 free+rect 的会话用例会静默分叉） |
| `tests/regression/test_gate_compose.py` 5 处 | **显式 `coord="px"`**（见 §3） |

### 2.4 legacy `px` 逐位不变的**回归策略**（队长追加要求 ②）

三层证据，从强到弱：

**L1 —— 纯函数逐位（最强，零容差）**
```
∀ (w,h) ∈ {(64,48),(512,341),(1024,683),(2048,1365),(6048,4032)},
∀ 参数网格 (x,y,width,height)（含 0、负、越界、>1）:
  compute_crop_rect(h,w,"free",coord="norm", x=x, y=y, width=wd, height=ht)
    == compute_crop_rect(h,w,"free",coord="px",   x=x*w, y=y*h, width=wd*w, height=ht*h)   # 逐位相等
  compute_crop_rect(h,w,*,coord="px", …原参数…)  # 与改动前冻结快照逐位相等
```
排除 `mode=ratio`/`auto_level`（本次不碰）后，free 的 px 分支在 A′ 下是**同一条代码路径**，只需证明「入参相同 ⇒ 输出相同」。

**L2 —— 冻结快照（改动前后对拍，必须"先快照后改码"）**
在**改代码之前**执行一次（同 F02 "先备份旧 DLL" 的纪律）：
```
python -c "<探针>"    # 建议落 .artifacts/r22-f09-px-baseline.json（含 sha256）
```
快照内容 = ①上述参数网格的 `compute_crop_rect` px 输出全表；②`ComposeStage().run(ctx)` 的 `ctx.state["compose"]["crop_rect"]`；③可选 `_run_full_pipeline({"compose": {px 值}})` 的输出数组 sha256（合成图，不碰真 RAW）。
改动后 `--check`：`np.array_equal` 全 True、sha256 相同 ⇒ **逐位不变**。若派单时已错过"改动前"时点，则退化为 `git stash` 出旧版对拍（本会话未执行 git 操作）。

**L3 —— 既有用例回归（命令口径）**
```powershell
# ① legacy px 组合（把 5 处显式标 coord="px" 后，原断言本身就是逐位）
python -m pytest tests/regression/test_gate_compose.py -q
#    其中 test_crop_bit_exact:79-87 / test_flip_bit_exact:90-99 就是 np.array_equal(out, ref) 逐位
# ② 金样本 21 features 零漂移（无 compose case，但证明全链未被波及）
python tests/regression/goldens/generate_gate_goldens.py --check      # 期望 exit 0
python -m pytest tests/regression/test_gate_golden.py -q
# ③ 掩码/闭环侧
python -m pytest tests/unit/test_region_masks_channel.py tests/unit/test_decide_region_wiring.py `
                 tests/unit/test_crop_wiring.py tests/integration/test_loop_e2e.py -q
# ④ 全量（红线）
python -m pytest tests/ -q -m "not e2e"        # ≥1574 passed / 0 failed
```
> PowerShell 5.1 落盘坑（本仓既有教训）：`>` 默认 UTF-16LE，需
> `cmd /c "set PYTHONIOENCODING=utf-8&&python -m pytest … > .agent-team\tmp-*.txt 2>&1"`。

**判据口径**：`px` 分支行为 = 改动前**逐位**（L1/L2）＋ 既有 5 处断言不改语义（L3①）。仅"全量绿"不算证（无 compose 用例时全量绿也可能掩盖语义翻转）。

---

## §3 受影响测试清单（逐条：文件:行 → 怎么改 → 为何）

### A. 必改（语义切换直接命中）

| # | 文件:行 | 怎么改 | 为何 |
|---|---|---|---|
| T1 | `tests/unit/test_region_masks_channel.py:637-672` `test_free_px_rect_cross_resolution_geometry_mismatch_recorded` | **有意翻转重写**（见下 T1 详案） | tech_debt #17 钉死用例，docstring `:646-647` 已写翻转契约 |
| T2 | `tests/regression/test_gate_compose.py:81` | `_run_compose(img, mode="free", coord="px", x=7,y=5,width=20,height=15)` | 「纯裁剪逐位一致」是机制断言，不是单位语义断言；显式 px 即 **legacy 冻结** |
| T3 | 同上 `:92` | + `coord="px"`（flip 逐位） | 同上 |
| T4 | 同上 `:118` | + `coord="px"`（rotation PSNR≥60） | 同上 |
| T5 | 同上 `:135` | + `coord="px"`（`width=w,height=h` 同尺寸） | 同上 |
| T6 | 同上 `:149` | + `coord="px"`（几何元数据） | 同上 |
| T7 | `tests/unit/test_crop_wiring.py:173-178` | 期望改**归一化**：`assert compose["coord"]=="norm"` 且 `(x,y,width,height) == pytest.approx((0.25,0.25,0.5,0.5))`；删除 `expect = rect_norm_to_px(...)` | **design 清单漏项**：adopt_crop 直接单测，硬断言 px 四元组 |
| T8 | `tests/unit/test_crop_wiring.py:201-209` | 同上改为 norm 期望（`rotation==-3.5` 保留断言不变） | 同上（merge 场景） |
| T9 | `tests/integration/test_loop_e2e.py:69` | `compose_params={"mode":"free","coord":"px",…}`（保留 32×32 断言）**或**改 `{"coord":"norm","x":.125,"y":.125,"width":.5,"height":.5}` 并保留 `final_image.shape==(32,32,3)` | 64×64 画布上 px(8,8,32,32) 在 norm 下会被钳成 1px 宽 ⇒ 必红 |
| T10 | `tests/unit/test_decide_region_wiring.py:514-515` | 文本改语义标注（`"coord":"norm"` 或改 px 键）；`:583` 增加 `compose["coord"]=="norm"` 断言 | 该处只是"指纹变化的构造样本"，加 `coord` 能顺带锁住新键进指纹 |
| T11 | `tests/unit/test_decide_region_wiring.py:488-491` | 两处 compose 样本加 `"coord"` 键（键序无关断言 `:492` 仍成立） | 同上；顺带覆盖"coord 参与指纹" |
| T12 | `tests/unit/test_region_masks_channel.py:239-244`（`_FakeCompose.run`） | + `coord=str(cp.get("coord","norm"))` | 测试替身必须与 `_post_compose_shape` 同源（A′ 方案下是硬要求） |
| T13 | `tests/unit/test_region_masks_channel.py:135-147` | 仅**复核**不需改：`:142` `{"mode":"free"}` 无 rect ⇒ `width=0` 全幅哨兵，语义中性 | 复核结论：确为中性（实测 `width<=0 → (0,w,h)`） |

### B. 复核但语义中性（不改）

| 文件:行 | 复核结论 |
|---|---|
| `tests/unit/test_compose_autolevel.py:109` `{"mode":"free"}` | `width=0` → 全幅哨兵；`AUTO_LEVEL` 只在 auto_level 模式生效 ⇒ 中性 |
| `tests/unit/test_loop_replay.py:48` | trace 事件 `value={"mode":"free"}`，无 rect、不参与渲染 ⇒ 中性 |
| `tests/unit/test_crop_wiring.py:135-154` `test_rect_converters_roundtrip` | 只测 `rect_norm_to_px/rect_px_to_norm` 两个独立工具函数（本次不改）⇒ 中性；**但它是容差口径的既有先例**（`:149 tol = 1.0/min(w,h)`）→ 见 §4 |
| `tests/unit/test_render_public_adapters.py:100` | 仅 `callable(compute_crop_rect)` ⇒ 中性（加尾置关键字参数不破坏） |
| `tests/unit/test_pipeline.py` / `test_f04_param_fence.py:84-100` | 栅栏"派生性"测试：新增 schema 键自动放行 ⇒ **加 coord 后应仍绿**（顺带成为 F04×F09 的交叉证据） |

### C. 新增用例（建议）

| # | 位置 | 内容 |
|---|---|---|
| N1 | `tests/unit/test_compose_coord.py`（新建，dev-1 域） | ① **逐位等价**：`coordinate="norm"` 与 scaled-px 逐位相等（§4 表达式 E1）；② **跨 tier 相对窗**（§4 表达式 E2，用既有容差先例）；③ `coord="px"` 命中 deprecated warn-once；④ `width=0→全幅` 在两种 coord 下同结果；⑤ `width=None` 不抛 TypeError |
| N2 | 同文件 | **同源守门测试 T-G1**：对同一 compose dict，`region_masks._post_compose_shape((h,w), cp) == tuple(reversed(ComposeStage().run(ctx) 的 final_size))`（norm/px 两态各一例）⇒ 把"两线同源"变成机器不变量 |
| N3 | `tests/unit/test_crop_wiring.py` | **legacy 迁移用例**：`params={"compose":{"mode":"free","coord":"px","x":16,"y":16,"width":48,"height":48}}` + `crop_suggest=True`（Synthetic backend fw=fh=64）→ 采纳后 `coord=="norm"` 且四值 ≈ (0.25,0.25,0.5,0.5)，**不得**出现 px/norm 混用 |
| N4 | `tests/regression/goldens/gate_cases.py` + `FEATURES` | **新增 1 个 compose gate case**（现零覆盖，21→22）：`_run_full_pipeline({"compose": {"mode":"free","coord":"norm","x":0.1,"y":0.1,"width":0.5,"height":0.5}})`；baseline 属**首次生成**，须队长 A2 书面授权 + 证据落 `.artifacts/r22-compose-case-baseline.md`；生成前后各跑一次 `--check`（生成前必须 exit 0 = 既有 21 features 零漂移） |

### D. T1「有意翻转」的**建议写法**（精确到可粘贴）

```python
def test_free_norm_rect_cross_resolution_relative_window_consistent():
    """#17 清偿后的正面不变量（翻转自 test_free_px_rect_cross_resolution_geometry_mismatch_recorded）。

    旧行为记录（保留于本 docstring，勿删）：px 语义下同一矩形在两 tier 的相对裁剪窗
    为 50% vs 25%（x=50 在 100 宽帧 / 200 宽帧），掩码逐位相同 = 失配可观测面。
    清偿后不变量 = **同一归一化参数跨 tier 的相对裁剪窗一致**；
    不得简化为「两线掩码不相等」（那是另一侧的错误钉死）。
    """
    from pixo.render.modules.compose import compute_crop_rect
    from pixo.render.pipeline.region_masks import _post_compose_shape

    tiers = [(100, 50), (200, 100)]                    # (w, h) 两线
    norm = dict(mode="free", coord="norm", x=0.5, y=0.0, width=0.5, height=1.0)

    def rel(rect, w, h):
        x0, y0, cw, ch = rect
        return (x0 / w, y0 / h, cw / w, ch / h)

    wins = [rel(compute_crop_rect(h, w, **norm), w, h) for (w, h) in tiers]
    # ① 主不变量：相对裁剪窗一致（容差 = 整数像素量化，来源见 §4）
    (w_a, h_a), (w_b, h_b) = tiers
    a, b = wins
    assert abs(a[0] - b[0]) <= 1.0 / min(w_a, w_b)   # x0/w
    assert abs(a[1] - b[1]) <= 1.0 / min(h_a, h_b)   # y0/h
    assert abs(a[2] - b[2]) <= 1.0 / min(w_a, w_b)   # width/w
    assert abs(a[3] - b[3]) <= 1.0 / min(h_a, h_b)   # height/h
    # ② 掩码 shape 仍两线一致（同源预测 ⇒ post-compose 帧同尺寸）
    assert (_post_compose_shape((50, 100), norm) ==
            _post_compose_shape((100, 200), norm) == (50, 50))
    # ③ 掩码逐位相等的**适用条件**（shape 相同时仍是正确结果，不可反转为不等）
    m_a = adapt_region_masks({"sky": _top_band_mask(50, 100)}, (50, 100), norm)
    m_b = adapt_region_masks({"sky": _top_band_mask(100, 200)}, (100, 200), norm)
    assert m_a["sky"].shape == m_b["sky"].shape == (50, 50)
    # 注：此处语义正确性由 ① 保证；若断言逐位相等，需先证明两 tier 入参掩码在
    # 相对坐标系下同源（本用例的 _top_band_mask 满足），故保留逐位相等是对的。
```
> ⚠️ 翻转的**唯一禁止项**：把 `assert np.array_equal(...)` 改成 `assert not np.array_equal(...)`。
> 正确落点是 ①（相对窗一致）＋ ③ 的适用条件写明。

### E. 其它需同步的文件（非测试）

| 文件:行 | 改动 |
|---|---|
| `docs/架构设计文档.md:384-393` | `"crop"` → `"compose"`，`{x:100,y:80,w:3000,h:2000}` → 归一化示例（如 `{x:0.1,y:0.1,width:0.5,height:0.5,coord:"norm"}`）+ 补一句 legacy `coord:"px"` 说明 |

---

## §4 「两线相对裁剪窗一致」的可判定表达式（队长追加要求 ①）

### E1 —— 零容差逐位判据（最强，优先落这条）

```python
# 归一化线 == 把归一化参数换算成该画布像素后走 legacy px 线（逐位，无容差）
for (w, h) in TIERS:                                        # TIERS 见下
    assert compute_crop_rect(h, w, "free", coord="norm",
                             x=0.25, y=0.20, width=0.50, height=0.60) == \
           compute_crop_rect(h, w, "free", coord="px",
                             x=0.25 * w, y=0.20 * h,
                             width=0.50 * w, height=0.60 * h)
```
成立性：norm 分支只做 `float(p) * dim` 后落入**同一段** px 代码；两侧的浮点乘积是同一 IEEE754 运算 ⇒ `int(round())`/`np.clip` 结果必然相同。这条同时就是"legacy px 路径逐位不变"的机器证明。

### E2 —— 跨 tier 相对裁剪窗一致（用户可感知的主不变量）

**表达式（分子/分母写死）**
```
rel(rect, w, h) := ( x0 / w , y0 / h , cw / w , ch / h )
                  # 分子 = compute_crop_rect 输出的像素后值 (x0,y0,cw,ch)
                  # 分母 = 该 tier 的**实际画布**尺寸 (w,h)，即 original_size
断言： ∀ tier ∈ TIERS，∀ i∈{0,1,2,3}:  |rel_tier[i] − rel_ref[i]| ≤ 1.0 / min(dim_tier_i, dim_ref_i)
      dim 取 w（i=0,2：x0 与 width 同属横轴）或 h（i=1,3：y0 与 height 同属纵轴）
      ref = 全幅 tier（6048×4032）
```
**tier 列表（本项目口径：`preview_long_edge` ∈ {512,1024,2048} + 导出全幅）**，以 Nikon Z5 2（6048×4032）为例：

| tier | (w, h) 实际画布 | 备注 |
|---|---|---|
| 512 | (512, 341) | 生产/门禁最严 tier（短边最小 ⇒ 容差最大） |
| 1024 | (1024, 683) | **生产缺省** `preview_long_edge=1024`（`runtime.py:908`） |
| 2048 | (2048, 1365) | — |
| 全幅 | (6048, 4032) | 导出线（`RawRenderBackend.full_size:415-427`） |

**容差来源（推导 + 实测，二者都给出）**
- **性质**：纯**整数像素量化**误差，来自 `compose.py:78-81` 的 `int(round())`（银行家舍入，单坐标 ≤0.5px）与 `:82-85` 的右/下边界钳位（最多再吃 1px）；**与 `cv2.resize` 重采样无关**（`region_masks.py:107-112` 只改 shape）。
- **推导**：`|round(x·w)/w − x| ≤ 0.5/w`（无钳位时）；跨 tier 相减 ⇒ `≤ 0.5/w_a + 0.5/w_b ≤ 1.0/min(w_a,w_b)`。故取 `tol_axis = 1.0 / min(dim_a, dim_b)`。
- **既有先例（本仓同一容差口径）**：`tests/unit/test_crop_wiring.py:149` 对 `rect_norm_to_px∘rect_px_to_norm` 往返即用 `tol = 1.0 / min(w, h) + 1e-9` —— 本次沿用同一口径，不引入新魔数。
- **实测（本次真机探针，参数 x=0.25, y=0.20, width=0.50, height=0.60，自由函数现版本）**：

| tier (w,h) | px 输出 | rel 四元 | 与全幅最大偏差 | 界 `0.5/dim` |
|---|---|---|---|---|
| (512,341) | (128, 68, 256, 205) | (0.25, 0.199413, 0.5, 0.601173) | **1.223e-3**（height/h） | 1.466e-3 ✅ |
| (1024,683) | (256, 137, 512, 410) | (0.25, 0.200586, 0.5, 0.600293) | 6.85e-4 | 7.32e-4 ✅ |
| (2048,1365) | (512, 273, 1024, 819) | (0.25, 0.200000, 0.5, 0.600000) | 9.9e-5 | 3.66e-4 ✅ |
| (6048,4032) | (1512, 806, 3024, 2419) | (0.25, 0.199901, 0.5, 0.599950) | 0（参照） | — |

  ⇒ 观测最大偏差 **1.223e-3**，`1.0/min(341,1365)=2.932e-3` 界内（2.4× 余量）。**不要用 5e-4 之类的"看起来紧"的常数**（512 tier 短边会直接翻红）。
- **边界声明（必须写进测试注释）**：断言前提是 `x+width ≤ 1` 且 `y+height ≤ 1`（避免右/下钳位）；若取 `x=1.0` 或 `x+width>1`，则 `x0` 被钳到 `w−1`，偏差可达 `1/min dim`（仍是同一容差公式，但会顶满）。
- **同 tier 两会话**：`dim_a == dim_b` ⇒ `tol = 1/dim` 仍成立，但实际应**逐位相等**（可另加 `assert rel_a == rel_b` 的强断言）。
- **ratio 路径对照**（既有先例口径，勿混用）：`tests/regression/test_gate_compose.py:180-199` 对 ratio 模式用 `≤0.02`（因 ratio+center 引入两次舍入 + `cw` 取整），**F09 不应把 free 的容差放宽到 0.02**，否则等于放弃可判定性。

---

## §5 风险点

| # | 风险 | 证据/结论 | 规避 |
|---|---|---|---|
| R1 | **金样本 21 features 是否漂移** | `gate_cases.py:25-42` 恰 21 个 feature，grep `compose\|crop` **0 命中** ⇒ 无 compose case。且三个全管线 case（`default_dispatch`/`card_portra_400`/`region_adjust`）都不传 compose 键 ⇒ 走 `default_params`（`width=0`）⇒ `0*w=0` 命中原哨兵 `compose.py:76-77` ⇒ **逐位不变**（前提：norm 分支把 `None` 早退放在缩放前，否则 `None*w` 抛异常；见 §2.2） | 改动后跑 `generate_gate_goldens.py --check`（期望 exit 0）+ `test_gate_golden.py`；新增 case 的 baseline 首次生成须队长 A2 授权 |
| R2 | **`adopt_crop` 写入面**（混用语义） | `loop.py:1786-1793` 用 `{**prev_compose, "x":x0(px), …}` ⇒ 若 `prev_compose` 带 `coord:"px"`，合并后 coord 仍为 px 而四值是新写 norm ⇒ **绝对值被当像素**（0.25 px → 1px 窗）。且当前写的是 `rect_norm_to_px(rect, fw, fh)` 的**全幅 px** | 必须改写为 norm 四值 + **强制** `"coord":"norm"`（覆盖而非继承）；legacy px 入参走 `rect_px_to_norm` 迁移（§6） |
| R3 | **掩码层是否真的零改动** | `region_masks.py:51-60` 与 `compose.py:268` 同源 ⇒ **shape 预测自动跟随**，`:107-112` 无坐标重映射 ⇒ 坐标语义也跟随 ⇒ **逻辑上零改动**。但 A′ 方案下**要改 1 行**（透传 `coord`），否则预测线仍按 px（A″ 下可不改，靠缺省巧合） | 加 T-G1 守门测试把"同源"固化为不变量；勿只靠缺省值 |
| R4 | 右/下边界钳位带来的容差放大 | `compose.py:82-85` 单侧最多吃 1px；极端参数（x=1.0、x+width>1）偏差顶满 `1/min dim` | 测试参数取内点（§4 已声明前提）；另加一条"钳位形态"断言证明钳位公式未变（px 冻结快照已覆盖） |
| R5 | HTTP 面 legacy px 静默改义 | `session.py:175-180` 无校验、`validate_param_patch` 只查 schema ⇒ 不带 `coord` 的 px 入参会按 norm 解释（如 width=3000 → 全幅、x=100 → 钳到 w−1、cw=1 ⇒ **1px 宽画面**） | ① 仓内实证 0 处（§1.5）；② `coord` 必须进 param_schema（否则连显式 `coord:"px"` 都被 400 拒）；③ 加**启发式告警**（§6.3）让"疑似 px"可观测；④ docs 明示 |
| R6 | 公开 API 默认值翻转 | `compute_crop_rect` 经 `geometry/crop_rotate.py:4-17` 对外导出 ⇒ 若纯函数默认取 `"norm"`（A″），仓外调用方静默改义 | 采用 A′（纯函数默认保持 `"px"`） |
| R7 | 测试替身不同源 | `test_region_masks_channel.py:239-244` `_FakeCompose` 自行调 `compute_crop_rect`（未传 coord）；现有会话用例**没有** free+rect 覆盖 ⇒ **不同源不会被抓** | A′ 下必须显式改该替身 + T-G1 守门测试 |
| R8 | 持久化 px 残留（新发现） | `state/store.py:93-127` 持久化 `current_params`（含 compose），`loop_replay.export_previews` 会回放重渲 | 生产 `crop_suggest` 恒 False ⇒ 生产库无记录；抽样核查见 §6.3 |

---

## §6 `adopt_crop` 写入面专节（队长追加要求 ③）

### 6.1 现状机制（实读 `loop.py:1765-1805`）

```
:1765-1768  adopt_crop = (crop_suggestion is not None
                          and decided_params.pop("compose.apply_suggestion", None) == 1)
:1772-1777  fw, fh = self._full_canvas_size(backend, preview_w, preview_h)   # 真全幅，如 6048×4032
            x0, y0, x1, y1 = rect_norm_to_px(crop_suggestion["rect"], fw, fh)  # 归一化 → **全幅 px**
:1781-1785  prev_compose = params.get("compose") if isinstance(..., dict) else {}
:1786-1793  params["compose"] = {**prev_compose, "mode": "free",
                                 "x": x0, "y": y0,
                                 "width": max(1, x1-x0), "height": max(1, y1-y0)}   # 写入全幅 px
:1794-1805  trace event_type="crop_adopted"（把 params["compose"] 原样留证）
```

三处语义缺陷（在归一化语境下全部致命）：
1. **写入 = 全幅 px**，随后 preview 线（512/1024 画布）按同值裁剪 ⇒ 正是 #17 的主症状。
2. **`{**prev_compose, …}` 会继承 `coord`**：prev 为 `coord:"px"` 时，新写的 norm 四值被按 px 解释（0.25 → 钳到 0，cw=1）⇒ 画面变 1px。
3. **同 dict 混用两种坐标系**：`x/y/width/height` 已换语义，`coord` 却由 prev 决定 ⇒ 无自描述性。

### 6.2 改法（推荐）

```python
# loop.py 1765-1805 区间
adopt_crop = (...)
if adopt_crop:
    fw, fh = self._full_canvas_size(backend, preview_img.shape[1], preview_img.shape[0])
    prev_compose = params.get("compose") if isinstance(params.get("compose"), dict) else {}
    # ① 存量 legacy px → norm 一次性迁移（B1 基准 = 全幅，坐标可判定）
    base = dict(prev_compose)
    if str(base.get("coord", "norm")) == "px":
        px = [float(base.get("x", 0.0) or 0.0), float(base.get("y", 0.0) or 0.0),
              float(base.get("x", 0.0) or 0.0) + max(float(base.get("width", 0.0) or 0.0), 0.0),
              float(base.get("y", 0.0) or 0.0) + max(float(base.get("height", 0.0) or 0.0), 0.0)]
        nx0, ny0, nx1, ny1 = rect_px_to_norm(px, fw, fh)      # ← 该函数首个真实调用点
        base.update({"x": nx0, "y": ny0,
                     "width": max(nx1 - nx0, 1e-6), "height": max(ny1 - ny0, 1e-6)})
        # 说明：min 用 1e-6（tier 无关）而非 1/fw —— 若用 1/fw，norm 值会随 tier 变
    # ② 建议矩形本身已是归一化 [x0,y0,x1,y1] ⇒ 直接落 norm，无需再经 rect_norm_to_px
    x0, y0, x1, y1 = (float(v) for v in crop_suggestion["rect"])
    params["compose"] = {**base, "mode": "free", "coord": "norm",   # ← 强制覆盖，禁止继承
                         "x": x0, "y": y0,
                         "width": max(x1 - x0, 1e-6), "height": max(y1 - y0, 1e-6)}
```
要点：
- **`coord:"norm"` 必须是显式覆盖项**（放在 `{**base, …}` 的右侧），否则 §6.1 缺陷 2 直接复现。
- `x1-x0` 的**退化保护**改用 **tier 无关的 `1e-6`**：`compute_crop_rect` 的 `cw=clip(round(width*w),1,…)` 已保证 ≥1px，无需在写入侧用 px 下限；用 `1/fw` 会让 norm 值随 tier 漂移。
- `rect_norm_to_px` 在本路径**不再需要**（保留为公开工具/px 兼容与调试用）；`rect_px_to_norm` 获得首个调用点。
- trace（`:1794-1805`）原样留证即可，但建议 metadata 补 `"coord":"norm"`（便于 `loop_replay` 读者判断坐标系）。

### 6.3 是否需要一次性迁移 / 版本标记？—— **判断与依据**

**结论：不需要数据迁移，也不需要版本字段；需要的是「显式 `coord` 落新值」+「三类入参的显式处置」。**

依据（全部实证）：
1. **仓内持久化 px 矩形 = 0**：`configs/**/*.json`、`resources/**/*.json`、`frontend/src` 三处 grep 零命中；`gate_cases.py` 零命中；代码内唯一持久写入者 `adopt_crop` 在生产**从不被触发**（`runtime.py` grep `crop_suggest` 零命中，缺省 `loop.py:884/958 = False`）。⇒ 没有需要批量改写的存量资产，「一次性迁移脚本」无对象可迁。
2. **迁移的坐标可判定性只在 adopt_crop 存在**：`compute_crop_rect` 只见**当前画布**（正是 px 语义产生 tier 依赖的那个分母）⇒ **禁止**在纯函数里"自动把 >1 的值当 px 换算"（在 512 tier 上换算会得到 512 基准的 norm，与导出线不一致，等于把债务换个地方）。因此**不允许隐式迁移**，只允许在已知 `fw/fh` 的 adopt_crop 处显式转换（§6.2 ①）。
3. **版本标记**：不需要新增 schema 字段（如 `compose.version`）——
   - params 不是"有版本的概念实体"，而是每次请求的即时入参；`coord` 本身**就是**自描述的版本标记（缺省即新语义）；
   - 旧记录（§1.5 的条件性存量面）只在**开发/测试库**可能含 px：核查命令
     ```powershell
     python -c "import sqlite3;c=sqlite3.connect('<db>');print(c.execute(\"select count(*) from photo_states where current_params like '%\"compose\"%'\").fetchone())"
     ```
     （生产 DB 若命中 >0，说明有人开过 `crop_suggest`，需人工判定；仓内默认永远 0）
   - 若队长仍要求可审计，最小代价是 **不新增字段**，而在 `docs/架构设计文档.md` 更正段写明"缺省 norm / `coord:\"px\"` legacy 保留一个版本"。
4. **必须补的两条可观测性**（替代"版本标记"的职责）：
   - a) `adopt_crop` 出口恒为 `coord:"norm"`（自描述，任何下游读到都无歧义）；
   - b) **启发式告警**：`ComposeStage.process` 中当 `coord` **缺失** 且 `any(abs(v) > 1.0 for v in (x, y, width, height))` → warn-once「疑似 legacy px 矩形被按 norm 解释（design §2.4）」。
     - 免误报依据：`default_params` 的四值全为 0（`0 ≤ 1`）；`width<=0` 的全幅哨兵不受影响；只有真正 >1 的 px 量级值才命中。
     - **不做自动纠正**（理由见依据 2），保持"可观测 + 文档"两条腿。

---

## §7 最小实施顺序（每步单独可验证）

> 前置纪律：**S0 必须在任何代码改动之前**执行（同 F02「先备份旧 DLL」——没有基线就没有"逐位不变"）。
> 文件域：`compose.py` / `region_masks.py` / `loop.py` / `docs/架构设计文档.md` / `tests/**` 归 W3 `dev-1`；`gate_cases.py` 需与 `tester` 串行（design §3）。

| 步 | 动作（文件） | 验证（单步） | 预期 |
|---|---|---|---|
| **S0** | **冻结 legacy px 基线**（只读探针，落 `.artifacts/r22-f09-px-baseline.json`）：① free 参数网格的 px 输出；② `ComposeStage` 元数据；③ 合成图全管线 px 输出 sha256 | `python -c "<探针> --write"` 记 sha256 | 基线落盘，含 sha256 |
| S1 | `compose.py` 五处：签名 `coord="px"` + norm 分支 + schema 键 + default `"norm"` + `process` 传参 + deprecated warn-once | ⓐ `python -c` 跑 S0 探针 `--check` → 全 True；ⓑ `pytest tests/regression/test_gate_compose.py -q` | ⓐ 全绿（legacy 未变）；ⓑ **5 处预期红**（证明语义确实切换）——红是预期证据，不是故障 |
| S2 | 测试同步：`test_gate_compose.py` 5 处 +`coord="px"`；`test_loop_e2e.py:69`；`test_crop_wiring.py:173-178/201-209`；`test_decide_region_wiring.py:488-491/514`；T1 翻转重写 | `pytest tests/regression/test_gate_compose.py tests/unit/test_crop_wiring.py tests/unit/test_region_masks_channel.py tests/unit/test_decide_region_wiring.py tests/integration/test_loop_e2e.py -q` | 全绿（S1 的红转绿 = legacy px 冻结生效） |
| S3 | `region_masks.py:51-60` +`coord` 透传；`test_region_masks_channel.py:239-244` `_FakeCompose` +`coord`；新增 T-G1 守门测试（N2） | `pytest tests/unit/test_region_masks_channel.py -q`（T-G1 必须真能翻红：临时把 `coord` 去掉应红） | 两线同源被机器固定 |
| S4 | `loop.py:1765-1805` adopt_crop 改写（norm 写入 + coord 强制 + px 迁移分支）；N3 迁移用例 | `pytest tests/unit/test_crop_wiring.py tests/unit/test_decide_region_wiring.py tests/integration/test_loop_e2e.py -q`；`rect_px_to_norm` 调用点 grep 由 0 → 1 | 全绿；adopt_crop 出口 `coord=="norm"` |
| S5 | `docs/架构设计文档.md:384-393` 更正（键名 + 坐标语义 + legacy 说明） | 人工复核；`python -c "from pixo.render.params import STAGE_CLASSES;print('crop' in STAGE_CLASSES)"` → False 佐证示例键名陈旧 | 示例可执行 |
| S6 | N4 新增 compose gate case（`gate_cases.py`，**与 tester 串行** + 队长 A2 授权） | 生成**前**：`python tests/regression/goldens/generate_gate_goldens.py --check` → exit 0（既有 21 features 零漂移）；生成（授权单点）→ 生成**后** `--check` → exit 0（22 features） | 21 不漂移 + 新 case 首版基线落证 |
| S7 | 全量收口 | `python -m pytest tests/ -q -m "not e2e"`；`python -m pytest tests/regression/test_gate_golden.py -q` | ≥1574 passed / 0 failed；金样本 u8_max=u16_max=0 |

改动量估算：`src/` ≈ 30~40 行（compose ≈14、region_masks 1、loop ≈12），`tests/` ≈ 7 文件，`docs/` 1 段。

---

## 结论

**F09 是"改一个纯函数 + 一个写入点"的低风险改动：`compute_crop_rect` 增加 `coord` 开关（纯函数默认保持 `px`，新语义只从 `default_params` 进入），`region_masks` 同步透传 1 行即两线同源，`adopt_crop` 改写为归一化并强制 `coord:"norm"`；存量迁移面经实证为空集，无需迁移脚本或版本字段，但设计漏掉的 `test_crop_wiring.py` 两处硬断言与 `_FakeCompose` 测试替身必须同步，且"逐位不变"证据必须在改码前先冻结基线。**

### 3 条最关键发现

1. **开关唯一可行落点是 `compute_crop_rect` 内部**（`region_masks.py:41-42` 自证两线同源）：放在 `ComposeStage` 里会让掩码 shape 预测线继续按 px 走，**编译期无感、运行时静默分叉**——等于没还债；而放在纯函数里，掩码层逻辑零改动（A′ 下仅 1 行透传）。
2. **design §2.4 的测试同步清单漏了 `tests/unit/test_crop_wiring.py:173-178 / 201-209`**（adopt_crop 的直接单测，硬断言 `rect_norm_to_px` 的 px 四元组），另 `test_region_masks_channel.py:239-244` 的 `_FakeCompose` 是不传 `coord` 的"不同源测试替身"且当前**无 free+rect 用例覆盖** ⇒ 不改不会被任何测试抓到，需专门加同源守门断言（T-G1）。
3. **"逐位不变"必须靠零容差等式 + 改动前基线，而非全量绿**：① `compute_crop_rect(coord="norm", x…) == compute_crop_rect(coord="px", x*w…)` 是**无容差**的机器证明；② 跨 tier 相对窗容差有严格来源与既有先例（`test_crop_wiring.py:149` 的 `1.0/min(w,h)`），实测 512↔全幅最大偏差 **1.223e-3**，界 `1.0/min(341,1365)=2.932e-3`；③ 金样本 21 features 无 compose case、默认 `width=0` 走全幅哨兵 ⇒ 零漂移，但这也意味着**全量绿不能证明 compose 语义未被误改**，所以 S0 冻结基线不可省。
