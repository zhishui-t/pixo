# R30 · DNG 复刻线退役 + 色彩准确度问题开题

日期：2026-09-19 ｜ 队长裁决："删除可以" + "现在自研体系渲染色彩不准"

---

## A. DNG 复刻线退役（已执行）

### 背景

OWN PIPELINE 换底完成后，DNG 复刻线（`render_dcp_linear` 底座 + 验证工具）作为
"回退保险"被刻意保留（路线图原则四：每层独立可回退）。现状核实：生产链零触碰、
工具侧零调用、tone_table 数据源已删（3/3 entry 断供）、仅 mock 单测陪跑——
**测试还绿着的死代码**。队长裁决退役。

### 删除清单

| 项 | 处置 |
|---|---|
| `pipeline/base.py`（camera_key/load_camera_cache/find_camera_entry/render_dcp_linear） | **删除** |
| `core/tone.py`（DNG Stage3 数值复刻：exposure_ramp/tone_table_interp/apply_rgb_tone/apply_hue_sat_map/4096 表） | **删除**；huesat oklch 形变消费的 `srgb_encode/decode` 迁入 `core/curves.py`（向量化，标量语义逐位一致） |
| `color_transform.py`（零消费方） | **删除** |
| `render/adjustments/` 包（Phase C 规划占位，零消费方） | **删除** |
| `core/io.py` 的 stage3 段（_read_opcode_list/_apply_vignette/_raw_make/decode_stage3_like，193 行） | **删除**；`camera_neutral_wb*` 生产消费保留 |
| `core/warp.py`（warp_rectilinear，仅 stage3 消费） | **删除** |
| `api.py` 旧标定流（Renderer.calibrate/render/render_file/render_adjusted/_render_adjusted_gamma_float + RawInput/RawMetadata/CameraCalibration/RenderIntent 四 dataclass） | **删除**；现役入口 render_preview/render_preview_full/render_preview_degraded/render_camera_matched 不变 |
| `resources/camera_profiles/dng_camera_cache.json` + pyproject data-files 行 | **删除** |
| 测试：test_renderer_adjust.py（整文件）、test_render_public_adapters.py（整文件，专测占位层）、test_native_decode.py 的 E3 段、test_render_perf_fixes.py 的 render_dcp 测试 | **删除/裁剪** |
| scripts 5 处 `core.tone` import（calib/评估脚本） | 迁 `core.curves`；`calib/optimize.py` 的 torch 代理 `srgb_decode_t` 由 4096 表插值改**解析式**（真实链 R30 起为解析式，代理同步精确化，测试容差 1e-9） |
| `core/huesat.py` 的 apply_hue_sat_map_prophoto/apply_look_table_prophoto 包装（tone 依赖、零调用方） | **删除**；get_*_table/apply_local_warm_sat/make_hue_sat_map 保留（stage 在用） |
| pipeline/__init__.py、pipeline.py、render/__init__.py、raw_loader.py 再导出 | 同步收窄 |

**保留**：`calibration.py` 的 DCP **解析**（load_dcp）——路线图明文"DCP 解析永远
保留"，风格卡/profile_curve/recipe 均在用；DCP 是互操作数据格式，与"DNG 渲染
逻辑"无关。

### 验收

- 全量 **1678 passed / 0 failed / 12 skipped / 1 xfailed**；
- 代码引用零残留（grep 终态仅退役注释与 calib 域同名异物 `diff_core.tone_lut_interp`）；
- 净删约 **1100+ 行**死代码与 6 个文件、1 个资源。

## B. "渲染色彩不准"——诊断定案 + 默认打开观感接线（已执行）

### B1 三轴分解（n=24 vs 相机内嵌 JPEG，median，Lab 8 位标度）

| 臂 | ΔL | Δa | Δb | Δ饱和(HSV) |
|---|---:|---:|---:|---:|
| 中性（此前默认打开） | **−83.5** | +1.0 | −1.0 | −2.1 |
| recipe | −2.5 | −2.0 | −1.0 | −8.0 |
| lr观感 | −40.5 | ±0 | −0.5 | −7.1 |

**定案**：色度轴三条臂都准（±2，与 R29 锚点结论一致）；**病灶在亮度轴**——
默认打开暗 83.5 个 L（约 1/3 量程），即用户观感"又暗又灰=色彩不准"的主体。
lr观感臂 −40.5 vs 相机 ≈ LR 与相机的已知亮度差（相机自动提亮）——
**lr观感 ≈ LR**，正中"打开照片≈LR"北极星。

### B2 默认打开观感接线

- `configs/styles/default_look.json`：lr_adobe_standard 卡参数（R29 暖度清偿
  + R24 复合语义修复后的锚点验证形态）；
- `_default_session_factory` 注入 `_load_default_look()` 为新会话初始 params
  （进程内缓存；env `PIXO_DEFAULT_LOOK=off` 回中性 R23 行为；非空路径覆盖；
  文件缺失回中性 + warning 不阻断）；用户 patch 深合并覆盖一切键；
- 边界：引擎各 Stage 默认值不动（R23 纪律）；auto-loop 自建闭环不受影响；
  strict 参数栅栏天然放行（卡参数本过栅栏）。

### 验收

全量 **1680 passed / 0 failed**；新增 2 个 loader/工厂单测。

### 遗留（下一轮候选）

- 前端 enabled 接线断点（R23 翻 enabled 后 UI patch 不带 enabled:true——
  清晰度/HSL/锐化等调了没效果）——"其他功能也得要有"的收尾；
- 饱和轴：look 系臂 vs 相机 ΔS ≈ −7（LR 系观感本比相机收敛，暂按 LR 语义
  接受；LR 参照重建后可精调）。
