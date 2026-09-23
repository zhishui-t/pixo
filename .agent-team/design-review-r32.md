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

---

# R32-T2 检视报告（design-review-r32 续）· 轻量棒

> 日期：2026-09-23（T2 检视棒）｜ 检视人：reviewer（本审核线）
> 被检对象：① core/color.py 三处注释锚点；② tests/unit/test_region_masks_channel.py T1 遗漏适配；③ dev1-r32-t2.md + .artifacts/_r32_t2_dcp_compare.json 数据面抽核；④ V1 回滚纪律 + V9 证据
> 执行引擎：宿主原生（R32 §4 既定兜底，RT 任务族 refusal 实证累计，未重试）

## T2-1. color.py 锚点 ✓（纯注释实证）

`git diff` 全量 14 行新增逐一核对：`neutral_to_xy` docstring 注记（:399-411 段）、`cct_from_wb` docstring 注记（:427-437 段）、`cam_to_xyz_matrix` 行内 # 注记（:572-576 段）——**全部为注释/docstring 文本，零代码行、零行为变更** ✓。

## T2-2. 测试替身适配 ✓（两态实测，且暴露 T1 提交遗漏实情）

- 修复本身正确：stub lambda 补 `demosaic="AHD"` 缺省，与 `_render_full_quality` 现显式传参的调用面对齐 ✓。
- **两态实测（stash push/pop，本棒亲跑）**：HEAD 提交态（275a818，无适配）→ **2 failed**（`test_render_full_quality_state_extras_masks` / `test_render_full_quality_no_extras_backward_compatible`）；工作区（含适配）→ **23 passed**。协调者断言独立复现 ✓。
- **记录（纪律点）**：T1 提交 2758a18 漏带此适配文件 → 提交态全量回归必含 2 失败；T1 交棒的「1732 passed」口径应为**含适配的工作区态**。建议 T2 提交信息注明「补 T1 遗漏的测试替身适配」，避免两报告口径打架。

## T2-3. 数据面抽核（2 个关键数字，一过一退）

**抽核 A ✓「RT 灰点随 WB 漂移 3200K xy(0.364,0.446)」（E3/V4）——推导链扎实，采纳：**
- json e3 `gray_rt[3200K]=[0.36359, 0.44628, 0.19013]`（XYZ/sum 表示）与报告 xy(0.364,0.446) 一致；pixo 侧 gray_px 恒 (0.34567,0.3585)=D50 ✓。
- 机制实读钉死：RT dcp.cc:1891-1939 dcraw legacy 段（本棒实读原文）——cam_rgb 过 xyz_sRGB 后**逐行归一化使 (1,1,1)→(1,1,1)**（RGB 等能白），取逆再复合——中性点因此锚在 sRGB 管道而非 PCS，随 WB 漂移；脚本 :181 注释「dcp.cc 1900-1939」+ :199 srgb_design 表与原文行号/结构吻合 ✓。
- **可复算性实证**：实验脚本重跑两次，产出 json **逐位一致**（determinism=True）✓。

**抽核 B ✗「FM1@(1,1,1)=XYZ D50 逐位成立」（E4/V5）——证据表述缺陷，退回修订（主要）：**
- 脚本 E4 段**无此 claim 的任何断言/输出代码**（note 为纯文字，rows 仅有矩阵差/ΔE/灰点）；
- **与同一 json 的数据表面矛盾**：e4 rows `gray_px`（pixo FM 域链灰点）= (0.28848,0.24395)@3200K / (0.37942,0.25578)@4500K / (0.46432,0.25245)@6500K——随 WB 漂移且 ≠ D50(0.3457,0.3585)。本棒以 pixo 链独立复算 `(inv(s)·cam_to_prophoto_matrix)@(1,1,1)` 三个 WB 点，输出与 gray_px **逐位一致**（脚本可信），即 pixo FM 域链 (1,1,1) 并不出 D50；
- 本棒四种构造独立复算均 ≠ D50：RT 字面 white=D50（归一 xy (0.2563,0.3811)）、RT 字面 white=StdA 场景白（(0.3827,0.3924)）、规范式 FM1·(CM1·1)/Y（XYZ 差 -0.26 级）、pixo 折回链（见上）；
- **真实出处已钉死**：RT dcp.cc:1892 `constexpr Triple white_d50 = {0.3457, 0.3585, 0.2958}` 是**无 FM 分支 `MapWhiteMatrix(white_d50, white_xyz)` 的源白点常量**——json note 与报告 V5 行把这一源码常量误写成了「FM1@(1,1,1) 输出逐位=D50」的验证结论。
- **处置**：不动摇 V5 裁决方向（保持+待议，依据是 ΔE 数据与「FM 优先=渲染哲学变更」的定性判断，均独立成立），**不阻塞 T2 提交**；但 **dev-1 须修订 dev1-r32-t2.md V5 行与 json e4 note**（改写为上述常量出处事实）后方可被 T8 台账引用——T8 台账数字必须可复算，此为门槛。

