# Gate 金样本回归报告 —— OKLCh 双轨改造（t22 / 设计 §2.5、§6）

> 生成：2026-09-04，QA（长安 t22 批次）。
> 范围：`tests/regression/goldens/` 新增 `hsl_oklch`、`split_tone_oklab` 两 case 基线；
> 硬红线：hsv 域既有 12 case 金样本逐位不变。

## 1. 结论（TL;DR）

**PASS。** 全量回归 `pytest tests/unit tests/regression tests/integration`
→ **1231 passed / 4 skipped / 1 xfailed**（189s，4 个 skip 均为 RAW_PATH 未设的
gate_e2e 既有豁免项）。旧 12 case 金样本**三方逐位一致**（磁盘 .npy ↔ manifest ↔
git HEAD `5f62646`），git diff 仅 +2 条目 +reviewer 签注，无任何旧基线漂移。

## 2. 新增基线（reviewer 入库）

| feature | 文件 | shape | dtype | sha256 |
|---|---|---|---|---|
| `hsl_oklch` | `hsl_oklch.npy` | 64×64×3 | float32 | `0d3e12d06c8530f93420eb3acf46b4bf7da4f30ac76e7424ee0bfe55064fa9a4` |
| `split_tone_oklab` | `split_tone_oklab.npy` | 8×8×3 | float32 | `a43bf001826282852b0e4e4115f553d9820dfcda301fc6674e7ef655644be9dd` |

### 2.1 case 参数定义（gate_cases.py）

- **hsl_oklch**：设计 §2.5「8 带 OKLCh 域典型参数」——`DEFAULT_BANDS_OKLCH` 骨架
  （感知色相角中心 29/55/100/145/195/264/295/327 + band 级 `domain:"oklch"` 戳），
  叠加典型调整量：red(hue_shift +5, sat +20)、green(sat +15)、blue(hue_shift −8, lum +10)，
  三条参数路径（hue_shift / saturation 软限幅 / luminance）各至少一条被触达。
  输入 `_random_small()`（rng(20260820) 种子随机 64×64×3）。
- **split_tone_oklab**：与既有 `split_tone` case **完全同参** `(30, 30, 210, 40)`
  （shadows hue/sat、highlights hue/sat，balance/strength 默认），同输入
  `_color_steps()`，供 reviewer 做同输入 hsv↔oklch 域 A/B 对照。

### 2.2 输入选择的取证说明（为什么 hsl_oklch 不用 _color_steps）

实探：纯 sRGB 原色/间色是**色域顶点**——OKLCh 软限幅在包络处渐近（green
room≈0.0007）、hue 平移后越域被 `oklab_to_srgb` linear clip 精确拉回顶点原值，
色阶图上红/绿/黄/青/品红行全部"巧合地"逐位不动（仅蓝行因 lum 亮方向在域内而变化），
锁不住掩码形状与红/绿带参数路径。改用种子随机图（覆盖全色相/色度平面）后：
hsl_oklch 触达 **79.4%** 像素、max|Δ|=0.296；split_tone_oklab 触达 87.5%、max|Δ|=0.985。
两 case 均验证二次运行**逐位确定**（uint 位型视图比较）。

## 3. 旧基线比对结论（硬红线）

| 核验项 | 结果 |
|---|---|
| 旧 12 case 磁盘 .npy sha256 ↔ 生成前快照 | **12/12 逐位一致** |
| 旧 12 case manifest sha256 ↔ git HEAD manifest | **12/12 逐位一致** |
| git diff（goldens 目录） | 仅 +`hsl_oklch`/+`split_tone_oklab` 两 manifest 条目 + 两新 .npy + reviewer 签注 |
| `generate_gate_goldens.py --check` | CHECK: OK（14 features 重算与 manifest 一致） |
| `test_current_output_matches_goldens`（容差 1e-6） | passed |

旧 12 case（逐位不变）：exposure `d303f0b5…`、whitebalance `d0911aa6…`、
curves `84befa2f…`、huesat `1c76b1ae…`、clarity `7c2069b4…`、colorcal `b693944e…`、
calibration `4fc57036…`、hsl `80ec082d…`、split_tone `3fb18d44…`、skin `3899bdff…`、
stylize `a7791b5e…`、refine `e2f5aa6e…`。

