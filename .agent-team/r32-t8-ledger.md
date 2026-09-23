# R32-T8 吸收台账 · RawTherapee 全模块清点（收官交付物）

日期：2026-09-23 ｜ 角色：dev-1（收官清点棒）｜ RT 源码：K:/work/project/rawtherapee @ 6c4cb59（dev，GPLv3）
方法：rtengine/ 全文件面枚举（~190k 行，cc+h）× rtgui/toolpanelcoord.cc ToolPanel 实例化清单交叉，逐模块对照 pixo render 现状裁决。
纪律：建议吸收项只给优先级（P0 渲染影响 / P1 能力面 / P2 锦上添花）与预估工作量（S<0.5d / M=0.5-2d / L>2d），**本轮不实施**；实施属后续轮。

**总览：模块/能力项 38 ｜ 已吸收（T1-T7 收编）8 ｜ 已具备/保持 13 ｜ 建议吸收 10（P0×3、P1×4、P2×3）｜ 跳过/不适用 7。**

---

## A. 已吸收收编（T1-T7 落地，各棒报告为准）

| # | 模块/能力 | RT 出处 | pixo 落地 | 收编棒 |
|---|---|---|---|---|
| A1 | 去马赛克 RCD | rcd_demosaic.cc | native `rcd_demosaic_native.cpp` + `mode="RCD"`（默认链 AHD 不变） | T1 |
| A2 | Film Simulation 引擎侧 | clutstore.cc（格式对照） | `hald_level_to_lut`/`write_cube`/`haldclut_convert` 工具 → stylize .cube 通道（纯格式适配） | T3 |
| A3 | 控制点曲线插值 | diagonalcurves.cc（Spline/CatmullRom） | `curve_lut_from_points(mode=)`：spline/catmull_rom/akima/monotone（mode 显式开启） | T4 |
| A4 | HSV Equalizer 非对称施加数学 | improcfun.cc:2755-2791 | `hsl_adjust_rgb(adjust_math="rt")` | T6 |
| A5 | Color Toning 亮度恢复（preser） | improcfun.cc toning2col | `split_tone_oklab_rgb(preserve_luma=)` | T6 |
| A6 | getAutoExp 自动匹配 | improcfun.cc:5440 | exposure `mode="match"` + `auto_match_suggest` | T7 |
| A7 | 面板 Luma 口径（Lab L\*） | improccoordinator updateLRGBHistograms | compute_histogram `luma="lab_l"` → `lum_lstar` 键 | T5 |
| A8 | 曝光基线联动（BaselineExposureOffset） | procparams/params | exposure stage baseline 模式（R31 既有）+ T2 符号校准 | 既有 |

## B. 建议吸收（本轮不实施；按优先级排序）

