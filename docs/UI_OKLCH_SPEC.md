# Pixo OKLCh 编辑域 UI 规格（UI_OKLCH_SPEC）

> 版本：v1.1（2026-09-04，增补 §4.4 色度滑杆非线性传递，收口评审 backlog ③）；v1.0（2026-08-28，UI 设计师）
> 上游：`docs/OWN_PIPELINE_STAGE1_DESIGN.md` §5（ui-designer 先行任务 t7）；§1.2 双轨开关、§2.2 band schema v2、§2.3 split_tone 迁移
> 事实来源：`src/pixo/render/core/hsl_oklch.py`（DEFAULT_BANDS_OKLCH、C_NEUTRAL、软限幅）、`src/pixo/render/core/hsl.py`（DEFAULT_BANDS、_ring_mask、字段带界）、`src/pixo/render/modules/hsl.py`（color_domain 分派）、`src/pixo/render/core/oklab.py`
> 消费者：**frontend-1 t8**（以此为唯一实现依据）；frontend-2（e2e 冒烟、卡片文案同步）参照
> 本文所有映射数字均为 2026-08-28 用已交付内核实测（复现脚本：`.artifacts/ui_oklch_probe.py`），禁止前端自行"估算"或改成固定偏移

---

## 0. 一页速览（给实现者的 TL;DR）

| # | 结论 | 一句话 |
|---|---|---|
| 1 | 双轨原则 | `color_domain=hsv`（缺省）时**控件集合、文案、量纲与现版逐像素一致**；一切 OKLCh 专属控件仅在 oklch 模式渲染 |
| 2 | 角度不能换算 | HSV 度→OKLCh 度偏移 **非均匀（+15°~+50°）**，不存在固定偏移量；参考读数一律查 §2.2 锚点表做分段线性插值，且**只用于显示，不参与提交数学** |
| 3 | center/width 量纲 | oklch 域标注「中心色相角 / 带宽角（单位 °）」；width 是**半径**语义（掩码在距中心 width° 处归零，全跨度 2×width） |
| 4 | 饱和→色度 | oklch 域滑杆改标「色度 C」，增强方向有**软限幅**（tanh 渐近色域边界），文案必须说明"无硬剪断层" |
| 5 | split_tone 拾色器 | hue 色谱条的渐变色域必须随域切换（hsv 六段谱 ↔ oklch 谱），同参数值两域感知色完全不同（45°：#ffbf00 ↔ #e97c48） |
| 6 | 提交契约 | 前端只 patch `hsl.color_domain` / `split_tone.color_domain`（"hsv"\|"oklch"）+ band 数组；**切域不改任何数值** |

实现优先级：P0 = 域开关 + 全部滑杆标注/文案 + band 展开行（center/width）+ 切域确认；P1 = HueRing 色相环（只读定位 + 点击选带）；P2 = 环上拖拽改 center。

---

## 1. 双轨总则：hsv 域 UI 完全不变

### 1.1 原则

后端 `hsl` Stage 的 `color_domain` 缺省 `"hsv"`（`modules/hsl.py:34`），13 张存量胶片卡逐位不变（设计 §2.2 / 盲点 A1）。前端必须镜像这一纪律：

1. **hsv 模式 = 现版 UI**。控件种类、数量、顺序、文案、量纲、步长、默认值与 2026-08-28 线上版（`AdjustmentsPanel.tsx`）一致；HueRing、双刻度、色度文案、band 展开 row 等 oklch 专属元素**不渲染**（条件渲染，不是隐藏）。
2. **oklch 模式 = 增量 UI**。只新增/改标注，不重排既有控件；8 个带行的顺序与带名不变。
3. **参数数值跨域保留**。切域只提交 `color_domain` 一个键，bands 数组数值原样不动（含 hue_shift/center）。用户显式选择"恢复默认带"时才重写 bands（见 §6.3）。
4. **域是面板级展示概念，存储上是 Stage 级参数**。前端不提供 band 级 domain 混合编辑（后端 `_split_bands_by_domain` 支持逐段覆盖，但 UI 不暴露——成本高、用户价值低）。UI 提交的 band dict 一律**盖戳 `domain: <当前域>`**，使卡片导出后脱离 Stage 默认值仍语义自描述。

### 1.2 域开关（DomainToggle，新组件，两面板共用）

