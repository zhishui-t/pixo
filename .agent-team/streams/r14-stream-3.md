# streams/r14-stream-3.md — dev-3 · 前端 Region 控件（M1 前端暴露）

> 2026-09-07 交付。任务：RegionSection（AdjustmentsPanel 内新节）+ 双态渲染断言。

## 做了什么

### 1. RegionSection 组件（`frontend/src/components/RegionSection.tsx`）
- 掩码状态经 api 适配位获取（useEffect + alive 竞态保护，沿 AdjustmentsPanel
  health() 模式）。
- **可用态**：prompt 胶囊选择（SegmentedControl，单区域时降级为 Badge 静态展示）
  + 三滑杆（exposure EV ±2 / saturation ±1 / warmth ±1）+ 状态徽标
  "掩码就绪 · N 个区域"。
- **不可用态**：三滑杆以 `locked` 渲染（禁用 + 半透明，SliderParam 既有语义）
  + 灰徽标 "区域掩码不可用" + 提示文案 "运行分析后可用区域调整"（附状态 API
  reason）——杜绝静默失效。
- 滑杆值经 **oklchScale 同款 γ=1.6 感知均匀传递**（13.1 惯例）：有符号推广，
  位置 0.5 = 0（不调整档）且中心附近分辨率最高（小幅微调是区域调整主场景）；
  NumberInput/提交值恒为参数域原值，后端契约不做换算。
- patch 形态 `{region_adjust:{regions:{<prompt>:{<param>:value}}}}`（PUT 深合并：
  仅提交被改动的 prompt/参数键）；提交前按滑杆域钳制（防触发后端 _regions
  ValueError）。

### 2. 纯函数模块（`frontend/src/components/regionAdjust.ts`，hslBands.ts 先例）
逻辑与 JSX 分离以便 node --test 直测（文件名 regionAdjust 避免与
RegionSection.tsx 大小写碰撞——Windows 不分区大小写，TS1261 实测）：
- `REGION_SLIDER_DEFS`：三滑杆域定义（后端 `_regions` 白名单镜像，±2/±1/±1）；
- `signedPerceptualToSlider/FromSlider`：oklchScale γ 幂函数的有符号推广
  （指数取 1/γ 使中心（0=不调整）分辨率最高；端点=min/max；精确互逆）；
- `readRegionAdjustment`：canonical 回读（含 decide 规则/卡建议写入值——来源
  无关同面渲染），数值化 + 白名单过滤 + 坏形状/非有限值回退 0（后端缺省语义）；
- `buildRegionPatch`：patch 构造 + 钳制；
- `normalizeRegionMaskStatus` / `maskStatusToUi`：状态 API 形状漂移吸收 +
  双态 UI 渲染模型（enabled/prompts/badgeText/hint/reason）。
- γ 常量与 oklchScale C_SLIDER_GAMMA 的同源关系**由测试钉死相等**
  （node 类型剥离要求显式 .ts 后缀、tsc bundler 解析禁止之，二者互斥——
  单源漂移防护放测试层，测试断言 `C_SLIDER_GAMMA === 1.6` 且传递函数幂律
  用同一常数）。

### 3. types.ts 补类型（`frontend/src/types.ts`）
- `RegionMaskStatus`（available + prompts + reason，dev-2 契约面）；
- `RegionAdjustment`（exposure/saturation/warmth 可选数值）；
- `ParamPatch.region_adjust?: { regions?: Record<string, RegionAdjustment> }`
  （PUT 深合并语义注释在类型上）。

### 4. api 适配位（端点以 dev-2 实施为准）
- `client.ts::getRegionMasks(sessionId)`：GET `/api/sessions/{id}/region-masks`
  ——**唯一对齐点**，dev-2 端点落地后路径/字段名变化只改此处；
- `api/index.ts::fetchRegionMaskStatus()`：后端优先、未实施（404）/离线回退
  mock；**不触碰 backendAvailable 全局信号**（子端点缺失 ≠ 后端不在线）；
- `api/mock.ts::mockGetRegionMaskStatus()`：恒 available
  （['sky','face','plant']）——离线开发态不呈现禁用面。

