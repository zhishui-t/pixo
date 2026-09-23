# R15 stream-2 —— 预览会话掩码供给（打开预览 → 直接可调区域）

> dev-2 · 2026-09-08 · 状态：**完成，7 项新测试全绿（含真权重 e2e），零回归**

## 1. 方案选择与理由（指令候选 a/b/c → 选 c 混合，缺省关）

**自动懒触发 + env 显式开关（缺省关）**，触发点 = `GET /region`（region
面板打开时机）：
- 实测成本：`PIXO_SEGMENTER=multi` 真权重，512 级输入——**首次 segment
  17.70s**（208 个权重文件冷加载 + segformer 首推）、进程热后 **0.73s/次**。
  按队长裁决标准「<1s 建议默认开」：冷启远超阈值 → **缺省关**
  （`PIXO_REGION_SUPPLY=1` 显式开启）；常驻服务 + 热权重场景（0.73s）
  由运维开启。
- 不选 b) 纯手动端点：与「打开预览→直接可调区域」目标相悖（多一步手动）。
- 供给渲染走 `session.render(long_edge=512)`——复用 decode/tier 缓存，
  后续正常预览渲染零额外解码成本。
- mock segmenter 环境永不尝试（零掩码 + 不可用，R14 契约不变，不装可用）。

## 2. 实现（生命周期 / 状态联动 / 护栏）
- `service/runtime.py`：
  - `_ensure_session_region_masks(session)`：懒触发——门槛
    （PIXO_REGION_SUPPLY 开 + segmenter_type=="multi"）→ 512 级渲染 →
    segment(["face","sky","plant"]) → **Route B 注入
    `session.region_masks`**（segmenter 原样输出注入；uint8 0/255 由
    region_masks.py 适配器 /255 归一，float 原样——契约已备）；生命周期 =
    **每会话至多一次**（非 None 即已尝试，空 dict = 分割完成无掩码，不再
    重试），掩码缓存沿 session（重渲染不重分割；透传纪律保 stage 缓存命中）
  - 并发防重入：`_region_supply_lock`（并发 GET 单次分割）
  - 降级：分割异常 → 空 dict + warn（不炸状态端点，已尝试不再重试）
  - 状态 reason 扩展（R14 契约加宽不破坏）：`masks_not_injected`（供给
    未开/未尝试/mock 环境）/ `segmenter_no_masks`（供给已试、无区域掩码）
- `service/app.py`：`GET /region` 端点在返回状态前调供给（sync def 走
  FastAPI 线程池，不阻塞其他端点）；params patch 响应不触发供给（patch 快路径）
- `session.py` 未动（属性注入即可）；loop.py/region_adjust.py 未动（边界 ✓）

## 3. 测试（新增 7 项，`tests/integration/test_region_supply.py`）
| 测试 | 钉死语义 |
|---|---|
| supply_default_off | 缺省关：不尝试分割，reason=masks_not_injected |
| supply_lazy_once_then_cached | 开启后懒触发一次 → available+prompts；重复 GET 不重分割（calls==1）；uint8 原样注入 |
| supply_mock_segmenter_never_attempts | mock 环境永不尝试（region_masks 保持 None） |
| supply_empty_masks_reports_segmenter_no_masks | 空掩码 → reason 区分 |
| supply_failure_degrades_without_error | 分割异常降级不可用，不重试 |
| supply_then_patch_then_render_uses_masks | patch 不重分割，参数面落位 |
| real_weights_supply_e2e | 真权重+真 RAW：供给→available（真 prompts）→嵌套 patch→掩码区变暗（兼成本实测载体） |

## 4. 成本实测数据（本机，真权重）
| 项 | 数值 |
|---|---|
| multi 构造 | 0.00s（权重懒加载） |
| 首次 segment（512 级，含权重冷加载） | **17.70s** |
| 二次 segment（进程热） | **0.73s** |
| R15 e2e 供给全程（512 渲染+冷分割） | 22.49s（真 prompts=['face','plant','sky']） |
| 缺省开关 | **关**（17.7s ≫ 1s 裁决线；热态 0.73s 场景由 PIXO_REGION_SUPPLY=1 显式启用） |