- 形态：Mantine `SegmentedControl`，size="xs"，两项 `HSV` / `OKLCh`，置于 **HSL 面板与分离色调面板头部右侧**（与 `SectionLabel` 同行）。两处渲染同一组件、绑定同一数据源，幂等 patch，不会漂移。
- 数据源：`params.hsl.color_domain ?? 'hsv'`（单一事实来源）。异步往返期间沿用 `SliderParam` 的 pending 显示模式（提交后保留本地值直到回读追上），避免开关回跳。
- patch：切换时同时提交 `{ hsl: { color_domain: d }, split_tone: { color_domain: d } }`（`split_tone` 键在 t4 合入前被后端深合并存储但 Stage 忽略，无害；能力探测见 §7.2）。
- 可访问性：`role="radiogroup"`，`aria-label="色彩编辑域"`；选中项变化后向面板容器发 `aria-live="polite"` 的一句话通告（文案见 §6.3）。

### 1.3 双轨验收清单（t8 自验门）

- [ ] `color_domain=hsv`（或缺省）时，HSL 面板与分离色调面板的 DOM 控件集合/文案与现版一致（建议截图对比基线）。
- [ ] oklch 模式下切回 hsv：新增控件全部消失，数值与切换前一致（往返无损）。
- [ ] `pnpm typecheck` + `test:e2e` 过（设计 §6 前端行）。
- [ ] hsv 域下发出的 patch 不含 `color_domain` 以外的语义漂移（bands 数组仅在被编辑时提交）。

---

## 2. 色相角度：HSV 度 vs OKLCh 度（双刻度映射）

### 2.1 为什么必须双刻度（设计依据，写给实现者）

两域的"度"度量的是不同的锥响应空间，**同一个自然色在两把尺子上的读数不同，且偏移量随色相剧烈变化**（实测：+14.8° ~ +49.8°）。橙-黄区压缩最狠（HSV 60° 的纯黄落在 OKLCh 109.8°），青-蓝区跳跃最大（HSV 210° 的天蓝落在 OKLCh 256.2°）。因此：

- **禁止**在 UI 任何位置呈现"OKLCh 度 = HSV 度 + 26"之类的固定偏移；
- 双刻度的唯一合法实现 = §2.2 锚点表 + 分段线性插值；
- 插值结果**仅用于参考读数**（滑杆 helper 小字、环 tooltip），提交给后端的数值永远是当前域的原始角度，不做任何跨域换算。（v1.1 注：本条约束的是**色相双刻度的跨域参考读数**；色度滑杆自身的「位置⇄参数值」非线性传递见 §4.4——那是同域内的滑杆几何变换，提交值仍为原始 saturation 参数，不与本条冲突。）

### 2.2 双刻度映射表（内核实测，冻结为前端常量）

**表 A · 8 带中心对照（DEFAULT_BANDS vs DEFAULT_BANDS_OKLCH）**——环上带标记、滑杆默认值、文档文案的唯一依据：

| 带 name | UI 显示名 | 旧 HSV 中心° | 新 OKLCh 中心° | Δ | OKLCh 中心参考色板* | OKLCh 中心的"≈旧 HSV"读数** |
|---|---|---|---|---|---|---|
| red | 红 | 0 | **29** | +29 | `#df8073` | ≈0° |
| orange | 橙 | 30 | **55** | +25 | `#d78951` | ≈31° |
| yellow | 黄 | 60 | **100** | +40 | `#b0a03c` | ≈55° |
| green | 绿 | 120 | **145** | +25 | `#6cb26f` | ≈129° |
| aqua | 青 | 180 | **195** | +15 | `#00b5b5` | ≈180° |
| blue | 蓝 | 240 | **264** | +24 | `#789de9` | ≈240° |
| purple | 紫 | 270 | **295** | +25 | `#a48fe1` | ≈271° |
| magenta | 品红 | 300 | **327** | +27 | `#c683c5` | ≈299° |

\* 取样 `oklch(L=0.70, C=0.12, h=中心)` → sRGB，实测值；仅作 UI 色板兜底（无 CSS `oklch()` 支持时），见 §3.2。
\** 反向插值读数（§2.3 表 B 反查），供 helper 小字；注意黄带的旧等效是 ≈55° 而非 60°——两把尺子没有对齐的整数关系。

