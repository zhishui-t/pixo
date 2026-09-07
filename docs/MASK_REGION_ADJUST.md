# 区域调整使用指南（region_adjust · 掩码驱动渲染 M1）

> 读者：会启动 pixo 服务与前端工作台、想使用或调参「区域调整」能力的使用者/贡献者。
> 事实来源：`src/pixo/render/modules/region_adjust.py`、`src/pixo/render/pipeline/region_masks.py`、
> `src/pixo/service/runtime.py`、`configs/rules/region_rules.yaml`、
> `.artifacts/region_trial_54.md`、`.artifacts/region_rules_activation_eval.md`、
> `.agent-team/streams/r13~r16-*` 各批次报告、`docs/tech_debt.md` 条目 17。
> 日期：2026-09-08（R17）。

---

## 1. 是什么

区域调整 = **按照片内容分区施加不同的曝光/饱和度/暖色调参数**，而不是全图一刀切。
链路三步：

1. **掩码（mask）**：分割模型按区域语义名（`face` / `sky` / `plant`，下称 prompt）产出
   每像素 0..1 的软权重图，标记"天空在哪里、植被在哪里"；
2. **区域意图**：两条驱动路径把意图写进 `region.<prompt>.<参数>` 键——规则引擎自动
   补偿（§3.2），或你在 UI 上拖滑杆（§2）；
3. **渲染**：`region_adjust` stage（管线顺序 57，磨皮之后、风格化 LUT 之前）按掩码把
   参数只作用在对应区域上。

效果量级（54 张真实语料试水，`.artifacts/region_trial_54.md`）：闭环 QC 达标率
48% → 57%（**净 +9pp**），7 张二次超标样本经天空压暗救回；全部触发落点在 ±0.5 EV
以内（EV = 曝光补偿档位，+1 EV ≈ 亮度翻倍）。注意该数据出自试水系数（sky −0.25）；
现行 sky 系数已复权至全量 −0.5（§3.2），复权后的独立增量未单独实测。

## 2. 快速上手

**环境前提**（三者缺一，区域面板即不可用）：

| 前提 | 说明 |
|---|---|
| `PIXO_SEGMENTER=multi` | 真分割栈（缺省 `mock`）。mock 环境下区域功能**按契约不可用**（零掩码 + 面板禁用），不报错——mock 分割器永不尝试供给掩码 |
| segformer 权重可用 | sky/plant 掩码由 segformer 产出，首次使用会从 HF 下载/读本机缓存。**sky/plant 不需要** NC 放行 |
| `PIXO_ALLOW_RESTRICTED=1`（仅 face 需要） | face 掩码依赖 uniface（NC=非商业许可权重），默认不进路由；只调天空/植被可完全不设此项 |

**推荐服务配置**：

```bash
export PIXO_SEGMENTER=multi
export PIXO_REGION_SUPPLY=1        # 预览会话掩码供给（缺省关，见 §4）
# PIXO_SEGMENTER_WARMUP 缺省已开：服务启动后台线程预载权重+首推理，
# 吸收约 17.7s 的首次分割冷启动（不阻塞主服务）。
```

**UI 路径**：打开照片预览 → 右侧 AdjustmentsPanel 的 **RegionSection** 节 →
选区域（face/sky/plant）→ 拖三根滑杆：exposure（±2 EV）/ saturation（±1）/
warmth（±1，负=冷 / 正=暖）。要点：

- 区域不可用时滑杆**整体不渲染**（禁用态无静默操作面，B1 修复后语义），
  状态徽标与提示给出原因、必要时提供重试入口——最常见是
  `masks_not_injected`（该会话还没有掩码，见 §5.2）；
- 滑杆经过感知均匀传递（γ=1.6 幂映射，与 oklch 色度滑杆同惯例）：中段行程对应
  常用小量，不必担心"轻轻一拖就过头"；
- 提交只包含你实际改动的 prompt/参数键；每次提交的响应里都带最新 region 状态。

**首请求耗时预期**：权重冷启动下第一次分割约 **17.7s**（`PIXO_SEGMENTER_WARMUP`
开启时这笔成本已移到服务启动阶段）；进程热态每次约 **0.73s**
（`src/pixo/service/runtime.py` 实测注记）。

## 3. 工作机制（简明）

### 3.1 掩码从哪来、到哪去

- **生产两源**：① 单张闭环（SinglePhotoLoop）在测量阶段按 prompts 分割；② 服务端
  供给——`PIXO_REGION_SUPPLY=1` 时，前端打开区域面板（`GET /api/sessions/{id}/region`）
  触发懒加载分割（face/sky/plant）。
- **一条通道**：两种来源的掩码都经 F13 适配通道（`render/pipeline/region_masks.py`）
  注入 `ctx.state["region_masks"]`（float 0..1 软掩码），**三条渲染入口共用**——
  web 预览线、web 导出全质量线、loop 合成后端。掩码分辨率与图不同会自动缩放，
  坐标系是构图后的最终帧。

### 3.2 决策双驱动

**规则自动**（`configs/rules/region_rules.yaml`，已在默认规则包内激活）：
目前两条，均为"按当前区域亮度比例补偿、方向钳制"的分区曝光：

| 规则 | 触发条件（全部满足） | 动作 |
|---|---|---|
| `region_sky_exposure_001` | 天空亮度 >150 且覆盖 <70% 且区域可靠 | `region.sky.exposure = −0.5 × (亮度/150)`，钳制 [−2, 0]（只压暗） |
| `region_plant_exposure_002` | 植被亮度 <70 且覆盖 <70% 且全图高光溢出 <1% 且区域可靠 | `region.plant.exposure = 0.2 × ((70−亮度)/70)`，钳制 [0, 2]（只提亮） |

