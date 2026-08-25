# scripts

开发/运维脚本放置目录。一次性实验脚本放 `experiments/`（不保证可复现）。

## 渲染标定与质检
- `fit_target_offset.py` —— 场景自适应曝光标定表拟合（以 RAW 内嵌相机缩略图为真值，二分搜索匹配 EV），产物写入 `src/pixo/render/target_offset.json`
- `calibrate_to_camera.py` —— 迭代求解 EV + whitebalance.trim 使输出贴近相机预览
- `ab_vs_camera_thumb.py` —— 全链渲染 vs 相机预览的感知 A/B（Lab ΔE / dL / 高光暗部裁切）
- `score_photos.py` —— 批量评分分级（good / mediocre / skip）
- `xiamen_screen.py` —— 批次抽样渲染 camera-matched 预览并评分
- `render_debug.py` / `vision_debug.py` / `batch_process.py` —— 单图调试与批量处理入口

## 自动修图闭环
- `auto_full_scan.py` / `auto_full_refine.py` / `auto_manual_fallback.py`
- `assess_auto_results.py` / `build_final_summary.py`
