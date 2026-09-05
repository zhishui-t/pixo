# scripts

开发/运维脚本放置目录。一次性实验脚本放 `experiments/`（不保证可复现）。

## 渲染标定与质检
- `fit_target_offset.py` —— 场景自适应曝光标定表拟合（以 RAW 内嵌相机缩略图为真值，二分搜索匹配 EV），产物写入 `src/pixo/render/target_offset.json`
- `calibrate_to_camera.py` —— 迭代求解 EV + whitebalance.trim 使输出贴近相机预览
- `fit_rp_ccm.py` —— 根多项式 CCM 拟合（相机 JPEG 弱监督，产出 `configs/color/rp_ccm_<camera>.json`，设计 §4）
- `eval_rp_ccm_ab.py` —— DCP vs DCP+RP-CCM 双轨 ΔE2000 A/B 报告（markdown 落 `.artifacts/`，只报告不切默认；`--selftest` 校验 CIEDE2000 实现）
- `fit_skin_oklch.py` —— 皮肤椭圆 OKLab 重拟合（厦门/春节语料，pixo.meta 拍摄日分组；正样本=旧 cv2-Lab 椭圆∩person 分割（RF-DETR）；产出 `configs/color/skin_oklab.json` + `.artifacts/fit_skin_oklch.md` 旧/新召回/误报对照，设计 §3；`--per-group` 组均衡抽样、`--resume` 采样缓存重放）
- `convert_hsm_to_oklch.py` —— DCP HueSatMap/LookTable（90×16×16）离线采样转 OKLCh 控制点云（`configs/color/hsm_oklch_<slug>.json`，只产数据不接运行时，供 M-D1 标定；`--table auto` 真 HSM 优先、缺席回退 LookTable）

## 阶段二 可微标定（calib/）
- `calib/diff_core.py` —— torch 可微代理（θ 全 nn.Parameter）：decode→exposure(ev+rolloff)→whitebalance(camera_wb×warmth×WB 矩阵链+高光中性化)→[RP-CCM]→tone(sRGB EOTF LUT 线性插值)→colorcal 中性快速路径（CCT 分桶曲线）。可微策略=前向逐位复刻/反向平滑近似（clip 前向硬+反向 tanh 软梯度；colorcal tint 前向直调 cv2 u8 整数路径+反向 float Lab 雅可比；静态量 θ0 冻结）。torch 只进 scripts/（阶段二 t30，设计 §1）
- `calib/surrogate_fidelity.py` —— 保真门（θ 优化硬前置）：同输入同 θ 下 surrogate vs render_preview_full 中性参数（clarity/refine/skin 等 θ 无关空间观感 stage 显式关）ΔE2000 median ≤0.05 / p95 ≤0.3，语料 ≥10 张，真值 ΔE 复用 eval_rp_ccm_ab（含 --selftest 自检），报告落 `.artifacts/surrogate_fidelity.md`
- `calib/theta_io.py` —— θ 五组件上下料（warmth knots[5] / 曝光二维表 / 中性曲线 / RP-CCM[18] / skin 椭圆[5]）：从现有 configs 加载初值供 diff_core/优化器取参，按**原 schema** 写回 `configs/color/calib_out/`（不覆盖源文件，对照留档；非 θ 字段原样保留）；load→save→load 数值逐位恒等 + CLI 自检（阶段二 t31，设计 §2）
- `calib/optimize.py` —— θ 端到端联合优化 + G-5 收口：Huber-smoothed Lab proxy（ΔE2000 不可微只做评估——训练看 proxy、决策看真值）+ scene_constraints 罚项（warmth 单调/二阶平滑、曝光表 2D TV、中性曲线单调、skin 轴正性；均值化=λ 量纲归一）；Adam(1e-3) 预热→L-BFGS 精修，真值恶化自动回滚；每 checkpoint 全语料真 ΔE2000 median/p95；曝光表经 `_cal_ev` 同式权重进链（逐张 ev=w·ev_table）；`--resume` npz 采样缓存（fit_skin 模式）；G-5 拍摄日分组 RP-CCM 拟合 + 门槛线（median≥15%/无单照片回归>1JND/p95 不劣化/≥2 相机）写入 `.artifacts/calib_run.md`，新表落 `configs/color/calib_out/`（阶段二 t32，设计 §3+§4）
- `calib/eval_stage2.py` —— 标定前后真值对照评估（新表 calib_out/ vs 现行 configs 全语料双轨，θ0/θ* 经 theta_io 双载 + t32 npz 采样缓存重放）：端到端口径（θ 全链含表 ev，无 gain 对齐——曝光差是标定对象）+ 色度口径（eval_rp_ccm_ab 同式逐照片增益对齐 + orientation 6/8 逆旋转），真 ΔE2000 median/p95；分带统计（拍摄日 + wb_B 光照三带）与 G-5 门槛线逐项独立核对（B/C 轨系数读 rp_ccm_by_group.json，D 轨现行 rp 参考）；checkpoint 与 calib_run.md 数值自动交叉核对；报告落 `.artifacts/stage2_eval.md` + 机器可读 `.artifacts/stage2_eval.json`，seed+语料清单可复现，**只建议不切默认**（阶段二 t33，设计 §5）
- `ab_intent_compare.py` —— 意图级 HSV vs OKLCh 编辑域 A/B 对照（同一调整意图两域内核渲染同一语料 ≥20 张含厦门样张：扇区内/外 ΔE2000 + 高光色相落点误差 + 近白色度强加；种子+语料清单可复现，报告落 `.artifacts/ab_intent_report.md`，设计 §6；`--selftest` 复用 CIEDE2000 文献对自检）
- `ab_vs_camera_thumb.py` —— 全链渲染 vs 相机预览的感知 A/B（Lab ΔE / dL / 高光暗部裁切）
- `score_photos.py` —— 批量评分分级（good / mediocre / skip）
- `xiamen_screen.py` —— 批次抽样渲染 camera-matched 预览并评分
- `render_debug.py` / `vision_debug.py` / `batch_process.py` —— 单图调试与批量处理入口

