/**
 * pixo-tools — DSH 工具插件（pixo.* 薄封装）
 *
 * 本插件只做 HTTP 薄封装，调用本机 pixo-service（默认
 * http://127.0.0.1:8000，见 service/__main__.py 的 uvicorn 端口），
 * 不在 DSH 端重复 Pixo 引擎逻辑。
 *
 * 注册方式（与 cleverer-dsh 热加载一致）：
 *   在 ~/.dsh/profiles/web/cordis.patch.yml 增加 insert 块：
 *   - insert:
 *       - id: pixo-tools
 *         name: 'file:///<PIXO_REPO>/src/pixo/dsh/pixo-tools.mjs'
 *         config:
 *           baseUrl: 'http://127.0.0.1:8000'
 *   并从 dsh.profile.bundles 移除 pixo-tools 包，避免重复注入。
 *   热加载后若未出现，touch cordis.patch.yml 强制 HMR 重应用。
 *
 * 零依赖纯 ESM（Node 内置 fetch/URL）。
 */

export const name = 'pixo-tools'
export const inject = ['tools']

// 与 service/__main__.py 的 uvicorn.run(host="127.0.0.1", port=8000) 一致。
export const DEFAULT_BASE_URL = 'http://127.0.0.1:8000'

const OUTPUT_RENDER = (_args, value) => [{
  type: 'text',
  text: typeof value === 'string' ? value : JSON.stringify(value, null, 2),
}]

const OBJECT_SCHEMA = {
  type: 'object',
  additionalProperties: true,
}

function buildUrl(baseUrl, tool, args) {
  let path = tool.path || ''
  for (const key of (tool.pathParams || [])) {
    const value = String(args[key] ?? '')
    path = path.replace(`{${key}}`, encodeURIComponent(value))
  }
  const url = new URL(path.replace(/^\//, ''), baseUrl.replace(/\/$/, ''))
  for (const key of (tool.queryParams || [])) {
    if (args[key] !== undefined && args[key] !== null && args[key] !== '') {
      url.searchParams.set(key, String(args[key]))
    }
  }
  return url
}

function buildBody(tool, args) {
  const body = {}
  for (const key of (tool.bodyFields || [])) {
    if (args[key] !== undefined) {
      body[key] = args[key]
    }
  }
  return Object.keys(body).length > 0 ? body : undefined
}

async function callService(baseUrl, tool, args) {
  const url = buildUrl(baseUrl, tool, args)
  const body = buildBody(tool, args)
  const init = {
    method: tool.method || 'GET',
    headers: { 'Content-Type': 'application/json' },
  }
  if (body !== undefined) {
    init.body = JSON.stringify(body)
  }
  const res = await fetch(url, init)
  const text = await res.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = text
    }
  }
  if (!res.ok) {
    throw new Error(`pixo-service ${res.status}: ${text || res.statusText}`)
  }
  if (tool.response !== undefined) {
    return tool.response(data)
  }
  return data
}

// 只保留 service/app.py 中真实存在的路由（GET /api/health、
// POST /api/photos/{photo_id}/decide、GET /api/photos/{photo_id}、
// GET /api/photos/{photo_id}/timeline）。
export const TOOL_DEFINITIONS = [
  {
    name: 'pixo.vision.health',
    description: '查询 Pixo Vision 各模型健康状态（可用性/版本/加载状态）。',
    method: 'GET',
    path: '/api/health',
    parameters: {
      type: 'object',
      properties: {},
      required: [],
    },
  },
  {
    name: 'pixo.decide.decide',
    description: '触发/查询一轮 Pixo Decide 决策。',
    method: 'POST',
    path: '/api/photos/{photo_id}/decide',
    parameters: {
      type: 'object',
      properties: {
        photo_id: { type: 'string', description: '照片 ID' },
      },
      required: ['photo_id'],
    },
    pathParams: ['photo_id'],
  },
  {
    name: 'pixo.state.get',
    description: '获取照片当前状态。',
    method: 'GET',
    path: '/api/photos/{photo_id}',
    parameters: {
      type: 'object',
      properties: {
        photo_id: { type: 'string', description: '照片 ID' },
      },
      required: ['photo_id'],
    },
    pathParams: ['photo_id'],
  },
  {
    name: 'pixo.state.history',
    description: '获取照片状态机/Trace 事件流。',
    method: 'GET',
    path: '/api/photos/{photo_id}/timeline',
    parameters: {
      type: 'object',
      properties: {
        photo_id: { type: 'string', description: '照片 ID' },
      },
      required: ['photo_id'],
    },
    pathParams: ['photo_id'],
  },
]

export function apply(ctx, config = {}) {
  const baseUrl = (config.baseUrl || DEFAULT_BASE_URL).replace(/\/$/, '')
  ctx.logger?.info?.('pixo-tools: loading pixo.* tool plugin')

  ctx.effect(() => {
    for (const tool of TOOL_DEFINITIONS) {
      ctx.tools.register({
        name: tool.name,
        description: tool.description,
        parameters: tool.parameters,
        output: {
          schema: OBJECT_SCHEMA,
          render: OUTPUT_RENDER,
        },
        async execute(args) {
          return callService(baseUrl, tool, args || {})
        },
      })
    }
  }, 'pixo-tools: register pixo.* tools')
}