## T2-4. V1 回滚纪律与 V9 证据 ✓

- **V1 回滚纪律 ✓**：吸收尝试触碰金样本零漂移红线（4 失败）即回滚，三处锚点留码（T2-1 已证纯注释）；受影响面 46 passed 本棒复跑全绿（test_color_math + test_illumination_est + test_diff_core + test_gate_golden，29.16s）✓。红线优先于改进，处置正确。
- **V9 LookTable 证据 ✓（入 T8 台账首位成立）**：meta 实测锚定真 Adobe DCP（look_dims=[90,16,16]、look_encoding=1、hsm 缺、BEO=-0.15）；「底座零消费」grep 证实（calibration.py 仅解析 tag 面；huesat.py:36 可选 look 开关基座默认关闭，R11 A 轨退役史在案）；E7 幅度如实标注「需完整 hsdApply 移植」不过度声称 ✓。前置条件：同报告内 V5 表述缺陷修订后一并归档。

## T2 结论

**通过（0 BLOCKER / 1 主要〔证据表述，限向修订，不阻塞提交〕/ 1 记录〔T1 提交遗漏适配，本棒修复正位〕）**。color.py 锚点与测试修复可提交；T2 推送后 dev-1 顺手修订 dev1-r32-t2.md V5 行 + json e4 note（措辞见 T2-3 处置），T8 台账编制时按修订稿引用。

*reviewer · T2 检视棒 2026-09-23 · 执行引擎：宿主原生*

---

# R32-T3 检视报告（design-review-r32 续）· 轻量棒

> 日期：2026-09-23（T3 检视棒）｜ 检视人：reviewer（本审核线）
> 被检对象：core/lut3d.py 增量（hald_level_to_lut + write_cube）、tools/haldclut_convert.py（新 CLI）、tests/unit/test_haldclut_convert.py（6 用例）、dev1-r32-t3.md、T2 限向修订落位
> RT 对照基线：rtengine/clutstore.cc @ 6c4cb59（本棒实读 :25-215）

## T3-1. hald_level_to_lut 索引推导 ✓（实读 RT 原文对照）

- **level 布局全一致**：边长=level³（RT clutstore.cc:40-47 `while level³<fw` 恰等）、网格 N=level²（:137 `clut_level *= clut_level`）、线性索引 **r+g·N+b·N²**（:183 `color = red + green*level + blue*level_square`，:137 后 level 即 N）、位深口径 uint16/65535（:138 `flevel_minus_one=(N-1)/65535`）——pixo 实现（xs=idx%side、ys=idx//side 行主序 gather、meshgrid ij 序 r 最慢 b 最快）与 RT 逐点对应 ✓。
- 防呆：非 level³ 边长拒收并引导 n² 布局走既有 `hald_to_lut` ✓；**既有 hald_to_lut（n² 布局）零触碰**（diff 纯追加，唯一删除行为 `__all__` 扩展）✓。
- write_cube 行序 r 最慢/b 最快与 parse_cube 读入一致；互逆性由 `test_write_cube_roundtrip` 锁定（4³ 随机数据、容差 2e-6=%.6g 文本量化、domain 断言）✓。

## T3-2. 「三线性 vs 四面体 10 倍」论断 ✓（基准可信 + 独立复算远超）

- **基准可信**：测试内 `rt_trilinear_ref` 与 RT getRGB 非 SSE 路径（clutstore.cc:186-210）逐式等价——intp 参数序展开同构（RT `intp(re, next, cur)` = cur+re·(next−cur) ≡ 测试 `intp(t,a,b)=a+t(b-a)` 同式）、r 向插值→g 混→b 平面重复→b 混结构一致、顶格钳 `min(N-2, v·(N-1)/65535)` 同款；出处标注在案（仅测量用，非生产移植）✓。
- **独立复算（同场景 seed=7，本棒亲跑）**：err_tet=**5.96e-08**（float32 eps 级，仿射场上逐位精确）、err_tri=**1.665e-01**、比值 **≈2.8×10⁶ 倍**——「10 倍以上」论断保守成立，「吸收 RT 引擎代码只有精度下行」的取舍依据扎实 ✓。
- 测试实证：test_haldclut_convert + test_lut = **22 passed**（本棒复跑）✓。

## T3-3. CLI 与测试判别力 ✓（1 条建议）

