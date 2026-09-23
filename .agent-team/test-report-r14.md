# R14 测试报告 —— M1 前端暴露（region 状态 API + RegionSection）前后端闭环

> tester 2026-09-07。被测版本：master @ 4a269a5 + 工作树 R14 未提交改动（7 modified + 4 新增，与 r14-stream-2/3 开发报告一致）。
> 开测前置：任务书（task-brief.md）、开发流报告（streams/r14-stream-2.md、r14-stream-3.md）齐全，准予开测。
> 测试资产（可重复执行）：`K:\work\project\pixo\.artifacts\_r14_service_e2e.py`、`K:\work\project\pixo\frontend\e2e\_r14_ui_contract.mjs`。

## 0. 结论一览

| 项 | 结果 |
|----|------|
| 后端 API 测试复跑（test_region_session_api.py） | **6/6 passed**（含真 RAW 渲染 e2e，未 skip） |
| 服务级 e2e（真实 uvicorn HTTP 闭环） | **13/13 passed** |
| 前端三件套 typecheck / build / test:unit | **全绿**（28/28 unit，build 5.38s） |
| 前端 e2e smoke（node e2e/smoke.mjs） | **8/8 passed** |
| 契约比对（client.ts ↔ GET /region schema，字段级+真实线路） | **字段/线路层一致；UI 消费层断链 → Bug B1（P1）**；另发现前置缺口 **Bug B2（P2，CORS）** |
| 全量回归 `python -m pytest tests -q -m "not e2e"` | **1515 passed, 5 skipped, 1 xfailed, 0 failed**（= R13 基线 1509 + R14 新增 6） |

**判定：后端交付与全量回归 GO；前端暴露的核心语义（available 置灰）在真实后端下 100% 失效（Bug B1），退 dev-3 修复后需回归本报告第 3.3 节脚本。**

---

## 1. 后端 API 测试复跑

```
$ python -m pytest tests/integration/test_region_session_api.py -v --tb=short
tests/integration/test_region_session_api.py::TestRegionStatusApi::test_region_status_not_injected PASSED
tests/integration/test_region_session_api.py::TestRegionStatusApi::test_region_status_available_after_route_b_injection PASSED
tests/integration/test_region_session_api.py::TestRegionStatusApi::test_params_patch_response_carries_region_status PASSED
tests/integration/test_region_session_api.py::TestRegionStatusApi::test_region_unknown_session_404 PASSED
tests/integration/test_region_session_api.py::TestRegionStatusApi::test_region_nested_patch_deep_merges PASSED
tests/integration/test_region_session_api.py::TestRegionPatchE2E::test_patch_nesting_canonical_readback_and_render_effect PASSED
======================== 6 passed, 1 warning in 24.33s ========================
```

RAW 语料 `K:/data/photo/0711/raw/DSC_5236.NEF`（28MB）可达，Route B e2e 未 skip。

## 2. 服务级 e2e —— 真实 uvicorn HTTP 闭环（非 TestClient）

脚本：`.artifacts/_r14_service_e2e.py`（uvicorn 线程起真实 service @ 127.0.0.1:8124，httpx 走真实 socket）。掩码注入按任务书授权：服务层无掩码注入入口，沿集成测试文件 Route B 方式直接设置 `session.region_masks`（F13 约定的 loop 分割通道注入点）。

```
$ python .artifacts/_r14_service_e2e.py
PASS  POST /api/photos → 201
PASS  POST /api/photos/{id}/sessions → 201
PASS  GET /region 未注入 → 200 且 available=False/prompts=[]/reason=masks_not_injected
PASS  GET /region 注入后 → available=True/prompts=['sky']/reason=None
PASS  GET /image gen=0 → 200 png16
PASS  PUT params 响应携带 region 节（available=True, prompts=['sky']）
PASS  PUT params canonical 回读 exposure=-0.5 且 enabled=True
PASS  PUT 后 GET /region 仍 available=True
PASS  GET /image gen=1 → 200
PASS  掩码区变暗（mean Δ < -0.005）  [Δ=-10.68213]
PASS  掩码区量级 ≈ 2^(-0.5/2.2) ±15%  [ratio=0.8532]  （期望 0.8542）
PASS  非掩码区（x≥128）逐位不变
PASS  GET /region 未知 session → 404
R14 service e2e: 13/13 passed, 0 failed
```

