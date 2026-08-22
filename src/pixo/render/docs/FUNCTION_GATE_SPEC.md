# pixo.render 功能门禁规范（FUNCTION_GATE_SPEC）

> 版本：v1.0  
> 状态：待审核  
> 作者：架构师（长安小队）  
> 目标文件：`render/docs/FUNCTION_GATE_SPEC.md`  
> 关联文档：`render/docs/PIXO_RENDER_NATIVE_SPECIFICATION.md`、
> `render/docs/PIXO_RENDER_1S_PREVIEW_DESIGN.md` v1.6

---

## 1. 目标与原则

功能门禁（gate）回答一个问题：**某个调整功能（曝光/白平衡/曲线/HSL/
分离色调/色彩校准/肤色/精修）改动后，是否仍然“正确”且可以被合并。**

原则：
1. **失败即阻塞合并**：任何 gate 用例失败，该 MR/提交不得合入；
   例外（环境缺数据、GPU/驱动缺失等）必须走 §10 的显式豁免，不允许静默 skip。
2. **严格但可达成**：阈值锚定现有实现与既有测试；不引入“永远过不了”的门禁，
   也不允许用宽阈值掩盖算法回归。
3. **分层隔离根因**：单元性质（纯数学）→ native 等价（同图两实现）→
   golden 回归（跨版本）→ 端到端 A-B（产品观感）。上层失败时能定位到
   最小 feature 与最小层。
4. **零 rawlab 依赖**：gate 测试只 import `render`；真实 NEF 只经
   `render/tools` 与 `render/calibration_data`。

---

## 2. 分层模型

| 层 | 名称 | 回答的问题 | 数据 | 是否阻塞 |
|---|---|---|---|---|
| L0 | 单元性质 | 数学/算法性质是否成立 | 合成图（确定性） | 是 |
| L1 | native 等价 | C++ 内核与 Python 参考是否等价 | 合成图 + 已有 native | 是 |
| L2 | golden 回归 | 相对已审基线是否有漂移 | `src/render/tests/goldens/gate/` | 是 |
| L3 | 端到端 A-B | 产品观感/全链是否可接受 | 真实 NEF（缺失可豁免） | 是 |

---

## 3. 全局阈值（所有 feature 通用）

| 场景 | 阈值 |
|---|---|
| 无参/禁用/恒等路径 | 与输入逐位一致（`np.array_equal`）；无法逐位者 max\|Δ\| ≤1e-6 |
| 输出值域 | 指定域内（线性域 ≥0 允许 >1；gamma 域 [0,1]） |
| NaN/Inf | 禁止 |
| f64 native vs Python | max\|Δ\| = 0（逐位） |
| f32 native vs Python | max\|Δ\| ≤1e-6 |
| 1D LUT 应用 vs `np.interp` 参考 | max\|Δ\| ≤1e-6 |
| 3D LUT 插值 vs 解析内核 | 格点 max\|Δ\|=0；任意点 max\|Δ\| ≤2/255 且附视觉说明 |
| golden 回归（确定性路径） | 与 golden 逐位一致；cv2/BLAS 路径 max\|Δ\| ≤1e-6 |
| 全链 A-B（同尺寸 fine/full） | p50 ≤2/255、p99 ≤10/255（512 实时档 p99 ≤12/255） |
| 灰阶/中性保护 | 中性 R=G=B 输入输出通道差 ≤1e-6（除非该功能语义就是着色） |

---

## 4. 统一输入构造

gate 测试不得使用未固定种子的随机图做唯一依据；统一 fixtures：

| fixture | 构造 |
|---|---|
| `gray_ramp` | 256×1 float32，线性 0→1；测试单调性与端点 |
| `neutral_gray` | 128×128，R=G=B 多档灰块 [0, 0.18, 0.5, 0.8, 1.0] |
| `color_steps` | 8×8×3，R/G/B/Y/C/M 六色阶 + 灰阶，值域 [0,1] |
| `skin_patch` | 肤色 Lab 中心 (140,150) 邻域 + 中性背景的 uint8 图 |
| `warm_highlight` | 高饱和暖橙 S≥0.32、暗背景上的小亮斑 |
| `spot_on_dark` | 暗底 + 3×3/5×5 高亮小斑（refine 防抹除） |
| `random_small` | `np.random.default_rng(20260820)` 生成 64×64×3 |
| `real_nef` | `render/bench` 或环境变量 `RAW_PATH` 指定，≥5 张 |

---

## 5. 每功能门禁

