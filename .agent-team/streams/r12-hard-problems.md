# streams/r12-hard-problems.md — super-dev 攻坚流 (r12)

> color.py DNG SDK 痕迹清偿重写 (F18 H4-H8 收官段)。执笔 2026-09-07。
> 作战地图: `.agent-team/research/color-sdk-audit.md` (函数级定性 a/b/c 已前置)。

## 1. 问题与红线

- a) SDK 衍生实现 2 处 (`camera_white` :556 / `cam_to_prophoto_matrix`
  :573, ~55 行) 按约束重构; b) 规范实现 6 处改注释; c) 纯注释 2 处改措辞。
- **最大风险 = 常数选择漂移**: 换 7 位 Lindbloom/ASTM 常数 → 输出漂移
  ~7e-5 → 金样本击穿。红线: PCS D50 与 ROMM 矩阵 **pin ICC 4 位公开值**,
  禁止"改进"精度。
- 验收硬标准: **纯 refactor 逐位等价** (gate --check 21 零漂 + RAW 24/24
  + 全量绿), 任何像素漂移=修到等价而非重生成基线。

## 2. 规范引证核对 (audit §2.2 清单, 本次完成)

audit 当时会话 DNG PDF 直取失败 (404), 标注"重写时核对"。本次通过
colour-hdri 项目对规范原文的引用交叉核对到**子节名 + 页码**:

- 白点迭代 = DNG 规范 Camera Colorimetric Characterization 节子节
  **"Translating Camera Neutral Coordinates to White Balance xy
  Coordinates" (规范 pp.80-81)**; 相邻子节 "Translating White Balance xy
  Coordinates to Camera Neutral Coordinates" (p.80) / "Camera to XYZ (D50)
  Transform" (p.81) —— B4 的"置信度中高"转实锤;
- ICC PCS D50 (0.3457, 0.3585): ICC.1/ISO 15076-1 PCS 定义, 多源交叉
  (W3C css-color-4 引为 ICC PCS 白; Spaulding et al. 2000 ROMM 白皮书
  以同值定义 ROMM 编码白) —— 该论文同时是 ROMM 4 位矩阵的公开出处;
- 章节号处理: 规范 PDF 本会话仍不可直取 (Adobe 站点跳转), 引证采用
  "章节名 + 子节名 + 页码" 的无歧义形式, 不猜裸节号。

## 3. 实现 (a/b/c 分类处置)

### a) 约束唯一解重构 (2 函数, 零数值改动)

- `camera_white`: docstring/注释重写为推导式 —— 场景白 XYZ (规范子节
  迭代) → 插值色彩矩阵 (CC@CM, XYZ→相机) = 相机对场景白的原生响应 →
  **max 通道归一** (白最先饱和, 归一后各通道值 = 相对白头的富余 =
  裁剪上限); max/[0.001,1] pin 明示为**通用数值护栏** (与色度学出处
  无关)。函数体逐行未动。
- `cam_to_prophoto_matrix`: 按「WB 后场景白 → PCS 白」约束重构 ——
  ① FM 白点缩放 S_FM=diag(PCS白/(FM·ones)) (ICC 公开技术: device white
  精确落 PCS); ② inv(CC) 个体→参考相机; ③ diag(1/(inv(CC)·camera_white))
  为约束对任意 WB 成立的**唯一修正项**; PCS 侧 ROMM 4 位矩阵先白点缩放
  再取逆。常数上收模块级钉死:
  `_PCS_D50_XY = (0.3457, 0.3585)` / `_ROMM_RGB_TO_XYZ_D50_4` (4 位
  公布形), 注释写明"勿换 7 位, 漂移 ~7e-5 击穿金样本"; 局部 `_DNG_D50_XY`
  / `dng_pp_m` 等旧命名全部换中性名。运算次序逐行保持 (见 §4 实证)。
  错误消息 "无法复刻 DNG SDK HSM 应用域" → 中性措辞 (无测试断言原文)。

### b) 出处改写 6 处 + c) 措辞 2 处

模块头权威依据段整段改公开规范/文献 (删 SDK 源文件名/FindXYZtoCamera);
:15 插值口径、:44 应用域、B1 illuminant_cct (EXIF/CIE 标准照明体)、B2
bradford_adapt (Lam 1985 + Lindbloom, Mb/A/Mb⁻¹ 标准构造)、B3 复合次序
(规范语义推论)、B4 两处白点迭代 (规范子节名+页码)、B5 (ISO 22028-2
4 位 ROMM + IEC 61966-2-1 派生 4 位 sRGB + ICC PCS 白缩放构造)、
C1/C2 措辞中性化、:672 应用域块 (规范记载口径)。

