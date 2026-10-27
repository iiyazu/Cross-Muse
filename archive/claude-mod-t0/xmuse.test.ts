import { test, expect, mock } from 'claude-code/testing'
import { findRoom, isKeyShape, isLoopbackUrl, normDir, parseHubs, registryDirFrom } from './src/registry'
import { doneMd, messageMd, renderHostWait, renderMembers } from './src/format'

// The hub is faked at the bottom ($.http.fetch). Paths and shapes follow
// the sidebar view API (v0 + v0.1).

const CWD = '/proj'
const SID = 'sess-1'
const BINDING = {
  hub: 'http://127.0.0.1:43117',
  memberId: 'claude-1',
  memberToken: 'mt_secret_member',
  operatorToken: 'ot_secret_operator',
  sessionId: SID,
  roomId: 'r-1',
}

function viewJson(extra: Record<string, unknown> = {}) {
  return {
    version: 5,
    room: { id: 'r-1', name: 'demo', dir: CWD, host: 'coord', info_layer: 'on', created_at: 1 },
    me: { kind: 'member', id: 'claude-1' },
    members: [
      { id: 'coord', vendor: 'claude', model: 'm', role: 'coordinator', description: '主控', status: 'idle', online: true, paused: false, unread: 0, tokens_hour: 0, tokens_hour_cap: 0 },
      { id: 'claude-1', vendor: 'claude', model: 'm', role: 'executor', description: '侧栏开发', status: 'idle', online: true, paused: false, unread: 1, tokens_hour: 0, tokens_hour_cap: 0 },
    ],
    threads: [{ id: '#d3', kind: 'topic', title: '#d3', members: ['coord', 'claude-1'], last_at: 10, unread: 1 }],
    timeline: [
      { id: 1043, thread: '#d3', from: 'coord', via: null, to: ['claude-1'], mentions: ['claude-1'], kind: 'message', text: '@claude-1 请跑一下测试', at: 10, for_me: true },
    ],
    timeline_cursor: { oldest: 1043, has_more: false },
    alignment: [{ id: 'E1', kind: 'decision', scope: 'module:sidebar', author: 'coord', text: '按 v0', supersedes: null, status: 'active', at: 9 }],
    approvals: [{ id: 'A1', kind: 'shell', member: 'coord', summary: 'npm install', detail: 'cd x && npm i', risk: 'normal', at: 11 }],
    run: null,
    ...extra,
  }
}

type Call = { url: string; method: string; headers: Record<string, string>; body: any }

function fakeHub(on: any, calls: Call[], view: () => any) {
  on('http.fetch', (_$: any, e: any) => {
    const url = new URL(e.url)
    const body = e.init && e.init.body ? JSON.parse(e.init.body) : undefined
    calls.push({ url: url.pathname + url.search, method: (e.init && e.init.method) || 'GET', headers: (e.init && e.init.headers) || {}, body })
    const resp = (status: number, obj: unknown) => ({ value: { status, ok: status >= 200 && status < 300, headers: {}, text: obj === null ? '' : JSON.stringify(obj) } })
    if (url.pathname === '/v1/view') {
      const since = Number(url.searchParams.get('since') || 0)
      const v = view()
      return since === v.version ? resp(204, null) : resp(200, v)
    }
    if (url.pathname === '/v1/join') {
      const b = body || {}
      if (!b.code) {
        // keyless local join (8.1): needs the sidebar key; member name from vendor
        if (b.room_id === 'r-t0a1') {
          if (e.init.headers['x-xmuse-sidebar'] !== FEATURE_KEY) return resp(401, { error: 'bad_sidebar_key', message: 'no' })
          return resp(200, { member_id: 'claude-9', member_token: 'mt_local_9', operator_token: 'ot_local_9', room: { id: 'r-t0a1', name: 'local-a' } })
        }
        return resp(404, { error: 'unknown_room', message: 'no' })
      }
      return resp(200, { member_id: 'claude-1', member_token: 'mt_secret_member', operator_token: 'ot_secret_operator' })
    }
    if (url.pathname === '/v1/act') {
      if (body && body.act === 'member_add') {
        if (!['claude', 'opencode', 'dsh'].includes(body.vendor)) return resp(400, { error: 'bad_vendor', message: 'no' })
        return resp(200, { member_id: body.name || 'opencode' })
      }
      if (body && body.act === 'thread_new') {
        if (body.id === '#dup') return resp(409, { error: 'thread_exists', message: 'dup' })
        return resp(200, { thread: body.id })
      }
      if (body && body.act === 'wake_host') return resp(200, { ok: true, released: 2 })
      return resp(200, { ok: true, id: 7 })
    }
    return resp(404, { error: 'not_found', message: 'no' })
  })
}

