# RawLux 原生迁移计划 (rawlab 反向 shim) — v2（已过审修订）

目标: rawlux 高内聚、独立于 rawlab。实现代码全部落在 rawlux; rawlab 反向变成兼容 shim;
rawlux 源码零 `from rawlab`/`import rawlab`。rawlab/tests 的旧 import 全部继续可用。

## 引擎数据资产迁移表（backend 补齐：共 5 个数据文件，不只 z5ii）
| 数据文件 | 现路径 | 迁移到 | 改法（迁移后 _FILE 定位） |
|---|---|---|---|
| z5ii_neutral_trim.json | rawlab/engine/z5ii_neutral_trim.json | rawlux/calibration_data/ | `_CAL_FILE = Path(__file__).resolve().parents[1] / "calibration_data" / "z5ii_neutral_trim.json"` |
| target_offset.json | rawlab/engine/target_offset.json | rawlux/calibration_data/ | exposure 侧 `_CAL_FILE` 改 `parents[1]/calibration_data/target_offset.json` |
| lr_tone_curve.json | rawlab/engine/lr_tone_curve.json | rawlux/calibration_data/ | tone 侧 `_P(__file__).resolve().parent.parent` 改 `parents[1]/calibration_data/lr_tone_curve.json` |
| dng_camera_cache.json | rawlab/calibration/dng_camera_cache.json | rawlux/calibration_data/ | render_base 侧 `Path(__file__).resolve().parent.parent / "calibration" / ...` 改 `parents[2]/calibration_data/dng_camera_cache.json` |
| preview_fast.json | rawlab/presets/preview_fast.json | rawlux/presets/ | api.py `render_preview` 改 `Path(__file__).resolve().parents[1] / "presets" / "preview_fast.json"`；preview_baseline*.json 也迁到 rawlux/presets/ |

迁移后 rawlab 只剩 shim，不再承载这些数据；数据单一来源在 rawlux。