## 5. 回归
- 全量单测：**1318 passed, 0 failed**；集成（not e2e）：**125 passed**
  （118 + 本文件 7）——R14 契约（GET /region 未开供给时语义）零破坏

## 6. 遗留 / 备注
1. 供给分割的输入图 = 渲染桩输出（`session.render(512)`），分割坐标系 =
   渲染最终帧（post-compose），与 F13 适配器契约同源 ✓。
2. 若后续量化「权重常驻服务占比」，可升级为「缺省开 + 后台预热线程」——
   本轮按实测数据保守取缺省关。
3. mock segmenter 的合成掩码语义（中央椭圆回退）不宜作为 region 控件的
   真实数据源——供给门禁死锁在 multi（如需 mock 演示态，另加显式
   demo 开关，未做）。

## 7. 复现命令
```
python -m pytest tests/integration/test_region_supply.py -q
PIXO_SEGMENTER=multi PIXO_REGION_SUPPLY=1 python -m pytest "tests/integration/test_region_supply.py::test_real_weights_supply_e2e" -q -s
python -m pytest tests/integration -q -m "not e2e"
```

---

## 8. P1 修复（tester B1：全零掩码被当有效注入，状态虚报 available=True）

### 修复内容（`service/runtime.py`）
- 注入前有效性判定 `_mask_has_signal(mask)`：逐 prompt 检查非零像素
  （uint8 0/255 与 float 0..1 两契约形态通用；空/全零/不可数值化 → 无信号）；
- 供给注入只保留**有信号的 prompt**（status.prompts 即真实可用面）；
  全零/空集 → **不注入**（region_masks={} + source="segmenter"）→
  `available=False + reason="segmenter_no_masks"`；
- **与异常降级路径区分**：分割异常 → source="segmenter_error" →
  `reason="segmenter_error"`（成功但全零 = segmenter_no_masks，两语义不再混）；
- 附带修复：runtime.py 补 `import numpy as np`（有效性判定初版漏 import 被
  判定函数自身 try/except 吞成恒 False——单测当场抓住后即修）。

### 测试更新
- `test_region_supply.py` +2：全零掩码不装可用（P1 回归钉死）/ 部分有效仅保留
  信号 prompt；异常降级用例补 `reason=="segmenter_error"` 断言；
  `test_real_weights_supply_e2e` 按 tester O1 建议翻转——该 RAW 对 segformer
  全零（实测覆盖率均 0）→ available=False + reason=segmenter_no_masks +
  patch 渲染逐位不变（B1 修复语义钉死）；渲染生效证据由合成掩码路径承载
  （Stub 用例 + tester 相位 D）。→ **9/9 passed**
- tester 资产 `_r15_supply_e2e.py` 相位 C 断言更新到修复后语义（check 数
  保持 15）：available=False + reason=segmenter_no_masks / 全零不注入
  （source=segmenter, masks={}）/ canonical 回读保留但响应 available=False /
  patch 渲染与基线逐位一致 / B1 证据检查反转为修复回归断言 →
  **四相位 e2e 15/15 passed**

### 复跑证据
```
$ python .artifacts/_r15_supply_e2e.py
R15 supply service e2e: 15/15 passed, 0 failed
$ python .artifacts/_r15_phaseC_diag.py
# region_status → available=False prompts=[]
# 2. 192 级 patch 前后: mean Δ=0.000000 逐位相同=True
# 4. 合成对照: 左半 mean Δ=12.437855   （region_adjust stage 可用性对照仍有效）
$ python -m pytest tests/unit tests/integration -q -m "not e2e"
1445 passed, 3 skipped, 1 xfailed, 0 failed
```
