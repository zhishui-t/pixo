# Pixo Tech Debt / 技术债清单

> 详细许可与发布阻断项见 [`PIXO_LICENSE_REVIEW.md`](PIXO_LICENSE_REVIEW.md)。

## 运行时断言映射（tech-debt 批次）

以下条目已固化为 `tests/unit/test_tech_debt_invariants.py` 收集期断言，复发即告警：

- **条目 1 关联约束**（受限后端默认不进 multi 路由，`PIXO_ALLOW_RESTRICTED=1` 显式放行）
  → `test_restricted_model_backends_gated_out_of_router_by_default`（含台账登记在位 + 放行机制正向验证）；
- **条目 1 + 6 + 8/10b 防复活**（YOLOE 适配器与代码级引用清零、`src/render` shim 不回归、
  VibranceStage 废弃占位显式调用抛 NotImplementedError）
  → `test_cleared_items_stay_cleared`；
- **条目 3**（两个许可台账的登记路径与当前路径同步，无悬空 + 交付形态一致）
  → `test_model_license_registry_paths_resolve`（`files[]` 逐项存在 + 交付形态自洽）、
  `test_model_license_registry_guard_is_falsifiable`（负控：路径改坏必红，防断言空转）、
  `test_vision_model_path_or_source_resolution_rules`（`path_or_source` 解析规则）、
  `test_vision_models_guanlan_root_env_branch_is_pending`（`$VAR` 解析不了判「待核验」）。

判定为**不可机器断言**的条目及理由（维持人工跟踪）：

- 条目 2（DNG clean-room 复审）：法律判断，非代码不变量；
- 条目 4/7（可选依赖声明、门禁口径扩展）：清偿动作本身是写文档/扩 gate，断言其"缺失"恒红无意义；
- 条目 5（历史路径残留）：条目自身声明"仅作迁移记录"，无需防复发；
- 条目 9（高光 cap）：运行时哨兵（highlight_budget）已内建，无需重复断言；
- 条目 11（评分器分布标定）：t98 已清偿且结论是"不可作合成图质检硬结论"——语义约定属代码评审层；
- 条目 12（公式守卫日落）：✅ **前置已满足、日落条款已关闭（2026-09-10 R22）**，见条目 12 正文；
- 条目 13.1（UI 滑杆）：前端域 + spec 修订流程约束，pytest 不可达；
- 条目 13.2（RP-CCM 罚项）：条件触发且当前无病态，"无病态"断言需数值阈值属新决策；
- 条目 13.3/13.4（±1EV 压力实验、低频加权）：实验行动项，非断言。

## 关键技术债

1. **YOLOE AGPL-3.0 发布阻断**（已清偿，t110 移除 YOLOE，AGPL 依赖清零）：
   - 历史脉络：仓库曾允许 AGPL 隔离使用——ultralytics 仅限
     `src/pixo/vision/segmenters/yoloe.py` 直接 import（AGPL 隔离）。
   - t110 处置：YOLOE 适配器（segmenters/yoloe.py）、runtime
     `PIXO_SEGMENTER=yoloe` 分支、vision_health yoloe 条目、模型台账
     （model_licenses.json / vision_models.json 的 YOLOE-26L-seg 与随链
     mobileclip2_b.ts）已全部移除，ultralytics/torch-AGPL 链依赖清零，
     grep 全仓无残留；其开放词汇角色由 multi 路由栈
     （RF-DETR/SegFormer/UniFace/Sapiens + 可选 GroundedSAM）承接。
   - 仍有效的关联约束：`model_licenses.json` 中
     `usage=internal_development_only` 的后端（uniface/sapiens）由
     multi_router 构造时门控：默认不注册进路由，需
     `PIXO_ALLOW_RESTRICTED=1` 显式放行。

