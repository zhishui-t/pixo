# dev1 R32-T2 对照报告 · RT DCP 处理链对照吸收

日期：2026-09-23 ｜ 角色：dev-1 ｜ 分支：render-core-integration（未 commit）
执行引擎：宿主原生（R32 设计 §4 兜底条款，RT 任务族引擎拒答实证，未重试）。

**一句话：差异项 10 / 建议吸收 0（V1 吸收尝试因触碰金样本零漂移红线已回滚，降级待议，锚点已留码内注释）/ 最重发现 = 我方底座链完全不消费 DCP LookTable/HueSatMap（真 Adobe v2 DCP 含 90×16×16 LookTable，RT 在底座施加而我们跳过——渲染差异最大项，已列 T8 台账候选）。**

数据：`.artifacts/_r32_t2_dcp_compare.json`（实验脚本 `_r32_t2_dcp_compare.py`，口径写死可复算）。
实验锚点：真 Adobe DCP（Nikon Z 5 2 Camera Standard v2：双光源 StdA/D65、CM1/2+FM1/2、PTC 125 点、BaselineExposureOffset −0.15EV、LookTable 90×16×16 enc=sRGB、无 HSM）。

---

## 1. RT 侧全链梳理（dcp.cc @ 6c4cb59，2275 行）

RT 把 DCP 应用拆两段：

**Step1 `apply()`（WB 相关）**：
1. `makeXyzCam`：RT WB 乘数 → `neutral`（经 sRGB 矩阵/cam_wb_matrix/pre_mul 折算，注释自承 "messy"）→ `neutralToXy` 不动点（≤30 轮，阈 1e-7）→ `xyCoordToTemperature`（DNG SDK Robertson 30 段 uv 表，**mired 倒数插值**）→ **1/T 权重** mix → CM 线性混合；
   - **有 FM 必走 FM**（"Always prefer ForwardMatrix"）：`cam_xyz = inv(FM_mix · inv(diag(CM_mix·white_xyz)))`；
   - 无 FM：`cam_xyz = CM_mix · MapWhiteMatrix(D50→scene)`（线性化 Bradford）；
   - 尾部 dcraw 遗产：**过 sRGB 矩阵 + 逐行归一化 + 取逆再复合**（RT 自注 "probably dcraw legacy... does no harm"——实测并非无害，见 E3 灰点漂移）；
2. `makeHueSatMap`：HSM1/2 按 **RT 自家 WB 温度**（非 DNG wbtemp）1/T 插值（含 T1>T2 反序处理），逐项线性混合；
3. 施加：直通矩阵（无 LUT 快路径）或 raw→ProPhoto → `rgb2hsvdcp`（hue 0..6 域+负区检查）→ `hsdApply`（HSM）→ 回 RGB → ProPhoto→work。

**Step2 `setStep2ApplyState`+`step2ApplyTile`（WB 无关，ProPhoto 域 tile）**：
`×2^BaselineExposureOffset` → ProPhoto（LUT/TC 时先钳 ≥0）→ **LookTable**（`rgb2hsvtc`+`hsdApply`，s/v CLIP01，`setUnlessOOG` 出域不动）→ **ProfileToneCurve**（`AdobeToneCurve.Apply`：max/min 过 65535 级 LUT，med 按原比例线性重推**保色相**；等值 case 直查 LUT）→ 回 work。

**解析语义要点**：PTC 非线性（x≠y）才启用；**Adobe Systems 版权 + 无 PTC tag → 注入 ACR 默认曲线**（`adobe_camera_raw_default_curve`，1025 点均匀表，dcp.cc:867）；HSM/Look 各有 `ProfileHueSatMapEncoding`/`ProfileLookTableEncoding` sRGB gamma 编码开关（v 通道 encode→查表→decode）；`will_interpolate` 由 CM1≠CM2 / FM1≠FM2 / 双 HSM 推导；**RT 明确不支持 CameraCalibration 与 reductionMatrix**（注释自承）。

## 2. 我方现状（R11/R12 clean-room）

