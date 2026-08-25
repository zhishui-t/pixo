# 摄影知识包（Knowledge Packs）

`configs/knowledge/*.json` 是 Pixo 迭代修图的知识层，由 `pixo.know.registry` 自动扫描并入库。

## 文件清单

| 文件 | 域 | 说明 |
|---|---|---|
| photography_capture_post.json | 拍摄×后期 | 前期手段与后期代价 |
| photography_tone.json | 影调 | 曝光/影调策略与工序 |
| photography_hue.json | 色相 | 色偏病因→调色动作→边界 |
| photography_post2.json | 后期方法论 | 流程与方法 |

## Schema

顶层为 `{"nodes":[...],"edges":[...]}`。

- **node**：`{"id","type","label","keywords","content"}`；keywords 3-6 个；content ≤80 字；**id 全库唯一**。
- **edge**：`{"id","from","to","relation","weight","content"}`；weight 取 0-1；跨包引用合法，from/to 必须能解析到全库任一包的节点 id。

## 发布约定（跨包边）

- 四个内容包之间存在**跨包边**（如 photography_capture_post.json 的 `e_overcast_post` 指向 tone 包的 `tone_st_blackpoint`）：含跨包边的包必须**同组提交、同组发布**，不允许单包先行变更落库。
- 后续新增跨包边时，须在所在包 JSON 顶部声明依赖元数据：`"_requires": ["tone"]`（数组列出被引用的包名）。registry 对未知顶层字段忽略不阻塞，该声明供人工与工具核对发布组合。

## 受控词表（后续新增包必须沿用）

### node type

`scene` / `light` / `capture` / `noise` / `tone` / `color_issue` / `action` / `boundary` / `strategy` / `style` / `camera` / `dcp` / `side_effect`

### edge relation

`策略` / `副作用` / `配套` / `病因` / `修正动作` / `边界` / `工序顺序` / `底层优先` / `技术路线` / `后期配套` / `方案对照`* / `场景风险`*

> \* 治理时自存量补入：`方案对照`（兄弟方法 A/B 对照，来源 photography_post2.json）、`场景风险`（场景诱发失误风险，来源 photography_post2.json）。其余十种为初始词表。

> 存量收敛记录（治理完成）：复合式"病因→动作"→`修正动作`、"动作→边界"→`边界`、"策略→动作"→`策略`；"前期配套"与"场景呼应"→`配套`；"噪声来源"→`修正动作`（同 issue→action 形状保持全库一致）；"流程先后"→`工序顺序`。现全库 relation 已全部落在受控词表内，原语义均保留于各边 content。
