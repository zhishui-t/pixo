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
   - 更新（2026-08-25 组合批）：7 维美学评分器已接线（batch 选片工厂 +
     loop 美学维度）；门禁口径扩展（ΔE/美学阈值纳入 gate）待做。

8. **WB 分桶标定与二维曝光分键**（已清偿，2026-08-25 组合批）：
   - warmth_curve 已拟合并落库：`configs/calibration/warmth_curve.json`
     （5 结点）；`WhiteBalanceStage.warm_cal_file` 缺省加载，缺失/非法回退
     内置斜率模型。DSC_0355 da/db 收敛至 ±6 门禁内（−12.25/+14.41 → +1.07/−3.78），
     对照 DSC_5236 不劣化。
   - 曝光标定表已升级 `(med_log2, wb_B)` 二维分键。

9. **0355 高光 cap**（已清偿 2026-08-25）：
   - 高光预算哨兵 ev≤log2((1-τ)/p99)，highlight_budget=0.02（相机实测 1.74%+余量）；
     拟合目标中位 L→均值 L。验收：clip_hi 3.68→2.29%（≤2.5）、|dL| 8.94→1.0（≤4）、色度≈0。

10. **跨包知识边须同组发布**：
    - 含跨包边的知识包必须同组提交、同组发布（见 `configs/knowledge/README.md`
      发布约定）；新增跨包边须在所在包 JSON 顶部声明 `_requires`，
      单包先行变更会制造悬空引用。
