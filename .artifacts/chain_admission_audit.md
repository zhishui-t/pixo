# 默认管线准入审计 —— 引擎里还挂进来哪些"自发动作"

日期：2026-09-14 ｜ 触发问题：用户发现磨皮（skin）默认在跑，追问"有没有其他动作挂进来了"

## 一、方法与口径

对 `DEFAULT_STAGES` 全部 15 个 Stage 做三项检查：

1. **空上下文自发执行**：构造空 `StageContext`（无 state、无 config 覆盖），调 `wants()` —— `True` 表示"无人下指令也会跑"（`_pipeline_audit.py`）
2. **默认是否改像素**：同上上下文跑 `process()`，量被改像素占比（合成图）
3. **真实照片消融**：`render_preview_full(p)` 默认 vs 关掉单个 Stage，量三项（`_chain_audit.py`，n=10）
   - `Δpix%` 改动像素占比（max-channel 差 > 1/255）
   - `高频能量比` = 变体 Laplacian 方差 / 默认方差的比值（**纹理量代理**；<1 = 变平滑，>1 = 变锐）
   - `|ΔLab|` 整图 Lab 均值位移（**颜色量代理**）

运行环境：`D:\Python\Python312\tools\python.exe`

## 二、结论表

| # | Stage | 默认开关参数 | 空 ctx `wants` | 默认改像素 | 算子类别 | 决策来源 |
|---:|---|---|:---:|:---:|---|---|
| 1 | exposure | `mode="auto"` | True | 是 | 影调 | **引擎自算 EV** + auto-load 标定表 |
| 2 | whitebalance | `mode="as_shot"`, `warmth=0.9` | True | 是 | 色彩 | **引擎自调暖度** + auto-load `warmth_curve.json` |
| 3 | compose | `rotation=0`, 全幅 | True | 否 | 几何 | 默认惰性 ✓ |
| 4 | huesat | `enabled=False` | False | – | 色彩+空间 | 上层 ✓ |
| 5 | tone | `brightness=0.25`, `profile_curve=False` | True | 是 | 影调 | **引擎自提亮 +0.25EV**（LR 拟合文件缺失，未生效） |
| 6 | dehaze | `enabled=False` | False | 否 | 空间 | 上层 ✓ |
| 7 | **clarity** | **`enabled=True, strength=0.3`** | True | **是** | **空间（局部对比）** | **引擎自发** ⚠️ |
| 8 | colorcal | `neutral_mode="static"`（其余全 None/0） | True | **否（空转）** | 色彩 | 生产默认下 **no-op**；色彩工作只经外部 params 进入 |
| 9 | calibration | `enabled=False` | False | 否 | 色彩 | 上层 ✓ |
| 10 | hsl | `enabled=False` | False | – | 色彩 | 上层 ✓ |
| 11 | split_tone | `enabled=False` | False | – | 色彩 | 上层 ✓ |
| 12 | **skin** | **`enabled=True, strength=0.5`** | True | **是** | **空间 + 语义** | **引擎自发 + 死门控** ⚠️ |
| 13 | region_adjust | `enabled=False` | False | 否 | 空间+掩码 | 上层 ✓ |
| 14 | stylize | `lut=None` | False | 否 | 色彩（LUT） | 上层 ✓ |
| 15 | **refine** | **无 `enabled` 键** | True | **是** | **空间 + 色彩** | **引擎自发，无法整体关** ⚠️ |

**空上下文自发执行 8/15；默认即改像素 4/15（tone / clarity / skin / refine）。**

`tone` 是编码步（linear→gamma），改像素是应然的。**其余三个（clarity / skin / refine）都是空间算子。**

（另：`denoise` / `sharpen` / `vibrance` 三个注册名 `wants()` 恒 `False`，属占位，不在默认链。）

## 三、skin 之外的三个"挂进来的动作"

### 3.1 clarity —— 与 skin 同构，只是一直被视为"基座"

`modules/reshape.py:71-72`：`{"enabled": True, "strength": 0.3}`，`wants` 只读 `enabled`。
模块自述（`:62-63`）：

> 基座默认开启 (enabled=True, strength=0.3): "质感"是基础画质属性而非风格

实测（n=10，preview 口径）：**Δpix median 93.3%** —— 三者中覆盖面最广，几乎全图被改。
**高频能量比 median 1.091**：注意方向 —— **关掉 clarity 反而高频更高**。
原因在 `:88-111`：preview 模式下 clarity 走"降采样 → 计算 → 上采样"路径，
这个往返本身丢纹理。export 全尺寸路径（`:112-114`）无此问题。

⇒ **preview 与 export 的清晰度行为不等价**，且 preview 是用户所见。

### 3.2 refine —— 连开关都没有

`modules/refine.py:181-185` **没有 `enabled` 键**；`process` 只在三个子参数全 ≤0 时才提前返回
（`:193`）。默认全部非零：

| 子步骤 | 默认 | 类别 |
|---|---:|---|
| `sharpen` | 0.35 | 空间（灰空间 unsharp） |
| `chroma_denoise` | 0.8 | 空间（1/4 降采样色度替换） |
| `highlight_desat` | 0.6 | 色彩 |
| `warm_sat_curve` / `warm_hue_curve` | 默认 None ⇒ **生产（空 params）下不生效** | 色彩（wb_B 驱动） |

实测：**Δpix median 66.9%**，高频比 **0.837**（关掉后更软 ⇒ refine 整体是在加锐/加对比）。

⇒ 想关掉它，必须**同时**把 3 个子参数置 0；`{"refine": {"enabled": false}}` **不会生效**（参数不存在）。
这是与 `dehaze` / `region_adjust` / `skin` 都不一致的接口形态。

### 3.3 三者叠加：默认链把纹理削掉一半以上

