# Changelog

## 2026-09-07 — 第十一轮：huesat A 轨删除（GPL 清偿）× scene 门控

- **A 轨删除**（337702e，用户拍板「删」）：HSV 查表应用链（core 24→17 函数）+ use_dng
  复刻分支删尽；RawTherapee/rtengine/dng_render/dng_color_spec grep 清零（F18 高危
  H1/H2/H3/H9 落面；color.py H4-H8 另案）；前置补点云——含表 DCP 3/3 全覆盖（回退链
  断裂风险消除），重写 oklch-or-no-op（缺省翻 oklch+退役域 warn-once）
- **【知情裁决】**：评估报告「生产零影响」被 dev-2 实测证伪——10 张 Fujifilm 卡在用
  A 轨（strength 0.15~0.45），删除=10 卡 A→B look 替换（ΔE median 0.19~1.02 亚 JND/
  超 JND 像素 10.5~29.6%，13 卡不变）；队长裁决接受（GPL 清偿目标不变+中位亚 JND+
  单点 revert 可逆），qa 独立抽验 3 卡量级吻合；**用户推翻权保留**
- **scene 门控**（098d42c，观察窗清偿）：诊断发现 scene 判定渲染路径从未接线（portrait
  恒缺）——无人像图磨皮一直在默认链误伤（覆盖最高 90.2%）；修法=未分类图覆盖率上限
  0.50（F11 语料人像/风景间隙）判误判 no-op+warn，portrait 豁免；人像位级保全
  （X1_DSC_0466 四 case）；RAW 基线 round11-regen 恰 12 case（qa 三证合一归因：
  门控 100% 驱动）
- tech_debt #2 huesat 部分清偿、FUNCTION_GATE_SPEC §5.12 收缩、theta_io 断言修复

验收：全量 1478 passed / 5 skipped / 1 xfailed / 0 failed（-6 对账=删 A 轨用例 -8+
门控 +3+1）；GPL grep 三文件零命中；gate --check 20 零漂；RAW 24/24（round11 后）；
门禁 .r11_ok PASS（六条+推翻权回滚提示）

## 2026-09-07 — 第十轮：oklch 第二批切换 × JND 统一 × 打包修复

- **打包三连修**（用户质询引出）：wheel 构建失败修复（data-files 目录通配炸构建，
  任何检出可复现——显式文件列表化）；films 23 卡补进包（非递归 glob 漏配）；
  **aesthetic_scorer.pt 随 wheel 分发**（用户拍板开箱即用，310MB wheel；加载器补
  安装态候选链 env>仓库>sys.prefix/data>前缀，3 单测钉死；初版 NOTICES「随 wheel
  分发」误报实为构建失败，已实测修正留痕）；data/golden 48MB 移出打包（开发资产）
- **JND 口径单源化**（baec4ec）：权威常量 `JND_DELTA_E=2.3` 落 pipeline/perceptual.py，
  loop 早停行为零变化（钉死），评估脚本统一引常量——F19 发现的 1.0/2.3 两套并存清偿
- **colorcal oklch native 内核**（dca189c，super-dev spike 先行）：ApplyColorCalLabF32
  换 SkinMaskOklab 整体进 native；15×（131ms Python）→~2× hsv native（提速 ~11×，
  4096px 外推 8.4s→0.75s/图）；掩码隔离逐位对齐/全参数 1 ULP f32；ucrt≠msun cbrt
  陷阱以 FreeBSD msun 逐句复刻处置（省 33% 掩码成本）；ABI 1.5.0
- **skin OKLab 椭圆重拟合**（dca189c）：低彩度端过紧修正（覆盖分位 0.96→0.98+软带
  0.25→0.31 重定标，中性灰不变量保持）；三验收全过（覆盖腰斩 5/72→0/门控分叉
  2/72→0/误伤闸门守住）；椭圆常数双源（cpp 硬编码副本）记 tech_debt #18，
  bitwise 测试为防复发防线，清偿=下次变更前参数化
- **oklch 第二批切换**（02a77b1）：skin/colorcal default_params 翻 oklch——四涉域
  stage 全部完成 t52 渐进方案。依据=人像域召回/精度修正（F11+refit 三验收）；
  RAW 漂移=掩码边缘 ~2% 像素重分布的预期语义变化（qa 独立加严归因：colorcal
  贡献精确 0/skin 100% 驱动/两代椭圆 RAW 覆盖 IoU 0.979-0.997）；film_pro_400h
  补 skin 钉域（唯一无键卡盲区，F07 计数 23）；三组基线队长重生成（RAW 24/
  gate default_dispatch v3/region_adjust v2）
