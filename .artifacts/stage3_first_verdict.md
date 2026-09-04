# 阶段三首块终审报告（t44）—— GO/NO-GO + 光照估计转正建议

- 日期：2026-09-04 · 执行：qa（长安）
- 审计对象：t42（治理框架四门禁固化）+ t43（光照估计经典法评估原型）——当前工作区未提交批次（基线 commit `f49d3fc`）
- 独立复核动作：白名单门构造性验证（含真实 manifest 变异）、隔离门三态实跑（临时建目录→红/绿/skip）、治理文档 env 逐一对照 src、三方法断言级性质验证（合成已知光源）、json/md/verdict 三方一致性、全量回归复跑

---

## 1. 总结论：**GO** ✅

t42 四门禁全部经**构造性验证**实证有效（非仅文书审查）；t43 三方法实现性质正确、口径与阶段二同源、三证据初评逻辑成立；红线全过（src 渲染零 diff、learned/ 未建、全量 **1334 passed / 5 skipped / 1 xfailed**）。

**光照估计转正建议（只建议）：不进入三证据转正流程**——证据①在初评阶段即被负收益否决（详见 §3），as_shot 链维持现状正确。

---

## 2. t42 四门禁核对（构造性验证）

### 2.1 门① 许可白名单硬拒 ✅（六组构造性验证全过）

`tests/unit/test_model_licenses.py` 的 `_license_gate_errors` 纯函数直接调用验证：

| 场景 | 结果 |
|---|---|
| 真实 manifest（7 条）过门 | 清洁 ✅ |
| 合成 `CC-BY-NC-4.0 + publishable=true` | **硬拒**（报错含条目名/许可/白名单 {MIT, Apache-2.0}）✅ |
| 复合文案 `code MIT / weights CC BY-NC-SA + true` | **硬拒**（整体比对，不因含 "MIT" 字样漏放）✅ |
| 非白名单缺 publishable 字段 | **拒**（deny-by-default）✅；白名单缺字段也报"缺显式布尔（缺省按 false 治理）"（比预判更严） |
| 正例 `MIT + true` | 放行 ✅ |
| **真实 manifest 变异**：3 条 NC 条目 false→true | **3 条逐一命名报错** ✅ |

`model_licenses.json` diff 核对：7 条全补 publishable（MIT/Apache-2.0 四条 true；UniFace CC BY-NC-SA / SegFormer ADE20K 随发布口径 / Sapiens CC-BY-NC-4.0 三条 false），与 t42 声明一致。

### 2.2 门② 隔离扫描预铺门 ✅（三态实跑）

`tests/unit/test_learned_isolation.py` 临时真建 `src/pixo/render/learned/` 做三态验证（验后清理，src 零残留）：

| 态 | 动作 | 结果 |
|---|---|---|
| 红 | 目录存在 + `bad_backend.py`（函数内懒 import torch） | 主门 **FAIL 并命中** ✅ |
| 绿 | 仅 `ok_backend.py`（numpy） | **PASS 零误报** ✅ |
| skip | 删除目录 | **SKIPPED 1**（message 写明"目录落地即生效"）+ 3 项门禁自检 passed ✅ |

自检覆盖（懒 import 捕获 / numpy-cv2-pixo 零误报 / 语法损坏报错不静默）在源码 `test_learned_isolation.py:60-97` 逐条在案。"未建先铺门"语义达成：skip 不是装饰品——本审计红态实跑证明目录落地即生效。

### 2.3 门③④ 治理文档与既有惯例对照 ✅（1 项观察）

**GOVERNANCE**（`docs/LEARNED_BACKEND_GOVERNANCE.md`）：
- §1.1 表列 15 个 env **逐一在 src 实存**（grep 全量核对：PIXO_GSAM_ENABLED / ALLOW_RESTRICTED / SEGMENTER / SAPIENS_MODEL / AESTHETIC_MODEL / FAIRFACE_MODEL / GSAM_SAM / UNIFACE_MODEL / SEGFORMER_MODEL / MODEL_LICENSES / CONFIG_ROOT / DATA_ROOT / RENDER_LUT_DIR / DECODE_CACHE_MB / SCORER_WARMUP 各≥1 文件）；
- 具体语义与代码逐字一致：真值集 `{"1","true","on","yes"}`（`grounded_sam.py:38-40` 实现同集合同 strip().lower()）；`PIXO_ALLOW_RESTRICTED=1` 仅放行 restricted 注册（`multi_router.py:103-115`）；`PIXO_SEGMENTER` 缺省 `"mock"`（`service/runtime.py:130`）；缺省关三连带有代码例证（gsam `enabled()` 缺省 "0" 短路）。
- **观察项（非差距）**：env 清单非穷尽（PIXO_GSAM_DINO / PIXO_SEGMENTER_WARMUP / PIXO_CAL_* / PIXO_DSH_* 未入表）——文档定位"既有实例"为示例、三类命名规则可全覆盖，遗留 L-2 建议维护批次补盘点。

