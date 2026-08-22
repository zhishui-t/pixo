# pixo.render 全链路预览（P1）方案设计

> 版本：v1.6（t23 修订：消除 v1.5 口径矛盾，按 t13 冷测数据确认门禁）  
> 状态：待审核  
> 作者：架构师（长安小队）  
> 需求来源：`render/docs/PIXO_RENDER_PREVIEW_UI_REQUIREMENTS.md` v1.0（定稿）  
> 上级文档：`render/docs/PIXO_RENDER_1S_FEASIBILITY.md`（t8 输出）  
> 关联规格：`render/docs/PIXO_RENDER_NATIVE_SPECIFICATION.md`（C ABI 规范）  
> 目标文件：`render/docs/PIXO_RENDER_1S_PREVIEW_DESIGN.md`（本文档）

---

## 0. 口径定义（v1.5，以此为准）

1. **P1 = 全链路预览**：执行完整 DEFAULT_STAGES 链
   （exposure / whitebalance / huesat / tone / clarity / colorcal /
   calibration / hsl / split_tone / skin / stylize / refine），
   用户开启的调整全部生效；**不允许用 preview_fast 砍 stage 凑时间**。
2. **分辨率按长边定义，保持原始宽高比**：
   - `long1024`：长边 1024。对 2020×3032（2:3）half_size 输出为
     **682×1024（约 0.70MP）**；横向图则为 1024×682。
   - `long2048`：长边 2048。对 2:3 图为 **1365×2048（约 2.80MP）**。
   - 不再使用“固定 1024×2048”画布；不裁切、不拉伸，`max(w,h)=long_edge`。
3. **目标分档（v1.6 确认，唯一口径）**：
   - **long1024（682×1024，0.70MP）**：
     热路径（会话已打开、参数增量重算）**≤1.0s 硬门禁**；
     冷启动首帧（含 rawpy 首次 CFA 访问）**≤2.0s 硬门禁、≤1.5s 目标**。
   - **long2048（1365×2048，2.80MP）**：
     常规门禁 **≤2.0s（热路径硬门禁，不是 ≤1s）**，热路径目标 ≤1.0s；
     冷启动首帧 **≤3.0s 硬门禁、≤2.5s 目标**。
   - **long4096（高 DPR）不承诺 ≤1s**：渐进加载，中心块 ≤1.0s，
     整图 ≤3.0s（详见 §12.1）。
   - t13 实测（冷启动）：long1024≈1.9s、long2048≈3.2s——long1024 已过
     v1.6 冷门禁但未达 1.5s 目标；long2048 超 3.0s 冷门禁，必须完成
     §4.6 的阻塞项后才能通过验收。
4. “half_size 2020×3032 全质量 1s”仍不可行（t8 结论不变）；P1 是低分辨率
   全链路预览，不替代全质量渲染。
5. `preview_fast` 轻量链保留为 **P-degraded 紧急兜底**，不参与 P1 验收。
6. P1 允许与全质量渲染的等比缩图存在可解释差异，按 §7 A/B 门禁交付。
7. **Web UI 分层预览（v1.6 口径）**：
   - 实时档长边 512：拖动更新 ≤500ms（热），首帧可用 P0 缩略图先见；
   - 精细档长边 2048：热路径门禁 ≤2.0s、目标 ≤1.0s；**不再写 2048≤1s 硬门禁**；
   - 精细档长边 4096：不承诺 ≤1s，渐进分块；
   - 全尺寸 1:1：1~3s 分块渐进；
   - 导出档独立 4s 主线。
8. **8-bit / 16-bit 双接口（v1.5 新增）**：Web 显示返回 8-bit
   JPEG/WebP；自动化修图接口返回 16-bit RGB（PNG-16/TIFF-16/48bpp raw），
   内部全程保持 16-bit 精度，输出编码可切换。
9. **缓存与增量（v1.5 新增）**：RAW 解码一次缓存线性中间图；滑块拖动
   只重算受影响 stage；最终全质量渲染直接复用 UI 参数。

---

## 1. 目标与验收口径

