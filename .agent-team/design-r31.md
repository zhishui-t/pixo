# 设计 · R31 RAW 打开色彩对齐 DNG 渲染（design.md）

队长 2026-09-22 拟；依据 task-brief.md（卡点①已批）。reviewer 审核对象。

## 0. F-ID 清单

| F-ID | 内容 | 负责 | 交付物 |
|---|---|---|---|
| F0 | GPLv3 许可证落地（LICENSE + pyproject `Proprietary` 清除） | junior-dev | LICENSE / pyproject diff |
| F1 | DNG 参照发生器（dng_validate 编译 + 渲染 CLI 壳 + 口径记录） | dev-1 | exe + `.artifacts/_r31_dng_render.py` + 自测 |
| F2 | 环境与批转（winget：DNG Converter + **RawTherapee**；NEF→DNG n=48 子样本） | junior-dev | `.artifacts/_r31_refs/`（DNG 批转产物）+ 安装记录 |
| F3 | 三臂测量 n=48（pixo default_look / RT-cli / DNG 渲染） | dev-2 | `.artifacts/_r31_three_arm.py` + 分布报告 |
| F4 | 矫正裁决执行（预授权判据 → 重拟合或判达标） | dev-2 | 矫正 diff（或达标结论）+ 复测数据 |
| F5 | 回归与复现（全量 pytest + 金样本零漂移 + 抽片复现） | tester-whitebox | .qa_ok + 测试证据 |

## 1. 采样与文件约定

- **样本**：与 R30 三轴探针**同一 pick 算法重建 n=48**（语料 K:/data/photo 4053 张等步长，剔 AppleDouble、跳已知 LibRaw 坏文件并留痕；R30 探针已丢失，清单内嵌本轮报告使测量可复算——可比性以此口径为准）。
- 文件：探针脚本 `.artifacts/_r31_*.py`（`_` 前缀自动 gitignore）；批转/渲染产物
  `.artifacts/_r31_refs/`（NEF 名同名 .dng + 各臂渲染输出，不入库）；正式报告
  `.artifacts/R31_dng_alignment.md`（入库）。
- 可能变更的仓内文件（仅数据）：`configs/styles/default_look.json`、
  `src/pixo/render/recipe_tone_curve.json`。**引擎代码零改动**（R23 纪律）。

## 2. 三臂口径（公平性核心，reviewer 重点审）

统一**每臂自己的默认打开语义**——测"用户打开照片各家的样子"，不做参数对齐作弊：

| 臂 | 发生器 | 口径 |
|---|---|---|
| pixo | `Renderer.render_preview_full(long_edge=1024, params=default_look)` | 现网默认观感（R30 接线），DCP=LR Adobe Standard Baseline |
| RT | `rawtherapee-cli -o <dir> -t -Y -d -c <file>`（`-d` 为**无参 flag**；`-c` 必须最后） | **-d = 启用 RT 的 Default Processing Profile**（fresh 安装即 Neutral；装后从 `--help` 与输出 pp3/元数据核录实际生效 profile 并写入报告）。注意：不传 `-d` 时 CLI 走 neutral 起新档（非"GUI 默认观感"），故必须显式 `-d`。`-t` 默认 16-bit TIFF。仅当输出元数据显示非 sRGB 时追加最小 pp3（仅含输出色彩空间键）并在报告记为口径偏离 |
| DNG | dng_validate 默认渲染（WriteTIFF 路径） | as-shot WB + 嵌入 profile（记录用的是哪个：转换器嵌入清单）+ sRGB 输出 + 基线曝光；**全分辨率渲染**（见 §5：禁 -min/预览级路径），实际输出尺寸记录 |