2. **DNG SDK clean-room 复审**（✅ **已清偿关闭，2026-09-07 R12 终章**）：
   - 部分实现注释仍引用 Adobe DNG SDK；发布前需确认 clean-room 或重写。
   - **部分清偿（2026-09-07 R11）**：huesat A 轨（HSV 三线性查表应用链 +
     use_dng 基准复刻分支）已整体删除，F18 高危 **H1/H2/H3/H9 清零**
     （`grep -iE "rawtherapee|rtengine|dng_render|dng_color_spec"
     src/pixo/render/core/huesat.py src/pixo/render/modules/huesat.py`
     零命中）；HSM 运行时应用由 OKLCh 点云形变（B 轨）与底座
     core/tone.py（clean-room）承接。**剩余另案**：color.py H4-H8、
     io.py H12、white_balance M 系（底座渲染在用，见 dng-sdk-review.md）。
   - **终章（2026-09-07 R12）**：color.py 痕迹清偿重写完成，三段全清——
     ① a) 类 2 函数（`camera_white`/`cam_to_prophoto_matrix`，约 55 行）按
     「场景白→PCS 白」约束唯一解重构推导：公式由白点定义 + DCP 矩阵规范
     语义导出，数值护栏（max 归一 / [0.001,1] pin / 振荡取均值）文档化为
     通用稳健性手段；**常数 pin ICC 4 位公开值**（PCS D50 (0.3457,0.3585)
     与 ROMM 4 位矩阵，`_PCS_D50_XY`/`_ROMM_RGB_TO_XYZ_D50_4` 模块级钉死
     并注明"勿换 7 位"红线）；② b) 类 6 处 + c) 类 2 处出处改公开规范/文献
     （DNG 规范 Camera Colorimetric Characterization 节及其子节
     "Translating Camera Neutral Coordinates to White Balance xy
     Coordinates"（规范 pp.80-81，子节名经 colour-hdri 对规范原文的引用
     交叉核对）/ ICC PCS / IEC 61966-2-1 / ISO 22028-2 / Lam 1985 /
     Spaulding 2000 / Lindbloom）；③ 相邻清扫：calibration.py 3 处 tag
     出处改 DNG 规范 tag 定义表、white_balance.py 头部出处与 2 处注释
     中性化（oracle/规范域口径）、test_color_math.py 2 处口径注释同步。
     **逐位等价实证**：git HEAD 原版 vs 重写版全函数（camera_white/
     cam_to_prophoto_matrix/cam_to_xyz_matrix/cam_to_linear_srgb_matrix/
     prophoto_to_linear_srgb_matrix/cam_wb_to_prophoto/cam_to_xyz/
     linear_prophoto_to_srgb）在 6 合成 DCP × 8 WB + 真 Nikon Z5 DCP ×
     8 WB 上逐位一致；gate `--check` 21 features 零漂移；RAW 金样本
     gate_defaults 24/24 PASS；全量测试 1480 passed。
     **grep 终态**：`grep -iE "dng sdk|dng_render|dng_color|adobe 源码|
     D50_xy_coord" src/` 仅存中性表述（clean-room 声明/黑盒 oracle 对齐/
     否定式"不使用/未读取/无依赖"/文件更名与退役历史记录），源码出处
     引用清零。遗留边界（不阻塞关闭）：io.py H12 的"Stage3 近似复刻"
     与 white_balance M 系的**行为级** oracle 注释（输出契约对照类）属
     clean-room 纪律允许的黑盒对照，非源码血缘——如需进一步收敛措辞
     可另开低优先条目；git 历史仍含旧注释（发布快照口径，F18 处置
     选项 C 归队长/用户）。

3. **第三方许可登记**（✅ **R22 #3 已收口，2026-09-10**；仓库根 `THIRD_PARTY_NOTICES.md`）：
   - ~~缺少统一 `THIRD_PARTY_NOTICES.md`~~ 已建成文：素材源
     `.agent-team/research/license-inventory.md`（researcher 盘点）+ F18
     `dng-sdk-review.md`（代码血缘节）；三项发布警示（~~huesat RawTherapee GPL-3.0 衍生~~ R11 已清偿：A 轨删除,
     2026-09-07 / DCP×6 再分发 / NC 模型门控）置顶。
   - **aesthetic 双台账冲突（原「需核验」+ 旧 `$GUANLAN_ROOT` 路径 vs MIT 定论）已校正**：
     `src/pixo/manifests/vision_models.json` 改为 `license=MIT` / `publishable=true` /
     `path_or_source="resources/models/aesthetic/aesthetic_scorer.pt"` / `delivery=in_repo`，
     与 `model_licenses.json` 对齐；两处 `delivery` 字段为 R22 新增的**交付形态显式标记**。
   - **segformer「publishable vs status 自相矛盾」已裁决（口径级，非改语义）**：
     `status` 与 `usage` 是**许可族档位**且互相镜像（`tests/unit/test_model_licenses.py::
     test_status_mirrors_usage` 钉死），`publishable` 是**可发布性权威字段**；原「矛盾」表述作废。
     引入第三档「待核验」usage 值需同步 `USAGE_VOCAB` 与 `multi_router` 门控语义（且
     `usage` 变更会改默认路由 = 行为变更），属独立变更 ⇒ **遗留（R23 候选）**。
   - **防复发断言的口径（R22 加固，2026-09-10）**——原断言 `tests/unit/test_tech_debt_invariants.py:96-100`
     只查 `path`/`local_path`/`file` 三键，而根台账 6 条**全部用 `files[]`**（且仅 1 条非空）
     ⇒ **实际检查路径数 = 0，断言空转**。现守卫**覆盖**：
     ① `files[]` 逐项相对仓库根存在性；
     ② 交付形态自洽（`delivery=in_repo` ⇒ `files` 非空；`files:[]` 仅限带 `delivery=external_*`
     且 `notes` 非空的条目）+ 期望表 `_MUST_BE_IN_REPO={"aesthetic_scorer.pt"}`；
     ③ `vision_models.json` 的 `path_or_source` 解析规则（`$VAR` 未设置 ⇒ 判「待核验」报红，
     不静默通过）；
     ④ 负控用例证明可证伪（临时副本改坏路径 ⇒ 生产断言必红；不触碰仓库文件）。
     **不覆盖**：许可条款真伪/法律判断本身（人工核验，NOTICES §7 速查表）；`notes` 文案真伪。
     ⚠️ 注意 ① 的副作用：`resources/models/aesthetic/aesthetic_scorer.pt` 是**非跟踪部署产物**
     （`.gitignore:58`），在**不含该产物的新克隆**上该断言会红并给出提示——这是有意的显式化
     （避免再次空转），CI 若需兼容请显式登记策略（R23 候选）。
   - **DCP×6 再分发核验（R22 #3，A3）**：逐项盘点结论 = **6/6 待处置**（详见
     `THIRD_PARTY_NOTICES.md §5` 的 6 行表 + 警示二）；文件内嵌**零**许可/版权条款文本，
     `ProfileCopyright(0xC6F4)` 一律为生产者标签 `RawLab fitted profile`。**注意**：DCP 本体
     是**运行时素材**（`service/runtime.py:41-46/320` → `Renderer` → `load_dcp`），
     不能按「纯登记资产」从打包面剔除。处置二选一（取得许可 / 替换为自产或官方 DCP 后重跑
     标定与门禁）= **R23 候选**，本轮只核验与登记。