## 文件级映射 (rawlab -> rawlux)
| rawlab 实现 | rawlux 新家 |
|---|---|
| rawlab/dcp.py | rawlux/core/calibration.py (DCP 部分) |
| rawlab/engine/calibration.py | rawlux/core/calibration.py (camera look/trim 部分) |
| rawlab/engine/curves.py | rawlux/core/curves.py |
| rawlab/engine/color.py | rawlux/core/color.py |
| rawlab/engine/dng_render.py | rawlux/core/tone.py |
| rawlab/engine/dng_warp.py | rawlux/core/warp.py |
| rawlab/engine/decode.py | rawlux/core/io.py |
| rawlab/engine/lut3d.py | rawlux/core/lut3d.py |
| rawlab/engine/huesat.py | rawlux/core/huesat.py |
| rawlab/engine/hsl.py | rawlux/core/hsl.py |
| rawlab/engine/usercal.py | rawlux/core/usercal.py |
| rawlab/engine/split_tone.py | rawlux/core/split_tone.py |
| rawlab/engine/enhance.py | rawlux/core/enhance.py |
| rawlab/engine/skin.py | rawlux/core/skin.py |
| rawlab/engine/core.py | rawlux/pipeline/graph.py (Stage/registry/domains/Pipeline) + context.py (StageContext/StageParams/StageResult) |
| rawlab/engine/pipeline.py | rawlux/pipeline/presets.py |
| rawlab/engine/render_base.py | rawlux/pipeline/base.py |
| rawlab/engine/api.py | rawlux/api.py |
| rawlab/engine/intents.py | rawlux/pipeline/intents.py |
| rawlab/engine/stages/*.py | rawlux/modules/*.py |
| rawlab/engine/{analyze,retouch,scene_apply,scenes}.py | 保留 rawlab 应用层 (retouch 依赖 vision_report, 不进 rawlux) |

## shim 旧名→clean 名映射契约（强制：不能只 `from rawlux.<new> import *`）
rawlab 旧公开 API 含 dng_* 名，rawlux 只暴露 clean 名；每个 shim 必须显式重建旧名，否则旧 import 破坏。
| rawlab 旧名 | rawlux clean 名 |
|---|---|
| dng_exposure_ramp / dng_table_interp / dng_srgb_encode / dng_srgb_decode / dng_build_tonetable | exposure_ramp / table_interp / srgb_encode / srgb_decode / build_tonetable |
| apply_dng_rgb_tone / load_dng_tone_table / apply_dng_hue_sat_map | apply_rgb_tone / load_tone_table / apply_hue_sat_map |
| tone_table_interp | tone_table_interp（本身 clean） |
| dng_temperature_from_xy / dng_camera_white | temperature_from_xy / camera_white |
| dng_cam_to_prophoto_matrix / dng_prophoto_to_linear_srgb_matrix / dng_linear_prophoto_to_srgb | cam_to_prophoto_matrix / prophoto_to_linear_srgb_matrix / linear_prophoto_to_srgb |
| dng_warp_rectilinear | warp_rectilinear |
| decode_dng_stage3_like | decode_stage3_like |
| _read_dng_opcode_list / _apply_dng_vignette | _read_opcode_list / _apply_vignette（私有名） |

shim 写法示例（rawlab/engine/dng_render.py）：
```python
from rawlux.core.tone import (exposure_ramp, srgb_encode, ...)  # clean 名
dng_exposure_ramp = exposure_ramp      # 显式重建旧名
dng_srgb_encode = srgb_encode
...
__all__ = ["dng_exposure_ramp", "dng_srgb_encode", ..., "tone_table_interp", ...]  # 保持旧 __all__
```
每切一个 shim 跑 `python -c "from rawlab.engine.<x> import <旧名>"` 确认不 ImportError。

## 阶段（纪律：先写 rawlux 原生实现、后切 rawlab shim，两步分开；每步 commit + pytest 子集）
A 叶子层（切 shim 唯一在 A4.5，且必须等 rawlux.core.__init__ 不再触发任何 rawlab 引用）:
  A1 只写 rawlux/core/calibration.py 原生（dcp+calibration 合并 + 上表数据文件）——【不切】rawlab/dcp.py、rawlab/engine/calibration.py
  A2 只写 rawlux/core/curves.py 原生
  A3 只写 rawlux/core/color.py 原生（rawlab.dcp 常量引用改 rawlux.core.calibration；dng_* 函数改 clean 名）
  A4 只写 rawlux/core/{tone,warp,io,lut3d}.py 原生（旧名→clean 名见上表）
  A4.5【切 shim 唯一入口】确认 rawlux.core 全原生、无 rawlab 引用后，逐个切 rawlab/dcp.py、rawlab/engine/{calibration,curves,color,dng_render,dng_warp,decode,lut3d}.py 为反向 shim；每切一个跑对应 pytest + 旧名 import 冒烟
  A5 huesat/hsl/usercal/split_tone/enhance/skin -> rawlux/core/*（同样先原生后切）
B 框架层:
  B0 改写 rawlab/engine/__init__.py：模块加载即 `from .core import ...` + `from .pipeline import ...`，core/pipeline 变 shim 后同步改为 `from .core import *` + `from .pipeline import *`，`__all__` 保持不变
  B1 core.py -> rawlux/pipeline/{graph,context}.py；rawlab/engine/core.py shim
  B2 pipeline.py -> rawlux/pipeline/presets.py；shim
  B3 stages -> rawlux/modules 原生；rawlab/engine/stages/* shims；rawlab/engine/stages/__init__.py 改为 `import rawlux.modules` 触发注册，并断言旧 `STAGE_REGISTRY` 的 key->class `is` 恒等 + 默认链合成图逐位一致
C 上层:
  C1 render_base -> rawlux/pipeline/base.py（dng_camera_cache 用 rawlux/calibration_data）
  C2 api -> rawlux/api.py（render_preview 定位 rawlux/presets/preview_fast.json；迁移后 rawlux/__init__.py 可恢复 eager `from . import api`，或保留惰性并加注释）
  C3 intents -> rawlux/pipeline/intents.py
D 验收:
  - grep -rIn "from rawlab|import rawlab" rawlux -> 0
  - PYTHONPATH=. python -m pytest rawlab/tests -q -m 'not e2e' -> >=597 passed
  - regression 11 passed；ablation 5 张 ≤5e-5；rawlux 全包 import；rawlab.engine 旧 import 全可用
  - rawlux 公开面零 dng；git commit 每个阶段
  - 【原生冒烟】新增 1 用例：`from rawlux.pipeline.graph import Pipeline, register_stage`、`from rawlux.modules import ...` 直接构建默认链跑合成图，输出与 rawlab 路径一致（证明 rawlux 自身可用，非经 shim）

## 风险
- 循环依赖：stages __init__ 只在显式 import 时触发注册；rawlab.engine.__init__ 保持先 import shim；切 shim 严格限定在 A4.5（吸取 A1 若提前切会触发 rawlab.dcp→rawlux→rawlab.color→rawlab.dcp 环的教训）。
- `is` 身份：rawlab shim 与 rawlux 同一对象，旧测试的 is 断言仍成立。
- dcp.py 常量被 color.py 使用：迁移后 rawlab.dcp 也要从 rawlux.core.calibration 导出同一对象。
- vision_report 依赖：retouch 留 rawlab 应用层，不进 rawlux。