三道护栏（都来自实测误伤案例，非拍脑袋）：

- **覆盖率护栏 0.70**：分割把 ≥70% 画面判成同一区域 = "整图误罩"，规则不触发
  （实证：high_contrast 样本 99.6% 被判 sky，裸规则会把全图压暗 0.52 EV）；
- **可靠性闸（S-5）**：小面积/低置信区域的区域亮度不可信，`*_reliable == true`
  才允许触发；
- **plant 溢出负联动（R16）**：全图高光溢出已 ≥1% 时不再提亮植被（提亮会推高溢出；
  阈值取自 54 张语料回退样本的溢出地板 1.35~1.64% 与中性样本 ≤0.42% 的间隙）。

系数沿革：R13 条件入包（试水系数减半）→ R15 分层复权：**sky 全量 −0.5**（17 次触发
零回退、7 张救回主驱），**plant 维持 0.2 续观察**（2 张 pass→二次超标回退与其共现）。

**UI 手动**：滑杆 patch 与规则写同一参数键（`region.<prompt>.<param>`），后端映射进
`region_adjust.regions[prompt][param]` 并自动把该 stage 的 `enabled` 置真——手动与
自动用同一个执行位，不双轨。

### 3.3 参数三维的语义（意图级近似）

| 参数 | 域 | 内核 |
|---|---|---|
| exposure | ±2 EV | gamma 域增益近似 `2^(ev/2.2)`：中间调线性误差 <4%，深阴影偏差增大、高光 clip 兜底 |
| saturation | ±1 | HSV 饱和度缩放，中性像素不受影响 |
| warmth | ±1（负=冷 正=暖） | RGB 通道增益（G 上 B 下为暖），白平衡标定链的意图级近似 |

均为"意图级软区域"口径：效果是**大面积分区曝光/色调重塑**（与掩码覆盖面积成正比），
不是局部斑点修补。

## 4. 配置参考

### 4.1 环境变量

| 变量 | 缺省 | 语义 |
|---|---|---|
| `PIXO_SEGMENTER` | `mock` | 分割栈选择；`multi` = 真分割路由（rfdetr+segformer 等）。区域调整需要 `multi` |
| `PIXO_ALLOW_RESTRICTED` | 未设 | NC 权重后端（uniface/sapiens）进路由需 `=1`；**sky/plant 不需要**，只要 face 掩码才需要 |
| `PIXO_REGION_SUPPLY` | 关（`1/true/on` 开） | 预览会话掩码供给：打开区域面板时懒加载分割。冷启首请求 ~17.7s、热态 ~0.73s，故缺省关；常驻服务+热权重建议开 |
| `PIXO_SEGMENTER_WARMUP` | 开（`0/false/off/no` 关） | 服务启动后台预载分割权重+小图首推理（daemon 线程，不阻塞主服务启动），把 17.7s 冷启移出用户首请求 |

### 4.2 规则调参入口

- 文件：`configs/rules/region_rules.yaml`（源）——条件阈值、公式系数、clamp 方向
  钳制都在这里。
- **同步警示**：该文件在 `src/pixo/decide/rules/region_rules.yaml` 有一份包内镜像，
  测试 `test_region_rules_yaml_loads_and_package_mirror_consistent`
  （tests/unit/test_decide_region_wiring.py）以**逐字节一致**断言锁定两份。改系数/阈值
  必须**两份同步改**，只改一边测试即红（这是有意设计的防漂移闸，不是障碍）。
- 调参历史与依据全部写在 yaml 头部注释（R13 激活评估 → R15 分层复权 → R16 溢出
  负联动的完整沿革与数据出处），动手前先读头注；评估可复跑：
  `python .artifacts/_r13_region_rules_eval.py`（6 样本双轨）、
  `python .artifacts/_r15_region_trial54.py`（54 张试水）。

## 5. 已知限制

1. **compose free 模式像素矩形 × 掩码错位**（tech_debt #17，记债中）：free 裁剪用
   全画布像素矩形，同一参数在不同渲染分辨率下相对取景不同；掩码适配只做尺寸对齐
   不做坐标重映射，free 路径下 preview/export 的区域落点可错位 10%+ 画幅宽。
   现行防线：构图参数一变即清空掩码缓存、区域效果静默直通（"不作为"优于"错作为"）。
   ratio/full-frame 构图路径不受影响。
2. **纯预览（没跑 loop、没开供给）无掩码**：此时区域状态返回
   `available=false, reason="masks_not_injected"`，面板滑杆禁用——语义是"暂无掩码、
   不可调"，不是错误。要让纯预览可调，开 `PIXO_REGION_SUPPLY=1`。
3. **plant 提亮的溢出双层防线**：全图高光溢出 ≥1% 时 plant 规则事前不触发；即便
   触发，引擎侧 S-4 限流（≥2.5%，事后压制）也可能吞掉一轮提亮（下一轮溢出回落后
   正常落地，方向保守）。sky 压暗方向与溢出无关，不受两条限制。
4. **语义灰区**：人像虚化背景可能被分割归入 sky（实测 tele 人像 40.6% 覆盖）——
   规则会压暗它；艺术上或可接受，但这属规则替你做的创作决定，敏感场景请用
   手动滑杆覆盖或在规则层调参。