- 6 用例覆盖：恒等精确（16 位顶点 ≤1.5e-5=量化级）、8/16 位一致性（≤2/255）、非法尺寸拒绝（非立方/非方图）、write_cube↔parse_cube 往返、仿射精度对照、端到端 png→cube→lookup（真走 cv2 16 位 png 与 BGR→RGB 翻转往返）——判别力足够 ✓。
- BGR 翻转正确性由端到端用例隐性锁定 ✓（cv2 读出 BGR、Hald 索引按 RGB——翻转缺失则恒等断言必挂）。
- **建议（不阻塞）**：`test_tool_convert_identity` 端到端容差 `1.5/(n-1)≈0.1` 偏松（恒等 CLUT 上四面体应达量化级），可收紧至 ≤1e-4 级提升判别力；现版防「布局级完全错误」够用。

## T3-4. 许可纪律 ✓

RT 官方 Film Simulation 包许可异质如实记录（聚合无统一许可、CC-BY-NC 混杂）**不入仓**；实测 3 个胶片观感全部自造（自有版权）；转正入库留队长/用户裁决——与 task-brief T3 纪律（只引擎/格式层，数据另议）一致 ✓。

## T3-5. T2 限向修订落位 ✓

dev1-r32-t2.md V5 行勘误版（如实记录：RT dcp.cc:1892 无 FM 分支 MapWhiteMatrix 源白点常量 {0.3457,0.3585,0.2958} 被误当验证结论、E4 脚本无此断言、四种复算均 ≠D50）+ `_r32_t2_dcp_compare.json` e4 note 重新生成 + `.py` note 同步——与本棒 T2-3 钉死的事实一致，修订完整落位 ✓。上棒退回项关闭。

## T3 结论

**通过（0 BLOCKER / 0 主要 / 1 建议）**。T3 可提交推送并派 T4（曲线轮）；建议项（端到端容差收紧）随 T4 或收官轮顺带处理即可。

*reviewer · T3 检视棒 2026-09-23 · 执行引擎：宿主原生*

---

# R32-T4 检视报告（design-review-r32 续）

> 日期：2026-09-23（T4 检视棒）｜ 检视人：reviewer（本审核线）
> 被检对象：core/curves.py 四插值模式、modules/tone_map.py mode 键、pipeline/graph.py 栅栏放行、tests/unit/test_user_curve.py（+7 用例）、_r32_t4_curves.json、dev1-r32-t4.md
> RT 对照基线：rtengine/diagonalcurves.cc + diagonalcurvetypes.h @ 6c4cb59（本棒实读）
> 独立验证：scipy 交叉复算（Akima1DInterpolator / CubicSpline(natural) / PCHIP，本棒亲跑）

## T4-1. 四模式数学同构性（对照 RT 实读）

- **spline ✓（双证）**：RT `spline_cubic_set`（diagonalcurves.cc:142-168，本棒实读）`ypp[0]=0 /* natural */` + `ypp[N-1]=0.0` ——自然边界确认；pixo `_natural_cubic_coeffs` 同边条件同三对角数学（矩阵解 vs NR 递推，同构）。双证：dev 四组控制集 vs scipy CubicSpline(natural) ≤6e-8（json `spline_vs_scipy_natural_max_diff`）+ 本棒独立复算 1.2e-14（机器精度）。
- **catmull_rom ✓（逐式对照）**：α=0.375（RT `catmull_rom_tj` :286-292 `pow(sqrt(Δ²), alpha)+ti` 实读，pixo 同式）；端点斜率受限反射同式（:371-388 `rx=cx−dx·0.01`、`dx>1e-5` eps 判——pixo `_catmull_rom_reflect` 逐字对应）；de Casteljau 三级展开（A1/A2/A3/B1/B2/C 的 t 区间权式）逐项一致；**y∈{0,1} 平段精确保持**（RT 平段特例 :330 同款，`test_r32t4_catmull_rom_flat_asymptote` 0 偏差锁定）。采样密度（RT n_points 参数 vs pixo 512/单位区间）仅影响 np.interp 重采样精度（4096 LUT 下二阶），非语义差——pixo 为公开数学独立实现非逐位移植，注释如实。
- **monotone ✓**：Fritsch–Carlson (1980) 三段式正确（端点单侧差商 / 变号置零+调和均值 / `tau=3/√(a²+b²)` 限幅），陡峭集 0 过冲断言在位。vs scipy PCHIP 差 0.123 系**已知变体差异**（FC≠PCHIP，两者均单调保持），非缺陷——报告如实区分。
- **akima ✗（主要，见 T4-6）**。
- 出处注释 ✓：RT diagonalcurves.cc 逐式标注 + akima/monotone 明标「公开文献独立实现，非代码移植」——GPL 面干净（RT 对照仅 spline/CR 数学，无代码拷贝）。