| 指标 | 目标 | 判定 |
|---|---|---|
| P1-long1024 热路径（会话内增量） | decode ≤0.30s；stage ≤0.60s；**端到端 ≤1.0s** | bench 5 次取中位 |
| P1-long1024 冷启动首帧 | decode（冷）≤1.50s；端到端 **≤2.0s 硬、≤1.5s 目标** | 同上（t13=1.9s，未达目标） |
| P1-long2048 热路径 | decode ≤0.32s；stage ≤1.60s；**端到端 ≤2.0s（不是 ≤1s）**，目标 ≤1.0s | bench 5 次取中位 |
| P1-long2048 冷启动首帧 | decode（冷）≤1.50s；端到端 **≤3.0s 硬、≤2.5s 目标** | 同上（t13=3.21s，未过） |
| UI 实时档（长边 512，允许降级） | 热更新 ≤0.5s；首帧 P0 缩略图 ≤0.3s | Web 接口计时 |
| UI 精细档（长边 2048） | 热路径 ≤2.0s 硬 / ≤1.0s 目标 | Web 接口计时 |
| UI 精细档（长边 4096） | 不承诺 ≤1s；中心块 ≤1.0s、整图 ≤3.0s | Web 接口计时 |
| UI 全尺寸 1:1 | 1~3s，分块渐进（先出中心块） | Web 接口计时 |
| 8-bit 预览编码 | JPEG q=88 / WebP q=85，≤60ms | 编码计时 |
| 16-bit 接口 | PNG-16/TIFF-16/48bpp raw，编码 ≤300ms | 接口计时 |
| P0 extract_thumb | ≤0.3s | 同上 |
| P3 回退（rawpy AHD half + 全链路 long1024） | ≤2.5s | 同上 |
| P1 vs 全质量等比缩图 | 精细/全尺寸：p50 ≤2/255、p99 ≤10/255；512 实时允许 p99 ≤12/255 | §7 |
| 原生缺失 | 逐 stage Python 回退，无异常 | pytest |

---

## 2. 总体架构

```
render_preview_full(raw_path, long_edge=1024, params=None)
  │
  ├─ 1) rawpy.RawPy.imread(raw_path)                 # 元数据 + CFA 解包
  ├─ 2) raw.raw_image_visible (uint16 HxW CFA)
  ├─ 3) render._native.PixoRenderDecodeCfaHalf(...)     # C++ 2×2 分箱 → half RGB
  │       └─ 失败/不可用 → decode_raw(half_size=True)   # 回退 P3
  ├─ 4) 等比缩放：scale = long_edge / max(H, W)，INTER_AREA
  │       long1024 → 682×1024（0.70MP） / long2048 → 1365×2048（2.80MP）
  ├─ 5) build_default_pipeline(prof, params)        # 完整 12 stage，不减链
  ├─ 6) Pipeline.run(...)                           # 逐 stage render/native/LUT，不可用回退 Python
  └─ 7) uint8 输出 + 元数据（long_edge、实际尺寸、native 命中、分段耗时）
```

- 解码产物仍为线性相机 RGB（0..1 相对白电平），下游 12 stage 语义不变；
- `render_preview_full` **不调用 preview_fast.json**；
- 各 stage `wants()` 门控保留（业务上“未启用/无数据”跳过不算砍链）；
- 逐 stage 回退：某 stage native 失败只回退该 stage 的 Python 实现。

---

## 3. C++ CFA 2×2 分箱快速解码

### 3.1 算法定义

输入 `raw.raw_image_visible`（uint16 CFA HxW）。每 2×2 quad：
`R=cfa@R`、`B=cfa@B`、`G=(g0+g1)/2`；
`v=max((v-black[c]) / max(white-black[c],1), 0)`（保留 >1 高光）；
输出 `(H/2, W/2, 3)` C 连续 float32。

### 3.2 C ABI

```cpp
// render/native/src/decode.h
struct PixoRenderCfaDecodeParams {
    int patternR;          // R 在 2x2 中的线性位置 0..3
    int patternG0;         // 两个 G 位置
    int patternG1;
    int patternB;
    float black[4];        // rawpy black_level_per_channel
    float whiteLevel;      // raw.white_level
    float outputScale;     // 调试缩放，通常 1.0
};

PIXO_RENDER_NATIVE_API int PixoRenderDecodeCfaHalf(
    const uint16_t* cfa, float* rgbOut, int width, int height,
    const PixoRenderCfaDecodeParams* params);
```

- 5 参数；输出 `floor(H/2) × floor(W/2) × 3`；状态码 0/-1/-3；
- Python 从 `raw.raw_pattern` 换算 patternR/G0/G1/B；
- 循环行级 OpenMP 可选；黑白归一化预计算逆系数。

### 3.3 decode 分段预算（v1.6：冷/热分开，不再统一 300ms）

**热路径（会话内，RAW 已打开，只重算解码后链）**：

| 环节 | long1024 | long2048 |
|---|---:|---:|
| `PixoRenderDecodeCfaHalf`（12MP CFA → 6.1MP half） | ≤0.20s | ≤0.20s |
| 等比缩放（INTER_AREA） | ≤0.02s | ≤0.04s |
| **热 decode 合计** | **≤0.30s（维持 200~300ms）** | **≤0.32s** |