4. **未声明可选依赖**（已处置，2026-09-07 F17）：
   - PyYAML 实为硬依赖，已升必装：decide/engine.py 与 know/graph.py 加载 YAML
     规则/图谱时 ImportError 直接报错、无回退路径，decide/rules/ 下 5 个规则
     YAML 属核心链路（代码仅用 yaml.safe_load）；requirements.txt 与
     pyproject dependencies 均加 `pyyaml>=6.0`。
   - scipy 保持真可选：render/core/color.py 懒 import least_squares，缺失回退
     纯 numpy 粗网格；挂新 extras `calib`（`scipy>=1.11`），README 安装节注明
     不装时标定拟合走 numpy 网格回退较慢。THIRD_PARTY_NOTICES.md 缺失归条目 3，
     由 F16 另批处理，不在本条范围。

5. **目录/路径历史残留**：
   - 历史文档中保留旧 `render/`、`rawlab`、`RawFlow` 路径说明，仅作迁移记录。

6. **命名空间迁移兼容层**（已解决）：
   - `src/render/` shim 已于 859082f 移除，统一为 `pixo.*`。

7. **感知质量门禁缺失**：
   - 金样本门禁仅防像素漂移（±1/255），不衡量与相机原图的观感差距；
     建议将 `scripts/ab_vs_camera_thumb.py` 的 ΔE/裁切预算纳入 gate。
   - 更新（2026-08-25 组合批）：7 维美学评分器已接线（batch 选片工厂 +
     loop 美学维度）；门禁口径扩展（ΔE/美学阈值纳入 gate）待做。

8. **WB 分桶标定与二维曝光分键**（已清偿，2026-08-25 组合批）：
   - warmth_curve 已拟合并落库：`configs/calibration/warmth_curve.json`
     （5 结点）；`WhiteBalanceStage.warm_cal_file` 缺省加载，缺失/非法回退
     内置斜率模型。DSC_0355 da/db 收敛至 ±6 门禁内（−12.25/+14.41 → +1.07/−3.78），
     对照 DSC_5236 不劣化。
   - 曝光标定表已升级 `(med_log2, wb_B)` 二维分键。
   - 更新（t66）：执行位已由 `loop._COLOR_PARAM_ALIASES` 桥接 colorcal，
     VibranceStage 占位类改为显式废弃声明（强制调用抛 NotImplementedError
     指引迁移），转发壳 modules/vibrance.py 已删除，无残留引用。

9. **0355 高光 cap**（已清偿 2026-08-25）：
   - 高光预算哨兵 ev≤log2((1-τ)/p99)，highlight_budget=0.02（相机实测 1.74%+余量）；
     拟合目标中位 L→均值 L。验收：clip_hi 3.68→2.29%（≤2.5）、|dL| 8.94→1.0（≤4）、色度≈0。

10. **跨包知识边须同组发布**：
    - 含跨包边的知识包必须同组提交、同组发布（见 `configs/knowledge/README.md`
      发布约定）；新增跨包边须在所在包 JSON 顶部声明 `_requires`，
      单包先行变更会制造悬空引用。

10b. **色彩规则执行位占位**（原编号 `10.`，R22 重编号为 `10b`）：
    - **重编号说明（2026-09-10 R22）**：本条原与上文 `10.`（跨包知识边）**重号**；本条在
      §运行时断言映射与 `tests/unit/test_tech_debt_invariants.py` 中**一直以 `10b` 被引用**
      （"条目 8/10b 防复活"），故补后缀而不整体后移——避免与外部引用编号（如
      `docs/OWN_PIPELINE_REVIEW_DISPOSITION.md ③④⑤⑧`）冲突。
    - 色彩规则决策键（vibrance/saturation.adjust）已通，下游 VibranceStage 为占位，
      参数暂不产生渲染差异；实装或映射至 huesat 待排期。
    - **现状补记**：该占位已改为**显式废弃声明**（强制调用抛 `NotImplementedError` 指引迁移
      colorcal，见条目 8 t66），由 `test_cleared_items_stay_cleared` 防复活。

11. **评分器权重部署**：
    - aesthetic_scorer.pt 就位后 make_default_scorer 自动切真模型（对照
      model_licenses.json 许可）；composition/overall 维度即可供 P2 规则消费。
    - 附注(t52 连锁,2026-08-25)：权重已部署(HF rsinema/aesthetic-scorer,MIT,
      resources/models/aesthetic/)。真模型对合成/低纹理图像系统性低分——
      实测噪声合成图 confidence≈0.52<0.6 阈值致 batch 推荐沉默（开发5 已在
      测试注入 FixedAestheticScorer 规避）。**分数分布标定须覆盖"合成/低纹理"
      域**（与 docs/metrics/proxy_distribution.md 同法补该域分位），否则依赖
      美学分的选片推荐与终止判定在此类输入下会系统性不触发。标定前生产语义：
      低分≠废片，仅是域外输入。
        - **已清偿(t98,合成/低纹理域深化)**：合成域分位表已入档
          docs/metrics/scorer_distribution.md（五大类探针+分位汇总+退化阶梯）。
          **关键结论**：同场景退化阶梯打分非单调、Spearman ρ≈0.03——域内相对
          排名自洽性不足，**不可作合成图质检硬结论**；batch synthetic 池改为
          隔离+池内排序仅供人审参考（include_synthetic 语义扩展见 batch.py
          MockAgentSelector.select），绝对分仍禁跨域比较。


