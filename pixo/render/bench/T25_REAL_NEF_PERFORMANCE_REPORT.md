# T25 真实 NEF 性能证据报告

> 日期：2026-08-20
> 执行：长安小队 · 测试（t25）
> 依据：`render/docs/PIXO_RENDER_1S_PREVIEW_DESIGN.md` v1.6 门禁
> 数据源：**真实 NEF**（非 DNG）
> NEF：`K:\data\photo\0711\raw\DSC_5236.NEF`
> DCP：`render/profiles/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp`

## 1. 验收命令

```bash
python render/tools/bench_preview.py \
    --raw K:/data/photo/0711/raw/DSC_5236.NEF \
    --dcp K:/work/project/pixo/pixo/render/profiles/Nikon\ Z\ 5\ 2\ RawLab\ LR\ Adobe\ Standard\ Baseline.dcp \
    --edges 1024,2048 --runs 3 --warmup 1 --mode both --ab \
    --baseline render/bench/preview_v16_nef_baseline.json
```

## 2. hot 口径（缓存热启动）

| 档 | decode | 门禁 | total | 门禁 | 判定 |
|---|---:|---:|---:|---:|---|
| long1024 | 0.3 ms | ≤300 ms | 414.2 ms | ≤1000 ms | **PASS** |
| long2048 | 0.2 ms | ≤300 ms | 1188.4 ms | ≤2000 ms | **PASS** |

## 3. cold 口径（清空内存/磁盘解码缓存）

| 档 | decode | 门禁 | total | 门禁（目标） | 判定 |
|---|---:|---:|---:|---:|---|
| long1024 | 1373.7 ms | ≤1500 ms | 1737.5 ms | ≤2000 ms（目标 1500） | **PASS** |
| long2048 | 1256.5 ms | ≤1500 ms | 2668.0 ms | ≤3000 ms（目标 2500） | **PASS** |

> cold total 未达到目标值 1.5s/2.5s，但满足 v1.6 硬门禁 2s/3s，按口径 PASS。

## 4. A/B 差异（真实 NEF）

门禁：每通道 p50 ≤ 2/255、p99 ≤ 10/255。

| 档 | 通道 | p50 | p99 | max | 判定 |
|---|---|---:|---:|---:|---|
| long1024 | R/G/B/all | 1.0 | 9~10 | 47~57 | **PASS** |
| long2048 | R/G/B/all | 1.0 | 9~10 | 56~64 | **PASS** |

## 5. 与 DNG 证据的差异说明

- 本报告使用真实 NEF（`DSC_5236.NEF`），不是 DNG 转换文件。
- 真实 NEF 的 rawpy 首访 `raw_image_visible` 耗时约 1.26~1.37s，与 DNG 的 1.23~1.31s 接近；CFA 内核本身仅约百毫秒级。
- 真实 NEF cold/hot 端到端与 A/B 均达到 v1.6 门禁，未出现 DNG 与 NEF 的显著性能/质量差异。
- 若后续需要更多 NEF 样本，可使用 `K:\data\photo\0711\raw\` 与 `K:\data\photo\2026春节\` 下的真实 NEF 继续扩充。

## 6. 产物

| 文件 | 说明 |
|---|---|
| `render/bench/preview_v16_nef_baseline_hot.json` | 真实 NEF hot 基线 |
| `render/bench/preview_v16_nef_baseline_cold.json` | 真实 NEF cold 基线 |
| `render/bench/t25_nef_bench.log` | bench_preview 日志 |
| `render/bench/T25_REAL_NEF_PERFORMANCE_REPORT.md` | 本报告 |

## 7. 结论

真实 NEF 性能证据已补齐，v1.6 cold/hot 双口径与 A/B **全部通过**：

- hot：long1024 total 414.2ms、long2048 total 1188.4ms。
- cold：long1024 total 1737.5ms、long2048 total 2668.0ms。
- A/B：p50=1/255、p99≤10/255。