## T4-2. 向后兼容红线 ✓（实现零触碰 + 三方 array_equal 锁定）

- `curve_lut_from_points` linear 分支与旧实现逐字同（linspace+np.interp+float32，仅函数搬家加 `mode="linear"` 参数）；list 输入与非 dict → `_user_curve_mode` 恒返 "linear" → 旧路径逐位不变；dict 无 mode 键同。`test_r32t4_linear_default_bitwise_unchanged` 三方 `array_equal`（list = 无 mode dict = mode:"linear" dict）锁定 ✓。
- tone_map allowed 集扩展受控（+mode）；graph 栅栏 mode 取值校验完备（合法集与 tone_map/curves 同值、None 放行=取默认、非法拒）✓。

## T4-3. 前端影响面实查 ✓（报告 §6 影响面不成立，无需前端改动）

frontend/src 全目录 `user_curve` 零命中；曲线 UI 为占位（AdjustmentsPanel.tsx:169-172「曲线编辑器正在开发中」）——**当前无任何前端 user_curve 构造/校验，mode 键不撞任何前端路径**。报告 §6「前端表单校验需同步」表述超出实况，建议改为「当前无前端校验面；未来曲线编辑器立项时纳入 mode 选择」。

## T4-4. 过冲矩阵与事实纠正 ✓

- 排序属实（S2_steep_contrast）：akima 0.331 > spline 0.209 > catmull_rom 0.013 > monotone/linear 0.0 ✓（json rows 本棒全读）。spline 交叉 ≤6e-8 口径=仅 spline vs scipy natural，诚实未扩大 ✓。
- **「RT 无 Akima」实证 ✓**：diagonalcurvetypes.h 枚举全列（DCT_Empty/Linear/Spline/Parametric/NURBS/CatumullRom/Unchanged，本棒实读全文）+ rtengine 全目录 grep "akima" 零命中——任务书纠正有源码证据，防过冲正解=monotone 的结论由矩阵支撑。

## T4-5. scipy 交叉验证口径 ✓（诚实但验证面不足，恰放过 T4-6）

json/报告声称的交叉验证=仅 spline vs scipy natural（≤6e-8）——声称与实际一致；但 akima/monotone 无 scipy 参考行，akima 的结构偏差因此漏网。建议修 akima 时顺带补 `Akima1DInterpolator` 参考行（monotone 标「PCHIP 性质参考，非等值」）。

## T4-6. 主要项（1）：akima 切线权重与 Akima (1970) 标准式不符

- `_akima_tangents` 的 `w_left = |d[i+2]−d[i+1]| = |δ_i−δ_{i-1}|`——标准式（Akima 1970 式(6)；scipy 同）为 **`|δ_{i+1}−δ_{i+2}|`**（即 `|d[i+3]−d[i+4]|`）；w_right 用法正确。注释声称「权重按 Akima (1970) 式 (6)」与实现不符。
- **独立复算实锤**：同控制点 pixo akima vs scipy `Akima1DInterpolator` max diff = **0.1176**（结构性偏差，非数值噪声）。
- 连带：报告 :7/:43 与 json 的「akima 过冲 0.331 / mono_violations 797」数字系错误实现产物，须修后重生成；`test_r32t4_steep_overshoot_matrix` 的 `akima>0.1` 断言修后大概率仍绿（Akima 固有过冲倾向），须复跑确认。
- **影响面**：不触及向后兼容红线（linear 缺省）与 spline/CR/monotone 三模式；akima 为可选新值，无既有消费方。

## T4 结论

**有条件通过（0 BLOCKER / 1 主要〔akima 权重，提交前必改〕）**。

提交前置（dev-1，预计 3 行码 + 数据再生）：
1. `curves.py _akima_tangents`：`w_left` 改 `abs(d[i+3] − d[i+4])`（=|δ_{i+1}−δ_{i+2}|），注释同步；
2. 重跑 `_r32_t4_curves.py` 重生成 json（akima 行数字更新）+ dev1-r32-t4.md :7/:43 数字更新；
3. 复跑 test_user_curve 全量（akima 断言确认）；修后 diff 过我一眼即放行。
顺带（不阻塞）：§T4-3 前端表述改写 + akima scipy 参考行 + 栅栏 mode 非法值断言一条。

*reviewer · T4 检视棒 2026-09-23 · 执行引擎：宿主原生*

### T4-7. 回流复检（同日）——放行 ✓

