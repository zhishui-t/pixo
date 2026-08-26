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
   - 更新（t66）：执行位已由 `loop._COLOR_PARAM_ALIASES` 桥接 colorcal，
     VibranceStage 占位类改为显式废弃声明（强制调用抛 NotImplementedError
     指引迁移），转发壳 modules/vibrance.py 已删除，无残留引用。

9. **0355 高光 cap**（已清偿 2026-08-25）：
   - 高光预算哨兵 ev≤log2((1-τ)/p99)，highlight_budget=0.02（相机实测 1.74%+余量）；
     拟合目标中位 L→均值 L。验收：clip_hi 3.68→2.29%（≤2.5）、|dL| 8.94→1.0（≤4）、色度≈0。

10. **跨包知识边须同组发布**：
    - 含跨包边的知识包必须同组提交、同组发布（见 `configs/knowledge/README.md`
      发布约定）；新增跨包边须在所在包 JSON 顶部声明 `_requires`，
      单包先行变更会制造悬空引用。

10. **色彩规则执行位占位**：
    - 色彩规则决策键（vibrance/saturation.adjust）已通，下游 VibranceStage 为占位，
      参数暂不产生渲染差异；实装或映射至 huesat 待排期。

11. **评分器权重部署**：
    - aesthetic_scorer.pt 就位后 make_default_scorer 自动切真模型（对照
      model_licenses.json 许可）；composition/overall 维度即可供 P2 规则消费。
    - 附注(t52 连锁,2026-08-25)：权重已部署(HF rsinema/aesthetic-scorer,MIT,
      resources/models/aesthetic/)。真模型对合成/低纹理图像系统性低分——
      实测噪声合成图 confidence≈0.52<0.6 阈值致 batch 推荐沉默（开发5 已在
      测试注入 FixedAestheticScorer 规避）。**分数分布标定须覆盖"合成/低纹理"
      域**（与 docs/metrics/proxy_distribution.md 同法补该域分位），否则依赖
      美学分的选片推荐与终止判定在此类输入下会系统性不触发。标定前生产语义：
      低分≠废片，仅是域外输入。
        - **已清偿(t98,合成/低纹理域深化)**：合成域分位表已入档
          docs/metrics/scorer_distribution.md（五大类探针+分位汇总+退化阶梯）。
          **关键结论**：同场景退化阶梯打分非单调、Spearman ρ≈0.03——域内相对
          排名自洽性不足，**不可作合成图质检硬结论**；batch synthetic 池改为
          隔离+池内排序仅供人审参考（include_synthetic 语义扩展见 batch.py
          MockAgentSelector.select），绝对分仍禁跨域比较。


12. **公式守卫日落条款**：
    - 引擎原生 AND/between 落地后，新规则改用原生 condition，存量公式守卫规则
      （clarity_flat 等）择机迁移（裁定见 t40 复审记录）。