**冷启动（本进程首次打开该 RAW）**：

| 环节 | 实测（t13） | v1.6 门禁 |
|---|---:|---:|
| rawpy `RawPy.imread` + 首次 `raw_image_visible` | 1.1~1.4s | ≤1.20s 硬、≤0.80s 目标 |
| C++ CFA 分箱 + 缩放 | ~0.1~0.2s | ≤0.30s |
| **冷 decode 合计** | **~1.2~1.6s** | **≤1.50s 硬、≤1.10s 目标** |

- 结论：**300ms 只适用于热路径**；冷启动 decode 预算 v1.6 明确放宽为
  1.50s（原因：rawpy/libraw 首访 CFA 触发解包，当前 1.1~1.4s）。
- 冷启动优化方向：进程内按 raw_path 缓存已打开 RawPy/CFA 元数据；
  优先展示 P0 extract_thumb（≤0.3s）掩盖冷 decode；后续评估 DNG 快速
  unpack 或 C++ CFA 读取替代 raw_image_visible 首访。
- 超预算处置：优化 SIMD/OpenMP/分块；仍超则降级 P0/P3；**不允许砍 stage**。

---

## 4. 全链路 stage 预算与 render/native/LUT 接入

### 4.1 长边 1024（1s 硬目标）：stage 合计 ≤600ms

| stage | 手段 | 目标 | 上限 |
|---|---|---:|---:|
| exposure | native 单遍 gain+rolloff | 0.03s | 0.04s |
| whitebalance | native 3×3 矩阵 + 高光中性化 | 0.04s | 0.05s |
| huesat | native HSV + warm_sat；HueSatMap 用 native HSV 或 3D LUT | 0.07s | 0.09s |
| tone | 1D LUT 应用 native | 0.03s | 0.04s |
| clarity | 1/2 降采样 blur + native 合成 | 0.05s | 0.07s |
| colorcal | native Lab 内核或 33³ 3D LUT | 0.08s | 0.10s |
| calibration | 矩阵 + 1D LUT native | 0.03s | 0.04s |
| hsl | native HSV（复用 hsv.cpp） | 0.04s | 0.05s |
| split_tone | shadow/highlight 1D LUT 合成 | 0.04s | 0.05s |
| skin | 1/2 分辨率引导滤波 | 0.05s | 0.06s |
| stylize | 通用 3D LUT `PixoRenderApplyLut3D` | 0.03s | 0.04s |
| refine | native 融合内核（t1 M3） | 0.05s | 0.07s |
| **合计** | | **0.54s** | **≤0.60s** |

总预算（**热路径**）：decode 0.30 + stage 0.60 + overhead 0.05 + 余量 0.05
= **≤1.00s**。冷启动另有 decode 1.50s + stage 0.45s + overhead 0.05s
= ≤2.00s 硬门禁（目标 1.50s）。stage 与 decode 上限不能同时取满；
bench 分段验收。

### 4.2 长边 2048（v1.6：常规门禁 ≤2.0s，不是 ≤1s）

- 像素量约为 long1024 的 4 倍（2.80MP vs 0.70MP）。按 render/native/LUT 命中的
  实际扩展性估算，stage 合计 **目标 1.00~1.40s、上限 1.60s**（热）。
- **热路径端到端：decode 0.32 + stage ≤1.60 + overhead 0.08 ≈ 2.00s
  → 硬门禁 ≤2.0s，目标 ≤1.0s（依赖全部内核命中）**。
- **冷启动端到端：冷 decode ≤1.50 + stage ≤1.40 + overhead 0.10
  = 3.00s → 硬门禁 ≤3.0s，目标 ≤2.5s**；t13 实测 3.21s，未过冷门禁。
- 不再使用“2048≤1s”作为任何硬门禁；UI 上 2048 精细档的 ≤1s 仅为热缓存
  目标值。

### 4.3 native 内核矩阵

| 内核 | 状态 | 覆盖 stage |
|---|---|---|
| `PixoRenderDecodeCfaHalf` | P1 新增 | decode |
| `PixoRenderRgbToHsvF32` / `PixoRenderHsvToRgbF32` | 已有 | huesat/hsl |
| `PixoRenderApplyLocalWarmSat` | 已有，补 spot | huesat |
| `PixoRenderColorCalApplyLab` | t1 M2 计划 | colorcal |
| `PixoRenderRefineApply` | t1 M3 计划 | refine |
| `PixoRenderApplyLut3D` | t1 计划 | stylize/colorcal(可选) |
| `PixoRenderToneApplyLut1D` | P1 新增 | tone/split_tone |
| `PixoRenderMatrixApply3` | P1 新增 | whitebalance/calibration |
| `PixoRenderExposureApply` | P1 新增（L1） | exposure |
| `PixoRenderClarityApply`（blur 平面输入） | P1 新增（L1） | clarity |

