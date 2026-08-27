# uint8 中转量化精度测量报告 (16-bit 导出精度改造 go/no-go)

- 日期: 2026-08-27
- 测量脚本: `scripts/measure_u8_precision.py` (本文所有数字均来自该脚本的真实运行输出, 复现命令见 §8)
- 环境: Windows / Python 3.12.10 / numpy 2.5.1 / opencv 5.0.0 / pixo native DLL 可用
- 语料: `K:/data/photo` (Nikon Z5_2 + NIKKOR Z 24-120mm f/4 S, NEF 6064x4040)
- 结论速览: **值得改, 且应优先只改 colorcal 一处** —— colorcal 全量 Lab 路径的
  uint8 往返在生产线预设下平均代价 **0.81 ΔE76**、**24.7% 像素超过 1 ΔE** 感知阈值;
  refine 的 sat_protection u8 中转可忽略 (<0.02 ΔE); stylize LUT 的 8bit 网格代价
  中等 (0.22 ΔE, >1ΔE 像素 <0.05%); lr_baseline 预设启用且门控命中时, refine 的
  warm HSV 全 u8 往返代价与 colorcal 同量级 (0.57~0.90 ΔE)。

---

## 1. 三处量化点定位

### 1.1 colorcal 全量 Lab 路径 (双向量化, 主链路 gamma 域最粗的一步)

`src/pixo/render/modules/color_cal.py::ColorCalStage.process`:

| 端 | 位置 | 代码 | 量化内容 |
|---|---|---|---|
| 输入 | `color_cal.py:284` | `u8 = (img * 255.0 + 0.5).astype(np.uint8)` | RGB → 8bit 网格 |
| 输入 | `color_cal.py:285` | `lab = cv2.cvtColor(u8, cv2.COLOR_RGB2LAB).astype(np.float32)` | cv2 uint8 Lab → **L 步长 100/255≈0.392, a/b 步长 1.0 (≈1 ΔE)** |
| 输出 | `color_cal.py:308` | `lab2 = _native_colorcal_apply_lab(lab, params)` | native 内核输出缓冲即 uint8 Lab (native/src/colorcal.cpp:146-148/162-164, 截断 cast) |
| 输出 | `color_cal.py:309-310` | `cv2.cvtColor(lab2, LAB2RGB)` + `/255` | uint8 Lab → uint8 RGB → /255 |

python 回退分支同口径: `color_cal.py:372` `lab2 = np.clip(lab2, 0, 255).astype(np.uint8)`、`:373-374` LAB2RGB。
(渲染深审所引 `:256`/`:339` 即现在的 284/372 行。)

补充: 仅中性校正的快速路径 `_apply_neutral_fast` 在 `color_cal.py:429` 也有一次 u8
量化, 但只用于 1/2 降采样测量 (输出仍为 float 相加), 且**生产预设恒不走该路径**
—— 两个生产预设 (§2) 的 colorcal 参数都绕开快速路径: `lr_adobe_standard_baseline`
恒定 `saturation=-0.06` (sat≠0 → 全量路径); `lr_baseline` 经 `scene_skin_trim`/
`scene_trim`/`scene_hue` 的 wb 窗口命中进入全量路径 (本测量 5 样本中 1 样本经
skin_trim 进入, 其余直通)。故快速路径量化不在本次测量范围 (如实说明, 非不可测)。

### 1.2 stylize LUT 应用 (双向量化, 8bit 网格)

`src/pixo/render/modules/style.py::StylizeStage.process`:

| 端 | 位置 | 代码 | 量化内容 |
|---|---|---|---|
| 输入 | `style.py:55` | `u8 = (np.clip(ctx.image,0,1)*255+0.5).astype(np.uint8)` | RGB → 8bit, 之后仅能在 256³ 整数格点 gather |
| 输出 | `core/lut3d.py:171` | `_build_table`: `(np.clip(out,0,1)*255+0.5).astype(np.uint8)` | 表值 → 8bit |
| 输出 | `style.py:56-57` | `lut.apply(u8)` → `out8/255` | uint8 出图 |

