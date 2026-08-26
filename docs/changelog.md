# Changelog

## 2026-08-25 — 性能治理批：评分器预热 · 域外隔离 · llm_review 报表

- 评分器常驻预热：warmup() 预加载+dummy 推理，service startup 钩子挂载
  （失败不阻断启动），health_info 增 warmed/warmup_ms；PIXO_SCORER_WARMUP=0
  可跳过——消除首推 15.8s 冷启（稳态 ~20ms）。
- batch 选片域外隔离：selector.include_synthetic=False 默认按
  domain_hint="synthetic_like" 分池剔除 TopN（隔离 verdict 可追溯不占位），
  开关开启并入——真模型上线后合成候选高分混入的污染通道关闭。
- llm_review 报表块：LoopResult 新增 accepted 逐条明细/rejected 计数与原因
  分布/notes 指引，供人工审核 UI 或导出直接消费；无建议时键缺席。
- 验收：862 passed；默认关路径逐位回归一致。

## 2026-08-25 — 日落批：公式守卫清零 · VibranceStage 占位处置

- 公式守卫日落盘点（CI 哨兵固化）：全部 5 个规则 yaml、9 条活跃规则 condition
  均为原生形态（metric/op/value 或 all）——clarity 迁移后已无任何 formula 条件
  守卫；exposure_rule_001 的 log2 算术属动作公式非守卫语义，在册保留。
  tests/unit/test_formula_guard_sunset.py 五用例固化为 CI 拦截（防回退）。
- VibranceStage 占位处置：转发壳 modules/vibrance.py 删除，reshape 占位类改
  显式废弃声明（NotImplementedError+docstring 指引 colorcal vibrance/saturation，
  _COLOR_PARAM_ALIASES 桥接），注册名保留稳住 STAGE_CLASSES；废弃契约断言入
  test_pipeline。色彩规则执行位已经由映射桥端到端生效（tech_debt#10 完全清偿）。
- 验收：852 passed 零失败（含哨兵与废弃契约用例）。

## 2026-08-25 — 收尾批：真评分器标定 · AND/between 原生化 · clarity 迁移试点

- 真评分器 12 样张分布标定：overall 为带符号原始分（实拍全负 p50=-0.47；
  合成噪声 +0.32 反高——绝对分无跨域语义，已制度化禁止跨域比较）；
  accept_threshold≈-0.5(p50)/stagnation_eps≈0.1 建议值入档，生产默认仍 None=关。
- 引擎原生 condition.all（≥2 子条件 AND）与 between [lo,hi] 落地：向后兼容逐位
  不变、lint 扩展覆盖 all 子项、命中附 matched 明细；畸形显式 DecideError。
- clarity_flat_rule 公式带通守卫→原生 all 三子件迁移（护栏④日落首例）：42 点
  矩阵触发集零差异；no-op 留痕条目消失属预期演进已在 yaml 注释声明。
- 验收：845 passed；32 个收尾批新用例全绿。

## 2026-08-25 — 清偿批：色彩规则执行位实装 · 真评分器权重部署 · 治理收尾

- 色彩规则端到端生效：决策键→colorcal 参数映射桥（_COLOR_PARAM_ALIASES，
  修复语义键悬空静默丢弃），6006 提 vibrance ΔS+11.2 / 5238 压饱和 ΔS−6.2，
  双 FINAL_QC 通过；四向方向探针固化为合成图单测。
- 真美学评分器部署：aesthetic_scorer.pt(333MB,MIT,HF 权威渠道) 落
  resources/models/aesthetic/，默认路径切换、探针 available 实证
  source="pixo"；许可双条目登记 model_licenses.json；真分偏低须标定
  （合成/低纹理域系统性低分已知，tech_debt #11 附注）。
- suggest 同上下文指纹 LRU8 缓存（命中零 HTTP）+ chat_latency_ms 全路径入 trace。
- print 告警统一迁 logging（5 文件 14 站点，capsys 断言随迁 caplog）；
  model_licenses 补换行与 usage 词表锁定测试。
- 验收：816 passed（终版门禁）。

## 2026-08-25 — P3 批：LLM 副驾转正（建议态闭环，默认关）

- dsh.chat 从占位转正：OpenAI 兼容客户端（PIXO_DSH_CHAT_URL/KEY/MODEL 三要素
  环境变量，缺一降级占位带 source 标记；10s 超时/重试 1 次/二次失败降级附 error）。
- 新增 agent/patch_protocol.py：LLM 参数补丁唯一闸门——五段校验链（结构 schema→
  ParamRef 双段白名单→op 枚举→clamp 预检拒绝式→locked_params 锁定拒绝）+
  PatchReview 分组 + apply_patches 纯函数。
- 新增 agent/suggest.py 编排：指标+aesthetic 历史+RAG top3 组装上下文，双 prompts
  加载，LLM 输出经校验后 accepted 入 decide_context 建议态（不碰终态）、rejected
  全文进 trace；agent_suggest 默认关（零行为变化已逐位验证），环境未配置整链跳过。
- know/context.py：RAG 结果 prompt 格式器（去重/置信截断/限长）。
- 安全评审通过：注入面协议层消灭、降级三态可观测、密钥全环境变量零硬编码。
- 验收：808 passed；30 个 P3 新用例全绿。

## 2026-08-25 — P2 规则包批：代理指标量纲修复 + 六条数据锚定规则

- vision.measure 新增三代理指标并统一 [0,1] 域（修复 colorfulness 恒饱和 100 的
  量纲失配）：haze_proxy / colorfulness_proxy / tonal_range，透传 decide_context。
- 规则扩容：影调通透包 4 条（dehaze≤0.22=p75 触发、clarity 入口 0.12=p25 带通
  <0.22、shadow_open≥0.18、highlight_recover）+ 色彩包 2 条（vibrance≤4.78=p25、
  saturation≥6.13=p75），全部阈值锚定 docs/metrics/proxy_distribution.md 实测分位。
- decide 护栏：公式标识符加载期 lint（笔误→DecideError）、no-op 计数留痕；
  load_rules 文件分支死代码修复。
- 验收：实测分布门禁——12 样张驱动 evaluate_rules，触发簇精确命中、中间带静默；
  全量 778 passed。已知限定：VibranceStage 执行位占位（决策键已通）。

## 2026-08-25 — 二次构图批：auto_level 实做与主体感知 smart_crop

- compose.auto_level 从占位转正：行梯度投影地平线检测（±12° 扫描/8° 钳制/
  置信度回退），无地平线场景不动构图；几何元数据入 trace。
- 新增 geometry/smart_crop.py：主体感知裁剪建议核心——候选网格 + 硬约束
  （人脸全含/头留白≥10%/躯干出画分级容忍 native5%·mask8%）+ composition
  软评分（aesthetic scorer 可注入，None 退化规则分）。
- 闭环接线：crop_suggest 开关默认关（零行为变化已逐位验证）；建议走
  decide_context 建议态，经 crop_suggest_rule_003 门控标量旗标采纳，
  采纳边界单点归一化→像素且合并保留用户既有 compose 字段（不重置
  auto_level）；box_provider 预留原生框升级通道。
- 知识包新增构图域 photography_composition.json（10n9e，三分法/头留白/
  视线留白/裁剪禁忌等），受控词表沿用。
- 验收：740 passed；真实样本主体框全含 4/4、composition 分 crop≥full 4/4、
  默认关路径逐位一致。

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
