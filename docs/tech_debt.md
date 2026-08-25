# Pixo Tech Debt / 技术债清单

> 详细许可与发布阻断项见 [`PIXO_LICENSE_REVIEW.md`](PIXO_LICENSE_REVIEW.md)。

## 关键技术债

1. **YOLOE AGPL-3.0 发布阻断**：
   - 当前仓库允许 AGPL 隔离使用（仅 `pixo/vision/segmenters/yoloe.py` 直接依赖 torch/ultralytics）。
   - 对外发布前需替换模型、企业授权，或从发布分支移除 AGPL 运行时依赖。

2. **DNG SDK clean-room 复审**：
   - 部分实现注释仍引用 Adobe DNG SDK；发布前需确认 clean-room 或重写。

3. **第三方许可登记**：
   - `model_licenses.json` 仍需同步更新为当前路径；
   - 缺少统一 `THIRD_PARTY_NOTICES.md`。

4. **未声明可选依赖**：
   - `scipy`、`PyYAML` 等为可选/间接依赖，应在安装说明中明确。

5. **目录/路径历史残留**：
   - 历史文档中保留旧 `render/`、`rawlab`、`RawFlow` 路径说明，仅作迁移记录。

6. **命名空间迁移兼容层**（已解决）：
   - `src/render/` shim 已于 859082f 移除，统一为 `pixo.*`。

7. **感知质量门禁缺失**：
   - 金样本门禁仅防像素漂移（±1/255），不衡量与相机原图的观感差距；
     建议将 `scripts/ab_vs_camera_thumb.py` 的 ΔE/裁切预算纳入 gate。

8. **WB 分桶标定与二维曝光分键**：
   - 部分场景残余偏色（如 DSC_0355 da−12/db+14.5）需 warmth_curve 数据拟合；
   - 暗室内与夜景 med 几乎相同但相机意图相反，标定表建议升级 (med, wb_B) 二维分键。