12. **公式守卫日落条款**（✅ **前置已满足 ⇒ 日落条款关闭，2026-09-10 R22 F10**）：
    - **前置已落地**：引擎原生 AND（`decide/engine.py:222` 条件校验 / `:410` 求值）与原生
      between（`:384-389`）均在位；**首例已迁移**：`decide/rules/tone_clarity_rules.yaml:36-39`
      （注释「护栏④日落条款首例 (t60)：原 formula 带通守卫迁原生 all 条件」）。
    - **剩余 formula 逐条复核 = 无迁移对象**（`tone_clarity_rules.yaml:29/54/66/79` 纯常数；
      `region_rules.yaml:56/86` 线性增益；`exposure_rule_001.yaml:9` 需 `targets` 的
      `2.2*log2(target/current)`；`crop_suggest_rule_003.yaml:10`/`highlight_protect_rule_002.yaml:10`
      标量）——均非"带通守卫"型，故本条判**关闭**而非"择机迁移"。
    - 安全保障在位：`engine.py:151 _enforce_formula_lint`（`:186-242` 白名单，白名单外名字直接
      `DecideError`）——迁移期笔误可被拦。原 t40 裁定见历史档。


13. **外部评审处置 backlog**（2026-09-04 登记，出处
    docs/OWN_PIPELINE_REVIEW_DISPOSITION.md ③④⑤⑧；①cbrt 已驳回、
    ②⑥⑦⑨⑩⑫已达成、⑪由 t40 承接，不在此列）：
    1. **UI 滑杆感知均匀传递函数（P3）**：✅ **2026-09-04 已交付收口**
       （前置条件已履行：docs/UI_OKLCH_SPEC.md 增 §4.4 v1.1，修订 §2.1
       「不换算」决策适用范围——色相跨域参考读数禁换算不变，色度滑杆
       同域位置⇄参数值几何变换放行，提交值仍为原始 saturation）。
       实现：oklchScale.ts `sliderToC/cToSlider`（幂 γ=1.6，C∈[0,0.33]，
       中段→C≈0.109 落常用区）+ `chromaValueToSliderPos/chromaSliderPosToValue`
       （增强半程位置变换，负向恒等=调低精确线性）；SliderParam 可选
       toSlider/fromSlider（缺省=现版线性路径逐位不变，双轨零变化）；
       HslBandRow oklch 色度滑杆接入。单测 frontend/tests/oklchScale.test.mjs
       （node --test）+ e2e/chroma_warp_check.mjs（含 hsv 域 canvas 逐像素
       diff 基线）。分离色调面板「色度 C」未接入，如需同曲线另开批次。
    2. **RP-CCM 拟合 Tikhonov/Frobenius 罚 + 线性回退罚（条件触发）**：
       现有防护 = 99% 分位残差裁剪（scripts/fit_rp_ccm.py:164-186，实测
       更激进裁剪反而病态）+ 逐照片 EV 对齐（:227-228）+ lstsq 最小范数解
       （rp_ccm.py:215）。**触发条件**：新相机语料回归簇再现/拟合系数幅值
       异常时启用（当前 NIKON Z5_2 54/54 改善零反转，无病态迹象）；
       identity_rp_ccm（rp_ccm.py:152-156）可作回退候选基座。
    3. ~~**语料级 ±1EV 压力测试（P3）**~~ **已关闭（2026-09-08 R18 实验）**：54 张×5 臂 270 渲染零异常——曝光表补偿斜率 +0.006（平坦场景目标表）、ΔE 五臂极差 0.26 亚 JND、无过拟合翻转=优雅降级实为设计性直通。证据 .artifacts/ev_stress_experiment.md。原描述：单测层曝光不变性已覆盖
       （test_rp_ccm.py:136-142，k∈{0.25,0.5,2,4}，atol 1e-12）；缺
       54 张语料加 ±1EV 全局偏移重跑端到端 ΔE 的压力实验——验证曝光表/
       warmth 联动在极端 EV 下不崩、新表收益不是曝光窗内的过拟合。
    4. ~~**参考图低频加权（P3）**~~ **已关闭（2026-09-08 R18 实验）**：前提成立（残差自相关 0.71、低/高频功率密度差 100×）但药方证伪——27/27 交叉验证高斯低通加权仅 median −0.20（亚 JND）且 p95 +1.56 恶化，根因是模型容量而非采样加权；「分频/局部模型」替代方向留档（未来另立提案）。证据 .artifacts/rp_ccm_lowfreq_eval.md。原描述：现有双侧线性窗
       [0.01,0.90] 滤裁剪区/深阴影（fit_rp_ccm.py:44-46,149-157）；无频域
       加权。若未来拟合残余集中在低频结构（ISP 风格差），补高斯低通加权
       采样或分频段残差分析。

