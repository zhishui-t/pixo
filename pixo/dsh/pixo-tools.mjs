/**
 * pixo-tools — DSH 工具插件（pixo.* 薄封装）
 *
 * 本插件只做 HTTP 薄封装，调用本机 pixo-service（默认
 * http://127.0.0.1:9777），不在 DSH 端重复 Pixo 引擎逻辑。
 *
 * 注册方式（与 cleverer-dsh 热加载一致）：
 *   在 ~/.dsh/profiles/web/cordis.patch.yml 增加 insert 块：
 *   - insert:
 *       - id: pixo-tools
 *         name: 'file:///K:/work/project/pixo/pixo/dsh/pixo-tools.mjs'
 *         config:
 *           baseUrl: 'http://127.0.0.1:9777'
 *   并从 dsh.profile.bundles 移除 pixo-tools 包，避免重复注入。
 *   热加载后若未出现，touch cordis.patch.yml 强制 HMR 重应用。
 *
 * 零依赖纯 ESM（Node 内置 fetch/URL）。
 */

export const name = 'pixo-tools'
export const inject = ['tools']

export const DEFAULT_BASE_URL = 'http://127.0.0.1:9777'

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
    name: 'pixo.vision.segment',
    description: '对指定图片执行分割，返回 prompt -> mask 元数据。',
    method: 'POST',
    path: '/api/vision/segment',
    parameters: {
      type: 'object',
      properties: {
        image_id: { type: 'string', description: '图片/会话 ID' },
        prompts: {
          type: 'array',
          items: { type: 'string' },
          description: '例如 ["face", "sky", "plant"]',
        },
      },
      required: ['image_id', 'prompts'],
    },
    bodyFields: ['image_id', 'prompts'],
  },
  {
    name: 'pixo.vision.measure',
    description: '对指定图片/区域执行测量，返回测量 JSON。',
    method: 'POST',
    path: '/api/vision/measure',
    parameters: {
      type: 'object',
      properties: {
        image_id: { type: 'string', description: '图片/会话 ID' },
        region: {
          type: 'object',
          description: '可选区域定义；缺省为全图',
        },
        metrics: {
          type: 'array',
          items: { type: 'string' },
          description: '可选测量项列表',
        },
      },
      required: ['image_id'],
    },
    bodyFields: ['image_id', 'region', 'metrics'],
  },
  {
    name: 'pixo.meta.extract',
    description: '提取 RAW/照片元数据（EXIF/相机/镜头/GPS 等）。',
    method: 'POST',
    path: '/api/meta/extract',
    parameters: {
      type: 'object',
      properties: {
        path: { type: 'string', description: 'RAW 文件路径' },
        strip_gps: { type: 'boolean', description: '是否剥离 GPS 隐私字段' },
        include_gps: { type: 'boolean', description: '是否返回 GPS 字段' },
      },
      required: ['path'],
    },
    bodyFields: ['path', 'strip_gps', 'include_gps'],
  },
  {
    name: 'pixo.render.preview',
    description: '渲染低分辨率预览（支持参数 patch 与长边）。',
    method: 'POST',
    path: '/api/render/preview',
    parameters: {
      type: 'object',
      properties: {
        image_id: { type: 'string', description: '图片/会话 ID' },
        session_id: { type: 'string', description: '预览会话 ID（可选）' },
        params: {
          type: 'object',
          description: '渲染参数 patch',
        },
        long_edge: {
          type: 'number',
          description: '预览长边像素，默认 1024',
        },
      },
      required: ['image_id'],
    },
    bodyFields: ['image_id', 'session_id', 'params', 'long_edge'],
  },
  {
    name: 'pixo.render.final',
    description: '执行全分辨率最终渲染并导出。',
    method: 'POST',
    path: '/api/render/final',
    parameters: {
      type: 'object',
      properties: {
        image_id: { type: 'string', description: '图片/会话 ID' },
        session_id: { type: 'string', description: '预览会话 ID（可选）' },
        output_dir: { type: 'string', description: '导出目录' },
        fmt: { type: 'string', description: '输出格式，如 jpeg/webp/tiff16' },
      },
      required: ['image_id'],
    },
    bodyFields: ['image_id', 'session_id', 'output_dir', 'fmt'],
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
  {
    name: 'pixo.review.submit',
    description: '提交人工复核请求（必须带 reason）。',
    method: 'POST',
    path: '/api/review/submit',
    parameters: {
      type: 'object',
      properties: {
        photo_id: { type: 'string', description: '照片 ID' },
        reason: { type: 'string', description: '升级人工复核原因' },
        decision: { type: 'string', description: '可选：accept/reject/edit' },
        confidence: { type: 'number', description: '可选置信度' },
      },
      required: ['photo_id', 'reason'],
    },
    bodyFields: ['photo_id', 'reason', 'decision', 'confidence'],
  },
  {
    name: 'pixo.trace.query',
    description: '按 photo_id/param/event_type 查询参数溯源链。',
    method: 'GET',
    path: '/api/photos/{photo_id}/timeline',
    parameters: {
      type: 'object',
      properties: {
        photo_id: { type: 'string', description: '照片 ID' },
        param: { type: 'string', description: '可选参数名过滤' },
        event_type: { type: 'string', description: '可选事件类型过滤' },
      },
      required: ['photo_id'],
    },
    pathParams: ['photo_id'],
    queryParams: ['param', 'event_type'],
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