新增 ABI 遵循 t1 规格：5 参数、`pixo.render*Params` 结构体、状态码、异常不外溢；
实现前补入 `PIXO_RENDER_NATIVE_SPECIFICATION.md`。

### 4.4 3D LUT、降采样与并行

- **3D LUT**：colorcal（33³，输入 uint8 gamma RGB，skin_mask/中性曲线
  均可表化）与 stylize 必须 LUT 化；LUT 未过 §7 A/B 门禁不得成为默认。
- **降采样**：clarity/skin 1/2 分辨率；colorcal adaptive 测量 1/2 小图；
  refine 色度路径沿用 1/4（现有算法语义）。
- **并行**：OpenMP 默认关；等价测试全绿后按 decode→colorcal→refine 顺序
  开启，仅并行像素间无依赖循环；开启后重跑 §7。
- **禁止**：为 1s 把 stage 默认参数改小或跳过默认链 stage；性能不足只能换
  内核实现。

### 4.5 Python 集成点

```python
def render_preview_full(self, raw_path, long_edge=1024, params=None,
                        decode_mode="cfa_half_native") -> np.ndarray
```

- 内部：`build_default_pipeline(prof, params)`（**完整 12 stage**）；
- 目标尺寸：`scale = long_edge / max(half_h, half_w)`，`cv2.resize` 等比缩放；
- `Pipeline.run_file` 增加只读 `decode_mode` 与 `preview_scale` 参数；
  生产 `render_adjusted` 默认不变；
- 每个 stage 调用点 “try native → except 回退 Python”，并在
  `ctx.results[-1].metrics["native"]` 记录；
- 旧 `render_preview`（preview_fast）保留为 `render_preview_degraded`，
  返回值带 `mode="degraded"`，不进入 P1 验收。

### 4.6 当前阻塞项（t13 实测，v1.6 必须闭环）

t13 不通过根因与任务分解（未完成这些，v1.6 门禁不得宣称通过）：

1. 冷 decode：`raw_image_visible` 首访 1.1~1.4s → 见 §3.3 冷路径优化。
2. `PixoRenderExposureApply` / `PixoRenderMatrixApply3` / `PixoRenderToneApplyLut1D` /
   `PixoRenderClarityApply` 尚未实现 → 补齐 native 内核。
3. CFA 2×2 与 AHD 差异超预期 → 先用 A/B 定位，必要时 CFA 分箱升级为
   1/2 加权插值或该档回退 rawpy AHD。
4. clarity/skin 降采样污染精细档 → 1024/2048 精细档禁用 clarity/skin
   降采样，恢复全分辨率或经 §7 门禁后才启用。
5. 热缓存掩盖首帧 → bench 必须区分 **cold（新会话首帧）** 与
   **hot（参数增量）**，两者分别验收，不再只报中位数。

---

## 5. 分辨率档与总预算汇总

| 档 | 实际尺寸（2:3 示例） | 像素量 | decode（热/冷） | 全链路 stage | 端到端门禁 |
|---|---|---:|---:|---:|---:|
| **long1024** | 682×1024 | ~0.70MP | ≤0.30s / ≤1.50s | 热 ≤0.60s、冷 ≤0.45s | 热 ≤1.0s；冷 ≤2.0s（目标 1.5s） |
| long2048 | 1365×2048 | ~2.80MP | ≤0.32s / ≤1.50s | 热 ≤1.60s、冷 ≤1.40s | 热 ≤2.0s（目标 1.0s）；冷 ≤3.0s（目标 2.5s） |
| long4096 | 2731×4096 | ~11.2MP | 分块/渐进 | 中心块按 2048 预算 | 不承诺 ≤1s；中心块 ≤1.0s、整图 ≤3.0s |
| P0 extract_thumb | 内嵌 | — | 0.05~0.2s | 无 | ≤0.3s |
| P3 回退（long1024） | 682×1024 | ~0.70MP | rawpy AHD ~0.9s | 全链路 Python | ≤2.5s |

其他口径：
- half_size 2020×3032 全链路：约 6.1MP，预估 1.8~2.5s，不承诺 1s；
- 任何 >长边 2048 的档：不做快档承诺，统一走“长边 2048 预览 + 完整渲染”。