**PROMOTION**（`docs/LEARNED_BACKEND_PROMOTION.md`）：三证据模板完整——证据①门"收益 < 1 JND 须记录无转正价值并停止晋升"（阶段三设计 §2 同口径）、证据②确定性方案或双轨（含回退路径+一致性抽检）、证据③域外降级+回退可见（禁止静默劣化）+ 评审签核表 + 转正后义务（回退开关永久保留）+ 无转正价值记录表（防重复尝试）。与 t43 报告引用的判据一致。

---

## 3. t43 光照估计报告核对

### 3.1 三方法实现正确性 ✅（断言级验证，合成已知光源 e=[1.25,1.0,0.72]）

| 性质 | 断言 | 结果 |
|---|---|---|
| 灰世界均值性质 | 中性反射场景（obs = e·r，r 三通道同灰）下 `estimate_light` ∝ e | 方向误差 **7.8e-16** ✅；校正后通道均值 = [1,1,1]（von Kries 语义） |
| 白斑 max 性质 | 最亮中性面（白面反射率 0.6）颜色即光源方向 | 方向误差 **3.3e-16** ✅ |
| 饱和排除 | 贴顶假饱和块（R=1.0 ≥ clip_hi 0.985）被剔除不拉偏 | 误差 **3.3e-16** ✅；对照不排除（clip_hi=None）偏差 0.043——排除逻辑必要 |
| 单测 | `test_illumination_est.py`（WB 域闭环往返等） | **14 passed** ✅ |

审计过程注记：本审计首轮"饱和排除"断言失败系**测试构造错误**（白面设 0.9·e 时 R 通道 1.125 本身超 clip_hi、恰属应被排除的贴顶像素）——修正构造后通过，反证 clip_hi 语义实现正确。`gray_world.py`（通道均值）/`white_patch.py`（亮度 max 通道前 0.5% 分位均值）算法核心与教科书定义一致。

### 3.2 ΔE 口径与阶段二一致 ✅

`scripts/illumination_est/eval_illum.py`：`:50` 同源 `from eval_rp_ccm_ab import delta_e_2000`（开跑先 `--selftest` 文献对自检 `:118-122`）；`:104` 同语料 `exports/auto/full_scan`（54 张，json n_photos=54 复核）；`:52` 复用 `fit_rp_ccm.aligned_pair/iter_corpus/sample_linear_pairs` 同链（[0.01,0.9] 双侧窗 + EXIF 逆旋转 + INTER_AREA）；`:162/:183` 逐照片 gain 对齐（A 轨算 gain、A/B 共用）——与阶段二 eval 口径同构。

### 3.3 数值三方一致性 ✅ + 三证据初评逻辑 ✅

- json `summary` 9 轨（5 主 + 4 guard）与 md 报告总体表逐位一致（as_shot 5.946 / GW 11.385 / GE1 10.180 / GE2 11.497 / WP 10.207；guard 4 轨同）；
- 机器可读 `verdict`：最佳 GE1 improvement −4.234 = **−1.841 JND**，`pass_1jnd=false`；`promotion` 三证据 `evidence_1=false / evidence_2=true / evidence_3=false` → `"无转正价值"`——与报告 §三证据初评一致；
- **<1 JND 条款触发正确**：PROMOTION 证据①门要求收益 <1 JND 记录无转正价值；t43 实测为**负收益**（更强触发），初评即否决并留档（.artifacts 报告 + json），as_shot 维持现状、不接运行时——逻辑链完整。

### 3.4 光照估计是否值得进入三证据转正流程（只建议）

**建议：不进入。** 依据：

