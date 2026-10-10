import { test } from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { apply, inject, name } from '../index.js'

const tick = () => new Promise((r) => setTimeout(r, 30))

function fakeHub(handler) {
  const seen = []
  const server = http.createServer((req, res) => {
    let b = ''
    req.on('data', (c) => (b += c))
    req.on('end', () => {
      seen.push({ url: req.url, auth: req.headers.authorization, body: JSON.parse(b || '{}') })
      const [code, obj] = handler(req)
      res.writeHead(code, { 'content-type': 'application/json' })
      res.end(JSON.stringify(obj))
    })
  })
  return new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve({ server, seen, port: server.address().port })))
}

function setup({ hubPort, flushOk = true, resolveError = false, noSessionController = false, bindingsFile: bf, preAgents = [] } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-bundle-'))
  fs.mkdirSync(path.join(dir, 'tokens'))
  if (hubPort) fs.writeFileSync(path.join(dir, 'hub.json'), JSON.stringify({ port: hubPort, pid: 1 }))
  fs.writeFileSync(path.join(dir, 'tokens', 'dsh-1'), 'tok-dsh-1\n')
  const bindingsFile = bf ?? path.join(dir, 'bindings.json')

  const logs = []
  const commands = new Map()
  const listeners = {}
  const followups = []
  const flushed = []
  const agents = new Map()
  const mkAgent = (id) => {
    const tools = new Map()
    const agent = {
      id, session: { id },
      followup: (m) => followups.push({ id, m }),
      ctx: {
        tools: { register: (t) => { tools.set(t.name, t); return () => tools.delete(t.name) } },
        effect: (fn) => fn(),
      },
      tools,
    }
    agents.set(id, agent)
    return agent
  }
  const ctx = {
    logger: { info: (m) => logs.push(['info', m]), warn: (m) => logs.push(['warn', m]) },
    effect: (fn) => fn(),
    on: (ev, fn) => { (listeners[ev] ||= []).push(fn); return () => {} },
    commands: { register: (c) => { commands.set(c.name, c); return () => commands.delete(c.name) } },
    agents: { roots: () => [...agents.values()] },
    sessions: { flush: async (s) => { flushed.push(s.id); return flushOk } },
    ...(noSessionController ? {} : {
      sessionController: {
        resolveAgent: async (id) => (resolveError ? { error: new Error('session/not-found') } : { agent: agents.get(id) }),
      },
    }),
  }
  const emit = async (ev, payload) => { for (const fn of listeners[ev] || []) await fn(payload) }
  for (const id of preAgents) mkAgent(id)
  apply(ctx, { state: dir, bindingsFile })
  const run = (sessionId, rawInput) => commands.get('xmuse').handler({ agent: agents.get(sessionId) ?? { id: sessionId }, rawInput })
  return { ctx, dir, bindingsFile, logs, commands, followups, flushed, agents, mkAgent, emit, run }
}

test('exports and command registration', async () => {
  assert.equal(name, 'xmuse')
  assert.deepEqual(inject, ['commands', 'agents', 'sessions', 'tools', 'sessionController'])
  const t = setup()
  assert.ok(t.commands.has('xmuse'))
  assert.equal(t.commands.get('xmuse').recordInput, false)
})

test('self-check logs services and hub state, never throws', async () => {
  const { server, port } = await fakeHub(() => [200, {}])
  const t = setup({ hubPort: port })
  await tick()
  const line = t.logs.find(([, m]) => m.includes('self-check'))
  assert.ok(line, 'self-check log present')
  assert.match(line[1], /"sessionController":true/)
  assert.match(line[1], new RegExp(`ok \\(port ${port}\\)`))
  server.close()
  // missing everything: still no throw
  const bad = setup({ noSessionController: true })
  await tick()
  assert.match(bad.logs.find(([, m]) => m.includes('self-check'))[1], /"sessionController":false/)
  assert.match(bad.logs.find(([, m]) => m.includes('self-check'))[1], /unreadable/)
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
})