dev-1 修正交棒复核（4 文件）：
1. **akima 修正 ✓（scipy 数值裁决）**：`_akima_tangents` 两处——w_left 权重 `|δ_i−δ_{i-1}|`→`|δ_{i+1}−δ_i|`（我点名）+ 左端延拓序 `[δ_{-1},δ_{-2}]`→`[δ_{-2},δ_{-1}]`（dev 自查，恰为 0.1176 主源）。本棒独立复算：**三控制集 + 5 随机集 vs scipy Akima1DInterpolator 全部 ≤5.95e-08**——与 scipy 语义对齐实证（dev 以 scipy 源码为锚正确；我上棒引用的文献式与 scipy 实现有出入，以数值为准）。break_mult 相对近零割线平均 fallback 同 scipy 语义。
2. **过冲断言未迎合性放宽 ✓**：`akima > 0.1` 原样保留，0.180 实测真实成立；json akima 行 0.17979/914 与报告 0.180/914 一致；排序互换（spline 0.209 > akima 0.180）如实记录，「防过冲正解 = monotone」结论维持。
3. **json/脚本/报告三方同步 ✓**：json 新增 `akima_vs_scipy_max_diff` 参考块（四组 ≤6e-8）；报告 :7/:43/:47/:51/:75 数字与勘误记录（含 0.1176/0.658 两处偏差来源）同步；§6 前端影响面句已改写（T4-3 结论吸收）。
4. **测试 ✓**：test_r32t4_akima_matches_scipy（≤1e-6，scipy 缺失 skip）新增；test_user_curve 28 passed（21+7）+ test_param_type_consistency 6 passed 本棒复跑；全量 1746/0（dev 报，tester 棒复核）。

**T4 放行**（主要项关闭；建议项——栅栏 mode 非法值断言一条——随 T5 顺带，不阻塞）。

---

# R32-T5 检视报告（design-review-r32 续）· 轻量棒

> 日期：2026-09-23（T5 检视棒）｜ 检视人：reviewer（本审核线）
> 被检对象：vision/measure.py（luma="lab_l"）、service/runtime.py+app.py（透传+400）、test_f04_param_fence.py（+3 遗留补齐）、test_proxy_metrics.py（+4）、dev1-r32-t5.md
> RT 对照基线：rtengine/improccoordinator.cc + rtgui/histogrampanel.cc @ 6c4cb59（本棒实读）

## T5-1. Lab L* 口径 ✓（RT 系数实读 + 数学标准 + 手算锚点）

- **RT 系数实读**：`updateLRGBHistograms`（improccoordinator.cc:2939-2996）`histLuma[(int)(nprevl->L/128.f)]++`——LabImage L 域 [0,32768]（L*×327.68；旁证：同函数 Chroma `/188` 自注「48000/256」同域惯例）→ 桶 = int(L*×2.56) 0..256；pixo `_lstar_255` = L*×2.55 → 0-255 域同语义（缩放差 0.4% + 末桶惯例差 = 二阶，docstring 如实记录）。**报告 §1「L*∈[0,100] 线性映射 256 桶」与实读相符，口径同构成立** ✓。
- **数学 ✓**：sRGB EOTF 逆（0.04045/12.92/1.055/2.4）→ 线性 BT.709 Y → CIE L* 分段式（eps=216/24389、(24389/27)y/116）——全部标准式；工作空间原色（非 Rec709）差已在 docstring 如实记为二阶近似。中灰锚点独立手算：u8=118 → linear≈0.1793 → L*≈49.4 → ×2.55≈126 桶，与测试 124..128 断言吻合 ✓。
- **域语义说明（不阻塞）**：RT 面板 Luma 取自 16 位 Lab 管道（nprevl），pixo 从 gamma sRGB 预览帧 EOTF 逆近似——帧域差已由 docstring「二阶近似」+ 报告 §2 域行覆盖，如实。

## T5-2. 向后兼容红线 ✓（三重锁定）

- 实现层：counts 先建 4 键再条件追加 `lum_lstar`——bt709 缺省路径输出键集/数值零变化 ✓；
- 测试层：键集断言 + 同输入 lab_l 调用的既有 4 键逐位相等（`test_histogram_lab_l_appends_lstar_key_default_unchanged`）✓；
- 检视层：本棒手工内联旧实现体复算 `counts.lum` 与新版**逐位一致** ✓。
- 非法 luma 两层 400 ✓：函数层 raise（measure.py luma 校验）+ 端点层 `except ValueError → _bad_request`（app.py 实读）。

## T5-3. 联动契约定型 ✓（对照 firstAnalysis 数据流）

