# dev1 R32-T4 报告 · 曲线体系增强（RT tone curve 对照吸收）

日期：2026-09-23 ｜ 角色：dev-1 ｜ 分支：render-core-integration（未 commit）
执行引擎：宿主原生（R32 设计 §4 兜底条款）。
顺带完成：T3 reviewer 遗留——`test_tool_convert_identity` 恒等容差 0.1 → **≤1e-4**（恒等场为仿射场，四面体插值应达量化级；收紧后 6/6 仍绿）。

**一句话：吸收 4 个插值模式（spline/catmull_rom/akima/monotone，user_curve 新增 `mode` 键，缺省 linear 逐位不变）+ 渐近线平段语义（CR y∈{0,1} 段精确保持）；最重发现 = 任务书点名的 "Akima" 并非 RT 模式（RT 枚举为 Linear/Spline/Parametric/NURBS/CatmullRom），且陡峭集实验证明：唯一零过冲的平滑模式是 Fritsch–Carlson monotone，spline（0.209）与 akima（0.180）均有显著过冲、CR 最轻（0.013）——"防过冲正解 = monotone" 结论在检视修正后依然成立。**

---

## 1. RT 侧侦察（diagonalcurvetypes.h + diagonalcurves.cc @ 6c4cb59，559 行）

| RT 模式 | 数学（逐段核实） |
| :--- | :--- |
| DCT_Linear | 控制多边形折线（fillDyByDx + 线性 getVal） |
| DCT_Spline (N>2) | **自然三次样条**（spline_cubic_set：自然边界 ypp0=yppN=0 的三对角解；求值用标准 cubic spline 式）——C2 平滑但**不保单调** |
| DCT_NURBS (N>2) | 二次贝塞尔子曲线链（控制点中点拼接，AddPolygons 按弧长布点）；**渐近线语义**：首点 x>0 时起点水平延伸、终点后平坦延伸至 x=3 |
| DCT_CatumullRom (N>2) | **向心 Catmull-Rom，alpha=0.375**（PR#4701 调优值），de Casteljau 三层求值；端点斜率受限反射（dx·0.01）；**y∈{0,1} 平段精确保持**（黑白渐近线段不算样条） |
| DCT_Parametric | 滑杆参数曲线（非控制点体系，不在本棒范围） |
| 兜底 | N≤2 / 恒等（所有点 x≈y）→ 回退 Linear / Empty；重复 x 端点防崩 nudge（Issue 2888/2923） |

**施加域**：RT 曲线按 DCP 语义施加于 ProPhoto/工作空间线性域（DCP PTC）与 L*a*b* 埼（Lab 工具）；**user curve 面板施加于显示器域**。我方 user_curve 施加于 gamma sRGB 域（tone stage）——**域/通道面（rgb/r/g/b/luminance）两侧均具备，不动**（任务书既定）。
**纠正记录**：任务书所列 "linear/smooth/spline/Akima" 与 RT 实况不符——RT 无 Akima、无 "smooth" 模式名（同 T1 census 纠正先例，报告如实记录）。

## 2. 我方对照与差集

| 项 | RT | pixo（T1.4 现状） | 差 |
| :--- | :--- | :--- | :--- |
| 插值 | Linear/Spline/NURBS/CatmullRom | 仅线性（np.interp） | **4 模式缺位** → 本棒吸收 |
| 渐近线点 | CR y∈{0,1} 平段精确、NURBS 首尾水平延伸 | 无（线性下平段天然直，但换平滑模式后需显式语义） | 随 CR 吸收 |
| 通道 | RGB 主 + 分通道 + Lab L/a/b | rgb/r/g/b/luminance（gamma 域） | 已够用，不动 |
| 施加域 | 工作空间（依 DCP）/Lab | gamma sRGB（tone stage） | 已够用，不动 |

## 3. 吸收集与数据（.artifacts/_r32_t4_curves.py → _r32_t4_curves.json）

**吸收集（4 模式 + 平段语义，全部纯数学实现，无 RT 代码移植；RT 特有常量 α=0.375 与端点反射式逐式标注出处）**：

| 模式 | 数学 | RT 对应 | 数据（S2 陡峭集：过冲 / 单调破坏采样数） |
| :--- | :--- | :--- | :--- |
| linear（缺省） | np.interp | DCT_Linear | 0 过冲 / 0 破坏（既有，逐位不变） |
| spline | 自然三次样条 | DCT_Spline | 过冲 **0.209** / 破坏 650 —— C2 最平滑（c1_jump=0）但陡峭段过冲 |
| catmull_rom | 向心 CR α=0.375 + 平段精确 + 端点反射 | DCT_CatumullRom | 过冲 **0.013** / 破坏 615 —— 过冲最轻的平滑模式 |
| akima | Akima 1970 | （RT 无——任务书点名纳入） | 过冲 **0.180** / 破坏 914 —— 价值在局部性（控制点编辑不远传），非防过冲；**实现已经 scipy Akima1DInterpolator 交叉验证 ≤6e-8**（检视回流：初版 w_left 权重错位，修正+补参考行） |
| monotone | Fritsch–Carlson 1980 | （RT 无——过冲自由补充项） | 过冲 **0** / 破坏 0 —— 陡峭集唯一安全平滑模式 |