- **huesat A 轨删除评估**（research）：有条件可行 2.5-3.5 人日（210 行精确界定/
  生产零影响/B 轨血缘干净），前置=补 5 个无点云 DCP（0.5 人日）——GPL 血缘
  釜底抽薪路径，待拍板
- 观察窗（qa .r10b_ok）：无人像高覆盖磨皮两代同在（scene 门控/覆盖率上限留待
  下轮）/双肤区强度尾部 9 张亚 JND/gate skin case 对软边带零敏感建议增补探针

验收：全量 1484 passed / 5 skipped / 1 xfailed / 0 failed（第九轮基线 1474+10
全为新增测试对账）；A1 23 卡双基线字节级全等；RAW 24/24（round10-regen 后零漂）；
性能缺省 1.02×/意图 ~2× hsv native；门禁 .r10b_ok PASS（六条结论+归因独立加严）

## 2026-09-07 — 第九轮战役：收口清债 × oklch 切默认 × M1 掩码驱动渲染

- 模型栈清债（651f5d1，F03/F04）：FairFace 彻底移除（person.py 整删、manifest/路由/
  health 同步、防复活断言）；GroundedSAM 移除（gsam 全链零残留，multi 路由未知 prompt
  兜底改零掩码降级+warning，torch extras 收缩）；tech_debt 条目 14/15 清偿在案。
- RAW 金样本重验与基线重生成（b187d27，F06）：qa 首验 24/24 FAIL（基线 stale）→
  gate_defaults 团队重生成对齐已验收渲染链 → 复跑 24/24 PASS。
- oklch 切默认三道前置修补：存量 23 卡显式钉 hsv（ef4473d，F07——69 条
  `color_domain:"hsv"` 纯插入：hsl 12/split_tone 12/skin 22/colorcal 23，A1 逐位保证
  不再依赖 stage 缺省）；gate 缺省分派 case + 存量卡全管线 golden（17→19 features）+
  patch_protocol band 归属与 stage 缺省同源化 + canonical 透出确认（ce92c73，F08/F09）。
- oklch 第一批切换（3d2db90，F10）：hsl/split_tone `default_params` 缺省翻转
  "hsv"→"oklch"，落点纯度两文件零行为改动；缺省断言修订 7 项零删除无净弱化；A1 存量卡
  23/23 sha256 三方字节级全等（tester 独立复跑 vs 钉域前基线 vs dev 存证）；RAW 金样本
  24/24 u8/u16 逐位零漂移；gate 基线 v2 治理（仅 default_dispatch 条目变更）。
- F11 skin+colorcal 意图级 A/B（只出证据不切换，缺省未动）：skin 伤害类不劣于+强度
  不劣于（B/A 0.935）；colorcal 质量不劣于、**性能劣于 ≈15×**——双结论如实入档，
  第二批切换待观察期后由用户决策。
- M1 掩码驱动渲染全链：region_adjust stage（512bd0d，F12——掩码区域化曝光/饱和度调整，
  order 56-59，DOMAIN_GAMMA_RGB，默认 enabled=False）；掩码通道 preview/export 双线
  注入（35af288，F13——堵 RawRenderBackend 无 state_extras 缺口）；decide region.*
  点分键接线（b812061，F14——`_DOTTED_PARAM_REGISTRY`+enabled 联动+指标键注册+
  region_rules.yaml 首版规则，默认零变化）；M1 验收资产 gate case（F15，20 features）。
  独立评审（reviews/m1-review.md）阻断 0/重要 4/建议 8；修复批（fc2bfa8）修
  I-1/I-3/I-4/S-1/S-2/S-3/S-5 七项（NaN 守卫/掩码生命周期/顺序合成钉死），
  I-2 px-rect 跨分辨率失配记债 tech_debt #17。