**表 B · 正向锚点：HSV 纯色（S=V=100%）→ OKLCh 角**——副刻度定位与反向插值的基准（12 锚点，`_hsv_to_rgb(h,1,1)` → `srgb_to_oklab` → `oklab_to_oklch` 实测）：

| HSV° | OKLCh° | | HSV° | OKLCh° |
|---:|---:|---|---:|---:|
| 0 | 29.2 | | 180 | 194.8 |
| 30 | 52.8 | | 210 | 256.2 |
| 60 | 109.8 | | 240 | 264.1 |
| 90 | 135.9 | | 270 | 293.8 |
| 120 | 142.5 | | 300 | 328.4 |
| 150 | 151.1 | | 330 | 2.6（环绕） |

**反向查表（oklch h → ≈旧 HSV 度）**：先把表 B 解环绕为单调序列 `(29.2,0) (52.8,30) (109.8,60) (135.9,90) (142.5,120) (151.1,150) (194.8,180) (256.2,210) (264.1,240) (293.8,270) (328.4,300) (362.6,330)`（末锚点 = 2.6+360，区间 [29.2, 362.6]）。取候选 `{h, h+360}` 中落在区间内的那个；两者都在区间外时取距端点更近者并**钳制到该端点**（例：h=29 距首锚点 0.2°，直接读首锚点 → ≈0°）。然后分段线性插值，四舍五入取整，显示时加「≈」前缀。

**精度声明**：锚点是 S=V=100% 纯色样本处的对应；同 HSV 色相在降饱和样本上 OKLCh 角还会漂移最多 ~16°（HSV 240° 在 S=50% 时漂 +16.0°）。因此读数一律带「≈」，且任何位置不得把参考读数回写进参数。

### 2.3 刻度绘制规则

- 主刻度（两域通用）：OKLCh 模式下主刻度即参数域角度，every 30° 标数字（0…330），起点 0° 固定在 **12 点钟方向、顺时针递增**（与 CSS `conic-gradient` 零角一致，实现零换算）。
- 副刻度（仅 oklch 模式）：内圈细刻度按表 B 的 12 个 OKLCh 位置放置；**相邻数字 <14° 时只画 tick 不标数字**（实测绿区 136/143/151 三刻度间距 7~8°，必然触发），完整数值入 hover tooltip。副刻度统一用 `textSecondary` 色 + 图例小字「内圈：旧 HSV 参考」。
- hsv 模式：只有主刻度（= HSV 度），**无双刻度**（双轨原则）。

---

## 3. HSL 面板（oklch 模式）

### 3.1 面板整体线框（oklch 模式）

```
┌ HSL ──────────────────────────────── [HSV|OKLCh] ┐   ← DomainToggle
│ HSL · 八通道色相（OKLCh 感知域）                    │   ← SectionLabel 随域变化
│ ┌────────────────────────────────────┐            │
│ │        HueRing（P1，176px 环）      │  内圈:旧HSV │   ← §3.2
│ │   选中带读数: 黄 · h=100° (≈旧55°)  │            │
│ └────────────────────────────────────┘            │
│ 红 色相平移        ─────●─────── +0      [°] ▸    │   ← 8 行带 row（折叠态同现版密度）
│ 橙 色相平移        ─────●─────── +0      [°] ▸    │
│ …（黄/绿/青/蓝/紫）                                 │
│ 品红 色相平移      ─────●─────── +0      [°] ▸    │
└───────────────────────────────────────────────────┘

点 ▸ 展开单个带 row（HslBandRow 展开态）：
│ 黄 · 中心色相角   0 ────●────────── 360   100°  │  ← center，默认 100
│      ≈旧 HSV 55°（参考）                         │  ← helper 小字（表 B 反查）
│ 黄 · 带宽角       5 ─────●───────── 180    45°  │  ← width（半径语义）
│      影响跨度 ±45°（余弦缓入出）                  │
│ 黄 · 色相平移   -30 ────●────────── 30     +0°  │  ← hue_shift（区间与 hsv 模式一致）
│ 黄 · 色度 C    -100 ────●───────── 100     +0%  │  ← saturation →「色度 C」，§4
│ 黄 · 明度 L    -100 ────●───────── 100     +0%  │  ← luminance
```

