# rawlab — 自研智能修图引擎

完全不依赖 Adobe 运行时的 RAW→成片管线（只读取 Adobe 的 DCP 相机标定数据）。

## 渲染引擎(插件化,`rawlab/engine/`)

八阶段管线,Stage 按 order 编排、域契约校验、参数 schema 校验:

```
NEF → decode(linear_cam)
  → [10] exposure       曝光(场景自适应表 + 主体感知加权 + 抗暗角径向增益)
  → [20] whitebalance   白平衡(CM×CameraCalibration→XYZ;斜率/分桶暖度曲线)
  → [25] huesat         DCP HueSatMap/LookTable(线性 ProPhoto、tone 前)
  → [30] tone           影调(sRGB EOTF 基座;ProfileToneCurve=Adobe look 可选)
  → [45..49] 观感层     dehaze/clarity(默认 clarity 开)
  → [50] colorcal       色彩校准(按 CCT 插值;肤色保护)
  → [55] skin           人像磨皮(引导滤波,仅人像,wants 门控)
  → [60] stylize        风格化 LUT(四面体插值)
  → [70] refine         精修(锐化/色度降噪/高光去色;高饱和色保护)
  → 8bit sRGB JPEG
```

## Phase 1.5+2 能力

- **主体感知曝光**:YOLOE(复用 guanlan)主体/人脸框 → 曝光加权(face 优先,无检测回退全图)。
- **按 CCT 分段相机观感标定**:`engine/z5ii_neutral_trim.json` 新格式(default + by_cct 桶),渲染时按色温插值曲线。
- **场景分类**:`engine/scenes.py` 6 类(portrait/landscape/night/street/food/mono),确定性 CV 特征。
- **场景固定风格**:`presets/scenes.json` 注册表 + `engine/scene_apply.py`。
- **人像精修**:`engine/skin.py` 椭圆肤色掩码 + 引导滤波磨皮(边缘保持)。
- **LR 基准打磨**:`lr_baseline` preset 内置暖度分桶曲线 (`warmth_curve`)、
  抗暗角 `exposure.vignette`、橙黄高光 HSM 提饱和;refine 对高饱和色
  (烟花/霓虹)保护,避免锐化/降噪/去色抹掉色度。

## 基线口径 (profiles/manifest.json)

- `lr_baseline` = **LR Camera Standard v2** 目标 (2026-08 新默认;
  真值 `lr_corpus_camera_standard`, 导出时固定 `CameraProfile` 并恢复原设置)。
- `lr_adobe_standard_baseline` = LR Adobe Standard v2 兼容基线。
- `preview_baseline` = RAW 内嵌全尺寸 JPEG 预览目标 (相机忠实, 无 Adobe 依赖)。
- 拟合前必须固定真值 profile, 不允许混用 (no_profile_mixing)。

## 标定(每机一次)

```bash
python rawlab/tools/fit_target_offset.py --n 120 --write   # 场景自适应曝光表
python rawlab/tools/fit_camera_look.py --n_fit 100 --n_val 20  # 相机观感曲线(按 CCT 分段)
# RAW 预览基线 (暖尾全量采样, 中性样本保底)
python rawlab/tools/fit_camera_profile.py --target preview --warm-all --n 180 ...
# LR 真值导出: 必须显式固定 CameraProfile
python rawlab/tools/lr_export_corpus.py --mode export --camera-profile "Camera Standard v2" --restore ...
```

## 使用

```bash
# 引擎管线(基座 / 场景风格)
python rawlab_cli.py pipeline <RAW> --preset neutral
python rawlab_cli.py pipeline <RAW> --scene auto      # 检测+分类后自动选场景风格
python rawlab_cli.py pipeline <RAW> --scene portrait  # 显式场景(人像含磨皮)
python rawlab_cli.py pipeline <RAW> --scene landscape --probe

# 旧闭环命令(主体检测默认开启, --no-detect 关闭)
python rawlab_cli.py fix <RAW>
python rawlab_cli.py batch <RAW_DIR> --n 50
```

## Phase 3:RetouchAgent 修图意见反馈闭环

```bash
# 单张 + 意见(初轮)
python rawlab_cli.py retouch <RAW> --edit "更亮一点" --scene auto
python rawlab_cli.py retouch <RAW> --edits "更亮一点, 饱和一点, 锐一点"

# 反馈闭环(脚本/agent 内): RetouchAgent
#   agent.retouch(raw) -> result(图+报告+场景+参数)
#   agent.apply_feedback("暖一点") -> 新结果(分析复用, 每 3 轮重分析)
#   agent.save_session(json) / RetouchAgent.replay(json) -> 位精确回放
```

意见关键词:亮/暗/暖/冷/饱和/清淡/锐/柔/磨皮/降噪/对比/高光 + 场景词(人像/风光/夜景/街拍/美食/黑白)+ 风格词(velvia/classic_neg/astia);程度词(一点/再/很/非常)控制幅度。

## 验收(Phase 1 结项 + Phase 2 + Phase 3,详见 dsh-plan-task*/)

- Phase 1 基座 vs 相机预览(40 张):d_med mean≈0(std 12,旧链 20.8)、d_b |mean| 1.2、中性区 a +0.9、裁切 <1%。
- 测试:`python -m pytest rawlab/tests -q`(183+ 项,含真实 NEF e2e)。
- 性能:half_size 全链 ≈3.3s(含检测/分类 <8s)。