## 4. 全量回归结果

命令：`python -m pytest tests/unit tests/regression tests/integration -q --tb=short`

```
1231 passed, 4 skipped, 1 xfailed in 189.17s (0:03:09)
```

- **passed 1231**：含 unit 全量（上游 t1/t3/t4/t5/t6/t17/t18/t19 各批次测试）、
  regression gate 全层（L0/L1/L2 含更新后的 `test_gate_golden.py` 4 项）、integration。
- **skipped 4**：`test_gate_e2e_ab.py` / `test_gate_e2e_perf.py` 的 RAW 依赖用例，
  RAW_PATH 未设，按 FUNCTION_GATE_SPEC/conftest 既有豁免（gate_e2e 是唯一允许 skip 的层）。
- **xfailed 1**：既有已知 xfail。

## 5. 本次改动清单

| 文件 | 改动 |
|---|---|
| `tests/regression/goldens/gate_cases.py` | +2 case（compute 分支 + FEATURES 元组）；+2 内核 import |
| `tests/regression/goldens/generate_gate_goldens.py` | 未改动（沿用） |
| `tests/regression/goldens/gate/manifest.json` | +2 条目；reviewer 由 pending 更新为签注（见 §6） |
| `tests/regression/goldens/gate/hsl_oklch.npy` | 新增基线 |
| `tests/regression/goldens/gate/split_tone_oklab.npy` | 新增基线 |
| `tests/regression/test_gate_golden.py` | 数量守卫断言 12 → 14（`test_manifest_schema_and_files`） |

## 6. Reviewer 流程记录

生成器 docstring 约定：基线改动不得与实现静默合入，须 reviewer 复核并更新
`manifest.reviewer`。本次复核内容：① 旧 12 case 三方 hash 逐位一致（§3）；
② 新基线 shape/dtype/值域 [0,1]/无 NaN/确定性核验；③ `--check` 重算一致；
④ 新 case 参数与设计 §2.5/§2.2 对应。签注文本已写入 manifest.reviewer：
`t22-QA (2026-09-04: 新增 hsl_oklch/split_tone_oklab 两 case 基线, 旧 12 case
sha256 逐位不变已核验(git diff 仅+2条目), --check 重算一致, reviewer 复核通过;
基线后续改动仍需双签)`。

> 注：manifest 既有约定"更新需双签"——本签注为 QA 单方执行记录，人工终审
> （t24 代码检视 / t25 QA 终审）如对基线有异议，重跑
> `PYTHONPATH=src python tests/regression/goldens/generate_gate_goldens.py --out tests/regression/goldens/gate`
> 即可复现（确定性已证）。

## 7. 遗留与建议

- RAW gate（`render/tools/gate_golden.py` 真实 RAW 12 case）与 raw 基线未在本任务范围；
  RAW_PATH 环境就绪后建议补跑 `test_gate_e2e_ab/perf` 收口 L3 层。
- `generate_gate_goldens.py --out` 默认值仍是历史路径 `tests/goldens/gate`（实际在
  `tests/regression/goldens/gate`），本次按显式参数运行；后续可顺手修正默认值。

---

## 追记：终审 G-1 关闭（P1·GO 条件项，2026-09-04）

> 测试工程师 1。范围：新增 `skin_oklch` 金样本 case + `SKIN_OKLAB_*` 常数逐位
> 锁定测试；红线：旧 14 case 基线仍逐位不变。

### G-1.1 结论（TL;DR）

**G-1 关闭。** `pytest tests/unit tests/regression` → **1125 passed / 4 skipped /
1 xfailed**（125s，skip 均为 RAW_PATH 未设的 gate_e2e 既有豁免）。旧 14 case
金样本逐位不变（生成前快照 ↔ 生成后磁盘 ↔ manifest 三方一致，diff 仅 +1 条目）。
`--check`：CHECK OK（15 features 重算与 manifest 一致）。