14. **FairFace 年龄/性别模型移除**（已清偿，2026-09-07 第九轮清债 F03）：
    - `pixo/vision/person.py`（FairFaceAge/PIXO_FAIRFACE_MODEL/
      get_fairface_age/fairface_health_info）整文件删除；vision_health 的
      `fairface`/`fairface_age` 健康键、`pixo.vision` 导出面、
      `vision_models.json` fairface-onnx 条目、治理文档 env 示例同步清零，
      grep src/tests/configs 无残留（防复活断言：
      `test_vision_models_no_unused_entries`）。
    - 历史评审文档（PIXO_LICENSE_REVIEW.md 等）按惯例不改写历史，以本条
      为移除事实记录；fairface.onnx（CC BY 4.0）不再随任何发布物分发。

15. **GroundedSAM（开放词汇分割）移除**（已清偿，2026-09-07 第九轮清债 F04）：
    - `pixo/vision/segmenters/grounded_sam.py`（GroundedSAMSegmenter/
      PIXO_GSAM_ENABLED/PIXO_GSAM_DINO/PIXO_GSAM_SAM）整文件删除；
      multi_router 兜底语义重设计：`DEFAULT_ROUTE="gsam"` 与 `_get()` gsam
      分支删除，**未知/未命中 prompt → 零掩码降级 + warn-once**（守
      exceptions.py 降级契约：路由未命中≠模型错误，不升级 manual_review；
      仅真实后端全败仍上抛 SegmenterUnavailable）；model_licenses.json 的
      grounding-dino-tiny+sam-vit-base 条目、models_reference.json 描述、
      segmenters 包导出面、治理文档 env 示例同步清零（防复活断言：
      `test_grounded_sam_removed` + 路由缺席断言）。
    - `pyproject.toml` 的 `pixo-vision-models` extras（torch/transformers）
      **保留**——非 gsam 专用：segformer_scenes/uniface_face/sapiens_body
      的 `_load()` 与 aesthetic.py（CLIP 评分器）均直接懒 import；
      rfdetr 走 rfdetr pip 包自带 torch 链。
    - grep src/tests 无 gsam/grounded_sam 活引用（仅防复活断言命中）。

16. **refine warm_sat HSV u8 往返精度**（记债，2026-09-07 第九轮 F05
    调查结论：生产启用面为零，暂不动代码）：
    - 现状：`modules/refine.py::apply_warm_sat_gamma`（:111-163）入口
      float→u8→HSV u8 量化往返；native `warm_sat_gamma_u8` 内核**已存在**
      （refine.py:140-142，与 Python LUT 回退共享同一 u8 域）——W4 实测
      该往返在 lr_baseline 预设启用且门控命中时 0.57~0.90 ΔE76
      （docs/metrics/u8_midpoint_precision.md，复跑
      `scripts/measure_u8_precision.py` PRESET_C）。
    - 启用面（F05 逐链核实）：**生产渲染零命中**——lr_baseline.json 在
      src/ 无任何代码引用；`resources/dcp/manifest.json`（登记它为
      lr_camera_standard_v2 目标）本身亦无 src/ 读者（仅文档图生成脚本
      gen_project_graph_frontend.py 提及）；23 张胶片卡（唯一进生产链的
      风格卡体系，know/cards._default_films_dir）零启用 warm_sat 曲线；
      默认链 refine default_params warm_*=None 直接短路
      （refine.py:102-103）；gate 金样本/预览/导出默认路径均不触发。
      当前唯一消费者 = `scripts/measure_u8_precision.py` PRESET_C（测量）。
    - 清偿条件与路径：若未来 lr_baseline 类 LR 基线预设接入生产风格卡
      体系、或 16bit 导出精度战役重启，按 t109 colorcal float 先例
      （3925b69：native F32 内核 + Python float 镜像 + golden 重生成）
      处置；**注意**「再 native 化」不构成清偿——u8 native 内核已存在，
      量化误差源于入口 u8 化而非算子实现，唯一有效路径是 float 化
      （super-dev warm_sat spike 结论落盘后可复核本条，预计同向）。
    - 防复发：无机器断言（潜在代价非现状缺陷，启动条件为产品决策）。

17. **compose free 模式像素矩形跨分辨率失准 × 掩码通道几何放大**（记债，
    2026-09-07 第九轮 M1 评审 I-2；根因既有，掩码通道为放大器）：
    - 现状：`modules/compose.py::compute_crop_rect` free 模式的 x/y/width/
      height 为**全画布像素**矩形。同一参数在不同渲染分辨率下相对裁剪窗
      不同（x=100px 在 320 宽 tier 占 31%、在 6000 宽导出占 1.7%）；loop
      的 adopt_crop 路径写 full-canvas 像素矩形（loop.py rect_norm_to_px），
      preview 在小 tier 按同像素值裁剪 —— preview/export 相对取景不同。
    - 掩码通道放大效应：`render/pipeline/region_masks.py` 的适配只做
      shape 对齐不做坐标重映射 —— 分割掩码（旧构图帧坐标）被直接 resize
      到消费帧；裁剪窗相对不一致时，同一掩码坐标在两线对应**不同场景
      内容**，区域效果落点错位可达 10%+ 画幅宽。F13 交付说明中「掩码通道
      两线仍一致（同参数同适配）」的论断**仅对 ratio/full-frame 路径成立**
      （该两线同参数同窗口；free-px-rect 路径不成立）。
    - 时间性防线（M1 评审 I-1 同批）：compose 参数指纹变化（含 adopt_crop）
      即清空 region 掩码缓存（loop._sync_region_masks），region_adjust
      静默直通 —— "不作为"优于"错作为"；本条清偿前掩码不跨构图复用。
    - 升级要点（原 hard-problems §6.1 记录，优先级提升）：涉及所有 free
      模式用户（非仅掩码链路）；清偿方向 = compose 参数 px→相对坐标
      归一化（独立战役，需迁移存量卡/用户参数）或适配器按裁剪窗差做
      坐标重映射。
    - 现状钉死：`tests/unit/test_region_masks_channel.py::
      test_free_px_rect_cross_resolution_geometry_mismatch_recorded`
      断言当前失配行为（防"静默变正确/静默变更坏"两边无感）——若未来
      清偿，该用例应**有意翻转重写**而非删除。