| 变体 | Δpix% median | 高频比 median | \|ΔLab\| median |
|---|---:|---:|---:|
| clarity 关 | 93.3% | 1.091 | 0.44 |
| skin 关 | 70.0% | **1.859** | 0.12 |
| refine 关 | 66.9% | 0.837 | 0.33 |
| **三者全关** | **99.5%** | **2.380** | 0.58 |

`三者全关` 的高频比 **2.380** ⇒ 默认链输出的高频（纹理）能量只有"全部关掉"时的 **约 42%**。
（三者非可加：算子非线性 + 顺序相关，比值不可相乘。）

**关键旁证**：四个变体的 `|ΔLab|` 全部 **< 0.6**（远低于 JND 2.3）。
⇒ 这三个动作**全部落在色准尺子的盲区** —— 与 skin 的病灶形态完全一致。

## 四、"引擎自动装载标定并施加"的四个（已逐个核实存在性）

除上面三个空间算子，还有一类"自发"是**引擎自己在运行时读标定文件**。
逐个核对文件是否真实存在（这决定它在生产链里到底生效没有）：

| Stage | 自动装载 | 文件 | 生产默认下 |
|---|---|---|---|
| `whitebalance` | `configs/calibration/warmth_curve.json` | **存在（2690B, Sep 8）** | **✓ 生效**（`[[wb_B, r, g, b], ...]` 按 wb_B 分桶查表） |
| `exposure` | `src/pixo/render/target_offset.json` | **存在（1215B）** | **✓ 生效**（每机常量偏移）＋ `mode="auto"` 自算 EV |
| `tone` | `src/pixo/render/lr_tone_curve.json` | **缺失** | **✗ 不生效**（负缓存跳过）；实际只有 `brightness=0.25` + sRGB EOTF |
| `colorcal` | 不读文件 | — | **✗ no-op**（`scene_trim` / `scene_hue` / `neutral_a_curve` 默认全 `None`） |

**这条修正了对 `wb_B` 一维代理的怀疑范围**：生产默认链里真正按 `wb_B` 查表的只剩
**`whitebalance.warmth_curve.json` 一处**；`exposure` 的 `baseline_ev_curve` /
`baseline_scene_ev`（也是 wb_B 驱动）只在 `mode="baseline"` 生效，而生产默认是 `auto`。
⇒ F01 的"色度压缩"病灶若要归因到 wb_B 代理，**可指认的候选只有一个**，可验证性强。

（这与 F01 实测"暖度标定域外告警仅 1/798"一致 —— 单点代理覆盖不足的问题
不一定表现为"域外"，也可能是域内的平滑偏置。）

## 五、一处"温和死门控"

`exposure.subject_mode="box"`（默认）依赖 `ctx.state["face_boxes"]` / `subject_boxes`
（`exposure.py:490`）。但生产入口注入的 state 只有：

- `camera_wb`（`api.py:173` / `export.py:56` / `session.py:521`）✓ 有
- `face_boxes` / `subject_boxes` —— **只能由上层经 `state_extras` 提供**（`session.py:515-516`
  t92 注释自承："归一化框注入 state，exposure 测光 subject_mode=box 在 raw 会话同样生效"），
  `runtime.py:400` 构造 session 时不传 extras

⇒ 生产链里 `"box"` 默认收不到框，静默回退全幅测光。**不致命**（退化为全局测光），
但与 `skin` 的 `scene` 是同一种病：**承诺了语义输入，通道没接**。

## 六、生产配置实证：就是"裸默认"

`runtime.py:400`：
```python
return RawPreviewSession(photo.path, self.profile, session_id=session_id,
                         validate_params=True)          # ← 不传 params
```
`session.py:310` `self.params = dict(params or {})` ⇒ `{}`
`session.py:645-661` `canonical_params()` = `default_params()` + 空覆盖
⇒ **生产链 = 各 Stage 的 `default_params()`**。

`configs/styles/lr_baseline.json` 里那套显式关掉 clarity/skin 的配置（`clarity={"enabled":false}`、
`skin={"enabled":false}`）**不是生产** —— 它只被 `scripts/measure_u8_precision.py` 当对照 C 用过。

⇒ 前面 800 张 F01 基线（`render_preview_full(p, long_edge=...)` 不传 params）**与生产同构** ✓
（但 skin 关掉后 A/B 仅 ±0.05 的结论意味着：这三个空间算子对色准基线无污染，只是损坏纹理。）

## 七、修复形态（建议，未执行）

按"引擎只负责加载与渲染，动作由上层触发"的原则，三类分开处理：

| 类别 | 处置 |
|---|---|
| **接口不一致（必修）** | `refine` 补 `enabled` 键，与 `dehaze` / `region_adjust` / `skin` 统一 |
| **默认值越权（必修）** | `clarity.enabled` 与 `skin.enabled` 改 `False`；"质感/磨皮"改由预设显式开（`scenes.json` portrait 已写对） |
| **死门控（必修）** | `skin` 的"猜掩码面积"门控（`skin.py:98-128`）删除 —— 它正是漂移源（DSC_2566 因上游 saturation +0.15 而翻转） |
| **语义通道（选修）** | `exposure.subject_mode="box"`：要么在上层真正注入框，要么默认改 `"full"` 说实话 |
| **色度压缩（另案）** | 四个 wb_B 一维代理表属 F01 已确诊病灶的修复范围，需先做"相机风格 vs 引擎错误"的分离实验 |

## 八、产物

- `.artifacts/_pipeline_audit.py` —— 15 Stage 准入审计（空上下文 wants + 默认改像素）
- `.artifacts/_chain_audit.py` —— 真实照片消融（Δpix / 高频比 / ΔLab）
- `.artifacts/chain_audit.json` —— 逐张原始数据