### 5.1 曝光（exposure）

- 输入构造：`gray_ramp`、`color_steps`、含高光块的 0..1.5 图；
  StageContext 带 DCP profile（合成或加载仓库 profile）。
- 期望性质与阈值：

| 用例 | 期望 | 阈值 |
|---|---|---|
| mode=off / EV=0 且无曲线 | 输出=输入 | 逐位 |
| EV>0 灰阶 ramp | 严格单调不减，不硬裁 | max 相邻负差 ≥0；高光经 rolloff |
| rolloff knee 以下 | 与输入线性段一致 | ≤1e-6 |
| rolloff knee 处 | 连续 | ≤1e-6 |
| 中灰锚点 | 0.18 → ≈117/255 | ≤1/255 |
| auto EV | 中位对数亮度收敛到目标 | ≤0.05 EV |
| max_ev | EV 钳位 | 精确等于 max_ev |
| 高光保护 | 增益前 ≥0.985 像素写 sat_mask；输出无硬裁 | mask 逐位；无 >1 硬裁 |
| native `PixoRenderExposureApply` | 同图同参 vs Python | f32 ≤1e-6 |

### 5.2 白平衡（whitebalance）

- 输入构造：`neutral_gray`、`color_steps`；profile 合成 CM/FM；
  mode ∈ {off, as_shot, auto, manual, [r,g,b]}。
- 期望性质与阈值：

| 用例 | 期望 | 阈值 |
|---|---|---|
| mode=off 且无 warmth/trim | 输出=输入 | 逐位 |
| manual temp/tint | 与 `temp_tint_to_wb` 结果一致 | ≤1e-6 |
| temp/tint 往返 | 色温往返误差小 | ≤1e-3 |
| 中性灰 | manual WB 下仍中性（R=G=B） | ≤1e-6 |
| tint 方向 | 正 tint → B 相对更高 | 符号断言 |
| warmth 曲线/锚点 | 按 wb_B 插值，越界 raise | 数值一致 + 抛 ValueError |
| trim 3/9 元 | 对角/3×3 矩阵语义 | ≤1e-6 |
| native `PixoRenderMatrixApply3` | 与 `img @ M.T` 一致 | f32 ≤1e-6 |

### 5.3 曲线 / 影调（tone / user_curve / sixkey）

- 输入构造：`gray_ramp`、`color_steps`、非单调曲线样例；
  eotf ∈ {srgb, power22, lrfit}；profile_curve 开/关。
- 期望性质与阈值：

| 用例 | 期望 | 阈值 |
|---|---|---|
| 恒等曲线 / 全零 sixkey | 输出=输入 | 逐位 |
| base LUT（srgb/power22/filmic） | 单调不减、端点 0→0、1→1 | 单调严格；端点 ≤1e-6 |
| profile curve 非单调输入 | 拒绝 | ValueError |
| `apply_lut1d` vs `np.interp` | 一致 | ≤1e-6 |
| 中灰 anchor | gamma 中灰 ≈117/255 | ≤1/255 |
| user_curve | 只按 luminance 变亮/压暗，中性不偏色 | 中性通道差 ≤1e-6 |
| sixkey 单滑块 | 高光键只动亮部、阴影键只动暗部；灰阶单调；中性无偏色；whites ≤1、blacks ≥0 | 各 ≤1e-6 / 边界 ≤1e-6 |
| native `PixoRenderToneApplyLut1D` | 与 Python LUT 应用一致 | f32 ≤1e-6 |

### 5.4 HSL

- 输入构造：`color_steps`、`neutral_gray`、8 band 默认结构与
  单 band 参数（hue/sat/lum 组合）。
- 期望性质与阈值：

| 用例 | 期望 | 阈值 |
|---|---|---|
| enabled=False / bands=None / 全 0 | 输出=输入 | 逐位 |
| 任意参数中性灰 | 中性不变 | ≤1e-6 |
| sat 只影响选中 segment | 非选中 segment 不变 | ≤1e-6 |
| hue shift | V 保持 | ≤1e-6 |
| luminance | H 保持 | ≤1e-6 |
| 环形 mask 环绕 | 0°/180° 带跨边界一致 | ≤1e-6 |
| 输出值域 | [0,1] 无 NaN | 严格 |
| 非法参数 | 越界/缺 key 抛 ValueError | 精确 |

### 5.5 分离色调（split_tone）

- 输入构造：`neutral_gray`、纯黑/纯白块、luma 渐变；
  hue/sat/balance/strength 网格。
