# Pixo —— AI 主导的迭代式 RAW 修图引擎

> 测量(measure) → 决策(decide) → 渲染(render) → 质检(QC) → 反馈再入环：
> 所有模块参与同一闭环，AI 出建议、规则护栏兜底、用户锁定优先。

## 这是什么

Pixo 是一套自研 RAW 照片渲染与 AI 修图系统：

- **渲染引擎**（`src/pixo/render`）：DNG 对齐解码 → 13 阶段管线
  （曝光标定/白平衡/HSL/colorcal/skin/stylize/refine…）→ gamma 输出；
  支持 .cube LUT 惰性加载、暗房主题工作台。
- **视觉**（`src/pixo/vision`）：多模型分割路由（UniFace/RF-DETR/SegFormer/Sapiens
  + 可选 GroundedSAM；AGPL 依赖已清零，t110）、7 维美学评分器
  （CLIP backbone，MIT 权重已部署+常驻预热）、轻量代理指标三件套。
- **决策**（`src/pixo/decide`）：确定性规则引擎——原生 AND/between 条件、
  优先级链（用户锁定＞偏好＞风格卡＞默认）、参数锁定、step_decay 收敛；
  公式守卫已日落清零（CI 哨兵防回退），exposure 动作算术在册保留。
- **知识**（`src/pixo/know`）：摄影六域知识图谱（63+ 节点）、风格卡
  （柯达/富士/哈苏/电影/黑白系 LUT 卡持续扩充）、RAG 混合检索。
- **闭环**（`src/pixo/pipeline`）：SinglePhotoLoop——measure→decide→
  preview×N→FINAL_QC，美学维度可参与达标/停滞终止。
- **LLM 副驾**（`src/pixo/agent`）：dsh.chat 真客户端（可降级）、参数补丁
  五段校验闸门（LLM 建议进系统的唯一入口）、suggest 编排、llm_review 审核报表。

## 快速开始

```bash
pip install -e ".[dev]"          # 或 pip install -r requirements.txt
python -m pytest -q              # 全量回归（当前 862 passed 基线）
uvicorn pixo.service.app:create_app --factory   # 服务（如已接）
cd frontend && npm install && npm run dev       # 暗房主题工作台
```

## 语料与标定

尼康 Z 系列 RAW 标定语料（多场景实拍 3400+ 张：日常/节庆/旅拍，
含高调、夜景、海滨大光比等覆盖），分层抽样工具支持 `--samples-per-scene`
复跑：

- `docs/metrics/proxy_distribution.md` —— 三代理指标分布
- `docs/metrics/scorer_distribution.md` —— 真 7 维评分分布
- `docs/metrics/ab_regression.md` —— 全语料 A/B 回归分带统计

## 文档索引

- [`docs/architecture.md`](docs/architecture.md) —— 架构总览
- [`docs/PIXO_ITERATIVE_LOOP_PLAN.md`](docs/PIXO_ITERATIVE_LOOP_PLAN.md) —— 迭代修图重构计划（Phase 0-4 + 知识库）
- [`docs/tech_debt.md`](docs/tech_debt.md) —— 技术债台账（#10-#12 为当前已知限定）
- [`configs/rules/`](configs/rules/) · [`configs/knowledge/`](configs/knowledge/) · [`configs/styles/films/`](configs/styles/films/) —— 规则/知识/风格卡
