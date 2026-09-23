# R32 设计审核报告（design-review-r32）· T1 设计门禁

> 日期：2026-09-23 ｜ 审核人：reviewer（delivery 质量门禁）
> 被审对象：`.agent-team/design.md`（R32-T1 RCD 去马赛克移植设计；design-r31.md 为上一战役归档，未混审）
> 参照：`task-brief.md` v2（T1 行 + 约束）、`dev1-r32-recon.md`、`junior-report-r32.md`
> 执行引擎标注：**宿主原生**（WorkBuddy 引擎提交即拒答，job-7f576fa973d8，stop_reason=refusal，与侦察期 refusal×3 同型；按 design.md §4 风险表既定处置「勿重试引擎、如实标注执行引擎」落兜底，未重试）。无 workbuddy 会话线。
> 覆盖声明：本报告只出意见，未改 design.md 及任何 src/tests 文件；修订由队长（作者）落实留痕。

---

## 0. 代码事实核查（实读，本报告全部结论的证据基座）

| # | 事实 | 证据（文件:行号） |
|---|---|---|
| F-a | `PixoRenderFallbackRequested = 1` **已存在**，约定注释「0 成功，1 请求 Python 回退，负数为错误」 | `src/pixo/render/native/src/abi.h:14-21` |
| F-b | `decode_raw` **已有** `demosaic: str = "AHD"` 参数（大写口径）；映射表大小写敏感仅收 "AHD"/"LINEAR"，**未知值静默回落 AHD** | `src/pixo/render/core/io.py:135-143` |
| F-c | `decode_cfa_half` 的 pattern 推导：`color_desc` 逐 2x2 位置判 R/G/B → `patternR/G0/G1/B`（0..3 线性位置）+ `black_by_pos` 按线性位置取 `black_level_per_channel` + `white_level`；非 1R+2G+1B 抛 ValueError | `src/pixo/render/core/io.py:189-207` |
| F-d | 参数栅栏 strict 路径对**未知 stage** 抛 `ParamValidationError`（服务层转 400）；白名单唯一派生源 `PARAM_SCHEMAS`；`STAGE_CLASSES` 18 个 stage **无 "decode"** | `src/pixo/render/web/session.py:344-346, 359-362, 208-217`；`src/pixo/render/params.py:29-53` |
| F-e | `canonical_params()` 只迭代 `pipe.stages` 复制已注册 stage 桶 → 非 stage 的 "decode" 桶**到不了**导出线；`ExportManager._run` 传给 `_render_full_quality` 的 params 正是 `session.canonical_params()` | `src/pixo/render/web/session.py:712-728`；`src/pixo/render/web/export.py:174-180` |
| F-f | `_render_full_quality(raw_path, prof, params, output_bps, state_extras)` 现调 `decode_raw(str(raw_path), half_size=False)` 不传 demosaic；region_masks 走**独立通道**转发（非 params 键）；预览线 `decode_mode` 同为**函数参数**（非 params 键） | `export.py:30-51, 169-180`；`session.py:546-548` |
| F-g | `decode_raw` 三处生产调用方均解包 `(img, raw)` 元组 | `export.py:51`；`pipeline/graph.py:354`；`tools/bench_pipeline.py:121` |
| F-h | `hasattr` 可选符号门确系既有惯例（数十处；含 `PixoRenderDecodeCfaHalf` 先例），版本门 (1,6,0) 加载校验在位 | `src/pixo/render/_native/__init__.py:299-481, 409, 481-494` |

---

## 1. 意见清单（0 BLOCKER / 4 主要 / 9 建议）

### 主要（须修订设计后方可动码；M1/M2 为接口规格硬伤）

- **M1【主要】§1.2 `decode.demosaic` params 透传通道按字面实施走不通（双重断裂）。**
  ① HTTP 面：`{"decode": {"demosaic": "rcd"}}` 经 strict 栅栏即被拒——"decode" 不是注册 stage（F-d，session.py:344-346 → 400）。② 绕过栅栏也没用：`canonical_params()` 只复制已注册 stage 桶（F-e，session.py:712-728），export.py:174-180 传的正是 canonical_params()，`_render_full_quality` 永远看不到该键。
  **整改**：改走显式参数/独立通道——`_render_full_quality` 增加 `demosaic` 形参（缺省 "AHD"）+ `ExportManager.submit` 增加可选透传（region_masks 同款独立通道，F-f 先例齐备）；删除「params 的 decode.demosaic 键」表述。若坚持 params 键则须新增 decode stage schema（更重，不建议）。T1 验收（A/B + 质量测试）不依赖 HTTP 通道，故定主要非 BLOCKER，但「作为导出选项」的完整闭环必须先修此通道。

