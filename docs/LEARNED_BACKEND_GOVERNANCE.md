# Pixo 学习后端治理约定（LEARNED BACKEND GOVERNANCE）

> 状态：v1（2026-09-04，阶段三 t42 固化）。
> 上游：`docs/OWN_PIPELINE_STAGE3_DESIGN.md` §1（治理框架四门禁固化）。
> 红线：学习组件**默认关**；torch/权重只进 `scripts/` 与 vision 栈隔离层；
> 权重不入仓（manifest 登记）。

本文档把 2026-08 以来形成的四个治理模式固化为可复用约定：任何学习型后端
（torch/transformers 权重推理、学习型估计器等）接入 pixo 前必须逐门通过。
门禁是测试固化的（不是文书约定），新组件照 checklist 自查即可。

---

## 1. env opt-in 统一约定（PIXO_* 惯例）

### 1.1 前缀与命名

- 一律 `PIXO_` 前缀（与 `calibration_store.resolve_repo_root`、vision 各后端
  既有用法同源）；全大写 + 下划线。
- 命名按语义分三类，**新 env 必须归入其一**：

| 类别 | 模式 | 既有实例 | 缺省语义 |
|---|---|---|---|
| 开关（opt-in） | `PIXO_<组件>_ENABLED` | `PIXO_GSAM_ENABLED` | **缺省关**（"0"）；真值集 `{"1","true","on","yes"}`（`strip().lower()` 后比对） |
| 许可门 | `PIXO_ALLOW_RESTRICTED` | 同名 | 仅 `== "1"` 放行 restricted 许可后端注册进路由 |
| 选择/覆写 | `PIXO_<组件>_MODEL` / `PIXO_<维度>` | `PIXO_SEGMENTER`（缺省 `"mock"`）、`PIXO_SAPIENS_MODEL`、`PIXO_AESTHETIC_MODEL`、`PIXO_FAIRFACE_MODEL`、`PIXO_GSAM_SAM` | 缺省取**安全值**（mock/默认权重），覆写仅换实现不改变默认关纪律 |
| 路径/资源覆写 | `PIXO_<对象>_DIR` / `PIXO_<对象>_ROOT` | `PIXO_MODEL_LICENSES`、`PIXO_CONFIG_ROOT`、`PIXO_DATA_ROOT`、`PIXO_RENDER_LUT_DIR`、`PIXO_DECODE_CACHE_MB`、`PIXO_SCORER_WARMUP` | 缺省仓库内约定位置；主要供测试隔离与多环境部署 |

### 1.2 缺省关语义（三连带）

`PIXO_<X>_ENABLED` 未设置时必须同时满足：

1. **不加载**——组件不注册/不实例化（如 multi_router 仅 `PIXO_ALLOW_RESTRICTED=1`
   时注册 restricted 后端；gsam `enabled()` 缺省 False 直接短路）；
2. **不下载**——不触发权重自动下载（GB 级权重只允许在显式 opt-in 后首用下载）；
3. **不 import**——重依赖（torch/transformers）保持在 adapter 层懒 import，
   关态下零 import（import 隔离门禁的检验对象）。

### 1.3 测试如何覆盖关态

- **关态是基线**：全量 pytest 不设任何 `PIXO_*` 开关运行（CI 无 env 即关态）——
  任何在 import 期/收集期读取开关的代码都会被全量绿反证。
- 显式关态用例：`monkeypatch.delenv("PIXO_X_ENABLED", raising=False)` 后断言
  组件缺席（参照 `test_vision_router_semantics.py` 的 `PIXO_MODEL_LICENSES`
  delenv 用法）。
- 开态用例：需真实权重的 opt-in 后端走 `e2e`/`gate_e2e` marker（无数据 skip），
  **不进默认全量**；DI 注入（如 `chat_client`）优先于 env，便于单测伪后端。

---

## 2. 四门禁 checklist（新学习组件逐门自查）

| # | 门禁 | 强制点（测试固化） | 合规动作 |
|---|---|---|---|
| 1 | **许可白名单** | `tests/unit/test_model_licenses.py`：`ALLOWED_LICENSES = {MIT, Apache-2.0}`；非白名单 license 条目 `publishable` 必须显式 `false`，`publishable=true` 即硬拒；`publishable=true ⇒ usage=可再分发档` 口径自洽 | 新模型先登记 `model_licenses.json`（含 `publishable` 布尔）；NC/需审核 license 一律 `publishable: false`，仅 `PIXO_ALLOW_RESTRICTED=1` 可用于内部研发 |
| 2 | **import 隔离** | `tests/unit/test_learned_isolation.py`：`src/pixo/render/learned/` 内零 `torch/torchvision/transformers`（AST 全量含懒 import；目录未建则 skip 预铺）；`test_vision_segmenter.py::test_heavy_imports_isolated_in_adapters` 管 vision 侧 | torch/transformers 只进 `scripts/` 与 vision adapter 隔离层；`render/learned/` 若落地只许 numpy/cv2，需重依赖时移出该目录或经 QA 评审立豁免清单 |
| 3 | **env opt-in** | 本文档 §1 约定 + 全量 pytest 关态基线（§1.3） | 新开关按 §1.1 三类命名；缺省关三连带（不加载/不下载/不 import）；关态用例进单测 |
| 4 | **三证据转正** | `docs/LEARNED_BACKEND_PROMOTION.md` 模板；缺省关直到三证据齐 | 评估原型只产报告不接运行时；转正按模板逐证据填写并评审签核 |

## 3. 新学习组件接入 SOP（顺序执行）

```
登记许可（门1: model_licenses.json, publishable 如实标注）
  → 实现隔离（门2: scripts/ 原型或 adapter 层, learned/ 只许 numpy/cv2）
  → env opt-in（门3: ENABLED 开关缺省关 + 关态单测）
  → 评估报告（不接运行时; scripts/ 评估原型 + .artifacts/ 报告）
  → 三证据转正（门4: LEARNED_BACKEND_PROMOTION.md 三证据齐 → 评审 → 才可切默认）
```

任一门不过：组件保持原型/关态，不阻塞主线（这正是默认关纪律的目的——
学习组件按需进，进必有据）。
