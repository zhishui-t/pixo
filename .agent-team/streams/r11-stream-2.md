# R11 stream-2 —— huesat A 轨删除（GPL 清偿）

> dev-2 · 2026-09-07 · 状态：**删除/点云/测试/台账已全部落地且定向全绿；但执行中发现评估报告重大数据误判（影响面非零），已停报等用户重新知情裁决**

## 0. ⚠️ 停报摘要（先读）

评估报告 `arail-removal-eval.md` 的核心安全前提——**「全部 35 个风格配置
huesat 均 enabled:false，生产默认渲染零变化（逐一遍历实证）」——不成立**。
实测：**11 个配置 huesat enabled=true**（10 张胶片卡 + lr_adobe_standard_baseline
预设），全部无显式 color_domain → 删除前实际运行 A 轨（HSV 查表）、删除后
切 B 轨（OKLCh 点云形变）。这不是「删死代码」，而是 **10 张在用胶片卡的
look 替换**（用户可感知；t64 口径下 B 为合法 look，但「存量卡逐位不变」
的字面承诺被本删除打破）。

- 10 卡 A→B 漂移全量表见 §4（median 0.19~1.02 ΔE / p95 4.1~11.8 /
  max 6.7~28.2；>JND(2.3) 像素 10.5%~29.6%）
- 另：RAW 24 case 当前 FAIL，**经 stash 验证非本删除引入**（dca189c 椭圆
  重拟合与 RAW 基线重生成的时序错位，归队长基线重生成权），见 §5
- 工作树状态：R11 全部改动**未提交**，`git checkout -- <files>` 即可整体
  回滚；新增点云为 untracked 文件，回滚后无害（含表 DCP 3/3 仍有点云可复用）

**等用户重新知情裁决**：① 接受 10 卡 B 轨渲染（基线重生成，历史对照表
已留 §4）② 回滚 R11 全部改动（重新拍板）。裁决前我不提交、不再动。

---

## 1. 已交付（第一/二步全量落地）

### 第一步：点云前置（回退链断裂消除）
- `scripts/convert_hsm_to_oklch.py` 逐 DCP 生成 → 新增
  `configs/color/hsm_oklch_nikon_z_5_2_rawlab_lr_baseline.json`（2205 点）、
  `…_lr_camera_standard_baseline.json`（2205 点）
- **覆盖事实**：6 DCP 中 3 个含 HSM/LookTable 表 → **含表 DCP 点云 3/3
  全覆盖**；Preview 系 3 个 DCP **本身无表**（转译器实测「DCP 无
  HueSatMap/LookTable 表」），旧代码对它们本就「无表直通」→ 无点云即无
  HSM 可用，不存在回退需求。**回退链断裂风险（报告 §2.4 关键风险）消除**
- 修正验收口径：指令的「6/6 DCP 有点云」对无表 DCP 不可达也无必要；
  有效口径 = 「点云覆盖 = 全部含表 DCP (3/3)」✓（逐 DCP 解析实证）

### 第二步：A 轨删除（严格按报告 §1.2/§3.1 界定）
| 文件 | 动作 |
|---|---|
| `core/huesat.py` | 525→约 430 行：删 `apply_table_to_hsv`/`apply_hue_sat_map`/`apply_look_table`/`_apply_table_prophoto`/`_apply_table_linear`；docstring 重写（H1 清零）；:107/:123/:181/:337 RT/SDK 注释改规范引证（H2 随函数删除、H3 改写）；`__all__` 收缩；**偏差**：`_tri_index` 删除后零引用（huesat_oklch 有独立副本），按死代码删除——报告保留清单偏差 1 处 |
| `modules/huesat.py` | 235→约 230 行：删 use_dng 分支（H9）与 hsv 分支；process 重写为 oklch-or-no-op；wants()：非法域 fail-fast → 无表静默 no-op → oklch+spec → 退役域 warn-once；`_oklch_domain` 去 use_dng 例外；**缺省 color_domain 翻 "oklch"**（"hsv" 保留于 schema 仅为历史配置兼容=no-op）；docstring 重写 |
| `core/huesat_oklch.py` | 3 处注释改写（引用已删符号）——代码零改动（B 轨逐位不变，git diff 仅注释） |
| `scripts/convert_hsm_to_oklch.py` | 3 处注释改写；功能不动（重跑验证过） |
| `pipeline/base.py` / `core/tone.py` | 不动（prophoto 包装 + clean-room 应用保留） |

