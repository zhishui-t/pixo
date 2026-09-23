# F07 存量卡钉 hsv 定向门禁（oklch 前置修补 a）

> 审核人：qa｜2026-09-07T01:36:15+08:00
> 对象：stream-2 交付（F07），黑板 streams/stream-2.md
> 基线：512bd0d + 共享树（F13 在飞已审毕；F08 dev-2 进行中——gate_cases.py/test_gate_golden.py 未碰）
> 方法：解析级 JSON 对账（非 diff 行数目测）+ 哈希证据三重复验（含 qa 独立重跑复现）+ 敏感性诊断复算 + 断言强度对比审 + 全域复跑

## 结论：**PASS**（修复 1 处后放行——测试断言强度弱化，已最小修复+复验）

---

## 1. 计数复核

qa 独立脚本（git show HEAD 版 vs 工作树版，解析后逐键对比）：
- 修改文件 = **23 张存量卡**（`git diff --name-only` 计数）；**oklch_demo×2 零触碰** ✓
- 钉域计数 = **hsl 12 / split_tone 12 / skin 22 / colorcal 23，共 69 条**——与 qa 设计修订时
  （design.md F07 节）实测口径逐一吻合 ✓
- skin 22 口径正确：film_pro_400h 无 skin 键（22≠23 的唯一特例），黑板逐卡表与实测一致 ✓

## 2. diff 纯度（解析级，强于目测）

qa 脚本逐卡逐 stage 对比解析后 JSON vs 512bd0d 版：
- **唯一变化 = 4 涉域 stage 新增 `color_domain:"hsv"`**；顶层 params 键集零增删；
  非涉域 stage 参数零变动；已存在的 color_domain 值零改动 → **violations: NONE** ✓
- 键序约定抽查 5 卡：hsl 的 color_domain 在 bands 前（kodak_portra_400/agfa 均位 2/3），
  其余 stage 追加末尾（split_tone 7/7、skin 2/2、colorcal 2/2）——沿 demo 卡约定 ✓

## 3. 逐位不变证据复核（方法论成立，三重复验）

- **方法论**（`_f07_pin_hsv_render_check.py` 审读）：真实集成路径
  `build_default_pipeline(params=卡参数)`（api.py 卡集成惯例，非信息性 stages 字段直组链）+
  仓库内置 DCP + duck-typed raw（固定 camera_whitebalance 供 as_shot）+ 固定种子合成图
  （肤色块过 skin 门限 + 彩色渐变盖 hsl 扇区/split_tone 染色 + 有界噪声）+ scene="portrait"
  （skin wants 门控放行）——**4 涉域 stage 实际执行而非恒等直通**，float32 逐字节 sha256。✅ 成立
- **23/23 前后一致**：`f07_render_hashes_before/after.json` 逐卡 sha256_float32 全等（23/23），
  pinned 条目 0→69（before 确为钉前状态）。✅
- **qa 独立重跑复现**：qa 现场重跑脚本生成 manifest 与 dev-2 的 after.json **23/23 条目逐字节一致**
  ——同时证明确定性与证据真实性（非事后构造）。✅
- **敏感性诊断复算**（kodak_portra_400，中和单 stage 参数 vs 卡参数）：
  hsl 0.0107 / split_tone 0.2088 / colorcal 0.2314 与黑板**逐位吻合**；skin qa 复算 0.0094 vs
  黑板 0.0201——中和方法差异（qa 置空参数 vs dev-2 禁用 stage），**四 stage 非零贡献结论一致**，
  对比路径敏感成立。✅

## 4. 测试改写质量审（发现 1 处弱化，已修）

### test_legacy_cards_pin_hsv_domain_explicitly
- 逐卡逐 stage 断言「凡带键必钉 hsv」+ 计数精确钉死 {12/12/22/23} + bands 无 domain 键保留——
  新口径下断言强于旧（旧禁键→新强制值）。✅
- **[弱化发现]** 旧不变量「任何 stage 不得出现 color_domain」是全覆盖；改写后仅钉 4 枚举，
  枚举外 stage（**huesat 亦有 color_domain 参数面**，t64 已接线 hsv|oklch 分派）的域键漂移
  失去守卫——若未来有人在存量卡 huesat 上钉域（新语义变更），测试静默放行。

### 修复记录（三要素）
- **改了什么**：`tests/unit/test_film_cards_oklch.py::test_legacy_cards_pin_hsv_domain_explicitly`
  追加「涉域四枚举之外禁止出现 color_domain」断言（`stage_name not in DOMAIN_STAGES` 分支，
  违例报错文案指引「钉域须显式扩 DOMAIN_STAGES」）。
- **为什么**：恢复旧不变量的全覆盖守卫，闭合枚举外（huesat 等）域键漂移盲区；与旧口径相比
  断言强度不弱化（设计审核承诺「不弱于旧不变量」）。
- **怎么验证**：修复后 `test_film_cards_oklch.py` 8 passed（当前卡库零违例=无误报）；
  心算反例（若卡 huesat 带 color_domain 将被新断言拦截）成立。

### test_legacy_domain_pin_merge_equivalent_to_defaults
- 合并层（`Stage.__init__` 的 `{**default_params(), **卡参数}`）钉/不钉逐键相等断言 +
  钉值恒 "hsv"——「钉域当前是语义 no-op」的永久守卫，且明示 F10 翻转后卡参数显式 hsv
  恒覆盖新缺省。设计完成标准实现 b，方法论正确。✅

## 5. 定向复跑（修复后）

```
test_film_cards_oklch.py                                  → 8 passed（0.51s）
卡域 14（film_cards_oklch + film_cards）                  → 14 passed
邻域 122（pipeline_config/pipeline/hsl_oklch/split_tone_oklab/hsl/skin/native_colorcal） → 122 passed
引用面 28（oklch_preview_e2e + know + film_cards + film_cards_oklch）→ 28 passed, 1 warning
```
合计 **8 + 164 passed / 0 failed**（164 = 14+122+28，与队长口径一致）。✅

## 6. 观察项（不阻断）

1. 卡 JSON `stages` 列表与真实链序不一致（信息性字段）——dev-2 遗留 1 已登记，建议卡 schema
   文档注明或后续删减，超 F07 范围。
2. `.artifacts/` 证据被 gitignore 不入库——脚本身可复现（qa 已独立复现），如需入库存证队长定。
3. F08/F10 接口提示已阅：F08 存量卡 golden 复用本渲染路径；F10 后复验命令与预期（23/23 仍逐位
   一致）——纳入 F10 专项门禁核对项。

## 7. commit 放行清单

- **F07 批**：23 张卡 JSON（69 条 color_domain:"hsv" 纯插入）+ tests/unit/test_film_cards_oklch.py
  （不变量改写 + 合并等价新测 + **qa 补强的枚举外禁域断言**）
- 依赖序：F07 须在 F10 之前（已满足）；与 F08（gate_cases.py/test_gate_golden.py，dev-2 在飞）
  文件不相交，可并行；证据脚本（.artifacts/_f07_*.py + 哈希 manifest）不入库（gitignore），留档即可。

> 门禁章：qa 2026-09-07T01:36:15+08:00 — F07 PASS（修复 1 处断言弱化并复验），
> 计数/diff 纯度/逐位证据三重复验全过，方法论成立。
