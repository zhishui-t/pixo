# calib_prev —— 阶段二新表入库前的旧表备份（2026-09-04，t36）

本目录是阶段二标定新表（configs/color/calib_out/，t32 产出）入库前被替换的四个正式表快照。

回退方法：把本目录四个文件拷回原位置即可——

```bash
cp configs/color/calib_prev/warmth_curve.json       configs/calibration/warmth_curve.json
cp configs/color/calib_prev/target_offset.json      src/pixo/render/target_offset.json
cp configs/color/calib_prev/z5ii_neutral_trim.json  resources/camera_profiles/z5ii_neutral_trim.json
cp configs/color/calib_prev/rp_ccm_nikon_z5_2.json  configs/color/rp_ccm_nikon_z5_2.json
```

回退后必须重生成金样本（金样本是按表快照的）：
`python tests/regression/goldens/generate_gate_goldens.py`
并更新 manifest.reviewer 签注 + 全量 pytest。

skin_oklab.json 新旧相同，未入库不在本备份范围。详见 .artifacts/stage2_adopt_report.md。

注：skin_oklab.json 为补齐 θ 五源加载所需而复制（新旧表完全相同，非被替换件）。
