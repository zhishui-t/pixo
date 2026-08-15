# rawlab — 自研智能修图引擎

完全不依赖 Adobe 运行时的 RAW→成片管线（只读取 Adobe 的 DCP 相机标定数据）。

## 核心模块

| 模块 | 职责 | 验收 |
|---|---|---|
| `dcp.py` | DCP 解析（TIFF 容器/ColorMatrix/ForwardMatrix/校准照明体） | ✅ |
| `render.py` | 渲染管线：rawpy 解码 → ×WB → ForwardMatrix → Bradford → sRGB → gamma | ✅ 肤色 a=+13 b=+15 |
| `exposure.py` | 曝光闭环：主体亮度/高光溢出/ΔEV/3轮迭代/高光保护 | ✅ 19PASS+1REVIEW |
| `lut.py` | 3D LUT：.cube 解析 + 三线性插值 + 256³ 查表 + 强度控制 | ✅ 0.21s |
| `vision_report.py` | 视觉语义报告：主体/色彩场/影调场/构图/质量 → JSON | ✅ 1.87s |
| `vision_bridge.py` | YOLOE-26L GPU 检测（guanlan 资产复用） | ✅ 0.5s |
| `rag.py` | RAG 知识库：100 条 + 词袋检索 + 风格推荐 | ✅ 0.2ms |
| `rawlab_cli.py` | CLI 工具层：render/analyze/fix/report/batch | ✅ 50张 158.6s |

## 核心链路（2026-08-14 定稿）

```
NEF → rawpy(linear 相机RGB) → ×camera_whitebalance(AsShot)
    → ForwardMatrix1 → XYZ(D50)      ← 关键: FM 不是 CM!
    → Bradford D50→D65 → sRGB 线性
    → 曝光(×2^ev) → LUT(sRGB域查表) → gamma → JPEG
```

## 验收记录（详见 guanlan/doc/自研修图系统计划书.md）

- 阶段0 DCP 色彩：5 张 Z5 II 肤色橙黄/灰阶中性 ✅
- 阶段1 渲染闭环：half_size 1.32s <2s ✅
- 阶段2 曝光闭环：20张 19PASS+1REVIEW，人像 10/10 ✅
- 阶段3 LUT：0.21s <0.5s，identity 误差 0 ✅
- 阶段4 视觉报告：50张 平均1.87s <2s ✅
- 阶段5 智能体调度：50张批量 158.6s <15分钟 ✅
- 阶段6 RAG：100条 + 检索0.2ms + 推荐方向正确 ✅

## 使用

```bash
python rawlab_cli.py fix <RAW>          # 曝光修正
python rawlab_cli.py report <RAW>       # 视觉报告
python rawlab_cli.py batch <RAW_DIR> --n 50   # 批量
python rawlab_cli.py render <RAW> --style velvia --out out.jpg
```