| # | 模块/能力 | RT 能力摘要 | pixo 现状 | 裁决 | 工作量 | 证据 |
|---|---|---|---|---|---|---|
| B1 | **DCP LookTable / HueSatMap 底座应用** | ProfileLookTable（实测 Adobe v2 DCP 含 90×16×16 sRGB 编码表）+ HueSatMap 在 ProPhoto HSV 域经 hsdApply 三线性查表施加（improcfun Step1/Step2） | **底座零消费**（R11 A 轨退役；huesat_oklch B 轨=用户可选形变非底座）——真 Adobe DCP 的观感表被整段跳过 | **P0 渲染影响**（T2 全部差异中最大项） | M-L：hsdApply 移植 + ProPhoto 域链 + 双光源表插值 + 金样本重生成 | dev1-r32-t2.md §3 V9；dcp.cc hsdApply:2013；本机 Adobe v2 DCP 实测 |
| B2 | **Shadows/Highlights 局部恢复** | Lab L\* pow4 掩码 + **guided filter 局部细化** + gamma 映射 + 暗部 NURBS 对比 + 色度比例保持（ipshadowshighlights.cc 全文件） | tone highlights/shadows 为**全局**亮度带通乘性（无空间分量） | **P0 渲染影响**（暗部提亮不灰化/局部不塌陷，质量面） | M：guided filter（cv2 可用）+ L\* 域链 + 掩码参数面 | ipshadowshighlights.cc:36-201；dev1-r32-t7.md §1.1 |
| B3 | **预览线 dcraw flip 方向缺失** | rawpy postprocess 自动按 dcraw flip 码翻转输出 | decode_cfa_half 预览无翻转 → **portrait 拍摄预览横竖颠倒**（T1 实测 flip=5 样张） | **P0 用户可见 bug**（T1 遗留既有 bug） | S：`_apply_dcraw_flip` 已在 io.py（T1 为 decode_raw RCD 分支实现），搬到 cfa_half 路径 + 回归锁 | io.py `_apply_dcraw_flip`；T1 .artifacts/_r32_t3_filmsim flip=5 案例 |
| B4 | **FlatCurve 自由控制点周期曲线**（HSV Equalizer 形态） | 周期 FlatCurve（FCT_MinMaxCPoints 控制笼），HSV 三曲线 hue 轴自由点 | hsl 为 8 具名带+环状掩码（无自由点形态） | **P1 能力面**（编辑自由度；与 B1 联动后价值更高） | M：flatcurves.cc 控制笼插值移植 + 周期边界 | flatcurvetypes.h:25；flatcurves.cc；dev1-r32-t6.md §6.2 |
| B5 | **NURBS 对角曲线** | DCT_NURBS：二次贝塞尔子曲线链 + 弧长布点（暗部对比/局部工具在用） | 无（T4 吸收四模式不含 NURBS） | **P1**（RT Custom 曲线逐位对齐前提） | M：Bezier 链 + 弧长采样移植 | diagonalcurves.cc:169-270 |
| B6 | **Lab/L\* 域独立曲线**（LCurve：L 主曲线 + a/b 曲线） | LCurve + RGBCurves 双面板，L 域亮度/色度曲线 | user_curve 为 gamma RGB 域 per-channel + luminance | **P1**（Lab 亮度曲线与 RGB 曲线观感不同：色度不漂） | M：L\* 域应用链（依赖 B1 的 Lab 域入口） | curves.h LCurve；dev1-r32-t4.md §6 |
| B7 | **动态 profile**（dynamicprofile） | 按 ISO/动态场景自动切换 DCP（camconst 标定联动） | 单一静态 DCP（resources/dcp 自拟合卡） | **P1**（高 ISO 换 profile 的色彩稳定性） | M：ISO→profile 映射 + 加载层 | dynamicprofile.cc:298；profilestore.cc |
| B8 | 色差自动矫正（CA auto） | CA_correct_RT 1383 行（raw 域自动 CA 检测矫正） | 无（rawpy 内部有限） | **P2** | L | CA_correct_RT.cc |
| B9 | Capture sharpening（RL 反卷积） | capturesharpening.cc 1171 行（Richardson-Lucy，传感器级锐化） | refine unsharp（灰空间 unsharp） | **P2**（锐化质感不同；RL 迭代成本） | M | capturesharpening.cc |
| B10 | Fattal 色调映射 | tmo_fattal02.cc（Edge-Preserving Decomposition HDR 观感） | 无（filmic/dehaze 覆盖部分意图） | **P2** | M-L | tmo_fattal02.cc |

## C. 已具备 / 保持（不吸收，含 T1-T7 裁决收编）