### 测试（报告 §3.2）
| 文件 | 动作 |
|---|---|
| `test_huesat.py` | 重写：删区段 2/3/6（apply_table_to_hsv 5 test、直通/dims 回退 4 test 中 3 个、use_dng 段）；保留 decode_table/dims 回退/`_sat_rolloff`/make_hue_sat_map/warm_sat 全部；**区段 4 改写为 oklch-or-no-op 分派钉死**（点云命中→应用 / 退役域→no-op / 缺失→no-op / 非法域 raise；metrics color_domain oklch|none）——**偏差**：区段 3 的 `test_hue_dims_do_not_fallback_to_look_dims` 与区段 2 的 `test_sat_rolloff_full_smoothstep` 锁的是保留功能，按条件 b（共享原语不得误删覆盖）保留 |
| `test_huesat_domain.py` | 重写：保留区段 1（ProPhoto/HSV 往返精度）；删区段 2/3（A 轨恒等往返/单调性）；区段 4 缺省表断言翻 `"oklch"`；链测试改写（点云命中 profile 执行顺序 + 点云缺失 no-op 链逐位） |
| `test_huesat_oklch.py` | 缺省断言按 F10 先例翻转：`test_stage_default_domain_unchanged`（钉 hsv 缺省）→ `test_stage_default_domain_oklch`（缺省≡显式 oklch；退役域 no-op≡基座直渲） |
| `test_huesat.py` 之外 | test_gate_huesat.py / test_native_hsv.py / test_hsl.py 不动，全绿 |

### 台账/文档（条件 d）
- `docs/tech_debt.md` #2：huesat 部分（H1/H2/H3/H9）标记已清偿 + 剩余另案
  清单（color.py H4-H8 / io.py H12 / white_balance M 系）；#3 发布警示
  huesat GPL 项划线清偿
- `FUNCTION_GATE_SPEC.md` §5.12：职责收缩（warm_sat + oklch）+ 门禁矩阵行
  `hsv/warm_sat` → `warm_sat/oklch`

### 指令偏差记录（gate case）
- 指令第 3 步要求「huesat gate case 删除」；实查 `gate_cases.py:170-174`：
  该 case 锁的是 `apply_local_warm_sat`（**自研保留功能**，lr_* 配置在用），
  报告 §3.3 明确判「零影响/保留」。「huesat_oklch case」不存在（报告 §3.3
  同证）。**未删**——删除将失去在用功能的 golden 锁。如队长仍要求删，
  一句话确认我再执行（基线 npy+manifest 同步随即做）。

## 2. GPL 清零验证（指令第 5 步）

`grep -iE "rawtherapee|rtengine|dng_render|dng_color_spec" src/pixo/render/`：
- **huesat 三文件（core/huesat.py / modules/huesat.py / core/huesat_oklch.py）：
  零命中** ✓（H1/H2/H3/H9 全落删除面）
- 范围内其余命中（均属指令声明的「另案保持现状」或非移植声明）：
  - `core/color.py` dng_color_spec/dng_render ×7 —— **H4-H8 另案**（指令明示保持）
  - `modules/white_balance.py` dng_color_spec —— F18 M 系另案
  - `core/lut3d.py` RawTherapee ×1 —— Hald CLUT 通用格式说明（非血缘）
  - `docs/PIXO_RENDER_*.md` ×5 —— 历史文档
- F18 H12（io.py）不在 grep 模式、不在本删除面（另案）

## 3. 定向验证（全绿项）

- 定向域：test_huesat + test_huesat_oklch + test_huesat_domain + test_gate_huesat
  + test_native_hsv + test_hsl + test_film_cards_oklch + test_film_cards →
  **72 passed**；test_gate_huesat + test_gate_golden（gate and not gate_e2e）→
  **8 passed**
- gate `--check`：**CHECK: OK（20 features）零漂** ✓（报告 §3.3 的静态推断
  实证成立——huesat 缺省关，合成 case 位型不变；gate `huesat` case 锁
  warm_sat 不受影响）
- B 轨逐位：`git diff core/huesat_oklch.py` 仅 3 行注释（零代码改动）→
  B 轨输出定义性不变；test_huesat_oklch 数值验收全绿

## 4. 停报主项：10 卡 A→B 渲染漂移（评估报告影响面误判）

