# RawLux 渲染引擎功能开发计划书

版本：v0.1
状态：功能开发阶段
前置条件：RAW 解码、白平衡、DCP 应用已与线性 DNG 对齐，基础色彩正确。

## 1. 目标
在已正确还原线性场景参考色彩的基础上，构建 RawLux 自研渲染引擎的完整调整功能，
使引擎具备独立修图能力。不拟合 Lightroom，不复刻 Adobe，以“可测量、可控制、可回归”为原则。

## 2. 范围
### 2.1 本期实现
| 模块 | 说明 | 优先级 |
|---|---|---|
| 曝光 EV | 线性空间曝光补偿 | P0 |
| 白平衡 | 手动色温/色调调整 | P0 |
| 曲线 | RGB 曲线/亮度曲线 | P0 |
| 高光/阴影 | 高光压缩、阴影提升 | P0 |
| HSL | 色相、饱和度、明度分色调整 | P1 |
| 色彩校准 | 全局色彩矩阵微调 | P1 |
| 色调分离 | 高光/阴影独立色相饱和度 | P1 |
| 清晰度 | 局部对比度增强 | P2 |
| 去朦胧 | 全局通透度调整 | P2 |
| 锐化 | 输出前细节增强 | P2 |
| 降噪 | 亮度/彩色降噪 | P2 |

### 2.2 暂不实现
局部调整、镜头校正、液化修复裁剪、视频处理、实时 GPU 渲染。

## 3. 架构原则
模块化、参数化、可测量、顺序固定、Python 优先并预留 C++ 扩展点。

## 4. 渲染管线顺序
RAW 解码 -> 白平衡 -> DCP -> 曝光 EV -> 高光/阴影 -> 曲线 -> 色彩校准 -> HSL
-> 色调分离 -> 清晰度/去朦胧 -> 降噪 -> 锐化 -> 输出。

## 5. 开发阶段
- 阶段 A: 管线骨架与核心影调 (P0)
- 阶段 B: 色彩调整模块 (P1)
- 阶段 C: 细节与质感 (P2)
- 阶段 D: 集成与性能优化

## 6. 风险与对策
见计划书正文。

## 7. 非目标
不追求与 Lightroom 参数一一对应、不拟合 Adobe 默认渲染、不实现局部选区、
不在本阶段做自动化优化/LLM 集成。

## 8. 里程碑
M1 阶段 A，M2 阶段 B，M3 阶段 C，M4 阶段 D。

## 9. 交付物
Python 包、参数 Schema、示例渲染脚本、回归测试集、开发文档。

## 10. 后续规划
金样本集、视觉测量、Harness 自动回归、clean-room 重写、C++ 迁移。
能

## 11. P0/P1 功能状态（Phase 1 集成后）

| 功能 | 优先级 | 状态 | 参数入口 (stage.param) |
|---|---|---|---|
| 曝光 EV | P0 | ✅ | exposure.mode |
| 白平衡 temp/tint | P0 | ✅ | whitebalance.mode=manual + temp/tint |
| 曲线 (RGB/亮度/分通道) | P0 | ✅ | tone.user_curve |
| 高光/阴影/白/黑四键 | P0 | ✅ | tone.highlights/shadows/whites/blacks |
| HSL 分色 | P1 | ✅ | hsl.enabled + bands |
| 色彩校准 | P1 | ✅ | calibration.enabled + shadow_tint/red_hue/.../blue_sat |
| 色调分离 | P1 | ✅ | split_tone.enabled + shadows/highlights hue/sat/balance/strength |
| 清晰度 | P2 | 🔶 | clarity.enabled + strength (intents 入口) |
| 去朦胧 | P2 | 🔶 | dehaze.enabled + strength (intents 入口) |
| 锐化 | P2 | 🔶 | refine.sharpen |
| 降噪 | P2 | 🔶 | refine.chroma_denoise |
