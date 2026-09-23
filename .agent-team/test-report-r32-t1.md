# R32-T1 测试报告 · tester-whitebox 回归收口（三条件实测）

日期：2026-09-23 ｜ 角色：tester-whitebox（delivery · 测试白盒路）｜ 分支：render-core-integration（工作树未 commit，待验态实测）
对象：T1 RCD 去马赛克移植（dev1-r32-impl.md 实现 + design-review-r32.md §C0-C4 码检通过 + .qa_ok_r32_t1 reviewer 前置意见）

**一句话：三条件全部实测通过——全量回归 1732P/12S/1X/**0 failed**；gate 金样本零漂移（golden 7 + native 等价 6 + curves 4 全绿）；A/B 抽 3 片（含竖拍 flip=5）复算与记录值 **d=0.0000 逐位一致**、零 fallback。缺陷 0 新增，T1 建议收口。**

---

## 条件 1：全量回归 → 通过

- 命令：`python -m pytest tests -q`（tester 复跑，非采信 dev 自报）
- 结果：**`1732 passed, 12 skipped, 1 xfailed, 13 warnings in 238.94s (0:03:58)`，0 failed**
- 与 dev 自报（dev1-r32-impl.md §4：1732 passed / 12 skipped / 1 xfailed / 0 failed，263s）数字一致，耗时同量级
- 重点用例单独命名复跑（`-v` 留证）：
  | 用例面 | 结果 |
  |---|---|
  | tests/unit/test_io_rcd.py（RCD 15 用例） | **15/15 PASSED** |
  | tests/regression/test_gate_curves.py | 4/4 PASSED |
  | tests/unit/test_native_stage_kernels.py + test_native_abi.py + test_decode_cache.py + test_region_masks_channel.py（export/decode 契约连带面） | 44 passed |
  - test_io_rcd 15 = 8 单体（契约/RCD≠AHD/缺省 AHD/未知值静默/异常回落/不支持回落/half_size 忽略/X-Trans 回落）+ flip 四态参数化 4 + export 通道 3，收集数与 dev 自报一致

## 条件 2：gate 金样本零漂移（默认链 AHD 不动）→ 通过

- 命名复跑（`tests/regression` + `-v`，32 passed in 25.59s，与 test_io_rcd 同批）：
  - **test_gate_golden.py 7/7**：`test_current_output_matches_goldens`（金样本主断言）、`test_generator_check_mode_reports_no_drift`（生成器 no-drift 自检）、manifest schema / sha256 基线 / skin softband 3 项全绿
  - **test_gate_native_equivalence.py 6/6**：exposure/matrix/tone/clarity/lut3d native 逐位等价门全绿（T1 增量未触碰既有内核的实证）
  - test_gate_curves.py 4/4（`test_native_tone_lut_matches_fast` 等）
- 默认链语义白盒核验（代码证据，非仅测试通过）：
  - decode_raw 的 RCD 分支入口为精确匹配 `if demosaic == "RCD" and not half_size`（src/pixo/render/core/io.py），缺省/未知值走既有 `.get(demosaic, rawpy.DemosaicAlgorithm.AHD)`，postprocess 参数零改动；
  - `_apply_dcraw_flip` 仅 RCD 分支消费 `raw.sizes.flip`（AHD 臂方向由 rawpy postprocess 缺省 user_flip 处理，未触碰）；
  - `test_default_ahd_unchanged` 钉住：postprocess 必调 + `gamma=(1.0,1.0)` + native 零参与。
- **结论：默认链（demosaic="AHD" 缺省）输出零漂移有金样本 + 等价门 + 回归锁三层实证，T1 红线成立。**

## 条件 3：A/B 抽片复算 → 通过（逐位复现）

- 口径可信度前置验证：按 _r32_t1_ab.py 的 pick 算法（sorted 字典序，`idx_i=floor(i*48/12)`）复算 corpus 48→12 片，与 _r32_t1_ab.json rows **逐一吻合**——「口径写死可复算」成立。
- 复算脚本：.agent-team/tmp-r32t1-ab-recompute.py（metrics/down512/边缘带函数**直接 import 自 _r32_t1_ab.py 零重写**，热身 1 + 计时 2 同口径）；抽片 3 张：
  | 片 | 方向/flip | fc_ratio_ratio 复算 vs 记录 | Δ | detail_rms_ratio | Δ | ΔE512 | fallback | 判定 |
  |---|---|---|---|---|---|---|---|---|
  | DSC_0352.dng | 横拍 flip=0 | 0.9694 / 0.9694 | 0.0000 | 0.8733/0.8733 | 0.0000 | 0.00107=记录 | False | OK |
  | **DSC_1319.dng** | **竖拍 flip=5** | 0.9615 / 0.9615 | 0.0000 | 0.9319/0.9319 | 0.0000 | 0.09511=记录 | False | OK |
  | DSC_5278.dng | 横拍 flip=0（记录最差 1.9479） | 1.9479 / 1.9479 | 0.0000 | 0.8744/0.8744 | 0.0000 | 0.00070=记录 | False | OK |
- 方向正确性（竖拍专项）：DSC_1319 `raw.sizes.flip=5` 实读确认；两臂输出 shape 一致且为 (6064,4040) 即 h>w 竖向，与 json 记录 size [4040,6064]（w,h 口径）吻合——**R32-T1 A/B 首轮崩掉的 portrait 方向 bug 修复复现有效**。
- 容差声明：fc_ratio_ratio/detail_rms_ratio ±0.02、ΔE512 ±0.01（覆盖舍入与浮点库漂移）；实测全部偏差 **0.0000**——解码链确定性成立，dev 报告数值可采信。
- 耗时：3 片子集 time_ratio 中位 0.597（记录全集 0.673），远低于 3x 门槛，native OpenMP 快于 libraw AHD 的结论复现。
- fallback：3/3 零降级事件（degradation 计数零增长）。

## 额外白盒抽查（reviewer 前置意见指定项）→ 通过

1. **decode_raw demosaic 缺省与未知值路径无新增抛错**：io.py 未知值维持 `.get(demosaic, AHD)` 静默口径；RCD 分支仅精确 `"RCD"` 且非 half_size 进入。测试锁：`test_unknown_demosaic_value_silent_ahd`（断言 native calls==[] 且降级 events==[]）。✓
2. **PixoRenderDemosaicRCD 错误码路径（非 RGBG → FallbackRequested=1）覆盖**：
   - 在役 DLL（v1.6.0，含 RCD 导出）ctypes 实测探针：2R 布局→None、GGGG 布局→None、18×18(<19)→None（均 FallbackRequested 语义）；合法 BGGR 变体正常出图；64×64 恒场 0.5 输出无 NaN、[0.499999, 0.500001]。✓
   - native 静态覆盖：tests/test_main.cpp TestRcdDemosaic 错误路径 4×FallbackRequested（非法布局×3 + 尺寸<19，:487-495）+ 4×InvalidArgs（:497-503）；reviewer 隔离构建 all passed（design-review-r32.md C0）。✓
   - Python 侧链路：`ret==1 → None`（_native/__init__.py demosaic_rcd）→ decode_raw 回落 AHD + record_degradation，`test_fallback_on_unsupported` / `test_xtrans_falls_back` 锁定。✓

## 缺陷清单

**本轮 0 新增（0 blocker / 0 major / 0 minor）。**

遗留观察（均非缺陷、不阻塞，如实记录）：
1. A/B 全集 DSC_5278/5957 高反差场景 RCD 色度残余高于 AHD（fc_ratio_ratio 1.95/2.23）——产品判断项，数据已在 json 留档（dev §5.3 同口径）。
2. 预览线 decode_cfa_half 无 dcraw flip 处理（既有行为，portrait 预览疑似横竖颠倒）——非 T1 引入，设计非目标，建议立项后续轮（dev §2.1 / reviewer C1.5 同判）。
3. reviewer 建议 S-1~S-4 维持不阻塞原判。
4. **工作树未 commit**（git status 实证：T1 增量全部 unstaged/untracked）；reviewer 前置意见第 3 条「分支推送 render-core-integration」属流程动作、非 tester 权限，提请队长按流程收口。

## 回流口径

三条件与抽查项全绿，无 MISSING/DEVIATED，无需回流 dev。T1 建议收口：`.qa_ok_r32_t1` 已在 reviewer 前置意见基础上追加 tester 三条件实测签章。

---
*tester-whitebox · 2026-09-23 · 证据脚本：.agent-team/tmp-r32t1-ab-recompute.py + tmp-r32t1-ab-recompute.json ｜ 复算数据：.artifacts/_r32_t1_ab.json（记录）*
