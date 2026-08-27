# Pixo P2-8 许可复审与技术债清单

> 日期：2026-08-22
> 范围：`pixo/` 与项目 Python 运行时依赖/模型/迁移代码
> 结论：**当前仅适合内部研发；发布前存在 YOLOE AGPL、DNG clean-room、模型权重许可、第三方声明缺失等阻断项。**
>
> **更新（2026-08-26，t110）**：下述阻断项之首——YOLOE AGPL——已清偿：
> `src/pixo/vision/segmenters/yoloe.py` 适配器、runtime `PIXO_SEGMENTER=yoloe`
> 分支、vision_health/模型台账对应条目已全部移除，仓库不再含 ultralytics/
> AGPL 运行时依赖（其开放词汇角色由 multi 路由栈承接，NC 后端门控不变）。
> 其余阻断项（DNG clean-room、第三方声明等）仍有效。正文为 2026-08-22
> 原始审计快照，其中 YOLOE/ultralytics 相关条目仅作历史记录。

---

## 1. 执行方式

本复审为只读评审，未修改业务代码；仅新增本许可文档。

关键验证命令：

```powershell
# 1) 全仓库实际 torch/ultralytics import（应只命中 pixo/vision/segmenters/yoloe.py）
git grep -nE '^\s*(import torch|from torch|import ultralytics|from ultralytics)' -- '*.py'

# 2) 模型/权重文件是否存在
Get-ChildItem -Recurse -File . -Include *.pt,*.onnx,*.safetensors,*.pth,*.ckpt -ErrorAction SilentlyContinue

# 3) 当前 Python 依赖中的第三方 import
Get-ChildItem -Recurse -File pixo -Include *.py |
  ForEach-Object { Select-String -Path $_.FullName -Pattern '^\s*(import|from)\s+(torch|ultralytics|mediapipe|onnxruntime|transformers|cv2|numpy|rawpy|exifread|fastapi|uvicorn|yaml|scipy)' }
```

---

## 2. 许可清单表

| 组件/模型 | 版本（当前环境） | 许可 | 用途 | 风险 | 是否可随发布 |
|---|---|---|---|---|---|
| Pixo 自身 | 0.1.0 | Proprietary（仅 pyproject 声明，无 LICENSE 文件） | 项目主体 | 低 | 需补 LICENSE/NOTICE |
| ultralytics | 8.4.116 | AGPL-3.0 | YOLOE 分割 | **高** | **否，除非替换或购买企业授权** |
| YOLOE-26L-seg 权重 | 外部，未入仓 | AGPL-3.0（登记中） | YOLOE 推理 | **高** | **否** |
| mobileclip2_b.ts | 外部，未入仓 | **未核验** | YOLOE 文本编码器 | **高** | 需核验后决定 |
| torch | 2.13.0+cu126 | Apache-2.0/BSD 等混合 | 由 ultralytics 引入 | 中 | 本身可发布，但随 AGPL 链需整体策略 |
| transformers | 5.14.1 | Apache-2.0 | 当前代码未使用，仅文档提及 | 低 | 若引入需复核 |
| rawpy | 0.27.0 | MIT（wrapper） | RAW 解码 | 中 | 需核验捆绑 LibRaw 的 LGPL 义务 |
| numpy | 2.5.1 | BSD-3-Clause 等 | 数值核心 | 低 | 可 |
| opencv-python | 5.0.0.93 | Apache-2.0 | 图像处理 | 低 | 可 |
| fastapi | 0.141.1 | MIT | pixo-service API | 低 | 可 |
| uvicorn | 0.52.1 | BSD-3-Clause | ASGI server | 低 | 可 |
| ExifRead | 3.5.1 | BSD 风格 | EXIF 读取 | 低 | 可（保留版权声明） |
| scipy | 1.18.0 | BSD-3-Clause（附 OpenBLAS/GCC exception） | DCP WB 求解，有 numpy fallback | 中 | 可，但需声明依赖/可选依赖 |
| PyYAML | 6.0.3 | MIT | 可选 YAML 规则/知识图谱加载 | 中 | 可，但需声明 optional |
| pytest | 9.1.1 | MIT | 开发测试 | 低 | 可 |
| FairFace | 未实现/未入仓 | CC BY 4.0（架构文档提及） | 人脸年龄等（P2 可选） | 中 | 若迁移需署名/登记 |
| MediaPipe | 未安装/未实现 | Apache-2.0（架构文档提及） | 人脸关键点等（P2 可选） | 中 | 若迁移需登记 |
| 中文 CLIP / aesthetic-scorer | 未实现/未入仓 | 架构文档注明需核验 | 语义/审美（P2 可选） | 中 | 若迁移须先核验许可 |
| DNG SDK / Adobe 参考 | 无运行时依赖 | Adobe 专有 | 代码契约/clean-room 参考 | **高** | 发布前需 clean-room 复审 |

---

## 3. AGPL 隔离检查

实测结果：

- 全仓库实际 `import torch` / `from ultralytics` 语句只出现在：
  - `pixo/vision/segmenters/yoloe.py`
