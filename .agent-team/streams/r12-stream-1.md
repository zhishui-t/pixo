# r12-stream-1 简报（dev-1）— gate skin 软边带探针 + 双肤区尾部记录

> 2026-09-07 · qa `.r10b_ok` 观察窗扫尾两任务。

## 任务1：gate skin_oklch_softband 软边带探针 case（20→21 features）

### 盲区与设计

- 盲区实证：R10 重拟合改了半轴+软带（SOFT_BAND 0.25→0.31），但
  skin/skin_oklch 两 case 输出零变化——输入是饱和经典肤色（核内 d≈0.85，
  mask≡1）+ 远外灰底，对软边带**零敏感**。
- 设计要点（避坑）：探针色若从椭圆**活常数**推导，常数变更时输入随之平移、
  掩码恒定——盲区重现。故以经典肤色 sRGB (210,155,130) 为**固定锚**：
  沿两条色相射线（肤色色相 45.5° / −30°=15.5°）扫色度
  C∈[0.3,1.8]×C_skin，32 步 × 2 射线 = 64 行，每行均匀纯色。
- 实测覆盖（r10 修后常数）：射线 A d∈[0.67,1.76]（核内 20/软带 5/核外 7）、
  射线 B d∈[1.16,2.39]（软带 11/核外 21）；全部探针色 sRGB 色域内无 clip。
- 直接捕获 `skin_mask_oklab` 掩码（纯函数，无 wants 门控介入）。

### 敏感性实证（盲区关闭的证据）

| 扰动 | 探针响应 |
|---|---|
| 软带 0.25→0.31（R10 实际变更） | **3968/4096 像素变化（62/64 行）**，max\|Δmask\|=0.156 |
| 半轴 MAJOR +10%（committed 测试） | 掩码输出变化（`test_skin_oklch_softband_probe_not_blind`） |
| 过渡带覆盖守卫 | `test_skin_oklch_softband_covers_transition_band`：≥8 行掩码 ∈(0,1)，C 范围与椭圆失配即翻红 |

### 落位与基线

- `tests/regression/goldens/gate_cases.py`：FEATURES +`skin_oklch_softband`
  （20→21）+ `_skin_softband_probe()` + compute 分支（设计全文见函数 docstring）
- 基线：`python tests/regression/goldens/generate_gate_goldens.py` 全量重生成
  —— **既有 20 case 字节零漂移**（git status 仅 manifest + 新 npy）；
  新增 `skin_oklch_softband.npy`（初代基线 dev-1 生成，**报 qa/队长复核**）
- manifest reviewer 旧文前缀式追加 R12 批次记录（沿惯例，避免 pending 翻红）
- `tests/regression/test_gate_golden.py`：数量断言 20→21（注释同步）+
  新增 2 验收测试（非盲 + 过渡带覆盖守卫）

### 验证

```
python -m pytest tests/regression/test_gate_golden.py -q → 6 passed
```
（原 4 + 新 2；含 manifest schema/sha256/--check 零漂移/逐 feature 1e-6 比对）

## 任务2：双肤区强度尾部 9 张亚 JND 记录

落点：`.artifacts/skin_colorcal_oklch_ab.md` 新增「§6 观察窗记录」节。

- 9 张 = golden_high_key_bright（金样本，B/A 0.850 欠磨侧）+
  DSC_5268~5275（full_scan 同场景连拍 8 张，B/A 1.179~1.412 过磨侧），
  逐图 A/B 作用量、B/A、|B−A| 全表在案。
- 判定：**记录即可，无需处置**。依据：|B−A| ≤0.150 ΔE2000，低于权威 JND
  （2.3）一个数量级、仅为保守带（1.0）的 15%；方向混合无一致偏置；
  比值尾部由 A 侧绝对值偏小放大（60 张有作用图中位 B/A=1.000 入带）。
- 复议触发条件已记录（连拍场景磨皮观感反馈 → 以本节为基线复测）。

## 遗留

无新增。此前 r11 的观察项（scene 分类器接线/RAW 基线重生成裁决）仍在队长侧。