注意 `core/lut3d.py:143-149` 已有 float 四面体插值入口 `LUT3D.lookup()` (与建表
同一 Kasson 算法), 因此该处的 float 重放**成本低** (本测量直接用它, 无需解析估界)。
生产默认不挂 LUT (scenes.json 全部 `"lut": null`), 胶片风格经 `core/lut.py:30`
注册表 (guanlan/luts/*.cube) 启用 —— 本测量用注册表内的 `astia` (32³)。

### 1.3 refine HSV 处理 (输入端量化, 恒开; 全 u8 往返, 参数门控)

`src/pixo/render/modules/refine.py`:

| 子点 | 位置 | 说明 |
|---|---|---|
| sat_protection (恒开) | `refine.py:326-327` (python) / `native/src/refine.cpp:193-198` (native, 生产实际路径) | RGB → u8 int → `RefineSatLut[max*256+min]` (cv2 8bit HSV 的 S 平面) → smoothstep 权重。量化只影响锐化/色度降噪/高光去色的权重图, 输出本身 float |
| apply_warm_sat_gamma (门控) | `refine.py:111-113` (入) / `:161-163` (出) | `u8 → cv2 RGB2HSV(u8) → 改 H/S → astype(uint8) → HSV2RGB(u8) → /255`, 全 u8 往返。仅 `warm_sat_curve`/`warm_sat_spot`/`warm_hue_curve` 参数启用且 wb/覆盖率门控命中时执行; `lr_baseline` 预设全部启用 (configs/styles/lr_baseline.json), `lr_adobe_standard_baseline` 未启用 |

native 侧 `RefineSatProtection` 与 python 回退同口径 (refine.cpp:193-195 先
`static_cast<int>(Clamp01(rgb)*255+0.5)`), 即**生产 (native) 路径确实存在该量化**。

---

## 2. 测量方法

### 2.1 渲染基准

复刻导出主线 `src/pixo/render/web/export.py::_render_full_quality` (16-bit 导出的
实际路径): `decode_raw(half_size=False)` 全分辨率解码一次 → `build_default_pipeline`
完整 12 stage → 取最终 float gamma RGB (导出 u16 量化**之前**的 float 输出, 使测量
不受最终 16bit 量化掩蔽; 另报一列"两版各自量化到 uint16 后"的 ΔE16, 即 TIFF16
用户实际所见)。同一样本所有变体复用同一次解码, 保证输入 bit 一致。

三个真实生产配置:

- **A** = `configs/styles/lr_adobe_standard_baseline.json` (auto_full_scan.py 生产
  主线预设; colorcal `saturation=-0.06` → 全量 Lab 路径每次必走; 无 LUT; refine
  仅 sat_protection u8 生效)
- **B** = A + `stylize.lut=astia` (注册表生产 LUT, 触发 stylize 量化)
- **C** = `configs/styles/lr_baseline.json` (colorcal 走 scene_trim/skin_trim/scene_hue
  wb 窗口门控; refine warm_sat_curve/spot/hue 全启用 → warm HSV 全 u8 往返被测)

### 2.2 monkeypatch 点 (只换量化往返, 不改算法逻辑)

| stage | patch | 实现 |
|---|---|---|
| colorcal | `ColorCalStage.process` 逐行拷贝 + 三处量化语句切换 float | 输入端 `cv2.cvtColor(u8,RGB2LAB)` → `cv2.cvtColor(float,RGB2LAB)` 换算到同一 0..255 Lab 坐标; 输出端 native uint8 内核 → 逐式镜像 colorcal.cpp 的 numpy float 内核 (不 cast uint8), `LAB2RGB` 走 cv2 float。gamut_soft 仍用生产 native (本就 float) |
| stylize | `StylizeStage.process` float 版 | `lut.apply(u8)` (256³ u8 gather) → `lut.lookup(float)` (core/lut3d.py 既有 float 四面体插值, 同一算法) |
| refine | `_native.refine_sat_protection` + `RefineStage._sat_protection` + `apply_warm_sat_gamma` float 版 | sat: S=(max−min)/max float 直算 (去掉 rgb→u8 int 与 RefineSatLut), 同一 smoothstep; warm: `cv2 RGB2HSV(float)`→改 H/S→`HSV2RGB(float)`, 门控/增益/阈值逐行同产产 |

保真自检 (全部通过, 首样本):

```
[selfcheck] copy-fidelity maxdiff=0 (须=0)  determinism maxdiff=0 (须=0)
[selfcheck] float-kernel vs DLL(u8): mismatch_px=0.0000%  max|ΔLab|=1.000
```

- copy-fidelity=0: 拷贝的 process 在量化模式 (float 关) 下与未 patch 生产渲染 **bit 一致** → 差异只能来自量化替换本身;
- determinism=0: 渲染可重复;
- float 内核 vs native DLL: 同一 float Lab 输入下, numpy float 内核按 cpp 同款截断
  cast 后与 DLL 输出 **0.0000% 像素不一致** → float 内核是 DLL 的忠实去量化版。
- 附加佐证: C 配置下 colorcal 直通的样本 `C_cc` 全部指标恒为 0 (patch 未引入任何
  副作用); DSC_1715 两次独立运行所有数字逐位一致。

### 2.3 度量

- **ΔE76**: 两版输出各自 `cv2.cvtColor(float32, COLOR_RGB2LAB)` (显式 float32 输入,
  L∈0..100), `ΔE = sqrt(dL²+da²+db²)`, 全分辨率全像素 (24.5M/张) 的 mean/p50/p95/p99/max
  与 >1ΔE 占比; 另给分通道 |dL|/|da|/|db| 均值。
- **RGB 8bit 网格残差**: `d8 = round_u8(base) − round_u8(patched)` (生产口径
  `(x*255+0.5)` 取整), 分通道 ≠0 占比 / |d8|≥1/≥2/≥3 占比 / 通道 max。
- **ΔE16**: 两版各自量化 uint16 (16-bit 导出口径) 后的 ΔE76 —— 回答"16-bit 导出
  用户实际能看到多少"。

### 2.4 样本 (EXIF 亮度多样性: EV100 3.00 ~ 16.64)

```
=== 样本 (EXIF 摘要) ===
  DSC_0470.NEF     1            NIKON Z5_2   NIKKOR Z 24-120mm f/4 S      f/4.0 1/2s ISO400 EC0.0 EV100=3.00
  DSC_0370.NEF     2026春节       NIKON Z5_2   NIKKOR Z 24-120mm f/4 S      f/4.0 1/100s ISO2500 EC0.0 EV100=6.00
  DSC_0512.NEF     2026春节       NIKON Z5_2   NIKKOR Z 24-120mm f/4 S      f/4.0 1/250s ISO125 EC0.0 EV100=11.64
  DSC_1715.NEF     101XM_02     NIKON Z5_2   NIKKOR Z 24-120mm f/4 S      f/4.0 1/640s ISO100 EC0.0 EV100=13.32
  DSC_2805.NEF     103XM_04     NIKON Z5_2   NIKKOR Z 24-120mm f/4 S      f/4.0 1/6400s ISO100 EC0.0 EV100=16.64
```

选样: EV100 = log2(N²/t) − log2(ISO/100) (场景亮度代理), 覆盖暗光 (3.0, 0.5s 长曝) /
暗光夜景 (6.0, ISO2500) / 正常 (11.6, 13.3) / 高调 (16.6, 1/6400s), 来自语料
`厦门/{1,101XM_02,103XM_04}` 与 `2026春节` 共 4 个目录 (2662 张候选中按分位选取)。
相机 WB (决定 C 预设 scene/warm 门控): wb_B = 1.490 / 2.311 / 1.418 / 1.371 / 1.270。

---

## 3. 核心数值 (5 样本运行输出)

### 3.1 配置 A (lr_adobe_standard_baseline, 生产主线预设) + B (A+astia LUT)

每行 = 该 stage 单独 patch float 直通 vs 同配置生产 baseline (ΔE76, 全像素):

```
DSC_0470 (EV100 3.00, 暗):
  A_cc    ΔE76 mean=0.8328 p95=1.5264 p99=2.0800 max=31.538 >1ΔE=24.210%  dL/da/db=0.213/0.604/0.389  rgb8 max=54 mean=0.9085  ΔE16 mean=0.8328 max=31.538
  A_rf    ΔE76 mean=0.0088 p95=0.0000 p99=0.3083 max=1.492  >1ΔE=0.000%   dL/da/db=0.002/0.006/0.005  rgb8 max=2  mean=0.0059  ΔE16 mean=0.0088 max=1.492
  A_all   ΔE76 mean=0.8328 p95=1.5264 p99=2.0801 max=31.893 >1ΔE=24.212%  dL/da/db=0.213/0.604/0.389  rgb8 max=55 mean=0.9086  ΔE16 mean=0.8328 max=31.893
  B_lut   ΔE76 mean=0.2154 p95=0.4644 p99=0.7296 max=2.568  >1ΔE=0.024%   dL/da/db=0.075/0.130/0.121  rgb8 max=3  mean=0.1335  ΔE16 mean=0.2132 max=2.568

DSC_0370 (EV100 6.00, 夜 ISO2500):
  A_cc    mean=0.9032 p95=1.6167 p99=2.3784 max=21.107 >1ΔE=30.949%  dL/da/db=0.213/0.542/0.569  rgb8 max=37 mean=0.9875  ΔE16 mean=0.9032 max=21.107
  A_rf    mean=0.0144 p95=0.1878 p99=0.3277 max=1.233  >1ΔE=0.000%   dL/da/db=0.003/0.009/0.009  rgb8 max=3  mean=0.0099  ΔE16 mean=0.0144 max=1.233
  A_all   mean=0.9034 p95=1.6164 p99=2.3776 max=21.107 >1ΔE=30.952%  dL/da/db=0.213/0.542/0.569  rgb8 max=37 mean=0.9878  ΔE16 mean=0.9033 max=21.107
  B_lut   mean=0.2357 p95=0.6094 p99=0.7605 max=2.592  >1ΔE=0.001%   dL/da/db=0.078/0.146/0.138  rgb8 max=3  mean=0.0989  ΔE16 mean=0.2357 max=2.592

DSC_0512 (EV100 11.64):
  A_cc    mean=0.8885 p95=1.6572 p99=2.2384 max=27.361 >1ΔE=31.613%  dL/da/db=0.251/0.550/0.491  rgb8 max=59 mean=1.0273  ΔE16 mean=0.8885 max=27.361
  A_rf    mean=0.0105 p95=0.0000 p99=0.3429 max=3.819  >1ΔE=0.000%   dL/da/db=0.003/0.007/0.006  rgb8 max=7  mean=0.0069  ΔE16 mean=0.0105 max=3.819
  A_all   mean=0.8885 p95=1.6572 p99=2.2382 max=27.356 >1ΔE=31.612%  dL/da/db=0.251/0.550/0.491  rgb8 max=59 mean=1.0273  ΔE16 mean=0.8885 max=27.356
  B_lut   mean=0.2430 p95=0.5386 p99=0.7129 max=2.802  >1ΔE=0.048%   dL/da/db=0.090/0.141/0.134  rgb8 max=5  mean=0.1531  ΔE16 mean=0.2423 max=2.802

DSC_1715 (EV100 13.32):
  A_cc    mean=0.8333 p95=1.6456 p99=2.2216 max=21.201 >1ΔE=29.039%  dL/da/db=0.243/0.507/0.463  rgb8 max=47 mean=1.0195  ΔE16 mean=0.8333 max=21.201
  A_rf    mean=0.0194 p95=0.2089 p99=0.3603 max=1.716  >1ΔE=0.000%   dL/da/db=0.005/0.012/0.012  rgb8 max=3  mean=0.0142  ΔE16 mean=0.0194 max=1.716
  A_all   mean=0.8333 p95=1.6460 p99=2.2216 max=21.449 >1ΔE=29.038%  dL/da/db=0.243/0.507/0.463  rgb8 max=48 mean=1.0195  ΔE16 mean=0.8333 max=21.449
  B_lut   mean=0.2175 p95=0.4726 p99=0.6329 max=1.825  >1ΔE=0.001%   dL/da/db=0.078/0.125/0.122  rgb8 max=3  mean=0.1565  ΔE16 mean=0.2167 max=1.825

DSC_2805 (EV100 16.64, 高调):
  A_cc    mean=0.5952 p95=1.0626 p99=1.3437 max=16.288 >1ΔE=7.867%   dL/da/db=0.205/0.432/0.232  rgb8 max=32 mean=0.7007  ΔE16 mean=0.5952 max=16.288
  A_rf    mean=0.0080 p95=0.0000 p99=0.3083 max=0.763  >1ΔE=0.000%   dL/da/db=0.002/0.005/0.005  rgb8 max=1  mean=0.0049  ΔE16 mean=0.0080 max=0.763
  A_all   mean=0.5947 p95=1.0626 p99=1.3405 max=15.598 >1ΔE=7.830%   dL/da/db=0.204/0.432/0.231  rgb8 max=31 mean=0.7001  ΔE16 mean=0.5947 max=15.598
  B_lut   mean=0.1969 p95=0.3660 p99=0.5773 max=1.045  >1ΔE=0.000%   dL/da/db=0.078/0.111/0.104  rgb8 max=2  mean=0.1771  ΔE16 mean=0.1969 max=1.045
```

### 3.2 配置 C (lr_baseline: colorcal scene 门控 + refine warm HSV 全往返)

```
DSC_0470 (wb_B=1.490):
  C_cc    mean=0.0000 (colorcal 直通: scene/skin/hue 窗口均未命中)
  C_rf    mean=0.5690 p95=1.0887 p99=2.2491 max=7.970 >1ΔE=7.581%   rgb8 max=16 mean=0.3604  ΔE16 mean=0.5691 max=7.970
          warm_sat gate: gain=0.0 hue_shift=1.937 coverage=0.97%
  C_all   mean=0.5690 (与 C_rf 相同, colorcal 无贡献)
DSC_0370 (wb_B=2.311, 夜):
  C_cc    mean=0.0000
  C_rf    mean=0.9008 p95=2.8416 p99=3.8746 max=6.624 >1ΔE=26.763%  rgb8 max=13 mean=0.5692  ΔE16 mean=0.9010 max=6.624
          warm_sat gate: gain=0.0 hue_shift=3.708 coverage=7.53%
  C_all   mean=0.9008
DSC_0512 (wb_B=1.418):
  C_cc    mean=0.5915 p95=1.4368 p99=2.1308 max=27.324 >1ΔE=13.959%  (scene_skin_trim 窗口 [1.39,1.43] 命中 → skin_trim [-2,-4] 进全量 Lab 路径)
  C_rf    mean=0.0058 (warm 门控未命中, hue_shift=0 → 仅 sat_protection 残差)
  C_all   mean=0.5909 p95=1.4355 max=25.853
DSC_1715 (wb_B=1.371):
  C_cc    mean=0.0000
  C_rf    mean=0.6054 p95=1.3338 p99=1.8430 max=7.558 >1ΔE=13.863%  rgb8 max=13 mean=0.3918  ΔE16 mean=0.6055 max=7.558
          warm_sat gate: gain=0.0 hue_shift=2.855 coverage=0.20%
  C_all   mean=0.6054
DSC_2805 (wb_B=1.270):
  C_cc    mean=0.0000
  C_rf    mean=0.0095 (warm 门控未命中)
  C_all   mean=0.0095
```

### 3.3 汇总 (脚本输出, 5 样本均值 / 极值)

```
===== 汇总 (各 stage 贡献, 5 样本) =====
variant     ΔE mean   ΔE p95   ΔE max   %>1ΔE rgb8max  ΔE16max
A_cc         0.8106   1.5017   31.538 24.735%      59   31.538
A_rf         0.0122   0.0793    3.819  0.000%       7    3.819
A_all        0.8105   1.5018   31.893 24.729%      59   31.893
B_lut        0.2217   0.4902    2.802  0.015%       5    2.802
C_cc         0.1183   0.2874   27.324  2.792%      39   27.324   (5 样本仅 1 个门控命中; 命中样本单独值 0.5915)
C_rf         0.4181   1.0528    7.970  9.641%      16    7.970   (5 样本 3 个 warm 门控命中; 命中样本 0.569~0.901)
C_all        0.5351   1.3399   25.853 12.430%      36   25.853
```

### 3.4 RGB 域 8bit 网格残差直方图 (DSC_1715 补测, 分通道)

```
A_cc    rgb8残差: R≠0=70.18% G≠0=60.51% B≠0=72.95%  |d|≥1=67.88% ≥2=23.81% ≥3=6.87%  R/G/B max=40/43/47
A_rf    rgb8残差: R≠0=1.48%  G≠0=1.23%  B≠0=1.56%   |d|≥1=1.42%  ≥2=0.00%  ≥3=0.00%  R/G/B max=3/2/3
A_all   rgb8残差: R≠0=70.17% G≠0=60.53% B≠0=72.96%  |d|≥1=67.89% ≥2=23.81% ≥3=6.87%  R/G/B max=39/43/48
B_lut   rgb8残差: R≠0=15.53% G≠0=15.26% B≠0=16.15%  |d|≥1=15.65% ≥2=0.00%  ≥3=0.00%  R/G/B max=2/2/3
C_rf    rgb8残差: R≠0=44.02% G≠0=48.03% B≠0=16.45%  |d|≥1=36.17% ≥2=2.37%  ≥3=0.38%  R/G/B max=11/13/5
C_cc    rgb8残差: 全 0 (直通)
```

即: 去掉 colorcal 的 u8 往返后, 68% 的像素在 8bit 网格上移动 ≥1 级、24% 移动 ≥2 级
(个别达 47 级); 16-bit 导出口径下 ΔE16 ≈ ΔE(float) (如 A_cc 0.8106→各样本
ΔE16mean 与 float 相差 <0.001), **量化差异几乎全额传导到 16bit 产物**。

---

## 4. stage 分解: 哪一处占大头

| 量化点 | 独立贡献 (ΔE76 mean, 5 样本) | >1ΔE 像素占比 | 判定 |
|---|---|---|---|
| colorcal Lab u8 往返 (`A_cc`) | **0.81** (0.60~0.90) | **7.9%~31.6%** | **占大头** |
| refine sat_protection u8 (`A_rf`) | 0.012 (≤0.019) | 0% | 可忽略 |
| 两处合计 (`A_all`) | 0.81 (≈A_cc) | 24.7% | refine 在噪声级 |
| stylize LUT 8bit 网格 (`B_lut`) | 0.22 (0.20~0.24) | ≤0.05% | 次要 (均值低于 1 ΔE) |
| refine warm HSV 全 u8 往返 (`C_rf`, 门控命中时) | 0.57~0.90 | 7.6%~26.8% | 与 colorcal 同量级, 但仅 lr_baseline 类预设且 wb/覆盖率门控命中时发生 |

要点:

1. **colorcal 是主链路 gamma 域内的主导项**, 与深审预判一致 (Lab u8 步长 ≈1 ΔE)。
   分通道 |da|>|db|>|dL| (如 DSC_0470: 0.60/0.39/0.21) —— a/b 的 1.0 Lab 单位步长
   是主要误差源, L 的 0.392 步长次之; p95 1.50 / p99 2.2 说明四分之一以上像素越过
   1 ΔE 感知阈值, max 16~31 出现在饱和色/色域边缘 (u8 Lab 硬裁 vs float 路径经
   gamut_soft 软压缩的分叉被量化步长触发)。
2. **refine sat_protection 的 u8 中转可以忽略**: 它只量化权重图 (非图像本体),
   ΔE mean 0.012、无像素 >1ΔE —— 不值得为它改造。
3. **stylize LUT 代价中等且有限**: mean 0.22 ΔE 低于感知阈值, >1ΔE 像素 <0.05%,
   但 8bit 网格上 15.7% 像素移动 1 级 (max 2~3 级); float 重放成本极低
   (`lookup()` 现成), 可作为顺手项。
4. **warm HSV 全往返** (仅 lr_baseline 类预设): 命中时 0.57~0.90 ΔE、最高 26.8%
   像素 >1ΔE, 与 colorcal 同量级 —— 若产品常驻 lr_baseline 预设, 该处应与 colorcal
   一并改造。
5. 亮度维度: colorcal 代价在高调样本 (EV100 16.64) 最小 (0.60, 7.9%>1ΔE), 暗光与
   正常样本相近 (0.83~0.90, 24%~32%) —— 代价普遍存在, 非特定亮度区问题。

---

## 5. 结论与建议

**改造收益上限 = 三处全开的合计 ΔE**:
- 生产主线预设 (A, 无 LUT): **mean 0.81 / p95 1.50 ΔE76, 24.7% 像素 >1ΔE** —— 由
  colorcal 单点贡献; 16-bit 导出口径几乎无损传导 (ΔE16≈ΔE)。
- 叠加 LUT (B): 再 +0.22 ΔE (次阈值)。
- lr_baseline 类预设 (C, 门控命中): colorcal(scene/skin trim 路径) 0~0.59 与 warm
  HSV 0.57~0.90 可同时发生, 合计可达 ~1.1 ΔE 量级。

与 1 ΔE 感知阈值比较: colorcal 单点 mean 0.81 已逼近阈值, **p95 (1.50) 与约四分之
一像素明确越过阈值**; 该步长与"Lab 的 uint8 量化步长 ≈1 ΔE"的理论预判吻合。

建议 (按优先级):

1. **go: 优先只改 colorcal 一处** —— 收益占绝对大头 (0.81/合计 0.81), 且改法明确:
   - 输入端: `cv2.cvtColor(u8, RGB2LAB)` → `cv2.cvtColor(img_f32, RGB2LAB)` +
     坐标换算 (本脚本 `rgb_to_lab255` 即现成实现, 性能无差);
   - 输出端: native 内核输出缓冲 uint8 Lab → float Lab (colorcal.cpp 增 float 出口
     或复用本脚本的 numpy float 内核, 已验证与 DLL 0.0000% 不一致率), `LAB2RGB`
     走 cv2 float;
   - 预期消除 ~24.7% 像素的 >1ΔE 误差, 主观上等效于一次全图色彩重采样级别的提升。
2. **同批顺改 (低成本)**: stylize 直接用既有 `LUT3D.lookup()` float 路径 (仅当 LUT
   启用时受益 0.22 ΔE; 注意 256³ gather 表是性能优化, 需保留 u8 快路径或评估
   lookup 的耗时 ~数秒/24MP)。
3. **视产品策略决定**: `apply_warm_sat_gamma` 的全 u8 HSV 往返 (lr_baseline 命中时
   0.57~0.90 ΔE) —— 若 lr_baseline 常驻, 应一并 float 化; 若仅在个别场景启用, 可
   后置。
4. **no-go: refine sat_protection 的 u8 权重量化** —— 0.012 ΔE / 0% >1ΔE, 收益低于
   改造成本, 不动。

## 6. 局限与如实说明

- colorcal 快速路径 (`_apply_neutral_fast`, `color_cal.py:429` 的测量端 u8) 未测:
  两个生产预设均不走该路径 (§1.1), 其量化只影响 1/2 降采样测量值、输出仍为 float,
  预期代价远小于全量路径; 未造数。
- warm_sat 门控: `C_rf` 的门控读数来自 patched 侧 instrumentation (gain/coverage
  与生产同门控逻辑); DSC_2805 (wb_B=1.270) 与 DSC_0512 (hue_shift=0) 未触发 warm
  修改, 其 C_rf≈A_rf 量级 (0.006~0.010) 即 sat_protection 残差, 与预判一致。
- 单 stage 分解非严格可加 (后级非线性): A_all ≈ A_cc + A_rf 在数值上成立 (refine
  项在噪声级); C_all 与 C_cc+C_rf 在 DSC_0512 上略有出入 (0.591 vs 0.592), 属两级
  patch 相互作用的二阶效应。
- ΔE76 未含 CIEDE2000 的心理加权; 1 ΔE 阈值按通用 JND 近似引用。
- B 配置的 LUT 为 astia (32³); 其它 LUT 的量化代价随表密度/斜率略变, 量级一致。
- 测量在 float 输出口径比较 (导出 u16 量化之前), ΔE16 列已验证差异全额传导。

## 7. 与理论的交叉验证

A_cc 的实测 mean 0.81 ΔE 与理论估计吻合: Lab u8 量化舍入误差 (均匀分布) 的期望
ΔE = sqrt((0.392² + 1² + 1²)/12) ≈ 0.44, 加上输入端 RGB u8 (±0.5/255 gamma) 与
输出端 RGB u8 的各自 ~0.2-0.4 ΔE 贡献, 合计落在 0.6~0.9 区间; p95 1.5 / max 16-31
来自饱和色与色域边缘的裁剪分叉, 非均匀舍入。

## 8. 脚本用法与复现

```bash
# 全量测量 (5 张自动选样, EV100 分位; 全分辨率, 约 6-8 分钟/样本)
python scripts/measure_u8_precision.py --corpus K:/data/photo

# 本文实际运行 (指定样本)
python scripts/measure_u8_precision.py --samples \
  "K:/data/photo/厦门/1/DSC_0470.NEF,K:/data/photo/2026春节/DSC_0370.NEF,K:/data/photo/2026春节/DSC_0512.NEF,K:/data/photo/厦门/101XM_02/DSC_1715.NEF,K:/data/photo/厦门/103XM_04/DSC_2805.NEF"

# 单样本快速复核 (含 rgb8 残差直方图行)
python scripts/measure_u8_precision.py --samples "K:/data/photo/厦门/101XM_02/DSC_1715.NEF"

# 只看自动选样
python scripts/measure_u8_precision.py --pick-only
```

输出即 §3 贴出的格式 (每变体一行 ΔE76/分通道/rgb8/ΔE16 + 汇总表); 首样本自动执行
保真自检 (copy-fidelity / determinism / float 内核 vs DLL), 任一非 0 即中止。
依赖: 语料 `K:/data/photo`, DCP `resources/dcp/Nikon Z 5 2 RawLab LR Adobe Standard
Baseline.dcp`, 生产预设 `configs/styles/lr_adobe_standard_baseline.json` 与
`lr_baseline.json`, LUT 注册表指向的 `guanlan/luts`。脚本不修改任何 src/ 代码,
所有 patch 仅进程内 monkeypatch。