- 合规与治理：THIRD_PARTY_NOTICES.md 编制（d25f70c，F16——238 行，tech_debt #3 处置，
  huesat GPL/DCP 未核验/NC 门控三项发布警示置顶）；PyYAML 升必装 + scipy 挂 calib
  extras（0d5372a，F17——tech_debt #4 处置，同笔含 F05 lr_baseline 记债/条目 16）；
  F18 DNG SDK 复审发现 huesat RawTherapee GPL-3.0 血缘（高危未决，发布前必决）；
  F19 感知质量门禁评估+提案（tech_debt #7，只出评估不实施）。
- 验收：全量 1474 passed / 5 skipped / 1 xfailed，0 failed（test-report.md @ fc2bfa8，
  189s；基线 1396 不降、+78 全部为本轮新增测试逐项对账）；RAW 金样本 24/24 逐位零漂移；
  gate --check 20 features OK；A1 存量卡 23/23 三方字节级全等；qa 总审 PASS（.qa_ok，
  F01~F19 逐条达成，阻断性缺陷 0、战役累计 qa 修复 10 处均留档）。

## 2026-09-05 — 路线图收官批：HSM→OKLCh 运行时接线 · 风格卡全链接线（t64/t66）

- HSM→OKLCh 接线（t64，自研管线路线图最终承诺）：新增 `core/huesat_oklch.py`
  OKLCh 域连续形变（t17 点云 2765 点 → IDW 栅格化 72×24×24 + OKLCh 三线性）；
  `HueSatStage` 按 `color_domain` 分派——hsv 走 DCP HSM、oklch 走形变，点云按
  DCP 名 token 子序列自动匹配 `configs/color/hsm_oklch_*.json`，缺失回退 hsv 链
  （一次性告警）；缺省仍 hsv，零行为变化。
- 风格卡全链接线（t66）：`GET /api/styles` + `/api/styles/{id}` 后端端点
  （from_films_dir 降载）；前端风格卡面板替换 mock 接真数据（Store/Panel/client
  全链）；`film_portra_400.json` 历史双卡退役（守卫 24→23）；client.ts 未接线
  端点清理。
- 至此自研渲染管线路线图全部里程碑（M-O1/O2/O3/D1/D2/L*）完成。
- 验收：54 张语料接线对照两域分歧 A↔B ΔE2000 median 10.890 / p95 16.070
  （≈4.73 JND，`.artifacts/hsm_oklch_eval.md`）；单测 + 全量回归绿；风格卡守卫
  24→23。

## 2026-09-05 — 循环治理批：LLM 影子模式 · JND 早停 · 滑杆感知传递 · 切默认评估（t46-t65）

- LLM 影子模式（t46，评审⑧采纳）：`PIXO_LLM_SHADOW=1` 默认开，低分验证后晋升，
  影子拒绝留 trace 事件 `llm_shadow_reject`；迭代轨迹回放（t48）：
  `scripts/loop_replay.py` + 单测；G-4 修复（t51）：`generate_gate_goldens.py
  --out` 默认路径改正确位置，仓库根无参可跑。
- JND 感知早停（t59，评审⑨采纳）：`pipeline/perceptual.py` 收尾，ΔE2000
  median <0.5 连续 2 次终止 perceptual_convergence。
- UI 滑杆非线性传递（t63，tech_debt 13.1 清偿）：`oklchScale.ts` gamma 幂映射
  （sliderToC/cToSlider），HslBandRow oklch 色度滑杆接入，hsv 域零变化。
- Oklab 切默认专项评估（t62，只评估不执行）：`.artifacts/oklch_default_eval.md`——
  收益 A/B 只覆盖 hsl/split_tone 两内核，skin/colorcal 无 A/B 闸门；切缺省的
  实际作用面为 4 个 stage 的 `default_params()`，波及存量胶片卡（12+12+18+24 张）
  与全部默认渲染（skin 缺省开启），必破 A1 红线；翻转实验金样本 0 张报警属守卫
  盲区。结论：不可一次翻 4 个缺省，先卡级锚定 + 分派级守卫 + 分 stage 渐进。
- tech-debt 运行时断言（t65）：`tests/unit/test_tech_debt_invariants.py` 固化收尾；
  评审处置表 v2（t58）：`docs/ARCH_REVIEW2_DISPOSITION.md` 5 维度 14 条逐条实证
  （已达成 4 / 部分 4 / 在途收口 3 / backlog 3 / 驳回 1）。