- 期望性质与阈值：

| 用例 | 期望 | 阈值 |
|---|---|---|
| enabled=False / sat 全 0 / strength=0 | 输出=输入 | 逐位 |
| 纯黑 | 只受 shadow hue/sat 影响 | highlight 部分 =0 |
| 纯白 | 只受 highlight hue/sat 影响 | shadow 部分 =0 |
| balance | 分割点随 balance 单调移动 | 单调 |
| strength=0.5 | 效果 = 0.5×strength=1（线性） | ≤1e-3 |
| hue 360 | 等价 hue 0 | ≤1e-6 |
| 中性灰 | 颜色与 HSV 参考一致 | ≤1e-3 |
| balance 附近 | C1 连续（相邻参数输出差有限） | ≤1e-3 |
| 输出值域 | [0,1] 无 NaN | 严格 |

### 5.6 色彩校准（calibration）

- 输入构造：`color_steps`、红/绿/蓝纯色块 + 灰阶；
  shadow_tint/red|green|blue hue/sat 网格。
- 期望性质与阈值：

| 用例 | 期望 | 阈值 |
|---|---|---|
| enabled=False / 全 0 | 输出=输入 | 逐位 |
| shadow_tint | 只影响暗部，中性着色有界 | 亮部 ≤1e-6；色偏 ≤|tint| 语义 |
| red_hue/red_sat | 只显著作用于红相区域，灰/绿/蓝近乎不变 | 非目标区 ≤1e-3 |
| green/blue 同理 | 同上 | 同上 |
| 输出值域 | [0,1] 无 NaN | 严格 |
| 参数越界 | ValueError | 精确 |

### 5.7 肤色（skin：skin_mask / skin_smooth / colorcal 肤色保护）

- 输入构造：`skin_patch`（Lab 椭圆内外）、带噪声肤色块、非肤色块。
- 期望性质与阈值：

| 用例 | 期望 | 阈值 |
|---|---|---|
| mask 值域/dtype | float32 [0,1] | 严格 |
| mask 椭圆内/外 | 肤色 ≈1、中性背景 ≈0 | 内 ≥0.95、外 ≤0.05 |
| 软边界 | 边界单调过渡，无 NaN | 单调 |
| 椭圆常量 | (140,150,22,14,0.65,band 0.25) | 精确 |
| smooth strength=0 / 无肤色 | 输出=输入 | 逐位 |
| smooth | 仅 mask 区改变 | mask=0 区域逐位 |
| 噪声方差 | 肤色区平滑后方差下降 | 下降 ≥10% |
| 无边缘 halo | 边缘 3px 内无振铃（max 变化有界） | ≤1/255 |
| colorcal skin_protect | 与 `core.skin.skin_mask` 同掩码 | ≤1e-6 |

### 5.8 精修（refine：sharpen / chroma_denoise / highlight_desat /
warm_sat_gamma）

- 输入构造：`gray_ramp`、`color_steps`、`warm_highlight`、`spot_on_dark`。
- 期望性质与阈值：

| 用例 | 期望 | 阈值 |
|---|---|---|
| sh=cd=hd=0 且无 warm 参数 | 输出=输入 | 逐位 |
| sat_protect 端点 | S≤0.08 →0、S≥0.32 →1 | 精确 |
| sharpen | 中性/低饱和区增细节、高饱和区保护；不产生色偏 | 灰块通道差 ≤1e-6 |
| chroma_denoise | 小亮斑不被抹除 | 亮斑峰值损失 ≤5/255 |
| highlight_desat | 低饱和高光去色、高饱和暖色保留 | 暖色 S 损失 ≤10/255 |
| warm_sat_gamma 无参数 | 输出=输入 | 逐位 |
| warm_sat_gamma curve/spot/hue | 按 wb_B 命中、锚点不触发 | ≤1e-3 |
| 输出值域 | [0,1] 无 NaN | 严格 |
| native `PixoRenderRefineApply` | 同图同参 vs Python | f32 ≤1e-6 |

### 5.9 影调分离前/清晰度（clarity）

- 输入构造：灰阶 ramp、边缘块（左暗右亮阶跃）、高频纹理块；
  strength ∈ {0, 0.5, 1.0}，radius ∈ {1, 15, 60}。
- 期望性质与阈值：