---

## 6. 目录与文件变更

```
render/native/
  src/decode.h / decode.cpp        # CFA 2×2 分箱解码
  src/stage_kernels.h / .cpp       # tone LUT / matrix / exposure / clarity
  tests/test_decode.cpp            # 新增
  tests/test_stage_kernels.cpp     # 新增
render/_native/__init__.py         # 新增解码与 stage kernel 包装
render/core/io.py                  # decode_cfa_half(raw)
render/api.py                      # render_preview_full / render_preview_degraded
render/pipeline/graph.py           # run_file 增 decode_mode / preview_scale
render/modules/*.py                # 逐 stage 加 native 分支（不改语义）
src/render/tests/test_native_decode.py # Python 参考等价
src/render/tests/test_preview_full.py  # 全链路 P1 集成与 A/B
render/tools/bench_pipeline.py     # --preview-full 分段计时
render/docs/...                    # 本文档
```

---

## 7. 质量门禁

### 7.1 逐内核数值等价

- 复用 t1 测试计划：f64 逐位、f32 ≤1e-6；LUT 格点 0 误差、
  插值 ≤2/255 且附视觉说明。
- 新增内核与 Python 参考逐一测试（合成图 64/256/682×1024/1365×2048 +
  边界值）。

### 7.2 P1 全链路 vs 全质量等比缩图 A/B

1. 语料 ≥5 张真实 NEF：
   - A = 全质量渲染（rawpy AHD half + 12 stage，2020×3032）
     → 等比缩到与 P1 相同长边（long1024 / long2048）；
   - B = P1（CFA 分箱 + 12 stage，直接目标长边）；
   - 差异指标 JSON：`mae_channel / max_abs / p50_abs / p99_abs /
     stage_native_hit[]`，存 `render/bench/preview_full_ab_<photo>_<edge>.json`。
2. A/B 门禁（v1.6 确认）：
   - **精细档（1024/2048）与全尺寸 1:1：p50 ≤2/255、p99 ≤10/255，维持
     10 不放宽**；当前未达标按 §4.6 逐项修复，不得用 p99=12 掩盖。
   - **512 实时档：p50 ≤2/255、p99 ≤12/255（唯一允许放宽到 12 的档）**，
     因其用途是手感，且允许 clarity/skin 降采样。
   - 无整片色偏/大面积条纹（`diff_viewer.py` 目检归档）。
3. 差异说明覆盖：CFA 2×2 无方向插值、边缘锯齿、低分辨率对 clarity/skin/
   refine 的作用差异、LUT 插值误差、高光/暗部噪声差异；并附
   “预览为长边 1024/2048 全链路快速渲染，完整渲染见全质量链”UI 文案。
4. 超门禁：按 stage 定位（stage_native_hit 与分段 A/B），修复或该 stage
   回退 Python；仍超则该张回退 P3 并记录原因。

### 7.3 回退与异常门禁

- DLL 缺失/加载失败：`available()==False`，逐 stage Python 回退；
  全量 `pytest -m 'not e2e'` 无新增失败；
- decode 异常：回退 rawpy AHD half 继续跑完整 12 stage（P3）；
- 任一 stage native 异常：只回退该 stage 的 Python 实现，不得整链降级
  preview_fast（除非 P3 也失败）。

---

## 8. 性能测试

`bench_pipeline.py --preview-full` 对真实 NEF 输出：
- 分段：`decode / geometry / exposure / whitebalance / huesat / tone /
  clarity / colorcal / calibration / hsl / split_tone / skin / stylize /
  refine / overhead / total`；
- **必须区分 cold 与 hot 两套验收，禁止只用热缓存中位数**：
  - cold：每个 raw_path 新会话首帧，不得预热；
  - hot：同会话内参数增量重算（只动受影响 stage）。
- long1024 验收：hot total ≤1.0s；cold total ≤2.0s（目标 ≤1.5s）。
- long2048 验收：hot total ≤2.0s（目标 ≤1.0s）；cold total ≤3.0s
  （目标 ≤2.5s）。
- decode 分段：hot ≤0.30s（1024）/≤0.32s（2048）；cold ≤1.50s
  （其中 rawpy 首访 CFA ≤1.20s）。
- 每个 stage 记录 native 命中率；
- 基线 `render/bench/preview_full_baseline_v1.json`；任一档比基线慢 >20% 失败。

---