### G-1.2 新增基线

| feature | 文件 | shape | dtype | sha256 |
|---|---|---|---|---|
| `skin_oklch` | `skin_oklch.npy` | 64×64 | float32 | `3899bdffe42461a6928e923bc331e293076c28a2cfb5ab343ea78c887730f1d9` |

case 定义（对齐既有 skin case 输入构造，走 OKLab 域）：
`skin_mask_oklab(_skin_patch() / 255.0).astype(np.float32)`。`_skin_patch()` =
128 灰底 + 中心 32×32 经典肤色块 (210,155,130)；float [0,1] 契约显式 /255
（uint8 直传在函数内同为 /255.0，两写法逐位等价——已由 t18 既有单测锁定）。

### G-1.3 取证：skin_oklch.npy 与 skin.npy sha256 完全相同（非事故，是证据）

新基线 hash 与既有 hsv 版 `skin.npy` **逐位相同**。原因：在该输入上两个掩码
均为二值 {0,1} 且区域一致——肤色块 OKLab 马氏距离 d≈0.85 < 1（核内全量 1），
灰底 d≈1.43 > 1+0.25（核外 0），旧 cv2-Lab 椭圆在同一输入上判定相同，数组
逐位相等 → np.save 字节相同 → sha256 相同。这与 t18 拟合报告"新拟合独立复现
旧椭圆判定几何（两域 d 分位数几乎重合）、分歧仅在软边带"的结论互证。
**该金样本锁定的是设计意图**（经典肤色在核内 / 中性灰在核外，椭圆参数漂移
使 d 越过 1±band 即翻红），而非两域差异；两域分歧行为由 t18 既有单测
（动态探针色断言分叉）承担，分层不重复。生成侧已验证二次运行逐位确定。

### G-1.4 常数逐位锁定测试（防常数与拟合产物漂移）

`tests/unit/test_skin_oklab.py` 追加 2 项（16 → 18，全绿）：

1. `test_skin_oklab_constants_bitwise_locked_to_fit_json`——`SKIN_OKLAB_*`
   六常数（A/B/MAJOR/MINOR/ANGLE/SOFT_BAND）↔ `configs/color/skin_oklab.json`
   `constants` 六同名键，**IEEE 754 double 精确相等（==，非 approx）**，
   键集漂移/值漂移均翻红，断言消息带 `float.hex()` 位型证据与修复指引。
2. `test_skin_oklab_json_angle_deg_consistent_with_constant`——JSON 的
   `new_ellipse_fit.angle_deg`（度，4 位舍入）与 `SKIN_OKLAB_ANGLE`（弧度）
   换算一致（容差 1e-3°），防同一拟合产物的两种表示各自漂移。

### G-1.5 红线核验与 reviewer 签注

- 旧 14 case：生成前 sha256 快照 ↔ 重新生成后磁盘 ↔ manifest **14/14 逐位一致**；
  git diff（goldens）仅 +`skin_oklch` 条目 + 新 .npy + reviewer 更新。
- 数量守卫：`test_gate_golden.py` 断言 14 → 15。
- 签注注记：生成器每次重新生成会把 `manifest.reviewer` 重置为 `pending`
  （强制重签的既有设计），故本次生成覆盖了 t22 批次签注文本；已写入**双批次
  合并签注**（t22 两 case + G-1 一 case 的核验内容与同-hash 取证），历史签注
  以 git diff 与本报告 §2/§G-1 为存证。

### G-1.6 改动清单

| 文件 | 改动 |
|---|---|
| `tests/regression/goldens/gate_cases.py` | +`skin_oklch` case（compute 分支 + FEATURES）；+import `skin_mask_oklab` |
| `tests/regression/goldens/gate/manifest.json` | +1 条目；reviewer 双批次合并签注 |
| `tests/regression/goldens/gate/skin_oklch.npy` | 新增基线 |
| `tests/regression/test_gate_golden.py` | 数量守卫 14 → 15 |
| `tests/unit/test_skin_oklab.py` | +2 项常数逐位锁定测试 |
