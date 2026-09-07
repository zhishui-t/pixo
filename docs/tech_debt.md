# Pixo Tech Debt / 技术债清单

> 详细许可与发布阻断项见 [`PIXO_LICENSE_REVIEW.md`](PIXO_LICENSE_REVIEW.md)。

## 运行时断言映射（tech-debt 批次）

以下条目已固化为 `tests/unit/test_tech_debt_invariants.py` 收集期断言，复发即告警：

- **条目 1 关联约束**（受限后端默认不进 multi 路由，`PIXO_ALLOW_RESTRICTED=1` 显式放行）
  → `test_restricted_model_backends_gated_out_of_router_by_default`（含台账登记在位 + 放行机制正向验证）；
- **条目 1 + 6 + 8/10b 防复活**（YOLOE 适配器与代码级引用清零、`src/render` shim 不回归、
  VibranceStage 废弃占位显式调用抛 NotImplementedError）
  → `test_cleared_items_stay_cleared`；
- **条目 3**（model_licenses.json 登记路径与当前路径同步，无悬空）
  → `test_model_license_registry_paths_resolve`。

判定为**不可机器断言**的条目及理由（维持人工跟踪）：

- 条目 2（DNG clean-room 复审）：法律判断，非代码不变量；
- 条目 4/7（可选依赖声明、门禁口径扩展）：清偿动作本身是写文档/扩 gate，断言其"缺失"恒红无意义；
- 条目 5（历史路径残留）：条目自身声明"仅作迁移记录"，无需防复发；
- 条目 9（高光 cap）：运行时哨兵（highlight_budget）已内建，无需重复断言；
- 条目 11（评分器分布标定）：t98 已清偿且结论是"不可作合成图质检硬结论"——语义约定属代码评审层；
- 条目 12（公式守卫日落）：触发前置（原生 AND/between 落地）未到；
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

2. **DNG SDK clean-room 复审**：
   - 部分实现注释仍引用 Adobe DNG SDK；发布前需确认 clean-room 或重写。

3. **第三方许可登记**（NOTICES 已建，2026-09-07 F16；仓库根 `THIRD_PARTY_NOTICES.md`）：
   - ~~缺少统一 `THIRD_PARTY_NOTICES.md`~~ 已建成文：素材源
     `.agent-team/research/license-inventory.md`（researcher 盘点）+ F18
     `dng-sdk-review.md`（代码血缘节）；三项发布警示（huesat RawTherapee GPL-3.0
     衍生 / DCP×6 再分发未核验 / NC 模型门控）置顶。
   - `model_licenses.json` 与 `vision_models.json` 的过期冲突（aesthetic「需核验」
     + 旧 `$GUANLAN_ROOT` 路径 vs MIT 定论）**仍待处置**（NOTICES §3 冲突 A 已
     如实记录，台账更新不在 F16 范围）；segformer 条目 publishable/status 自相
     矛盾同挂待核验。

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

10. **色彩规则执行位占位**：
    - 色彩规则决策键（vibrance/saturation.adjust）已通，下游 VibranceStage 为占位，
      参数暂不产生渲染差异；实装或映射至 huesat 待排期。

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


12. **公式守卫日落条款**：
    - 引擎原生 AND/between 落地后，新规则改用原生 condition，存量公式守卫规则
      （clarity_flat 等）择机迁移（裁定见 t40 复审记录）。


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
    3. **语料级 ±1EV 压力测试（P3）**：单测层曝光不变性已覆盖
       （test_rp_ccm.py:136-142，k∈{0.25,0.5,2,4}，atol 1e-12）；缺
       54 张语料加 ±1EV 全局偏移重跑端到端 ΔE 的压力实验——验证曝光表/
       warmth 联动在极端 EV 下不崩、新表收益不是曝光窗内的过拟合。
    4. **参考图低频加权（P3，与阶段二 L-4 p95 上限同源）**：现有双侧线性窗
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
    （记债，2026-09-07 r10；本次 dev-1 椭圆重拟合落地后 native 副本失同步，
    test_native_colorcal_oklch 3 红，手工同步恢复）：
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