const START = { cwd: CWD, surface: 'desktop', isInteractive: true } as any

// Distinctive sidebar key (valid 64-hex shape so the fake hub accepts it).
// It must never appear in command output, pane rendering, or prompts.
const FEATURE_KEY = 'ab'.repeat(32)

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

// Real temp registry files. This assumes the harness lets $.fs.read hit the
// real filesystem and the mod sees the real process.env; the pure registry
// unit tests below do not depend on either.
function realRegistry(entries: any[], key: string = FEATURE_KEY) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-claude-reg-'))
  fs.writeFileSync(path.join(dir, 'hubs.json'), JSON.stringify({ hubs: entries }))
  fs.writeFileSync(path.join(dir, 'sidebar.key'), key)
  return dir
}

function withRegistryEnv(dir: string) {
  const prev = process.env.XMUSE_REGISTRY_DIR
  process.env.XMUSE_REGISTRY_DIR = dir
  return () => {
    if (prev === undefined) delete process.env.XMUSE_REGISTRY_DIR
    else process.env.XMUSE_REGISTRY_DIR = prev
  }
}

const liveEntry = (over: any = {}) => ({
  room_id: 'r-t0a1', name: 'local-a', dir: '/proj', url: 'http://127.0.0.1:9/', host: 'somebody',
  pid: process.pid, started_at: 1, ...over,
})

test('registry pure helpers: normDir/parseHubs/findRoom/loopback/key/dir', async () => {
  expect(normDir('C:\\X\\Y')).toBe('c:\\x\\y')
  expect(normDir('/mnt/c/X/Y/')).toBe('c:\\x\\y')
  expect(normDir('/home/u/x/')).toBe('/home/u/x')
  const alive = (p: number) => p === 11
  const entries = parseHubs(JSON.stringify({ hubs: [
    { room_id: 'r-1', name: 'a', dir: 'C:\\p', url: 'http://127.0.0.1:1/', host: 'h', pid: 11, started_at: 1 },
    { room_id: 'r-2', name: 'a', dir: 'C:\\q', url: 'http://127.0.0.1:2/', host: 'h', pid: 12, started_at: 1 },
    { room_id: 'r-3', name: 'b', url: 'http://127.0.0.1:3/', host: 'h', pid: 11, started_at: 1 },
    'junk',
    { room_id: 'r-4' },
  ] }), alive)
  expect(entries.map(e => e.room_id).join(',')).toBe('r-1,r-2,r-3')
  expect(parseHubs('not json', alive).length).toBe(0)
  expect(parseHubs('{"hubs": {}}', alive).length).toBe(0)
  expect(findRoom(entries, { roomId: 'r-2' }).entry?.name).toBe('a')
  expect(findRoom(entries, { roomId: 'r-x' }).error).toContain('unknown room')
  expect(findRoom(entries, { name: 'a' }).error).toContain('2 个')
  expect(findRoom(entries, { name: 'b' }).entry?.room_id).toBe('r-3')
  expect(findRoom(entries, { dir: '/mnt/c/p' }).entry?.room_id).toBe('r-1')
  expect(findRoom(entries, { dir: 'C:\\nope' }).error).toContain('没有服务')
  expect(findRoom([], { dir: 'C:\\x' }).error).toContain('没有登记')
  expect(findRoom(entries, {}).error).toBeDefined()
  expect(isLoopbackUrl('http://127.0.0.1:9/')).toBe(true)
  expect(isLoopbackUrl('http://localhost:9')).toBe(true)
  expect(isLoopbackUrl('http://[::1]:9/')).toBe(true)
  expect(isLoopbackUrl('http://192.168.1.2:9')).toBe(false)
  expect(isLoopbackUrl('https://example.com')).toBe(false)
  expect(isLoopbackUrl('not a url')).toBe(false)
  expect(isKeyShape('ab'.repeat(32))).toBe(true)
  expect(isKeyShape('xyz')).toBe(false)
  expect(registryDirFrom({ XMUSE_REGISTRY_DIR: '/r' }, 'linux', '/h')).toBe('/r')
  expect(registryDirFrom({}, 'win32', 'C:\\U\\me')).toBe('C:\\U\\me\\AppData\\Local\\xmuse')
  expect(registryDirFrom({ LOCALAPPDATA: 'D:\\L' }, 'win32', '')).toBe('D:\\L\\xmuse')
  expect(registryDirFrom({}, 'linux', '/h')).toBe('/h/.local/state/xmuse')
})

