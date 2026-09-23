# dev1 R32 实施报告 · T1 RCD 去马赛克移植（design.md v2 落地）

日期：2026-09-23 ｜ 角色：dev-1 ｜ 分支：render-core-integration（未 commit，待检视）
执行引擎：**宿主原生直接执行**（WorkBuddy 引擎拒答，design v2 §4 兜底条款；侦察棒 refusal×3 实证，本棒未再重试引擎）。

**一句话：RCD 就绪度 = 生产就绪（native+Python+export 通道全链通，native 测试/pytest/门禁/全量回归全绿）；A/B（n=12 全分辨率，零回落）：伪彩中位比 0.944（RCD 优于 AHD）、耗时中位比 0.673（native 反而快），判定「值得保留为选项」。**

---

## 1. 实现清单（逐文件）

### native（新增/修改）
| 文件 | 改动 | 为什么 |
| :--- | :--- | :--- |
| `src/pixo/render/native/src/rcd_demosaic_native.cpp`（新，~700 行） | RT `rcd_demosaic.cc` 核心**逐字移植** + `border_interpolate`（demosaic_algos.cc）整搬 + rt_math 垫片（SQR/LIM01/intp，intp 原文 `a*(b-c)+c`）+ array2D 薄垫片（`Array2DView`，仅 `[row][col]` 语义） | 数值保真（设计 §0 整文件搬定案）；文件头保留 RT 原版权块 + 来源标注（rcd_demosaic.cc / demosaic_algos.cc / rt_math.h @ 6c4cb59, GPLv3）+ 五条适配说明 |
| `src/pixo/render/native/src/rcd.h`（新） | C ABI 声明 `PixoRenderDemosaicRCD(mosaic, out, w, h, pattern[4])` | 对齐 decode.h 房式；状态码复用 abi.h 既有枚举 |
| `CMakeLists.txt` | `add_library` 加 `src/rcd_demosaic_native.cpp` | OpenMP 已是**目标级**（`PIXO_RENDER_NATIVE_OPENMP=ON` + `OpenMP::OpenMP_CXX`，CMakeCache 实证 `-fopenmp` libgomp 4.5），新文件自动继承——设计「为新文件开 -fopenmp」由既有管线满足，无需逐文件 flag |
| `tests/test_main.cpp` | `TestRcdDemosaic()`：四相位（RGGB/BGGR/GRBG/GBRG）恒场 0.5（无 NaN+全图 0.5）、垂直渐变单调保序+恢复误差<0.02、彩色垂直边伪彩 RCD<双线性基线（chroma 高频能量，边带）、确定性金样本（双跑 memcmp 逐位 + 5 个 hex 位型钉样本）、错误路径（非法布局×3/尺寸<19→FallbackRequested；空指针/非正尺寸→InvalidArgs） | 设计 §3.1/3.2；金样本先红后钉（首轮打印 actual bits → 钉入 → 复跑绿） |

适配要点（设计 M2/M3 定夺的落地点）：
- 归一化归 Python：native 装载处 `LIM01(mosaic)`（RT `/65536` 移除），输出处 `max(0, rgb01)`（RT `×65536` 移除）——算法全程与 RT 同在 [0,1] 域，其余逐字；
- pattern：入口 `pattern[4]` 布局码（0=R,1=G,2=B），native 侧校验恰 1R+2G+1B，非 RGBG → `FallbackRequested=1`（RT fallback igv 的等价回落门）；
- chunkSize 固定 2（RT `options.chunkSizeRCD` 缺省，rtgui/options.cc:526）；GUI/StopWatch/progress 剥离；
- **OpenMP/串行双构建位型一致**：run_tests.bat（OpenMP OFF）钉的金样本 5 位型与生产 DLL（OpenMP ON）ctypes 冒烟逐位 MATCH。

### Python（修改）
| 文件 | 改动 | 为什么 |
| :--- | :--- | :--- |
| `_native/__init__.py` | `PixoRenderDemosaicRCD` ctypes 注册（hasattr 可选门，旧 DLL 不受影响）+ `demosaic_rcd(mosaic, pattern) -> rgb\|None`（None=FallbackRequested；异常走 RuntimeError）；`__all__` 补条目 | 设计 §1.2；对齐 decode_cfa_half 封装风格 |
| `core/io.py` | decode_raw 的 `demosaic` 参数新增 `"RCD"` 取值（仅 `half_size=False` 生效）；`_rcd_mosaic_from_raw`（取数路径照 decode_cfa_half 既有实现 io.py:189-207：raw_image_visible/raw_pattern/color_desc/black_level_per_channel/white_level → (v−black)/(white−black) 归一化，2x2 黑电平周期铺满）；`_decode_raw_rcd`；`_apply_dcraw_flip`；失败/不支持→**静默回落 AHD** + record_degradation（source=`render.io.decode_raw.rcd`） | 设计 M3/M4；**观察项①**：(img, raw) 返回契约不变（RCD 分支同样 imread 返回 raw 对象）；**观察项②**：未知值维持 `.get(demosaic, AHD)` 静默口径，无新增抛错路径 |
| `web/export.py` | `_render_full_quality` 加显式 kwargs `demosaic="AHD"` 透传 decode_raw；ExportManager._run 读 `session.demosaic` 属性，非 "AHD" 才传参（旧调用面不变） | 设计 M1：独立通道，**不进 params 白名单**（照 region_masks 先例） |
| `web/session.py` | `RawPreviewSession.demosaic: str = "AHD"` 属性 | 通道载体（region_masks 同款） |
| `service/runtime.py` | `submit_export` 加可选 `demosaic`（None=不变；非 "AHD"/"RCD" → ValueError→400） | 请求体独立字段入口 |
| `service/app.py` | `POST /api/sessions/{id}/exports` body 读 `demosaic` 字段透传 | 同上 |
| `THIRD_PARTY_NOTICES.md` | §8 追加 R32-T1 RT 移植条目（文件清单+commit+日期+上游链接） | 设计 §2 GPL 合规 |

