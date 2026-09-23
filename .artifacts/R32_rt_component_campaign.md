# R32 · RawTherapee 组件移植战役收官报告

日期：2026-09-24 ｜ 分支：render-core-integration（7 提交，2758a18..bd40c37）
任务书：`.agent-team/task-brief.md` v2 ｜ 台账：`.agent-team/r32-t8-ledger.md`（正式交付物）

---

## 0. 结论速览

**八步串行全部收官，模块面 38 项裁决**：已吸收收编 8 / 已具备保持 13 / 建议吸收 10（P0×3）/ 跳过 7。
战役 pattern 定论：**RT 值得搬的是能力面（去马赛克/胶片格式/匹配曝光），不值得搬的是数学底座
（插值/矩阵合成/六键——我方实现多更优）**；GPLv3 合规（pixo 已 GPLv3，出处逐处标注）。

## 1. 八步成果表

| 步 | 提交 | 姿态 | 关键成果 |
|---|---|---|---|
| T1 去马赛克 | 2758a18 | 移植 | RCD 进 native（RT 核心 ~330 行逐字搬）；A/B n=12：伪彩 0.944/耗时 0.673 双优；附带修竖拍 flip bug |
| T2 DCP 对照 | 20fbbf2 | 对照 | 10 差异 **0 吸收**（我方矩阵合成=规范语义，RT 灰点随 WB 漂移系 dcraw 遗产）；**V9 LookTable 零消费**列 P0 首位 |
| T3 胶片 | ee8e071 | 适配 | 纯格式适配零引擎吸收（HaldCLUT→.cube 转换器）；我方四面体插值精度高出 RT 三线性 ~2.8e6 倍 |
| T4 曲线 | f5835ab | 吸收 | user_curve 新增 4 插值模式（spline/catmull_rom/akima/monotone）+渐近线平段；检视抓 akima 双错回流修正（scipy 双参考 ≤6e-8）；事实纠正：Akima 非 RT 模式 |
| T5 直方图 | 1236d2b | 吸收 | Lab L\* 感知亮度模式（RT 同口径）+ 曲线编辑器联动数据契约；parade 实为波形三窗（勘误） |
| T6 HSL/分色调 | 33abc4a | 吸收 | RT 施加数学（防截断二次混合/lum 饱和衰减）+ preserve_luma；CLUT 猜测被源码推翻（实为逐像素解析式） |
| T7 曝光 | bd40c37 | 移植 | getAutoExp 匹配曝光忠实移植（16 结构点过审）mode='match' 与 auto 并存；六键数学保持（ramp 实测达标）；黑白点硬钳制不吸收（设计特性） |
| T8 清点 | （台账） | 台账 | 38 项裁决；P0×3：LookTable 零消费 / guided-filter 局部恢复 / 预览线 flip 缺失 |

## 2. 质量门禁战绩

- **每步双门禁**：design/代码 review ×8 + 回归 ×8；检视抓出真错三起（T4 akima 双错、
  T1 漏收测试文件、T3 容差松）全部回流修正；
- **默认链零漂移红线全程保持**：八步全走"显式开启/缺省逐位不变"，终检实证；
- 全量从 1732 → 1765 passed / 0 failed（战役净增 33 用例）；
- 执行引擎备注：WorkBuddy 引擎对本任务族连续拒答（refusal），按预案全程宿主兜底执行，
  各棒报告如实标注。

## 3. T8 台账摘要（38 项裁决）

- **已吸收收编 8**：RCD / HaldCLUT 适配 / 四模式曲线 / lab_l 直方图 / RT sat-lum 数学 /
  preserve_luma / match 曝光 / 曝光基线联动；
- **建议吸收 10**（后续轮）：**P0×3** = DCP LookTable/HSM 底座零消费（渲染影响最大）、
  Shadows/Highlights guided-filter 局部恢复、预览线 dcraw flip 缺失（用户可见 bug）；
  P1×4 = FlatCurve 周期曲线 / NURBS 贝塞尔 / Lab 域曲线 / 动态 profile；P2×3 = CA auto /
  RL capture sharpening / Fattal tone mapping；
- **保持/跳过**：rawpy 已覆盖（解码全家桶）、Locallab（23.5k 行）归 S1/S2 图层轮统一设计、
  CIECAM/小波低 ROI 登记不删、CameraCalibration 与 oklch 域为我方超集/独有。

## 4. 排队与挂起（随 DELIVERY 呈用户）

1. **R31 候选 c 仲裁**（挂起）：DNG 对齐候选 c（median 4.453 vs 现状 13.44）——接/不接；
2. P0×3 实施轮（建议 R33）；
3. S1 分割进引擎、S2 Compositor 图层模型（任务书 v2 排队项）；
4. 分支合并 master 时机。