- 验收：切默认评估基线全量 1360 passed / 5 skipped / 1 xfailed、四缺省翻转实验
  11 failed 逐项归因（`.artifacts/oklch_default_eval.md`）；滑杆传递单测
  `frontend/tests/oklchScale.test.mjs` + `e2e/chroma_warp_check.mjs`，hsv 域零变化。

## 2026-09-04 — 阶段三首块批：学习后端治理四门禁 + 光照估计评估否决（t42/t43）

- 治理框架四门禁（t42，全部构造性验证）：① 许可白名单硬拒（MIT/Apache-2.0 only，
  deny-by-default，六组变异测试含真实 manifest 翻转）；② import 隔离预铺门
  （`src/pixo/render/learned/` 未建先铺门，红/绿/skip 三态实跑）；③ env opt-in
  统一约定 `docs/LEARNED_BACKEND_GOVERNANCE.md`（15 个 env 逐一在 src 实存核对）；
  ④ 三证据转正模板 `docs/LEARNED_BACKEND_PROMOTION.md`（收益 <1 JND 记录无转正
  价值即停）。
- 光照估计评估（t43，不接运行时）：Gray-World/Gray-Edge/White-Patch 三经典法
  纯 numpy + WB 逆链，54 张语料全数劣于 as_shot（最佳 GE1 10.180 vs as_shot
  5.946，improvement −1.841 JND 为负）——春节钨丝灯场景内容主导全局统计，
  经典"场景平均灰"假设失效；诚实结论无转正价值，as_shot 链维持现状。
- 验收：终审 GO（`.artifacts/stage3_first_verdict.md`）；全量 1334 passed /
  5 skipped / 1 xfailed；src 渲染零 diff。

## 2026-09-04 — 评审收口批：标定敏感金样本 · patch 闸门 oklch 防御 · 评分器守卫（t38-t41）

- gate 增补 exposure_cal_auto / warmth_cal_auto 两 case（15→17 features，t38）：
  触达 auto 标定路径，换表敏感实证 + 回退演练双向验证——收口阶段二入库终审
  上报的"金样本对标定表零敏感"门禁缺口。
- patch 闸门 oklch 防御（t40）：hsl.bands oklch 域感知拒绝（hue 越界硬拒）+
  协议文案内嵌量纲说明 h∈[0,360) / C 0-0.33 / L∈[0,1]；评分器 sRGB 边界守卫
  4 项测试 + 突变验证（t41）。
- 外部评审处置表 `docs/OWN_PIPELINE_REVIEW_DISPOSITION.md`（t39）：12 条逐级
  实证（6 已达成 / 4 backlog / 1 驳回 / 1 部分）。
- 验收：全量 1130+ passed 绿（commit 记录口径）；gate 数量守卫 17 features。

## 2026-09-04 — 阶段二入库批：标定新表入正式 configs + cal_ev_weights 修复（t36/t37）

- calib_out 四件替换正式位：warmth_curve / target_offset / z5ii_neutral_trim /
  rp_ccm_nikon_z5_2（skin_oklab 新旧相同未动），全部经 sha256 + 运行时加载链
  双逐位校验；旧表备份 `configs/color/calib_prev/`（README 含回退指引）。
- 端到端收益落地：ΔE2000 median 6.649→4.251，54/54 逐照片改善零反转。
- `scripts/calib/optimize.py` 修 cal_ev_weights 重复 wb 键取值分歧（12 万次对拍
  归零；src 代码零改动）。
- 金样本 SOP：15 features 零漂移重生成 + reviewer 签注；"金样本对标定表零敏感"
  如实留痕为门禁覆盖缺口（后由 t38 补 cal_auto case 收口）。
- 验收：入库终审 GO（`.artifacts/stage2_adopt_verdict.md`，回退演练实证可回滚）；
  全量 1297 passed / 4 skipped / 1 xfailed（QA 复跑 173s 一致）。

## 2026-09-04 — 阶段二首跑批：M-D1 可微标定 + G-5 收口，运行时零变化（t30-t34）

- `scripts/calib/` 可微标定链：diff_core（torch 可微代理，保真门 PASS
  median/p95=0/0）、theta_io（θ 五组件 configs 双向序列化字节级恒等）、optimize
  （Huber-Lab proxy + 罚项 + Adam→L-BFGS）、eval_stage2（独立双轨评估，与训练侧
  数值逐位一致，QA 缓存重放复现）。