## 阶段三 光照估计评估原型（illumination_est/）
- `illumination_est/wb_inverse.py` —— 估计光源色（相机原生线性域）→ pixo WB 参数域 (cct_k, tint) 逆链：wb = 1/e_cam 归一 G → `wb_to_temp_tint`（temp_tint_to_wb 现成逆函数）；与 as_shot 同域无跨域换算，`scene_xy_to_neutral_wb` 场景白点原语
- `illumination_est/gray_world.py` / `gray_edge.py`（Minkowski p=1,2）/ `white_patch.py` —— 三件经典法纯 numpy 实现，est_cct(rgb_linear, dcp_profile) → (cct_k, tint)，确定性无权重（白斑法排除贴顶饱和像素；灰边缘平坦图回退灰世界）
- `illumination_est/eval_illum.py` —— 语料评估（54 张，aligned_pair 口径）：A=as_shot WB / B=估计法 WB（warmth 曲线按估计 wb_B 预折入数值向量 mode，两轨唯一差异=neutral 源）/ 参照=相机 JPEG，逐照片 gain 对齐色度 ΔE2000（--selftest 先行）；wb_B 三带分带（日光<1.5/中间 1.5-2.0/低色温≥2.0）+ guard 域外降级轨；三证据转正初评（改善 <1 JND=2.3 ΔE00 → 明确"无转正价值"），报告落 `.artifacts/illumination_eval.md` + json（阶段三 t43，设计 §2；不接运行时/不建 learned/）

## 阶段三 HSM→OKLCh 运行时接线
- `hsm_oklch_eval.py` —— HSM→OKLCh 接线语料对照（54 张，aligned_pair 口径，--selftest 先行）：A=color_domain=hsv（DCP LookTable 的 HSV 三线性，现行为）/ B=color_domain=oklch（t17 点云 2765 点 → IDW...连续高斯核栅格化 72×24×24 + OKLCh 三线性形变）/ 参照=相机 JPEG；固定窗（基座 vs 参照定窗，A/B 同掩码）+ 逐照片 gain 对齐，读数 A↔B（接线保真度）/A↔R/B↔R + wb_B 三带分带；报告落 `.artifacts/hsm_oklch_eval.md` + json（core/huesat_oklch.py + HueSatStage color_domain 分派缺省 hsv 不变；点云按 DCP 名 token 子序列自动匹配，缺失回退 hsv 链）

## 自动修图闭环
- `loop_replay.py` —— 迭代轨迹回放调试工具（评审建议落地）：按 photo_id 查 `SQLiteStateTraceStore.trace_events` 全序列，逐事件解析渲染时间线 markdown（每步一行：iter#、事件类型、param delta 摘要、score/metrics 含 `{name}_area_ratio` 掩码面积、LLM 建议参数、qc_rollback）；`--export-dir` 可选——RAW 可达（--raw → photo_id 分组键即 file_path → meta_extracted.file_path）时逐参数快照重渲染预览（复用 `render_preview_full`，快照=各轮 decide.params）+ side-by-side 对照图序列；CLI `--photo-id X --db path [--export-dir Y]`（只读 db，不接运行时）
- `auto_full_scan.py` / `auto_full_refine.py` / `auto_manual_fallback.py`
- `assess_auto_results.py` / `build_final_summary.py`

## 项目图谱
- `build_project_graph.py` —— AST 解析 `src/pixo/` 生成机器可验证项目图谱：`docs/project_graph.json`（nodes/edges 均带源码行号证据，含 RAW→decode→IDT→编辑→ODT→encode 管线数据流，Stage 顺序取自 `render/pipeline/presets.py` DEFAULT_STAGES、域契约取自各 `@register_stage`）与 `docs/PROJECT_GRAPH.md`（mermaid 分层图/数据流/模块职责表/外部依赖隔离清单）。`--check` 幂等校验（CI 防漂移）；`--merge <t15片段.json>` 消费前端/配置资产图谱片段（id 冲突即报错，不静默覆盖）。只管 src/pixo，frontend/configs 归 t15。
