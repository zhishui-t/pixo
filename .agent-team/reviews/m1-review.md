# M1 掩码驱动渲染全链（region_adjust）独立评审

> reviewer 2026-09-07 交付（阻断 0 / 重要 4 / 建议 8）；队长处置裁决附各条末尾【裁决】。
> 审查对象：F12/F13/F14/F15 全链工作树现状；基准：design.md §2 F12-F15、stream-3.md、hard-problems.md。
> 取证：三个新测试套件 69 passed、邻域 50 passed 复跑全绿；另做 4 组独立数值/行为探针。

## 重要

### I-1 掩码在构图变化后不失效、不重分割（时间性几何失准，M1 新增行为面）
- 位置：`src/pixo/pipeline/loop.py:1211-1213`（`if masks_cache is None:` 仅首轮分割）、`loop.py:786/1224`（`_region_masks_soft` 一次性转换）、`loop.py:1513-1541`（`adopt_crop` 中途改写 `params["compose"]`）、`loop.py:1589-1593`（FINAL_QC 仍注入旧掩码）
- 证据：首轮 preview（旧构图帧）上分割的掩码，在 crop 建议被采纳后（后续迭代 + 导出线）继续注入；适配器只做 shape 对齐不做坐标重映射 → region_adjust 作用在错误的图像区域。`loop.py:1199-1201` 注释自认"compose 裁切改画幅"是预期场景（JND 形状重置），但掩码通道未随之处理——同一场景两套处理。触发条件：`crop_suggest=True` + decide 写 `compose.apply_suggestion`（crop_suggest_rule_003 在 DEFAULT_RULES 内，见 `decide/rules/__init__.py:31-37`）。
- 修复方向：以 compose 参数指纹为失效键——采纳/变化后重分割，或至少清空 `_region_masks_soft` 让 wants 静默直通。
- 【队长裁决】**本轮修保守版**：compose 参数变化（含 adopt_crop）时清空软掩码缓存 + warn-once，region_adjust 静默直通（"不作为"优于"错作为"）；重分割方案留 v2 记遗留。文件域仲裁：loop.py 掩码区向 dev-3 开放（限本修复）。

### I-2 free-px-rect 跨分辨率下 preview/export 掩码几何失配，且"两线仍一致"论断不成立
- 位置：`src/pixo/render/pipeline/region_masks.py:108-112`（盲 resize 到目标 post-compose shape）；根因 `render/modules/compose.py:75-86`（free 模式 x/y/w/h 为**像素**矩形）；`loop.py:1520-1541`（adopt_crop 写 full-canvas px，preview 在小 tier 上按同像素值裁剪）
- 证据：同一 params 在 tier（如 320 宽）与全分辨率（6000 宽）产生不同**相对**裁剪窗（x=100px → 31% vs 1.7%）；掩码在 preview 窗口语义下分割、被直接 resize 到 export 窗口帧 → 区域效果落点错位可达 10%+ 画幅宽。hard-problems §6.1 已登记根因（"既有"），但其中"掩码通道两线仍一致（同参数同适配）"的判断对此路径不成立——两线相对裁剪窗不同，几何并不一致。全部测试用 ratio/full-frame 规避了该路径（test_region_masks_channel.py 无 px-rect 用例）。
- 修复方向：compose 参数归一化到相对坐标（独立条目，建议升级优先级），或适配器按裁剪窗差做坐标重映射。
- 【队长裁决】**本轮不修主体**（既有架构问题、超 M1 范围；compose px→ratio 归一化是独立战役，牵动所有 free 模式用户）；处置=tech_debt 新条目（升级 hard-problems §6.1 优先级+注明掩码通道放大效应+验收论断限定范围），reviewer 的 px-rect 用例补进测试钉住现状行为。

### I-3 NaN 掩码穿透守卫，污染整帧输出（实测复现）
- 位置：`src/pixo/render/modules/region_adjust.py:206`（`if float(m.max()) <= 0.0`——NaN 比较为 False，不跳过）、`:173`（np.clip 不清除 NaN）、`:177`（GaussianBlur 将 NaN 空间扩散）、`:201-205`（except 分支声明"掩码内容坏→跳过不炸链"）
- 证据：探针实测——8x8 掩码含单点 NaN → 输出图像含 NaN（`nan in output: True`）。与 201-205 行声明的降级意图直接相悖。正常 0/255 分割契约下触发概率低（vision/base.py:44 契约为 uint8 0/255），但服务层直设 `session.region_masks`（Route B 公开属性）时可触达。
- 修复方向：`_prepare_mask` 内 `np.isfinite(m).all()` 检查（或 `nan_to_num`），坏掩码走既有 warn+跳过路径。
- 【队长裁决】**必修**（与代码声明意图直接相悖的缺陷）。

