# R16 stream-2 —— segmenter 启动预热（供给冷启 17.7s 优化）

> dev-2 · 2026-09-08 · 状态：**完成，7 项新测试全绿（含真权重 e2e），零回归**

## 1. 预热基建现状核查（任务第 1 步）
- grep 全仓 warmup/预热：**无 segmenter 预热的既有实现**（N1a 时代未落地）；
  唯一预热基建 = t67 评分器（`vision/aesthetic.py` `PIXO_SCORER_WARMUP`
  缺省开 + `_warmup_disabled` 解析 + `service/app.py` lifespan
  `scorer_warmup_lifespan` 阻塞式预热 + health_info 暴露）→ 新建沿其
  设计/命名惯例。

## 2. 实现
### 2.1 `service/runtime.py`
- env `PIXO_SEGMENTER_WARMUP`：沿 scorer 惯例（"0/false/off/no" 关，
  **缺省开**）+ `_segmenter_warmup_enabled()`
- `warm_segmenter()`：真预热（multi 后端加载 + 64×48 小图首推理，prompts
  覆盖 segformer+rfdetr 两后端）——**非 daemon 阻塞语义的幂等方法**，
  由 lifespan 以 daemon 线程调用；状态机 pending→warming→done|skipped|
  failed 写 `segmenter_warmup_info`（health 暴露，沿 scorer health_info）
- 推理锁 `_segmenter_infer_lock`：预热与供给的 segment 调用互斥
  （multi 后端懒加载非线程安全，并发首推理会重复加载权重）
- 门控：env 关 → skipped(env_off)；mock segmenter → skipped
  （segmenter=mock，无权重可预热）；NC 门控经 multi 常规路由同源满足
  （PIXO_ALLOW_RESTRICTED 未放行时受限后端不在路由表，实测预热后端
  ⊆ {rfdetr}）
- `health()` 增加 `segmenter.warmup` 节（status/duration_s/prompts/backends）
- **供给衔接（R15 供给区仅此一处动）**：`_ensure_session_region_masks`
  的 segment 调用套推理锁

### 2.2 非阻塞语义（关键设计裁定）
预热持推理锁期间到达的 `GET /region` **立即返回**
`reason="segmenter_warming"`（不推理不阻塞），UI 稍后重查即热态供给——
v1 设计为"供给阻塞等待获锁"被实测否决（预热中 GET /region 阻塞 25s，
违反"预热中请求不阻塞"），已改非阻塞。锁释放后重查供给热态执行
（实测 2.85s 内含 512 渲染+热分割+有效性判定）。

### 2.3 `service/app.py` lifespan
scorer 阻塞式预热保持不变（其预热快）；segmenter 预热追加为**后台
daemon 线程**（不 join、不挡 lifespan 完成——服务立即就绪，预热在后台
吸收冷启）。`__main__` 零改动（lifespan 随 uvicorn.run(app) 生效）。

## 3. 成本实测数据（本机，真权重 + 0711 RAW）
| 项 | 数值 |
|---|---|
| 预热耗时（后台线程全程，R16 e2e） | **16.42s / 15.58s**（两轮实测，波动=磁盘/权重加载） |
| 预热后首供给（GET /region 含 512 渲染+热分割+注入） | **2.85s**（对照 R15 冷启 17.70s） |
| NC 门控 | 预热后端 ⊆ {segformer, rfdetr}（缺省未放行受限后端）✓ |
| mock 环境 | skipped（segmenter=mock），行为=R14 语义零掩码+不可用 |

## 4. 测试（新增 7 项，`tests/integration/test_segmenter_warmup.py`）
mock 跳过+health 暴露 / env 四值关 / multi done+幂等（不重推理）/
失败→failed / **预热持锁期间供给非阻塞（segmenter_warming）+ 锁释放后
热态执行** / health 暴露 / 真权重 e2e（预热吸收冷启+预热中不阻塞+
首供给秒级+NC 门控+patch 渲染逐位不变）

## 5. 回归
- 全量单测：**1319 passed, 0 failed**；集成（not e2e）：**134 passed**
- R15 `test_region_supply.py` 9/9 不回归（供给语义加宽：新增
  segmenter_warming 中间态，原 reason 两值保持）

## 6. 遗留 / 备注
1. segmenter_warming 态的 UI 行为（轮询间隔/置灰文案）归前端（R14 契约
   reason 字段已备）。
2. 预热线程 daemon=True：服务退出时预热中断无清理（权重加载可安全中断，
   下次启动重预热）。
3. `measure_session` 的 segment 调用未套推理锁（历史路径，测量与预热并发
   理论上可能重复加载权重——发生窗极窄且测量为既有行为，未动；如需收敛
   归 loop/service 域另案）。

## 7. 复现命令
```
python -m pytest tests/integration/test_segmenter_warmup.py -q -s   # 含成本打点
python -m pytest tests/integration/test_region_supply.py -q         # R15 不回归
python -m pytest tests/integration -q -m "not e2e"
```
