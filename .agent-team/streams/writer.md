# writer 简报 — changelog 历史批次补写（2026-08-27 ~ 2026-09-05）

日期：2026-09-07 · Wave1/F01 · 交付物：docs/changelog.md（顶部新增 11 个条目，既有条目未动）

## 做了什么

- 覆盖 2026-08-27 至 2026-09-05 全部 31 个 git commit（任务书预估约 29 条，实际全量 31 条：
  08-27 有 22 条、09-04 有 5 条、09-05 有 4 条），归并为 11 个批次条目，插入 changelog 顶部
  （最新在上），格式沿既有惯例：`## YYYY-MM-DD — 批次名：主题` + bullet（动机+实现+落点）
  + 结尾「验收：」行。
- 09-05 之后（本轮 F20 范围）的工作未写。
- 注意：既有条目「2026-08-26 — t110 YOLOE 移除批」对应 commit 769a225（commit 日期 08-27）。
  为避免重复，08-27 新增「t110 落库收口 + 路线图立项」条目定位为正式落库/测试同步/仓库治理/
  路线图立项，正文注明"内容同 2026-08-26 t110 条目"。

## commit 清单核对表（31/31 全覆盖）

| hash | 归属条目 |
|---|---|
| f357b35 | 2026-09-05 路线图收官批（t64 HSM→OKLCh） |
| f4a51db | 2026-09-05 路线图收官批（t66 风格卡） |
| 8f4c582 | 2026-09-05 循环治理批（t46/t48/t51） |
| c1e6fe2 | 2026-09-05 循环治理批（t59/t63/t62/t65/t58） |
| 3bcccd3 | 2026-09-04 阶段三首块批（t42/t43） |
| f49d3fc | 2026-09-04 评审收口批（t38-t41） |
| 3fbe56d | 2026-09-04 阶段二入库批（t36/t37） |
| bc96a09 | 2026-09-04 阶段二首跑批（t30-t34） |
| bca52ed | 2026-09-04 阶段一批（t1-t25） |
| e216743 / 417bc2a / e922dae / 47cedef / 26a97c5 / 09616ab / 7d6578b / 2debcc7 | 2026-08-27 全链正确性修复批 |
| 57c7870 / 3be14be / e8d7d61 / e3c8f7c / f48d453 / 5f62646 | 2026-08-27 渲染正确性与验证链批 |
| 7a31cbf / 3925b69 / 4388f37 / 0e8d2a5 | 2026-08-27 16bit 精度改造批 |
| 769a225 / 07adce1 / 146acfa / f68b158 | 2026-08-27 t110 落库收口 + 路线图立项 |

## 验收数字来源（全部可溯源，无编造）

| 数字 | 出处 |
|---|---|
| HSM→OKLCh A↔B median 10.890 / p95 16.070（4.73 JND） | .artifacts/hsm_oklch_eval.md |
| 切默认评估基线 1360 passed / 5 skipped / 1 xfailed、翻转 11 failed | .artifacts/oklch_default_eval.md §3.4 |
| 处置表 v2 14 条（4/4/3/3/1） | docs/ARCH_REVIEW2_DISPOSITION.md 汇总行 |
| 阶段三 1334 passed / 5 skipped / 1 xfailed；光照 GE1 10.180 vs as_shot 5.946、−1.841 JND | .artifacts/stage3_first_verdict.md §1/§3.3 |
| 评审收口批"1130+ passed 绿"、gate 17 features | f49d3fc commit body（报告无对应 .artifacts 文件，见遗留） |
| 入库批 6.649→4.251、12 万次对拍、1297 passed（173s） | .artifacts/stage2_adopt_verdict.md §2/§3 + 3fbe56d body |
| 首跑批 6.658→4.244（+36.3%）、G-5 3/4、5250 +2.607→−5.15、+0.224、120 文件零 torch | .artifacts/stage2_qa_verdict.md §2/§4/§3 + bc96a09 body |
| 阶段一 1231 passed / 4 skipped / 1 xfailed、1.8e-10、0.955/0.258（旧 0.271）、−7.7%（45/54）、268 节点/660 边、11.27°→4.48°、0.0756→0.0115 | .artifacts/stage1_qa_verdict.md + bca52ed body + .artifacts/ab_intent_report.md（经 verdict 转引） |
| 08-27 各条目数字（3457x、0.05098→0.0、0.219→0.0013 EV、rel 0.03→0.002/125 倍、0.81 ΔE/24.7%、1.075 ΔE/47.8%、87-95ms/6x/333ms/7x、2663 张、24+8 条 PASS、1031 passed、e2e 5/5、在线 7/7、bundle −24KB、17+5+3、16 用例、8 用例×2、11→4） | 各 commit body（e216743/417bc2a/57c7870/3be14be/e8d7d61/3925b69/4388f37/0e8d2a5/7a31cbf/e3c8f7c/5f62646/7d6578b/2debcc7/26a97c5/769a225）。docs/metrics/u8_midpoint_precision.md 佐证 7a31cbf |

