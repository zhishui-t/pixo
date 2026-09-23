# F08+F09 联合定向门禁（oklch 前置修补 b+d —— F10 前最后一道闸）

> 审核人：qa｜2026-09-07T02:07:17+08:00
> 对象：stream-2 交付（F08 gate case 17→19 / F09 patch 同源化+canonical 确认），黑板 streams/stream-2.md
> 基线：b812061（F14 已提交）+ 共享树（dev-3 F15 在飞：samples.py/render/README/gate region_adjust case——非本门禁对象，归属切分见 §1）
> 方法：diff 归属切分 + manifest 字节级外科核验 + 翻转实验独立复跑 + 断言强度逐行审 + 七组定向复跑

## 结论：**PASS —— F10 放行（派遣解堵）**

修复记录：**0 处**（F08/F09 域内未发现需修复缺陷）
上轮红旗（test_patch_protocol 11 红）：**已转绿**（29 passed，§4）。

---

## 1. F08 审核

### 1.1 归属切分（共享文件内 F08 vs F15）
gate_cases.py 在飞 diff 含三部分：F08 的 `default_dispatch`+`card_portra_400`（含
`_FullPipeRaw/_fullpipe_input/_run_full_pipeline/_DISPATCH_BANDS` helpers）＝本门禁对象；
F15 的 `region_adjust` case + `_region_soft_mask` + `_run_full_pipeline` 的 region_masks
可选参＝dev-3 F15 域（**未审**，其基线 region_adjust.npy 与断言行同理）；manifest 新增 3
条目中 region_adjust 属 F15。`_run_full_pipeline` 的 region_masks 参数缺省 None——既有 case
路径行为逐位不变（注释明示+--check 全绿佐证）。

### 1.2 两 case 设计与双重用途注释
- **case1 default_dispatch（观测点）**：四 stage 非零典型参数、**Stage 级与 band 级均不传
  color_domain**（bands 无 domain 键，归属完全落 `hsl.py:73 band.get("domain",default_domain)`）；
  skin 不传 enabled（缺省 True，未来 skin 翻转同被观测）——qa 读 params dict 逐项证实。
  契约注释明示：**F10 后本 case 必须变化**（不变=切换未生效，阻断）；基线 v2 队长单点重生成。✅
- **case2 card_portra_400（A1 证明）**：参数单一来源=运行时读卡 JSON（不复制——卡误改同在
  金样本层可观测）。契约注释明示：**F10 前后必须逐位不变**（漂移=A1 破坏，阻断切换）。✅
- 输入合成：独立种子 20260907 + 经典肤色补丁过 skin 掩码门限 + scene="portrait" 显式钉死
  （纯函数式确定）。✅

### 1.3 翻转实验性质验证（qa 独立复跑 `_f08_case_property_check.py`）
- 敏感性：hsl 0.0097 / split_tone 0.168 / skin 0.0766 / colorcal 0.0265——与黑板逐位吻合
  （对比路径真实敏感，非恒等直通）；✅
- 进程内翻转 hsl+split_tone 缺省→oklch：**case1 flip-changed=True（观测点有效）；case2
  flip-changed=False 且逐位一致（A1 卡级锚定在金样本层生效）**——双契约性质均实证；✅
- 确定性：两 case sha256（fbd5d50c…/94bdd613…）与黑板记录一致。✅

### 1.4 外科式基线新增（F06 教训的镜像操作）
qa 字节级核验 manifest（git show b812061 版 vs 工作树版）：**旧 17 条目 repr 逐字节相等
（17/17）；reviewer 字段原样保留**（t38 tester-1 全文未动）；顶层键集不变；diff 纯 30 行插入
零删除。旧 .npy 未重写（--check 全绿佐证）。✅
断言同步：len==17→**20**（F08 的 19 + F15 的 1，构成注释归属清晰，精确计数断言+reviewer
非空守卫保持——无弱化）。✅

### 1.5 定向复跑
```
tests/regression/test_gate_golden.py -m "gate and not gate_e2e"  → 4 passed（24.5s）
tests/regression/test_gate_golden.py（全）                        → 4 passed
generate_gate_goldens.py --check                                  → CHECK: OK（20 features 与 manifest 一致，零漂移）
```
✅

## 2. F09 审核

### 2.1 红旗复验（最高优先）
上轮 F14 门禁定位的 test_patch_protocol.py 11 红（patch_protocol.py:214
`UnboundLocalError: stage` 未绑定——F09 中途态）：**本轮 29 passed 全绿**。
根修确认：`_bands_reject_reason(raw, stage)` 增参 + `_validate_one` 调用点就地派生
`param.split(".",1)[0]`——中途态补全，非绕过。✅ **红旗关闭**