### 测试（新增/修改）
| 文件 | 改动 |
| :--- | :--- |
| `tests/unit/test_io_rcd.py`（新，15 用例） | (img,raw) 契约、RCD≠AHD（确认真走 native）、缺省 AHD 不变（postprocess+gamma(1,1)）、未知值静默 AHD 零降级事件、native 异常回落+降级事件、不支持回落+降级事件、half_size 忽略 RCD、X-Trans 6x6 回落、**dcraw flip 四态**（0/3/5/6——见 §2 坑 1）、export kwargs 透传、ExportManager 通道、session 缺省属性 |
| `tests/unit/test_region_masks_channel.py` | fake decode_raw lambda 补 `demosaic="AHD"` 形参（_render_full_quality 接口显式化的连带，行为不变） |

## 2. 踩坑记录

1. **portrait 方向缺失（A/B 实测抓出，非合成测试能预见的真 bug）**：rawpy postprocess（AHD 臂）缺省按 dcraw flip 码自动翻转输出，而 `raw_image_visible` 是传感器原始方向——flip=5 的 DSC_1319 首轮 A/B 直接两臂形状不匹配崩掉。修复：`_apply_dcraw_flip`（位语义 bit2=转置/bit1=flipud/bit0=fliplr，libraw 同序），并加 0/3/5/6 四态回归锁。注：**预览线 decode_cfa_half 无翻转处理（既有行为，portrait 预览疑似横竖颠倒）——预览线不动（设计 §5 非目标），建议登记后续轮**。
2. 2x2 黑电平广播：`(H,W) 与 (2,2)` 直接相减不广播，需 `np.tile` 按 Bayer 周期铺满。
3. 测试 spy 递归：monkeypatch `native.demosaic_rcd` 后 wrapper 内再调同名符号即自递归，须先捕获原引用。
4. CMake OpenMP：设计要求「为新文件开 -fopenmp」，实测既有目标级 OpenMP 管线（PIXO_RENDER_NATIVE_OPENMP 默认 ON）已覆盖，未加逐文件 flag（避免重复 flag）。
5. A/B 语料：R31 picklist 原始 NEF（K:/data/photo）本轮不可达（missing 48/48，外置盘），按预案改用 R31 转换件 DNG（同 pick 谱系，rawpy CFA 路径可用），子采样口径写死在 json（等步长 `idx_i=floor(i*48/12)`，同 `_r31_pick.py` 算法族）。

## 3. A/B 摘要（.artifacts/_r32_t1_ab.json，复算脚本 _r32_t1_ab.py）

- 语料：n=12 全分辨率（24MP 级，DSC_xxxx.dng），AHD vs RCD 双臂，热身 1 + 计时 2 取均值；**零回落**（12/12 无 fallback 事件）。
- **伪彩（边缘带色度高频能量比，fc_ratio_ratio = RCD/AHD）**：中位 **0.944**；12 张中 10 张 <1.0，最好 DSC_2716=0.010、DSC_2378=0.434；两张 >1（DSC_5278=1.95、DSC_5957=2.23，高反差场景 RCD 色度残余略高，逐张数据在 json）。
- **耗时**：中位比 **0.673**（mean AHD 2824ms vs RCD 2026ms——native OpenMP 并行快于 libraw 单线程 AHD），远低于 3x 门槛。
- 细节能量（detail_rms 比中位 0.923）与色彩一致性（ΔE512 mean 最大 0.287）无异常。
- 判定（design §1.3 双门槛）：**伪彩更低 且 耗时<3x → 值得保留为选项（不改默认，默认切换另议）**。
- 数据质量备注：DSC_5615 近平坦帧（chroma_hf 2e-6 / luma_hf 3e-5），其 fc 比值（6.7e10）为 0/0 型爆炸、无物理意义，两臂绝对值均噪声级；中位数对该离群稳健，原始数据按「口径写死」原则保留在 json 未修剪。

## 4. 门禁证据

- native 测试（串行构建）：`pixo_render_native_tests: all passed`（含 5 位型金样本）；
- 生产 DLL（OpenMP ON）ctypes 冒烟：同 5 位型逐位 MATCH（跨构建确定性）；
- pytest 新增面：test_io_rcd.py **15 passed**；
- 受影响面：test_region_masks_channel.py + test_decode_cache.py 等 34 passed；
- gate 金样本零漂移：**test_gate_golden.py 7 passed**；
- **全量回归（最终代码态）：tests 全量 `1732 passed, 12 skipped, 1 xfailed, 0 failed`（263s）**；
- 构建：build.bat 生产构建零告警通过，DLL 已拷贝至 `src/pixo/render/_native/`；
- 未 commit（队长检视后统一走流程）；未动 master。

## 5. 待队长/reviewer 关注

1. export 链 body→session→Manager 的三跳透传属薄胶水，仅 `_render_full_quality` kwargs 层有单测，Manager._run 层用轻量 stub 测过一例（test_export_manager_reads_session_attribute）；服务层 400 路径（非法 demosaic 值）未单测（submit_export 校验逻辑一行，检视可肉眼确认）。
2. 预览线 flip 缺失（既有）建议立后续项（见 §2.1）。
3. A/B 两张高反差场景（DSC_5278/5957）RCD 色度残余高于 AHD——是否可接受属产品判断，数据已留档。
