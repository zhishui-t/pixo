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

## 受控词表（后续新增包必须沿用）

### node type

`scene` / `light` / `capture` / `noise` / `tone` / `color_issue` / `action` / `boundary` / `strategy` / `style` / `camera` / `dcp` / `side_effect`

### edge relation

`策略` / `副作用` / `配套` / `病因` / `修正动作` / `边界` / `工序顺序` / `底层优先` / `技术路线` / `后期配套`

> 注：存量包中存在词表外 relation（如复合式"病因→动作""动作→边界""策略→动作"，以及"前期配套""噪声来源""方案对照""场景风险""场景呼应""流程先后"），本次仅约束新增内容，存量收敛另行任务处理。