- RT：`firstAnalysis`（improccoordinator.cc:861）产 vhist16（65536 桶工作空间 Y master）→ CurveFactory 压 256 供曲线编辑器背景 + 同 master 喂 getAutoExp 曝光匹配——报告 §1 表格与实读一致 ✓。
- pixo 契约 = `compute_histogram(pre_curve_gamma_frame, bins=256).counts.lum`：曲线背景所需「施加前亮度分布 256 桶」形状对齐 ✓；帧域差（RT 工作空间线性 Y vs pixo gamma 帧）以 `pre_curve_gamma_frame` 命名如实标注 ✓；管线截帧登记「待曲线 UI 落地，非本棒」清晰、不冒进 ✓；`luma=lab_l` 显式开启供感知 y 轴 ✓。契约充分。

## T5-4. parade 裁决 ✓（实读 drawParade；1 条表述勘误）

- `HistogramArea::drawParade`（histogrampanel.cc:1491-1530，本棒实读）：仅将已备数据渲染为红/绿/蓝三窗 Cairo buffer（含 needRed/Green/B 开关），**零新数据计算**——「非独立数据模式」裁决成立，我方 r/g/b 键即数据面的表述准确 ✓。
- **勘误（建议级，不改裁决）**：drawParade 渲染的底层数据是 **rwave/gwave/bwave（RGB 波形 waveform）**，非报告 §1 行 19 所写 histRed/Green/Blue（直方图）——parade 在 RT 中是波形监视器的三窗布局。裁决（同数据多窗、非新模式）不受影响；T8 台账引用时按「RT parade=波形三窗」表述即可。

## T5-5. 遗留补齐与 T7 登记 ✓

- test_f04_param_fence 3 断言落位 ✓（合法五值栅栏放行 / 非法值拒且含 "mode" 原因 / Stage._curve_dict_check 抛 ValueError——T4 遗留项关闭）；
- 匹配曲线联动（RT getAutoExp→曝光/对比自动匹配）登记 T7 曝光校准轮、口径清晰不在本棒 ✓。

## T5 结论

**通过（0 BLOCKER / 0 主要 / 1 建议勘误）**。测试实证：test_proxy_metrics + test_f04 + test_user_curve = **92 passed, 1 skipped**（本棒复跑）。T5 可提交推送并派 T6（HSL/分色调）；勘误句随 T6 或 T8 台账编制时顺带修正。

*reviewer · T5 检视棒 2026-09-23 · 执行引擎：宿主原生*

---

# R32-T6 检视报告（design-review-r32 续）· 轻量棒

> 日期：2026-09-23（T6 检视棒）｜ 检视人：reviewer（本审核线）
> 被检对象：core/hsl.py（adjust_math="rt"）、core/split_tone_oklab.py（preserve_luma）、两 Stage schema 透传、test_hsl_split_tone_r32t6.py（新 7 用例）、契约测试同步、dev1-r32-t6.md + _r32_t6_hsl.json
> RT 对照基线：rtengine/improcfun.cc @ 6c4cb59（本棒实读 :2740-2800 HSV 段、:4003-4104 toning2col 全段）

## T6-1. adjust_math="rt" ✓（RT 施加式逐式对照通过）

实读 improcfun.cc:2755-2791（HSV equalizer 像素段）逐式核对：
- **sat 正向**：RT `s'=(1−p)s + p(1−(1−min(s,1))²)`（二次混合，高饱和收敛无截断）——pixo rt 分支同式 ✓；**sat 负向**：RT `s *= 1+p`（乘法）——同 ✓；
- **lum 饱和衰减**：RT `valparam *= (1−SQR(SQR(1−min(s,1))))` = **(1−(1−S)⁴)**（近中性保护更强/中间饱和作用更满），再正混/负乘——pixo `lum_w=1−(1−protect)⁴` 同式 ✓；E3 数字手验自洽（1−(1−0.05)⁴=0.186 ✓、1−(1−0.9)⁴≈1.000 ✓）；
- p 域 [-1,1] 同（RT 曲线输出 ±1、pixo x/100·m）；pixo 附加 clip(0,1) 与无 ±1e-5 死区 = 二阶加固，不改变语义；
- 吸收面如实：吸收的是**施加数学**而非 RT 曲线控制面（RT sCurve/vCurve 为 hue 轴全域曲线，pixo 为 8 band 掩码——报告 §2 hue 行「保持+理由」裁决合理）✓。

## T6-2. 缺省红线 ✓（两参数均缺省关闭 + 双锁）

- hsl：`adjust_math="pixo"` 分支保留原式逐字（对称乘法+线性 protect），default/schema choices 校验到位，非法值 raise；oklch 路径不受影响 ✓。
- split_tone：`preserve_luma=False` 时不进恢复块，输出路径原样；hsv 旧路径零接线 ✓。
- 测试双锁：`test_adjust_math_default_bitwise_unchanged`（内联旧公式复算 ≤1e-6）+ `test_split_tone_preserve_luma_default_bitwise_unchanged`（array_equal）✓。E2 的 50.05% clip 数据即**既有行为画像**（锁定非修复）✓——RT 正向混合 s=0.8/+100 → 0.96 手验吻合（`test_adjust_math_rt_sat_boost_no_clip` 断言化）。

