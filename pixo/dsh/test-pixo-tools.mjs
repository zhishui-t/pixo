/**
 * pixo-tools 插件最小测试：mock pixo-service 调用。
 *
 * 运行：node --test pixo/dsh/test-pixo-tools.mjs
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { TOOL_DEFINITIONS, apply } from './pixo-tools.mjs'

const BASE = 'http://127.0.0.1:9777'

const REQUIRED_TOOLS = [
  'pixo.vision.health',
  'pixo.vision.segment',
  'pixo.vision.measure',
  'pixo.meta.extract',
  'pixo.render.preview',
  'pixo.render.final',
  'pixo.decide.decide',
  'pixo.state.get',
  'pixo.state.history',
  'pixo.review.submit',
  'pixo.trace.query',
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

test('registers all required pixo.* tools', () => {
  const { ctx, registered } = makeContext()
  apply(ctx, { baseUrl: BASE })
  const names = registered.map((t) => t.name)
  for (const name of REQUIRED_TOOLS) {
    assert.ok(names.includes(name), `missing tool: ${name}`)
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

test('pixo.vision.segment posts image_id and prompts', async () => {
  const fake = mockFetchImpl(async () => ({
    ok: true,
    status: 200,
    statusText: 'OK',
    text: async () => JSON.stringify({ masks: { face: 'mask_meta' } }),
  }))
  try {
    const { ctx, registered } = makeContext()
    apply(ctx, { baseUrl: BASE })
    const tool = registered.find((t) => t.name === 'pixo.vision.segment')
    const result = await tool.execute({ image_id: 'p1', prompts: ['face', 'sky'] })
    assert.equal(fake.calls[0].url, `${BASE}/api/vision/segment`)
    assert.equal(fake.calls[0].init.method, 'POST')
    const body = JSON.parse(fake.calls[0].init.body)
    assert.equal(body.image_id, 'p1')
    assert.deepEqual(body.prompts, ['face', 'sky'])
    assert.equal(result.masks.face, 'mask_meta')
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

test('pixo.trace.query adds query parameters', async () => {
  const fake = mockFetchImpl(async () => ({
    ok: true,
    status: 200,
    statusText: 'OK',
    text: async () => JSON.stringify({ events: [] }),
  }))
  try {
    const { ctx, registered } = makeContext()
    apply(ctx, { baseUrl: BASE })
    const tool = registered.find((t) => t.name === 'pixo.trace.query')
    await tool.execute({ photo_id: 'p1', param: 'Exposure', event_type: 'iteration' })
    const url = new URL(fake.calls[0].url)
    assert.equal(url.pathname, '/api/photos/p1/timeline')
    assert.equal(url.searchParams.get('param'), 'Exposure')
    assert.equal(url.searchParams.get('event_type'), 'iteration')
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