## 遗留问题（供 qa 总审参考）

1. **f49d3fc 的"1130+ passed"无 .artifacts 报告佐证**：该批（t38-t41）没有独立评估报告落盘
   .artifacts/，唯一出处是 commit body 原文。changelog 已标注"（commit 记录口径）"。
2. **批内数字混用 commit body 与报告两个口径**：09-04/09-05 批次两处一致（body 与报告数字
   互验过），08-27 批次只有 commit body 可用（该日无 .artifacts 报告）。
3. **t62 批次号差异**：oklch_default_eval.md 报告头写"t52"、commit c1e6fe2 写"t62"。
   changelog 采用 commit 口径（t62），只引报告文件名不引批次号，避免歧义。
4. **08-26 t110 既有条目与 769a225 重叠**：既有条目日期（08-26）早于 commit 日期（08-27），
   属批次完成日与落库日之差；已用"落库收口"条目显式衔接，未改动既有条目。

---

# F17 简报 — 可选依赖声明（tech_debt #4）

日期：2026-09-07 · 交付物：requirements.txt / pyproject.toml / README.md / docs/tech_debt.md(#4)

## 做了什么

- **PyYAML 可选→必装**：复核确认 qa 两条事实成立——decide/engine.py:256-261 import yaml
  失败即 raise DecideError（无回退）、know/graph.py:250-254 同样 ImportError→RuntimeError
  硬报错，decide/rules/ 下 5 个规则 YAML 属核心链路；全仓仅用 yaml.safe_load 两处。
  requirements.txt 与 pyproject dependencies 均加 `pyyaml>=6.0`（沿仓内全小写 `pkg>=X.Y`
  惯例；safe_load 自 5.1 稳定，取 6.0 clean-API 主线）。
- **scipy 保持可选**：render/core/color.py:487 懒 import least_squares、
  `except ImportError: pass` 后回退纯 numpy 粗网格（结果域一致，较慢）。挂新 extras
  `calib = ["scipy>=1.11"]`（未并入 pixo-render：渲染缺省路径不要求 scipy，calib 语义
  对应标定/拟合工作流；未加 pixo- 前缀因其非包级别名而是工作流级，与 dev 同类）。
- **安装说明**：README.md「快速开始」块加一行 `pip install -e ".[calib]"` 注明不装时
  temp_tint_to_wb 走 numpy 网格回退；requirements.txt 尾部同义注释。
- **tech_debt #4 标注**：改为「已处置，2026-09-07 F17」，正文写明两条事实与落点；
  THIRD_PARTY_NOTICES.md 缺失归条目 3（F16 另批），不在 #4 范围。

## 验证证据

1. `python -c "import yaml, scipy"` → yaml 6.0.3 / scipy 1.18.0（环境满足声明约束）；
2. pyproject 结构（tomllib 解析）：dependencies 含 pyyaml>=6.0；extras.calib ==
   ['scipy>=1.11']；extras 键 = pixo-render/pixo-vision/pixo-vision-models/pixo-meta/calib/dev；
3. `pip install --dry-run -r requirements.txt` → "Requirement already satisfied:
   pyyaml>=6.0 (6.0.3)"，无 Would install 新增项（无新增必装副作用）；
4. 功能定向：PYTHONPATH=src 下 load_rules 逐个解析 5 个规则 YAML → 9 条规则
   （2+1+1+1+4，与既有 changelog「9 条活跃规则」交叉印证；注：load_rules 传 list
   会被当 dict 规则列表过滤，须传单路径字符串——首次调用返回 0 系调用方式错误非解析问题）。

## 遗留

- THIRD_PARTY_NOTICES.md 未写（tech_debt 条目 3，等 researcher 素材后 F16 另派）；
- 其他 extras（pixo-render/pixo-meta 空列表）语义未在本批整理，属历史遗留非 #4 范围。

---

# F16 简报 — THIRD_PARTY_NOTICES.md 成文（tech_debt #3）

日期：2026-09-07 · 交付物：THIRD_PARTY_NOTICES.md（仓库根，新建）+ docs/tech_debt.md #3 标注

## 做了什么

- 基于 `.agent-team/research/license-inventory.md`（唯一事实来源）逐项忠实转写成文
  `THIRD_PARTY_NOTICES.md`，结构按任务书 7 点：§0 总述+三项置顶警示 → §1 Python 必装
  （7 项，含 rawpy→LibRaw LGPL-2.1 捆绑说明与"附两份许可文本"义务）→ §2 可选/dev/懒
  import（scipy 挂 calib extras、PyYAML 标注 F17 已升必装——时点差异显式注记，未改清单
  事实）→ §3 模型 6 项（M1-M6 全带核验状态；冲突 A=vision_models.json 过期、
  aesthetic_scorer.pt 打包矛盾、segformer 台账自相矛盾、sapiens SA 差异均如实记录）→
  §4 前端 12+132=144（lucide ISC 义务+标准文本；传递树"未逐包人工复核"如实声明+
  license-checker 终验建议）→ §5 native 零负担+语料/数据表+**登记资产声明**（dcp/
  manifest.json 与两张 lr_*_baseline 预设=非运行时消费，队长裁定口径，引 stream-1 F05
  证据链；DCP 本体核验义务不因此免除）→ §6 代码衍生专节（huesat GPL H1/H2/H9 引文、
  DNG 痕迹 286 行/35 项/12-11-12、Adobe 许可四要点修正、clean-room M1-M5 缺档、guanlan
  三处）→ §7 存疑速查表 10 项。
- tech_debt.md #3：标注「NOTICES 已建，2026-09-07 F16」；model_licenses 路径同步子项
  改写为如实保留的待处置项（vision_models.json 过期冲突 + segformer 矛盾，注明 NOTICES
  已记录、台账更新不在 F16 范围）。

## 事实忠实度自检

- 清单 §1.1 六项运行时依赖全部保留（pyyaml 按任务口径移入必装表并注记 F17）；
- 清单 §1.2 可选组逐项保留（空 extras 也列出）；§1.3 两项懒 import 按 F17 后口径成文；
- 清单 §2 六个模型逐项转写，冲突/未复核/置信度标签一个不少；§3 前端表逐包转写；
  §4 native/§5 语料逐行转写；§6 六个血缘项 L-1~L-6 全覆盖（L-6 health.py 注明无许可面）；
- 清单 §7 九项速查全保留，另加"clean-room 过程记录缺档"一行（事实源 F18 §0.5，非清单
  冲突）；
- 未发现清单内部冲突，无需向队长追问。

## 遗留

- 三项警示对应的三条待决动作（huesat 血缘核实、DCP 核验、NC 门控保持）均超出 writer
  职权，已在 NOTICES 置顶并指向 F18 §3.3 决策清单；
- vision_models.json 台账更新、resources/models/README.md 过期声明修正为待处置项，
  F16 只记录不改（边界约束）。

---

# F20 简报 — changelog 本轮批次（第九轮战役）

日期：2026-09-07 · 交付物：docs/changelog.md 顶部 1 条（第九轮战役）

## 做了什么

- 新增单条目「2026-09-07 — 第九轮战役：收口清债 × oklch 切默认 × M1 掩码驱动渲染」，
  8 个主题 bullet + 固定「验收：」行，插入最新位置（2026-09-05 收官批之前）。
- commit 覆盖核对（f357b35..HEAD 共 13 笔，11 笔具名归属 + 1 笔边界排除）：
  651f5d1→清债(F03/F04)、b187d27→F06 RAW 金样本重生成、e02b91d→**changelog 落库，
  按"F20 之后的 commit 不写"边界排除**、512bd0d→F12、0d5372a→F17+F05、35af288→F13、
  ef4473d→F07、d25f70c→F16、b812061→F14、ce92c73→F08/F09/F15、3d2db90→F10、
  fc2bfa8→M1 评审修复批。F11/F18/F19 为证据/文档型任务（产物在 .artifacts 与
  research/，无独立 commit），条目内按内容归属。
- 格式沿本文件 F01 确立的惯例（`## 日期 — 批次名：主题` + 动机/实现/落点 bullet +
  「验收：」行）；既有条目未动。

## 验收数字来源（全部可溯源）

| 数字 | 出处 |
|---|---|
| 1474 passed / 5 skipped / 1 xfailed，0 failed（189s） | .agent-team/test-report.md §0（被测版本 fc2bfa8） |
| 基线 1396 不降、+78 对账 | .agent-team/baseline-f02.md + test-report §0/§2 |
| 23 卡 69 条钉域（hsl 12/split_tone 12/skin 22/colorcal 23） | .agent-team/gates/f07-pin-hsv.md §1 |
| A1 三方字节级全等 | test-report §0（tester 复跑 vs 钉域前基线 vs dev F10 存证）+.f10_ok 门 1 |
| RAW 24/24 u8/u16 逐位零漂移 | .f10_ok 门 3 + test-report §0 |
| gate 17→20 features | gates/f08-f09-oklch-pre.md（17→19）+ F15 region_adjust case（→20，test-report --check 20 features） |
| M1 评审 阻断 0/重要 4/建议 8；修复 7 项+I-2 记债 | .agent-team/reviews/m1-review.md 头注 + qa-report.md（tech_debt #17） |
| F11 双结论（skin B/A 0.935 双不劣于；colorcal 质量不劣于/性能 ≈15× 劣于） | qa-report.md §1 F11 行 |
| NOTICES 238 行、F18 GPL 血缘 | 本文件 F16 节 + research/dng-sdk-review.md（均为本人经手交付） |
| qa 总审 PASS | .agent-team/.qa_ok（F01~F19，阻断 0，qa 修复 10 处留档） |

## 遗留

- 无数字疑点；唯一边界判断是 e02b91d（changelog 补写落库）不计入本轮条目——任务书
  "12 笔"口径与该排除一致。
- F20 之后的 DELIVERY 类 commit 落库后如需补记，属下一轮收尾件。

---

# R17 简报 — M1 掩码驱动渲染用户文档

日期：2026-09-08 · 交付物：docs/MASK_REGION_ADJUST.md（新建，约 150 行）

## 做了什么

- 成文面向使用者/贡献者的区域调整操作指南，5 章按任务书结构：§1 是什么（掩码→区域
  意图→渲染三步链 + QC 达标率 48%→57%/+9pp 效果引用，注明"试水系数口径、复权后
  增量未单独实测"）→ §2 快速上手（环境前提表：multi/segformer 权重/face 才需 NC
  放行；服务配置示例；RegionSection 三滑杆 UI 路径与 locked 态/γ=1.6/首请求耗时
  17.7s 冷启 vs 0.73s 热态）→ §3 工作机制（掩码生产两源+三渲染入口一条通道；
  决策双驱动：两规则条件/公式/三道护栏表格化+系数沿革，UI 手动同执行位；参数三维
  内核语义）→ §4 配置参考（4 个 env 表 + YAML 调参入口含两份镜像逐字节同步断言
  警示与评估脚本复跑）→ §5 已知限制 4 条（tech_debt #17 free-px-rect、纯预览
  masks_not_injected、plant 溢出双层防线、人像背景归 sky 语义灰区）。
- 术语首现解释：掩码/prompt/EV/NC/multi；文档头列全事实来源路径。

## 事实来源对照（全部有源）

| 关键表述 | 出处 |
|---|---|
| +9pp / 48%→57% / 7 张救回 / 试水系数口径 | .artifacts/region_trial_54.md §4.1/§7 |
| 17.7s 冷启 / 0.73s 热态 / 供给缺省关 / warmup 缺省开+daemon | src/pixo/service/runtime.py:52-104 注记 |
| mock 零掩码+不可用契约；masks_not_injected | runtime.py 注记 + streams/r14-stream-2.md §1 |
| RegionSection 三滑杆 ±2/±1/±1、locked、γ=1.6、仅提交改动键、warmth 预留 | streams/r14-stream-3.md §1 |
| 两规则条件/公式/clamp/护栏 0.70/S-5/R16 1%/系数沿革 | configs/rules/region_rules.yaml 全文（含头注） |
| 三渲染入口共用适配器、compose 后帧坐标、自动缩放 | src/pixo/render/pipeline/region_masks.py docstring |
| 参数三维内核（2^(ev/2.2)/HSV S/RGB 增益、意图级口径） | src/pixo/render/modules/region_adjust.py docstring |
| free-px-rect 错位 10%+/清缓存防线/ratio 路径不受影响 | docs/tech_debt.md 条目 17 |
| 镜像逐字节同步断言 | tests/unit/test_decide_region_wiring.py:209-215 |
| sky/plant 无需 NC 放行 | .artifacts/region_rules_activation_eval.md §1 |

## 遗留

- 无阻塞。文档命名取 docs/MASK_REGION_ADJUST.md（任务默认建议；仓库 docs/ 无既有
  用户指南命名惯例可循，UI_OKLCH_SPEC.md 同为无 PIXO_ 前缀的功能文档）。
- sky 复权 -0.5 后的独立效果数据不存在（trial54 的 +9pp 是 -0.25 试水系数口径），
  文档已如实注记，未虚构复权后数字。