| 用例 | 期望 | 阈值 |
|---|---|---|
| enabled=False / strength=0 | 输出=输入 | 逐位 |
| 平坦区 | 局部对比增强不改变平均亮度 | 均值差 ≤1/255 |
| 边缘 | 边缘两侧局部对比增加，无过冲振铃 | 过冲 ≤1/255 |
| 半径单调性 | radius 增大，作用域扩大 | 非递增边界 |
| 输出值域 | [0,1] 无 NaN | 严格 |
| native `PixoRenderClarityApply`（若存在） | 同图同参 vs Python | f32 ≤1e-6 |

### 5.10 色彩校准 Lab 路径（colorcal：饱和/自然饱和/色相/中性/肤色保护/色域）

- 输入构造：`color_steps`、`neutral_gray`、`skin_patch`、高饱和暖色块；
  saturation/vibrance/hue/neutral_a/neutral_b/skin_protect/gamut_soft 网格。
- 期望性质与阈值：

| 用例 | 期望 | 阈值 |
|---|---|---|
| 全 0 且无曲线/无 skin_trim | 输出=输入（快速路径） | 逐位 |
| saturation | 色度按 gain 线性缩放 | ≤1e-3 |
| vibrance | 低饱和区增益大于高饱和区 | 增益单调性 |
| hue | a/b 平面旋转角 = 参数 | ≤1e-3 |
| neutral_a/b | 只显著影响低色度区 | 高色度区 ≤1e-6 |
| 中性曲线 | 按 7 点亮度桶插值 | ≤1e-3 |
| skin_protect | 肤色区增益衰减，与 `core.skin.skin_mask` 同掩码 | ≤1e-6 |
| gamut_soft | 越界通道向灰回拉，不改变色相方向 | 各通道 ≤1e-6 |
| native `PixoRenderColorCalApplyLab` | 同图同参 vs Python | f32 ≤1e-6 |
| 33³ LUT | 格点 0 误差；任意点 ≤2/255 + 视觉说明 | §3 |

### 5.11 风格化 LUT（stylize）

- 输入构造：恒等 LUT、强对比/着色 LUT、`color_steps`；
  `lut_strength` ∈ {0, 0.5, 1.0}。
- 期望性质与阈值：

| 用例 | 期望 | 阈值 |
|---|---|---|
| lut=None / strength=0 | 输出=输入 | 逐位 |
| strength 线性混合 | out = lerp(input, lut(input), strength) | ≤1e-3 |
| 恒等 LUT | 输出=输入 | 逐位/≤1e-6 |
| 3D LUT 应用 | 格点精确、插值 ≤2/255 + 视觉说明 | §3 |
| 输出值域 | [0,1] 无 NaN | 严格 |

### 5.12 色相/饱和映射（huesat：HueSatMap/LookTable + 局部暖高光饱和）

- 输入构造：六色相阶 + 灰阶 + `warm_highlight`；恒等 HueSatMap、非恒等
  sat_scale/hue_shift 表；warm_highlight_sat ∈ {1, 3, 5}。
- 期望性质与阈值：

| 用例 | 期望 | 阈值 |
|---|---|---|
| strength=0 / 无表 / warm=1 | 输出=输入 | 逐位 |
| 恒等表 | 往返 max\|Δ\| ≤1e-6 | ≤1e-6 |
| H 轴环绕 | 0° 与 360° 邻域一致 | ≤1e-6 |
| sat_scale 带 | 带内全效、带外不变、边缘 smoothstep | ≤1e-3 |
| warm_highlight_sat | 只增强命中暖带像素；中性不动 | 中性 ≤1e-6 |
| coverage 分支 | 低覆盖 broad、高覆盖 spot，与 Python 同分支 | 分支一致 + f32 ≤1e-6 |
| native `PixoRenderApplyLocalWarmSat` | 同图同参 vs Python | f32 ≤1e-6 |

---

## 6. golden 回归（L2）

- 数据位置：`src/render/tests/goldens/gate/<feature>/<case>.npy` +
  `manifest.json`（版本、fixture 指纹、sha256、生成者、审阅者）。
- 生成器：`src/render/tests/goldens/generate_gate_goldens.py`，只生成
  合成图 golden；真实 NEF golden 不入库（体积），改为记录特征哈希。
- 更新流程：功能语义变更 → 生成新 golden → reviewer 复核 diff → 双人同意后
  提交；不允许单人改测试改 golden 一起合。
- 阈值：确定性路径逐位；cv2 路径 ≤1e-6；8-bit 输出 ≤1/255（结构差异豁免
  见 §10）。

---

## 7. 端到端 A-B（L3）

