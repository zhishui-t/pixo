# Pixo 自研渲染管线 · 阶段二详细设计（M-D1 可微标定首跑 + G-5 收口）

> 状态：详细设计 v1（2026-09-04，队长架构师）。
> 上游：路线图 §4、阶段一终审（.artifacts/stage1_qa_verdict.md，GO）、G-5 遗留项。
> 铁律：**运行时零变化**——本阶段交付物只允许 `scripts/` + `configs/*.json`，`src/pixo/render` 零改动（QA 审计 git diff 红线）。

---

## 0. 目标

标定期把渲染管线写成可微函数，语料端到端联合优化 θ；产出仍是**确定性查找表/曲线/系数**（写回现有 configs 格式）。同时收口 G-5（RP-CCM 门槛线 + 分组拟合）。

```
θ = { warmth_knots[5], exposure_table[2D 12n], neutral_curves, rp_ccm_coeff[18], skin_ellipse[5] }
loss = Σ_corpora proxy_ΔE(render_diff(raw, θ), ref_jpeg) + λ·scene_constraints(θ)
```

## 1. 可微代理（surrogate）与保真门

- `scripts/calib/diff_core.py`：torch 重实现中性渲染链（decode→WB(warmth)→exposure→tone(neutral)→encode + RP-CCM），θ 全部为 `nn.Parameter`。**torch 只进 scripts/**（隔离纪律同 vision 栈）。
- **保真门（先于任何优化）**：同输入同 θ 下，surrogate 输出 vs 真实管线 `render_preview_full`（中性参数）的 ΔE2000 **median ≤ 0.05 / p95 ≤ 0.3**（校准抽样 ≥10 张）。不过门禁止优化——避免优化错误的目标函数。数据来源复用阶段一 `aligned_pair` 口径（orientation 6/8 逆旋转已实证）。
- 已知难点预埋：真实链含 LUT 插值/clip；surrogate 用线性插值可微近似 + soft-clip（tanh 近似），保真门就是量化这层近似的代价。

## 2. θ 参数化与上下料（configs 双向序列化）

- `scripts/calib/theta_io.py`：从现有 configs（warmth 曲线 JSON、曝光二维表、中性曲线、`rp_ccm_nikon_z5_2.json`、`skin_oklab.json`）加载初值；优化后按**原格式**写回（新文件落 `configs/color/calib_out/`，不覆盖原文件——对照留档）。
- 结构约束在参数化层解决：RP-CCM 用根多项式结构（曝光不变性 by construction）；warmth/exposure/neutral 用带罚项的连续参数（不做硬单调重参数化，靠 §3 罚项）。

## 3. Loss 设计

- **proxy（可微）**：Huber-smoothed Lab 距离（ΔE2000 含 min/max 不可微，只做评估不做训练目标——这是显式设计决策，防止对不可微目标做梯度）。
- **scene_constraints（可微罚项）**：warmth 单调 + 二阶平滑；曝光表 2D TV 平滑；中性曲线单调；skin 椭圆轴长正性；λ 用相对量纲归一。
- **优化器**：Adam(lr=1e-3) 预热 + L-BFGS 精修；seed 固定；语料清单 + npz 采样缓存（`--resume`，复用 fit_skin 模式）。
- **真值评估**：每轮 checkpoint 用真 ΔE2000（复用 `eval_rp_ccm_ab.delta_e_2000`，含 --selftest）出 median/p95——训练看 proxy，决策看真值。

## 4. G-5 收口（并入本轮）

- **门槛线文档化**（写进本设计 §6 与报告）：RP-CCM 转默认须同时满足——median 改善 ≥15%、无单照片 median 回归 >1 JND、总体 p95 不劣化、≥2 相机复验。
- **分组拟合**：按 pixo.meta 拍摄日/光照分组拟合 RP-CCM（阶段一 skin 拟合已实证组间中心漂移 a∈[−0.006, 0.041]）；产出 per-group 系数 + 分簇门控建议（不接运行时）。

## 5. 验收门

| 项 | 标准 |
|---|---|
| 保真门 | surrogate vs 真实管线 ΔE median ≤0.05/p95 ≤0.3 |
| 标定收益 | 真 ΔE2000 before/after：median 改善量化报告（不设硬线，首跑摸底） |
| 红线 | 新表全量回归：金样本按新表重生成（reviewer 流程）+ 全量 pytest 绿 + `src/pixo/render` git diff 为零 |
| 可复现 | seed + 语料清单 + 缓存 npz，`--resume` 重放一致 |

## 6. 任务拆解（weave）

```
t30 可微代理 diff_core + 保真门 (dev-1) ─┐
t31 θ 上下料 theta_io (dev-2) ────────────┴→ t32 loss+优化器+分组拟合 (dev-3)
                                              → t33 标定前后真值评估 (tester-2)
                                              → t34 新表全量回归+金样本 (tester-1)
                                              → t35 QA 终审+运行时零变化审计 (qa)
```