test('format v0.1: done tags, unverified, shared_from, routed questions, host wait, wakes', async () => {
  const base: any = { id: 9, thread: '#room', from: 'dsh-1', via: null, to: [], mentions: [], text: '做完 X', at: 100, for_me: false }
  const done = { ...base, kind: 'done', outcome: 'needs_alignment', outcome_by: 'hub', outcome_reason: 'declares decision beyond its own scope' }
  const t1 = doneMd(done)
  expect(t1).toContain('结果：needs_alignment')
  expect(t1).toContain('hub 改判')
  expect(t1).toContain('declares decision')
  const ev = { ...base, kind: 'done', outcome: 'completed', outcome_by: 'member', evidence_status: 'unverified', evidence_problems: ['transcript unavailable'] }
  const t2 = doneMd(ev)
  expect(t2).toContain('结果：completed')
  expect(t2).not.toContain('hub 改判')
  expect(t2).toContain('未核实')
  expect(t2).toContain('transcript unavailable')
  const sh = { ...base, kind: 'message', via: 'shared', shared_from: { member: 'cl-9', message_id: 3 } }
  expect(messageMd(sh)).toContain('分享自 cl-9（#3）')
  const q = { ...base, kind: 'question', routed_to: ['dsh-1', 'op-1'], route_reason: '关键词重叠' }
  const t3 = messageMd(q)
  expect(t3).toContain('已路由给 dsh-1、op-1')
  expect(t3).toContain('关键词重叠')
  const q1 = { ...base, kind: 'question', routed_to: 'dsh-1' }
  expect(messageMd(q1)).toContain('已路由给 dsh-1')
  const plain = { ...base, kind: 'question' }
  expect(messageMd(plain)).not.toContain('已路由给')
  const hw = renderHostWait({ host_wait: { waiting_on: [{ member: 'dsh-1', handoff_id: 'h7', since: 50 }], results_held: 2, wake_at: null } } as any)
  expect(hw).toContain('dsh-1')
  expect(hw).toContain('h7')
  expect(hw).toContain('压住了 2 条结果')
  expect(renderHostWait({} as any)).toContain('暂无等待')
  const mm = renderMembers({
    room: { host: 'coord' },
    members: [{ id: 'dsh-1', vendor: 'dsh', role: 'executor', description: '', status: 'idle', online: true, paused: false, unread: 0, wakes_hour: 7 }],
  } as any, 'coord')
  expect(mm).toContain('唤醒7/h')
})

function world(on: any, withBinding: boolean) {
  on('session.id', () => ({ value: SID }))
  on('session.cwd', () => ({ value: CWD }))
  on('session.start', () => ({ cwd: CWD }))
  on('command.register', () => ({ value: {} }))
  on('tool.register', () => ({ value: { tool: 'mcp__xmuse__say' } }))
  const clock = mock.clock(on, { now: 1_000_000 })
  mock.store(on, withBinding ? { ['binding:' + CWD]: BINDING } : {})
  return clock
}

test('/xmuse join binds the session and never prints a token', async ($, on) => {
  const calls: Call[] = []
  fakeHub(on, calls, () => viewJson())
  world(on, false)
  const r = await $.command.run({ command: 'xmuse', args: 'join K7Q2-9F' })
  expect(r.text).toContain('claude-1')
  expect(r.text).not.toContain('mt_secret')
  expect(r.text).not.toContain('ot_secret')
  expect(r.text).not.toContain('K7Q2')
  const join = calls.find(c => c.url === '/v1/join')
  expect(join).toBeDefined()
  expect(join?.body.vendor).toBe('claude')
  expect(join?.body.session_id).toBe(SID)
})