**度量（公式写死，全程 float，无二次量化）**：
```
每臂每片:
  img → (u16 时) u8f = u16 / 65535.0 * 255.0        # float, 不取整
  rgb01 = u8f / 255.0 → cv2.cvtColor(RGB2LAB, float32 输入)
       # OpenCV float Lab: L∈[0,100], a/b∈[-127,127]
  L8 = L * 2.55; a8 = a + 128; b8 = b + 128          # 转仓内 8 位标度, 保持 float
几何归一（唯一算法）: 各臂输出先 resize 长边→512 (INTER_AREA),
  再中心裁 min(h,w)×min(h,w) 方形; 朝向三臂同侧（均按 EXIF 转正）。
逐片: ΔL = median(L8_arm_crop) − median(L8_dng_crop)  (Δa/Δb 同式)
主判据量: median_over_photos( |Δ_photo| )             # 先逐片绝对值再跨片中位
分布表: 在逐片**有符号** Δ 上报 p10/p50/p90/IQR/min/max
ΔE76 换算: L100=L8/2.55, a=a8−128, b=b8−128 (对齐 fit_tone_curve.py:106-111)
```

## 3. 判据（预授权，写死）

- **wb_B 定义**：`wb_B := rawpy.camera_whitebalance[2] / camera_whitebalance[1]`
  （as-shot WB 的 B/G，取自**源 NEF**；DNG 转换不改变相机 WB，F3 以 1 例对照佐证
  并记录）。由 F3 探针产出，进 `_r31_three_arm.json` 逐片字段。
- **达标**：median(|ΔL|) ≤ 5 **且** median(|Δa|) ≤ 3 **且** median(|Δb|) ≤ 3
  （Lab 8 位标度）**且** |Spearman(逐片**有符号**ΔL, wb_B)| < 0.3 → 判达标出报告收工。
- **矫正触发**：上式任一不满足 → 执行 F4。
- **矫正后目标**：median(|ΔL|) ≤ 3 **且** median(|Δa|) ≤ 2 **且** median(|Δb|) ≤ 2。
- **失败路径**（三候选均不达矫正后目标）：**不写盘**、保留现状 default_look，
  数据与结论落报告、上报队长仲裁（援引 R18"失败路径合法"先例），不擅自迭代。
- **判定链**：dev-2 出数 → reviewer 复核判据执行 → tester 抽片复现。
- **写盘硬约束**：default_look.json 必须保留 `tone.profile_curve: true` 与
  `whitebalance.mode: "as_shot"` 两键（recipe 分支下 profile_curve 惰性无害），
  以过 `tests/unit/test_service_runtime_fixes.py:211-212` 硬断言。
- RT 臂**不入判据**（选型参考）：报告 Δ(RT−DNG) 与 Δ(RT−pixo)。

## 4. F4 矫正机制（数据驱动选优）

1. 拟合：`fit_tone_curve.py` 的方法（共享曲线 + gains）目标从相机 thumb 换成
   **DNG 渲染参照**（同 48 片 train/holdout 切分）→ 产出候选 recipe 曲线；
2. 候选对比（同 n=48 复测三选一）：
   a. 现 default_look（profile_curve 复合）；b. 现 recipe（相机目标旧曲线）；
   c. 新 recipe（DNG 目标曲线，eotf=recipe）；
3. 胜者（按 §3 判据指标）写入 `default_look.json`（受 §3 写盘硬约束与失败路径约束）；若新 recipe 胜出则同步更新
   `recipe_tone_curve.json`（旧相机曲线在 git 历史可回滚，报告注明交接）；
4. 全量回归 + 金样本（gate 主线引擎默认不变 → 预期零漂移；数据文件改动
   需过 default_look 相关单测）。

## 5. 风险预案

