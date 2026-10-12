import { test } from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { apply, inject, name, toDsl } from '../index.js'

const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms))
const until = async (cond, what = 'condition', ms = 4000) => {
  const t0 = Date.now()
  while (!cond()) {
    if (Date.now() - t0 > ms) assert.fail(`timed out waiting for ${what}`)
    await tick(10)
  }
}
const TOOL_NAMES = ['xmuse_whoami', 'xmuse_send', 'xmuse_inbox', 'xmuse_ack', 'xmuse_thread', 'xmuse_leave_thread', 'xmuse_context', 'xmuse_done']

/** handler(url, body, req) -> [code, obj] | Promise of the same. */
function fakeHub(handler) {
  const seen = []
  const server = http.createServer((req, res) => {
    let b = ''
    req.on('data', (c) => (b += c))
    req.on('end', async () => {
      const body = JSON.parse(b || '{}')
      seen.push({ url: req.url, auth: req.headers.authorization, session: req.headers['x-xmuse-session'], body })
      const [code, obj] = await handler(req.url, body, req)
      if (res.destroyed) return
      res.writeHead(code, { 'content-type': 'application/json' })
      res.end(JSON.stringify(obj))
    })
  })
  const close = () => { server.closeAllConnections?.(); server.close() }
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve({ server, seen, port: server.address().port, close })))
}

/** A hub whose relay endpoints behave like the real one: unreported deliveries stay pollable. */
async function relayHub({ deliveredFail = 0 } = {}) {
  const st = { queue: [], delivered: new Set(), deliveredCalls: [], polls: [], deliveredFail, bound: {}, binds: [], unbinds: [] }
  const h = await fakeHub(async (url, body, req) => {
    const tok = req.headers.authorization, sess = req.headers['x-xmuse-session']
    if (url === '/v1/relay/bind') {
      if (st.rejectBind) return [200, { error: { code: 'invalid_arguments', message: st.rejectBind } }]
      const replaced = st.bound[tok] && st.bound[tok] !== body.session_id ? st.bound[tok] : null
      st.bound[tok] = body.session_id
      st.binds.push(body.session_id)
      return [200, { result: { bound: body.session_id, replaced } }]
    }
    if (url === '/v1/relay/unbind') {
      st.unbinds.push(sess)
      const old = st.bound[tok] ?? null
      delete st.bound[tok]
      return [200, { result: { unbound: old } }]
    }
    if ((url.startsWith('/v1/relay/') || url.startsWith('/v1/tools/')) && st.bound[tok] !== sess) {
      return [200, { error: { code: 'not_bound_session', message: `this agent is bound to dsh session ${st.bound[tok]}` } }]
    }
    if (url === '/v1/relay/poll') {
      st.polls.push(body.cursor)
      const pending = st.queue.filter((i) => i.delivery_id > body.cursor && !st.delivered.has(i.delivery_id))
      if (!pending.length) { await tick(40); return [200, { result: { cursor: body.cursor, items: [], text: '' } }] }
      return [200, { result: { cursor: pending.at(-1).delivery_id, items: pending, text: `TEXT[${pending.map((i) => i.delivery_id)}]` } }]
    }
    if (url === '/v1/relay/delivered') {
      st.deliveredCalls.push(body)
      if (st.deliveredFail > 0) { st.deliveredFail--; return [500, { error: { code: 'boom', message: 'down' } }] }
      for (const id of body.delivery_ids) st.delivered.add(id)
      return [200, { result: { delivered: body.delivery_ids.length, session: body.session_id } }]
    }
    return [200, { result: { echo: url, args: body.args } }]
  })
  const add = (id) => st.queue.push({ delivery_id: id, message_id: id + 100, thread: 'dm:dsh-1+human', from: 'human', kind: 'message', mentions: [], wake: true })
  return { ...h, st, add }
}

const defaultHub = await relayHub() // for tests that only need /xmuse bind to succeed
test.after(() => defaultHub.close())

