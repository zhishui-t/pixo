/**
 * pixo-tools 插件最小测试：mock pixo-service 调用。
 *
 * 运行：node --test pixo/dsh/test-pixo-tools.mjs
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { TOOL_DEFINITIONS, apply } from './pixo-tools.mjs'

const BASE = 'http://127.0.0.1:8000'

// 与 service/app.py 真实路由一一对应（GET /api/health、
// POST /api/photos/{photo_id}/decide、GET /api/photos/{photo_id}、
// GET /api/photos/{photo_id}/timeline）。
const REQUIRED_TOOLS = [
  'pixo.vision.health',
  'pixo.decide.decide',
  'pixo.state.get',
  'pixo.state.history',
]

// 已删除的死端点 / 重复工具，防止回归。
const REMOVED_TOOLS = [
  'pixo.vision.segment',
  'pixo.vision.measure',
  'pixo.meta.extract',
  'pixo.render.preview',
  'pixo.render.final',
  'pixo.review.submit',
  'pixo.trace.query',
]

const REMOVED_PATHS = [
  '/api/vision/segment',
  '/api/vision/measure',
  '/api/meta/extract',
  '/api/render/preview',
  '/api/render/final',
  '/api/review/submit',
]

function makeContext() {
  const registered = []
  const ctx = {
    logger: { info() {} },
    tools: {
      register(def) {
        registered.push(def)
      },
    },
    effect(fn) {
      fn()
    },
  }
  return { ctx, registered }
}

function mockFetchImpl(handler) {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init })
    return handler(url, init, calls)
  }
  return {
    calls,
    restore() {
      globalThis.fetch = original
    },
  }
}

test('registers exactly the required pixo.* tools', () => {
  const { ctx, registered } = makeContext()
  apply(ctx, { baseUrl: BASE })
  const names = registered.map((t) => t.name)
  for (const name of REQUIRED_TOOLS) {
    assert.ok(names.includes(name), `missing tool: ${name}`)
  }
  for (const name of REMOVED_TOOLS) {
    assert.ok(!names.includes(name), `removed tool still registered: ${name}`)
  }
  assert.equal(names.length, REQUIRED_TOOLS.length)
  // 每个工具只允许打真实存在的路由。
  for (const tool of TOOL_DEFINITIONS) {
    assert.ok(!REMOVED_PATHS.includes(tool.path),
      `tool ${tool.name} hits removed endpoint ${tool.path}`)
  }
})

test('each registered tool has schema/output/execute', () => {
  const { ctx, registered } = makeContext()
  apply(ctx, { baseUrl: BASE })
  for (const tool of registered) {
    assert.equal(typeof tool.description, 'string')
    assert.equal(tool.parameters.type, 'object')
    assert.equal(typeof tool.execute, 'function')
    assert.equal(tool.output.schema.type, 'object')
  }
})

test('pixo.vision.health calls GET /api/health', async () => {
  const fake = mockFetchImpl(async () => ({
    ok: true,
    status: 200,
    statusText: 'OK',
    text: async () => JSON.stringify({
      status: 'ok',
      vision: { ready: false },
    }),
  }))
  try {
    const { ctx, registered } = makeContext()
    apply(ctx, { baseUrl: BASE })
    const tool = registered.find((t) => t.name === 'pixo.vision.health')
    const result = await tool.execute({})
    assert.equal(fake.calls.length, 1)
    assert.equal(fake.calls[0].url, `${BASE}/api/health`)
    assert.equal(fake.calls[0].init.method, 'GET')
    assert.equal(result.vision.ready, false)
  } finally {
    fake.restore()
  }
})

test('pixo.decide.decide posts to /api/photos/{photo_id}/decide', async () => {
  const fake = mockFetchImpl(async () => ({
    ok: true,
    status: 200,
    statusText: 'OK',
    text: async () => JSON.stringify({ decision: 'accept' }),
  }))
  try {
    const { ctx, registered } = makeContext()
    apply(ctx, { baseUrl: BASE })
    const tool = registered.find((t) => t.name === 'pixo.decide.decide')
    const result = await tool.execute({ photo_id: 'p1' })
    assert.equal(fake.calls[0].url, `${BASE}/api/photos/p1/decide`)
    assert.equal(fake.calls[0].init.method, 'POST')
    assert.equal(result.decision, 'accept')
  } finally {
    fake.restore()
  }
})

test('pixo.state.get substitutes photo_id path param', async () => {
  const fake = mockFetchImpl(async () => ({
    ok: true,
    status: 200,
    statusText: 'OK',
    text: async () => JSON.stringify({ photo: { photo_id: 'p1' } }),
  }))
  try {
    const { ctx, registered } = makeContext()
    apply(ctx, { baseUrl: BASE })
    const tool = registered.find((t) => t.name === 'pixo.state.get')
    await tool.execute({ photo_id: 'p1' })
    assert.equal(fake.calls[0].url, `${BASE}/api/photos/p1`)
  } finally {
    fake.restore()
  }
})

test('pixo.state.history calls GET /api/photos/{photo_id}/timeline', async () => {
  const fake = mockFetchImpl(async () => ({
    ok: true,
    status: 200,
    statusText: 'OK',
    text: async () => JSON.stringify({ events: [] }),
  }))
  try {
    const { ctx, registered } = makeContext()
    apply(ctx, { baseUrl: BASE })
    const tool = registered.find((t) => t.name === 'pixo.state.history')
    await tool.execute({ photo_id: 'p1' })
    assert.equal(fake.calls[0].url, `${BASE}/api/photos/p1/timeline`)
    assert.equal(fake.calls[0].init.method, 'GET')
  } finally {
    fake.restore()
  }
})

test('non-ok service response is surfaced as error', async () => {
  const fake = mockFetchImpl(async () => ({
    ok: false,
    status: 503,
    statusText: 'Service Unavailable',
    text: async () => 'model not ready',
  }))
  try {
    const { ctx, registered } = makeContext()
    apply(ctx, { baseUrl: BASE })
    const tool = registered.find((t) => t.name === 'pixo.vision.health')
    await assert.rejects(() => tool.execute({}), /503/)
  } finally {
    fake.restore()
  }
})
