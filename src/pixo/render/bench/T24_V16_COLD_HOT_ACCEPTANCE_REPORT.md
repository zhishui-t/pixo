# T24 v1.6 cold/hot 双口径终验报告

> 日期：2026-08-20
> 执行：长安小队 · 测试（t24）
> 依据：`render/docs/PIXO_RENDER_1S_PREVIEW_DESIGN.md` v1.6 门禁
> 数据源：`K:\dsh-share\dng_verify\DSC_5607.dng`
> DCP：`render/profiles/Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp`

## 1. 验收命令

```bash
# 全量测试
python -m pytest src/render/tests -q --tb=short

# cold/hot 双口径 + A/B
python render/tools/bench_preview.py \
    --raw K:/dsh-share/dng_verify/DSC_5607.dng \
    --dcp K:/work/project/pixo/src/pixo/render/profiles/Nikon\ Z\ 5\ 2\ RawLab\ LR\ Adobe\ Standard\ Baseline.dcp \
    --edges 1024,2048 --runs 3 --warmup 1 --mode both --ab \
    --baseline render/bench/preview_v16_baseline.json
```

## 2. 全量 pytest

结果：**417 passed, 1 xfailed**（WebP 编码耗时已知未达 60ms，见 t17）。

- 退出码：0
- 日志：`render/bench/t24_pytest.log`

## 3. cold/hot 性能验收

### 3.1 hot（缓存热启动，warmup=1，runs=3 中位）

| 档 | decode | 门禁 | total | 门禁 | 判定 |
|---|---:|---:|---:|---:|---|
| long1024 | 0.2 ms | ≤300 ms | 370.5 ms | ≤1000 ms | **PASS** |
| long2048 | 0.2 ms | ≤300 ms | 1094.6 ms | ≤2000 ms | **PASS** |

### 3.2 cold（清空内存/磁盘解码缓存，runs=3 中位）

| 档 | decode | 门禁 | total | 门禁（目标） | 判定 |
|---|---:|---:|---:|---:|---|
| long1024 | 1308.4 ms | ≤1500 ms | 1648.5 ms | ≤2000 ms（目标 1500） | **PASS** |
| long2048 | 1236.8 ms | ≤1500 ms | 2248.2 ms | ≤3000 ms（目标 2500） | **PASS** |

> 说明：cold total 未达到“目标值”1.5s/2.5s，但满足硬门禁 2s/3s；按 v1.6 口径为 PASS。

## 4. A/B 差异验收

门禁：每通道 p50 ≤ 2/255、p99 ≤ 10/255。

| 档 | 通道 | p50 | p99 | max | 判定 |
|---|---|---:|---:|---:|---|
| long1024 | R/G/B/all | 1.0 | 9~10 | 38~56 | **PASS** |
| long2048 | R/G/B/all | 1.0 | 9~10 | 43~47 | **PASS** |

## 5. 生产路径无降采样污染

- 基准使用 `build_default_pipeline` 完整 12 stage 链，`preview_fast` 不参与。
- A/B 口径统一为“同一 CFA half 解码 + 完整 12 stage”，仅对比“先渲后缩”与“先缩后渲”，差异 p50=1/255、p99≤10/255。
- `src/render/tests/test_preview_full.py` 已验证 `render_preview_full` 使用默认全链、支持 8/16-bit、CFA 解码失败回退 rawpy AHD，未发现降采样污染导致的整片偏色/条纹。

## 6. 基线产物

| 文件 | 说明 |
|---|---|
| `render/bench/preview_v16_baseline_hot.json` | hot 口径基线 |
| `render/bench/preview_v16_baseline_cold.json` | cold 口径基线 |
| `render/bench/t24_pytest.log` | 全量 pytest 日志 |
| `render/bench/t24_bench_preview.log` | bench_preview cold/hot 日志 |

## 7. 结论

v1.6 cold/hot 双口径终验 **全部通过**：

- 全量 pytest：417 passed / 1 xfailed。
- long1024：hot total 370.5ms、cold total 1648.5ms，均达标。
- long2048：hot total 1094.6ms、cold total 2248.2ms，均达标。
- A/B：p50=1/255、p99≤10/255，达标。
- 生产路径使用完整 12 stage，无 preview_fast 降级污染。