| 风险 | 预案 | 责任 |
|---|---|---|
| winget 静默装失败（DNG Converter/RT） | 重试 `--silent`；仍败→GUI 安装上报队长请用户点一次；RT 无包→官网 portable zip | junior-dev |
| dng_validate 编译 | **jxl 已实摘**（2026-09-22 队长执行：vcxproj jxl 引用/编译项 0 行、真 ProjectReference 0、XML 良构、字节级仅删不加；`dng_flags.h:481 qDNGSupportJXL(0)`）——**只编 vcxproj，不编 sln**（sln 仍挂 jxl 三工程，绕开并在报告记录）；仍败→自写最小渲染壳（SDK API ~150 行 main） | dev-1 |
| dng_validate 渲染慢 | **禁用 -min/预览级渲染路径**（会降级为预览管线不可作参照）；接受全分辨率渲染，仅在度量步降采样（§2 几何归一） | dev-1 |
| DNG Converter 半装残留 | 本机 `C:\Program Files\Adobe\Adobe DNG Converter\` 仅剩 c2pa.dll——junior 先卸净/修复安装再 winget 重装，安装后核验 exe 存在 | junior-dev |
| RT 默认输出色彩空间不明确 | `rawtherapee-cli` 指定输出 profile sRGB 的 pp3 最小文件（只含输出色彩空间键）；记录 | dev-2 |
| 三臂几何/朝向不一致 | 统一 512 中心裁 + EXIF 同侧处理；探针内置四角 sanity（同片三臂 dhash 对比），异常片跳过留痕 | dev-2 |

## 6. 接口约定（角色间文件交接）

- design.md（本文件）= 唯一真相源；各角色读文件不传对话历史。
- F1 交付：`dng_validate.exe` 路径 + `.artifacts/_r31_dng_render.py`（入参
  dng 路径 → 出 TIFF 路径，口径常量在文件头注释）。
- F2 交付：`.artifacts/_r31_refs/manifest.json`（NEF 原路径 ↔ DNG 路径 ↔
  48 片清单）。
- F3 依赖 F1 的渲染函数与 F2 的 manifest；产出 `.artifacts/_r31_three_arm.json`：
  **逐片** `{file, wb_B, dL, da, db, abs_dL, abs_da, abs_db}` + **分布块**（有符号 Δ
  的 p10/p50/p90/IQR/min/max）+ **判据块**（阈值字面常量 + 各比较结果 + verdict）。
- **脚本入库**（B6）：最终版 harness 以**无下划线前缀**入库
  （`.artifacts/r31_three_arm.py` / `r31_dng_render.py` 等，随报告同批提交，
  报告附 sha256）；报告内嵌**48 片完整清单**与口径常量；R30 探针已丢失 ⇒
  可比性口径改为"同 pick 算法重建"，清单内嵌使测量可复算。
- 所有脚本头注释写口径（版本/参数/日期），报告可复现。

## 7. 非目标重申

引擎 Stage 默认值、loop/decide、前端、Compositor 集成、分割进渲染引擎——全部不动。


## 8. 编号隔离声明（2026-09-22）

**开工前既有**的无关残留（2026-09-22 组队前已存在于盘上）：
`.artifacts/R31_enabled_wiring.md`、`.artifacts/_r31_consist.xml`、
`.artifacts/_r31_corpusfix_integ.log`——非本轮所出，不得动、不入本轮产物。
**本轮新建**（不在"无关残留"之列）：`.artifacts/_r31_dng_render.py`、
`_r31_three_arm.py`、`_r31_three_arm.json`、`_r31_refs/`（工作产物）与入库物
`.artifacts/R31_dng_alignment.md`、`r31_*.py`。下游以本声明为准。

## 9. 修订记录（reviewer 六项 BLOCKER 整改）

- v2 2026-09-22：B1 判据公式/几何/换算写死（§2/§3）；B2 RT 臂改 `-d` 显式
  Default profile 并删"无 pp3=全默认"错误表述；B3 wb_B 定义+F3 JSON 全字段；
  B4 "且"语义+失败路径+写盘硬约束+判定链；B5 jxl 实摘证据（见 §5）+ 只编
  vcxproj；B6 脚本入库+清单内嵌+可比性口径降级声明。另采纳建议：禁 -min、
  Converter 半装先修、编号隔离（§8）。

- v2.1 2026-09-22：残留-1（-d 无参）/-2（删矛盾行+全分辨率表述）/-3（§8 时间限定+本轮产物白名单）+建议三条（§1 可比性措辞、Spearman 有符号注记）落实。