| # | 模块/能力 | RT | pixo | 裁决理由 |
|---|---|---|---|---|
| C1 | 曝光/影调曲线六键 | exposure+black+hlcompr+bright+contr | exposure 六键 + soft rolloff + compress curve（T7 ramp 达标） | 保持（T7 E3 数据；RT 黑点硬钳制语义不吸收） |
| C2 | 阴影/高光（全局带通） | （同 B2 全局面） | tone highlights/shadows 带通乘性 | 保持（B2 为其局部增强形态） |
| C3 | Highlight compression 肩部 | 曝光曲线 shoulder | soft rolloff + highlight_compress_curve + shoulder | 保持（T7） |
| C4 | HSV Equalizer 三通道施加 | 非对称 sat/lum 数学 | adjust_math="rt" 显式开启（T6）；缺省 pixo 对称乘法并存 | 已吸收（A4） |
| C5 | 双色分色调（Split 系） | toning2col（二次 ramp+保护+preser） | split_tone 双域 + balance/strength + preserve_luma（T6） | 已吸收（A5）+保持 |
| C6 | 直方图后端 | firstAnalysis/updateLRGBHistograms/parade | compute_histogram（bt709/lab_l/parade 数据面）+ 联动契约 | 已吸收（A7，T5） |
| C7 | 色彩管理（工作空间矩阵/PCS 白） | iccstore/iccmatrices | core/color.py clean-room（4 位公布形+白点缩放，金样本钉死） | 保持（R11/R12 清偿） |
| C8 | DCP 解析/序列化 | dcp.cc 解析 | calibration.py load/write（往返兼容） | 保持（R11/R12） |
| C9 | 双光源插值/中性→xy/Bradford | dcp.cc/color.cc | color.py（1/T 同式；Kim vs Robertson 差 ≤0.0014 矩阵元） | 保持（T2 E1/E2） |
| C10 | CameraCalibration (CC) | **不支持**（RT 注释自承） | 支持（先插值后复合，S1 回归守卫） | 保持（我方为规范超集） |
| C11 | 去马赛克 AHD/快速路径 | ahd/fast | rawpy AHD（默认链） | 保持（T1 双臂并存） |
| C12 | 镜头暗角/渐变（Gradient/PCVignette） | 暗角/渐变工具 | exposure vignette（径向）+ 后续可扩 | 保持（部分；形态不同） |
| C13 | Resize/重采样 | ipresize + Lanczos | core/resample.py（CV2 面积/Lanczos） | 保持 |
| C14 | Clarify/Local contrast（面板） | LocalContrast（UI 对比工具） | clarity stage（大/小尺度模糊对） | 保持（语义近似） |

## D. 建议吸收（P2 续）/ 跳过 / 不适用