test('bind persists to file and status shows it; usage errors', async () => {
  const t = setup()
  t.mkAgent('s1')
  assert.equal((await t.run('s1', 'bind')).kind, 'error')
  const r = await t.run('s1', ' bind dsh-1 ')
  assert.equal(r.kind, 'success')
  assert.deepEqual(JSON.parse(fs.readFileSync(t.bindingsFile, 'utf8')), { s1: 'dsh-1' })
  const s = await t.run('s1', 'status')
  assert.match(s.text, /s1 -> dsh-1/)
  assert.match(s.text, /sessionController: yes/)
  assert.equal((await t.run('s1', 'nope')).kind, 'error')
  assert.equal((await t.run('s1', '')).kind, 'error')
  // bindings survive a "restart": a second instance over the same file loads them
  const t2 = setup({ bindingsFile: t.bindingsFile })
  await tick()
  assert.match((await t2.run('s1', 'status')).text, /s1 -> dsh-1/)
})

test('bind persist failure does not throw', async () => {
  const t = setup()
  t.mkAgent('s1')
  fs.mkdirSync(t.bindingsFile) // a directory: writeFile fails
  const r = await t.run('s1', 'bind dsh-1')
  assert.equal(r.kind, 'success')
  assert.match(r.text, /write failed/)
})

test('xmuse_whoami: registered on agent/created, unbound message, then hub call after late bind', async () => {
  const { server, seen, port } = await fakeHub(() => [200, { result: { id: 'dsh-1', vendor: 'dsh' } }])
  const t = setup({ hubPort: port })
  const agent = t.mkAgent('s1')
  await t.emit('agent/created', { agent })
  const tool = agent.tools.get('xmuse_whoami')
  assert.ok(tool, 'tool registered')
  assert.match(await tool.execute({}, { signal: new AbortController().signal }), /\/xmuse bind/)
  assert.equal(seen.length, 0)
  await t.run('s1', 'bind dsh-1') // bound after agent/created
  const out = await tool.execute({}, { signal: new AbortController().signal })
  assert.equal(out, JSON.stringify({ id: 'dsh-1', vendor: 'dsh' }))
  assert.equal(seen[0].url, '/v1/tools/xmuse_whoami')
  assert.equal(seen[0].auth, 'Bearer tok-dsh-1')
  assert.deepEqual(seen[0].body, { args: {} })
  server.close()
})

test('xmuse_whoami: hub errors, missing token, hub down all return text', async () => {
  const { server, port } = await fakeHub(() => [200, { error: { code: 'forbidden', message: 'nope' } }])
  const t = setup({ hubPort: port })
  const agent = t.mkAgent('s1')
  await t.emit('agent/created', { agent })
  const tool = agent.tools.get('xmuse_whoami')
  await t.run('s1', 'bind dsh-1')
  assert.match(await tool.execute({}, {}), /hub error forbidden: nope/)
  await t.run('s1', 'bind ghost')
  assert.match(await tool.execute({}, {}), /failed/)
  server.close()
  await t.run('s1', 'bind dsh-1')
  assert.match(await tool.execute({}, {}), /failed/) // connection refused
})

test('agent backfill at apply time, creation, idempotence and disposal', async () => {
  const t = setup({ preAgents: ['pre'] })
  assert.ok(t.agents.get('pre').tools.has('xmuse_whoami'), 'backfilled from roots()')
  t.mkAgent('late')
  await t.emit('agent/created', { agent: t.agents.get('late') })
  assert.ok(t.agents.get('late').tools.has('xmuse_whoami'))
  await t.emit('agent/created', { agent: t.agents.get('late') })
  assert.equal(t.agents.get('late').tools.size, 1)
  await t.emit('agent/disposed', { agent: t.agents.get('late') })
  assert.ok(!t.agents.get('late').tools.has('xmuse_whoami'))
})
