# rawlab/legacy —— 归档模块(2026-08 审核后归档)

被新引擎 (`rawlab.engine`) 或外部流程替代的历史代码, 保留以追溯旧验收结论。

| 文件 | 原职责 | 替代 |
|---|---|---|
| `rag.py` | RAG 风格知识库(词袋检索 + 风格推荐) | 阶段6 验收产物; 后续走外部方案 |
| `cal_step1/2/3.py` | 旧曝光/中性/肤色三步标定脚本 | `engine/calibration.py` + `tools/fit_neutral_trim.py` |
| `send_to_feishu.py` / `send_compare.py` | 飞书发图(个人脚本, 顶层裸代码) | 手动/外部工具 |

⚠️ 这些脚本含本机硬编码路径(Adobe 目录/个人账户/私照库), 仅作历史参考, 不在验收链上, 不保证可移植。