- **M2【主要】§1.1 pattern 注释事实错误：「rawpy raw_pattern 语义: 0=R,1=G,2=B,3=G2」不成立。**
  rawpy `raw_pattern` 的值是 `color_desc` 的**颜色索引**，两个 G **共用索引 1**（如 RGGB = [[0,1],[1,2]]），不存在 "3=G2" 取值。正确口径 = `decode_cfa_half` 既有推导（F-c，io.py:189-207），与侦察 §4 草案（patternR/G0/G1/B 线性位置 + black[4] + whiteLevel）一致。
  **整改**：§1.1 的 `const int pattern[4]` 参数改为侦察草案口径，或明写「复用 decode_cfa_half 推导，值 = 2x2 线性位置索引 + black_by_pos」。

- **M3【主要】§1.1 ABI 与侦察 §4 ABI 草案互相矛盾且未定夺。**
  设计版：输入 float mosaic（Python 侧已归一化）；侦察版：输入 uint16 cfa + black/white params（native 内逐 tile `LIM01((v−black)/(white−black))`）。数值逐元素等价，但设计版要求 Python 物化全分辨率 float32 中间缓冲（24MP ≈ 96MB 额外峰值），侦察明言「不引入全分辨率 float 中间缓冲（遵循 RT 逐 tile 装载）」；且设计版未写明 LIM01 钳位责任归属（Python 钳还是 native 留 LIM01）。
  **整改**：队长定夺其一并写明理由与钳位责任（审核倾向侦察版：贴近 RT 逐 tile 结构、省 96MB 峰值、black/white 语义留在 ABI 层可单测）。

- **M4【主要】§1.2 与既有签名冲突：`decode_raw(..., demosaic: str = "ahd")`。**
  该参数**已存在**且缺省大写 `"AHD"`（F-b，io.py:135-136），映射表大小写敏感、未知值静默回落 AHD（io.py:141-143）。设计当作新增参数且小写口径，照抄会与既有调用面分叉。
  **整改**：改写为「扩展既有 `demosaic` 参数」，写明确切字面量（建议 "RCD" 对齐既有大写）与未知值行为（维持静默回落，或显式 record_degradation——二选一写死）。

### 建议

- **S1** §1.1 状态码「FallbackRequested(新增码或复用现有)」犹疑应删：复用现有（F-a，abi.h:17），新增码反而违背「1=请求回退」既定约定。
- **S2** §1.2 返回契约未声明：三处调用方均解包 `(img, raw)` 元组（F-g）——RCD 分支必须保持 `(img, raw)` 返回契约，设计应写明。
- **S3** §3.2「等价守卫」名实不符：金样本锁的是**确定性**（不漂移），不锁 **RT 等价**；RT 等价由「整文件搬 + reviewer 逐行对照」（§4 风险2）保证。建议改名「确定性守卫」并如实表述，避免误导验收——「签核即担责：没验证 RT 逐位等价就不能写等价」。
- **S4** §3 缺**四 Bayer 相位覆盖**：RCD 方向判定按 FC 奇偶自适应（recon §1.1），RGGB/GBRG/GRBG/BGGR 四相位是移植最易错处，合成单测必须枚举四相位 × 渐变/彩色边缘用例。
- **S5** §3 缺错误码路径测试：侦察 §7 test_main.cpp 原有「错误码」项在设计 §3 丢失——FallbackRequested（非 RGBG Bayer/尺寸非法）与 InvalidArgs 的 native 级单测须保留；io 层回落路径的 `record_degradation` 断言同补（§1.2 声明了该行为就该有测试锁它）。
- **S6** §3 缺小尺寸边界：tile 194 + border 9 → 补 W/H < 194（单 tile）、≤19（算法区空）、奇数尺寸用例；边界环 9px 需合成图 ≥20px 才能测到 border_interpolate 区域，应显式断言边界环数值。
- **S7** §3 缺真 RAW 冒烟：侦察 §7 pytest 冒烟（真 RAW 形状/值域/回落）未进设计 §3，建议补回。
- **S8** 高光削波断言前移：侦察 §4「按 (white−black) 归一后实测无削波」是实施前断言——A/B 报告应加削波占比指标（输出 =1.0 像素比例），设计 §1.3 指标面补一行。
- **S9** §2 GPL 格式合规（原版权块原文保留 + 来源路径 + commit 6c4cb59 + 适配说明 + THIRD_PARTY_NOTICES.md §8 追加；pixo 已 GPLv3）；两点补强：NOTICE 条目补上游 URL（RawTherapee 仓库 + https://github.com/LuisSR/RCD-Demosaicing，recon §6 已备）；design.md:57-59 的示例标注行给一个**完整文件头示例块**，避免 dev 自由发挥致格式走样。

