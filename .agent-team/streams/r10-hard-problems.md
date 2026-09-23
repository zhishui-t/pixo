# streams/r10-hard-problems.md — super-dev 攻坚流 (r10)

> colorcal oklch 域 native 内核: 堵 F11 实测 15× 性能鸿沟 (8.5ms→131ms @512,
> 4096px 外推 8.4s/图)。执笔 2026-09-07, super-dev。

## 1. 问题定义

`modules/color_cal.py` 的 native 快路径原先只认 hsv 域——oklch 域旁路 native
走纯 Python float 路径。但读码发现: **oklch 与 hsv 的全量路径算术完全相同**
(中性轴/曲线/色相/饱和增益全在 float Lab 域), 唯一分叉点是
`_skin_region_mask`: hsv → float Lab 椭圆, oklch → `core/skin.py::skin_mask_oklab`
(原始 gamma sRGB → OKLab a-b 椭圆)。F11 A/B 报告也证实 (算术差
ΔE(hsv-native, hsv-python)=0.000 → 复合差 100% 来自掩码域)。

所以问题收敛为: **native 内核把掩码源换成 OKLab 椭圆, 能否与
`skin_mask_oklab` 数值对齐, 且成本回到 native 量级?**

## 2. spike 证据 (产物在 `.agent-team/spike/`, 可复现)

### 2.1 数值对齐可行性 (`spike_oklch_mask.cpp/.py`)

C++ 原型逐式复刻 `skin_mask_oklab` 链 (f32→f64 clip [0,1] → sRGB EOTF
pow → M1 → cbrt → M2 → 椭圆 → f32 smoothstep), 常数以 **hex 字面量**嵌入:
- 中心 `np.float32(0.01516/0.06125)` 舍入后展宽 (十进制 0.06125 的 f32
  **不是精确值**, 直接写 double 差 1 ULP —— 实测踩到);
- `np.cos/np.sin(0.191122)` 的 f64 结果 (消除 libm cos/sin 跨实现风险)。

```
[OK] random_[0,1]: bit-exact (100000 px)
[OK] random_[-0.3,1.3]: bit-exact (100000 px)      ← 越界 (入参清洗 clip)
[OK] random_8bit_grid: bit-exact (100000 px)
[OK] skin+neutral+edges: bit-exact (546 px)         ← EOTF 0.04045 边界/椭圆边/极值
```
**结论: 掩码链可逐位对齐** (pow 走 ucrt 与 numpy 同源, v1.4.0 oklab 内核先例)。

### 2.2 性能结构剖析 (`spike_oklch_bench*.cpp`, 512², 8 线程)

| 分解 | 耗时 | 说明 |
|---|---:|---|
| 完整掩码 (ucrt pow+cbrt) | 13.7 ms | pow ≈57%, cbrt ≈33% (ucrt cbrt 60ns/次, 比 pow 还慢) |
| cbrt 换 msun 复刻 | **9.2 ms** | 掩码结果 0/262144 px 差异 |

关键事实链 (探测过程, `spike_cbrt_probe*.cpp`):
- `np.cbrt == ucrtbase.cbrt` 逐位 (20k 对拍 0 差异) → 对齐锚是 ucrt;
- **ucrt cbrt ≠ FreeBSD msun** (31% 输入差 1 ULP f64, 复刻验证) → 无法用
  "正确舍入 cbrt" 或 msun 复刻做到与 ucrt 逐位;
- 但 msun 复刻与 ucrt 差 ≤1 ULP f64 → 经掩码链 f64→f32 舍入后**实际逐位
  一致** (262144 px 0 差异; 翻转期望 ~1e-8/px; 即使翻转, 掩码差 1 ULP f32
  ⇒ Lab 输出差 ~2.4e-7, 远低于 1e-6 容差) —— 落在任务书"逐位或紧容差
  (≤1e-6)"授权带内。
- pow 保持 ucrt 调用 (与 numpy 逐位, 无自由度)。

**spike 结论: 路线可行; 掩码 bit-exact; msun cbrt 杠杆省 ~33% 掩码成本。**

## 3. 最终实现