## T6-3. preserve_luma ✓（乘性恢复同构 + E4 可信；1 条建议注明系数域）

- RT 实读（improcfun.cc:4093-4104）：`preserv = lumbefore/lumafter`，`CLIP(rgb·preserv)`——pixo `scale = y/max(y_after,1e-9); out·scale` 同式 ✓（pixo 1e-9 防零除更稳）。
- **建议（不阻塞）**：系数域差异未注明——RT luma 加权为 **Rec.601（0.299/0.587/0.114）**，pixo `_RGB_WEIGHTS` 为 **BT.709（0.2126/0.7152/0.0722）**。机理同构（乘性恢复），系数域为 pixo 全链自洽选择，建议 docstring 一句注明「RT 原文 Rec.601、本实现 BT.709（域惯例）」避免「同式」误读。
- E4 三臂数据可信 ✓：0.08627（RT preser=0）/ 0.02691（pixo oklch）/ 0.00467（RT preser=1）——「恢复有效 + 我方 oklch 居中」支撑 A2；json note 如实标注「RT 参考含 secondeg_* 简化（测量参考非逐位），结论量级级」——诚实不过度声称 ✓。

## T6-4. CLUT 裁决 ✓（源码推翻成立）

toning2col 全段实读：**逐像素解析数学**——secondeg_end/begin 二次 ramp（阴影/高光中段削平）+ 阴影保护 `pow(min(rgb)/20000, 0.85)`（纯黑不动）+ 高光滚落（>45535 线性衰减），全段无任何 LUT 查表；labtoning docstring 自注「ctColorCurve curve **500 colors**」（500 点色曲线 + opacity 曲线）。「CLUT 猜测被源码推翻」表述与源码一致 ✓。

## T6-5. FlatCurve 登记 → 建议列 T8 台账（横切项）

§6.2 登记如实（FlatCurve FCT_MinMaxCPoints 控制笼未移植、未做曲线级对拍—— apples-to-apples 缺失如实声明）。**评估：应列 T8 台账**——hue 轴自由控制点曲线是**能力面差异**而非纯 UX 差异（8 具名带 + 环状升余弦掩码无法表达任意非对称 hue 形状；RT 侧 8 带实为 UI 分区、参数面是自由曲线，报告 §1.1 结构纠正已自证），且 FlatCurve 体系横跨 HSV Equalizer 与曲线编辑器两域，登记为 T8 横切项（非 HSV 单项）。

## T6-6. 契约测试同步 ✓

加法式合规：`test_stage_default_params_preserved` 原 8 键值零改动断言保持、新键 `preserve_luma: False` 显式入表 + schema 在位断言 ✓；新 7 用例判别力合格（0.96/0.3 手验锚点、衰减四断言、漂移 d_on < d_off/3、两个 array_equal 红线锁）✓。

## T6 结论

**通过（0 BLOCKER / 0 主要 / 1 建议〔preserve_luma 系数域注明〕+ 1 台账建议〔FlatCurve 列 T8 横切项〕）**。测试实证：test_hsl_split_tone_r32t6 + test_split_tone_oklab + test_hsl = **42 passed**（本棒复跑）；全量 1760/0 留 tester 棒复核。T6 可提交推送并派 T7（曝光校准 + T5 登记的匹配曲线联动接驳）。

*reviewer · T6 检视棒 2026-09-23 · 执行引擎：宿主原生*

---

# R32-T7 检视报告（design-review-r32 续）· 轻量棒

> 日期：2026-09-23（T7 检视棒）｜ 检视人：reviewer（本审核线）
> 被检对象：modules/exposure.py（auto_match_suggest + mode="match"）、test_exposure_match.py（新 6 用例）、_r32_t7_exposure.json、dev1-r32-t7.md
> RT 对照基线：rtengine/improcfun.cc getAutoExp :5440-5650 @ 6c4cb59（本棒全文实读）

## T7-1. auto_match_suggest 逐式对照 ✓（16 结构点全对上 + 2 泛化等价）