## 9. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| long1024 全 12 stage 仍超 0.60s | 1s 目标失败 | 逐 stage render/native/LUT；仍超只降长边到 768/512，不砍 stage |
| 热 decode 超 300ms 或冷 decode 超 1.50s | 对应档目标失败 | SIMD/OpenMP/分块；P0 extract_thumb 兜底或回退 P3 |
| long2048 超 2.0s | 快档未达标 | 按 2.0~2.5s 宽松口径记录；引导用 long1024 |
| 3D LUT 插值伪影 | 预览观感 | 33³/65³ 双测；A/B 门禁不过回退解析内核 |
| 降采样造成 clarity/skin 差异 | 视觉差异 | 1/2 与全分辨率 A/B；差异说明归档 |
| OpenMP 数值变化 | 回归难定位 | 默认关；开启重跑全部等价测试 |
| P1 被误用于导出 | 质量事故 | 返回 preview 元数据；生产入口不暴露 decode_mode |

---

## 10. 验收清单

1. `render/native/build.bat` 成功；`PixoRenderDecodeCfaHalf` 与新增 stage kernels 可调用。
2. decode 数值：native vs Python 参考 max|Δ| ≤1e-6；热 decode ≤0.30s；
   冷 decode ≤1.50s（rawpy 首访 CFA ≤1.20s）。
3. **long1024**：hot 端到端 ≤1.0s；cold 端到端 ≤2.0s（目标 ≤1.5s）。
4. **long2048**：hot 端到端 ≤2.0s（目标 ≤1.0s）；cold 端到端 ≤3.0s
   （目标 ≤2.5s）。
5. 12 stage 全链路执行，preview_fast 不作为验收路径；bench 证明除
   `wants()` 业务门控外无 stage 被跳过。
6. 5 张 NEF 的 P1 vs 全质量等比缩图 A/B（long1024 + long2048）数据与
   差异说明归档；精细/全尺寸 p50≤2/255、p99≤10/255，512 实时 p99≤12/255。
7. DLL 缺失逐 stage Python 回退，全量 `pytest -m 'not e2e'` 无新增失败。
8. 生产 `render_adjusted` 行为与输出不受改动影响（默认值不变 + 回归测试）。
9. §4.6 的 5 项阻塞项全部闭环（冷 decode、缺失内核、CFA 差异、
   clarity/skin 降采样、cold/hot 双口径），t13 失败项全部有归零记录。

---

## 11. Web UI 实时预览架构（v1.5 增补）

### 11.1 拓扑

```
浏览器 Web UI
  │  REST：会话 / 参数 / 图像 / 16bit / 最终渲染
  │  WebSocket：进度、分块渐进、取消
  ▼
render.web.preview_server（推荐 FastAPI + uvicorn，线程池执行 CPU 任务）
  │
  ├─ RawPreviewSession（每张 RAW 一个会话）
  │     raw_path / prof / params / decode 缓存 / stage 缓存 / tile 缓存
  │     generation 单调递增（每次参数变更 +1，旧任务结果作废）
  ▼
pixo.render 引擎
  ├─ decode：C++ CFA 2×2 分箱（回退 rawpy AHD）
  ├─ 全链路 Pipeline（12 stage，逐 stage render/native/LUT 回退）
  └─ 8-bit 编码（JPEG/WebP）与 16-bit 编码（PNG-16/TIFF-16/48bpp）
```

### 11.2 会话模型

- `POST /api/preview/sessions`：传入 raw_path、dcp_path、初始 params，返回
  session_id、当前 generation、首张预览（默认实时档 512）。
- 同一 raw_path 打开多个会话允许；同一会话内的参数与缓存互不串扰。
- 并发：CPU 渲染在线程池串行执行（每会话 1 个 worker），WebSocket 推送
  进度；参数变更采用 **generation 令牌**：旧 generation 完成时若令牌已过期，
  直接丢弃结果，避免乱序覆盖。
- 防抖：滑块拖动前端 80~120ms debounce；后端收到新请求时取消/忽略在跑的
  低优先级实时任务。

### 11.3 目录变更（v1.5）

```
render/web/
  preview_server.py   # FastAPI 路由与 WebSocket
  session.py          # RawPreviewSession、缓存、generation、依赖图
  encode.py           # JPEG/WebP 8bit、PNG-16/TIFF-16/48bpp 编码
render/api.py         # 复用 render_preview_full；16bit 输出参数
src/render/tests/test_preview_server.py
```

---

## 12. 分层预览（512 实时 / 2048~4096 精细 / 全尺寸 1:1）