---

## 2. 重点五项判定

| 重点 | 结论 | 依据 |
|---|---|---|
| §0 定案表五项 | **四项成立，一项待收敛** | 整文件搬+薄适配（依赖面 recon 评级 A，junior 工具链实测支撑 OpenMP 保留）✓；算法事实纠正（无 census）✓；归一化 (white−black) 定案正确——与 decode_raw「0-1 相对白电平」（io.py:137）及 decode_cfa_half（io.py:207,215）同口径，RT 固定 /65536 在 Nikon 白电平 15520 场景会整体压暗 ✓；array2D 薄垫片可行性 ✓（recon 风险2 已配 reviewer 逐行对照）；**但 §1.1 ABI 与侦察草案矛盾未定夺**（→ M3） |
| §1 接口一致性 + 栅栏兼容 | **有条件成立（3 处修订）** | hasattr 可选门系既有惯例（F-h）✓；FallbackRequested 复用现有（S1）✓；**decode.demosaic 键会被栅栏 400 且被 canonical_params 丢弃（M1）**；pattern 注释错误（M2）；签名口径冲突（M4） |
| §2 GPL 标注 | **合规（2 点补强）** | S9 |
| §3 测试判别力 | **有判别力，覆盖有缺口** | 合成单测方向正确；缺四相位（S4）、错误码（S5）、小尺寸（S6）、真 RAW 冒烟（S7）；金样本表述名实不符（S3） |
| §4 风险面 | **完备（含兜底实证）** | WorkBuddy 拒答兜底已写明（design.md §4 行4）——本轮审核即触发该路径并按其处置执行；OpenMP/垫片/耗时覆盖在位；缺全分辨率 float 中间缓冲内存面一条（并入 M3 处置） |

---

## 3. 结论

**有条件通过（0 BLOCKER / 4 主要 / 9 建议）。**

- 红线面：默认链零漂移（缺省 AHD 不变）设计成立；GPL 路径合规；无安全/数据丢失/越权面 → 无 BLOCKER。
- 整改项：**M1（demosaic 透传通道）、M2（pattern 口径）为接口规格硬伤，队长修订后方可动码**；M3（ABI 定夺）、M4（签名口径对齐）同批落实；S1-S9 建议修订时顺带吸收（S4/S5 属测试面必补）。
- 门禁：按「无 BLOCKER 则写门禁」指令，`.design_ok_r32_t1` 已写（结论=有条件通过，整改项随附）；修订落实情况由码检（.code_ok 前）复核，M1/M2 未落修订则码检驳回。

---

*reviewer · 2026-09-23T22:28:54+08:00 · 执行引擎：宿主原生（WorkBuddy refusal，已按 §4 处置标注）*

---

# R32-T1 码检报告（design-review-r32 续）· T1 实施检视

> 日期：2026-09-23（码检棒）｜ 检视人：reviewer（本审核线保留码检权，凭增量 diff 复用）
> 被检对象：分支 render-core-integration 未 commit 增量（diff ≈ +806/−358，.agent-team 黑板文件不在码检域）
> 范围：新 rcd_demosaic_native.cpp / rcd.h / tests/unit/test_io_rcd.py；改 _native/__init__.py、core/io.py、web/export.py、web/session.py、service/runtime.py、service/app.py、native/CMakeLists.txt、native/tests/test_main.cpp、THIRD_PARTY_NOTICES.md §8、tests/unit/test_region_masks_channel.py
> 执行引擎标注：**宿主原生**（WorkBuddy 交叉验证 job-717ad7b4aeeb 提交即拒答 stop_reason=refusal，为本战役第 4 次 refusal；按 design.md §4 既定处置不再重试）。无 workbuddy 会话线。
> RT 原文对照基线：K:/work/project/rawtherapee rtengine/rcd_demosaic.cc、rtengine/demosaic_algos.cc @ 6c4cb59（实读比对，非采信 recon）。

---

## C0. 独立验证（不信口说数字，码检自跑）