1. **同尺寸 native vs Python 全链**（可离线）：5 张 `random_small` +
   ≥2 张真实 NEF 缩到 1024 长边，native 开关各跑一遍：
   f32 路径 max|Δ| ≤1e-6；LUT 路径 ≤2/255。
2. **预览 vs 全质量**（v1.6 口径）：同一 long_edge（1024/2048），
   p50 ≤2/255、p99 ≤10/255；512 实时档 p99 ≤12/255。
3. **参数单调性 A-B**：对每个 feature 取 0/0.5/1.0 三档强度，输出差异
   单调（|Δ(0.5)| 位于 0 与 |Δ(1.0)| 之间，允许 1e-3 波动）。
4. 当前状态（t37 审核实测，DNG DSC_5607，v1.6 口径）：
   long1024 cold total=1401ms / hot total=296ms；long2048 cold total=2094ms /
   hot total=911ms；A/B long1024 p50=1/255、p99=10/255，long2048 p50=1/255、
   p99=9~10/255 → **在现有 DNG 语料下达标**。真实 NEF 语料补齐前，
   L3 仍要求 RAW_PATH 真实 NEF 数据再产证一次。

---

## 8. pytest marker 与运行方式

### 8.1 marker 注册

`src/render/tests/conftest.py` 增加：

```python
config.addinivalue_line("markers",
                        "gate: pixo.render 功能门禁测试（失败阻塞合并）")
config.addinivalue_line("markers",
                        "gate_e2e: 需真实 NEF 的门禁 A-B（RAW_PATH 缺省时 skip）")
```

### 8.2 文件组织

```
src/render/tests/gate/
  __init__.py
  conftest.py                 # gate fixtures（§4 输入构造）
  test_gate_exposure.py       # pytestmark = pytest.mark.gate
  test_gate_whitebalance.py
  test_gate_curves.py
  test_gate_hsl.py
  test_gate_split_tone.py
  test_gate_calibration.py
  test_gate_skin.py
  test_gate_refine.py         # 锐化/降噪/高光去色/warm_sat_gamma
  test_gate_clarity.py
  test_gate_colorcal.py
  test_gate_stylize.py
  test_gate_huesat.py
  test_gate_native_equivalence.py   # L1 汇总
  test_gate_golden.py               # L2
  test_gate_e2e_ab.py               # L3，另标 gate_e2e
  test_gate_coverage.py             # 守门员覆盖矩阵自检（§8.4）
```

### 8.3 命令

```bat
python -m pytest src/render/tests/gate -q -m gate
python -m pytest src/render/tests/gate -q -m "gate and not gate_e2e"
python -m pytest src/render/tests/gate -q -m "gate and gate_e2e"
```

- `-m gate`：全部功能门禁（L0~L2 + L3；无 RAW_PATH 时 gate_e2e 用例以
  `pytest.skip("RAW_PATH not set")` 跳过，不算失败）。
- native 缺失在 gate 内**不允许 skip**：`run_all_tests.bat` 会先构建 DLL；
  若 `render._native.available()==False`，gate 用例 `pytest.fail`。

### 8.4 守门员覆盖矩阵自检（防漏测）

`test_gate_coverage.py` 维护唯一覆盖矩阵（12 feature × 4 层），并在
`pytest --collect-only` 后断言：

1. 每个 feature 至少存在 L0 用例（1 个 feature ≥3 个独立性质断言）；
2. 有 native 内核的 feature 必须存在 L1 用例（decode/hsv/warm_sat/
   colorcal/refine/exposure/matrix/tone/clarity）；未原生化 feature 在矩阵中
   标注 `N/A`，不得静默标记为“已覆盖”；
3. 每个 feature 至少 1 个 golden case；
4. 参数强度 0/0.5/1.0 三档单调性 A-B 至少覆盖全部 12 feature；
5. 新注册 stage 未出现在矩阵中 → 收集阶段直接失败（门禁不完整即阻塞）。

矩阵初始值：