| 档位 | 长边 | 全链路策略 | 目标（v1.6） | 缓存 |
|---|---|---|---:|---|
| 实时档 | 512 | 全链，允许降级（clarity/skin 1/2、colorcal LUT、refine 1/4） | 热更新 ≤500ms；首帧 P0 ≤0.3s，512 首帧 ≤2.0s | 512 最近 1 版 |
| 精细档 | 2048 | 12 stage 全链，render/native/LUT 全部命中 | 热 ≤2.0s 硬 / ≤1.0s 目标；冷 ≤3.0s 硬 / ≤2.5s 目标 | 2048 最近 2 版 |
| 精细档（高 DPR） | 4096 | 12 stage 全链，渐进加载（先中心块） | **不承诺 ≤1s**；中心块 ≤1.0s、整图 ≤3.0s | 分块 |
| 全尺寸 1:1 | 原图 | 全链路，分块渲染（512px tile，中心优先） | 1~3s，先出中心块 | tile 缓存 |
| 导出档 | 原图 | 独立 4s 主线 | ≤4s | 不复用预览缓存 |

### 12.1 4096 精细档口径（v1.6 已确认）

- **4096 不承诺 ≤1s**（需求中“2048~4096 ≤1s”在 v1.6 拆为 2048 与 4096
  两个口径，不再混写）。
- 4096 = 高 DPR 渐进档：中心块 ≤1.0s，整图 ≤3.0s；全链路生效。
- 若产品坚持 4096 整图 ≤1s，则必须上 GPU 或全 stage LUT（t8 R3 分支），
  不包含在本设计验收范围内。

---

## 13. 缓存与增量计算

### 13.1 缓存分层

| 缓存 | 内容 | 生命周期 | 失效 |
|---|---|---|---|
| L0 raw 元数据 | rawpy RawPy 元数据、pattern/black/white | 会话 | 无 |
| L1 decode 缓存 | CFA 2×2 分箱的 half RGB float32（回退为 rawpy 输出） | 会话 | raw_path/decode_mode 变化 |
| L2 目标尺寸缓存 | 各 tier 等比缩放后的线性 RGB | 会话 | tier/geometry 变化 |
| L3 stage 依赖缓存 | 每 stage 输入参数指纹 + 输出数组 | 会话（LRU，上限 512MB） | 参数指纹变化 |
| L4 编码缓存 | 8-bit JPEG/WebP 字节、16-bit 文件路径 | 会话 | 渲染 generation 变化 |
| L5 tile 缓存 | 1:1 分块 JPEG（key=tile+params 指纹） | 会话 | 参数变化逐块重建 |

### 13.2 stage 依赖图与增量重算

- 以 `DEFAULT_STAGES` 顺序建立线性依赖图；参数按 stage 归一化后计算
  sha256 指纹。
- 参数更新时：从第一个指纹变化的 stage 开始重算到链尾（其上游复用缓存）。
- 解码/缩放完全跳过：RAW 只解码一次，所有 tier 共用 L1 缓存。
- 实时档额外优化：512 图重算全链（0.7MP 下便宜）；若实测 >500ms，
  再把低频 stage（clarity/skin）降到 256 计算后上采样。
- 缓存压力控制：超过 512MB 按 LRU 淘汰最旧 stage 输出；session 关闭即释放。

---

## 14. 8-bit Web UI 预览接口

| 方法/路径 | 说明 |
|---|---|
| `POST /api/preview/sessions` | 打开 RAW：`{raw_path, dcp_path, params?}` → session_id |
| `PATCH /api/preview/sessions/{id}/params` | 更新参数：`{"params": {stage: {...}}}` → generation+1 |
| `GET /api/preview/sessions/{id}/image` | query：tier、long_edge、fmt、q；返回 8-bit 图像 |
| `GET /api/preview/sessions/{id}/tile?level=full&x=0&y=0&tile=512` | 1:1 分块渐进 |
| `GET /api/preview/sessions/{id}/params` | 当前归一化参数 JSON |
| `WS /api/preview/sessions/{id}/ws` | 进度/分块就绪/完成/错误事件 |
| `DELETE /api/preview/sessions/{id}` | 释放会话缓存 |

- 8-bit 编码：内部 float32 [0,1] → `round(clamp(x,0,1)*255)`；
  JPEG q=88（预览）/WebP q=85；编码预算 ≤60ms（512/2048）。
- 响应头：`X-pixo.render-Cost-Ms`、`X-pixo.render-Tier`、`X-pixo.render-Generation`、
  `X-pixo.render-Native-Hit`、`ETag`（参数指纹）。
- 错误格式：`{"ok": false, "error": "...", "code": ...}`；DLL 缺失/内核失败
  自动逐 stage 回退并在 `native_hit` 中体现，不报 500。

---

## 15. 16-bit 自动化修图接口