| 验证 | 方式 | 结果 |
|---|---|---|
| native 测试 | **隔离构建**（-B build-qa-rcd + `PIXO_RENDER_NATIVE_COPY_TO_PY=OFF`，不触碰 `_native/` 在役 DLL） | **all passed, exit=0** ✓（含 TestRcdDemosaic：四相位/伪彩 vs 双线性/位型金样本/8 条错误路径） |
| pytest 抽查 | test_io_rcd.py + test_gate_curves.py | **19 passed**（15 RCD 用例 + 4 gate 金样本）✓ |
| `_native/` DLL 完好性 | 全程零触碰（隔离构建 + 事后 sha256 留痕）；RCD 符号在役由 pytest 真 native 路径用例证明 | sha256 `e77233d5…`（dev 重建的含 RCD 版本）未被我改动 ✓ |
| 全量回归 1732 | **未重跑**（tester-whitebox 棒随后执行，码检不重复测试执行职责） | 转 tester 复核 |

## C1. 五项重点核（逐项结论 + 行号证据）

**1) GPL 合规 ✓（逐文件）**
- rcd_demosaic_native.cpp:1-18 RT 原版权块**原文逐字保留**（与 RT rcd_demosaic.cc:1-18 头块逐字一致，本棒实读比对）；:19-48 来源标注三处（算法核心 rcd_demosaic.cc @ 6c4cb59 + border_interpolate demosaic_algos.cc（Gabor Horvath 2004-2010）+ rt_math.h）+ 上游 URL（LuisSR/RCD-Demosaicing）+ 适配说明注 1-5。
- 垫片逐处标注：rt_math（:59）、border_interpolate（:97-100）、ALIGNED16→alignas（:387）、chunkSize=2 钉值（:340-341）、scale 移除注（:320-321, :365, :679）。
- THIRD_PARTY_NOTICES.md §8 追加条目完整（仓库 URL + commit 6c4cb59 + 版权人 + 上游 + GPL-3.0-or-later 同源声明）；rcd.h:3-4 指回主文件头。**合规，S9 建议已全部吸收。**

**2) 数值保真 ✓（核心逐字，零顺手重构）**
- RT 原文与移植版逐段比对：装载循环（RT `LIM01(rawData/scale)` → 移植 `LIM01(rawData[row][col])`，rcd.cpp:364-365，注 3 声明）；Step 1.1 bufferV 界与公式（rcd.cpp:374-383）；Step 1.2 bufferH/V0V1V2 swap 旋转（:387-421）；Step 2 lpf（:425-436）；Step 3 四梯度/比率修正/VH_Disc 精化/intp 合成（:439-497）；**Step 4.1 最易错索引逐字对上**（P_Stat=indx3+indx2+indx4+1 / Q_Stat=indx3+1+indx2+indx4，rcd.cpp:529-535 vs RT 同构）；Step 4.2 `c=2-fc(...)`（:544）与四对角梯度/色差（:563-597）；Step 4.3 col 起点用 `fc(cfarray,row,1)&1`（:604，列 1 相位，正确）；tile 写出外缘 rcdBorder/内缘 tileBorder 逻辑（:668-684）；border_interpolate 四象限**不对称边界检查逐字一致**（:123/:156/:194/:232 vs RT demosaic_algos.cc 原文——first columns 无 j1<width 等，均安全因 fallback 门保证 min(w,h)≥19>bord×2）。
- 常量零漂移：eps=1e-5f / epssq=1e-10f / tileSize=194 / tileBorder=rcdBorder=9（:308-318）。仅有的差异全部 = 文件头注 1-5 声明过的适配。array2D 垫片仅下标语义（Array2DView :82-90，行距=width，不改数值）。OpenMP 结构原样（parallel + for collapse(2) schedule(dynamic,2) nowait，:323-342；无 fast-math，CMakeLists 全局 OpenMP::OpenMP_CXX :46-51 继承，金样本位型确定性成立）。

**3) 观察项落实 ✓（均有专门回归锁）**
- `(img, raw)` 契约：io.py RCD 成功路径 `return img_rcd, raw`、失败/不支持走既有路径 `return img, raw`；三处解包调用面不变；`test_returns_img_raw_tuple_contract`（test_io_rcd.py:105-118，断言 `out_raw is raw` + postprocess 未调）锁定。
- 未知 demosaic 静默 AHD：精确 `"RCD"` 大写匹配 + 非 half_size 才进分支（io.py diff `if demosaic == "RCD" and not half_size`），未知值维持既有 `.get` 缺省 AHD 不抛错；`test_unknown_demosaic_value_silent_ahd`（:139-149，断言 `calls==[] and events==[]`）+ `test_session_default_demosaic_attribute`（:287-295）锁定。
- `record_degradation` 调用与签名匹配（degradation.py:124-132：`exc=None` 合法、`reason`/`detail` 关键字在位）；回落路径两态（异常/不支持）各有用例（test_io_rcd.py:151-179）。