test('/xmuse join with a bad hub answers with an explanation, exit code 1', async ($, on) => {
  on('http.fetch', () => {
    throw new Error('ECONNREFUSED')
  })
  world(on, false)
  const r = await $.command.run({ command: 'xmuse', args: 'join K7Q2-9F' })
  expect(r.text).toContain('hub')
  expect(r.exitCode).toBe(1)
})

test('background loop: renders the pane, shows the band, wakes the session once', async ($, on) => {
  const calls: Call[] = []
  const submitted: string[] = []
  fakeHub(on, calls, () => viewJson())
  on('prompt.submit', (_$: any, e: any) => {
    submitted.push(e.text)
    return { text: e.text }
  })
  const clock = world(on, true)
  await $.session.start(START)
  await clock.advance(1100)
  await clock.advance(1100)

  // woken exactly once, with sender / thread / original text, and the tool name
  expect(submitted.length).toBe(1)
  expect(submitted[0]).toContain('coord')
  expect(submitted[0]).toContain('#d3')
  expect(submitted[0]).toContain('@claude-1 请跑一下测试')
  expect(submitted[0]).toContain('mcp__xmuse__say')
  expect(submitted[0]).not.toContain('mt_secret')

  // the loop used the MEMBER token and the session header only
  const views = calls.filter(c => c.url.startsWith('/v1/view'))
  expect(views.length).toBeGreaterThan(0)
  expect(views[0].headers.authorization).toBe('Bearer mt_secret_member')
  expect(views[0].headers['x-xmuse-session']).toBe(SID)
  expect(calls.every(c => c.headers.authorization !== 'Bearer ot_secret_operator')).toBe(true)

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({
      plugin: 'xmuse',
      surface,
      component: 'Pane',
      requestId: 'xmuse',
      props: { title: 'xmuse', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 20 }, view: {} } as any,
      viewport: { columns: 80, rows: 30, isFullscreen: true },
    })
    expect(await ui.find({ type: 'Markdown', text: /请跑一下测试/ })).toBeDefined()
    expect(await ui.find({ type: 'Input', key: 'draft' })).toBeDefined()
    await ui.press({ key: 'sec-members' })
    expect(await ui.find({ type: 'Markdown', text: /侧栏开发/ })).toBeDefined()
    await ui.press({ key: 'sec-approvals' })
    expect(await ui.find({ type: 'Button', key: 'ap-A1-once' })).toBeDefined()
    await ui.press({ key: 'ap-A1-once' })
    await ui.press({ key: 'sec-alignment' })
    expect(await ui.find({ type: 'Markdown', text: /按 v0/ })).toBeDefined()
    await ui.press({ key: 'sec-room' })
    expect(await ui.find({ type: 'Button', key: 'inv-go' })).toBeDefined()
    await ui.press({ key: 'sec-timeline' })
    await ui.unmount()
  }

  // approvals go through the OPERATOR token
  const approve = calls.find(c => c.body && c.body.act === 'approve')
  expect(approve).toBeDefined()
  expect(approve?.headers.authorization).toBe('Bearer ot_secret_operator')
  expect(approve?.body.decision).toBe('once')

  const band = await $.ui.mount({
    plugin: 'xmuse',
    surface: 'desktop',
    component: 'AbovePrompt',
    props: { hasSurvey: false, isWorking: false, maxRows: 5, bodyColumns: 80, scroll: { offset: 0, bodyRows: 5 }, view: {} } as any,
    viewport: { columns: 80, rows: 30, isFullscreen: true },
  })
  expect(await band.find({ type: 'Text', text: /@ 我的未读 1 · 待审批 1/ })).toBeDefined()
  expect(await band.find({ type: 'Button', key: 'open' })).toBeDefined()
  await band.unmount()
})

test('sending from the pane uses the operator token; the agent tool uses the member token', async ($, on) => {
  const calls: Call[] = []
  fakeHub(on, calls, () => viewJson())
  on('prompt.submit', (_$: any, e: any) => ({ text: e.text }))
  const clock = world(on, true)
  await $.session.start(START)
  await clock.advance(1100)

  const ui = await $.ui.mount({
    plugin: 'xmuse',
    surface: 'desktop',
    component: 'Pane',
    requestId: 'xmuse',
    props: { title: 'xmuse', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 20 }, view: {} } as any,
    viewport: { columns: 80, rows: 30, isFullscreen: true },
  })
  await ui.select({ key: 'to', value: 'coord' })
  await ui.input({ key: 'draft', text: '收到 @coord', kind: 'change' })
  await ui.press({ key: 'send' })
  await ui.unmount()
  const say = calls.find(c => c.body && c.body.act === 'say')
  expect(say?.headers.authorization).toBe('Bearer ot_secret_operator')
  expect(say?.body.to).toBe('coord')
  expect(say?.body.mentions).toContain('coord')

  const t = await $.tool.call({ tool: 'mcp__xmuse__say', to: '#d3', text: 'done' } as any)
  expect(t.isError).toBeUndefined()
  const say2 = calls.filter(c => c.body && c.body.act === 'say').pop()
  expect(say2?.headers.authorization).toBe('Bearer mt_secret_member')
  expect(say2?.body.to).toBe('#d3')
})