### 5. mock 深合并修复（`api/mock.ts`）
原 mockPatchParams 仅 stage 级浅合并——region_adjust.regions 的 prompt 子键
会被整桶替换（第二张区域的 patch 抹掉第一张）。改为**递归深合并**
（plain object 逐级合流；数组如 hsl.bands 与标量保持整值替换），对齐后端
PUT params 深合并语义。store 无需改动（patchProjectParam 透传 ParamPatch）。

### 6. AdjustmentsPanel 接线
新增"区域调整"手风琴节（默认展开，basic 之后 curve 之前），传入
params + patch（边界处类型收窄：ParamPatch ⇄ Record 双向 cast）。

## 双态渲染断言（`frontend/tests/regionSection.test.mjs`，17 用例，oklchScale
.test.mjs 同款 node:test + assert/strict 模式）
- **可用态**：maskStatusToUi → enabled=true / prompts 直出 / "掩码就绪 · 3 个
  区域"；mock 状态恒 available；
- **不可用态**：available=false、prompts 空、available 与 prompts 矛盾、形状
  漂移（null/undefined/字符串/数值）六种输入 → enabled=false + "运行分析后
  可用区域调整" 提示 + reason 透传文案；
- 回读三态：canonical 值直读 / decide 写入值来源无关同面 / 容错回 0；
- patch：精确形状 + 越界钳制 + 白名单镜像；
- 感知传递：γ=1.6 同源断言 / 锚点（0.5→0，端点→满量纲）/ 中心高分辨率
  （|v(0.55)|=0.050 < 线性 0.2）/ 双向互逆网格 1e-9 / 单调扫描；
- mock：prompt 级累积深合并 + 恒可用。

## 改了哪些文件
| 文件 | 改动 |
|----|----|
| `frontend/src/components/RegionSection.tsx` | **新增** 组件 |
| `frontend/src/components/regionAdjust.ts` | **新增** 纯函数模块 |
| `frontend/src/components/AdjustmentsPanel.tsx` | 接线新节 + import |
| `frontend/src/types.ts` | RegionMaskStatus / RegionAdjustment / ParamPatch.region_adjust |
| `frontend/src/api/client.ts` | getRegionMasks 适配位 |
| `frontend/src/api/index.ts` | fetchRegionMaskStatus（mock 兜底） |
| `frontend/src/api/mock.ts` | mockGetRegionMaskStatus + 递归深合并 |
| `frontend/tests/regionSection.test.mjs` | **新增** 17 用例 |

## 如何验证（命令 + 输出摘要）
```
npm run typecheck   → tsc --noEmit 零错误
npm run test:unit   → pass 28 / fail 0（17 regionSection 新用例 + 11 oklchScale 既有）
npm run build       → tsc --noEmit + vite build ✓ built in 12.36s
```

## 遗留问题
1. 状态 API 端点未实施（dev-2 并行中）：`client.getRegionMasks` 当前 404 →
   回退 mock；dev-2 落地后仅需对齐 client.ts 单点（路径/字段名），消费面不动。
2. 不可用态当前以"禁用 + 提示"呈现；若产品后续要"运行分析"动作按钮，
   需接 analyze 触发端点（超本批范围）。
3. warmth 三滑杆（-1~1）按后端 warmth 批口径预留；若 warmth 量纲调整
   （如改 mired），仅需改 REGION_SLIDER_DEFS 常量表。
4. 本轮未 commit（提交策略归队长）。

---

## P1/P2 修复批（tester test-report-r14.md B1/B2，2026-09-07）

### B1（P1）UI 消费层断链 —— 已修
- **真实会话 id**：RegionSection 直读 store `sessionId`（与照片/参数请求同源），
  `fetchRegionMaskStatus(sessionId)`；`sessionId=null`（未 ensureSession）→
  **未激活态**（reason=`session_not_ready`，提示"会话未建立…"）——不再装可用。
  sessionId 变化（首次 patch 建 会话）自动重查。