- 8 个带 row 的折叠态 = 现版「{色名} 色相」hue_shift 滑杆行，**不改**；展开箭头（`▸/▾`，24px 命中区）是 oklch 模式新增的唯一行内元素。hsv 模式无展开能力（双轨原则）。
- 展开态一次只展开一个带（手风琴），避免 8×5 滑杆把面板撑爆。
- 带名后跟随 6px 色点（表 A 参考色板 hex），颜色标识 + 文字双通道（色盲安全）。

### 3.2 HueRing 色相环（P1，新组件 `HueRing.tsx`）

- **谱环渲染**：首选 CSS `conic-gradient`，停靠点每 10° 一个，颜色 `oklch(0.70 0.12 ${h})`（浏览器原生计算，零 JS）；`@supports (color: oklch(50% 0.1 100))` 不满足时回退为同布局的 36 停靠 `rgb()` 渐变，停靠 hex 用内核同法预生成（表 A 色板即 8 个采样示例）。**两域谱环不同**：hsv 模式（若 P1 提前实现于 hsv，规格允许但非必需）用 `hsl(${h} 100% 50%)`。
- **带标记**：8 个手柄位于各自 `hue_center` 角度、环带中线半径上；手柄 = 12px 圆点 + 外扩至 24px 命中区，选中态 2px `focusRing` 描边。手柄 tooltip：`{色名} · OKLCh {center}°（≈旧 HSV {x}°）`。
- **中心读数区**：环心显示当前选中带 `{色名} h={center}°`，下行小字 `≈旧 HSV {x}°（参考）`。
- **交互分级**：P1 只读 + 点击手柄/环带选中带（联动展开对应 band row，滚动定位）；P2 手柄拖拽改 center（拖拽中显示角度 tooltip，步进 1°，`%360` 环绕，提交走 onChangeEnd 防抖，对齐 SliderParam 既有节律）。
- **键盘/无障碍**：每个手柄 `role="slider"`，`aria-valuemin=0 aria-valuemax=360 aria-valuenow={center}`，`aria-valuetext="{色名}中心 OKLCh {n}°（≈旧 HSV {x}°）"`；←/→ ±1°，Shift+←/→ ±10°，Home/End 到带默认 center。环容器 `role="img"` 的 `aria-label`：「OKLCh 色相环，内圈为旧 HSV 参考刻度」。
- **尺寸**：外径 176px、环带宽 28px；面板宽 320~380px 下水平居中，可整环折叠（折叠钮存 localStorage）。

### 3.3 band 滑杆量纲与文案总表（oklch 模式，全部复用 `SliderParam`）

| 参数 | label | min–max | step | unit | 默认（黄带为例） | helper 文案（滑杆下一行 xs 灰字） |
|---|---|---|---|---|---|---|
| hue_center | 中心色相角 | 0–360 | 1 | ° | `DEFAULT_BANDS_OKLCH` 各带中心 | `≈旧 HSV {x}°（参考）` |
| width | 带宽角 | 5–180 | 1 | ° | 45 | `影响跨度 ±{w}°（余弦缓入出）` |
| hue_shift | 色相平移 | -30–30* | 1 | ° | 0 | `绕 OKLCh 色相环平移，0/360 环绕连续` |
| saturation | 色度 C | -100–100 | 1 | % | 0 | 见 §4 文案 |
| luminance | 明度 L | -100–100 | 1 | % | 0 | `感知亮度轴；50% 灰实测 L≈0.60，与旧 HSV 明度(V)不同` |

\* hue_shift UI 区间维持现版 ±30（用户肌肉记忆/防误触大偏移）；后端硬界 ±180（`core/hsl.py` `_HS_MIN/_HS_MAX`）写入组件注释即可，不放开 UI。
center/width 的边界契约来自 `_validate_band`（width∈[5,180]），NumberInput 越界由 SliderParam 既有 clamp 行为兜住，不新增报错态。

---

## 4. 饱和滑杆 →「色度 C」语义（文案与刻度）

### 4.1 为什么改叫「色度」

oklch 域的 `saturation` 参数作用于 OKLCh 的 C 轴（chroma，染色强度/离灰程度），不再是 HSV 的 S（相对饱和比例）。对用户的可感差异：C 是**绝对量**（灰=0，常见照片内容 C≈0.06–0.18，sRGB 色域上界包络峰 ≈0.33，实测），且增强方向带**软限幅**。

### 4.2 滑杆规格（oklch 模式）