test('/xmuse rooms lists local rooms (dead pids filtered) and join-local binds with the key', async ($, on) => {
  const calls: Call[] = []
  fakeHub(on, calls, () => viewJson())
  const dir = realRegistry([liveEntry(), { ...liveEntry(), room_id: 'r-dead', name: 'dead', pid: 999999999 }])
  const restore = withRegistryEnv(dir)
  try {
    world(on, false)
    const rooms = await $.command.run({ command: 'xmuse', args: 'rooms' })
    expect(rooms.text).toContain('local-a')
    expect(rooms.text).toContain('r-t0a1')
    expect(rooms.text).not.toContain('dead')
    expect(rooms.text).not.toContain(FEATURE_KEY)
    const r = await $.command.run({ command: 'xmuse', args: 'join-local local-a' })
    expect(r.text).toContain('claude-9')
    expect(r.text).not.toContain(FEATURE_KEY)
    const join = calls.find(c => c.url === '/v1/join' && !c.body.code)
    expect(join).toBeDefined()
    expect(join?.headers['x-xmuse-sidebar']).toBe(FEATURE_KEY)
    expect(join?.body.room_id).toBe('r-t0a1')
    expect(join?.body.vendor).toBe('claude')
    expect(join?.body.session_id).toBe(SID)
    // already bound: second join is refused without touching the hub
    const again = await $.command.run({ command: 'xmuse', args: 'join-local r-t0a1' })
    expect(again.text).toContain('leave')
    expect(again.exitCode).toBe(1)
  } finally {
    restore()
  }
})

test('/xmuse join-local by id, ambiguous and unknown names', async ($, on) => {
  const calls: Call[] = []
  fakeHub(on, calls, () => viewJson())
  const dir = realRegistry([
    liveEntry({ room_id: 'r-a1', name: 'dup' }),
    liveEntry({ room_id: 'r-a2', name: 'dup' }),
  ])
  const restore = withRegistryEnv(dir)
  try {
    world(on, false)
    const dup = await $.command.run({ command: 'xmuse', args: 'join-local dup' })
    expect(dup.exitCode).toBe(1)
    expect(dup.text).toContain('r-a1')
    expect(dup.text).toContain('r-a2')
    const r = await $.command.run({ command: 'xmuse', args: 'join-local r-a2' })
    expect(r.text).toContain('claude-9')
    expect(r.text).not.toContain(FEATURE_KEY)
  } finally {
    restore()
  }
})

test('/xmuse join-local unknown room reports it', async ($, on) => {
  const calls: Call[] = []
  fakeHub(on, calls, () => viewJson())
  const dir = realRegistry([liveEntry()])
  const restore = withRegistryEnv(dir)
  try {
    world(on, false)
    const r = await $.command.run({ command: 'xmuse', args: 'join-local nope' })
    expect(r.exitCode).toBe(1)
    expect(r.text).not.toContain(FEATURE_KEY)
    expect(calls.filter(c => c.url === '/v1/join').length).toBe(0)
  } finally {
    restore()
  }
})