- 该文件内的动态 `__import__("ultralytics")` 也位于同一文件。
- `pixo/vision/health.py` 中出现的“import torch/ultralytics”只是 docstring 文本，不是真实 import。
- `pyproject.toml` / `requirements.txt` **未声明** torch/ultralytics，说明未把 AGPL 组件作为默认安装依赖。
- 当前仓库未发现 YOLOE/FairFace/CLIP 等权重文件入仓；模型权重应由外部路径/环境变量加载。

结论：**AGPL 单文件隔离当前有效**。

---

## 4. guanlan 迁移来源注释检查

| 文件 | 来源注释/归属 | 状态 |
|---|---|---|
| `pixo/meta/burst.py` | 明确写有 `Ported/adapted from Guanlan...` | ✅ 有归属，但原项目许可未登记 |
| `pixo/meta/lighting.py` | 明确写有 `Ported/adapted from Guanlan...` | ✅ 有归属，但原项目许可未登记 |
| `pixo/vision/measure.py` | 模块/函数中引用 guanlan 算法名 | ⚠️ 有文字引用，无正式来源/许可块 |
| `pixo/vision/segmenters/yoloe.py` | 引用 guanlan `yoloe_det.py` 方案 | ⚠️ 有参考说明，无正式许可/归属块 |
| `pixo/render/core/lut.py` | 引用 guanlan luts 复用 | ⚠️ 有路径/说明，无许可登记 |

建议：新增 `THIRD_PARTY_NOTICES.md`，统一登记 guanlan 来源、原项目许可、迁移文件列表；在迁移文件中补充统一 header。

---

## 5. DNG SDK / clean-room 状态

代码与文档中存在大量 Adobe DNG SDK 参考：

- `pixo/render/core/calibration.py`：注释引用 `dng_tags.h`、`dng_camera_profile.cpp`
- `pixo/render/core/color.py`：引用 `dng_color_spec.cpp`、`dng_camera_profile.cpp`
- `pixo/render/modules/white_balance.py`：引用 DNG 1.4 与 Adobe dng_color_spec 语义
- `pixo/render/core/warp.py`：声明 clean-room 独立实现，以 DNG SDK 黑盒产物为 oracle

架构文档已明确：当前存在从 DNG SDK 源码移植/参考实现细节，**产品化前必须完成 clean-room 复审或重写**，并延续 M1-M5 等价测试。

---

## 6. 阻断项与发布前动作

### 阻断项（发布前必须解决）

1. **YOLOE-26L-seg AGPL-3.0**
   - 替换为 Apache/MIT 模型（如 Grounding-DINO + SAM 系）
   - 或购买 Ultralytics 企业授权
   - 或确保发布分支完全移除 ultralytics/torch 运行时依赖
2. **mobileclip2_b.ts 权重许可未核验**
   - 需确认是否可随 YOLOE 权重一起分发
3. **DNG SDK 相关实现 clean-room 复审**
   - 不能以 Adobe 源码直接移植进入发布产品
   - 需仅依据 DNG Specification / 公开色彩学文献
4. **无 LICENSE / THIRD_PARTY_NOTICES**
   - 需要为项目本体和所有第三方组件建立可分发声明
5. **`model_licenses.json` 路径仍为旧路径**
   - `isolation_file` 当前写的是 `render/vision/segmenters/yoloe.py`
   - 实际应为 `pixo/vision/segmenters/yoloe.py`，或同时保留 shim 路径说明

### 发布前建议动作

- 将 `scipy`、`PyYAML` 作为 optional dependencies 或移除未声明依赖。
- 为 `pixo-vision` optional extra 明确是否包含 YOLOE/ultralytics；如不包含，应在文档中说明“真实分割需要额外安装”。
- 为 FairFace/MediaPipe/CLIP/aesthetic-scorer 等未实现模型建立许可预审清单，避免未来迁移时遗漏。
- 单独复审 frontend（`frontend/package.json`、npm 依赖）的第三方许可，本次 Python 扫描未覆盖。
- 确认 `rawpy` 绑定/捆绑的 LibRaw 许可与再分发义务。

---

## 7. 建议的 P2-8 Gate

在发布分支上增加硬门禁，建议至少包含：

```powershell
# 1) AGPL 隔离：只允许 pixo/vision/segmenters/yoloe.py 出现真实 torch/ultralytics import
git grep -nE '^\s*(import torch|from torch|import ultralytics|from ultralytics)' -- '*.py' |
  Select-String -NotMatch 'pixo/vision/segmenters/yoloe.py'
# 若输出非空 -> FAIL

# 2) 禁止默认依赖携带 AGPL 组件
Select-String -Path pyproject.toml,requirements.txt -Pattern '^(ultralytics|torch)'
# 若命中 -> FAIL

# 3) model_licenses.json 必须登记所有入库模型，且 isolation_file 指向实际文件
# 4) 发布产物必须包含 THIRD_PARTY_NOTICES.md / LICENSE
# 5) 不允许 *.pt/*.onnx/*.safetensors/*.pth 等模型权重直接进入发布分支
```

---

## 8. 结论

- **内部研发：当前许可隔离与技术债可接受。**
- **对外发布：阻断。** 必须先解决 YOLOE AGPL、mobileclip2_b.ts 许可、DNG clean-room、第三方声明与模型登记路径更新。
- 建议将本文件作为 P2-8 发布门禁的输入，后续在创建发布分支时实施上述 Gate。