RT getAutoExp 全文实读，pixo 移植逐项核对：
- **统计**：sum/ave（getSumAndAverage）、中位累积过半 ✓；八分位 log2(1+j) 域、sum/8 定格（末位 sum/16）✓；过曝外推 `1.5·oct[5]−0.5·oct[4]` 与 oct6/oct7 快照 ✓；零 octile 前向传播 ✓；ospread 加权间距 ÷5（分母 max(0.5, octile[3] 分段)）✓；
- **clip 双点**：clippable=sum·clip、whiteclip/shc 两个 while 累积循环边界同 ✓（RT clip 为百分数 /100，pixo 参数语义 0.02=2% 已内化，等价）；
- **EV 合成序**：expcomp1（中灰锚定 `log2(midgray·scale/(ave−shc+midgray·shc))`）+ expcomp2（顶点估计 `0.5·(C−(2·oct7−oct6)+log2(scale/rawmax))`）按 |e1|−|e2|>1 分派几何/算术混合 ✓；
- **五参**：gain=2^ev → corr=√(gain·scale/rawmax) → black=shc·corr ✓；hlcompr 级数近似 ×2.3、clamp[0,100]、thresh=0 ✓；bright 控制笼包络两段式 + 0.25·max(0,·) ✓；contr=50(1.1−ospread) clamp ✓；黑帧全零安全返回 ✓；
- **两处泛化数学等价**（dev 自述修正的 bin/scale 换算）：bin→scale 域 `×scale/n` ≡ RT `<<histcompr`（bin 宽同一）；`15.5−histcompr` ≡ `log2(n)−0.5`（n=imax=65536>>histcompr 时恒等）——修正后与 RT 原式一致 ✓；
- **建议级登记（2 条二阶边界差异，不阻塞）**：①losum/hisum 分界 bin 双计（pixo 第一循环 range(int(ave_bins)+1) 且第二循环从 j 起——分界 bin 的 octile 累计/losum 各多计一次；影响八分位 ±1 bin 精度与黑帧判定边界）；②黑帧判据组合：RT `median==0 OR ave<1` vs pixo `median==0 AND hist[0]==0` 加 ave 阈——hist[0]>0 的 median=0 图像 pixo 不触发安全零（RT 会）。两条均在防御路径，正常图像建议值不受影响，T8 台账引用移植实现时注明即可。

## T7-2. 缺省红线 ✓ + 建议语义 ✓

- `default_params["mode"]=="baseline"` 为既有缺省（diff 未触 default_params），`mode="match"` 为 elif 插入分支，auto/off/baseline/数值路径零触碰——红线成立，`test_exposure_stage_default_mode_unchanged` 锁定 ✓；
- **建议写 metrics 非自动套用 ✓**：black/hlcompr/contr/expcomp/overex 以 RT 原单位写 `ctx.results[-1].metrics["exposure_match_*"]`；EV 仅取建议 expcomp 沿既有 ev 应用链（同 max_ev 钳位）；**无 tone 参数写点**（六键消费留编辑动作显式化）——「建议语义」核过 ✓。

## T7-3. 并存非整替数据 ✓

E1 direction_check 如实记录：中灰直方图 getAutoExp_ev=**+0.369** vs 我方中位锚定 **0.0**（same_sign=false）——RT match 含「直方图顶点推向 clip」第二目标项，非纯中灰锚定；暗场 +1.106/亮场 −0.176 与中位锚定同号（暗/亮场景两口径方向一致）。json/报告/协调者表述三方一致 ✓——match 与 auto 并存的语义差异已数据化留档 ✓。

## T7-4. 三个「保持」裁决 ✓

- **黑白点硬钳制**：RT toneCurve.black（含逐通道 blackred/green/blue）= 曲线前数据钳制；pixo blacks/whites 为带通乘性键、无硬 clip——不吸收硬钳语义（我方设计特性=验收项）裁决合理 ✓；
- **HL compression**：RT hlcompr/thresh=曝光曲线肩部压缩（shoulder 公式在案），pixo soft_highlight_rolloff+highlight_compress_curve+shoulder 能力已覆盖 ✓；
- **E3 六键 ramp**：1024 级 ramp ±0.8 满载——四键双向单调、内域无 ≥3 采样硬 clip 平台、带外隔离数值在 json ✓（T1.5 六键数学达标的数据化）；
- **guided filter 局部恢复**：RT S/H = Lab L* pow4 掩码 + **guidedFilter(L, mask) 局部细化** + L* gamma 映射 + NURBS 暗部对比 + 色度保持（§1.1 机理与任务书问题回答齐备）——pixo 六键为全局带通语义，**T8 台账登记**为独立工具语义 ✓。

## T7 结论

**通过（0 BLOCKER / 0 主要 / 2 建议登记〔八分位分界 bin 双计、黑帧判据组合——移植实现的二阶边界，T8 引用时注明〕）**。测试实证：test_exposure_match + test_exposure = **31 passed**（本棒复跑）；全量回归留 tester 棒复核。T7 可提交推送并派 T8（全模块清点收官棒）。

*reviewer · T7 检视棒 2026-09-23 · 执行引擎：宿主原生*