- label：`色度 C`；unit：`%`；区间 -100–100 step 1（增量语义不变，参数键名不变——后端契约）。
- 刻度建议：`marks` 停在 **-100 / -50 / 0 / +50 / +100** 五档，0 档 label「原色」加粗；拖动 label 沿用 `v.toFixed(2)` 无需改。
- helper 文案（固定显示）：`C=染色强度。增强趋近色域边界时平滑收敛（软限幅），无 HSV 模式的断层/平台`。
- info 图标 tooltip（label 右侧 14px ⓘ，hover/focus 显示）：
  `照片常见色 C≈0.06–0.18；C<0.02 视为中性灰，自动保护不动。软限幅仅在增强方向生效，调低色度精确线性。`
  （0.02 = 内核 `C_NEUTRAL` 中性保护阈值，0.06–0.18 与 0.33 为实测锚点，见文件头探针脚本 F 节。）
- **禁止**运行时按像素预判"是否触顶"并变色——前端无逐像素色域信息，静态文案 + ⓘ 即可，不做假警示。

### 4.3 明度滑杆连带规格

`luminance` 同理改标「明度 L」，helper 见 §3.3 表。hsv 模式下两滑杆维持旧 label「饱和度/明度」不出现（该滑杆在 hsv 模式本就不渲染，双轨原则自动满足）。

### 4.4 色度滑杆非线性传递（v1.1 增补，评审 backlog ③ 收口）

> **决策修订声明**：本节修订 v1.0 §2.1「提交数值不做任何换算」的适用范围——该决策约束的是**色相双刻度的跨域参考读数**（HSV 度↔OKLCh 度插值永不回写参数），维持不变；§4.4 引入的是**色度滑杆同域内的「滑杆位置⇄参数值」几何变换**，提交给后端的仍是原始 saturation 参数值（键名/区间 [-100,100]/step 1 均不变），不存在跨域数值换算。此修订即 `docs/OWN_PIPELINE_REVIEW_DISPOSITION.md` ③ 与 `docs/tech_debt.md` §13-1 登记的采纳前置条件。

**背景**：滑杆→参数值线性直传时，常用调整区（照片内容 C≈0.06–0.18）与极端区（趋近色域峰 0.33，内核 tanh 软限幅收敛）在行程上不分分辨率——评审要求「滑杆中段应对应常用调整范围，两端保留极端能力」。

**传递函数**（冻结于 `frontend/src/theme/oklchScale.ts`，锚点全部来自 §4 内核实测）：

| 量 | 定义 | 锚点 |
|---|---|---|
| `C_SLIDER_MAX` | 色域包络峰 | `0.33` |
| `C_SLIDER_GAMMA` | 传递指数 | `1.6` |
| `sliderToC(t)` | `C = 0.33 · t^1.6`，t∈[0,1] 滑杆位置 → C∈[0,0.33] | t=0→0；**t=0.5→C≈0.1089**（落常用区 [0.06,0.18] 近中心，锚点 0.12）；t=1→0.33 |
| `cToSlider(c)` | 逆映射 `t = (C/0.33)^(1/1.6)`，与上**精确互逆** | C=0.06→t≈0.345；C=0.12→t≈0.531；C=0.18→t≈0.685 |

效果量化：常用区 [0.06,0.18] 骑跨行程中段（34.5%–68.5%）；低色度细调区（0→0.06）行程占比 34.5%（线性时 18.2%，近 2 倍分辨率）；极端区 [0.18,0.33] 压缩到末端 31.5%——「中段常用、两端极端」。

**滑杆接线**（增强半程的位置变换，参数值域仍 [-100,100]）：

- `chromaValueToSliderPos(v)`：v>0 → `100·(v/100)^(1/1.6)`（低值分辨率展开：+1..+10 占增强半程前 24%，行程 3/4 处 ≈ +33 常用增强，右端 +100 极限保留）；**v≤0 → 恒等**（§4.2「调低色度精确线性」不变），0 处两侧连续。
- `chromaSliderPosToValue(s)`：上式逆映射（正向幂压缩极端区，负向恒等）。
- 仅作用于 **HslBandRow 展开态色度滑杆**（oklch 模式）；hsv 域该滑杆本就不渲染。分离色调面板「色度 C」（§5）暂不接入，留后续批次评估。
- 实现机制：`SliderParam` 增可选 `toSlider/fromSlider` 变换对——Mantine Slider 恒在线性「位置域」运行，组件在边界换算；拖动 label/数字输入框/提交值均为参数域原值。**变换缺省 = 现版线性路径逐位不变**（双轨零变化的实现保证）。
- marks 仍是 §4.2 五档（-100/-50/0/+50/+100，0 档「原色」），由组件按变换自动重排到位置域。

