# rawlab/engine —— 插件化渲染引擎

六阶段管线(2026-08 重构定稿),每阶段一个插件,由 Pipeline 统一调度:

```
NEF → rawpy 解码(AHD, 相机RGB线性)           ← 采集层, 非插件
   → [1] exposure     曝光矫正    linear_cam → linear_cam
   → [2] whitebalance 色彩矫正/WB  linear_cam → linear_rgb
   → [3] tone         影调重塑    linear_rgb → gamma_rgb
   → [4] colorcal     色彩校准    gamma_rgb → gamma_rgb
   → [5] stylize      风格化(LUT) gamma_rgb → gamma_rgb
   → [6] refine       精修        gamma_rgb → gamma_rgb
   → 8bit sRGB JPEG
```

## 插件协议

```python
@register_stage("exposure", order=1, domain_in=..., domain_out=...)
class ExposureStage(Stage):
    name = "exposure"
    def default_params(self) -> dict: ...
    def process(self, ctx: StageContext) -> None: ...
```

- **注册即接入**:`engine/stages/` 下新文件 import 即注册;Pipeline 按 order 编排。
- **域契约**:每级声明输入/输出色彩域,Pipeline 自动校验,域错位直接报错
  (旧管线教训:gamma 域 LUT 拿线性域输入、测量域≠输出域)。
- **参数**:实例默认值 ← Pipeline params ← JSON 配置,三层覆盖;`wants(ctx)` 可整级关闭。
- **状态交换**:跨级只走 `ctx.state`(ev / wb / 饱和掩码等),插件间不互相 import。
- **探针**:`--probe` 每级中间图落盘,肉眼可查每一级干了什么。

## 色彩域

| 域 | 含义 | 值域 |
|---|---|---|
| `linear_cam` | 相机原始 RGB(未 WB) | float32 ≥0 |
| `linear_rgb` | 线性 sRGB(D65) | float32,可 >1(高光余量) |
| `gamma_rgb` | sRGB gamma 编码 | float32 0..1 |

## 关键修复(相对旧 render.py)

1. **曝光**:线性域一步定标。用 1/4 降采样探针在**影调级消费的域**
   (WB×FM×Bradford×sRGB 之后)量 log2 中位,锚点 = 令影调曲线输出 0.45 的线性输入
   (curve_anchor_target, 换曲线自动跟随)。高光保护 = p98 不越白电平(裁切预算 2%)。
   替代:EXPOSURE_CAL_TABLE 场景拟合表 + 两轮探测迭代。
2. **白平衡**:AsShot WB × ForwardMatrix(CCT 插值,本机 FM2==FM1 恒等)
   → XYZ D50 → Bradford → sRGB;传感器饱和像素(增益前 ≥0.985 且近中性)
   中性化渲染(防暖高光)。替代:WB_CAL=[0.90,1,1] 全局补丁。
3. **影调**:单一亮度曲线(RGB 同曲线,中性天然保持),filmic 肩部软压缩;
   DCP ProfileToneCurve 作可选 preset(acr_standard)。
4. **色彩校准**:中性轴按亮度分段校正曲线(每机标定一次,只动低色度区)+
   饱和度/自然饱和度/色相/肤色保护。替代:+12 HSV 饱和补丁。
5. **DCP 解析修正**:0xC6FC=125 点影调曲线、0xC726=HueSatMap(90×16×16×3,
   待接入)、0xC7A5=BaselineExposureOffset(-0.15EV,已计入曝光)。

## 配置(JSON,agent 可直接改)

```json
{
  "stages": ["exposure","whitebalance","tone","colorcal","stylize","refine"],
  "params": {
    "exposure":  {"mode": "auto"},
    "whitebalance": {"mode": "as_shot"},
    "tone":      {"profile_curve": false, "contrast": 0.12},
    "stylize":   {"lut": null, "lut_path": "velvia.cube", "lut_strength": 0.8}
  },
  "output": {"quality": 95}
}
```

`mode` 枚举:exposure `auto|off|<ev数值>`;whitebalance `as_shot|auto|off|<[r,g,b]系数>`。
预设: `rawlab/presets/{neutral,acr_standard,vivid}.json`。

## 每机标定

1. `python rawlab/tools/fit_neutral_trim.py --n_fit 30 --n_val 10`
   → 拟合中性轴校正曲线写入 `engine/z5ii_neutral_trim.json`(拟合集留出验证)。
2. 曝光/影调如需对齐特定观感,调 `exposure.target_offset` / `tone.brightness`
   (每机单个常量,非场景表)。

## 验收

- L1 客观:`python rawlab/tools/verify_l1.py --mode engine --n 100`
  (亮度锚定/高光裁切/暗部裁切/分层中性)
- L2 预览对照:`python rawlab/tools/verify_engine.py --mode engine --n 100`
  (d_med / d_a / d_b / 中性区,相机预览仅参考)

## 性能(2020×3032 half_size)

decode AHD 0.84s + exposure 0.46s + wb 0.15s + tone 0.59s + colorcal ~1s(默认直通 0)
+ refine 0.78s ≈ 3.9s;全尺寸约 4 倍。colorcal 默认参数直通跳过。
