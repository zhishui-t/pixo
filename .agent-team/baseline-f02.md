# F02 全量测试基线存证（2026-09-07）

> 队长执行（额度纪律：全量回归队长统一执行）；qa 复核签认见文末。

## 命令
```
python -m pytest tests -q -m "not e2e"
```
工作树：master @ f357b35（干净，与 origin/master 同步）

## 结果
**1396 passed / 5 skipped / 1 xfailed —— 240.36s，exit 0**

Warnings（13 条，均为第三方库噪音，非阻断）：
- fastapi testclient StarletteDeprecationWarning（httpx 弃用提示）
- test_calib_optimize.py:242 torch requires_grad UserWarning（1 条）
- test_rfdetr_person.py torch.jit.script DeprecationWarning（11 条）

## 与历史基线对比
| 时点 | 结果 | 来源 |
|------|------|------|
| 2026-08-26 | 910 passed / 4 skipped / 1 xfailed | changelog.md:40 |
| 2026-09-04 | 1231 passed / 4 skipped / 1 xfailed | .artifacts/stage1_qa_verdict.md §6 |
| **2026-09-07（本次）** | **1396 passed / 5 skipped / 1 xfailed** | 本文件 |

增量 +165 passed：09-05 批次（8f4c582/c1e6fe2/f4a51db/f357b35）新增测试未落盘存证，本次补上。skipped 4→5（新增 1 skip，预计为条件缺数据的 gate_e2e 类，qa 总审时核对 skip 清单）。

## 本轮战役回归基线
后续所有批次（F03~F20）的全量回归以 **1396 passed / 5 skipped / 1 xfailed** 为不降基线。

## qa 复核
- [x] **qa 签认 2026-09-07T01:03:32+08:00**——独立复跑 `python -m pytest tests -q -m "not e2e" -rs`：
  **1396 passed / 5 skipped / 1 xfailed，191.48s**，与队长存证一致；基线采认。
  skip 清单（5 项全良性）：① test_gate_e2e_ab.py:20 RAW_PATH 未设 ② test_gate_e2e_perf.py:49
  RAW_PATH 未设 ③ **test_learned_isolation.py:48 learned/ 目录未建（4→5 的新增项，3bcccd3
  09-04 23:11 阶段三首块预铺隔离门，晚于 09-04 终审运行落库，目录落地即生效）**
  ④ test_proxy_metrics.py:113 空参数集（语料未注入 env） ⑤ test_sapiens_body.py:267
  无本地 sapiens 权重。明细见 golden-reverify.md §7。