18. **skin OKLab 椭圆常数双源（core/skin.py 单源 vs colorcal.cpp 硬编码副本）**
    （记债，2026-09-07 r10；dev-1 椭圆重拟合落地后 native 副本失同步，
    test_native_colorcal_oklch 3 红，手工同步恢复；**✅ 已清偿关闭，2026-09-07
    R17 参数化**——详见文末终章注记）：
    - 现状：OKLab 椭圆六常数的**单源**在 `core/skin.py SKIN_OKLAB_*`（r10
      低彩度端重拟合：覆盖分位 0.96→0.98 + 软带 0.25→0.31）；
      `native/src/colorcal.cpp` 的 `SkinOklab*` constexpr 为**硬编码副本**
      （掩码逐位对齐纪律要求 hex 字面量：中心经 np.float32 舍入展宽、
      cos/sin 取 np f64 结果、半轴 round-trip 十进制——非简单抄值）。
      椭圆再变更时必须双侧同步，本次已同步（DLL 1.5.0 重编）。
    - 防复发（现状防线）：`tests/unit/test_native_colorcal_oklch.py::
      test_oklch_mask_isolated_bitwise`（掩码隔离路径与 skin_mask_oklab
      逐位断言）会在常数失同步时**自动抓红**——双源漂移可检出，但检出
      时点=下次跑测（非编译期/启动期）。
    - 清偿条件：**下次椭圆变更前**必须参数化——内核签名传常数
      （PixoRenderColorCalApplyLabF32Oklch 增椭圆参数结构体，Python 侧
      从 core/skin.py 单源填充），colorcal.cpp 副本删除；一并评估
      SkinStage oklch 掩码 native 化复用同一参数化内核（r10-hard-problems
      §6.3 遗留：skin oklch 掩码仍走 numpy ~150ms @512）。

    - **终章（2026-09-07 R17 清偿）**：椭圆常数参数化落地——
      ① `PixoRenderSkinOklabEllipse` ABI 结构（7 常数: 中心×2 / cos·sin /
      半轴×2 / 软带），`PixoRenderColorCalApplyLabF32Oklch` 增第 7 参
      （**DLL 1.6.0，签名与 1.5.0 不兼容**，ctypes 侧以 version ≥ 1.6.0
      为调用门，旧 DLL 自动回退纯 Python 路径）；colorcal.cpp 的
      `SkinOklab*` constexpr 副本**删除**，内核只从参数读椭圆。
      ② Python 侧单源流入：`_native.skin_oklab_ellipse()` 从
      core/skin.py SKIN_OKLAB_* 构造（缓存），对齐变换随字段携带——
      中心经 np.float32 舍入展宽 f64、cos/sin 为 np.cos/np.sin 产物直传、
      半轴 Python float 直传、软带舍入 f32（NEP50 除法语义）——椭圆再
      变更只改 core/skin.py 一处。
      ③ 逐位等价实证：v1.5.0（编译期常数）vs v1.6.0（参数化）同语料
      快照对拍**逐位零漂移**（`.agent-team/spike/_r17_kernel_snapshot.py`）；
      test_native_colorcal_oklch 7/7 绿（含新增
      `test_ellipse_parameterized_single_source`：字段=单源变换 + 自定义
      椭圆实时生效）；native 回归 29 绿；gate --check 21 features 零漂移
      （oklch 已是缺省域的现役金样本）；全量 1533 passed。
      ④ 性能无损：内核 11.96 vs 11.8 ms @512²（噪声内）。
      SkinStage oklch 掩码 native 化（复用本参数化内核）仍为独立机会项
      （非本债范围，见 r10-hard-problems §6.3）。

19. ~~**标定覆盖缺口：warmth 曲线/曝光表与语料 wb_B 域错配**~~ **已清偿-日光段扩域落地（2026-09-08 R20，用户批准执行 R19 条件触发选项）**：
    - **执行**：warmth 曲线补日光段 2 结点（D1 wb_B=1.10 / D2 wb_B=1.40，由
      R19 OOS-low 31 张逐照片最优 warmth 分箱中位数换算增益），拟合域扩为
      [1.10, 2.3984]；暖簇 5 结点全保留 → 域内 [1.7578,2.3984] 2001 点增益
      **逐位不变**实证（warmth_cal_auto gate case 零漂移）。
    - **效果**：OOS-low 31 张垫片偏差（生产−逐照片最优）median +0.537 →
      **+0.019** / p90 +1.117 → +0.109 / max 2.426 → 0.526；方向性过暖消除。
    - **金样本影响（报队长裁决）**：RAW gate_defaults 24/24 漂移（全部金样本
      wb_B<1.6778 落新日光段=预期改善性漂移，ΔE76 mean 2.34~9.91 / max u8
      24~65，方向=移除垫片过暖）；合成 gate 恰 2 case（default_dispatch max
      0.030 / card_portra_400 max 0.016，b=0.96 合成相机移入新插值段），
      warmth_cal_auto **零漂移**（域内不变性 gate 级证明）。基线重生成权在队长。
    - 证据：`.artifacts/warmth_daylight_knots_r20.md`、
      脚本 `_r20_fit_daylight_knots.py` / `_r20_warmth_daylight_verify.py`、
      机读 `r20_warmth_daylight_verify.json`。R19 评估记录（下存档）：
    - warmth 曲线 56% 样本、曝光表 wb 轴 89% 样本落标定适用域外（垫片近似
      生效中）；属 EV 无关的覆盖缺口，量级与影响待专项评估（是否扩域
      重标定 vs 垫片精度实测）。证据 .artifacts/ev_stress_experiment.md。