### 改动文件
| 文件 | 改动 |
|---|---|
| `native/src/colorcal.cpp` | ① `CbrtFast`: FreeBSD msun s_cbrt.c 逐句复刻 (常数/操作序勿改, 出处注释); ② `SkinMaskOklab(r,g,b)`: OKLab 椭圆掩码单像素 (常数 hex 同源); ③ `ApplyColorCalLabF32Oklch(lab, rgb, labOut, w, h, params)`: 与 `ApplyColorCalLabF32` 逐式对应, 唯一差异=掩码源; OpenMP `schedule(dynamic, 2048)` (共享机器抗负载倾斜); ④ C ABI 导出 `PixoRenderColorCalApplyLabF32Oklch` |
| `native/src/colorcal.h` | 内部 + C ABI 声明 (含对齐契约注释) |
| `native/src/abi.cpp` | 版本 1.4.0 → **1.5.0** (+changelog) |
| `render/_native/__init__.py` | 符号绑定 (hasattr 守卫, 旧 DLL 不影响加载) + 包装 `colorcal_apply_lab_f32_oklch(lab, rgb, params)` + 模块 docstring/__all__ |
| `modules/color_cal.py` | native 接线区: `_native_available()` 下按域分派 (hsv→F32, oklch→F32Oklch, rgb 传原始 img); DLL<1.5.0 抛 RuntimeError→`native_ok=False`→纯 Python 回退 (回退链 native→Python float→u8 legacy 三层不变); 更新旁路时期的过时注释 |
| `native/README.md` | 内核清单刷新 (补 1.2~1.5 导出) |
| `tests/unit/test_native_colorcal_oklch.py` | **新增 6 测试** (见下) |

**未碰**: hsl/split_tone/skin 的 default_params、loop.py/decide、既有内核
(hsv F32/u8 legacy/oklab 转换内核逐字节未动)。

### 接口
```c
// rgb = 校正前 gamma sRGB f32 (H,W,3) —— 掩码取原始像素口径 (同 Python 侧)
PixoRenderColorCalApplyLabF32Oklch(const float* lab, const float* rgb,
                                   float* labOut, int w, int h,
                                   const PixoRenderColorCalParams* params);
```

### 测试证据 (`tests/unit/test_native_colorcal_oklch.py`, 6 passed)
1. `test_oklch_mask_isolated_bitwise` — 仅 skin_trim/protect 激活 (无
   exp/interp libm 源) → 与 `skin_mask_oklab` 参考**逐位一致**, 40 trial
   含随机+越界+EOTF 边界语料 (实测 0/276480 px 差异) —— 新增对齐面的
   ≤1e-6/bitwise 门;
2. `test_oklch_kernel_matches_reference` — 全参数 → Lab |Δ|≤4e-5
   (实测 2.29e-5 = 1 ULP f32 @|a|~128; **同语料 hsv 内核同值 2.289e-5** →
   地板是 np.exp/np.interp 的共享 libm ULP, 掩码零新增分歧);
3. 零参数恒等 (bit 级);
4. stage 级 native vs Python 回退 (RGB mean≤1e-5 / max≤2.5e-3, 同
   test_native_colorcal 口径);
5. 旧 DLL (未导出符号) → RuntimeError → 回退纯 Python 且输出一致;
6. 版本-符号一致性门 (≥1.5.0 必导出)。

回归: `test_native_colorcal + test_native_oklab + test_native_abi +
test_native_fallback + 新文件` → **31 passed**; 全量 unit → 1295 passed
(1 失败为 `test_render_public_adapters` pyproject `data/golden` 断言,
**先在红**、pyproject 本次未碰, 非本任务引入);
`tests/integration/test_oklch_preview_e2e.py` → 4 passed。

## 4. 性能前后对比 (512×512, 同 harness 同会话, median of 11, 本机)

| 轨 | 前 | 后 | 倍率 |
|---|---:|---:|---|
| oklch 全 stage | 189~213 ms (纯 Python) | **15.5~19.6 ms (native)** | **提速 ~11-12×** |
| oklch vs hsv native | 15.3× (F11: 131/8.5) | **median 1.99×** (5 次采样 1.52/1.86/1.99/2.00/2.15, 共享机器噪声) | 达标线 ≤2× 贴线过 |
| 内核级 (无 stage 开销) | — | hsv 3.04 / oklch 11.79 ms (掩码增量 8.75 ms) | — |
| 4096px 外推 | 8.4 s/图 | **~0.75 s/图** (线性) | auto 闭环交互成本回收 |

## 5. 金样本/基线处置 (报队长)

**本次零基线影响**: gate 的 colorcal case 直接调旧 u8 内核 (不经 stage 路由);
全管线 gate case 用缺省域 (hsv, 本次逐位未动); oklch e2e 只 patch
hsl/split_tone 域; 现无任何 oklch-colorcal 基线。**dev-2 第二批切换
(skin+colorcal 缺省翻 oklch) 后**, colorcal oklch 成为缺省路径, 金样本像素
变化属域切换本身预期 (F11 已证质量不劣于), 基线重生成权在队长。

