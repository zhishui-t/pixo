# pixo.render 性能整体评估（只读，未改实现）

## 1. 当前基线（来自已有实测）
| 场景 | 耗时 | 来源 |
|---|---|---|
| 默认管线 6 活跃 stage（合成 2020×3032） | ≈5.2s | Phase4 审计 t26 |
| 其中 refine | ≈3.0s（58.6%） | t26 / t29 |
| refine 优化后（t29） | ≈2.95s（+3.5%） | t29 实测 |
| 真实 NEF 底座（master plan 记录） | ≈10.8s | RAWLAB_MASTER_PLAN |
| 快速预览（preview_fast + half_size） | 明显低于默认（未正式计时） | t33 |

## 2. 热点与瓶颈
1. **refine**（58%）：sharpen / chroma_denoise / highlight_desat / warm_sat 在 (2020,3032,3) float32 上做多遍全图广播运算；内存带宽型，纯 NumPy 已近极限。
2. **colorcal**（~0.7s）：Lab 域 + 场景曲线/肤色保护多遍全图转换。
3. **tone / clarity / exposure / whitebalance**（各 0.26~0.41s）：中轻度。
4. **decode/resample**：真实 NEF 全分辨率 rawpy 解码 + CFA 平均 + Stage3 重采样占用大头（10.8s 中的大部分）；现有 half_size 可降到预览档。
5. **DCP 解析/缓存**：首次加载较重，已有进程内缓存。

## 3. 优化路线评估
| 路线 | 预期收益 | 风险/成本 | 备注 |
|---|---|---|---|
| A. Numba JIT（refine/resample/CFA） | 高（内存带宽型通常 2-5x） | 中：需新增依赖（已可安装 numba 0.67）；要逐函数做数值等价回归 | 最推荐；可保持默认输出逐位一致（或 ≤1e-6） |
| B. 近似快速路径（refine 降采样/简化核） | 中高（refine 可省 50%+） | 低：默认关闭，不影响现有输出 | 适合“预览档”和用户可接受差异场景 |
| C. C++ 扩展 | 最高 | 高：编译链/维护成本 | 最后考虑 |
| D. 架构级（半精度/分块/缓存复用） | 中 | 中：改动面广 | 可作为 A 的补充 |
| E. 只保留现有 preview_fast | 低（已实现） | 零 | 已可用 |

## 4. 建议分步计划（每步独立验收）
1. **R-P1 基准固化**：写 `render/tools/bench_pipeline.py`（合成图 + 可选真实 NEF），输出每 stage 中位耗时与总耗时，保存基线 JSON。
2. **R-P2 Numba 试点 refine.sharpen/chroma_denoise**：只 JIT 两个最热函数，数值等价（max|Δ| ≤1e-6），跑 test_refine + 全量回归。
3. **R-P3 扩展 Numba 到 resample/CFA**（真实 NEF 大头），验收 input MAE ≤1e-5 + ablation。
4. **R-P4 可选近似 fast_mode**：默认 False，单独开关 + 测试。
5. **R-P5 复查全量性能目标**：真实 NEF 全分辨率 <5s 或给出可达到的明确数字。

## 5. 当前结论
- 不做任何改动也能交付；性能是“优化项”而非“缺陷”。
- 若要动，**先做 R-P1 基准**，再按 R-P2→R-P3 小步推进；每步跑 597 全量 + regression + ablation。
- Numba 已成功安装（numba 0.67 / llvmlite 0.49），具备试点条件；是否启用由你确认。