20. **auto-loop 与 `/decide` 缓存、`/timeline` 不联动**（✅ **已清偿关闭，2026-09-19 R26**）：
    - 历史脉络（记债 2026-09-10 R21 D3）：`SinglePhotoLoop` 自建状态机（`pipeline/loop.py:1783`）≠
      `service.state_machines`。auto-loop 结果只落任务表，**刻意不回写** `photo.last_decision` 与
      `runtime.state_machines`——后者是引擎决策缓存，`GET /api/photos/{id}/decide` 按其 schema
      原样透传，且有断言 `tests/unit/test_service_runtime_fixes.py:164-173`，写入 `LoopResult`
      会让该端点返回异形 `decision`（静默契约破坏）。**后果**：跑完 auto-loop 后
      `/timeline` 仍显示 RAW_PENDING，用户可能误判"没生效"。
    - **清偿（R26，取"显式回写契约"方向）**：`runtime._write_back_auto_loop` 在任务
      成功终局（done；cancelled/failed 不回写防半态污染）做三件事——① service SM 停在
      RAW_PENDING 时按 loop 转移事件序列**重放**（timeline/`photo.state` 反映全程轨迹与
      终态；已离开 RAW_PENDING 的重跑只补 `auto_loop_summary` 不重放，防非法转移）；
      ② 非状态事件原样 `add_trace`（`source="auto_loop"` 与用户编辑轨迹可区分）；
      ③ `photo.last_decision` 写 **decide 引擎同形** dict（decision/params/reasons/rule_ids/
      unreliable_regions/last_iteration + 扩展键 source/task_id/state，`decision`=loop 终态、
      消费方按 `source` 分派词汇表）——decide_photo 路径既有断言不受影响。回写失败
      可见（任务翻 failed + `write_back_failed:`）。测试
      `tests/integration/test_auto_loop_api.py::test_auto_loop_writeback_*` ×2。

21. **auto-loop 无任务级超时/取消**（✅ **已清偿关闭，2026-09-19 R26**）：
    - 历史脉络（记债 2026-09-10 R21 D4）：渲染无中断点，单次真 RAW 闭环实测 43.95–107.4s
      （`DSC_5236` 门禁 124s 含两次全分辨率渲染）。可控手段只有 `max_iterations`
      （缺省 3，env `PIXO_LOOP_MAX_ITERATIONS`，硬上限 5）+ `preview_long_edge`；任务一旦
      启动只能等其结束，且任务表无淘汰策略、跨 photo 排队无 `queued` 态。
    - **清偿（R26，协作粒度 = 迭代边界；渲染本体仍无中断点——诚实边界）**：
      ① `SinglePhotoLoop.run(stop_check=...)` 三边界询问（preview 迭代前 / 每轮迭代头 /
      FINAL_QC 全分辨率渲染前），真值即以当前状态早退（metadata.stopped/stop_reason）；
      ② 任务生命周期 queued→running→done|failed|cancelled（提交即 queued，单飞口径含 queued）；
      ③ `POST /api/auto-loop/{task_id}/cancel`：queued 即刻终态、running 置协作标记、
      终态幂等；④ 截止时间 env `PIXO_AUTO_LOOP_TIMEOUT_S`（0=不设限，缺省保持 R21 行为）
      超限落 failed+timeout；⑤ 任务表治理：终态 TTL（env `PIXO_AUTO_LOOP_TASK_TTL_S`，
      缺省 1800s、下限 60）+ 容量上限 200（最老先淘汰），提交时惰性清理；
      ⑥ 视图追加 created_at/started_at/finished_at/cancel_requested（纯追加键）。
      测试 `test_auto_loop_cancel_queued_and_running` / `..._deadline_marks_timeout` /
      `..._ttl_prunes_finished_tasks` / `..._cancel_http_endpoint` / `..._lifecycle_timestamps`。