1. **证据①已在初评否决且无翻案空间**：四法全负（−1.8~−2.4 JND）、guard 轨全负；任何分带组合都救不回——最好的单带是中间带 Gray-World（5.535→3.896，改善 1.64 < 1 JND=2.3），且同方法在低色温带灾难性劣化（5.21→20.09）；
2. **劣化机理明确**：春节钨丝灯场景（红衣/暖色物）内容主导全局统计，经典假设"场景平均灰"失效——估计法把场景内容误当光源过度校正到 ~2500K，相机 as_shot 的场景感知本质更强。这是方法族局限不是调参问题；
3. **分带洞察值得留档**：日光带 GE1 略优（6.66 vs 7.24）、中间带 GW 明显优（3.90 vs 5.54）——未来若上**学习型**光照组件，实证门槛已由 t43 数据设定："须显著优于 as_shot 且低色温带不崩"（可重启条件，见遗留 L-1 回填建议）。

---

## 4. 红线核对 ✅

| 红线 | 结果 |
|---|---|
| src 渲染零 diff | ✅ `git status` src/ 为空——本批次改动仅 model_licenses.json（根目录数据）/ scripts/（illumination_est + README）/ tests/（3 文件）/ docs/（3 文档）/ .artifacts |
| 无新建 learned/ 目录 | ✅ 未建；本审计构造性验证临时建/删后零残留（git status 复核） |
| 全量回归绿 | ✅ QA 复跑 **1334 passed / 5 skipped / 1 xfailed**（243.7s；5 skip 含隔离门预铺 1）与 t43 交付一致 |

---

## 5. 遗留清单

| # | 级别 | 内容 | 责任方 |
|---|---|---|---|
| L-1 | P3 | PROMOTION"无转正价值记录"表仍是空模板：t43 四法结论已留档 .artifacts/illumination_eval.{md,json}，但"可重启条件"栏未按模板回填——建议补一行（经典法族合并记录，可重启条件 = 学习型方法满足"显著优于 as_shot + 低色温带不崩"门槛） | 维护批次 |
| L-2 | P3 | GOVERNANCE env 清单非穷尽（GSAM_DINO / SEGMENTER_WARMUP / CAL_* / DSH_* 未入表）；三类命名规则可覆盖，建议维护批次补完整盘点 | 维护批次 |
| L-3 | P3 | guard 阈值 2500K 为首跑经验值、触发率低（guard 轨 ≈ 主轨，仅少量照片如 DSC_5244 偏离 6474K 触发）；未来再做降级演示时按估计-实际 CCT 差分布校准阈值。不影响本轮否决结论（更严 guard 只会确认负收益） | 阶段三后续 |
| L-4 | P3 | 承接 t42 上报：model_licenses.json 与 src/pixo/manifests/vision_models.json 的 license 口径不一致（aesthetic-scorer 一边 MIT 一边"需核验"），维护批次对齐 | 维护批次 |
| 观察 | — | 隔离门在 learned/ 落地前于 CI 恒 SKIPPED——其有效性已由 3 项自检 + 本审计红态实跑双重确认，skip 语义即治理承诺（目录落地自动生效），无需动作 | — |

---

## 6. 复核动作清单（证据可复现）

```bash
# 门① 构造性验证：import tests/unit/test_model_licenses.py::_license_gate_errors
#   合成 CC-BY-NC-4.0+true / 复合文案+true / 缺字段 / MIT+true 正例 / 真实 manifest 3 条 NC 翻转
# 门② 三态：mkdir learned/ + torch 懒 import 文件 → pytest FAIL；仅 numpy → PASS；rm -rf → SKIP
# 门③④：grep -rn "PIXO_[A-Z_]*" src/ 对照 GOVERNANCE §1.1 表；grounded_sam.py:38-40 truthy 集
# t43 性质：scripts/illumination_est 下合成 e=[1.25,1.0,0.72] 断言（均值/max/饱和排除，误差 ~1e-16）
# t43 单测：python -m pytest tests/unit/test_illumination_est.py   # 14 passed
# 红线：git status --porcelain -- src/（空）；python -m pytest tests/unit tests/regression tests/integration
#   → 1334 passed / 5 skipped / 1 xfailed
```

判定基线 `f49d3fc` + t42/t43 工作区批次（model_licenses.json / scripts/illumination_est/ / tests/×3 / docs/×3 / .artifacts/illumination_eval.*）。