test('/xmuse add and group new (member_add / thread_new)', async ($, on) => {
  const calls: Call[] = []
  fakeHub(on, calls, () => viewJson())
  world(on, true)
  let r = await $.command.run({ command: 'xmuse', args: 'add opencode m/mod executor 做测试' })
  expect(r.text).toContain('已添加成员')
  expect(r.text).not.toContain(FEATURE_KEY)
  const add = calls.find(c => c.body && c.body.act === 'member_add')
  expect(add?.headers.authorization).toBe('Bearer ot_secret_operator')
  expect(add?.body.vendor).toBe('opencode')
  expect(add?.body.model).toBe('m/mod')
  expect(add?.body.role).toBe('executor')
  r = await $.command.run({ command: 'xmuse', args: 'add slack x y z' })
  expect(r.exitCode).toBe(1)
  r = await $.command.run({ command: 'xmuse', args: 'add a b' })
  expect(r.exitCode).toBe(2)
  r = await $.command.run({ command: 'xmuse', args: 'group new #g2 dsh-1' })
  expect(r.text).toContain('#g2')
  const g = calls.find(c => c.body && c.body.act === 'thread_new')
  expect(g?.body.id).toBe('#g2')
  expect(g?.body.members).toContain('dsh-1')
  r = await $.command.run({ command: 'xmuse', args: 'group foo' })
  expect(r.exitCode).toBe(2)
  r = await $.command.run({ command: 'xmuse', args: 'wake-host' })
  expect(r.text).toContain('放出 2')
})

async function absent(ui: any, q: any) {
  // ui.find's miss behavior is harness-defined: only undefined (or a throw)
  // means absent; a found element must fail loudly, never be swallowed.
  let threw = false
  let v: any = undefined
  try {
    v = await ui.find(q)
  } catch {
    threw = true
  }
  if (!threw) expect(v).toBeUndefined()
}

const PANE_PROPS = {
  title: 'xmuse', isFocused: false, bodyColumns: 60, placement: 'dock', scroll: { offset: 0, bodyRows: 20 }, view: {},
} as any
const PANE_VIEWPORT = { columns: 80, rows: 30, isFullscreen: true } as any

function paneView(extra: Record<string, unknown> = {}) {
  return viewJson({
    members: [
      { id: 'coord', vendor: 'claude', model: 'm', role: 'coordinator', description: '主控', status: 'idle', online: true, paused: false, unread: 0, tokens_hour: 0, tokens_hour_cap: 0 },
      { id: 'claude-1', vendor: 'claude', model: 'm', role: 'executor', description: '侧栏开发', status: 'idle', online: true, paused: false, unread: 1, tokens_hour: 0, tokens_hour_cap: 0 },
      { id: 'dsh-1', vendor: 'dsh', model: 'm', role: 'executor', description: '干活', status: 'idle', online: true, paused: false, unread: 0, tokens_hour: 0, tokens_hour_cap: 0 },
    ],
    threads: [
      { id: '#d3', kind: 'topic', title: '#d3', members: ['coord', 'claude-1'], last_at: 10, unread: 1 },
      { id: '#g1', kind: 'topic', title: 'G1', members: ['human', 'claude-1', 'dsh-1'], last_at: 11, unread: 0, private: true },
    ],
    ...extra,
  })
}

test('pane: unbound rooms list one-click join never shows the key', async ($, on) => {
  const calls: Call[] = []
  fakeHub(on, calls, () => viewJson())
  const dir = realRegistry([liveEntry()])
  const restore = withRegistryEnv(dir)
  try {
    world(on, false)
    const ui = await $.ui.mount({
      plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse',
      props: PANE_PROPS, viewport: PANE_VIEWPORT,
    })
    expect(await ui.find({ type: 'Text', text: /local-a/ })).toBeDefined()
    await absent(ui, { type: 'Text', text: new RegExp('ab{8}') })
    await ui.press({ key: 'rl-go-r-t0a1' })
    const join = calls.find(c => c.url === '/v1/join' && !c.body.code)
    expect(join?.headers['x-xmuse-sidebar']).toBe(FEATURE_KEY)
    await ui.unmount()
  } finally {
    restore()
  }
})