22. **RP-CCM 运行时接入：显式否决**（结论落档，2026-09-10 R22 F07；CR-12 取"B 明确否决"）：
    - **结论**：`apply_rp_ccm` **不进运行时**（`src/` 命中仅 `render/core/rp_ccm.py` 自身：
      定义/`__all__`/docstring；渲染链 0 调用点），代码与单测**保留**作为未来"中性语境重拟合"的基础。
    - **否决依据（证据已复核）**：CR-12 原文引的 `−7.7%` 出自 **2026-08-28** 旧系数报告
      （`.artifacts/eval_rp_ccm_ab_nikon_z5_2_20260828_232324.md:14-16`，B−A `−0.475 (−7.7%)`、
      B 优于 A `45/54`）；`configs/color/rp_ccm_nikon_z5_2.json` 于 **2026-09-04** 被 commit
      `3fbe56d` 换成阶段二**联合优化**系数后，同脚本同语料复评 =
      `.artifacts/eval_rp_ccm_ab_nikon_z5_2_20260904_235522.md:14-16` `+1.147 (+19.3%)`、
      B 优于 A 仅 `22/54`（`:77`）。**转默认门槛线**（`docs/OWN_PIPELINE_STAGE2_DESIGN.md:38`：
      median 改善 ≥15% / 无 >1JND 回归 / p95 不劣化 / ≥2 相机复验）现行系数 **0/4 通过**，
      且第二相机语料本机不可得 ⇒ 否决。
    - **勘误落点**：`docs/R21_CHANGE_REQUESTS.md` CR-12 条目下的「勘误（2026-09-10）」块
      （照该文档 §0 的更正手法）；`src/pixo/render/core/rp_ccm.py` 模块 docstring 顶部同步标注。
    - **触发复核条件**（出现即须重议）：中性语境下新 A/B median 改善 ≥15% 且 p95 不劣化；
      或第二台相机语料入库后复验通过。备选路径与代价见 `.agent-team/design-r22.md §0.1①`
      （换表 + 定死在线插入点 + 补 gate case + 全量回归，属独立战役）。

23. **`build/lib/pixo/**` 旧副本漂移**（记债，2026-09-10 R22 F10；原 R21 续排候选 #25）：
    - **事实**：`build/lib/pixo/render/core/skin.py` 仍是旧 OKLab 常数（`A=0.01516` /
      `SOFT_BAND=0.25`），而 `src/pixo/render/core/skin.py` 是 R10 重拟合后的
      `0.015127` / `0.31`（mtime 2026-09-04）；`build/lib/pixo/pipeline/loop.py` 为旧实体。
    - **误取风险三面核查（R22 实测，均不取 build/lib）**：
      ① **git**：`build/` 已在 `.gitignore:90` 排除，`git ls-files build` = 0 条；
      ② **打包**：`pyproject.toml [tool.setuptools.packages.find] where=["src"]`（`:41-44`，
      `include=["pixo*","render*"]`）⇒ `build/lib` 不在发现根，**不进 wheel/sdist**；
      ③ **运行时/测试**：`tests/conftest.py:21-22` 把 `src` 插到 `sys.path[0]`；本机 editable
      安装的 finder `MAPPING` 指向 **src 布局**（实测其值为已悬空的 `K:\work\project\pixo\pixo`
      ⇒ 裸 `python -c "import pixo"` 失败，而**不会**回落到 `build/lib`）。全仓 `build/lib`
      文案命中仅本清单。
    - **处置口径（本轮）**：**明确排除 + 文档说明**（`.gitignore` 就地注释 + 本条）；**不删除**
      `build/lib`（怕影响构建流程）。**清理动作登记 R23**。
    - **遗留（同批发现）**：本机 `pip install -e .` 状态陈旧（editable finder MAPPING 指向
      不存在的路径）⇒ 脱离 pytest 的裸导入依赖 `PYTHONPATH=src`；重新执行 `pip install -e .`
      即修，属环境问题 ⇒ **R23**。


### R21 总审续排候选（未编号，待专项评估后正式入账）

- 后台 segmenter 预热线程未持 `_segmenter_infer_lock`（与供给路径互斥面待核）；
- ~~`build/lib/pixo/**` 陈旧副本与 `src/` 漂移~~ **已正式入账为条目 23（2026-09-10 R22）**。
- `crop_suggestion_applicable`（注册面 `loop.py:769`）与运行期 `crop_suggestion_available`（`:1387`）命名并存，无规则引用；
- `src/pixo/render/bench/preview_cold_baseline.json` 坏 JSON（`JSONDecodeError` line 35）且会进打包产物，全仓无消费者；
- `render/bench/preview_v16_nef_baseline_*.json` 的 `raw` 指向已消失的 `K:\data\photo\corpus_a\raw\...`（该路 compare 本机无法复跑）；
- `scripts/auto_real_edit.py:154,163` 扫描根为 `<corpus_root>` 占位符（不带 `--photo` 开箱不可跑）。

### R23 待办候选（R22 会话登记，2026-09-10）

| # | 事项 | 来源 | 性质/代价 |
|---|------|------|-----------|
| R23-1 | `build/lib/pixo/**` 清理评估（明确排除已落地；**删除**仅在不触及构建流程时做） | 条目 23（F10 #25） | 清理型；需先确认 `setup.py build`/打包链依赖面 |
| R23-2 | DCP×6 处置：取得 RawLab 再分发许可，或替换为自产/官方 DCP 后重跑标定与门禁 | 条目 3（F10 #3 / A3） | 发布阻断型；替换会牵动 `configs/color/*`、`skin_oklab.json`、暖度/曝光表与金样本 |
| R23-3 | segformer「待核验」引入第三档 `usage` 值（需同步 `USAGE_VOCAB` + `multi_router` 门控语义 = 行为变更） | 条目 3（口径裁决遗留） | 语义型；须与路由默认行为一并裁决 |
| R23-4 | 本机 editable 安装陈旧（finder MAPPING 悬空）重装 `pip install -e .`，恢复裸导入 | 条目 23 遗留 | 环境型；`pip install -e .` 即修 |