| feature | L0 | L1 | L2 | L3 | native 内核 |
|---|---|---|---|---|---|
| exposure | ✓ | ✓ | ✓ | ✓ | ExposureApply |
| whitebalance | ✓ | ✓ | ✓ | ✓ | MatrixApply3 |
| curves/tone | ✓ | ✓ | ✓ | ✓ | ToneApplyLut1D |
| huesat | ✓ | ✓ | ✓ | ✓ | hsv/warm_sat |
| clarity | ✓ | ✓ | ✓ | ✓ | ClarityApply |
| colorcal | ✓ | ✓ | ✓ | ✓ | ColorCalApplyLab/Lut3D |
| calibration | ✓ | N/A | ✓ | ✓ | 暂无 |
| hsl | ✓ | N/A | ✓ | ✓ | 暂无 |
| split_tone | ✓ | N/A | ✓ | ✓ | 暂无 |
| skin | ✓ | N/A | ✓ | ✓ | 暂无（guided filter Python） |
| stylize | ✓ | ✓ | ✓ | ✓ | Lut3D |
| refine(锐化/降噪) | ✓ | ✓ | ✓ | ✓ | RefineApply |

---

## 9. run_all_tests.bat 集成（失败即阻塞）

`render/run_all_tests.bat` 调整为：

| 步骤 | 内容 | 失败行为 |
|---|---|---|
| 1/6 | native CMake 构建 | exit /b 1 |
| 2/6 | C++ 单元测试 | exit /b 1 |
| **3/6（新增）** | `python -m pytest src/render/tests/gate -q -m "gate and not gate_e2e"` | **exit /b 1** |
| 4/6 | Python 全量 `pytest -m "not e2e"` | exit /b 1 |
| 5/6 | `bench_preview` cold（`--gate` 开启阈值判定） | **exit /b 1** |
| 6/6 | `bench_preview` hot（`--gate`） | **exit /b 1** |

说明：
- `bench_preview.py` 增加 `--gate` 参数：任何 v1.6 门禁（decode/stage/A-B）
  未达标时以非零退出；不加 `--gate` 保持“只告警”的本地开发行为。
- 连续集成/合并前必须跑 `run_all_tests.bat`；任何 `[FAIL]` 阻塞合并。
- `pytest` 中出现的 `pytest.mark.skip` 只允许 `gate_e2e` 因缺 `RAW_PATH`
  使用；其他 skip 视为违规（reviewer 检查）。

---

## 10. 失败处理与豁免

1. 失败分类：gate 失败先定位层（L0 性质 → L1 等价 → L2 golden → L3 A-B），
   修复后**从该层向下重跑全部**，不允许只跑单用例。
2. 阈值修改：任何放宽/收紧必须由架构师改本规范 + reviewer 审，并附
   5 张以上实测数据；同一次 MR 不允许同时改实现和阈值（除非 golden 走 §6
   双人流程）。
3. 豁免：环境缺真实 NEF（gate_e2e skip）、缺 GPU（GPU 专属用例 skip）可豁免；
   native 缺失、性能超时、数值超差一律不豁免。
4. 阻塞状态：gate / 性能 / A-B 任一失败即阻塞合并；当前 DNG 语料下
   `run_all_tests.bat` 六步全绿，真实 NEF 语料到位后需重跑 L3 再确认。

---

## 11. 当前达标状态与首跑基线

| 层 | 状态 | 说明 |
|---|---|---|
| L0 单元性质 | 达标 | 12 feature 均有 gate 文件（t37 补齐 clarity/colorcal/stylize/huesat） |
| L1 native 等价 | 达标 | 覆盖全部已导出 native 内核；DLL 缺失在 gate 内 fail |
| L2 golden | 达标 | `src/render/tests/goldens/gate/` 12 feature + manifest（reviewer=t37-reviewer） |
| L3 A-B | DNG 达标 / 真实 NEF 待产证 | DNG 实测 p50=1、p99≤10；cold/hot 六步全绿 |

首跑要求：完成 gate 目录骨架后执行 `run_all_tests.bat`，生成第一版
`render/bench/gate_baseline_v1.json`；绿灯前基线不得进入发布分支。

---

## 12. 验收清单

1. `render/docs/FUNCTION_GATE_SPEC.md` 存在且与本规范一致。
2. `pytest --markers` 能看到 `gate` 与 `gate_e2e`。
3. §5 全部 12 个 feature（含 clarity/colorcal/stylize/huesat 与 refine 锐化/
   降噪）的 L0 用例存在；每个表格行对应至少一个用例；覆盖矩阵自检通过。
4. L1 用例覆盖当前所有已导出 native 内核；DLL 缺失在 gate 内 fail。
5. L2 golden 目录与 manifest 存在，生成器可复现。
6. L3 gate_e2e 在 RAW_PATH 缺失时 skip，存在时执行并阻塞。
7. `run_all_tests.bat` 含 gate 步骤；gate 失败非零退出。
8. 当前 t13 红灯项在 `render/bench/gate_baseline_v1.json` 中留痕。

---
