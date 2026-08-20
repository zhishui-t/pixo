# RawLux 渲染引擎完整实施计划 v1.0

## 0. 总体目标
在 RawLux 底座（NEF/DNG + DCP 与 DNG 线性渲染对齐）之上，构建
“不拟合 Lightroom、不复刻 Adobe、可测量可回归”的独立修图引擎。

## 1. 与现有架构对照结论
### 可采纳的用户计划
- 模块范围与优先级（P0 曝光/白平衡/曲线/高光阴影，P1 HSL/校准/色调分离，P2 细节）✅
- 暂不实现局部调整/镜头校正/视频/GPU ✅
- 参数化、模块化、顺序固定 ✅
- 非目标：不追求与 LR 参数一一对应、不拟合 Adobe ✅

### 需调整
1. **DNG clean-room 未完成前不开功能**：M1-M5 完成后才进入功能阶段。
2. **管线顺序按现有 Stage 架构微调**：
   - base: decode -> whitebalance(as-shot) -> DCP -> exposure -> tone(DCP)
   - adjustments: EV -> highlights/shadows -> curves -> calibration -> HSL -> split toning -> clarity/dehaze -> denoise -> sharpen
3. **HSL 与 DCP HueSatMap/LookTable 分离**：HSL 在 DCP base 之后独立执行。
4. **性能门槛**：当前 NEF 底座 ~10.8s；功能阶段全程监控，最终目标全分辨率 < 5s，hotspot 允许 Numba/C++。

## 2. 阶段与任务
### Phase 0: RawLux 底座稳定
- T0.1 M1 clean-room `dng_render.py`（已交回，待主代理验收）
- T0.2 M2 `dng_warp.py`
- T0.3 M3 `color.py` DNG temperature 插值
- T0.4 M4 `dng_stage3_replicate.py` 重采样
- T0.5 M5 `decode.py` opcode 解析
- T0.6 RawLux API/架构文档锁定，conformance 全绿

### Phase 1: 管线骨架与核心影调 P0
- T1.1 `BaseAdjustment` 抽象接口 + `RenderPipeline` 顺序调度
- T1.2 曝光 EV（线性乘系数，基线=0）
- T1.3 手动白平衡（色温/色调，Bradford）
- T1.4 RGB 曲线 / 亮度曲线（LUT 加速，白→白）
- T1.5 高光/阴影（保色压缩，避免高光变灰/偏红）

### Phase 2: 色彩调整 P1
- T2.1 HSL 八色段（局部掩码，边界 C1）
- T2.2 色彩校准（全局矩阵/色相饱和微调）
- T2.3 色调分离（高光/阴影独立 hue/sat/balance）

### Phase 3: 细节与质感 P2
- T3.1 清晰度（中频局部对比度，控 halo）
- T3.2 去朦胧（全局对比度/饱和度补偿）
- T3.3 降噪（亮度/彩色）
- T3.4 锐化（输出前）

### Phase 4: 集成与性能
- T4.1 参数 JSON/YAML Schema + 序列化
- T4.2 批量渲染脚本
- T4.3 低分辨率快速预览
- T4.4 profiling 与热点优化
- T4.5 回归 Harness + 金样本集

## 3. 子代理执行协议
- 预设：**锚定标准·满血子代理**
- v4-flash：锚定验收标准/oracle/测试命令，不写核心代码；
- 满血子代理：按锚定包实现；
- 主代理：每任务完成后验收，验收通过才进入下一任务。

## 4. 每任务验收基线
1. 默认参数输出 == base（逐位或 ≤1e-6）；
2. 灰阶 ramp 单调，黑白点保持；
3. 中性灰不偏色；高光/肤色不硬裁；
4. 5 张 DNG full scaled MAE ≤ 5e-5；
5. `pytest rawlab/tests -q -m 'not e2e'` 全绿；
6. LR 十张指标不因“参数全 0”而变化。

## 5. 里程碑
- M0: T0.1-T0.6 完成，RawLux base 冻结。
- M1: T1.1-T1.5 完成，P0 控件可用。
- M2: T2.1-T2.3 完成，P1 色彩可用。
- M3: T3.1-T3.4 完成，P2 细节可用。
- M4: T4.1-T4.5 完成，批量稳定。

## 6. 交付物
- RawLux Python 包与统一 API
- 参数 Schema（JSON）
- 示例渲染脚本
- 基础回归测试集
- 开发文档：架构/模块/参数范围/管线顺序
- 金样本集与自动回归指标
- Clean-room 交付记录

## 7. 非目标
- 不追求与 Lightroom 参数一一对应
- 不拟合 Adobe 默认渲染
- 不实现局部选区
- 不在本阶段做 LLM 自动优化
- 不实现实时 GPU 渲染

## 8. 风险与对策
- HSL 与 HueSatMap 冲突 → HSL 在 DCP 后独立；可配置关闭 DCP LookTable
- 高光压缩引入偏色/变灰 → 保色压缩 + 高光 a/b 单独测量
- 降噪/锐化损伤细节 → 参数保守，分区域处理
- 参数组合爆炸 → 固定顺序 + 参数范围约束
- Python 性能不足 → 先向量化，再 Numba/C++ 热点
- 合规风险 → Phase 0 clean-room 必须先行