test('pane: member menu and groups section call the right acts', async ($, on) => {
  const calls: Call[] = []
  fakeHub(on, calls, () => paneView())
  on('prompt.submit', (_$: any, e: any) => ({ text: e.text }))
  const clock = world(on, true)
  await $.session.start(START)
  await clock.advance(1100)
  const ui = await $.ui.mount({
    plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse',
    props: PANE_PROPS, viewport: PANE_VIEWPORT,
  })
  await ui.press({ key: 'sec-members' })
  for (const k of ['m-pause', 'm-resume', 'm-host', 'm-remove', 'm-dm', 'm-edit-go', 'm-grp-go']) {
    expect(await ui.find({ type: 'Button', key: k })).toBeDefined()
  }
  await ui.press({ key: 'm-host' })
  expect(calls.find(c => c.body && c.body.act === 'transfer_host')).toBeDefined()
  await ui.press({ key: 'm-grp-go' })
  const ta = calls.find(c => c.body && c.body.act === 'thread_add')
  expect(ta?.body.thread).toBe('#g1')
  await ui.press({ key: 'sec-groups' })
  expect(await ui.find({ type: 'Button', key: 'grp-go' })).toBeDefined()
  expect(await ui.find({ type: 'Markdown', text: /G1/ })).toBeDefined()
  await ui.input({ key: 'grp-id', text: '#g9', kind: 'change' })
  await ui.input({ key: 'grp-members', text: 'dsh-1', kind: 'change' })
  await ui.press({ key: 'grp-go' })
  const tn = calls.find(c => c.body && c.body.act === 'thread_new')
  expect(tn?.body.id).toBe('#g9')
  expect(tn?.body.members).toContain('dsh-1')
  await ui.press({ key: 'grm-#g1-dsh-1' })
  const tr = calls.find(c => c.body && c.body.act === 'thread_remove')
  expect(tr?.body.thread).toBe('#g1')
  expect(tr?.body.member).toBe('dsh-1')
  await absent(ui, { type: 'Markdown', text: new RegExp('ab{8}') })
  await ui.unmount()
})

test('pane: done tags, share excerpt, host wait and wake button (v0.1 step 2)', async ($, on) => {
  const v: any = paneView({
    timeline: [
      { id: 50, thread: '#room', from: 'dsh-1', via: null, to: [], mentions: [], kind: 'done', text: '做完 X', at: 100, for_me: false, outcome: 'needs_alignment', outcome_by: 'hub', outcome_reason: 'declares decision beyond its own scope', evidence_status: 'unverified', evidence_problems: ['transcript unavailable'] },
      { id: 51, thread: 'dm:boss+claude-1', from: 'cl-9', via: 'shared', to: ['claude-1'], mentions: [], kind: 'message', text: 'body', at: 101, for_me: true, shared_from: { member: 'cl-9', message_id: 3 } },
    ],
    approvals: [
      { id: 'share:1', kind: 'share', member: 'cl-9', summary: 'cl-9 想把 #3 分享给 boss', detail: { message_id: 3, to: 'boss', why: 'need', excerpt: '密钥 ALPHA-1' }, risk: 'normal', at: 102 },
    ],
    host_wait: { waiting_on: [{ member: 'dsh-1', handoff_id: 'h7', since: 90 }], results_held: 1, wake_at: null },
  })
  v.members.find((m: any) => m.id === 'dsh-1').wakes_hour = 7
  const calls: Call[] = []
  fakeHub(on, calls, () => v)
  on('prompt.submit', (_$: any, e: any) => ({ text: e.text }))
  const clock = world(on, true)
  await $.session.start(START)
  await clock.advance(1100)
  const ui = await $.ui.mount({
    plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse',
    props: PANE_PROPS, viewport: PANE_VIEWPORT,
  })
  await ui.press({ key: 'sec-timeline' })
  expect(await ui.find({ type: 'Markdown', text: /结果：needs_alignment/ })).toBeDefined()
  expect(await ui.find({ type: 'Markdown', text: /hub 改判/ })).toBeDefined()
  expect(await ui.find({ type: 'Markdown', text: /未核实/ })).toBeDefined()
  expect(await ui.find({ type: 'Markdown', text: /分享自 cl-9/ })).toBeDefined()
  await ui.press({ key: 'sec-approvals' })
  expect(await ui.find({ type: 'Text', text: /ALPHA-1/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /给 boss/ })).toBeDefined()
  await ui.press({ key: 'sec-members' })
  expect(await ui.find({ type: 'Markdown', text: /唤醒7\/h/ })).toBeDefined()
  await ui.press({ key: 'sec-host' })
  expect(await ui.find({ type: 'Markdown', text: /任务 h7/ })).toBeDefined()
  expect(await ui.find({ type: 'Markdown', text: /压住了 1 条结果/ })).toBeDefined()
  await ui.press({ key: 'wake-go' })
  const wake = calls.find(c => c.body && c.body.act === 'wake_host')
  expect(wake).toBeDefined()
  expect(wake?.headers.authorization).toBe('Bearer ot_secret_operator')
  await ui.unmount()
})