- **404/mock 兜底收紧**（`api/index.ts::fetchRegionMaskStatus` 重写）：
  仅 `backendAvailable === false`（真离线）走 mock 恒可用（唯一装可用分支）；
  后端在线但 404（会话不存在/过期）→ 显式错误态 `session_not_found`；
  其余失败（网络/5xx/端点未实施）→ 显式错误态 `fetch_failed`——两种均不回退
  mock。backendAvailable 全局信号不被本函数修改（子端点失败 ≠ 后端不在线）。
- **显式错误态 + 重试**：不可用态渲染"重试"按钮（nonce 触发重查真实会话）；
  reason 机器码 → 可行动文案映射（`regionAdjust.ts::regionReasonText`）：
  masks_not_injected → "运行分析后可用区域调整"、session_not_found → "会话已
  失效：将随下次操作自动重建"、fetch_failed → "…可点击重试"、未知码 → 通用
  文案+原因码透传（不吞诊断信息）。
- **配套**：`client.ts` 新增 `PixoApiError`（带 status——api 层区分 404 与其他
  失败的唯一依据）；不可用态区域滑杆不渲染（禁用态无静默操作面）+ 不可用期间
  零 region_adjust PUT（不静默提交无效调整）。
- **复跑回归**（tester 要求面）——`node e2e/_r14_ui_contract.mjs`（脚本时序按
  修复后语义更新：会话由【全局曝光】滑杆交互创建，region 节随 sessionId 重查）：
  ```
  PASS  会话未建立时零 /region 请求（B1: 不触达状态面，无 mock 兜底）
  PASS  会话未建立时区域滑杆不渲染（禁用态无静默操作面）
  PASS  会话建立后 /region 用真实 sid 重查（B1 断链回归面）  ← 全程零 demo-session
  PASS  掩码不可用期间零 region_adjust PUT（不静默提交无效调整）
  PASS  UI 徽标与真实后端状态一致性  ← 后端 available=false/masks_not_injected
                                    ↔ UI 徽标"区域掩码不可用"（一致）
  R14 UI contract: 5/5 passed, 0 failed
  ```
  真实线路证据：`GET http://localhost:5173/api/sessions/2fbd75cb…/region →
  {"available":false,"prompts":[],"reason":"masks_not_injected"}`，UI 徽标同步
  不可用——tester 抓包中的"404(demo-session)→mock 恒可用"断链已关闭。

### B2（P2）CORS 前置缺口 —— 已修（vite proxy 方案）
- 后端默认端口确认：`service/__main__.py` `uvicorn.run(port=8000)`。
- `frontend/vite.config.ts`：dev server 加 `proxy: {'/api': {target:
  'http://127.0.0.1:8000', changeOrigin: true}}`（注释注明端口变化时仅改此处）。
- `client.ts::API_BASE` 缺省 `http://localhost:8000` → **''（同源相对路径）**：
  dev 请求走 vite proxy 免 CORS；`VITE_PIXO_API_URL` 显式覆盖保留（直连场景）。