**验收数字**（单测 `frontend/tests/oklchScale.test.mjs`）：`sliderToC(0.5)≈0.1089∈[0.06,0.18]`；`sliderToC/cToSlider` 互逆误差 <1e-9；位置变换在 v=33 处 s=50、v=±端点精确落位、负向恒等；hsv 域 DOM 与基线逐像素一致（`e2e/chroma_warp_check.mjs` canvas diff）。

---

## 5. 分离色调面板（split_tone）与 hue 拾色器

### 5.1 面板线框（oklch 模式）

```
┌ 分离色调 ────────────────────────── [HSV|OKLCh] ┐
│ 分离色调 · 高光 / 阴影（OKLCh 感知域）             │
│ 高光  [■色板] 色相 0 ────●────────── 360  210°  │  ← HueSpectrumBar + SliderParam
│       spectrum 轨道下方双刻度小尺（仅 oklch）      │
│       ≈旧 HSV 187°（参考）                       │
│ 高光 饱和度      0 ────●────────── 100     0%   │  ← oklch 域改标「色度 C」同 §4
│ 阴影  [■色板] 色相 0 ────●────────── 360   45°  │
│       ≈旧 HSV 20°（参考）                        │
│ 阴影 色度 C     0 ────●────────── 100      0%   │
│ 平衡            0 ────●──────────── 1    0.50   │  ← 不随域变
│ 强度            0 ────●──────────── 1    1.00   │  ← 不随域变
└─────────────────────────────────────────────────┘
```

### 5.2 HueSpectrumBar（新组件：色谱轨道拾色器）

- 形态：在「高光/阴影 色相」两条 SliderParam 的**轨道背景**上渲染水平色谱（`linear-gradient(to right, 停靠点每 15°)`，圆角同轨道），slider thumb 即拾色游标；行首加 20×20px 当前染色色板（圆角 4px，hairline 描边）。
- **谱随域切换（核心标注点）**：
  - hsv 模式：`hsl(h 100% 50%)` 六段谱（现版无谱、纯灰轨，属新增可见元素——允许，因为分离色调面板在两域都不属于"现版 HSL 逐像素基线"，但控件集合不变：只是轨道上色）。
  - oklch 模式：停靠色 `oklch(0.70 0.15 h)`（无 CSS oklch 支持时回退 24 停靠 rgb 预生成 hex，同 §3.2 兜底法）。
  - **依据（实测，写给评审）**：同参数 45° 在 hsv 域是 `#ffbf00`（金黄）、在 oklch 域是 `#e97c48`（橙红）；210° 在 hsv 域是 `#0080ff`（天蓝）、oklch 域是 `#00b6d1`（青）。谱不变则拾色器在 oklch 域是骗人的。
- 双刻度小尺（仅 oklch 模式，轨道下方 12px 高）：主刻度 0/90/180/270/360 标数字；副刻度在表 B 的 256.2°（旧 210° 天蓝）等锚点处画细 tick + 图例「旧 HSV 参考」；拥挤规则同 §2.3。
- 色板 tooltip：`高光染色 · OKLCh h=210° C≈0.15（≈旧 HSV 187°）`。
- 色板取色实现：CSS `oklch(0.70 0.15 var(--hue))` 直接算；兜底预生成 0–360 步长 5° 的 hex 表（72 项，内核同法）。
- 键盘/无障碍：slider 本身沿用 Mantine 键盘能力；色板 `aria-hidden`（装饰性，值已在 slider aria-valuetext 中：`高光色相 OKLCh {n}°（≈旧 HSV {x}°）`）。

### 5.3 后端契约与门控

- `split_tone` 的 oklch 语义由设计 §2.3（t4，`core/split_tone_oklab.py`）交付，参数名不变、仅 `color_domain` 分派。**t8 实装时 t4 应已合入**（依赖图 t3,t4→t8）。
- 门控兜底（t4 万一未合入）：首次切域后回读 `canonical.split_tone`，若不含 `color_domain` 键 → 分离色调面板显示灰色 Badge「分离色调 OKLCh 域待后端支持，暂按 HSV 语义」，该面板域标注退回 hsv 形态；HSL 面板不受影响。能力探测沿用 t91 health-badge 既有模式，结果入 store 一次性缓存。

