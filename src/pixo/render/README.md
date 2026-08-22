# pixo.render

pixo.render 是一个独立、高内聚的 RAW 渲染引擎包：输入 NEF/DNG + DCP，输出与 DNG SDK 对齐的渲染结果，并在此基础上提供可测量的修图调整能力。

## 设计目标

- **独立**：`pixo.render` 完全独立，源码零 `from rawlab` / `import rawlab`；`rawlab` 已删除。
- **高内聚**：核心引擎（core）、渲染 Stage（modules）、管线框架（pipeline）都在 `render` 内。
- **可回归**：金样本 DNG + 5 张一致性回归，输入 MAE ≤1e-5、full engine_mae ≤5e-5。
- **公开面干净**：无 `dng_*` 公开符号，文件/类/函数命名统一 snake_case + 领域语义。

## 包结构

```
src/pixo/render/
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
  profiles/            # DCP 相机配置文件
  web/                 # 8-bit/16-bit 编码与会话缓存
  tools/               # bench_preview / bench_pipeline
  bench/               # 性能基线 JSON
  docs/                # 设计/需求/规格/测试文档
  tests/               # 单元测试
  calibration_data/    # dng_camera_cache / z5ii_neutral_trim
```

## 快速开始

```python
import pixo.render
from pixo.render.api import Renderer, RenderIntent

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
from pixo.render.pipeline.presets import build_default_pipeline, pipeline_from_config
from pixo.render.core.calibration import load_dcp

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
PYTHONPATH=. python -m pytest src/render/tests -q -m 'not e2e'
# 金样本回归（数据存在时执行）
PYTHONPATH=. python -m pytest src/render/tests -q -m regression
# DNG SDK 消融（全链路 MAE）
python src/pixo/render/tools/dng_stage3_ablation.py
```

当前基线：**557 passed, 1 skipped, 1 xfailed**（`-m "not e2e"`）；
P1-1 迁移后含命名空间双入口验证的全量基线为 **586 passed, 1 skipped, 1 xfailed**。

## 一键构建与测试（可复现性）

仓库提供 `render
un_all_tests.bat`，一条命令完成：

1. Native CMake 构建（`src/pixo/render/native/build.bat`）
2. C++ 单元测试（`src/pixo/render/native/run_tests.bat`）
3. Python 全量单元测试（`src/render/tests`，`-m 'not e2e'`；render 为兼容 shim）
4. 功能门禁 gate 测试（`pytest src/render/tests/gate -m gate`，失败即阻塞）
5. `bench_preview` 冷启动（`--warmup 0`）
6. `bench_preview` 热启动（`--warmup 1 --runs 2`）

```bat
render\run_all_tests.bat
```

- 脚本会自动把仓库根目录加入 `PYTHONPATH`。
- 构建、Python 全量测试或 gate 任一步失败会立即以非零退出码结束；**后续任何修改必须通过 gate 才能算完成**。
- 脚本末尾会输出 `PASS/FAIL 汇总`。
- bench 步骤属于性能/质量验收：未达门禁时打印 `[WARN]`，不会阻断构建与测试流程。
- 基准 JSON 输出到 `src/pixo/render/bench/preview_cold_baseline.json` 与 `src/pixo/render/bench/preview_hot_baseline.json`。
- 若本机没有 `bench_preview.py` 内置的默认 RAW 路径，可设置环境变量 `RAW_PATH` 指向你的 NEF/DNG 文件：
  ```bat
  set RAW_PATH=D:\photos\test.dng
  render\run_all_tests.bat
  ```

## 迁移状态

- 实现代码全部在 `render`；`rawlab` 已删除。
- `grep -rIn "from rawlab\|import rawlab" render` 应为空。
- 文档全部在 `render/docs/`。

## 相关文档

- 状态总览：`render/docs/PIXO_RENDER_STATUS_20260820.md`
- 重构方案：`render/docs/PIXO_RENDER_PACKAGE_REFACTOR.md`
- 完整计划：`render/docs/RAWLAB_MASTER_PLAN.md`