关键真实响应样例（png16 无损编码保证逐位断言成立）：
- 未注入：`{'session_id': '001ad9080a954b49', 'generation': 0, 'available': False, 'prompts': [], 'reason': 'masks_not_injected'}`
- 注入后：`{..., 'available': True, 'prompts': ['sky'], 'reason': None}`
- PUT region_adjust.regions.sky.exposure=-0.5 后 canonical 回读 `{'exposure': -0.5}`，渲染掩码区亮度比 0.8532 ≈ 2^(-0.5/2.2)=0.8542，对照区逐位不变。

**后端状态 API 语义闭环成立。**

## 3. 前端验证

### 3.1 三件套
```
$ npm run typecheck    → tsc --noEmit 零错误（exit 0）
$ npm run test:unit    → tests 28 / pass 28 / fail 0（17 regionSection 新用例 + 11 oklchScale）
$ npm run build        → tsc + vite build ✓ built in 5.38s（2556 modules）
```

### 3.2 smoke 复跑
```
$ node e2e/smoke.mjs   → Smoke passed: 8/8
```

### 3.3 跨端契约实测（本轮唯一空档的关闭尝试）——发现 Bug B1 / B2

脚本：`frontend/e2e/_r14_ui_contract.mjs`。环境：真实后端 `python -m pixo.service`（:8000，PYTHONPATH=src）+ `npm run dev`（:5173）+ Playwright(msedge)。真实 RAW 经 API 预置。

**实测证据（网络层抓包原文）：**

```
# 前端发出的 /region 请求（真实线路）:
  404  http://localhost:8000/api/sessions/demo-session/region
       → {"detail":"'session 不存在: demo-session'"}     ← 两次（StrictMode 双挂载）
# 滑杆操作后:
  PUT   http://localhost:8000/api/sessions/d7a4a72925b5449d/params
        body={"region_adjust":{"regions":{"sky":{"exposure":0}}},"__source":"user"}  ← 200
# 直接查后端该真实会话:
  GET /api/sessions/d7a4a72925b5449d/region
       → {"session_id":"d7a4a72925b5449d","generation":3,"available":false,
          "prompts":[],"reason":"masks_not_injected"}
# 同一时刻 UI 徽标: "掩码就绪 · 3 个区域"
```

R14 UI contract: 3/4 passed（"UI 徽标与真实后端状态一致性" FAIL，即 B1 的断言面）。

## 4. 前后端契约比对表（逐字段）

### 4.1 GET /api/sessions/{id}/region 响应

| 后端字段（runtime.py `_region_status_of`/`region_status`） | 后端类型/取值 | 前端 types.RegionMaskStatus | 判定 |
|----|----|----|----|
| `session_id` | str | 未声明 | 前端忽略附加字段，无害 |
| `generation` | int | 未声明 | 同上 |
| `available` | bool（=bool(prompts)） | `available: boolean` | 一致 |
| `prompts` | string[]（sorted，仅可用非空） | `prompts: string[]` | 一致 |
| `reason` | `null \| "masks_not_injected"` | `reason?: string \| null` | 一致 |

- URL：后端 `GET /api/sessions/{session_id}/region`（app.py:151）↔ 前端 `client.ts:47` `/api/sessions/${sessionId}/region` —— **队长对齐后的路径一致**（git diff 确认仅此单点改动）。
- 形状漂移吸收：`normalizeRegionMaskStatus`（regionAdjust.ts:140）对非对象/prompts 非数组/available 与 prompts 矛盾均有回退 —— 17 unit 用例覆盖。
- 404 语义：未知 session 双端一致（后端 404 + detail；前端 throw → api 层 catch）。
- **字段/线路层契约一致；断链在 sessionId 供给（见 B1），不在 schema。**

### 4.2 PUT params 响应 region 状态节

| 后端（runtime.py:348-354） | 前端 ParamsUpdateResult（types.ts:120-125） | 判定 |
|----|----|----|
| `{session_id, generation, params, canonical, region:{available,prompts,reason}}` | `{session_id, generation, params, canonical}` —— **未声明 region 节** | 前端忽略附加字段无害；观察项 O1 |

### 4.3 前端 → 后端 patch 形状（真实线路验证）

- 前端实测发出 `{"region_adjust":{"regions":{"sky":{"exposure":0}}},"__source":"user"}` → 后端 200，嵌套深合并、canonical 回读正确（服务级 e2e + 集成测试双证据）。**一致。**

## 5. 全量回归

```
$ python -m pytest tests -q -m "not e2e"
1515 passed, 5 skipped, 1 xfailed, 13 warnings in 182.33s (0:03:02)
```

- 对齐预期：R13 基线 1509 + R14 新增 6（test_region_session_api.py）= **1515 passed，0 failed**。
- 5 skipped / 1 xfailed 与 R13 基线形态一致（LLM env / RAW 守卫类，逐项语义同前轮）。