- **跨端请求验证**：`curl http://localhost:5173/api/health` → 200（真实后端
  payload 经 proxy 返回）；契约脚本全程走 :5173/api/* 代理线路，PUT params 与
  GET region 真实到达后端（后端日志可见 uvicorn 请求）。

### 修复批验证（命令 + 输出摘要）
```
npm run typecheck   → 零错误
npm run test:unit   → pass 30 / fail 0（+2：B1 reason 映射与未知码透传）
npm run build       → ✓ built in 5.27s
node e2e/smoke.mjs  → Smoke passed: 8/8
node e2e/_r14_ui_contract.mjs → 5/5 passed（含一致性断言）
curl :5173/api/health → 200（B2 代理线路）
```

### 改了哪些文件（修复批增量）
| 文件 | 改动 |
|----|----|
| `frontend/src/api/client.ts` | PixoApiError（带 status）+ API_BASE 缺省改同源（proxy） |
| `frontend/src/api/index.ts` | fetchRegionMaskStatus 重写（真离线 mock/无会话未激活/404+失败显式错误态） |
| `frontend/src/components/regionAdjust.ts` | REASON_TEXT 映射 + regionReasonText（已知码可行动文案，未知码透传） |
| `frontend/src/components/RegionSection.tsx` | store sessionId 接入 + sessionId/retry 依赖重查 + 重试按钮 |
| `frontend/vite.config.ts` | dev proxy '/api' → 127.0.0.1:8000 |
| `frontend/e2e/_r14_ui_contract.mjs` | 时序更新为修复后语义（全局滑杆建会话；新增零请求/滑杆不渲染/零 region PUT 三断言；一致性断言保持） |
| `frontend/tests/regionSection.test.mjs` | +2 用例（reason 映射/未知码透传） |

### 遗留
1. O1（tester 观察项）未动：PUT 响应新增的 region 节可作为"patch 后即时刷
   徽标"的现成数据源（当前重查靠 sessionId 变化 + 手动重试）。
2. 掩码可用态（available=true）的浏览器级验证需 Route B 注入（服务无注入
   端点）——tester service e2e 已在 python 侧覆盖该语义；UI 侧可用态渲染由
   unit 的 maskStatusToUi 可用态断言覆盖。

---

## R17 收尾打磨 —— 前端 reason 矩阵联动（segmenter 四码，2026-09-08）

### 做了什么
1. **reason 矩阵补齐**（`regionAdjust.ts::REASON_TEXT`，与 runtime.py
   `_region_status_of` R16 四分对齐）：
   - `segmenter_warming` → "模型加载中，稍候自动重试" + **自动重查**；
   - `segmenter_no_masks` → "此图未检出可调区域"（分割成功但掩码全零，如实呈现）；
   - `segmenter_error` → "分割服务异常，可点击重试"（手动重试）；
   - `masks_not_injected` 沿既有文案不动。
2. **warming 自动重试策略**（纯函数，node --test 直测）：
   `warmingRetryDelayMs(retryCount)` = 2000ms 固定间隔（无抖动——锁死不闪断），
   ≥`WARMING_AUTO_RETRY_MAX`(5) 返回 null（停止自动，转手动重试按钮，
   避免无限轮询打后端）。
3. **RegionSection 接线（锁死不闪断）**：
   - warming 时按策略 setTimeout 递增 retryNonce → 复用既有查询 effect 静默
     重查；**不触碰 selected/徽标结构**（selected 仅在 null 时落值，重查不重置）；
   - hint 后缀 `（n/5）` 仅在每次重查发生时更新，文案主体全程恒定；
   - 离开 warming 或换会话即重置计数；手动重试按钮在 warming 自动期隐藏、
     封顶后显示（`showManualRetry` 纯函数钉死）。
4. **e2e 契约脚本同步**：脚本无 segmenter 码硬断言（warming 需 in-process
   注入，e2e 不强触达——该语义由 unit 矩阵覆盖）；补 reason 联调观测 echo。
5. 后端 reason 语义核对（只读 runtime.py `_region_status_of`）：四码名与
   R16 注释逐一对齐后才落文案。

### 验证（命令 + 输出摘要）
```
npm run test:unit   → pass 34 / fail 0（+6：四码文案/固定间隔封顶/手动重试
                      可见性/UI 文案矩阵同源/既有码不回归）
npm run typecheck   → tsc --noEmit 零错误
npm run build       → ✓ built in 5.95s
node e2e/_r14_ui_contract.mjs → 5/5 passed（reason=masks_not_injected 一致性
  断言不受影响；+reason 观测 echo）
```

### 改了哪些文件
| 文件 | 改动 |
|----|----|
| `frontend/src/components/regionAdjust.ts` | REASON_TEXT 三新码 + WARMING_* 常量 + warmingRetryDelayMs + showManualRetry |
| `frontend/src/components/RegionSection.tsx` | warmingAttempts 状态 + 自动重查 effect + 计数后缀 + 手动重试门控 |
| `frontend/tests/regionSection.test.mjs` | +6 用例（34 总） |
| `frontend/e2e/_r14_ui_contract.mjs` | reason 观测 echo（无断言语义变化） |

### 遗留
- warming 自动重查封顶（5 次/10 秒）后仅手动重试；若后端预热可能超 10 秒，
  需调 `WARMING_AUTO_RETRY_MAX`/`WARMING_RETRY_DELAY_MS` 常量（单点可调）。
- 本轮未 commit（提交策略归队长）。
