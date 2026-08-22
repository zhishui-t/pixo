# Pixo DSH 工具插件（pixo.*）

P2-1 交付：DSH 侧的 `pixo.*` 工具薄封装。插件本身只发 HTTP 请求到本机
`pixo-service`，不复制渲染/视觉/决策逻辑。

## 文件

| 文件 | 说明 |
|---|---|
| `pixo/dsh/pixo-tools.mjs` | DSH 插件（ESM），注册全部 `pixo.*` 工具 |
| `pixo/dsh/test-pixo-tools.mjs` | Node 内置测试，mock service 验证 schema/参数/返回 |
| `render/tests/test_dsh_plugin.py` | pytest 入口，跑 Node 测试 + 静态工具名校验 |

## 工具映射

插件默认服务地址：`http://127.0.0.1:9777`。

| 工具 | HTTP | 路径 | 主要参数 |
|---|---|---|---|
| `pixo.vision.health` | GET | `/api/health` | 无 |
| `pixo.vision.segment` | POST | `/api/vision/segment` | `image_id`, `prompts[]` |
| `pixo.vision.measure` | POST | `/api/vision/measure` | `image_id`, `region?`, `metrics[]?` |
| `pixo.meta.extract` | POST | `/api/meta/extract` | `path`, `strip_gps?`, `include_gps?` |
| `pixo.render.preview` | POST | `/api/render/preview` | `image_id`, `params?`, `long_edge?` |
| `pixo.render.final` | POST | `/api/render/final` | `image_id`, `output_dir?`, `fmt?` |
| `pixo.decide.decide` | POST | `/api/photos/{photo_id}/decide` | `photo_id` |
| `pixo.state.get` | GET | `/api/photos/{photo_id}` | `photo_id` |
| `pixo.state.history` | GET | `/api/photos/{photo_id}/timeline` | `photo_id` |
| `pixo.review.submit` | POST | `/api/review/submit` | `photo_id`, `reason`, `decision?` |
| `pixo.trace.query` | GET | `/api/photos/{photo_id}/timeline?param=...&event_type=...` | `photo_id`, `param?`, `event_type?` |

> 当前 `pixo-service` 一期已实现部分基础 API；插件按 §6.2 工具表预留上述
> 端点，后续 P1-6 补齐 service 路由即可直接使用，无需改插件。

## 安装 / 热加载

按本机已验证的 DSH 热加载流程：

1. 启动 pixo-service：
   ```bash
   python -m pixo.service
   ```

2. 在 `~/.dsh/profiles/web/cordis.patch.yml` 增加 insert 块：
   ```yaml
   - insert:
       - id: pixo-tools
         name: 'file:///K:/work/project/pixo/pixo/dsh/pixo-tools.mjs'
         config:
           baseUrl: 'http://127.0.0.1:9777'
   ```

3. 若包管理器自动把 `pixo-tools` 加回 `dsh.profile.bundles`，请再次从
   bundles 移除，避免重复注入（与 cleverer-dsh 等热加载插件同一约定）。

4. 重新加载 DSH Web；若工具未出现，`touch ~/.dsh/profiles/web/cordis.patch.yml`
   强制 HMR 重应用。

5. 在 DSH 工具列表确认出现：
   `pixo.vision.health`、`pixo.vision.segment`、`pixo.vision.measure`、
   `pixo.meta.extract`、`pixo.render.preview`、`pixo.render.final`、
   `pixo.decide.decide`、`pixo.state.get`、`pixo.state.history`、
   `pixo.review.submit`、`pixo.trace.query`。

## 测试

```bash
node --test pixo/dsh/test-pixo-tools.mjs
python -m pytest render/tests/test_dsh_plugin.py -q
```

测试覆盖：
- 必需工具全部注册；
- 每个工具都有 description / parameters / output / execute；
- mock pixo-service：健康检查 GET、分割 POST body、状态 GET 路径参数、
  trace 查询参数、非 2xx 错误透传。