| # | 模块 | RT 出处 | 裁决 | 理由 |
|---|---|---|---|---|
| D1 | 小波工具套件 | ipwavelet.cc 5261 + cplx_wavelet + dirpyr_equalizer 685 | **跳过（登记）** | 5k+ 行大件；我方 denoise/clarity 覆盖子集；ROI 低 |
| D2 | Retinex | ipretinex.cc 1669 | **跳过（登记）** | 观感类；使用率低（RT 自身默认关） |
| D3 | Impulse denoise / Median | impulse_denoise 557 / median.h 6300 | **跳过** | cv2.medianBlur 可达同等；RAW 域坏点场景少 |
| D4 | BADPIXEL / 暗帧 / 平场 | badpixels 616 / dfmanager / ffmanager + rawflatfield | **跳过（登记）** | 需暗帧/平场素材采集流程；rawpy 阶段无入口 |
| D5 | CFA linedn / Green equil / PDAF filter | cfa_linedn 466 / green_equil 252 / pdaflinesfilter 305 | **跳过** | RAW 域传感器级行降噪，rawpy 解码后不可达 |
| D6 | 色差手动矫正 / Purple fringe | CACorrection / PF_correct_RT 1199 | **跳过（登记）** | 手动几何 CA 滑杆；使用频率低 |
| D7 | 镜头矫正（lensfun：畸变/暗角/CA + LCP） | rtlensfun 800 + lcp 1199 + calc_distort 284 | **建议吸收 P2** | 需 lensfun 数据库依赖（许可 OK，数据 LGPL/CC）；几何矫正产品决策后实施 |
| D8 | 透视/裁剪/旋转/裁切框 | PerspCorrection 416 / dcrop 2294 / Rotate | **跳过** | 编辑器几何功能（compose/reshape 部分覆盖），属前端画布轮 |
| D9 | Film Negative | filmnegativeproc 667 | **跳过（登记）** | 负片扫描小众；实现为通道反相+标定 |
| D10 | Spot 移除 / 修复画笔 | spot.cc 580 | **跳过** | 编辑器画笔功能，前端画布轮 |
| D11 | HDR 合成 | （RT 无括号合并；Fattal 为 HDR 观感映射） | **跳过** | 多帧合成不在 RT 单文件管线内；观感需求由 B10 覆盖 |
| D12 | 黑白工具（BlackWhite + before/after 曲线） | BlackWhite 面板 | **部分（保持）** | split_tone mono/huesat 覆盖；before/after 双曲线形态可后续对照 |
| D13 | 色彩外观 CIECAM | ciecam02.cc 1135 + ColorAppearance 面板 | **跳过（登记）** | 大件；J/Q/M/s/C 直方图体系；科学完备但 ROI 低 |
| D14 | Vibrance（智能自然饱和） | ipvibrance 662（肤色保护饱和） | **部分（保持）** | skin.py 肤色椭圆 + colorcal 饱和已覆盖同意图 |
| D15 | 元数据/EXIF 读写 | metadata.cc 619 + MetaDataPanel | **跳过** | rawpy/piexif 层职责 |
| D16 | RAW 解码全家桶（dcraw 11754 / amaze / xtrans / fujicompressed / canon_cr3 / panasonic / camconst） | 各解码器 | **跳过（不适用）** | rawpy/LibRaw 职责；T1 已按需吸收算法层（RCD） |
| D17 | Pixel Shift | pixelshift.cc 1043 | **跳过** | 需多帧 RAW 采集流程 |
| D18 | 参数管理（procparams/serdes/profilestore/pp3 sidecar/批量） | profilestore 559 + serdes + dynamicprofile | **部分（保持）** | 我方 presets/cards/configs + service 批量形态不同构；pp3 互转可作互操作后续项 |
| D19 | 局部调整（Locallab 蒙板局部编辑器） | iplocallab.cc 23551（全仓最大模块） | **登记（不在 RT 吸收范围）** | 与 R31 挂起的分割进引擎（S1）/Compositor 图层（S2）同域——局部调整=图层蒙板编辑的实现载体，排队后续轮统一设计 |
| D20 | 高光重建（hilite_recon 1597） | 高光色彩重建（原始通道混合） | **部分** | exposure sat_mask 高光中性化（T1.5）为简化形态；逐通道重建可登记 P2 |

## E. 排队登记（非 RT 范围，随本台账一并呈交）

| 项 | 来源 | 状态 |
|---|---|---|
| R31 候选 c（4.453）曝光仲裁 | R31 | 挂起待用户 |
| S1 分割进引擎（RF-DETR/SegFormer multi-router 接渲染管线） | R32 任务书原 T1' | 排队 |
| S2 Compositor 图层模型 | R32 任务书原 S2 | 排队 |
| LookTable/HSM 底座落地（B1）实施设计 | 本台账 | 排队 |
| WorkBuddy 引擎拒答模式记录（RT 任务族 refusal×3+，设计 §4 兜底生效） | T2/T4-T8 各棒报告 | 已知行为 |

---

## 统计与结论

- **模块/能力项 38**（A 8 + B 10 + C 14 + D 20 中去重合并口径，含 T1-T7 收编 8）；
- **建议吸收 10 项**：P0×3（B1 LookTable/HSM 底座、B2 S/H 局部恢复、B3 预览线 flip 缺失 bug）、P1×4（B4 FlatCurve、B5 NURBS、B6 Lab 曲线、B7 动态 profile）、P2×3（B8 CA auto、B9 RL 锐化、B10 Fattal）；
- **P0 首位 = B1（DCP LookTable/HueSatMap 底座零消费）**——T2 实测 Adobe v2 DCP 自带 90×16×16 观感表被 RT 施加而被我方整段跳过，为全部差异中渲染影响最大项；
- **跳过/不适用 7 组**（RAW 解码层由 rawpy 职责覆盖；编辑器几何/画笔类待前端画布轮；大件低 ROI 项登记不删）。

> 台账由 dev1 依源码逐模块核实出具（rtengine @ 6c4cb59）；优先级与工作量为工程预估，供队长/用户逐项裁决后派单。