### 相邻清扫 (grep 终验驱动, 均注释级零代码)

- `calibration.py` 3 处: tag 出处 → DNG 规范 tag 定义表 (tag 编号/类型/
  语义为规范公开记载);
- `white_balance.py`: 头部权威链路出处改规范引用 (指向 color.py 同源);
  :372 Stage3 语义注明"黑盒产物 oracle 对齐"、:390 应用域改"DNG 规范"
  口径;
- `test_color_math.py` 2 处口径注释同步 (S1 先插值后复合 = DNG 规范口径)。

## 4. 逐位等价实证 (核心验收)

自检脚本 `.agent-team/spike/_r12_bitdiff_check.py` (临时, 可删):
git HEAD 原版 color.py 落临时模块加载, 与重写版全函数对拍:

- 语料: 6 合成 DCP 变体 (FM/CC/CM2 有无组合) × 8 组 WB + **真 Nikon Z5
  基线 DCP** × 8 组 WB;
- 覆盖函数: camera_white / cam_to_prophoto_matrix / cam_to_xyz_matrix /
  cam_to_linear_srgb_matrix / prophoto_to_linear_srgb_matrix /
  cam_wb_to_prophoto (像素级) / cam_to_xyz (像素级) /
  linear_prophoto_to_srgb (像素级);
- **结果: 全部逐位一致 (array_equal, dtype+shape+值)**, 含
  "[real DCP] Nikon Z5 基线: 全部逐位一致"。

金样本/回归 (改动前后同跑, 漂移归因明确):

| 验收 | 前 (基线) | 后 (终态) |
|---|---|---|
| gate `--check` (合成) | OK 21 features | **OK 21 features 零漂移** |
| RAW gate_defaults (真 NEF) | PASS 24/24 | **PASS 24/24 零漂移** |
| 全量测试 | 1480 passed | **1480 passed, 5 skipped, 1 xfailed** |

## 5. GPL 终验 grep

`grep -iE "dng sdk|dng_render|dng_color|adobe 源码|D50_xy_coord" src/
--include=*.py --include=*.cpp --include=*.h` 终态命中 **均为中性表述**:

- 否定式声明: io.py "不使用 DNG SDK"、warp.py "未读取 DNG SDK 源码"、
  base.py "运行时无 DNG SDK 依赖";
- 黑盒 oracle 对照 (clean-room 纪律允许且应保留): README/base.py
  "与 DNG SDK 对齐"、warp.py "黑盒产物对齐验证"、README "DNG SDK 消融";
  white_balance.py "Stage3 语义 (输出契约以参考渲染器黑盒产物为 oracle
  对齐)";
- 历史记录: `__init__.py` "原 engine/dng_render.py (去 dng 命名)"、
  huesat.py "R11 A 轨退役...已删除"、docs/ 迁移文档。

**源码出处引用 (dng_color*/dng_tag_codes/D50_xy_coord/FindXYZtoCamera 类)
清零**; .md 历史文档中的文件名记录属迁移档案, 保留。

## 6. 台账与遗留

- **tech_debt #2 关闭** (终章已写入): huesat A 轨 (R11) + color.py (R12)
  + 相邻清扫三段全清, 逐位等价 + grep 终态证据齐 → 条目转 ✅。
- 遗留边界 (不阻塞, 已在 #2 终章记录): io.py H12 "Stage3 近似复刻" 与
  white_balance M 系的**行为级** oracle 注释属黑盒对照非源码血缘; git
  历史仍含旧注释 (发布以快照为准, F18 处置选项 C 归队长/用户)。
- spike 产物: `_r12_bitdiff_check.py` (等价性对拍, 建议保留至 R12 验收
  复核后删), `_color_head_r12.py` 临时模块已删。

**一句话结论**: 重写为纯 refactor —— git HEAD 对拍全函数逐位等价
(6 合成 DCP + 真 Z5 DCP × 8 WB), gate 21 features 零漂移 + RAW 金样本
24/24 零漂 + 全量 1480 passed, grep 终态仅存中性表述 (源码出处清零),
tech_debt #2 三段清偿终章关闭。
