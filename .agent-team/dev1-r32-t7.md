# dev1 R32-T7 报告 · 曝光六项优化校准（RT 曝光工具链对照吸收）

日期：2026-09-23 ｜ 角色：dev-1 ｜ 分支：render-core-integration（未 commit）
执行引擎：宿主原生（R32 设计 §4 兜底条款）。

**一句话：吸收 1 项落地（exposure `mode="match"`——RT getAutoExp 八分位直方图匹配的 numpy 移植，输出 EV + black/hlcompr/contr 的 RT 单位建议并写 metrics，显式开启缺省 baseline 不变）；六键数学、黑白点语义、HL compression 三项裁决"保持"；最重发现 = RT match 的 EV 目标并非纯中灰锚定——含"直方图顶点推向 clip"的第二目标项（中灰高斯输入实测 +0.37EV vs 我方中位锚定 0.0），两口径差异已数据化留档。**

---

## 1. RT 侧侦察（ipshadowshighlights.cc 203 行 + improcfun.cc getAutoExp:5440-5680 + params @ 6c4cb59）

### 1.1 Shadows/Highlights（`params.sh` → `ImProcFunctions::shadowsHighlights`）
- **域**：工作空间 → **Lab L\***（32768 尺度）；amount = hightli·0.7 / shado·0.6。
- **算法**（回答任务书"基于什么数学"）：**pow4 亮度掩码 + guided filter 局部细化**——掩码 `hl: l>thresh?1:pow4(l·scale)`、`sh: l≤thresh?1:pow4(scale/l)`，再用 **guidedFilter(L, mask)** 以 L 为引导做局部结构细化（半径 = rad·10/scal）；然后 L\* 域 gamma 映射 `pow(L/32768, base)`，base = 4^(amount/100)（提亮）/倒数（压暗）；阴影额外叠一条 **DCT_NURBS 暗部对比曲线**（0.125/0.25/0.375 锚点，contrast = 2^(amount/100)）；提阴影时**色度按比例保持**（a/b × L 比例混合）。逐像素 `intp(blend, f[L], L)` 混合。
- 定性：RT S/H = "亮度掩码 + 导引滤波局部细化 + 全局 L\* gamma 映射"，**非局部对比增强**。

### 1.2 Black/White 点 + Highlight compression（CurveFactory，exposure 曲线）
- `toneCurve.black`（含 blackred/blackgreen/blackblue 逐通道）= 曲线前**数据钳制**（硬黑点）；`hlcompr/hlcomprthresh` = 曝光曲线**肩部压缩**（`shoulder = (65536/exp_scale)·(thresh/200)+0.1`，`comp = max(0,expcomp+1)·hlcompr/100`）。

### 1.3 auto-matched 曲线（`getAutoExp`，T5 登记的 vhist16 联动源头）
- 输入：65536 桶工作空间 Y 直方图（firstAnalysis，pre-processing）+ clip%（缺省 0.02）+ histcompr。
- 统计：sum/average/median → **octile 8 分位（log2(1+j) 域）** → 过曝检测（octile 6/7 超上限 → 外推）→ ospread（八分位间距加权和）→ **clippable = sum·clip** 的白/黑 clip 点。
- 输出五参：`expcomp` = 中灰锚定估计（`log2(midgray·scale/(ave−shc+midgray·shc))`，**midgray = 0.1842 线性中灰**）与直方图顶点估计（octile 外推 + `log2(scale/rawmax)`）的**几何/算术混合**；`black = shc·corr`（corr = √(gain·scale/rawmax)）；`hlcompr` = 把 whiteclip 经增益拉回顶部的级数近似（×2.3 系数）；`bright` = 控制笼包络近似（√(median·ave)→midgray）；`contr = 50(1.1−ospread)`。
- 黑帧/退化 → **全零安全返回**（RT 同）。

## 2. 对照表与差集

