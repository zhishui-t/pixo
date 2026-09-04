# scripts

开发/运维脚本放置目录。一次性实验脚本放 `experiments/`（不保证可复现）。

## 渲染标定与质检
- `fit_target_offset.py` —— 场景自适应曝光标定表拟合（以 RAW 内嵌相机缩略图为真值，二分搜索匹配 EV），产物写入 `src/pixo/render/target_offset.json`
- `calibrate_to_camera.py` —— 迭代求解 EV + whitebalance.trim 使输出贴近相机预览
- `fit_rp_ccm.py` —— 根多项式 CCM 拟合（相机 JPEG 弱监督，产出 `configs/color/rp_ccm_<camera>.json`，设计 §4）
- `eval_rp_ccm_ab.py` —— DCP vs DCP+RP-CCM 双轨 ΔE2000 A/B 报告（markdown 落 `.artifacts/`，只报告不切默认；`--selftest` 校验 CIEDE2000 实现）
- `fit_skin_oklch.py` —— 皮肤椭圆 OKLab 重拟合（厦门/春节语料，pixo.meta 拍摄日分组；正样本=旧 cv2-Lab 椭圆∩person 分割（RF-DETR）；产出 `configs/color/skin_oklab.json` + `.artifacts/fit_skin_oklch.md` 旧/新召回/误报对照，设计 §3；`--per-group` 组均衡抽样、`--resume` 采样缓存重放）
- `convert_hsm_to_oklch.py` —— DCP HueSatMap/LookTable（90×16×16）离线采样转 OKLCh 控制点云（`configs/color/hsm_oklch_<slug>.json`，只产数据不接运行时，供 M-D1 标定；`--table auto` 真 HSM 优先、缺席回退 LookTable）
- `ab_intent_compare.py` —— 意图级 HSV vs OKLCh 编辑域 A/B 对照（同一调整意图两域内核渲染同一语料 ≥20 张含厦门样张：扇区内/外 ΔE2000 + 高光色相落点误差 + 近白色度强加；种子+语料清单可复现，报告落 `.artifacts/ab_intent_report.md`，设计 §6；`--selftest` 复用 CIEDE2000 文献对自检）
- `ab_vs_camera_thumb.py` —— 全链渲染 vs 相机预览的感知 A/B（Lab ΔE / dL / 高光暗部裁切）
- `score_photos.py` —— 批量评分分级（good / mediocre / skip）
- `xiamen_screen.py` —— 批次抽样渲染 camera-matched 预览并评分
- `render_debug.py` / `vision_debug.py` / `batch_process.py` —— 单图调试与批量处理入口

## 自动修图闭环
- `auto_full_scan.py` / `auto_full_refine.py` / `auto_manual_fallback.py`
- `assess_auto_results.py` / `build_final_summary.py`

## 项目图谱
- `build_project_graph.py` —— AST 解析 `src/pixo/` 生成机器可验证项目图谱：`docs/project_graph.json`（nodes/edges 均带源码行号证据，含 RAW→decode→IDT→编辑→ODT→encode 管线数据流，Stage 顺序取自 `render/pipeline/presets.py` DEFAULT_STAGES、域契约取自各 `@register_stage`）与 `docs/PROJECT_GRAPH.md`（mermaid 分层图/数据流/模块职责表/外部依赖隔离清单）。`--check` 幂等校验（CI 防漂移）；`--merge <t15片段.json>` 消费前端/配置资产图谱片段（id 冲突即报错，不静默覆盖）。只管 src/pixo，frontend/configs 归 t15。