- `calibration.py`：DCP 解析/序列化（tag 面完整）+ 自拟合相机观感曲线通道；`color.py`：应用数学（CM/FM/CC 插值、Bradford、中性→xy 不动点、cam→XYZ/ProPhoto、temp/tint 正反解）；`huesat.py`：表数据访问+解码+OKLCh 转译供给（**运行时底座应用链 R11 A 轨已退役**）；`curves.py`+`modules/tone_map.py`：PTC 以 125 点线性插值 LUT 复合进 tone stage（R24 复合语义 base∘curve）。
- **底座链 DCP 消费点**：cam_to_xyz（exposure 探针/主链）、cam_to_prophoto（HSM 域入口，但无 HSM 消费者）、PTC LUT（tone stage）、bloe（exposure stage ev+=offset）。**LookTable/HueSatMap 底座零消费**（huesat Stage B 轨=用户可选 OKLCh 形变，非底座）。

## 3. 差异清单与数据（逐项）

| # | 环节 | RT | pixo | 数据（E=实验编号） | 裁决 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| V1 | xy→CCT 反查 | Robertson 表（DNG SDK），max err **26.1K** | 双口径并存：内部 `_neutral_to_xy`/`_find_matrices`=Kim2002 轨迹（**9.1K**）；公开 `neutral_to_xy`/`cct_from_wb`=McCamy（极端点 **~2869K**） | E1：20 点黑体+5 命名照明体 | **待议**（吸收已试：切 Kim 致 4 测试失败含 gate 金样本——正反解对 `temp_tint_to_wb↔wb_inverse` 须同步切换+金样本重生成，属队长批准项；回滚完成，锚点注释留在 color.py `neutral_to_xy`/`cct_from_wb`/`cam_to_xyz_matrix` 三处） |
| V2 | 双光源 1/T 插值公式 | `(1/T−1/T2)/(1/T1−1/T2)`，端点钳位，mix=1→光源1 | 同式同端点约定 | E2：白点 xy 距 ≤1.0e-4，CM 矩阵元差 ≤**0.0014** | **保持**（等价性实证；CCT 算法差为二阶效应） |
| V3 | 中性→xy 不动点 | 30 轮/1e-7/振荡取均值 | 同（两套实现：`_neutral_to_xy` 含 CC，公开版不含 CC） | E2 | **保持**（结构同式；CC 有无差异见 V10） |
| V4 | CM 路径合成（无 FM） | CM·MapWhiteMatrix(**D50→scene**) + dcraw 遗产 sRGB 往返行归一化（以 sRGB 白为中性基准） | Bradford(**scene→D50**)·inv(CM)·inv(CC)·diag(1/wb)（规范语义，灰点恒 PCS D50） | E3：矩阵元差 ≤0.54；patch ΔE76 mean 24-34；**RT 灰点随 WB 漂移**（3200K→xy(0.364,0.446)，6500K→(0.275,0.359)），pixo 灰点恒 (0.3457,0.3585) | **保持**（我方=规范语义且白点稳定；RT 遗产怪癖复刻需全管线 pre_mul/cam_wb 管道，收益存疑→T8 议） |
| V5 | FM 路径合成 | **有 FM 必走 FM**；`inv(FM·inv(diag(CM·white)))`+行归一化 | 基座恒走 CM（colorimetric）；FM 仅缺 CM 回退 + HSM 域入口（FM 白点缩放+CC+camera_white diag→ProPhoto） | E4：矩阵元差 ≤1.42；patch ΔE 82-239（含 V4 同类管道系统差）。勘误（reviewer 限向修订）：初稿"FM1@(1,1,1)=D50 逐位验证"系误把 RT dcp.cc:1892 无 FM 分支 MapWhiteMatrix 的源白点常量 {0.3457,0.3585,0.2958} 当作验证结论——E4 脚本无此断言，四种输入折叠复算均 ≠D50（gray_rt 即证）；该常量如实表述为无 FM 分支源白点 | **保持** + 待议（"FM 优先"是 Adobe look 对齐路线，基座改 FM=渲染哲学变更，产品级决策→T8） |
| V6 | PTC 曲线插值 | DCT_Spline（DiagonalCurve） | 125 点线性插值 LUT | E5：线性 vs 保单调三次（PCHIP 代理）max 差 **2.4e-4** | **保持**（低于感知阈；125 点密采样下形状差可忽略） |
| V7 | PTC 施加语义 | AdobeToneCurve：max/min 过 LUT、med 保色相线性重推（65535 域，ProPhoto，LookTable 后） | per-channel LUT，tone stage，base∘curve 复合（R24） | 定性（未量化——需同曲线双施加 A/B） | **待议**（DNG 规范措辞待查证；Adobe 语义防彩色像素色偏 vs 我方 per-channel；建议 T7 曝光校准轮顺带 A/B） |
| V8 | Adobe 无 PTC 注入默认曲线 | 有（1025 点表，dcp.cc:867） | 无（parse=None→不施加） | 本机 5 个 Adobe DCP 全带 PTC（254/250 vals）——**无本机触发面** | **待议/登记**（实施锚点+表已定位；无真实触发面，吸收收益为零——登记到 T8 台账） |
| V9 | **LookTable/HSM 底座应用** | Step1 HSM + Step2 LookTable（ProPhoto HSV 0..6 域，srgb_gamma 编码，hsdApply 三线性） | **底座零消费**（R11 A 轨退役；真 Adobe v2 有 LookTable 90×16×16 enc=1 被跳过） | E7 定性（幅度量化需完整 hsdApply 移植，留作实施前提） | **待议（本棒最重发现）**：底座吸收=大改动+R11 有意退役史，产品决策→**T8 台账重点项**；huesat_oklch B 轨可作为落地形态参考 |
| V10 | CameraCalibration (CC) | **不支持**（注释自承） | 支持（inv(CM)·inv(CC) 先插值后复合，S1 回归在守） | 代码对照 | **保持（我方更规范）** |
| V11 | BaselineExposureOffset 施加域/序 | ProPhoto 域、LookTable/PTC **之前** | exposure stage ev+=offset（矩阵后线性域，PTC LUT 前） | E6：先乘后过曲线 vs 先过曲线后乘，gamma 域最大差 **0.039**（PTC 非线性⇒顺序不可交换） | **待议**（数值差小但语义位置不同；统一需移动施加点=架构改动；符号约定两侧一致已核） |

