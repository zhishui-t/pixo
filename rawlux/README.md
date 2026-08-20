# RawLux

RawLux 是一个独立、高内聚的 RAW 渲染引擎包：输入 NEF/DNG + DCP，输出与 DNG SDK 对齐的渲染结果，并在此基础上提供可测量的修图调整能力。

## 设计目标

- **与 rawlab 撇开**：`rawlux` 源码零 `from rawlab` / `import rawlab`；`rawlab` 仅作为反向兼容 shim。
- **高内聚**：核心引擎（core）、渲染 Stage（modules）、管线框架（pipeline）都在 `rawlux` 内。
- **可回归**：金样本 DNG + 5 张一致性回归，输入 MAE ≤1e-5、full engine_mae ≤5e-5。
- **公开面干净**：无 `dng_*` 公开符号，文件/类/函数命名统一 snake_case + 领域语义。

## 包结构

```
rawlux/
  __init__.py          # 顶层 API（惰性导出）
  api.py               # Renderer / RenderIntent / RawInput / RawMetadata / CameraCalibration
  core/                # 数值与数据原语
    calibration.py     # DCP 解析 + 相机标定（camera_look/trim）
    color.py           # 色度学/矩阵/WB 正反解
    curves.py          # 影调曲线原语
    tone.py            # DNG 影调/曝光/HSM 底层（clean 名）
    warp.py            # WarpRectilinear
    io.py              # RAW 解码 / Stage3 输入
    lut.py / lut3d.py  # 3D LUT
    huesat.py / hsl.py / usercal.py / split_tone.py / enhance.py / skin.py
    resample.py        # Stage3 双程立方重采样
  modules/             # 可调渲染 Stage（16 个）
    exposure.py / white_balance.py / tone_map.py / huesat.py
    reshape.py / color_cal.py / calibration.py / hsl.py / split_tone.py
    skin.py / style.py / refine.py
  pipeline/
    context.py         # StageContext / StageParams / StageResult
    graph.py           # Stage / Pipeline / register_stage / STAGE_REGISTRY
    presets.py         # DEFAULT_STAGES / build_default_pipeline / pipeline_from_config
    base.py            # render_dcp_linear / camera cache
    intents.py         # EditIntent / apply_intents / parse_feedback
    scene_apply.py     # 场景预设应用
  presets/             # preview_fast / scenes / preview_baseline 等
  calibration_data/    # dng_camera_cache / z5ii_neutral_trim
```

## 快速开始

```python
import rawlux
from rawlux.api import Renderer, RenderIntent

renderer = Renderer("path/to/your.dcp")
# 默认线性渲染（DNG 对齐底座）
linear = renderer.render_file("DSC_5607.NEF")
# 带调整（走完整 Pipeline，返回线性 float32）
intent = RenderIntent(
    exposure=0.5,
    stages={"whitebalance": {"mode": "manual", "temp": 5500, "tint": 10},
            "hsl": {"enabled": True, "bands": [...]}},
)
out = renderer.render_file("DSC_5607.NEF", intent=intent)
# 低分辨率快速预览（uint8 gamma）
preview = renderer.render_preview("DSC_5607.NEF", half_size=True)
```

## Pipeline 直接使用

```python
from rawlux.pipeline.presets import build_default_pipeline, pipeline_from_config
from rawlux.core.calibration import load_dcp

prof = load_dcp("path/to/your.dcp")
pipe = build_default_pipeline(prof=prof)
rgb8 = pipe.run_file("DSC_5607.NEF", half_size=True)

cfg = {"stages": ["exposure", "whitebalance", "tone"],
       "params": {"exposure": {"mode": "auto"}}}
pipe2 = pipeline_from_config(cfg, prof=prof)
```

## 测试与一致性

```bash
# 全量单测（不含 e2e）
PYTHONPATH=. python -m pytest rawlab/tests -q -m 'not e2e'
# 金样本回归（数据存在时执行）
PYTHONPATH=. python -m pytest rawlab/tests -q -m regression
# DNG SDK 消融（全链路 MAE）
python rawlab/tools/dng_stage3_ablation.py
```

当前基线：**597 passed, 7 deselected**；regression **11 passed**；ablation full ≤8.1e-8。

## 迁移状态

- 实现代码全部在 `rawlux`；`rawlab/engine` 与 `rawlab/dcp` 已变成反向 shim。
- `grep -rIn "from rawlab\|import rawlab" rawlux` 应为空。
- 详细计划：`rawlab/docs/RAWLUX_NATIVE_MIGRATION_PLAN.md`。

## 相关文档

- 状态总览：`rawlab/docs/RAWLUX_STATUS_20260820.md`
- 重构方案：`rawlab/docs/RAWLUX_PACKAGE_REFACTOR.md`
- 完整计划：`rawlab/docs/RAWLAB_MASTER_PLAN.md`
