# r16-stream-1 报告（dev-1）— plant 提亮的溢出负联动（规则层事前门控）

> 2026-09-07 · R15 遗留清偿。零引擎/loop 改动（双层防线：规则事前 + 引擎 S-4 事后并存）。

## 做了什么

### 1. 阈值定界（R15 54 张数据回挖，非拍脑袋）

对 54 张试水语料的 70 轮 plant 触发，计算**每样本溢出地板**（该图各轮
decide 时 preview_overflow_ratio 的最小值）：

| 组 | 溢出地板 | 说明 |
|---|---|---|
| 2 张回退图（DSC_5276/5277，pass→二超标） | **1.35% / 1.64%** | sky 压暗后仍持续的高溢出 |
| 中性图（QC 不受 region 影响） | **≤0.42%**（5241/5242/5240/5279/5278/5284/5260/5283 等） | 提亮落地后溢出回落 |
| 5288（中性，plant 面积 0.8%） | 7.28% | 例外——其 plant 作用亚 JND（面积 0.8%、lum 41~44），记录为接受 collateral |

**阈值取 1.0%（`preview_overflow_ratio lt 0.01`）**：位于回退地板（1.35%+）
与中性地板（≤0.42%）的实测间隙；同时与引擎 S-4 限流 datum（2.5%）同向
构成双层（事前不决定 → 事后不压制）。注意 2.5% 不可行：回退图的**再触发
轮** it2/it3 ovf 1.35~1.64% <2.5%，2.5% 门控拦不住回退落地轮（R15 数据
实测其 it1 本就被 S-4 压制、回退照样发生）。

### 2. 落地

| 文件 | 变更 |
|---|---|
| `src/pixo/decide/rules/region_rules.yaml` | plant 规则 condition 补 `preview_overflow_ratio lt 0.01` + 头注「溢出负联动 (R16)」依据段（数据/阈值/双层防线/sky 豁免理由） |
| `configs/rules/region_rules.yaml` | 镜像逐字节同步 |
| `tests/unit/test_decide_region_wiring.py` | plant 触发/reliable 闸用例 metrics 补 `preview_overflow_ratio: 0.0`（隔离拦截因素）；钉死断言扩展（plant 溢出门控 lt 0.01 在位 + **sky 豁免**断言——sky 条件不得含溢出门控）；**新增** `test_plant_rule_blocked_by_high_overflow`（≥1% 不触发/<1% 正常触发/.sky 压暗不受门控波及） |

sky 规则**不加**门控（裁决：压暗方向与溢出无关）——并以断言反向钉死
（sky 条件含溢出门控即翻红，防未来误加）。

## 2. 回放抽验（`.artifacts/_r16_region_overflow_gate_spot.py`，6 张 × 双轨）

| 样本（类别） | plant 触发轮 (触发时 ovf) | QC A→B | 判定 |
|---|---|---|---|
| DSC_5276（回退图） | **0 轮**（地板 1.64%） | pass → pass | **回退消除**：sky 压暗照常（fire 1 轮），plant 全程事前不触发 |
| DSC_5277（回退图） | **0 轮**（地板 1.35%） | pass → pass | **回退消除** |
| DSC_5241（高溢出中性） | 2 轮 @ 0%（it1 12.2% 被门控暂挡） | pass → pass | **延迟一轮恢复**——溢出回落 <1% 后正常提亮，非禁绝 |
| DSC_5240（高溢出中性） | 2 轮 @ 0%（it1 8.2% 暂挡） | pass → pass | 同上 |
| DSC_5280（低溢出中性） | 3 轮 @ 0.42% | escalate_2x → escalate_2x | **it1 即正常触发，门控零误伤**（其升降级与 plant 无关，双轨一致） |
| DSC_5288（collateral） | **0 轮**（地板 7.3% 永久 gated） | escalate_2x → escalate_2x | plant 面积 0.8%、作用亚 JND——接受 collateral，QC 与 R15 一致 |

Whipsaw 消除实证：DSC_5276/5277 的 plant 决定序列从 R15 的
「it1 决定+0.047 → 被限流压 0.0 → it2 再决定 +0.065」变为**全程零决定**
——事前不触发，事后无压制，S-4 引擎限流保留为最后防线。

## 3. 验证

```
python -m pytest tests/unit/test_decide_region_wiring.py tests/unit/test_tone_clarity_rules.py -q
→ 41 passed（含新增 test_plant_rule_blocked_by_high_overflow 与钉死断言扩展）
python .artifacts/_r16_region_overflow_gate_spot.py → 6 样本回放（上表）
```

## 4. 遗留

1. 5288 溢出地板 7.3% 永久 gated（plant 面积 0.8% 亚 JND，QC 与 R15 一致）
   ——接受 collateral；若未来语料出现「高溢出+大 plant 面积」真实内容图，
   阈值/条件再议。
2. 高溢出中性图（5241/5240）提亮延迟一轮——语义即「溢出回落后再提亮」，
   符合门控意图；对闭环收敛轮数的影响未观测（本轮 QC 终态不变），留下轮
   loop 收敛数据复核。
3. S-4 引擎豁免议题维持关闭：事前门控落地后 whipsaw 源头消除，引擎事后
   限流保留为第二层。