## 6. Bug 清单

### B1（P1，退 dev-3）：RegionSection 掩码状态查询用写死 `demo-session`，真实后端语义永远到不了 UI

- **现象**：后端在线 + 真实会话场景下，UI 徽标恒为「掩码就绪 · 3 个区域」（mock 数据 sky/face/plant），三滑杆可操作；而后端对真实会话返回 `available=false, reason="masks_not_injected"`。用户拖滑杆 → PUT 被接受（generation 递增）但无掩码渲染静默失效——**状态 API 设计要消灭的"滑杆调了静默失效"陷阱在真实后端下完整复活**。
- **证据**：第 3.3 节网络抓包原文 + 截图 `frontend/e2e/screenshots/r14_ui_contract.png`；复现脚本 `node e2e/_r14_ui_contract.mjs`（需 :8000 后端 + :5173 前端）。
- **定位流**：`RegionSection.tsx:42` `fetchRegionMaskStatus()` 无参调用 → `api/index.ts:110` `sid = getMockSessionId()`（恒 `'demo-session'`）→ `client.ts:47` GET → 后端 404 → `api/index.ts:117` catch 回退 `mockGetRegionMaskStatus()`（恒 available）。store 中明明持有真实 `sessionId`（useAppStore.ts:44），RegionSection 拿不到。
- **最小复现**：起后端+前端 → 预置照片 → 选中照片 → 调整 Tab → 看 region 徽标。
- **期望/实际**：期望徽标反映真实会话状态（不可用态：禁用+"运行分析后可用区域调整（masks_not_injected）"）；实际恒可用态 mock。
- **修复方向建议**（归 dev-3 定夺）：RegionSection 接收 store sessionId；后端在线且会话未建立/查询 404 时呈现不可用态，mock 回退仅限 `backendAvailable=false`。
- **回归要求**：修复后重跑 `_r14_ui_contract.mjs`，"UI 徽标与真实后端状态一致性"须 PASS。

### B2（P2，前置设施缺口，非 R14 引入，退队长定流）：vite dev ↔ pixo-service 浏览器级联调不可能（CORS）

- **现象**：`npm run dev`（:5173）打开的 UI 对 :8000 的一切 fetch 被 CORS 拦截 → `fetchPhotos` catch → `backendAvailable=false` → **整个前端永远 mock 模式**，README「配置 VITE_PIXO_API_URL 即连后端」在浏览器不可达。这也是队长指出"联调对齐后没有真实跨端请求过"的结构性根因。
- **证据**：`grep -rni "cors\|add_middleware" src/pixo/service/` 零命中；`curl -i -X OPTIONS http://localhost:8000/api/photos -H "Origin: http://localhost:5173" -H "Access-Control-Request-Method: GET"` → `405 Method Not Allowed`；GET 响应无 `Access-Control-Allow-Origin` 头；`vite.config.ts` 无 proxy、app.py 无 StaticFiles 挂载。
- **影响**：不阻塞后端 API 与契约本身（`--disable-web-security` 隔离后所有请求真实到达后端且语义正确）；阻塞"前端+后端"真实联调路径与 B1 的日常暴露。
- **修复方向建议**：后端加 CORSMiddleware（allow :5173）或 vite dev server 加 proxy——二选一，属基建/开发域，由队长仲裁归属。

### 观察项（非缺陷）

- O1：`ParamsUpdateResult` 未声明后端 PUT 响应新增的 `region` 节，前端未消费该数据源（RegionSection 仅 mount 时 GET 一次）。若后续要"每次 patch 后即时刷徽标"，该节是现成数据源。
- O2：本轮 UI 实测中滑杆 patch 提交值为 `exposure: 0`（滑杆中心位起步），形状契约已验证；数值域语义由 17 unit 用例覆盖。

## 7. 资产与复现命令汇总

| 资产 | 命令 |
|----|----|
| 后端定向 | `python -m pytest tests/integration/test_region_session_api.py -q` |
| 服务级 e2e | `python .artifacts/_r14_service_e2e.py`（自起 uvicorn :8124，依赖 K:/data/photo/0711 语料） |
| 前端三件套 | `cd frontend && npm run typecheck && npm run test:unit && npm run build` |
| smoke | `cd frontend && node e2e/smoke.mjs`（需 :5173 dev server） |
| 跨端契约 | 起 :8000（`PYTHONPATH=src python -m pixo.service`）+ :5173 → `cd frontend && node e2e/_r14_ui_contract.mjs` |
| 全量回归 | `python -m pytest tests -q -m "not e2e"` |