- 首跑收益：端到端真值 ΔE2000 median 6.658→4.244（+36.3%），54/54 张全改善
  零回归；checkpoint 轨迹单调下降。
- G-5 收口：转默认门槛线 3/4 过（≥2 相机复验待语料补齐）；阶段一遗留回归簇
  （523x-5250 拍摄段 9/54 张）全额消除——最差照片 DSC_5250 +2.607→−5.15；
  分组系数将自身残余 8 张轻微回归（均 <1 JND）压至 ≤+0.224。
- 新表落 `configs/color/calib_out/` 对照档不切默认；torch 只进 scripts/（120 个
  src 文件零 torch import），运行时零变化铁律达成（QA git 全仓 diff 审计）。
- 验收：终审 GO（`.artifacts/stage2_qa_verdict.md`）；全量 1297 passed /
  4 skipped / 1 xfailed；git diff src 零行。

## 2026-09-04 — 阶段一批：Oklab 编辑域双轨 + RP-CCM 并联 + 项目图谱（t1-t25）

- M-O1 Oklab 双轨：`core/oklab.py` 转换内核（往返 1.8e-10）；hsl/split_tone 双域
  化（`color_domain` band schema v2，存量 24 张胶片卡零迁移、hsv 域逐位不变）；
  skin OKLab 椭圆重拟合 `skin_mask_oklab`（核内召回 0.955 / 背景误报 0.258，
  旧 0.271）；native `oklab.cpp` F32 内核与 numpy 逐位等价（10/10）；前端
  color_domain 双刻度（hsv 域视口像素级零变化）。
- M-O3 RP-CCM 并联（只报告不切默认）：`core/rp_ccm.py` + 拟合/评估脚本，54 张
  语料 ΔE2000 median −7.7%（45/54 改善）；9/54 回归簇（523x-5250 拍摄段）如实
  上报，留阶段二可微标定消化。
- 项目图谱：ast 解析生成脚本 + 后端/前端/全量三份图谱（268 节点 / 660 边）。
- 质量资产：gate 金样本 15 case（hsl_oklch / split_tone_oklab / skin_oklch 新域
  case + `SKIN_OKLAB_*` 常数逐位锁定，终审 GO 条件项 G-1 批内关闭）；
  `ab_intent_compare.py` 意图级 A/B（不劣于闸门全过，高光落点误差 median
  11.27°→4.48°、近白 C 强加 0.0756→0.0115）。
- 验收：QA 终审 GO 有条件放行（`.artifacts/stage1_qa_verdict.md`）；全量
  1231 passed / 4 skipped / 1 xfailed；hsv 旧 12 case 金样本三方核验逐位不变。

## 2026-08-27 — 全链正确性修复批：meta/decide/vision/service/pipeline/frontend

- meta（e216743）：burst aware/naive 时区混排统一归一 UTC naive（混相机照片库
  不再崩溃）、无时间戳照片不再丢图、超大组 parent_id 全局唯一（原跨组碰撞）；
  exif Flash 按 EXIF 位语义解析（'No Flash function' 不再误判 on）、GPS (度,分)
  二元组保留分钟位（原 ~1° 误差）。
- decide+know（417bc2a）：rules.py 同名包遮蔽致 load_rules 不可达修复；
  check_termination off-by-one 消除（max_iterations 不再截断当轮规则计算）；
  improvement 改朝目标的距离缩短量（振荡不再算改善）；知识层 PIXO_CONFIG_ROOT
  去 CWD 化（不再静默丢包）、rag IDF + 词边界匹配、graph 命中 1-hop 邻域扩展。
- vision（e922dae）：multi_router 全组失败抛 SegmenterUnavailable（loop 升级
  manual_review，模型错误不再冒充无检出）；grounded_sam 默认关（数 GB 隐式下载
  改 PIXO_GSAM_ENABLED opt-in）；vision_health 聚合可见；internal_development_only
  后端 PIXO_ALLOW_RESTRICTED 合规门控。
- service/state/review（47cedef + 26a97c5）：async 阻塞调用线程池化（不再冻结
  事件循环）；runtime 假接线修复（PIXO_SEGMENTER 真生效、非法值 fail-fast）；
  会话真 LRU（逐出同步清理死 id）；SQLite check_same_thread=False + 写锁 + WAL；
  MANUAL_REVIEW 补出边不再卡死；配套 8 个回归用例补齐。
