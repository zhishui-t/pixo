# r11-stream-1 报告（dev-1）— scene 门控：无人像高覆盖磨皮观察窗清偿

> 2026-09-07 · qa `.r10b_ok` 观察窗首项。诊断 → 修法落地 → 三重验证（含金样本影响量化与归因铁证）。

## 1. 诊断（先查清机理再动手）

**Q1: RAW 四路径的 scene 判定是什么（portrait 从哪来）？**
- **渲染路径根本不存在 scene 判定**。全仓 grep：`ctx.state["scene"]` 的读者只有
  `skin.py` 一个；写入侧唯一命中是 `render/pipeline/intents.py:246`，但那里写的是
  `__meta__` 元数据字典，**不是 ctx.state**。skin.py docstring 提到的
  `analyze._classify` 在 src 中**不存在**（陈旧注释；gate_cases.py 也自证：
  合成 case 需「显式钉死 scene=portrait，不依赖 analyze 步骤」）。
- 结论：`render_preview_full`（preview/export 两线）与 loop/batch 的默认链上
  **scene 状态永远缺失** → skin wants 永远走「未分类」分支。

**Q2: 占比门限值与实际通过情况？**
- 门限（`skin.py` 常数）：scene=="portrait" → 下限 0.5%；未分类 → 下限 3%。
- 两档都是**单向下限**（只防"无肤色"），无上界。无人像图 night_lowlight
  掩码覆盖 90.2%、wide_angle 56.4%（.r10b_ok §3b 实测）≥3% → **畅通无阻**，
  磨皮（strength 0.5，enabled 缺省 True，oklch 缺省域）一直作用于风景默认链渲染。

**Q3: 机理结论**：不是「scene 误判」——是「**scene 判定从未接线 + 占比门限无上界**」
两代椭圆同在此列（非 R10 引入，与 .r10b_ok 定性一致）。

## 2. 修法选择（二选一 → 选 b，含证据）

- **a) scene 门控收紧——不可行（现状下无意义）**：渲染路径没有 scene 分类器，
  「收紧」的前提（存在分类结果）不成立；接入视觉分类器 = 重模型进默认链，
  超出本项范围且与缺省链轻量纪律冲突。
- **b) 覆盖率上限——选定**：未分类图掩码占比 >50% 判定场景误判 → no-op + warn。
  证据：F11 72 张语料真人像占比 ≤40%（tele 人像 6.6%、合成人像 ~30%），
  无人像风景样本 56.4~90.2% —— **50% 阈值恰好落在人像/风景覆盖间隙**；
  实现零额外成本（占比本就要算）。
- 组合语义：**scene=="portrait" 显式分类时豁免上限**（分类意图优先，保留
  未来分类器接线的正向通道）；scene 明确为其他值时维持既有直通。

## 3. 落地改动

| 文件 | 变更 |
|---|---|
| `src/pixo/render/modules/skin.py` | `_SKIN_RATIO_MAX_NO_SCENE = 0.50` + wants 未分类分支上限判定（no-op + warn + `ctx.state["skin_gate"]="coverage-cap"` 留痕）+ docstring/注释（module docstring 启用条件同步） |
| `tests/unit/test_skin.py` | 适配 `test_skin_stage_wants_no_scene_mask_gate`（True 侧改部分覆盖 ~25%，满幅肤色现在属上限截停语义）；**新增 3 用例**：coverage-cap（False+warn+状态留痕）、(3%,50%) 区间畅通（42% 覆盖）、portrait 豁免上限 |
| `tests/unit/test_skin_oklab.py` | `test_skin_stage_oklch_uses_oklab_mask` wants 断言前显式钉 `scene=portrait`（实心探针图覆盖 100%，免未分类上限；断言语义不变） |

语义矩阵（进程内直检 + 单测双验证）：

