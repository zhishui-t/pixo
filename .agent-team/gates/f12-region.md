# F12 region_adjust 定向门禁（M1 主体）

> 审核人：qa｜2026-09-07T01:25:39+08:00（2026-09-06T17:25:39Z）
> 对象：stream-3 交付（F12 region_adjust stage），黑板 streams/stream-3.md
> 基线树：f357b35 + Wave 并行共享树（region_masks.py/loop.py 等在飞改动属 super-dev F13，只读核对契约，不评其实现）
> 方法：交付面 diff 核对 + 数值断言逐条推演 + 契约两侧（生产/消费）逐点比对 + 既有断言弱化检查 + 定向复跑

## 结论：**PASS**（F12 可进入分批 commit 序列；F13/F14 下游依赖的契约面已冻结为本实现口径）

修复记录：**0 处**（未发现需修复缺陷；观察项 2 条见 §7，不阻断）

---

## 1. 交付面核对

| 项 | 证据 | 结论 |
|---|---|---|
| region_adjust.py | `@register_stage("region_adjust", order=57, domain_in/out=DOMAIN_GAMMA_RGB)`；param_schema `enabled`(bool)+`regions`(dict)；default_params `{enabled: False, regions: {}}` | ✅ 与设计 F12 节一致 |
| 56-59 槽位 | `test_registration_order_domain` 钉死 neighbors == {skin:55, region_adjust:57, stylize:60}（qa 设计时已实测空槽，实现落 57） | ✅ |
| presets.py | DEFAULT_STAGES 14→15，`"region_adjust"` 落 skin 后 stylize 前 + 注释更新；`test_default_chain_insertion_between_skin_and_stylize` 钉序 | ✅ |
| params.py | import + STAGE_CLASSES 登记；`test_params_registry_entries` 验 PARAM_SCHEMAS/DEFAULT_PARAMS 派生 + **PARAMS_DEFAULT_STAGES is DEFAULT_STAGES 同一性断言**（防两表漂移，超预期的好钉法） | ✅ |
| modules/__init__.py 注册线（队长已追认的范围外改动） | **技术必要性成立**：`build_default_pipeline` 仅靠 `from pixo.render import modules` 触发装饰器注册；DEFAULT_STAGES 已含 region_adjust，缺此 import 则 STAGE_REGISTRY 缺键 → `Pipeline._resolve` 必 KeyError——不只影响 patch_protocol/loop 旁路，而是所有默认管线构建。改动仅 2 行（import+导出），最小 | ✅ 追认合理 |

## 2. 数值正确性抽查

| 项 | 断言证据（qa 逐条推演） | 结论 |
|---|---|---|
| gamma 域曝光 `gain=2^(ev/2.2)` | 纯幂数学自洽（gain^2.2=2^ev）；`test_exposure_gamma_gain_exact` 6 档 EV（-2..2）逐像素精确 `0.5*gain`；`test_exposure_monotonic_and_clips` 单调+clip+角点精确值 | ✅ |
| 中间调线性等效 <4% | `test_exposure_linear_equivalence_midtones`：**测试侧独立实现分段 sRGB EOTF**（`_srgb_decode`，x≤0.04045 线性/否则 ^2.4），gamma 0.30..0.64 渐变 × EV=+1，`max|lin_out/(lin_in*2)-1| < 0.04`——用真 sRGB 而非纯幂自证，口径正确 | ✅ |
| HSV S 饱和度 | float32 路径（cv2 32F：S∈[0,1]）；`S'=clip(S*(1+sat))`；中性 S=0 恒等（allclose 1e-6）；方向+clip 双向精确断言（红 (0.8,0.4,0.4) +1→(0.8,0,0)、-1→(0.8,0.8,0.8)） | ✅ |
| 分辨率相对羽化 | `sigma=clip(长边/512, 1, 8)`（常量区实现）；`test_feather_no_hard_edge_on_binary_mask`：二值阶跃掩码 max\|Δcol\| < 0.5×全幅 step（禁硬边纪律量化钉死）；preview/export 相对过渡带一致（tier 口径差教训落实） | ✅ |
| 软掩码顺序合成 | `out = out*(1-m) + adjusted*m`，regions 声明序，同区先曝光后饱和；`test_soft_mask_linear_blend` m=0.5 精确钉混合式；`test_overlapping_regions_deterministic` 两区重叠两次运行逐位一致；`test_mask_zero_region_bit_identical` m=0 区（离羽化边界）逐位不变 | ✅ |
| 零效果守卫 | `test_zero_ev_zero_sat_identity`：image_writes 不增（「未写即未变」恒等直通，与 graph.py run 后验契约自洽） | ✅ |