### 4.1 报告误判证据
`arail-removal-eval.md` §0.1/§3.3：「全部 35 个风格配置 huesat 均
`enabled:false`，逐一遍历实证」——实测（本会话程序化遍历，脚本见
stream 底）：
```
huesat enabled=true: 11 个
  film_pro_400h(strength .3)  fujifilm_astia(.3)   fujifilm_classic_chrome(.15)
  fujifilm_community_lab_scan(.2)  fujifilm_pro_neg_hia(.2)  fujifilm_pro_neg_std(.16)
  fujifilm_provia_100f(.3)  fujifilm_provia_400x(.3)  fujifilm_reala_100(.22)
  fujifilm_velvia_50(.45)  lr_adobe_standard_baseline(全缺省)
```
全部无显式 color_domain → 删除前走 A 轨。**10 张在 23 卡哈希语料内**
（fujifilm_acros_100 无 huesat 参数），与渲染 DIFFERS 清单逐卡吻合。

### 4.2 A→B 逐卡量级（stash 双渲染实测，512px 合成基座）
| 卡 | ΔE median | ΔE p95 | ΔE max | >JND(2.3) |
|---|---:|---:|---:|---:|
| film_pro_400h | 0.793 | 7.380 | 19.346 | 23.5% |
| fujifilm_astia | 0.697 | 6.909 | 15.193 | 20.8% |
| fujifilm_classic_chrome | 0.543 | 4.075 | 6.736 | 10.5% |
| fujifilm_community_lab_scan | 0.185 | 5.681 | 14.183 | 15.4% |
| fujifilm_pro_neg_hia | 0.695 | 5.097 | 13.576 | 17.0% |
| fujifilm_pro_neg_std | 0.543 | 4.741 | 8.283 | 14.3% |
| fujifilm_provia_100f | 0.745 | 7.804 | 19.609 | 24.0% |
| fujifilm_provia_400x | 0.773 | 8.169 | 20.898 | 25.3% |
| fujifilm_reala_100 | 0.639 | 5.649 | 10.547 | 16.2% |
| fujifilm_velvia_50 | 1.017 | 11.841 | 28.163 | 29.6% |

读法：median 亚 JND~1 JND（整体观感轻微），尾部 p95 ≈2-5×JND、
超 JND 像素占比 10-30%（色相偏移作用区）——**用户可感知的走色变化**，
量级与 strength（0.15-0.45 部分强度）自洽（全强度 A↔B 分歧为 10.89）。

## 5. RAW 24 case FAIL —— 非 R11 引入（归属证明）

当前树 RAW compare 24/24 FAIL（u8 2~35）。`git stash` 三个 huesat 文件后
复跑：**仍 FAIL** → 失败先于 R11 存在。归属：dca189c（skin 椭圆重拟合）
落库晚于 RAW 基线重生成（R10 收口期），重拟合改变 oklch 域 skin 掩码 →
RAW 默认链（skin 缺省 oklch 已翻转、部分样本肤覆盖过门限）漂移 → **基线
需按重拟合后链再重生成（归队长）**。R11 的 huesat 在 RAW 四路径
enabled=false 零贡献（A 组/B 组分离实验逻辑同 R10 §3c 可复核）。

## 6. 等用户/队长裁决
1. **10 卡 B 轨渲染接受与否**（§4 量级表为决策数据）：
   - 接受 → 23 卡哈希基线 v_new 重生成（对照表 §4）+ changelog 明示
     「10 张 Fujifilm 系卡 look 更新（A 轨退役）」
   - 不接受 → `git checkout -- src/pixo/render/core/huesat.py
     src/pixo/render/modules/huesat.py src/pixo/render/core/huesat_oklch.py
     tests/unit/test_huesat*.py scripts/convert_hsm_to_oklch.py` 整体回滚
     （点云/台账保留无害），重新评估拍板
2. gate `huesat` case 是否仍要删（我按报告保留，见 §指令偏差记录）
3. RAW 基线按 dca189c 后链重生成（与 R11 无关的既有欠账）
4. test_theta_io 类同款漏改断言排查建议扩至 dca189c 全部触达测试
   （本批已修 theta_io 一处）

## 7. 复现命令
```
python scripts/convert_hsm_to_oklch.py --dcp resources/dcp/<name>.dcp
grep -riE "rawtherapee|rtengine|dng_render|dng_color_spec" src/pixo/render/core/huesat.py src/pixo/render/modules/huesat.py   # 零命中
python -m pytest tests/unit/test_huesat.py tests/unit/test_huesat_oklch.py tests/unit/test_huesat_domain.py tests/regression/test_gate_huesat.py -q
python tests/regression/goldens/generate_gate_goldens.py --check
```
