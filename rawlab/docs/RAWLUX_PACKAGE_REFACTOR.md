# RawLux 包重构计划 v1.0

## 目标
把引擎代码从 rawlab/engine 迁移为独立包 rawlux/，包内按 core/modules/pipeline 组织。
去除文件名与公共 API 中的 dng 标识，文件命名统一 snake_case、按领域命名。

## 前置条件
- M1-M5 clean-room 全部完成并验收；
- 431 项测试通过；
- M5 子代理结束后启动本重构。

## 目标结构
```
rawlux/
  __init__.py
  api.py                  # Renderer/RenderIntent/RawInput/RawMetadata/CameraCalibration
  core/
    __init__.py
    io.py                 # 原 engine/decode.py: decode_raw / stage3 输入
    color.py              # 原 engine/color.py: 色度学/矩阵
    calibration.py        # 原 rawlab/dcp.py + dng_camera_cache 合并入口
    curves.py             # 原 engine/curves.py
    tone.py               # 原 engine/dng_render.py 去 dng 命名
    warp.py               # 原 engine/dng_warp.py 去 dng 命名
  modules/
    __init__.py
    exposure.py
    white_balance.py
    huesat.py
    tone_map.py
    clarity.py
    dehaze.py
    denoise.py
    sharpen.py
    vibrance.py
    color_cal.py
    style.py
    skin.py
    refine.py
  pipeline/
    __init__.py
    context.py            # StageContext
    graph.py              # Pipeline/Stage 框架
    base.py               # render_base.py
    presets.py            # 参数 Schema/预设
  calibration_data/
    dng_camera_cache.json
  tools/
    render.py
    conformance.py        # 原 dng_stage3_replicate 相关, 只作工具不进入 core
```

## 命名规范
- 文件名: snake_case，按职责命名，不用 dng/ref/sdk 前缀。
- 类名: PascalCase；函数/变量: snake_case。
- 公共 API 只从 rawlux.api 导出；内部模块不做跨层 import。
- 禁止 `dng_xxx` 文件名与公开符号；实现注释中允许“与 DNG 规范对齐”说明。

## 迁移策略（小步，避免大爆炸）
1. 创建 rawlux/ 目录与 __init__.py，不立即删 rawlab/engine。
2. 先迁 core: io/color/calibration/curves/tone/warp，逐文件用 `import` 兼容层回指 rawlab.engine。
3. 迁 pipeline: context/graph/base。
4. 迁 modules: 逐 stage 迁移，保持原 Stage 名注册兼容。
5. 更新 tools 与 tests import。
6. 全量测试 + 5 张 DNG conformance + NEF render 验证。
7. 最后删除 rawlab/engine 旧文件（保留 rawlab 应用层）。

## 兼容要求
- 旧 import `rawlab.engine.xxx` 在新包落成前仍可用；
- `rawlab/tools/dng_linear_probe.py` 等诊断工具暂时不删除，后续统一迁到 rawlux.tools.conformance。

## 验收
- `python -m pytest rawlab/tests -q -m 'not e2e'` 431 passed；
- `python rawlux/tools/render.py --raw <NEF> --dcp <DCP> --out <jpg>` 输出正常；
- 5 张 DNG full engine_mae ≤ 5e-5；
- 代码中不再出现 `dng_render.py / dng_warp.py / dng_stage3_replicate.py` 文件名或公开类名。
