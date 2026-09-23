# R14 stream-2 —— region 状态 API + patch 嵌套确认（M1 前端暴露·后端）

> dev-2 · 2026-09-08 · 状态：**完成，6 项新测试全绿，零回归**

## 1. 方案选型（掩码状态暴露）与理由

采用「**专用 GET 端点 + params patch 响应带状态节**」双面方案：
- `GET /api/sessions/{id}/region`（新增）：region 面板打开时的一次性感知；
- `PUT /api/sessions/{id}/params` 响应追加 `region` 节：每次 patch 后 UI
  即时感知（滑杆置灰逻辑的数据源）。
- **不选 canonical 注入**：canonical_params 直接喂
  `build_default_pipeline(params=canonical)`（export 全质量线），注入非
  stage 键会污染渲染参数面——状态元数据与渲染参数面分离。
- 原因语义：`available=False` 且 `reason="masks_not_injected"`（纯预览
  会话无 loop 分割通道注入 `session.region_masks`——F13 Route B 属性）。

## 2. 改了哪些文件
- `src/pixo/service/runtime.py`：`update_params` 响应追加 `region` 节 +
  `_region_status_of(session)`（available/prompts/reason）+
  `region_status(session_id)` 公开查询（含 session_id/generation）
- `src/pixo/service/app.py`：新增 `GET /api/sessions/{session_id}/region`
  （404 语义与既有端点一致）
- `tests/integration/test_region_session_api.py`：新增（6 测试）

## 3. 测试与验证证据

### API 形状（FakeSession，4 项）
- 未注入：`GET /region` → `available=False, prompts=[], reason="masks_not_injected"`
- Route B 注入（`session.region_masks={"sky":…, "face":…}`）→
  `available=True, prompts=["face","sky"]`（排序稳定）, reason=None
- PUT params 响应携带 `region` 节；未知 session 404

### patch 嵌套闭环 + preview e2e（真 RawPreviewSession 渲染，2 项）
- 语料：`K:/data/photo/0711/raw/DSC_5236.NEF`（不可达自动 skip）
- Route B 注入左半图掩码 → `update_params({"region_adjust": {"enabled":
  True, "regions": {"sky": {"exposure": -0.5}}}})`：
  - canonical 回读：`region_adjust.regions.sky.exposure == -0.5` ✓
    （嵌套路径深合并）
  - `region.available=True, prompts=["sky"]` ✓
  - 渲染生效：掩码区（左内）Δmean<0 且亮度比 ≈ `2^(-0.5/2.2)`（±15%）✓；
    非掩码区（右远端 x≥128）**逐位不变** ✓
- 调参注记：对照区取 x≥128——掩码边界 x=96 的羽化过渡带实测至 ~x=107
  （region_masks 适配器入口羽化 + stage 二次羽化叠加）
- 配套保真修复：本文件 FakeSession.update_params 改递归深合并（镜像
  RawPreviewSession._deep_merge 语义，原浅合并会让嵌套 patch 互相覆盖、
  无法表达被测行为）

### 回归
- 全量单测：**1318 passed, 3 skipped, 1 xfailed, 0 failed**
- 集成（not e2e）：**118 passed**（112 + 本文件 6），既有 service API
  断言不受响应新增 region 节影响（无响应键集合钉死）

## 4. 遗留 / 备注
1. `reason` 目前单值 `masks_not_injected`；loop 分割链接入后的
   "分割未运行/无显著区域" 细分原因等接入时扩展（字段已留）。
2. 掩码可用后 region_adjust 是否 enabled 属用户参数面（不在状态节强绑）；
   前端按 `available` 置灰、按 canonical.region_adjust 回显当前值。
3. e2e 依赖本机 RAW 语料（0711），不可达环境自动 skip（与
   test_huesat_oklch 同守卫惯例）。

## 5. 复现命令
```
python -m pytest tests/integration/test_region_session_api.py -q
python -m pytest tests/integration -q -m "not e2e"
python -m pytest tests/unit -q
```
