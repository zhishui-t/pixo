# R32 战役终检报告 · tester-whitebox（campaign 级收口棒）

日期：2026-09-23 ｜ 角色：tester-whitebox（delivery · 测试白盒路，T1 交棒后第二棒）｜ 对象：R32 战役 T1-T8 全收官态
基线：分支 render-core-integration，HEAD=`bd40c37`（feat(exposure) R32-T7），campaign 累计 7 commits（`a8f7890..bd40c37`：T1 native / T2 docs / T3 lut / T4 curves / T5 histogram / T6 hsl+split / T7 exposure）

**一句话：终检五项全绿（2026-09-24 补核后定稿）——全量 1765P/0F、gate 金样本零漂移、四步抽验全过、GPL 面完整；第 5 项推送态于 2026-09-24 实证闭环（HEAD == origin tracking ref == fdd9d6f，同步零偏差），`.qa_ok_r32_final` 已补签，R32 战役收口。**

---

## 终检 1：全量回归 → 通过

- 命令：`python -m pytest tests -q`（终检棒复跑）
- 结果：**`1765 passed, 12 skipped, 1 xfailed, 13 warnings in 195.33s (0:03:15)`，0 failed**
- 符合预期 ~1765+；较 T1 收口态（1732）+33，即 T4-T7 新增用例面（test_user_curve r32t4 ×8、test_hsl_split_tone_r32t6 ×7、test_exposure_match ×5、histogram/联动契约等）；T8 台账（dag.json）note 亦自记 "1765/0"，与实测一致

## 终检 2：gate 金样本零漂移（战役红线，累计 diff 上）→ 通过

- 命名复跑（72 用例批量，26.42s，见终检 3 同批）：
  - **test_gate_golden.py 7/7**：`test_current_output_matches_goldens`（金样本主断言）+ `test_generator_check_mode_reports_no_drift`（生成器 no-drift 自检）+ manifest schema / sha256 基线 / skin softband ×3 —— 在战役累计 7 commits 之上全部零漂移
  - **test_gate_native_equivalence.py 6/6**：exposure / matrix / tone / clarity / lut3d native 逐位等价门全绿（T6/T7 触碰 hsl/split-tone/exposure 后等价门仍绿）
  - test_gate_curves.py 4/4（T4 改 curves 域后 `test_native_tone_lut_matches_fast` 等仍绿）
- 「显式开启/缺省不变」纪律白盒核验（campaign 四步各一）：
  - T1：RCD 分支精确匹配 `demosaic == "RCD" and not half_size` 进入，缺省 AHD 零触碰（test_default_ahd_unchanged 锁定）
  - T4：`test_r32t4_linear_default_bitwise_unchanged` PASSED（缺省 linear 逐位不变）
  - T6：`test_adjust_math_default_bitwise_unchanged` + `test_split_tone_preserve_luma_default_bitwise_unchanged`（array_equal）PASSED
  - T7：`test_exposure_stage_default_mode_unchanged` PASSED（缺省 mode="baseline" 不受 match 吸收影响）
- **结论：默认链在整个战役累计 diff 上最终实证零漂移，campaign 红线成立。**

## 终检 3：campaign 关键声明抽验（各步定向测试面）→ 通过

| 步 | 抽验声明 | 定向证据 | 结果 |
|---|---|---|---|
| T1 | RCD FallbackRequested 路径 + 默认 AHD 分支 | `test_io_rcd.py` 15/15 PASSED（本批命名留证；`test_fallback_on_unsupported`：FallbackRequested→None→回落 AHD+降级事件；`test_default_ahd_unchanged`：postprocess 必调+gamma(1,1)+native 零参与。T1 轮在役 DLL ctypes 三态探针（非 RGBG→None、<19→None）在当前 HEAD 同 DLL 上仍有效） | ✓ |
| T4 | akima scipy 参考 ≤1e-6 | `test_r32t4_akima_matches_scipy` PASSED（vs `scipy.interpolate.Akima1DInterpolator` 独立参考，断言 `max≤1e-6`；docstring 记录检视回流：初版 w_left 权重错位 0.1176 已修正锁定）；同面 `test_r32t4_spline_matches_scipy_natural` 亦 PASSED | ✓ |
| T6 | adjust_math 缺省逐位（array_equal） | `test_adjust_math_default_bitwise_unchanged` PASSED + `test_split_tone_preserve_luma_default_bitwise_unchanged` PASSED（:123 `np.array_equal(a, b)` 逐位断言） | ✓ |
| T7 | mode=match 建议 metrics 写点、无 tone 参数写点 | `test_exposure_stage_match_mode_end_to_end` PASSED（state[ev_mode/match_suggest] + metrics["exposure_match_expcomp"] 断言）；代码面核验：`_match_ev`（exposure.py:651-677）仅写 state+metrics，grep `params[`/`params.update`/`set_param` 于 exposure.py **零命中**，docstring 明示「不自动改写 tone 参数（编辑动作显式化）」 | ✓ |

