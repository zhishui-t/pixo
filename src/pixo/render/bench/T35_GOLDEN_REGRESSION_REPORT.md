# T35 功能 golden 回归报告

> 日期：2026-08-20
> 执行：长安小队 · 测试（t35）
> 依据：`render/docs/FUNCTION_GATE_SPEC.md` §6 golden 回归（L2）
> 数据源：真实 NEF `K:\data\photo\0711\raw\DSC_5236.NEF`
> DCP：`resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp`

## 1. 交付物

| 文件 | 说明 |
|---|---|
| `render/tools/gate_golden.py` | golden 生成/对比工具（`generate` / `compare` 子命令） |
| `data/golden/reference/render_bench/goldens/gate/manifest.json` | golden 清单（raw/dcp/params/sha256/shape） |
| `data/golden/reference/render_bench/goldens/gate/<feature>/output_u8.npy` | 8-bit golden 输出 |
| `data/golden/reference/render_bench/goldens/gate/<feature>/output_u16.npy` | 16-bit golden 输出 |
| `render/bench/T35_GOLDEN_REGRESSION_REPORT.md` | 本报告 |

覆盖 feature：`exposure`、`whitebalance`、`tone`、`hsl`、`split_tone`、`calibration`、`skin`、`refine`。

## 2. 生成命令

```bash
python render/tools/gate_golden.py generate \
    --raw K:/data/photo/0711/raw/DSC_5236.NEF \
    --dcp $PIXO_ROOT/resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp \
    --out data/golden/reference/render_bench/goldens/gate \
    --long-edge 512
```

- 每个 feature 使用一组代表性非默认参数（见 `FEATURES`）。
- 同时输出 8-bit 与 16-bit 基准，保存为 `.npy` 并记录 sha256。

## 3. 对比命令与阈值

```bash
python render/tools/gate_golden.py compare \
    --raw K:/data/photo/0711/raw/DSC_5236.NEF \
    --dcp $PIXO_ROOT/resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp \
    --out data/golden/reference/render_bench/goldens/gate \
    --long-edge 512
```

阈值：
- 8-bit：`max|Δ| ≤ 1/255`
- 16-bit：`max|Δ| ≤ 1/65535`
- 任一 feature 超阈值 → 非零退出，阻塞合并。

## 4. 首跑对比结果

| feature | u8_max | u16_max | verdict |
|---|---:|---:|---|
| exposure | 0 | 0 | PASS |
| whitebalance | 0 | 0 | PASS |
| tone | 0 | 0 | PASS |
| hsl | 0 | 0 | PASS |
| split_tone | 0 | 0 | PASS |
| calibration | 0 | 0 | PASS |
| skin | 0 | 0 | PASS |
| refine | 0 | 0 | PASS |

首跑 golden 与当前实现完全一致（逐位），后续任何功能改动应先跑 `compare`。

## 5. 说明

- 当前基线使用真实 NEF，非合成图；尺寸为长边 512（341×512×3），兼顾体积与回归覆盖。
- 如需扩大覆盖，可增加真实 NEF 样本或切换 `--long-edge 1024/2048` 重新生成。
- 该工具只依赖 `render`，不引用 `rawlab`。
