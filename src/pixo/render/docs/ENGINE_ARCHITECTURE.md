# pixo.render 渲染引擎架构 v0.1

代号: **pixo.render**
含义: Raw（原始影像）+ Lux（光）。代码层统一使用 pixo.render。

## 设计目标
1. NEF/DNG + DCP 底座渲染，输出与 DNG SDK 对齐。
2. 调整层可插拔：曝光、WB、HSL、校准、清晰度等后续逐步加回。
3. Python 现在跑通，接口稳定后 C++ 重写不破坏上层。
4. clean-room 合规：DNG SDK 只作黑盒 oracle。

## 分层
```
apps/tools/presets
─────────────────────────────
pixo.render Engine API
  Renderer.render(raw, calibration, intent) -> Image
    │
    ├─ Input Layer
    │   RawDecoder -> CameraRGB + RawMetadata
    │
    ├─ Calibration Layer
    │   DcpProfile + CameraLensCache -> CameraCalibration
    │
    ├─ Core Render Graph
    │   Base Pipeline (DNG-compatible)
    │   Adjustment Stages (future style)
    │
    └─ Output Layer
        Linear RGB -> Encode -> TIFF/JPEG
```

## 模块映射
| 层 | 现有/目标模块 |
|---|---|
| Input | render/core/io.py |
| Calibration | render/core/calibration.py, render/calibration_data/dng_camera_cache.json |
| Color science | render/core/color.py |
| DNG-compatible primitives | render/core/tone.py, dng_warp.py |
| Base renderer | render/pipeline/base.py |
| Stage framework | render/pipeline/graph.py, stages/ |
| Tool CLI | render/tools/render_dcp.py |

## 核心接口标准 (v0.1)
```python
# 输入: 解码后统一为 CameraRGB
@dataclass
class RawInput:
    camera_rgb: np.ndarray        # (H,W,3) float32, linear camera RGB
    metadata: RawMetadata         # wb, size, lens, white/black, opcodes

# 标定: DCP + camera/lens cache 合并
class CameraCalibration:
    profile: DcpProfile
    camera_entry: dict            # white_level, baseline, opcodes

# 渲染意图: 底座 + 可选调整
class RenderIntent:
    base: BaseIntent              # as_shot, exposure, tone
    stages: dict[str, dict]       # 后续风格化参数

# 引擎主接口
class Renderer:
    def render(self, raw: RawInput, calib: CameraCalibration,
               intent: RenderIntent) -> np.ndarray: ...
    # 返回 float32 线性 sRGB [0,1]
```

## 规则
- 引擎内部只处理 float32 线性 RGB；
- 所有 Stage 输入/输出域显式声明；
- 输出编码是最后一层，不混在 Stage 里；
- DNG 对齐模块只依赖公开规范 + oracle，不依赖 SDK；
- 性能热点集中在 Input/Color/Stage，方便后续 C++ 下沉。

## 未来扩展点
- Lens correction 注册表
- GPU/numpy JIT backend
- Local adjustment masks
- Style presets
- C++ backend 与 Python API 双实现

## 迁移计划
1. 等 M1 clean-room 子代理完成；
2. 按 M2-M5 完成 clean-room；
3. 建立 `render/api.py` 暴露 Renderer/RawInput/CameraCalibration/RenderIntent；
4. 让 render_dcp.py 和 tests 改走 api；
5. 再考虑代码目录重命名/发布。