## 终检 4：GPL 合规面（文件级）→ 通过

- `THIRD_PARTY_NOTICES.md` **§8**（项目许可证变更节）末尾 R32-T1 条目完整：上游 URL（Beep6581/RawTherapee）+ commit `6c4cb59`（dev 分支）+ 版权人（Luis Sanz Rodriguez & Ingo Weyrich 2017-2020）+ 子组件溯源（rcd_demosaic.cc / demosaic_algos.cc border_interpolate © 2004-2010 Gabor Horvath / rt_math.h 垫片）+ 上游原始实现（LuisSR/RCD-Demosaicing）+ GPL-3.0-or-later 同源声明
- `src/pixo/render/native/src/rcd_demosaic_native.cpp` 文件头 RT 原版权块**逐字存在**（"This file is part of RawTherapee" + GPLv3 声明全文）+ 移植来源标注段

## 终检 5：分支推送态核验 → 通过（2026-09-24 补核闭环）

首次核验（2026-09-23）UNVERIFIED：本地无 `refs/remotes/origin/render-core-integration`（仅 origin/master）、分支无 upstream、`ls-remote` Permission denied (publickey)，证据指向未推送 → 签章暂扣，回流队长。

**闭环补核（2026-09-24，队长 HTTPS 推送 fdd9d6f 后）**：
- `git status -sb` → `## render-core-integration...origin/render-core-integration`（无 ahead/behind，同步零偏差；工作树全净）
- `git rev-parse HEAD refs/remotes/origin/render-core-integration` → 两者同指 **`fdd9d6f282bbaf84fb19d0c5abe3c250b2905548`**
- fdd9d6f = docs(r32) 收官提交（dag.json 台账 + r32-t8-ledger.md + 本报告 + R32_rt_component_campaign.md，**零代码文件**）——条件 1-4 证据对分支尖端继续有效
- **判定：UNVERIFIED → PASS**（原报告事实保留存档，见上方首次核验记录）

## 其余核验

- **工作树零代码改动 ✓**：`git status --short` 仅 ` M .agent-team/dag.json`（T8 台账：t7→done/t8→in_progress + note），diff 已实读确认为台账内容；无 untracked 代码文件
- T1 全部产物（rcd_demosaic_native.cpp / rcd.h / test_io_rcd.py）已入 HEAD（git ls-tree 实证）

## 缺陷清单

- **代码缺陷：0**（0 blocker / 0 major / 0 minor）
- **流程未决项：1** —— 终检 5 分支推送态 UNVERIFIED（证据与闭环路径见上节），回流队长
- 遗留观察维持 T1 报告口径（高反差 RCD 色度残余产品判断项、预览线 flip 既有缺失待立项、reviewer S-1~S-4），均不阻塞

## 签章判定

**2026-09-24 更新：条件 5 闭环补核通过（见终检 5），五项前置整体满足，`.qa_ok_r32_final` 已补签。**
签章路径留档：2026-09-23 首检 1-4 全绿、第 5 项 UNVERIFIED 暂扣签章（契约：没有证据的状态必须显式标注，不许默认通过）；2026-09-24 推送态实证（HEAD == remote tracking ref == fdd9d6f，同步零偏差）后按本节闭环路径一步补签。

---
*tester-whitebox · 2026-09-23 · 终检棒（宿主原生）· 命名证据批：72 passed in 26.42s（gate golden+native 等价+curves+T1/T4/T6/T7 定向面）*
