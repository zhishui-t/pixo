# R31 状态速览（队长维护）

## 进度
- 卡点①②过；.design_ok 已签（v2.1，两轮整改）
- F0 ✅ GPLv3（LICENSE/pyproject/NOTICES §8）
- F1 ✅ dng_validate.exe（targets/win/release64_x64/）+ _r31_dng_render.py（口径：-tif 全默认管线 sRGB 8bit）
- F3 任务1-3 ✅（_r31_three_arm.py n=3 自测过 + _r31_fit_dng_target.py dry-run 过）
- F2 ⛔ UAC：等用户放行（.artifacts/_r31_env_install.ps1 或 UAC 点"是"）→ 后 python .artifacts/_r31_convert.py
- 阶段5-10 待环境

## 阶段5结果（2026-09-22 dev-2, n=48）
- pixo−DNG: median|ΔL|=13.44(FAIL>5), |Δa|=0.23/|Δb|=0.51(PASS), Spearman(ΔL,wb_B)=0.479(FAIL)
- 触发 F4；三候选：a(现状)13.44 / b(旧相机曲线)系统性+30偏置出局 / **c(DNG目标新曲线) 4.453**（holdout dL_med=0.10, IQR−82%, 唯一<5）
- c 未达矫正后目标(≤3) 且其 Spearman=0.5068 落在 IQR=3.94 窄域 → 按 §3 失败路径：**零写入**，上报仲裁
- dev-2 过程裁决存档：tone_map recipe 路径硬编码无注入键 → 进程内 monkeypatch 测量（零写入，仓内测试同款手法）

## 队长裁决记录
1. **并行工作流隔离**（2026-09-22）：工作树存在 20 文件未提交改动（src: exposure/hsl/
   white_balance/graph/session/runtime；tests: conftest/wb/exposure_tier/huesat_oklch/
   service_runtime_fixes/region_*/segmenter_warmup；scripts: _t102_smoke/run_ab_regression/
   t93_smoke）——属**另一会话的 enabled/wb 接线工作流**（佐证：R31_enabled_wiring.md/
   _r31_consist.xml 开工前已在）。本轮角色**不得触碰/回滚**这些文件；本轮域仍限
   configs/styles/default_look.json、recipe_tone_curve.json、.artifacts/r31_*、
   .agent-team/*。注意：test_service_runtime_fixes.py 被其修改 ⇒ F4 写盘硬约束
   **执行时须重新核验该测试当前断言**，不得沿用 design 撰写时的行号。
2. F2 交付物命名偏差（picklist.json vs manifest.json）：探针已兼容两者，§6 以
   "picklist.json（48 片）+ manifest.json（批转后）"双阶段口径补记，无需改设计。

3. **F4 仲裁上报用户（2026-09-22）**：候选 c（median 4.453，介于达标线 5 与矫正目标 3 之间，
   holdout 泛化优秀）vs 字面判据失败路径（保留现状 13.44）。队长建议=接受 c 为中期改进 +
   尾部(20/48>5, p90=9.62)立项跟进；用户拍板后执行对应分支（写 c / 保持现状）。
4. 尾部结构性残差（Spearman 持续 0.48-0.51 提示与 wb_B 相关）→ R32 候选立项。
5. recipe 路径参数化（engine 改动）→ 技术债候选，本轮 monkeypatch 仅测量用。
6. manifest/picklist 双清单已验同序一致 → design §6 补记统一口径，无需改实现。