- pipeline+agent（09616ab）：`_DOTTED_PARAM_REGISTRY` tone/clarity/dehaze 悬空
  语义键落进 stage 桶（原整链静默忽略）；dehaze 规则命中联动 enabled；batch RAW
  半尺寸解码通道（原批量 RAW 输入 100% no_image 判废）；patch 闸门 NaN/Infinity
  封堵；suggest 提取器剥离回显前缀 + chat 连续失败熔断冷却。
- frontend（7d6578b + 2debcc7）：types/client 对齐后端真实 schema（删 as 强转）；
  滑杆修复（曝光键 ev→mode、tone ±100→±1、hsl bands 数组 patch）；onChangeEnd
  防抖（消除 PUT 请求风暴）；导出真轮询；后端照片接线/状态过滤映射/原图契约
  三断点填空；死代码与未用依赖清理（bundle −24KB）。
- 验收：前端 tsc 零错误 + vite build 通过 + e2e 冒烟 5/5、在线模式 7/7（真实
  后端实测）；test_loop_termination 新增 8 用例；runtime 假接线回归 8 用例。

## 2026-08-27 — 渲染正确性与验证链批：native 逐位一致 · 曝光探针 · 标定加载治理

- render 正确性与性能（57c7870）：stage 缓存键补全链参数指纹——修复 exposure
  探针读 whitebalance 参数命中陈旧缓存的活跃像素 bug（改 WB 后 EV 不更新）；
  tone lrfit 六键接回处理链、色彩矩阵插值序对齐 DNG SDK、colorcal 未声明参数补
  schema 防 native 越界；性能指纹链式传递 ~310MB→8KB/渲染（3457x）+ 三把细粒度
  锁 + RAW 双解压消除（−1.3s/次）。
- native 逐位一致（3be14be）：colorcal DLL 中性权重改平台+高斯尾并 MinGW 重编，
  native vs Python 全量路径 max diff 0.05098→0.0，一致性测试收严回严格
  array_equal（删除 0.1 有界分歧临时上界）。
- 曝光探针 tier 无关化（e8d7d61）：统计网格钉死帧坐标——三档预览/导出曝光决策
  一致，合成图三档 EV 散度 0.219→0.0013 EV、真实 RAW 档间散度降 4-10x、默认
  1024 档 EV 零变化。
- 标定加载统一治理（e3c8f7c）：新 `core/calibration_store.py`（负缓存/mtime 失效/
  RLock/reset 钩子），exposure 表/warmth 曲线/tone lrfit 三处迁移数值零变化；
  解码缓存条数→字节预算（PIXO_DECODE_CACHE_MB）。
- 管线框架质量（f48d453）：Stage domain 后验校验、ctx.mode 显式化（preview/export）、
  渲染样板合并 runner.py、Renderer 调整路径 8bit 往返量化消除。
- harness+dsh（5f62646）：金样本容差 rel 0.03→0.002（原实质放水 125 倍）+
  4 用例锁口径；RAW/SYNTH schema 拆分三态校验 + --check 漂移模式；dsh 死端点
  清理（11→4 真实路由工具）。
- 验收：金样本零漂移 + test_render_perf_fixes 16 用例；native 一致性严格等价
  恢复；曝光探针 test_exposure_tier_consistency 4 用例；标定加载新测试 17+5+3
  条；双 gate 逐位不变。

## 2026-08-27 — 16bit 精度改造批：u8 量化实测 → colorcal/LUT float 化 + RAW 默认路径金样本

- 决策数据（7a31cbf）：`scripts/measure_u8_precision.py` 全分辨率渲染 + 进程内
  去量化对照，报告 `docs/metrics/u8_midpoint_precision.md`——colorcal Lab u8
  往返 0.81 ΔE / 24.7% 像素越阈占绝对大头（go）、stylize LUT 0.22（顺手改）、
  refine sat_protection 0.012（不值得）、warm HSV 0.57-0.90（视预设定）。
- colorcal Lab 路径 float 化（3925b69，改造主项）：native 新内核
  PixoRenderColorCalApplyLabF32 + Python 三层回退（native F32 → 纯 float 镜像 →
  legacy u8 兜底）；native vs 参考 Lab 域 ≤1.9e-6；暗样本实测增益 1.075 ΔE /
  47.8% 像素越阈；附带修复肤色掩码误用中性校正后 a/b 的真 bug。