其它实验数据：
- **独立验证**：spline vs scipy `CubicSpline(bc_type="natural")` 与 akima vs scipy `Akima1DInterpolator` 四组控制集最大差均 **≤6e-8**（两套平滑模式实现均与独立参考一致；akima 参考行系检视回流补充——初版 w_left 权重错位 `|δ_i−δ_{i-1}|`（应为 `|δ_{i+1}−δ_i|`）+ 左端延拓序颠倒，节点 0/1 切线偏差合计 0.1176/0.658，reviewer 复算点名后已修正并锁定参考行）；
- **通过性**：全部模式过控制点（≤8.7e-6）；
- **平段**：CR 的 y∈{0,1} 平段精确（flat_lo/hi_dev = 0.0，E-S3）；
- **平滑度**：spline/akima/monotone 的 C1 跳变 ≈ 浮点噪声（≤1e-5），linear 折线节点跳变 1e-3 量级（形状参考）；
- **检视修正后的过冲排序**（S2 陡峭集）：monotone 0 ≈ linear 0 < CR 0.013 < **akima 0.180 < spline 0.209**——"防过冲正解 = monotone" 表述经数据重生成后依然成立（spline 与 akima 排序互换，方向结论不变）。

## 4. 实现（diff 清单）

| 文件 | 改动 |
| :--- | :--- |
| `src/pixo/render/core/curves.py` | 新增 5 个私有函数（`_natural_cubic_coeffs`/`_cubic_hermite_coeffs`/`_fritsch_carlson_tangents`/`_akima_tangents`/`_catmull_rom_lut`+`_catmull_rom_reflect`）+ `_smooth_lut_by_mode`/`_eval_cubic_on_grid` 分发求值；`curve_lut_from_points` 加 `mode="linear"` 参数（缺省路径逐位不变；<3 控制点平滑模式自动回退 linear，同 RT N>2 规则；平滑模式要求 x 严格递增）；出处注（RT diagonalcurves.cc + 公开文献） |
| `src/pixo/render/modules/tone_map.py` | `_USER_CURVE_MODES` + `_user_curve_mode()` + `_curve_lut_for()`；`_apply_user_curve` dict 形式新增可选 `"mode"` 键（作用于组内全部曲线；非法值 raise）；列表形式与缺省行为不变（向后兼容红线）；docstring 更新 |
| `src/pixo/render/pipeline/graph.py` | `curve_dict_problem` 栅栏（两端唯一同源）放行 `"mode"` 键 + 取值校验（`_CURVE_DICT_MODES`） |
| `tests/unit/test_haldclut_convert.py` | T3 遗留：恒等容差 0.1 → 1e-4 |
| `tests/unit/test_user_curve.py` | 新增 7 用例：全模式过控制点 / linear 缺省逐位不变（列表=无 mode dict=linear dict 三方 array_equal）/ spline vs scipy（≤1e-6）/ 陡峭过冲矩阵 / CR 平段精确 / 非法 mode + 两点回退 / ToneStage 端到端 monotone |

## 5. 门禁证据

- 定向：test_user_curve（27）+ test_f04_param_fence + test_intents **112 passed**；test_haldclut_convert 6/6；
- **全量回归（最终代码态，含检视修正）：`1746 passed, 12 skipped, 1 xfailed, 0 failed`（194s）**；
- 实验数据：`.artifacts/_r32_t4_curves.json`（复算脚本 `_r32_t4_curves.py`）；
- 未 commit；未动 master。

## 6. 待队长/reviewer 关注

1. ~~`curve_dict_problem` 前端同步~~（T4 检视改写）：经查前端曲线 UI 为占位实现，user_curve 无前端表单校验命中——该影响面不成立，后端栅栏（graph.py 唯一同源）已放行 `mode` 键，无前端改动需求。
2. RT 的 NURBS（贝塞尔链）未吸收（数据面无 NURBS 控制点来源，user_curve 用户画的是普通点集；如后续要"RT Custom 曲线逐位复刻"再议）。
3. RT Lab 域曲线（L/a/b 独立）未纳入——我方通道面为 gamma RGB 域 rgb/r/g/b/luminance，按任务书"施加域/通道面已够用则不动"保持。
4. 检视回流记录（2026-09-23）：`_akima_tangents` 两处修正——w_left 权重 `|δ_i−δ_{i-1}|` → `|δ_{i+1}−δ_i|`（reviewer 点名），左端延拓序 `[δ_{-1},δ_{-2}]` → `[δ_{-2},δ_{-1}]`（对齐 scipy，自查发现）；实验数据与过冲矩阵断言已随重生成数字同步更新。