---

## 6. 关键交互流程与状态

### 6.1 状态矩阵（每个新控件必须覆盖）

| 状态 | DomainToggle | HueRing | band 展开行 | HueSpectrumBar |
|---|---|---|---|---|
| 默认 | 按 `params.hsl.color_domain` 渲染 | 折叠（localStorage 记忆） | 全部折叠 | 不显示谱（hsv）或按域显示 |
| 加载中（params 未回读） | 按 hsv 渲染（双轨缺省），回读后若为 oklch 静默切换 | 同上 | 同上 | 同上 |
| 拖拽/输入中 | 本地 pending，防回跳 | 手柄高亮 + 角度 tooltip | SliderParam 既有 pending | 同左 |
| 后端不可用 | disabled + tooltip「后端不可用」 | 照常渲染（纯本地） | 照常 | 照常 |
| patch 失败 | 沿用全局 toast，回读值兜底 | 同左 | 同左 | 同左 |
| 回读形状非法 | 回退 hsv（`?? 'hsv'`） | 回退 DEFAULT_BANDS_OKLCH 镜像 | `readHslBands` 同款校验 + oklch 分支回退 | 回退 hsv 形态 |

### 6.2 用户动线（oklch 首次使用）

1. 打开 HSL 面板 → 见 [HSV|OKLCh] 开关，当前 HSV（缺省，与现版无异）。
2. 切到 OKLCh → 确认弹窗（§6.3）→ 面板出现色相环/双刻度/「色度 C」标注；预览按 generation 自动刷新。
3. 点环上「蓝」手柄 → 蓝带 row 展开定位 → 拖「色度 C」至 +40 → helper/ⓘ 解释软限幅 → onChangeEnd 提交 `{hsl:{bands:[…8 项,蓝带 saturation=40,domain:'oklch']}}`。
4. 任意时刻切回 HSV → 控件回到现版形态，数值保留（往返无损）。

### 6.3 切域确认弹窗（唯一新增 Modal）

- **触发**：两域间任意方向切换，且当前 bands **非全默认**（任一 band 任一参数 ≠0，或 center ≠ 所在域默认中心）。
- 内容：标题「切换色彩编辑域？」；正文一行说明 + 差异示例；两按钮：
  - 「保留数值切换」（主按钮，accent）：只 patch `color_domain`，bands 原样。附注风险小字：`胶片卡自带的 HSV 色段数值将按 OKLCh 角度解释`。
  - 「恢复该域默认带后切换」（次按钮）：patch `color_domain` + `bands=null`（后端按域回 DEFAULT_BANDS / DEFAULT_BANDS_OKLCH，见 `modules/hsl.py:43`）。
- bands 全默认时免弹窗直接切。
- 切换完成后 `aria-live` 通告：`已切换到 OKLCh 感知域：色相角度与 HSV 不同，各滑杆旁为参考读数`（反向同理）。
- 理由：切域是**语义切换而非数值换算**（§1.1 第 3 条），弹窗把不可逆的认知代价显式化，同时给出零损伤出路（恢复默认带）。

### 6.4 边界情况

- **h 环绕**：center 拖过 0/360、hue_shift 叠加越界，UI 一律 `%360` 显示（0–360 半开区间，与内核一致）；hue_shift 区间钳制在 ±30 UI 界内。
- **带重叠**：相邻带中心距（如红 29°/橙 55° 差 26°）小于带宽 45° 是**设计内**现象（余弦掩码顺序叠加），不警示、不吸附；HueRing 上两带手柄相邻过近（<6°）时 tooltip 自动上下错位。
- **存量卡片**：卡片 bands 无 domain 键 + 用户主动切 oklch → 后端按 Stage 级归属把无键 band 走 oklch（A1 设计行为），弹窗文案已点名；卡片载入时若 `color_domain=hsv` 则一切如旧。
- **Agent/预设 patch 竞态**：`source≠user` 的 patch 带橙徽标（现版机制），域切换不锁面板；store 回读覆盖本地 pending（现版链路）。

---

## 7. 前端实现契约（types / store / 复用清单）