- LUT native float 四面体内核（4388f37）：PixoRenderLut3DApplyF32 与 numpy 参考
  逐位相等 0.0（镜像 NEP50 f64 MAC 语义，修出上边界步长错格）；预览 87-95ms
  （6x）、全幅 333ms（7x）；stylize 切 apply_f32，u8 表路径保留供金样本生成器；
  t111 顺带删除 256³ 表预热。
- RAW 默认路径金样本（0e8d2a5）：新 `tests/regression/goldens/gate_defaults/`
  24 条（wb_as_shot/exposure_auto/compose/clarity 四条默认路径 × 6 样本，全语料
  2663 张 EXIF 扫描选样，manifest 匿名 ref）；旧 gate/ 8 条基线重生成（原 8/8
  FAIL 形同虚设）；单 RAW CLI 忽略 --features/--reviewer 修复。
- 验收：gate_defaults 24 条 bit-exact PASS + 旧 gate 8/8 重生成 PASS；colorcal
  native vs Python ≤1.9e-6（Lab 域）；LUT 内核逐位 0.0、SYNTH gate 零漂移；
  金样本零漂移。

## 2026-08-27 — t110 落库收口 + 自研渲染管线路线图立项

- YOLOE 移除正式落库（769a225，BREAKING CHANGE：`PIXO_SEGMENTER=yoloe` 移除，
  迁移 `mock|multi`；内容同 2026-08-26 t110 条目）：删 segmenters/yoloe.py
  （466 行，仓库唯一 ultralytics import 点）及 7 测试；新增 import 隔离门禁
  （ultralytics 全 vision 包禁入 + torch/transformers/rfdetr 限适配器懒 import）。
- 测试同步（07adce1）：t110 遗漏的清单/分割器测试补齐（yoloe 断言移除 + 隔离
  门禁迁移）。
- 仓库治理（146acfa）：.gitignore 实验残留与可再生 metrics、dsh 插件纳入跟踪、
  tech_debt 台账 AGPL/torch 隔离口径同步。
- 路线图立项（f68b158）：`docs/PIXO_RENDER_OWN_PIPELINE.md`——自研渲染管线
  三阶段（Oklab 编辑层 / root-polynomial CCM 并联 / 可微标定 + 学习后端治理）；
  决策记录：不走端到端 learned ISP（与可解释闭环定位冲突）、DCP 永不删除。
- 验收：全仓 1031 passed（=1038−7 删测），vision/manifests/service 定向 48 绿。

## 2026-08-26 — t110 YOLOE 移除批（AGPL 依赖清零）

- 移除 YOLOE 分割器（唯一 AGPL-3.0 依赖，tech_debt #1 发布阻断项清偿）：
  删 `src/pixo/vision/segmenters/yoloe.py` 与其单测；`PIXO_SEGMENTER`
  收敛为 `mock|multi`；vision_health 去除 yoloe 条目，真实分割栈缺省
  报 multi_router 聚合；vision_models.json / model_licenses.json 删
  YOLOE-26L-seg 与随链 mobileclip2_b.ts 条目。
- 遗留命名清理：loop `_detection_version` 由 "yoloe26l_seg_v1" 改中性
  "segmenter_v1"（全仓无测试/金样本钉死该串）；隔离门禁测试保留并改为
  "ultralytics 全仓禁入 + torch/transformers 限适配器懒 import"。
- scripts 五个实验驱动（auto_full_scan/auto_full_refine/auto_manual_
  fallback/auto_real_edit/retouch_10）改用 MultiModelSegmenter。
- 开放词汇兜底：原 YOLOE 94 词开放词汇能力由 multi 路由
  （route 表内 prompt + 可选 GroundedSAM，`PIXO_GSAM_ENABLED=1`）承接。
- 验收：grep 全仓无活引用（历史文档注记除外）；基线无回归。

## 2026-08-25 — 视觉栈替换批 + LUT 库三批 + 高光/判据加固

- 多模型 Segmenter 替换 YOLOE：face→UniFace / person→RF-DETR-Seg 2XL /
  hair·skin·clothes→Sapiens / 背景→SegFormer-B1 / 开放词汇→GroundedSAM(可选)，
  {prompt:mask} 契约不变；授权矩阵 8 模型在册（AGPL YOLOE 隔离内、NC Sapiens
  标注、MIT+Apache 可分发）；懒加载+零掩码降级+隔离岛纪律。