## 4. 吸收裁决汇总

- **本轮落地吸收：0 项**。唯一够格的 V1（CCT 口径统一）实施后触碰金样本零漂移红线（4 测试失败：gate_golden×2 + wb 正反解对×2），已按红线优先**回滚**，三处锚点注释留在 `core/color.py`（`neutral_to_xy`/`cct_from_wb`/`cam_to_xyz_matrix`），待队长批准「正反解对联动切换 + 金样本重生成」后 diff 极小即可落地。
- **保持 6 项**（V2/V3/V4/V5/V6/V10）：两侧同式或我方=规范语义（V4/V5 灰点稳定性我方更优；V10 我方支持 CC 为超集）。
- **待议 5 项**（V1/V7/V8/V9/V11）：全部登记，其中 **V9（LookTable/HSM 底座缺位）为最重渲染差异**，建议入 T8 吸收台账首位；V7/V11 建议挂 T7 曝光校准轮顺带 A/B。

## 5. 门禁证据

- 回滚后受影响面：test_color_math/test_illumination_est/test_diff_core/test_gate_golden **46 passed**（含 gate 金样本 7/7 零漂移）；
- 全量回归（回滚后最终代码态）：见文末回填；
- 新增/修改文件：`.artifacts/_r32_t2_dcp_compare.py`+`.json`（新增）、`core/color.py`（三处注释锚点，无行为变更）、`tests/unit/test_color_math.py`（净零，追加测试已随回滚移除）；
- 未 commit；未动 master。

（回归结果回填处）**全量回归（回滚后最终代码态）：`1732 passed, 12 skipped, 1 xfailed, 0 failed`（218s）**；gate 金样本 `test_gate_golden.py` 7/7 零漂移。