### 7.1 `types.ts` 增量

```ts
export interface HslBand {
  name: string;
  hue_center: number;
  width: number;
  hue_shift: number;
  saturation: number;
  luminance: number;
  /** band schema v2（设计 §2.2）：UI 提交时盖戳当前域；缺省后端按 Stage color_domain 归属。 */
  domain?: 'hsv' | 'oklch';
}
// ParamPatch 增：
hsl?: { enabled?: boolean; bands?: HslBand[]; smooth?: number; color_domain?: 'hsv' | 'oklch' };
split_tone?: { …; color_domain?: 'hsv' | 'oklch' };
```

### 7.2 store / 组件清单

| 项 | 类型 | 复用/新建 | 说明 |
|---|---|---|---|
| 域选择器 | `params.hsl.color_domain ?? 'hsv'` | 复用 store，无需新字段 | 单一事实来源；跨项目各自记忆（随 params） |
| DomainToggle | 组件 | **新建**（SegmentedControl 封装 + pending + Modal） | 两面板共用 |
| HslBandRow | 组件 | **新建**（折叠态=现版 SliderParam 行 + ▸） | 展开态 5 滑杆全复用 SliderParam |
| HueRing | 组件 | 新建（P1） | conic-gradient + 8 手柄 |
| HueSpectrumBar | 组件 | 新建 | 轨道谱 + 色板 + 双刻度小尺 |
| 双刻度插值 | 工具函数 `hsvRefFromOklch(h)` / `oklchFromHsvRef(h)` | 新建 `theme/oklchScale.ts` | §2.2 表 B 冻结常量 + 分段线性；**只用于显示** |
| 8 带常量镜像 | `DEFAULT_HSL_BANDS_OKLCH` | 新建（对齐现 `DEFAULT_HSL_BANDS` 模式） | `domain:'oklch'` 戳 + 表 A 中心值 |
| e2e 钩子 | `data-testid` | — | `domain-toggle`、`hue-ring`、`band-row-{name}`、`band-{name}-center/width/chroma`、`split-hue-{shadows\|highlights}` |

成本注记：P0 全部落在现有 SliderParam/Accordion 体系内（约 +1 工具文件 +2 小组件 +1 Modal）；HueRing/谱环无第三方依赖，CSS 渐变优先、hex 表兜底。

---

## 8. 文案总表（唯一出处，实现照抄）

| 位置 | 文案 |
|---|---|
| 域开关两项 | `HSV` / `OKLCh` |
| HSL SectionLabel（oklch） | `HSL · 八通道色相（OKLCh 感知域）` |
| 分离色调 SectionLabel（oklch） | `分离色调 · 高光 / 阴影（OKLCh 感知域）` |
| band 滑杆 label | `中心色相角` / `带宽角` / `色相平移` / `色度 C` / `明度 L` |
| center helper | `≈旧 HSV {x}°（参考）` |
| width helper | `影响跨度 ±{w}°（余弦缓入出）` |
| 色度 helper | `C=染色强度。增强方向幂传递：行程中段≈+33 落常用区，细调区加宽；调低精确线性，趋近边界软限幅平滑收敛` |
| 色度 ⓘ | `照片常见色 C≈0.06–0.18；C<0.02 视为中性灰，自动保护不动。增强方向按 C 域幂曲线（γ=1.6）传递：行程中段≈+33（常用增强），右端保留 +100 极端；软限幅仅在增强方向生效，调低色度精确线性` |
| 内圈图例 | `内圈：旧 HSV 参考` |
| 切域弹窗标题/正文 | `切换色彩编辑域？` / `OKLCh 按感知均匀划分色相，角度与 HSV 不同。例：旧"黄 60°"在 OKLCh 约 110°。` |
| 弹窗按钮 | `保留数值切换` / `恢复该域默认带后切换` |
| 切域 aria 通告 | `已切换到 OKLCh 感知域：色相角度与 HSV 不同，各滑杆旁为参考读数`（反向：`…HSV 域：界面恢复旧版量纲`） |
| t4 缺位 Badge | `分离色调 OKLCh 域待后端支持，暂按 HSV 语义` |

---

## 附：规格数据复现

```bash
python .artifacts/ui_oklch_probe.py   # 表 A/B/D/E/F 全部数字，内核: src/pixo/render/core/oklab.py
```