| 输入 | scene | 覆盖 | wants |
|---|---|---:|---|
| 满幅肤色 | 无 | 100% | **False**（coverage-cap + warn） |
| 25% / 42% 肤色 | 无 | 25/42% | True |
| 满幅肤色 | portrait | 100% | True（豁免上限） |
| 满幅肤色 | landscape | 100% | False（既有 scene 直通） |
| 纯灰 | 无 | ~0% | False（既有下限门） |

## 4. RAW 金样本影响量化（报队长裁决基线）

方法：加载 `data/golden/reference/render_bench/goldens/gate_defaults` 现行基线
（R10 重生成版，long_edge=512），以新门控重渲染 24 case（4 features × 6 样本，
`render_preview_full` 同参数），u8 逐像素比对 + ΔE76（`pipeline.perceptual` 同源）。

| 样本（scene 类别） | 漂移 case | 触发时占比(1/4 降采样) | 变化像素 | max Δ(u8) | ΔE mean / p95 |
|---|---|---:|---:|---:|---|
| night_lowlight（夜景） | 4/4 | 80.6% | **84.0%** | 68 | 1.356 / 4.034 |
| wide_angle（风景） | 4/4 | 54.5% | **63.5%** | 68 | 0.883 / 3.090 |
| high_contrast（高对比） | 4/4 | 60.8% | **40.3%** | 35 | 0.396 / 1.008 |
| day_normal | 0/4（41% < 50% 上限内） | — | 0% | 0 | 0 / 0 |
| high_key_bright | 0/4（~25%） | — | 0% | 0 | 0 / 0 |
| portrait_tele（人像） | 0/4（6.6%） | — | 0% | 0 | 0 / 0 |

- 漂移 **12/24**，全部为无人像高覆盖样本 × 4 features；u16 同向漂移（抽验确认）。
- **归因铁证**：对 2 个漂移样本禁用上限（`_SKIN_RATIO_MAX_NO_SCENE=1e9`）重渲染，
  u8 与 u16 sha256 **均与基线逐位还原**——漂移 100% 由本门控驱动，无其他混杂。
- **人像不受影响验证（任务4）**：portrait_tele（=X1_DSC_0466）四 case u8
  **位级全等**（sha256 相同）——F11 refit 成果的作用带完整保留。
- **基线处置建议（报队长裁决）**：RAW 24 基线重生成（12 case u8/u16 变更 +
  manifest sha 字段；其余 12 case 字节不动）。方向=移除两代同在的无人像误磨皮
  （.r10b_ok §3b 定性的观察窗清偿），属「缺陷修正」而非语义变更；reviewer 流程沿 R10 惯例。

## 5. 验证

```
python -m pytest tests/unit/test_skin.py tests/unit/test_skin_oklab.py \
  tests/regression/test_gate_skin.py tests/regression/test_gate_golden.py tests/unit/test_pipeline.py -q
→ 79 passed（含新增 3 用例；gate golden 20 features 全过）
```
- gate golden 合成族零漂移：skin case（scene 钉 portrait + 25% 覆盖）与
  default_dispatch（钉 portrait）不受上限影响；RAW 影响已单列上表。
- 中间态说明：首轮跑测试时 huesat 处于 dev-2 删 A 轨的并行中间态
  （`apply_hue_sat_map` 暂缺，测试收集期 ImportError），与本流无关，
  稳定后复跑全绿。
- F11 口径不受影响：F11 掩码域/磨皮意图数据直接调 `core.skin` 掩码函数
  （不经 wants 门控），结论维持。

## 6. 遗留/建议

1. **scene 分类器接线**（长期）：真 scene 门控需要渲染路径接入分类结果
   （loop/agent 侧决策），本轮以覆盖率上限兜底；未来接线时 portrait 豁免
   上限的语义已就位。
2. 阈值 50% 基于 F11 72 张语料间隙（人像 ≤40% / 风景 ≥56%）；如后续语料
   出现 40~50% 的合法高覆盖人像（特写构图），可按数据复议阈值或改由
   scene 分类承担。
3. RAW 基线重生成后，建议在 gate 工具输出附 skin wants 的 gate 决策
   （ratio/cap）便于下次归因。
