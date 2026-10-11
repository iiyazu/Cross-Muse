import { test, expect, mock } from 'claude-code/testing'

// The hub is faked at the bottom ($.http.fetch). Paths and shapes follow
// docs/design/XMUSE2-VIEW-API.zh.md (v0).

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
    if (url.pathname === '/v1/join') return resp(200, { member_id: 'claude-1', member_token: 'mt_secret_member', operator_token: 'ot_secret_operator' })
    if (url.pathname === '/v1/act') return resp(200, { ok: true, id: 7 })
    return resp(404, { error: 'not_found', message: 'no' })
  })
}

const START = { cwd: CWD, surface: 'desktop', isInteractive: true } as any

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