**4) 接口与设计 v2 一致性 ✓**
- M1 通道：`_render_full_quality(..., demosaic: str = "AHD")` 显式 kwargs（export.py diff）+ `ExportManager._run` 经 `getattr(session, "demosaic", "AHD") or "AHD"` 仅非 AHD 传参（旧调用面零变化）；session.demosaic 属性缺省 "AHD"（session.py diff）不进 params 白名单；HTTP 面 `submit_export(demosaic)` 校验 `("AHD","RCD")` → ValueError → app.py `except ValueError → _bad_request(400)` 映射在位（app.py:262-263 实读）。
- FallbackRequested=1 复用（abi.h:17 既有）：native 布局门（码值越界/计数≠1R2G1B → 1，rcd.cpp:277-286）+ min(w,h)<19 门（:289-291）；绑定层 `ret==1 → None`（_native/__init__.py demosaic_rcd）+ hasattr 可选门（既有惯例，:478-488）。
- 缺省 "AHD" 零漂移：`test_default_ahd_unchanged`（postprocess 必调 + gamma=(1,1) 钉住断言）+ gate 金样本 4 passed（本棒重跑）。

**5) flip 修复 ✓（dcraw 位语义正确，AHD 零触碰）**
- `_apply_dcraw_flip`（io.py 新增）：bit2=转置 → bit1=flipud → bit0=fliplr，应用顺序与 dcraw/libraw 原文一致；flip=5=转置+左翻（90°）、6=270°、3=180°——docstring 口径正确。
- 仅 RCD 分支消费 `raw.sizes.flip`（rawpy postprocess 的 user_flip=-1 自动翻转语义对 AHD 路径不变）→ **默认链零影响**；`test_dcraw_flip_orientation` 四态参数化 flip=0/3/5/6（形状 40×48/40×48/48×40/48×40，含 portrait 场景 flip=5 回归锁）。
- 预览线 decode_cfa_half 既有缺翻转：dev 如实上报且未动（设计非目标）——纪律正确，留待立项。

## C2. 当场小修（≤5 行原则，已记录）

- **修 1**：`native/CMakeLists.txt` 为 `pixo_render_native_tests` 目标补 `-static-libgcc -static-libstdc++`（与 SHARED 库 :39-44 同款）。检视中 ldd 实证：tests exe 动态依赖构建机 MinGW 运行时且会错配到 PATH 里版本不符的 libstdc++（本次验证中 Git Bash 自带旧版），换机/PATH 不同即无法加载。修后 objdump 复核 import 表两项依赖消除（剩余 libwinpthread-1 为 libgomp/OpenMP 传递依赖，DLL 本体特性，非本修引入），隔离重建测试 all passed。修 1 第一版误置于 add_subdirectory 之前（target 未定义 configure 失败），当场纠正为 add_subdirectory 后置——同一小修内的自纠，最终验证通过。

## C3. 建议（不阻塞，交后续棒吸收）

- **S-1**：`session.demosaic` 为粘性属性、`_run` 执行时读现值——同一 session 两个排队导出任务间改 demosaic 会互相覆盖（region_masks 同款既有语义；单用户场景无实际影响）。若未来要按任务隔离，`ExportManager.submit` 转发参数即可。
- **S-2**：test_io_rcd.py:103 与 :202 类级/方法级 skipif 重复，无害。
- **S-3**：native tests exe 仍依赖 libwinpthread-1.dll（libgomp 传递，MinGW posix 线程模型特性）；非缺陷，不建议为此动线程模型。
- **S-4**：A/B 报告建议补削波占比指标（输出 =1.0 像素比例，S8 遗留）；tester 棒跑全量回归 1732 后 T1 收口。

## C4. 码检结论

**通过（0 BLOCKER / 0 主要 / 1 当场小修已验证 / 4 建议）。**

- GPL 逐文件合规、RT 核心逐字保真、两条观察项回归锁定、接口与设计 v2 全对齐、flip 修复正确且默认链零触碰——T1 实施与设计门禁 v2 无偏差。
- `.qa_ok` 前置意见已写：全量回归 1732/0 与分支推送由 tester 棒收口（码检已抽查 gate 4/4 + RCD 15/15 + native all passed）。

*reviewer · 码检棒 2026-09-23 · 执行引擎：宿主原生（WorkBuddy refusal×1 本棒，战役累计×4，均按 §4 处置）*