### I-4 `test_overlapping_regions_deterministic` 未钉死顺序合成语义（"看起来测了其实没测"）
- 位置：`tests/unit/test_region_adjust.py:368-386`
- 证据：docstring 声称断言"重叠区效果既不同于仅A也不同于仅B（顺序合成生效）"，但实际断言只有 (a) 两次运行逐位一致（任何确定性代码都通过）(b) `np.abs(ctx1.image - img).mean() > 0.0`（有任何变化即通过）。把合成改成反序、`np.maximum`、甚至只施加最后一个区域，测试仍绿。设计 §2 点名的"多区域按声明序顺序软合成"语义没有任何测试钉死。
- 修复方向：加正序 vs 反序结果不同的断言，或对重叠区像素做公式级断言（`out*(1-mB)+blendA*mB`）。
- 【队长裁决】**必修**（M1 语义核心无守卫）。

## 建议

### S-1 羽化 sigma"分辨率无关相对过渡带"声明与实现不符（clamp 边界）
- `region_adjust.py:49-53,174-176`：48px 长边相对宽 1.562% vs 6000px 0.133%，仅 512-4096 区间近似无关。【裁决】修声明（限定有效区间+说明 clamp 理由）。

### S-2 stage 兜底 resize 与适配器下采样核不一致
- `region_adjust.py:171-172`（INTER_LINEAR）vs `region_masks.py:108-112`（INTER_AREA）。【裁决】**修**：兜底按"目标小于源用 INTER_AREA"对齐（一行）。

### S-3 区域参数限幅常量双份定义（漂移风险）
- `loop.py:82-84` vs `region_adjust.py:55-57`。【裁决】**修**：loop 侧 import stage 常量单源。

### S-4 region.* 曝光键被全局溢出限流器波及（实测复现，已登记）
- `decide/engine.py:736-746`（`"exposure" in param` 命中 `region.plant.exposure`）；overflow 5% → plant 规则 +0.2 被压回 0.0。全局溢出统计压制**局部**暗部提亮在语义上偏保守。【裁决】本轮规则不入默认包无生产影响——region_rules.yaml 注释留痕，引擎豁免留下轮决策（随规则激活一起定）。

### S-5 region 规则未门控区域可靠性
- `region_rules.yaml:14-27`；小面积/低置信区域的高亮度可触发区域补偿。【裁决】**修**：condition 加 `*_reliable == true`（YAML 已有键可用，便宜且正确）。

### S-6 region_adjust 全图工作集内存（export 线）
- 24MP 多区域瞬时 GB 级（全图 gain 乘法+HSV 往返+blend）。【裁决】记遗留（bbox 裁剪优化留 v2）。

### S-7 stage 缓存命中时 region_adjust metrics 丢失（观测性）
- `session.py:360-377` 命中路径不调 `stage.run`。【裁决】记遗留（对 F14 闭环无影响）。

### S-8 `preview_overflow_ratio` 两键一值别名被注册宇宙固化（既有，非 M1 引入）
- `loop.py:487-492/738-739`。【裁决】记遗留（后续统一命名）。

## 各维度审查结论（含无问题维度）

1. **数学与色彩正确性**：EV 近似独立复算（0.5 处 ~0.2%，中间调 <0.4%）；组合路径（exposure+saturation）数值探针与手工公式 0.0 偏差；blend 加权保持 [0,1]。内核数学与声明一致，无阻断；仅 I-3/S-1 出入。建议补组合路径单测。
2. **坐标/分辨率边界**：I-1/I-2/S-1/S-2。适配器 compose shape 预测与 `compute_crop_rect` 同源正确（auto_level/旋转/翻转保尺寸均核实）。
3. **并发与缓存**：`_ndarray_digest` 采样+data_ptr 方案自洽（陈旧命中需条目存活钉住地址，闭环成立）；透传纪律、命中/失效有测试钉死。无新问题（S-7 观测性）。
4. **接线完整性**：全链核验无键冲突、特例分支正确、钳制/联动/畸形键不吞有测试；YAML 双源 diff 一致；规则未入 DEFAULT_RULES 核实；enabled=False 零影响彻底。遗留 S-3/S-4/S-5。samples.py 新键向后兼容经 compare.py:99-100 核实。
5. **测试质量**：数值断言真实钉死语义，e2e 闭环质量高。缺口：I-4、组合 ex+sat 无用例、头注 "<6%" 与断言 "<4%" 不一致（装饰性，顺手修）。