function setup({ hubPort = defaultHub.port, noHub = false, flushOk = true, resolveError = false, noSessionController = false, bindingsFile: bf, preAgents = [], toolsJson, extra = {} } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-bundle-'))
  fs.mkdirSync(path.join(dir, 'tokens'))
  if (hubPort && !noHub) fs.writeFileSync(path.join(dir, 'hub.json'), JSON.stringify({ port: hubPort, pid: 1 }))
  fs.writeFileSync(path.join(dir, 'tokens', 'dsh-1'), 'tok-dsh-1\n')
  fs.writeFileSync(path.join(dir, 'tokens', 'dsh-2'), 'tok-dsh-2\n')
  if (toolsJson) fs.writeFileSync(path.join(dir, 'tools.json'), toolsJson)
  const bindingsFile = bf ?? path.join(dir, 'bindings.json')

  const logs = []
  const commands = new Map()
  const listeners = {}
  const followups = []
  const flushed = []
  const agents = new Map()
  const disposers = []
  const t = { flushOk, order: [] }
  const mkAgent = (id) => {
    const tools = new Map()
    const agent = {
      id, session: { id },
      followup: (m) => { followups.push({ id, m }); t.order.push(`followup:${id}`) },
      ctx: {
        tools: { register: (tool) => { tools.set(tool.name, tool); return () => tools.delete(tool.name) } },
        effect: (fn) => fn(),
      },
      tools,
    }
    agents.set(id, agent)
    return agent
  }
  const ctx = {
    logger: { info: (m) => logs.push(['info', m]), warn: (m) => logs.push(['warn', m]) },
    effect: (fn) => { const off = fn(); if (typeof off === 'function') disposers.push(off); return off },
    on: (ev, fn) => { (listeners[ev] ||= []).push(fn); return () => {} },
    commands: { register: (c) => { commands.set(c.name, c); return () => commands.delete(c.name) } },
    agents: { roots: () => [...agents.values()] },
    sessions: { flush: async (s) => { flushed.push(s.id); t.order.push(`flush:${s.id}`); return typeof t.flushOk === 'function' ? t.flushOk() : t.flushOk } },
    ...(noSessionController ? {} : {
      sessionController: {
        resolveAgent: async (id) => (resolveError ? { error: new Error('session/not-found') } : agents.has(id) ? { agent: agents.get(id) } : { error: new Error('session/not-found') }),
      },
    }),
  }
  const emit = async (ev, payload) => { for (const fn of listeners[ev] || []) await fn(payload) }
  for (const id of preAgents) mkAgent(id)
  apply(ctx, { state: dir, bindingsFile, pollWaitS: 1, backoffMinMs: 20, backoffMaxMs: 80, ...extra })
  const run = (sessionId, rawInput) => commands.get('xmuse').handler({ agent: agents.get(sessionId) ?? { id: sessionId }, rawInput })
  const dispose = () => { for (const off of disposers) off() }
  Object.assign(t, { ctx, dir, bindingsFile, logs, commands, followups, flushed, agents, mkAgent, emit, run, dispose })
  return t
}
const readBindings = (f) => JSON.parse(fs.readFileSync(f, 'utf8'))

test('exports and command registration', async () => {
  assert.equal(name, 'xmuse')
  assert.deepEqual(inject, ['commands', 'agents', 'sessions', 'tools', 'sessionController', 'webServer'])
  const t = setup()
  assert.ok(t.commands.has('xmuse'))
  assert.equal(t.commands.get('xmuse').recordInput, false)
  t.dispose()
})

test('self-check logs services, hub state and tools, never throws', async () => {
  const { close, port } = await fakeHub(() => [200, {}])
  const t = setup({ hubPort: port })
  await tick()
  const line = t.logs.find(([, m]) => m.includes('self-check'))
  assert.ok(line, 'self-check log present')
  assert.match(line[1], /"sessionController":true/)
  assert.match(line[1], new RegExp(`ok \\(port ${port}\\)`))
  assert.match(line[1], /"tools":"8 from bundled tools.json"/)
  close()
  const bad = setup({ noSessionController: true, noHub: true })
  await tick()
  assert.match(bad.logs.find(([, m]) => m.includes('self-check'))[1], /"sessionController":false/)
  assert.match(bad.logs.find(([, m]) => m.includes('self-check'))[1], /unreadable/)
  t.dispose(); bad.dispose()
})

