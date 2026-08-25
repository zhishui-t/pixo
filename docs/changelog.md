# Changelog

## 2026-08-25 — 高光治理批：0355 清偿与评分器接线

- 曝光高光预算哨兵 ev≤log2((1−τ)/p99)，highlight_budget=0.02；标定表升维 (med, wb_B)
  并以均值 L 为拟合目标重拟合 12 张。
- WB 暖度曲线标定 configs/calibration/warmth_curve.json（双留出验证），0355 色度 da/db≈0。
- 真 7 维美学评分器接入 batch 选片与 loop 终止条件（健壮回退+暗路径测试）。
- 验收：716 passed；A/B 5236=8.3/5239=8.0/0352=14.4/0355 clip_hi 2.29%·|dL|=1.0——
  四样张全指标达标，tech_debt #9 销账。

## 2026-08-25 — 组合批：知识图谱 · 评分接线 · 标定升级

- 知识库四包 49 节点 / 37 边（capture_post 11n4e / hue 14n11e /
  post2 9n9e / tone 15n13e）过审；`KnowledgeRegistry` 两阶段自动合并
  内置图与 `configs/knowledge/*.json`（实测合并 63 节点 / 46 边，
  悬空引用 0），新增知识包零代码接入。
- 图谱健壮化：受控词表 README（type/relation 枚举）、知识包软基线测试、
  跨包边同组发布约定（`_requires` 声明）。
- 评分器接线：batch 选片工厂换真实 7 维美学评分器（无 torch 回退 Mock），
  loop measure 每轮附美学维度分数。
- 曝光标定表升维：`(med_log2, wb_B)` 二维分键——暗室与夜景中位亮度
  相同而相机意图相反的场景得以区分。
- WB 暖度曲线拟合（0355 偏色治理）：新增 `configs/calibration/warmth_curve.json`
  （5 结点）与拟合脚本 `scripts/fit_warmth_curve.py`（RAW 缩略图为真值，
  最小化 Lab da/db）；`WhiteBalanceStage` 新增 `warm_cal_file` 开关缺省加载，
  文件缺失回退内置斜率模型。实测 DSC_0355 da −12.25→+1.07 / db +14.41→−3.78
  （±6 门禁内），对照 DSC_5236 不劣化（da −3.23→+0.62）。
- 全量测试 697 passed。

## 2026-08-23 — 修图质量 P0 修复与项目整理

- 修复：tone `brightness` 回归标定值 0.25（原 0.5 与标定注释矛盾）；
  exposure 新增低光保护参数（low_key_knee/keep/range）。
- 新增：场景自适应曝光标定表 `src/pixo/render/target_offset.json`（12 结点，
  以 RAW 内嵌相机缩略图为真值拟合）+ 拟合工具 `scripts/fit_target_offset.py`。
- 实测：室内 ΔE 38.8→9.2 / 33.6→9.8，夜景 46.5→16.5；全量测试 673 passed。
- 测试：loop_e2e 亮场夹具改为显式超亮，解除对引擎默认亮度的依赖。
- 整理：清理根目录残留日志；`.agent-teams/` 纳入 .gitignore；
  一次性实验脚本归档至 `scripts/experiments/`；重写 `scripts/README.md`。

## 2026-08-22 — Phase A/E 目录与资源整理

- `doc/` 改名 `docs/`，并更新全仓引用。
- 新增 `configs/`、`resources/`、`data/`、`tests/`、`scripts/` 骨架与 README。
- 静态资源迁移：
  - DCP → `resources/dcp/`
  - 相机标定 → `resources/camera_profiles/`
  - 风格/预设 → `configs/styles/`
  - 金样本 → `data/golden/`
- 补齐 Phase E 文件：渲染/视觉/批量诊断脚本、规则 YAML、Harness 包装模块、文档入口。

## 之前重要里程碑

- P1-1：`pixo.render` 命名空间迁移 + `render` shim。
- P1-5：单张闭环（compose → segment → preview×3 → FINAL_QC）。
- P1-6/7：pixo-service 与性能门禁。
- P2-2/3/4：批量/连拍、Web UI v1、复核与报告。
- P2-8：许可复审与发布阻断清单。
