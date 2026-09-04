# Surrogate 保真门报告 (torch 可微代理 vs 真实管线)

- 生成时间: 2026-09-04 11:43:56
- 结论: **PASS ✅** — 总体 ΔE2000 median 0.0000 / p95 0.0000 (门限 median ≤0.05 / p95 ≤0.3)
- 语料: exports/auto/full_scan (12 张评估 / 0 张跳过; 要求 ≥10)
- DCP: Nikon Z 5 2 RawLab LR Adobe Standard Baseline.dcp @ long_edge=512, stride=3, θ0=现行 configs 标定值
- ΔE 实现: eval_rp_ccm_ab.delta_e_2000 (Sharma 2005, --selftest 通过), 窗口 [0.01,0.90] 线性域 (语料口径 sample_linear_pairs)
- 耗时: 17.7s

## 链口径

代理链 (设计 §1) = decode → exposure(ev) → whitebalance(camera_wb × warmth × 矩阵 + 高光中性化) → [RP-CCM] → tone(brightness + sRGB EOTF LUT 线性插值) → colorcal 中性快速路径 (CCT 分桶曲线) → u8 量化。
真实对照 = render_preview_full 中性参数 (下表), 其中 clarity/refine/skin
为 θ 无关的空间观感 stage (默认开启, 实测对逐像素链 ΔE median ~2.1),
按代理链口径显式关闭:

```json
{
  "exposure": {
    "mode": 0.0
  },
  "whitebalance": {
    "trim": [
      1,
      1,
      1
    ]
  },
  "clarity": {
    "enabled": false
  },
  "refine": {
    "sharpen": 0.0,
    "highlight_desat": 0.0,
    "chroma_denoise": 0.0
  },
  "skin": {
    "enabled": false
  }
}
```

## 可微近似 (前向逐位复刻, 反向平滑)

- tone LUT: 真实链最近邻 (native 内核), 代理线性插值 (设计 §1) ——
  ≤半格偏差, 本报告即其量化代价;
- clip: 前向硬 clip (逐位), 反向 tanh 软梯度 (soft-clip 语义在反向);
- colorcal tint: 前向 cv2 u8 逐位 (整数 tint), 反向 float Lab→RGB 雅可比;
- 静态量 (饱和掩码/colorcal 权重与 L 混合索引/基 tint/CCT 分桶) θ0 冻结。

## 总体 (全样本池)

| 指标 | 值 | 门限 | 判定 |
|---|---:|---:|:---:|
| ΔE2000 median | 0.0000 | ≤ 0.05 | ✅ |
| ΔE2000 p95 | 0.0000 | ≤ 0.3 | ✅ |
| ΔE2000 max | 1.7374 | — | — |
| u8 同码像素占比 | 97.07% | — | — |

## 分照片

| photo | n | median | p95 | max | 同码率 |
|---|---:|---:|---:|---:|---:|
| DSC_5269_raw | 5913 | 0.0000 | 0.0000 | 1.116 | 96.5% |
| DSC_5270_raw | 5976 | 0.0000 | 0.0000 | 1.684 | 96.5% |
| DSC_5271_raw | 6602 | 0.0000 | 0.0000 | 1.564 | 96.2% |
| DSC_5272_raw | 6591 | 0.0000 | 0.0000 | 1.181 | 96.7% |
| DSC_5273_raw | 6653 | 0.0000 | 0.0000 | 1.586 | 96.4% |
| DSC_5274_raw | 7413 | 0.0000 | 0.0000 | 1.737 | 96.7% |
| DSC_5275_raw | 7584 | 0.0000 | 0.0000 | 1.176 | 96.5% |
| DSC_5276_raw | 7410 | 0.0000 | 0.0000 | 1.635 | 97.5% |
| DSC_5277_raw | 7336 | 0.0000 | 0.0000 | 1.181 | 97.7% |
| DSC_5278_raw | 5461 | 0.0000 | 0.0000 | 1.146 | 98.5% |
| DSC_5279_raw | 5479 | 0.0000 | 0.0000 | 1.211 | 97.9% |
| DSC_5280_raw | 7018 | 0.0000 | 0.0000 | 1.176 | 98.0% |

最差照片 (median): DSC_5269_raw = 0.0000。

> 纪律: 本门为 θ 优化的硬前置 (设计 §1 —— 不过门禁止优化); 报告只读,
> 未修改任何 configs/ 运行时配置与 src/pixo/render。