test('no config.state: no built-in machine path, the self-check says what to set', async () => {
  const saved = process.env.XMUSE_STATE_WIN
  delete process.env.XMUSE_STATE_WIN
  const t = setup({ extra: { state: '' } })
  await tick()
  const line = t.logs.find(([, m]) => m.includes('self-check'))[1]
  assert.match(line, /config\.state is not set/)
  assert.match(line, /xmuse doctor/)
  assert.match(line, /"tools":"8 from bundled tools.json"/)
  t.dispose()
  if (saved !== undefined) process.env.XMUSE_STATE_WIN = saved
})

test('ping delivers followup with source.kind xmuse and flushes', async () => {
  const t = setup()
  t.mkAgent('s1')
  const r = await t.run('s1', 'ping')
  assert.equal(r.kind, 'success')
  assert.equal(t.followups.length, 1)
  const m = t.followups[0].m
  assert.equal(m.source.kind, 'xmuse')
  assert.equal(m.content[0].type, 'text')
  assert.match(m.content[0].text, /^\[xmuse\] smoke delivery \d{4}-\d\d-\d\dT.*: reply "pong" in one line\.$/)
  assert.deepEqual(t.flushed, ['s1'])
  t.dispose()
})

test('ping failure modes return errors instead of throwing', async () => {
  const a = setup({ resolveError: true })
  a.mkAgent('s1')
  assert.equal((await a.run('s1', 'ping')).kind, 'error')
  const b = setup({ flushOk: false })
  b.mkAgent('s1')
  const r = await b.run('s1', 'ping')
  assert.equal(r.kind, 'error')
  assert.match(r.text, /did not acknowledge/)
  const c = setup({ noSessionController: true })
  c.mkAgent('s1')
  assert.match((await c.run('s1', 'ping')).text, /not available/)
  for (const x of [a, b, c]) x.dispose()
})

test('bind/unbind/status persist to file; usage errors; restart restores; legacy flat file loads', async () => {
  const t = setup()
  t.mkAgent('s1')
  assert.equal((await t.run('s1', 'bind')).kind, 'error')
  assert.equal((await t.run('s1', 'bind ../x')).kind, 'error')
  const r = await t.run('s1', ' bind dsh-1 ')
  assert.equal(r.kind, 'success')
  assert.deepEqual(readBindings(t.bindingsFile).bindings, { s1: 'dsh-1' })
  const s = await t.run('s1', 'status')
  assert.match(s.text, /s1 -> dsh-1/)
  assert.match(s.text, /relay: (polling|idle|error)/)
  assert.match(s.text, /sessionController: yes/)
  assert.match(s.text, /tools: 8 from bundled/)
  assert.equal((await t.run('s1', 'nope')).kind, 'error')
  assert.equal((await t.run('s1', '')).kind, 'error')
  // bindings survive a "restart"
  const t2 = setup({ bindingsFile: t.bindingsFile })
  await tick()
  assert.match((await t2.run('s1', 'status')).text, /s1 -> dsh-1/)
  t2.dispose()
  // unbind
  assert.equal((await t.run('s1', 'unbind')).kind, 'success')
  assert.deepEqual(readBindings(t.bindingsFile).bindings, {})
  assert.equal((await t.run('s1', 'unbind')).kind, 'error')
  assert.match((await t.run('s1', 'status')).text, /\(none\)/)
  // legacy 0.0.x flat file
  const legacy = path.join(t.dir, 'legacy.json')
  fs.writeFileSync(legacy, JSON.stringify({ s9: 'dsh-2' }))
  const t3 = setup({ bindingsFile: legacy })
  await tick()
  assert.match((await t3.run('s9', 'status')).text, /s9 -> dsh-2/)
  t.dispose(); t3.dispose()
})