## 6. 遗留 / 降维交接

1. **2× 门贴线 (1.99× median, 噪声带 1.5~2.3×)**: 剩余大头是 ucrt pow
   (~57% 掩码成本, bit-exact 无自由度)。已识别未做的下一杠杆: SSE2 向量
   多项式 pow (~1e-16 rel, 同 msun-cbrt 风险类, 掩码翻转期望 ~1e-9/px),
   估掩码 8.75→~4 ms → 比率 ~1.5×; 手搓超越函数数值风险 vs 边际收益,
   未擅自做——若队长要求严格 <2× (含负载下), 可立项。
2. **ucrt 数学函数同源事实** (入文档): np.cbrt/np.power == ucrtbase 逐位;
   ucrt cbrt ≠ FreeBSD msun (31% 输入差 1 ULP)。Windows 更换 ucrt 实现
   时掩码 bitwise 断言需复验 (测试门自动把守)。
3. **SkinStage oklch 掩码仍走 numpy** `skin_mask_oklab` (~150ms @512):
   同一 `SkinMaskOklab` 内核可直接复用为其 native 化底座 (皮肤流缺省翻转
   前建议同步评估, 否则 skin oklch 会成为下一个 15× 点)。
4. **DLL 并发重建陷阱** (团队纪律): 有 python 进程持有 DLL 时 build.bat 的
   copy 步骤失败且 make 删除产物。处置: rename 旧 DLL (锁文件可改名不可
   覆盖) → rebuild。本次 F11 进程持锁即用此法, 无需杀队友进程。
5. spike 产物 (`spike_oklch_*`, `spike_cbrt_*`, `_perf_check.py`) 留
   `.agent-team/spike/` 作复现证据, 结论回收后可删。

**一句话结论**: spike 证明 oklch 掩码可逐位对齐 (bit-exact, 30 万像素含越界
/EOTF 边界 0 差异; msun cbrt 复刻经 f32 舍入后同样逐位), native 内核落地后
oklch 全 stage 15×→**约 2×** hsv native (median 1.99×, 512px 131→~17ms,
提速 ~11×), 掩码隔离路径对齐精度逐位、全参数路径 1 ULP f32 (与 hsv 内核同
地板)。

## 7. 常数同步收尾 (r10 追加, 2026-09-07)

**事件**: dev-1 的 skin 椭圆 r10 重拟合落地 (`core/skin.py` 六常数 + 软带
0.25→0.31, 三验收全过) 后, 本内核 `SkinOklab*` 硬编码副本失同步 →
`test_native_colorcal_oklch` **3 红** (mask-isolated bitwise /
kernel-vs-reference / stage-vs-fallback —— 正是常数耦合面, 防线按设计抓红)。

**处置** (硬编码方案, 队长裁决): 按原对齐纪律从 Python 运行时重取新常数
写回 `colorcal.cpp` (**勿裸十进制 double**):
| 常数 | 新值 (r10 重拟合) | cpp 字面量 |
|---|---|---|
| 中心 A | 0.015127 | `0x1.efae7ap-7` (np.float32 舍入展宽) |
| 中心 B | 0.061263 | `0x1.f5ddd2p-5` (同上; 十进制 f32 非精确) |
| 倾角 | 0.196323 | cos `0x1.f62a2ab9fefa4p-1` / sin `0x1.8f7dddf635799p-3` (np f64 结果) |
| 半轴 | 0.049594 / 0.047463 | round-trip 十进制 (精确) |
| 软带 | **0.25→0.31** | `0.31f` (NEP50: f32 除以标量按 f32, 两侧同为 f32 舍入的 0.31) |

cpp 注释同步加**双源警告**指向 tech_debt #18。

**证据**: DLL 重编 (build.bat, 1.5.0, 09:40) →
`test_native_colorcal_oklch` **6 passed** (3 红转绿);
native 回归 `test_native_colorcal + test_native_oklab + test_native_abi +
test_native_fallback` → **29 passed**; 邻域 `test_skin_oklab +
test_film_cards_oklch + test_hsl_oklch` → 44 passed;
`tests/integration/test_oklch_preview_e2e.py` → 4 passed。

**记债**: `docs/tech_debt.md` **#18** —— 椭圆常数双源, 本次手工同步恢复;
清偿条件 = 下次椭圆变更前必须参数化 (内核签名传常数, Python 侧单源),
并借机评估 SkinStage oklch 掩码 native 化 (§6.3 遗留, 同一内核复用)。