- rfdetr 导入修复：rfdetr 1.9.4 顶层无 RFDETRSeg → RFDETRSeg2XLarge +
  pretrain_weights 构造；真机 person 35.6% 掩码+原生框验证。
- Sapiens id2label 守卫：权威 28 类表纠正 hair=3/skin=16/clothes=7，三来源
  解析+关键词比对，不一致/未核验拒用对应组——防静默污染磨皮/抠图。
- 原生框兑现：RF-DETR detect_boxes 归一 xyxy 直供 box_provider 三级链；
  Raw session state_extras 注入使 exposure 测光 subject_mode=box 真正生效。
- 视觉批门禁：最终树 910 passed；三适配器真实 RAW 冒烟全过（face/person/sky）；
  A/B 44 张逐位零回归——掩码替换对下游曝光/渲染无副作用。
- LUT 胶片卡库：films/ 24 张 + 内置风格卡 4 张（Kodak 系/Fuji 系/电影系/
  哈苏 NCS/黑白系/Agfa），schema+family 分组+可复跑生成脚本。
- 高光判据加固：标定表路径 spike 放宽（p99>=1.0 且 med<=-3.3 → ev+0.15），
  常规带补 clip<=cam*1.5（cam>=1% 应用）；厦门 669 压力 A/B 20 张 0707/2761
  修复生效，无新超限。
- 引擎微修：conflict_policy 加载期校验（仅 high_priority_wins）；clamp 绝对
  语义显式化（行为零变更）；合成域 ρ=0.03 非单调→池隔离+池内排名仅参考。
- 验收：910 passed / 4 skipped / 1 xfailed；授权核验+真机冒烟+可复跑脚本留档。


## 2026-08-25 — 日落批：公式守卫清零 · VibranceStage 占位处置 · 主题锁防回归门禁

- 公式守卫日落盘点（CI 哨兵固化）：全部规则 yaml 条件已无任何 formula 守卫
  （clarity 迁原生 all 为末例）；exposure log2 算术属动作公式在册保留；
  test_formula_guard_sunset.py 五用例固化为 CI 拦截。
- VibranceStage 占位处置：转发壳删除、占位类显式废弃（NotImplementedError+
  colorcal 指引），注册名保留稳住 STAGE_CLASSES；废弃契约断言入 test_pipeline。
- 新增 theme_locked_dark 防回归门禁：属性覆写后 review/settings 字节级一致、
  workspace 计算样式断言（blur 噪声规避）——暗房单主题锁的不变量守护。
- 工程占位文案清理四处 + MOCK 徽章角标化。

## 2026-08-25 — 暗房主题 UI 批：基座 · 三线对齐 · 视觉走查整改

- 主题基座：DESIGN_TOKENS 单一取色源（三层表面 canvas #101214/panel #17191c/
  overlay #1f2328、暖金 accent #e8a33d 十阶、hairline/radius/柔阴影/语义四色）
  + createTheme 暗房重定义 forceColorScheme=dark 锁死（产品裁定：暗房单主题
  为最终形态，Lightroom/C1 行业惯例）。
- 布局：TopBar 三段式品牌化（暖金竖条+字标/pill 导航/全局动作）、间距放宽、
  ReviewQueue token 容器；死文件 TopBar.tsx 清除。
- 面板：SectionLabel 小节微标签组件、SliderParam tabular-nums+拖动高亮+
  双击重置+暖金滑轨、InspectorTabs 暗房对齐、密度放宽。
- 库/胶片条/AI面板：Filmstrip 缩略图放大+accent 选中描边、PhotoLibrary 全套
  token 化样式（原裸默认渲染根因修复）、对话气泡暗色化、空态引导统一。
- 视觉走查整改（t79 6.5/10→整改）：三页白底面板主题化（near_white 实测
  0.003%/0.015%，阈值 2%）、焦点环归 tokens 琥珀、warning 语义档分离、
  light_forced 误导模拟件删除改 theme_locked 断言、工程占位文案清理、
  MOCK 徽章角标化。
- 验收：build 绿；862 后端回归保持零影响；截图 docs/ui/ 六张暗态规范集。

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