## 3. 零影响验证（默认 enabled=False）

- 链级证据 `test_default_off_full_chain_bit_identical`：真实 profile 全链渲染，DEFAULT_STAGES ±region_adjust 两跑
  **max|Δ| == 0.0（逐位）**——qa 复跑绿。此为金样本/gate 零影响的设计级证据（沿 dehaze t108 口径）。
- wants 门控 7 用例：默认关/regions 缺失空/state 无 region_masks/prompt 无掩码/零效果参数各路 False，就绪路 True——复跑绿。
- 全注册链冒烟（Pipeline(stages=None) 全 order 链含 region_adjust，wants=False 跳过）经 phase1/pipeline 套件覆盖。

## 4. 与 F13 契约对齐（生产侧 region_masks.py 只读比对，不评 super-dev 实现）

| 契约点 | 生产侧（adapt_region_masks） | 消费侧（region_adjust） | 吻合 |
|---|---|---|---|
| 类型/形状 | 输出 dict prompt→float32 HxW（HxWx1 已展平；非 2D/空 skip+warn） | 接受 HxW/HxWx1，非 2D 显式 ValueError（防直接误用） | ✅ |
| 值域 | uint8 /255 归一（0/255→恰 0/1）；float clip 0..1 | 再 clip 0..1（防御冗余，无害） | ✅ |
| 分辨率 | 对齐 post-compose 帧（compute_crop_rect 预测；两线同函数同插值） | shape 不匹配时双线性缩放兜底（loop 首轮 shape=None 转换的下游场景） | ✅ |
| 羽化归属 | 本层不做（「适配即语义中性」明示） | 消费 stage 尺度相对高斯羽化 | ✅ 职责无重叠 |
| 坏掩码降级 | 单掩码 skip+warn（不阻断渲染） | 缺 prompt 的区域静默跳过；掩码全零跳过 | ✅ 同语义链 |
| 缓存纪律 | data_ptr 透传保 _ndarray_digest 指纹稳定 | 不生产掩码、不改 state | ✅ |

**判定：契约逐点吻合，无需任何一侧调整。**

## 5. 既有断言机械同步检查

- `test_phase1_chain.py`：`test_default_chain_contains_14_stages`→`15_stages`——计数+**全列表等值断言**同步插入 region_adjust，docstring 更新；
- `test_pipeline.py`：`test_default_stages_contains_huesat` 同口径同步。
- 两处均保持**精确列表相等**（强于计数断言），无弱化、无其他断言触碰——纯机械修订成立。

## 6. 定向复跑

```
python -m pytest tests/unit/test_region_adjust.py tests/unit/test_phase1_chain.py \
  tests/unit/test_pipeline.py tests/unit/test_pipeline_config.py tests/unit/test_colorcal_direction.py -q
  → 85 passed in 1.05s（region_adjust 单文件 30 collected，与黑板一致）
python -m pytest tests/unit/test_skin.py tests/unit/test_render_public_adapters.py tests/unit/test_patch_protocol.py -q
  → 53 passed in 1.23s（邻域/公共适配器/补丁协议冒烟）
```
合计 138 passed / 0 failed。（dev-3 黑板自报定向 343 passed，本门禁抽核心域复核；全量回归队长统一执行。）

## 7. 观察项（不阻断）

1. **深阴影近似偏差**（路线 a 已知取舍）：gamma<0.25 区线性等效误差 >5%（dev-3 实测 0.15 处 ≈11%）——
   模块 docstring + 黑板遗留项 3 已声明，设计 §2 明示「意图级软区域」选 a。如验收在意，后续按区域加
   阴影保护或切路线 b，本轮不动。
2. **wants 内结构校验抛错**：enabled=True 且 regions 结构非法时 ValueError 自 wants 抛出（fail-fast，
   沿参数校验惯例，`test_invalid_regions_raise_value_error` 钉死）——可接受，无需改。

## 8. 放行清单（供分批 commit）

- F12 批：region_adjust.py（新）+ presets.py + params.py + modules/__init__.py（注册线，队长已追认）
  + test_region_adjust.py（新）+ test_phase1_chain.py / test_pipeline.py（机械同步）
- 依赖序提示：F12 批与 F13 批（loop.py/session.py/export.py/region_masks.py/test_export.py）文件不相交，可独立提交；
  test_phase1_chain/test_pipeline 的 15 段断言依赖 F12 批先行（或同批）。

> 门禁章：qa 2026-09-07T01:25:39+08:00 — F12 PASS，零修复，F13 契约逐点吻合。