### 2.2 同源化落点（零字面量）
- `_stage_default_color_domain(stage)`：读 `STAGE_REGISTRY[stage]().default_params()
  ["color_domain"]`——与运行时链同源（graph.py:46-48 合并 default_params 进实例参数 →
  hsl.py:51 的缺省字面量因 default_params 恒含该键而**不可达**）。qa 全 diff 复核：代码内
  **零 "hsv" 字面量复制**（仅 docstring 叙述性文字）。✅
- 旧 :118 `band.get("domain", "hsv")` → `band.get("domain", default_domain)` 参数化。✅
- 防御路径（stage 未注册/实例化失败→空串→不属 oklch 量纲仅通用拒绝）——正常不可达，合理。✅

### 2.3 断言强度（「F10 后自动成立」承诺是否真被钉死）
- `test_no_domain_band_attribution_follows_stage_default`（翻转自证）：同一 hue_center=9999
  无 domain 键 band，翻转前不检 / 进程内翻 HslStage 缺省→oklch 后硬拒命名——**若残留字面量
  本测试红**。承诺钉死。✅
- `test_patch_attribution_equals_runtime_dispatch`（parity）：三 band 形态 × 两缺省下，
  patch 侧被 oklch 检查的 band 集合 == 运行时 `_split_bands_by_domain` oklch 分组（逐 band，
  期望值读同源）——**F10 后零修订自动成立**。承诺钉死。✅
- `test_stage_default_color_domain_source`：单源读点直接断言。✅
- 辅助 `_flip_hsl_default_domain`：真实 default_params 暂存+条件翻转，多次翻转安全（qa 审读）。✅

### 2.4 canonical 透出结论核查
- `test_canonical_params_expose_color_domain`：四 stage canonical 的 color_domain ==
  STAGE_REGISTRY default_params 值（读同源，F10 自动跟随）+ 用户覆盖优先 + enabled 合并——
  「现状已透出」由测试钉死而非仅口头结论。✅
- 前端现状（qa grep types.ts 佐证）：`color_domain?: ColorDomain` 仅 hsl(:221)/split_tone(:241)
  （DomainToggle 域开关用）；skin/colorcal UI 类型无此字段——UI 不做这两域切域编辑（design §1.2
  第一批口径），**非缺口**的判断成立。✅

### 2.5 定向复跑
```
test_patch_protocol.py           → 29 passed（26 旧+3 新；11 红转绿）
test_preview_session.py          → 21 passed（20 旧+1 新）
F09 联合（patch+preview+export+service_runtime+loop_param_mapping）→ 78 passed
agent 域（agent+agent_suggest+llm_shadow）                          → 37 passed
F07/F08 回归（film_cards_oklch 8 + gate_golden_tool 4）             → 12 passed
```
✅ 全绿

## 3. 观察项（不阻断）

1. **gate 资产的 commit 切分提示（队长）**：在飞 gate_cases.py/manifest/test_gate_golden 同时含
   F08（2 case）与 F15（1 case）改动，文件级不可拆——建议 F08+F15 的 gate 资产同批提交（或按
   hunk 外科拆分，成本高不建议）；断言 20 = 两批共同口径。
2. case1 raw 桩 wb_B=0.960 触发 warmth 域外垫片告警（stderr，确定性，黑板遗留 2 已记）——
   不动正确（调系数=改基线须走重生成）。
3. 旧测试 `test_bands_string_hsv_domain_not_checked` 钉当前缺省语义——F10 后随缺省断言批次
   修订（design §F10 清单可并入，黑板遗留 1 已登记）。✅ 分级合理
4. F08 manifest reviewer 仍为 t38 文案：本批 2 case 待 qa 复核后追加——**本门禁即复核**，
   建议 captain 提交时在 reviewer 文案追加 F08/F15 批次记录（沿 t38 先例），或由 qa 在
   F15 门禁后统一落笔。

## 4. F10 放行判定

**放行。**依据（design F10 前置全就绪）：
1. F06 ✓（RAW 基线 regen 后 24/24 逐位，2026-09-07 复验）；
2. F07 ✓（23 卡 69 条钉 hsv，逐位证据三重复验，门禁 2026-09-07）；
3. F08 ✓（本门禁：观测点 case 翻转必变 + A1 case 翻转逐位不变双性质实证）；
4. F09 ✓（本门禁：校验归属同源零字面量 + parity/翻转自证钉死）。
F10 执行时按 design §F10 验证链四项留证；缺省断言修订清单 = design 4 项（hsl/split_tone）
+ 本门禁 §3.3 的 1 项旧语义测试（dev-2 黑板已自我申报，合并修订）。

> 门禁章：qa 2026-09-07T02:07:17+08:00 — F08 PASS / F09 PASS / 11 红转绿确认 /
> F10 放行（前置修补 a·b·d + F06 全数就绪）。
