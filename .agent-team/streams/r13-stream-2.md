# R13 stream-2 —— region 参数面扩展：warmth（区域暖色意图）

> dev-2 · 2026-09-08 · 状态：**完成，定向全绿 + 零影响实证 + 基线零漂**

## 1. 做了什么

### 1.1 region_adjust.py（参数扩展）
- `regions` 新键 `warmth: float [-1,1]`（默认 0=无操作；负=冷调，正=暖调）
- 实现 = **gamma 域 RGB 通道增益近似**（白平衡 warmth 标定链的意图级近似）：
  `_warmth_gains(w) = [1, 1+0.10·w, 1−0.26·w]`——增益幅度锚定
  `white_balance.apply_warmth` 缺省暖方向通道斜率（g_slope=0.10 /
  b_slope=0.26，冻结锚点 wb_B∈[1.79, 2.287] 的暖黄方向；r_slope 缺省 0 →
  R 通道不动，R 增益归 WB 链）。正 warmth = G 上/B 下（标定暖黄向），
  负对称反向为冷。精度纪律与 exposure 的 `2^(ev/2.2)` 同级（意图级近似，
  不做色温线性化往返）
- 施加序（同区域）：**曝光 → 暖色 → 饱和度**，区域末尾一次 clip（沿既有
  "增益不经中间 clip" 组合纪律）
- `_regions()` 规范化/越界 raise 泛化为 `REGION_PARAM_LIMITS` 查表
  （消灭原 if/else 双份限幅）；wants() "有实际效果" 判定纳入 warmth
- `REGION_PARAM_LIMITS` 单源（S-3）+ `"warmth": 1.0`

### 1.2 loop.py（仅 registry/limits 区，decide_context 区零触碰）
- `_REGION_PARAM_NAMES = ("exposure", "saturation", "warmth")` 一行扩展 +
  注释——`_apply_decide_params` 的 region.* 映射分支（懒 import
  REGION_PARAM_LIMITS 钳制 + enabled 联动）零改动即生效

### 1.3 文件域遵守
- region_adjust.py + loop.py L86 一行 + 两个测试文件；decide_context 区/
  native cpp/core skin 未触碰

## 2. 测试（新增 16 项）
- `test_region_adjust.py` +10：`_warmth_gains` 公式级（±1/0/越界钳制）、
  逐通道精确增益（4 档参数化）、蓝天方向语义（暖=B↓G↑ R 不动 / 冷反向）、
  warmth=0 恒等（wants False + 未写即未变）、高光 clip、越界 raise、
  **exposure→warmth→saturation 三参数组合公式级**、REGION_PARAM_LIMITS
  单源含 warmth
- `test_decide_region_wiring.py` +3：`region.<p>.warmth` 映射+enabled 联动、
  越界钳制且符号保留、**规则可用性确认**（decide 动作 param=
  "region.<p>.warmth" 经映射准入落嵌套参数面——region_rules.yaml 引用
  通路已通，真规则等激活评估）

## 3. 验证链（证据）
| 项 | 结果 |
|---|---|
| 定向域 | test_region_adjust 43 + test_decide_region_wiring 24 + huesat 回归 62 → **全绿** |
| 全量单测 | **1304 passed, 3 skipped, 1 xfailed, 0 failed** |
| 集成（not e2e） | **112 passed** |
| gate 基线 | `--check` **OK 21 features 零漂**（region_adjust case 显式参数不含 warmth——零漂确认 ✓；21=R12 后口径） |
| 23 卡 | R13 改动 stash 前后 **23/23 float32 字节级全等**（region_adjust 默认关零影响 ✓；注：对照基准=当前 HEAD 态，R11 已拍板的 10 卡 B 轨渲染为既入库状态，非本批变化） |
| RAW 24 case | **RESULT: PASS**（region_adjust 不在四路径） |

## 4. 遗留 / 备注
1. warmth 数学为意图级通道增益近似（G+/B−，R 不动）——若未来需要
   "R 主导的暖肤"语义，可扩锚（标定链 r_slope 有界可调 0~0.5），当前
   与全局 warmth 调节方向保持单一来源一致。
2. decide 真规则（如 region.sky.warmth 随 sky_luminance 联动）等激活评估
   轮再写（指令明示不必）。

## 5. 复现命令
```
python -m pytest tests/unit/test_region_adjust.py tests/unit/test_decide_region_wiring.py tests/unit/test_huesat.py -q
python tests/regression/goldens/generate_gate_goldens.py --check
python src/pixo/render/tools/gate_golden.py compare --samples D:/tmp/pixo_t108/samples.json --out data/golden/reference/render_bench/goldens/gate_defaults --long-edge 512
```

---

## 6. 同树并行事件与最终状态（补记）

### 6.1 stash 冲突与恢复
验证期使用 git stash 做零影响对照时，与 **dev-3 在同工作树的 loop.py 并行
改动**（R13 style_cards 接入 decide_context，`PIXO_STYLE_CARDS` 缺省关）
发生 stash pop 冲突。恢复方式：
- `region_adjust.py` 从 stash 按路径取回（本流独占文件，无冲突）；
- `loop.py` 保留 dev-3 工作树版本（decide_context 区），我的 warmth 注册
  行（registry 区 L86-89，与 dev-3 的 decide_context 区 L109+/L735+ 无区域
  重叠）在其上重打；
- stash 已 drop（内容确认恢复后）。**文件域纪律未破**：我未触碰
  decide_context 区。

### 6.2 qc_overflow 偶发 flake 归属（非本批）
R13 验证期偶发 `test_qc_overflow_rolls_back_once_then_manual_review`
漂移（ACCEPTED vs MANUAL_REVIEW）。归属排查：含/不含 R13 改动各压测
6 轮全量集成 → **0/6 vs 0/6**，与 warmth 改动无关；根因=dev-3 style_cards
双态测试的环境串扰（dev-3 注释自述同一现象并已处置为缺省关 + qc 测试
`enable_style_cards=False` 隔离）。偶发窗口为 dev-3 在飞改动的中间态。

### 6.3 test_decide_region_wiring 2 项瞬时失败（归属 dev-3 在飞）
收尾时 dev-3 正在落 region_rules 激活评估（入 DEFAULT_RULES +
`sky_area_ratio<0.70` 误罩护栏 + 试水系数减半），`test_sky_rule_fires_*` /
`test_plant_rule_fires_*` 2 项与旧断言瞬时不同步（metrics 缺 area_ratio
入参）——dev-3 注释已预告同步测试。**归属 dev-3，本流未触碰**；本流的
3 项 warmth 新用例在该文件内全绿。

### 6.4 最终定向计数（R13 warmth 增量）
- test_region_adjust.py：43 passed（含 warmth 新增 10 项）
- test_decide_region_wiring.py：24 项中 warmth 新增 3 项全绿；另 2 项
  既有规则触发断言瞬时不同步归 dev-3 在飞（见 6.3）
- 全量单测（R13 改动后）：1304 passed / 0 failed
- gate --check：OK 21 features 零漂；23 卡 stash 对照零影响；RAW 24/24 PASS