| 方法/路径 | 说明 |
|---|---|
| `POST /api/preview/sessions/{id}/render16` | body：`long_edge?`、`format`（png16/tiff16/raw48）、`params_override?` |
| `GET /api/preview/renders/{render_id}` | 任务状态 / 文件路径 |

编码约定（架构师定）：
- **raw48（推荐给自动化模块）**：48bpp RGB，每通道 uint16 大端
  `round(clamp(x,0,1)*65535)`，行主序；同目录写 `*.json` sidecar
  （宽高、通道序 RGB、值域 0..65535、参数快照、profile 路径）。
- **PNG-16 / TIFF-16**：sRGB gamma 域 16-bit（与 8-bit 预览同域），
  给人类查看或通用工具；PNG 用 cv2.imwrite 16bit，TIFF 由 PIL 输出。
- 内部精度：渲染链全程 float32（等效 >16bit 精度），仅在末端编码时量化；
  文档明确量化误差 ≤0.5/65535（vs 内部 float32），并提供对比说明。
- 16-bit 接口默认使用**当前 session 参数快照**，不改变 UI 状态；
  `params_override` 仅一次性覆盖，不写入 session。
- 输出目录：`render/out/preview16/<session_id>/`；响应返回绝对路径与 sha256。

---

## 16. 最终渲染复用参数

- `GET /api/preview/sessions/{id}/params` 返回 **canonical params JSON**：
  每 stage 经 param_schema 校验与默认值合并后的完整参数，可直接作为
  `render pipeline --config <json>` 或 `build_default_pipeline(params=...)`
  的输入。
- `POST /api/preview/sessions/{id}/export`：创建最终渲染任务
  （raw_path + prof + canonical params + 全尺寸 4s 主线），返回 job_id；
  任务独立执行，与预览会话缓存/worker 隔离。
- `WS` 推送最终渲染进度；产物写入 `render/out/export/<session_id>/`。
- 一致性门禁：以同一 canonical params 分别跑“预览 fine”与“最终全质量”，
  A/B 指标写入任务结果；任何参数被 UI 归一化改动的情况必须可追溯
  （保存原始 params 与 canonical params 两份）。

---

## 17. v1.5 验收清单（v1.6 修订追加）

9. Web 实时档：长边 512 全链路，热更新 ≤500ms；首帧 P0 ≤0.3s、
   512 冷首帧 ≤2.0s。
10. Web 精细档：长边 2048 热 ≤2.0s 硬 / ≤1.0s 目标；冷 ≤3.0s 硬 /
    ≤2.5s 目标。4096 不承诺 ≤1s，按 §12.1 渐进口径验收。
11. 全尺寸 1:1：1~3s，中心块先出，tile 参数失效正确。
12. 增量：只改 refine 参数时，decode 与 refine 之前的 stage 缓存命中，
    `bench` 输出重复计算 stage 数 = 受影响 stage 数。
13. 8-bit 接口：JPEG/WebP 编码 ≤60ms，响应头完整。
14. 16-bit 接口：raw48/PNG-16/TIFF-16 可写可读回，量化误差 ≤0.5/65535，
    sidecar 参数快照完整。
15. 最终渲染：canonical params 与 UI 会话参数一致；全尺寸渲染用 4s 主线
    完成，结果可复现。

---

## 18. v1.6 结论（唯一口径）

- **long1024**：热路径 ≤1.0s 硬门禁；冷启动 ≤2.0s 硬 / ≤1.5s 目标
  （t13 实测 1.9s，过冷门禁未达目标）。
- **long2048**：**门禁是 ≤2.0s（热路径硬门禁），不是 ≤1s**；≤1.0s 仅为
  热缓存目标。冷启动 ≤3.0s 硬 / ≤2.5s 目标（t13 实测 3.21s，未过）。
- **long4096**：**不承诺 ≤1s**；高 DPR 渐进档，中心块 ≤1.0s、整图 ≤3.0s。
- **A/B**：精细档与全尺寸维持 p99 ≤10/255；仅 512 实时档放宽 p99 ≤12/255；
  p50 一律 ≤2/255。
- **冷启动 decode**：300ms 只适用于热路径；冷 decode 门禁 ≤1.50s
  （rawpy 首访 CFA ≤1.20s），t13 实测 1.1~1.4s。
- Web UI 分层、缓存增量、8-bit/16-bit 接口、参数复用沿用 v1.5 设计；
  bench 必须区分 cold/hot 两套验收，§4.6 五项阻塞未闭环前不宣称达标。
- 所有新路径均为 `render/` 独立体系（docs/web/bench/tests），禁止
  import render。

---