| 项 | RT | pixo T1.5 | 裁决 |
| :--- | :--- | :--- | :--- |
| 曝光自动 | getAutoExp：中灰锚定 + 顶点-clip 目标 + 八分位对比（5 参） | mode="auto"：探针**中位 log2 锚定**到复合影调锚点（R24 同源），主体框可选 | **部分吸收 A1**：新增 `mode="match"`（八分位匹配移植），与既有 auto 并存 |
| 阴影/高光恢复 | Lab L\* + pow4 掩码 + **guided filter 局部细化** + NURBS 暗部对比 + 色度保持 | tone highlights/shadows：**全局亮度带通掩码**（0.55-0.78 / 0-0.14）乘性 | **保持**（六键=全局影调带语义，达标；RT 的局部 guided-filter 恢复是独立工具语义 → **T8 台账登记**） |
| 黑白点（含逐通道） | toneCurve.black + blackred/green/blue：**硬钳制** | blacks/whites：带通**乘性**键，无独立数据黑点，无硬 clip（设计特性） | **保持**（不吸收硬钳制语义；我方白/黑点不硬 clip 为验收项） |
| HL compression | 曝光曲线肩部（hlcompr/thresh） | soft_highlight_rolloff + highlight_compress_curve + shoulder | **保持**（能力已覆盖） |
| 下采样/性能 | 预览级 + OpenMP sections + LRU 缓存 | 探针 256 长边固定网格 + 向量化 | 等价，保持 |

## 3. 实验（.artifacts/_r32_t7_exposure.py → _r32_t7_exposure.json）

- **E1 getAutoExp 移植验证**（4096 桶合成高斯直方图）：
  - 中灰直方图（center=0.1842）：ev +0.369（RT 公式含"顶点推向 clip"目标项，非纯中灰锚定——**口径差异如实记录**；我方中位锚定同输入 ev=0.0）；
  - 暗场（center=0.03）：ev +1.106（提亮方向 ✓）；
  - 亮场（center=0.55）：ev −0.177（压暗 ✓）；
  - 黑帧：全零安全返回 ✓；
  - 方向一致性：暗/亮与中位锚定同号 ✓（中灰集因 RT 顶点目标项异号，见上）。
- **E3 六键 ramp 口径扩展**（1024 级线性 ramp，±0.8 满载，T1.5 口径数据化）：四键 × 双向全部**单调**、内域 [0.05,0.95] **无 ≥3 采样硬 clip 平台**、带外隔离均值（highlights 带外 <0.4 / shadows >0.45 等）数值见 json——六键数学达标。
- 移植过程修正两处域换算（bin 域 ↔ scale 域：`ave = ave_bins·bin_w`；`15.5 → log2(n)−0.5` 泛化）——移植自测发现的实现错误，已在最终 json 中修正。

## 4. 吸收落地（diff 清单）

| 文件 | 改动 |
| :--- | :--- |
| `src/pixo/render/modules/exposure.py` | 新增 `auto_match_suggest(hist_counts, *, clip, midgray, scale)`：RT getAutoExp 八分位数学 numpy 移植（GPL 出处标注；通用 bin 数泛化 `15.5 → log2(n)−0.5`、bin/scale 域显式换算）；`ExposureStage` 新增 `_match_ev` 方法与 `mode="match"` 分支（ev = 建议 expcomp，同 max_ev 钳位；black/hlcompr/contr 以 RT 原单位写 metrics `exposure_match_*` **不自动改写 tone 参数**——编辑动作显式化）；schema 注释更新 |
| `tests/unit/test_exposure_match.py`（新，6 用例） | 中灰 EV 近零 / 暗正亮负 / 黑帧安全零 / stage 端到端 match（256² 输入，探针像素量充足）/ 缺省 baseline 不变 |
| `tests/unit/test_haldclut_convert.py` | （T3 遗留，上棒已完成）容差收紧 |

**不动项（保持裁决）**：六键带通掩码数学（E3 达标）；黑白点硬钳制语义（不吸收）；HL compression（已覆盖）；RT S/H guided-filter 局部恢复（T8 台账）；getAutoExp 的 bright/contr 自动写 tone 参数（仅建议输出，避免编辑动作隐式化）。

## 5. 门禁证据

- 定向：test_exposure_match（6）+ test_exposure（25）全绿；
- 全量回归（最终代码态）：见文末回填；
- 未 commit；未动 master。

## 6. 待队长/reviewer 关注

1. `mode="match"` 的 black/hlcompr/contr 建议仅进 metrics 不进参数——"自动改 tone 键"需要产品决策（RT 是直接改写五个参数），如需完全对齐 RT 交互可后续加 `match_apply=true` 开关。
2. match 模式依赖探针像素量：16 像素级小图会触发 RT 同款整数八分位量化退化（安全零）；生产探针 256 长边 ≈4.4 万像素无此问题（测试已用 256² 并注明边界）。
3. RT S/H 的 guided-filter 局部恢复建议进 T8 吸收台账（独立工具语义，cv2.ximgprocguided 或自实现 guided filter 为实施前提）。

（回归结果回填处）**全量回归（最终代码态）：`1765 passed, 12 skipped, 1 xfailed, 0 failed`（191s）**。