test('bind persist failure does not throw', async () => {
  const t = setup()
  t.mkAgent('s1')
  fs.mkdirSync(t.bindingsFile) // a directory: writeFile fails
  const r = await t.run('s1', 'bind dsh-1')
  assert.equal(r.kind, 'success')
  assert.match(r.text, /write failed/)
  t.dispose()
})

// ---- tools ----

test('all 8 tools register per session with hub-derived schemas and unbound-safe descriptions', async () => {
  const t = setup()
  const agent = t.mkAgent('s1')
  await t.emit('agent/created', { agent })
  assert.deepEqual([...agent.tools.keys()], TOOL_NAMES)
  for (const tool of agent.tools.values()) assert.match(tool.description, /^Only for sessions the user bound with `\/xmuse bind/)
  const send = agent.tools.get('xmuse_send').parameters
  assert.equal(send.to.required, true)
  assert.equal(send.body.required, true)
  assert.equal(send.kind.required, undefined)
  assert.deepEqual(send.kind.enum.slice(0, 2), ['message', 'handoff'])
  assert.equal(send.mentions.type, 'array')
  assert.equal(send.mentions.items.type, 'string')
  assert.equal(send.why.type, 'object')
  assert.equal(send.why.additionalProperties, false)
  assert.equal(send.why.properties.what.type, 'string')
  assert.deepEqual(agent.tools.get('xmuse_whoami').parameters, {})
  const done = agent.tools.get('xmuse_done').parameters
  assert.equal(done.declares.items.additionalProperties, false)
  assert.equal(done.declares.items.properties.kind.required, true)
  assert.deepEqual(done.declares.items.properties.kind.enum, ['decision', 'assumption', 'question'])
  t.dispose()
})

test('tool specs: hub state tools.json wins, broken file falls back to the bundled copy', async () => {
  const custom = JSON.stringify([{ name: 'xmuse_whoami', description: 'x', inputSchema: { type: 'object', properties: {}, required: [] } }])
  const a = setup({ toolsJson: custom })
  const agentA = a.mkAgent('s1')
  await a.emit('agent/created', { agent: agentA })
  assert.deepEqual([...agentA.tools.keys()], ['xmuse_whoami'])
  const b = setup({ toolsJson: '{not json' })
  const agentB = b.mkAgent('s1')
  await b.emit('agent/created', { agent: agentB })
  assert.equal(agentB.tools.size, 8)
  assert.ok(b.logs.some(([l, m]) => l === 'warn' && /bundled copy/.test(m)))
  a.dispose(); b.dispose()
})

test('toDsl converts JSON Schema to the dsh author DSL', () => {
  assert.deepEqual(toDsl({ type: 'string', description: 'd', enum: ['a'] }, true), { type: 'string', description: 'd', required: true, enum: ['a'] })
  assert.deepEqual(toDsl({ type: 'object', properties: { a: { type: 'integer' } }, required: ['a'] }),
    { type: 'object', additionalProperties: true, properties: { a: { type: 'integer', required: true } } })
})

test('every tool proxies args to /v1/tools/<name> with the bound agent token and returns the result', async () => {
  const { close, seen, port } = await fakeHub((url, body) => [200, { result: { echo: url, args: body.args } }])
  const t = setup({ hubPort: port })
  const agent = t.mkAgent('s1')
  await t.emit('agent/created', { agent })
  for (const n of TOOL_NAMES) assert.match(await agent.tools.get(n).execute({}, {}), /\/xmuse bind/)
  assert.equal(seen.length, 0)
  await t.run('s1', 'bind dsh-1') // bound after agent/created
  const argsFor = {
    xmuse_whoami: {}, xmuse_send: { to: 'oc', body: 'hi', mentions: ['oc'], kind: 'message' }, xmuse_inbox: { unread_only: false },
    xmuse_ack: { ids: [1, 2], outcome: 'ok' }, xmuse_thread: { id: '#t', limit: 5 }, xmuse_leave_thread: { thread: '#t' }, xmuse_context: { topic: '#t' },
    xmuse_done: { summary: 's', next: 'none', declares: [{ kind: 'decision', statement: 'x' }] },
  }
  for (const n of TOOL_NAMES) {
    seen.length = 0
    const out = await agent.tools.get(n).execute(argsFor[n], {})
    assert.deepEqual(JSON.parse(out), { echo: `/v1/tools/${n}`, args: argsFor[n] })
    const call = seen.find((s) => s.url === `/v1/tools/${n}`)
    assert.equal(call.auth, 'Bearer tok-dsh-1')
    assert.equal(call.session, 's1', 'the tool sends the session it runs in')
    assert.deepEqual(call.body, { args: argsFor[n] })
  }
  t.dispose(); close()
})

test('tools: hub errors, missing token, hub down all return text', async () => {
  const { close, port } = await fakeHub((url) => url.startsWith('/v1/tools/')
    ? [200, { error: { code: 'forbidden', message: 'nope' } }] : [200, { result: {} }])
  const t = setup({ hubPort: port })
  const agent = t.mkAgent('s1')
  await t.emit('agent/created', { agent })
  const tool = agent.tools.get('xmuse_whoami')
  assert.equal((await t.run('s1', 'bind dsh-1')).kind, 'success')
  assert.match(await tool.execute({}, {}), /hub error forbidden: nope/)
  const ghost = await t.run('s1', 'bind ghost') // no token file: the bind fails and the old binding stays
  assert.equal(ghost.kind, 'error')
  assert.match(await tool.execute({}, {}), /hub error forbidden/)
  fs.rmSync(path.join(t.dir, 'tokens', 'dsh-1'))
  assert.match(await tool.execute({}, {}), /failed/)
  fs.writeFileSync(path.join(t.dir, 'tokens', 'dsh-1'), 'tok-dsh-1\n')
  close()
  assert.match(await tool.execute({}, {}), /failed/) // connection refused
  t.dispose()
})

test('identity: the hub must accept /xmuse bind; nothing is recorded locally otherwise', async () => {
  const hub = await relayHub()
  hub.st.rejectBind = 'dsh-1 is not a polled agent'
  const t = setup({ hubPort: hub.port })
  t.mkAgent('s1')
  const r = await t.run('s1', 'bind dsh-1')
  assert.equal(r.kind, 'error')
  assert.match(r.text, /hub did not accept the binding: hub error invalid_arguments: dsh-1 is not a polled agent/)
  assert.ok(!fs.existsSync(t.bindingsFile) || Object.keys(readBindings(t.bindingsFile).bindings).length === 0)
  assert.match((await t.run('s1', 'status')).text, /\(none\)/)
  assert.equal(hub.st.polls.length, 0, 'no relay loop started')
  // hub unreachable: same
  const t2 = setup({ noHub: true })
  assert.match((await t2.run('s1', 'bind dsh-1')).text, /hub did not accept/)
  t.dispose(); t2.dispose(); hub.close()
})

test('identity: bind/poll/delivered/unbind and tool calls all carry x-xmuse-session', async () => {
  const hub = await relayHub()
  const t = setup({ hubPort: hub.port })
  const agent = t.mkAgent('s1')
  await t.emit('agent/created', { agent })
  const r = await t.run('s1', 'bind dsh-1')
  assert.match(r.text, /hub confirmed/)
  hub.add(1)
  await until(() => hub.st.deliveredCalls.length === 1, 'delivered')
  assert.match(await agent.tools.get('xmuse_whoami').execute({}, {}), /echo/)
  await t.run('s1', 'unbind')
  const by = (u) => hub.seen.filter((s) => s.url === u)
  for (const u of ['/v1/relay/bind', '/v1/relay/poll', '/v1/relay/delivered', '/v1/tools/xmuse_whoami', '/v1/relay/unbind']) {
    assert.ok(by(u).length >= 1, u)
    assert.ok(by(u).every((s) => s.session === 's1' && s.auth === 'Bearer tok-dsh-1'), `${u} carries session and agent token`)
  }
  assert.deepEqual(hub.st.binds, ['s1'])
  assert.deepEqual(hub.st.unbinds, ['s1'])
  assert.match(await agent.tools.get('xmuse_whoami').execute({}, {}), /not bound/) // local binding gone: hub not called
  t.dispose(); hub.close()
})

test('identity: unbind with the hub down still unbinds locally and says the hub was not told', async () => {
  const hub = await relayHub()
  const t = setup({ hubPort: hub.port })
  t.mkAgent('s1')
  await t.run('s1', 'bind dsh-1')
  fs.rmSync(path.join(t.dir, 'hub.json'))
  const r = await t.run('s1', 'unbind')
  assert.equal(r.kind, 'success')
  assert.match(r.text, /hub NOT told/)
  assert.deepEqual(readBindings(t.bindingsFile).bindings, {})
  t.dispose(); hub.close()
})

test('identity: another session took the agent over: poll fails with not_bound_session and the local binding is dropped', async () => {
  const hub = await relayHub()
  const t = setup({ hubPort: hub.port })
  const agent = t.mkAgent('s1')
  await t.emit('agent/created', { agent })
  await t.run('s1', 'bind dsh-1')
  await until(() => hub.st.polls.length >= 1, 'polling')
  hub.st.bound['Bearer tok-dsh-1'] = 'other-session' // /xmuse bind in another session
  assert.match(await agent.tools.get('xmuse_whoami').execute({}, {}), /hub error not_bound_session/)
  await until(() => Object.keys(readBindings(t.bindingsFile).bindings).length === 0, 'binding dropped')
  assert.ok(t.logs.some(([, m]) => /dropping the local binding/.test(m)))
  assert.match((await t.run('s1', 'status')).text, /\(none\)/)
  t.dispose(); hub.close()
})

test('identity: a restored binding is re-asserted on the hub before polling (dsh restart / hub db reset)', async () => {
  const hub = await relayHub()
  const t = setup({ hubPort: hub.port })
  t.mkAgent('s1')
  await t.run('s1', 'bind dsh-1')
  t.dispose()
  delete hub.st.bound['Bearer tok-dsh-1'] // the hub forgot
  hub.st.binds.length = 0; hub.st.polls.length = 0
  const t2 = setup({ hubPort: hub.port, bindingsFile: t.bindingsFile })
  await until(() => hub.st.polls.length >= 1, 'polls after restart')
  assert.deepEqual(hub.st.binds, ['s1'])
  assert.equal(hub.st.bound['Bearer tok-dsh-1'], 's1')
  t2.dispose(); hub.close()
})

test('agent backfill at apply time, creation, idempotence and disposal', async () => {
  const t = setup({ preAgents: ['pre'] })
  assert.equal(t.agents.get('pre').tools.size, 8, 'backfilled from roots()')
  t.mkAgent('late')
  await t.emit('agent/created', { agent: t.agents.get('late') })
  assert.equal(t.agents.get('late').tools.size, 8)
  await t.emit('agent/created', { agent: t.agents.get('late') })
  assert.equal(t.agents.get('late').tools.size, 8)
  await t.emit('agent/disposed', { agent: t.agents.get('late') })
  assert.equal(t.agents.get('late').tools.size, 0)
  t.dispose()
})

// ---- relay ----

test('relay delivers like ping, reports delivered, advances and persists the cursor only after flush', async () => {
  const hub = await relayHub()
  const t = setup({ hubPort: hub.port })
  t.mkAgent('s1')
  await t.run('s1', 'bind dsh-1')
  hub.add(5)
  await until(() => hub.st.deliveredCalls.length === 1, 'delivered report')
  assert.equal(t.followups.length, 1)
  const m = t.followups[0].m
  assert.equal(m.source.kind, 'xmuse')
  assert.deepEqual(m.content, [{ type: 'text', text: 'TEXT[5]' }])
  assert.deepEqual(t.order.slice(0, 2), ['followup:s1', 'flush:s1'])
  assert.deepEqual(hub.st.deliveredCalls[0], { delivery_ids: [5], session_id: 's1' })
  const poll = hub.seen.find((s) => s.url === '/v1/relay/poll')
  assert.equal(poll.auth, 'Bearer tok-dsh-1')
  assert.deepEqual(poll.body, { cursor: 0, wait_s: 1 })
  await until(() => readBindings(t.bindingsFile).cursors?.['dsh-1'] === 5, 'persisted cursor')
  await until(() => hub.st.polls.includes(5), 'poll with advanced cursor')
  assert.match((await t.run('s1', 'status')).text, /cursor 5, last delivery \d{4}-/)
  hub.add(6)
  await until(() => hub.st.deliveredCalls.length === 2, 'second delivery')
  assert.equal(t.followups.length, 2)
  t.dispose(); hub.close()
})

test('cursor survives a restart (loop resumes from the persisted cursor)', async () => {
  const hub = await relayHub()
  const t = setup({ hubPort: hub.port })
  t.mkAgent('s1')
  await t.run('s1', 'bind dsh-1')
  hub.add(3)
  await until(() => readBindings(t.bindingsFile).cursors?.['dsh-1'] === 3, 'cursor persisted')
  t.dispose()
  hub.st.polls.length = 0
  const t2 = setup({ hubPort: hub.port, bindingsFile: t.bindingsFile })
  t2.mkAgent('s1')
  await until(() => hub.st.polls.length > 0, 'restored loop polls')
  assert.equal(hub.st.polls[0], 3)
  t2.dispose(); hub.close()
})

test('flush failure: cursor stays, nothing is reported, the retry delivers and then reports once', async () => {
  const hub = await relayHub()
  let calls = 0
  const t = setup({ hubPort: hub.port, flushOk: () => ++calls > 2 }) // first two flushes fail
  t.mkAgent('s1')
  await t.run('s1', 'bind dsh-1')
  hub.add(1)
  await until(() => calls >= 1, 'first flush')
  assert.equal(hub.st.deliveredCalls.length, 0)
  await until(() => hub.st.deliveredCalls.length === 1, 'eventual report')
  assert.ok(t.logs.some(([l, m]) => l === 'warn' && /did not acknowledge/.test(m)))
  assert.equal(calls, 3)
  assert.deepEqual(hub.st.deliveredCalls[0].delivery_ids, [1])
  assert.ok(hub.st.polls.slice(0, 3).every((c) => c === 0), 'cursor did not move before a successful flush')
  assert.equal(readBindings(t.bindingsFile).cursors['dsh-1'], 1)
  t.dispose(); hub.close()
})

test('resolveAgent failure also retries with backoff and never loses the message', async () => {
  const hub = await relayHub()
  const t = setup({ hubPort: hub.port })
  hub.add(1)
  await t.run('s-missing', 'bind dsh-1') // session not resolvable yet
  await until(() => t.logs.some(([, m]) => /session\/not-found/.test(m)), 'failure logged')
  assert.match((await t.run('s-missing', 'status')).text, /relay: (error|polling|idle)/)
  t.mkAgent('s-missing') // the session appears
  await until(() => hub.st.deliveredCalls.length === 1, 'delivered after recovery')
  t.dispose(); hub.close()
})

test('delivered report failure is retried without delivering the text twice', async () => {
  const hub = await relayHub({ deliveredFail: 2 })
  const t = setup({ hubPort: hub.port })
  t.mkAgent('s1')
  await t.run('s1', 'bind dsh-1')
  hub.add(1)
  await until(() => hub.st.delivered.has(1), 'delivered accepted')
  assert.equal(hub.st.deliveredCalls.length, 3)
  assert.equal(t.followups.length, 1, 'the session got the text once')
  t.dispose(); hub.close()
})

test('hub down: loop backs off, reports error state, recovers when the hub is back', async () => {
  const hub = await relayHub()
  const t = setup({ hubPort: hub.port })
  t.mkAgent('s1')
  await t.run('s1', 'bind dsh-1')
  fs.renameSync(path.join(t.dir, 'hub.json'), path.join(t.dir, 'hub.json.off'))
  await until(() => t.logs.filter(([, m]) => /relay dsh-1/.test(m)).length >= 2, 'repeated backoff')
  assert.match((await t.run('s1', 'status')).text, /relay: error.*last error [^-]/)
  fs.renameSync(path.join(t.dir, 'hub.json.off'), path.join(t.dir, 'hub.json'))
  hub.add(1)
  await until(() => hub.st.deliveredCalls.length === 1, 'recovery')
  t.dispose(); hub.close()
})

test('unbind stops the loop and aborts the in-flight poll', async () => {
  const hub = await relayHub()
  const t = setup({ hubPort: hub.port })
  t.mkAgent('s1')
  await t.run('s1', 'bind dsh-1')
  await until(() => hub.st.polls.length >= 2, 'polling')
  assert.equal((await t.run('s1', 'unbind')).kind, 'success')
  await tick(120)
  const n = hub.st.polls.length
  hub.add(1)
  await tick(300)
  assert.equal(hub.st.polls.length, n, 'no further polls after unbind')
  assert.equal(t.followups.length, 0)
  assert.match((await t.run('s1', 'status')).text, /\(none\)/)
  t.dispose(); hub.close()
})

test('dispose stops every loop', async () => {
  const hub = await relayHub()
  const t = setup({ hubPort: hub.port })
  t.mkAgent('s1'); t.mkAgent('s2')
  await t.run('s1', 'bind dsh-1')
  await t.run('s2', 'bind dsh-2')
  await until(() => hub.st.polls.length >= 2, 'polling')
  t.dispose()
  await tick(150)
  const n = hub.st.polls.length
  await tick(300)
  assert.equal(hub.st.polls.length, n)
  hub.close()
})

test('duplicate binding: one loop per agent, last binding wins, replacement is reported', async () => {
  const hub = await relayHub()
  const t = setup({ hubPort: hub.port })
  t.mkAgent('s1'); t.mkAgent('s2')
  await t.run('s1', 'bind dsh-1')
  const r = await t.run('s2', 'bind dsh-1')
  assert.match(r.text, /replaced: session s1 no longer bound to "dsh-1"/)
  assert.deepEqual(readBindings(t.bindingsFile).bindings, { s2: 'dsh-1' })
  await tick(300)
  hub.add(1)
  await until(() => hub.st.deliveredCalls.length === 1, 'delivery')
  assert.deepEqual(t.followups.map((f) => f.id), ['s2'])
  assert.equal(hub.st.deliveredCalls[0].session_id, 's2')
  // exactly one loop polls: sample poll starts over a window (each empty poll lasts ~40ms + 250ms guard)
  const before = hub.st.polls.length
  await tick(700)
  const rate = hub.st.polls.length - before
  assert.ok(rate <= 4, `single loop expected, saw ${rate} polls in 700ms`)
  // rebinding a session to another agent stops the old agent's loop
  await t.run('s2', 'bind dsh-2')
  const status = (await t.run('s2', 'status')).text
  assert.match(status, /s2 -> dsh-2/)
  assert.doesNotMatch(status, /dsh-1/)
  t.dispose(); hub.close()
})

test('the coordinator-only tool is never offered to a dsh session, even when the hub lists it', async () => {
  const t = setup()
  const agent = t.mkAgent('s1')
  await t.emit('agent/created', { agent })
  const hubTools = JSON.parse(fs.readFileSync(new URL('../tools.json', import.meta.url), 'utf8')).map((x) => x.name)
  assert.ok(hubTools.includes('xmuse_approve'), 'the bundled copy mirrors the hub (9 tools)')
  assert.ok(!agent.tools.has('xmuse_approve'))
  assert.equal(agent.tools.size, 8)
  t.dispose()
})
