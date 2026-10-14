import { test, expect } from 'claude-code/testing'

// The per-second elapsed time and the typing effect run inside Client modules (hooks/elapsed.tsx, hooks/grow.tsx), so a
// running member does not redraw the whole panel. Mounts the panel with one running member and drives the frame clock.

const T0 = 1_700_000_000_000 // host clock (ms) at the draw
const view = {
  version: 1,
  room: { id: 'r1', host: 'claude' },
  me: { id: 'claude' },
  members: [{ id: 'opencode', status: 'running', progress: { started_at: T0 / 1000 - 65, tools: 2, text: 'hello world' } }],
  timeline: [],
}
// the typing effect is on: 5 characters shown at first, then 8, then all 11
const typed = { id: 'opencode', full: 'hello world', from: 5, steps: [8, 11], run: 1 }

function mountPanel($: any, on: any) {
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async () => ({ value: null }))
  // `typed` is seeded until the plugin writes it (the kit holds values from then on, so the write lands as it does live)
  let typedWritten = false
  on('state.set', async (_$: any, e: any, next: any) => { if (e.key === 'typed') typedWritten = true; return next(e) })
  on('state.get', async (_$: any, e: any, next: any) => {
    if (e.key === 'view') return { value: { value: view, version: 1 } }
    if (e.key === 'typed' && !typedWritten) return { value: { value: typed, version: 0 } } // 0: what the kit holds, so the write lands
    return next(e)
  })
  return $.ui.mount({ plugin: 'xmuse', surface: 'terminal', component: 'Pane', requestId: 'xmuse', props: {} })
}

test('elapsed Client counts seconds by itself', async ($, on) => {
  const ui = await mountPanel($, on)
  const key = 'el-opencode-strip'
  expect((await ui.find({ type: 'Text', text: '1:05', in: key }))?.text).toContain('1:05')
  await ui.advance(3000)
  expect((await ui.find({ type: 'Text', text: '1:08', in: key }))?.text).toContain('1:08')
  await ui.unmount()
})

test('grow Client types the text in and reports when done', async ($, on) => {
  const ui = await mountPanel($, on)
  const key = 'gr-t-opencode-1'
  expect((await ui.find({ type: 'Text', text: 'hello ▍', in: key }))?.text).toContain('hello')
  await ui.advance(150)
  expect((await ui.find({ type: 'Text', text: 'hello wo', in: key }))?.text).toContain('hello wo')
  expect(await ui.find({ type: 'Client', key })).toBeDefined() // still typing: the panel's own tree holds the Client
  await ui.advance(150)
  await ui.advance(16) // the Client's post is delivered on the next frame; the ui.message hook then clears `typed`
  await ui.redraw() // the write of `typed` invalidated the panel; draw it again
  expect(await ui.find({ type: 'Client', key })).toBeUndefined() // the panel drew itself again with the plain text
  expect((await ui.find({ type: 'Text', text: 'hello world ▍' }))?.text).toContain('hello world')
  await ui.unmount()
})

// ---- "加载更早的消息": pages that fold into notice rows are skipped over in one press -------------------------------------

const notice = (id: number) => ({ id, from: 'hub', kind: 'system', thread: '#room', at: 1_699_000_000 + id, text: `agent${id} joined the room (claude)` })
const PAGES: Record<number, { items: any[]; has_more: boolean }> = {
  // `before` the page is asked for -> the page (oldest first): two pages of notices, then one with a plain message
  100: { items: Array.from({ length: 20 }, (_, i) => notice(80 + i)), has_more: true },
  80: { items: Array.from({ length: 20 }, (_, i) => notice(60 + i)), has_more: true },
  60: { items: [...Array.from({ length: 10 }, (_, i) => notice(40 + i)), { id: 50, from: 'opencode', thread: '#room', at: 1_699_000_050, text: 'an older plain message' }], has_more: true },
}
const olderView = {
  version: 1,
  room: { id: 'r1', host: 'claude' },
  me: { id: 'claude' },
  members: [],
  timeline: [{ id: 100, from: 'opencode', thread: '#room', at: 1_699_000_100, text: 'newest message' }],
  timeline_cursor: { has_more: true },
}

test('one press on the older-messages button skips pages of notices until a real message shows', async ($, on) => {
  const asked: number[] = []
  const files: Record<string, string> = {
    'C:\\state\\install.json': '{}', // the kit normalises the path it hands the fs.read hook
    'C:\\state\\hubs.json':JSON.stringify({ hubs: [{ url: 'http://127.0.0.1:9', dir: '/room', started_at: 1 }] }),
  }
  const stored: Record<string, unknown> = {
    setup: { stateDir: '/state', distro: 'd', python: '' },
    knownRooms: ['/room'],
    'conn:/room': { url: 'http://127.0.0.1:9', token: 't', member: 'claude', memberToken: 'm', dir: '/room', sid: 'S' },
  }
  const toasts: string[] = []
  on('ui.toast', async (_$: any, e: any) => { toasts.push(String(e.text ?? JSON.stringify(e))); return { value: undefined } })
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async (_$: any, e: any) => ({ value: stored[e.key] ?? null }))
  on('session.cwd', async () => ({ value: '/room' }))
  on('session.id', async () => ({ value: 'S' }))
  on('fs.read', async (_$: any, e: any, next: any) => (e.path in files ? { value: files[e.path] } : next(e)))
  on('http.fetch', async (_$: any, e: any, next: any) => {
    const m = /\/v1\/timeline\?before=(\d+)&limit=100/.exec(String(e.url))
    if (!m) return next(e)
    asked.push(Number(m[1]))
    return { value: { status: 200, text: JSON.stringify(PAGES[Number(m[1])]) } }
  })
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: olderView, version: 1 } } : next(e)))
  const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'terminal', component: 'Pane', requestId: 'xmuse', props: {} })
  expect(await ui.find({ type: 'Text', text: 'an older plain message' })).toBeUndefined()
  await ui.press({ key: 'older' })
  await ui.redraw()
  expect(toasts).toEqual([])
  expect(asked).toEqual([100, 80, 60]) // the third page was fetched because the first two showed nothing but notices
  expect((await ui.find({ type: 'Markdown', text: 'an older plain message' }))?.text).toContain('an older plain message')
  await ui.unmount()
})

// ---- the reveal of a new message (grow Client, 'md' mode) must always draw -----------------------------------------------

const REVEAL_TEXTS: Record<string, string> = {
  short: 'ack',
  markdown: '**Plan**\n\n- one\n- two\n\n```ts\nconst a = 1\n```\n\n> quoted `code` and [a link](https://example.com)\n\n| a | b |\n|---|---|\n| 1 | 2 |',
  crlf: 'line one\r\nline two\r\n',
}

function revealStepsOf(len: number): number[] {
  const n = Math.min(10, Math.max(3, Math.ceil(len / 40)))
  const out: number[] = []
  for (let i = 1; i <= n; i++) out.push(Math.min(len, Math.ceil((len * i) / n)))
  out[out.length - 1] = len
  return out
}

for (const surface of ['terminal', 'desktop'] as const) {
  for (const [name, text] of Object.entries(REVEAL_TEXTS)) {
    for (const withSteps of [true, false]) {
      test(`reveal of a ${name} message draws on ${surface}${withSteps ? '' : ' (no steps)'} from start to done`, async ($, on) => {
        const msg = { id: 7, from: 'agy', thread: '#room', at: 1_699_000_007, text, reply_to: 3 }
        const v = { ...chipView, members: [], timeline: [{ id: 3, from: 'human', thread: '#room', at: 1_699_000_003, text: 'ping' }, msg] }
        const steps = withSteps ? revealStepsOf(text.length) : []
        let cleared = false
        on('state.set', async (_$: any, e: any, next: any) => { if (e.key === 'reveal') cleared = true; return next(e) })
        on('clock.now', async () => ({ value: T0 }))
        on('store.get', async () => ({ value: null }))
        on('state.get', async (_$: any, e: any, next: any) => {
          if (e.key === 'view') return { value: { value: v, version: 1 } }
          if (e.key === 'reveal' && !cleared) return { value: { value: { id: 7, steps, run: 1 }, version: 0 } }
          return next(e)
        })
        const ui = await $.ui.mount({ plugin: 'xmuse', surface, component: 'Pane', requestId: 'xmuse', props: {} })
        await ui.drawn() // rejects with the refusal when the surface could not draw the panel or one of its Clients
        for (let i = 0; i < steps.length + 2; i++) {
          await ui.advance(70)
          await ui.drawn()
          if (withSteps && !cleared) {
            // the Client draws plain Text: a Markdown root in a Client is what the desktop refused to draw
            expect(JSON.stringify(await ui.drawn({ in: 'gr-m-7' }))).not.toContain('"Markdown"')
          }
        }
        await ui.redraw()
        expect(await ui.find({ type: 'Client', key: 'gr-m-7' })).toBeUndefined() // done: the plain rendering is back
        await ui.unmount()
      })
    }
  }
}

// ---- layout at two pane widths ---------------------------------------------------------------------------------------------

const widthView = () => ({ ...chipView, timeline: [{ id: 5, from: 'alpha', thread: '#room', at: 1_699_000_005, text: 'hi claude', for_me: true }] })

for (const [label, columns] of [['narrow', 40], ['wide', 130]] as const) {
  test(`rail, header, notices and composer all draw at a ${label} pane (${columns} columns)`, async ($, on) => {
    const stored: Record<string, unknown> = { briefMissing: true, wakeSeen: 0 }
    on('clock.now', async () => ({ value: T0 }))
    on('store.get', async (_$: any, e: any) => ({ value: stored[e.key] ?? null }))
    on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: widthView(), version: 1 } } : next(e)))
    const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse', props: {}, viewport: { columns, rows: 40 } })
    await ui.drawn()
    // every control keeps its key at both widths: the rail has the room, one entry per member and 全部
    const keys = ['wake-banner', 'brief-ask', 'brief-skip', 'add-toggle', 'auto-wake', 'rail-toggle', 'rail-room', 'rail-all', 'xm-in-0',
      'wk-stop-alpha', ...['alpha', 'beta', 'gamma', 'delta'].map(id => `rail-dm-${id}`)]
    for (const k of keys) expect(await ui.find({ key: k })).toBeDefined()
    // only the wake notice is a solid (primary) button; the rest are plain text buttons
    const primary = JSON.stringify(await ui.drawn()).match(/"variant":"primary"/g) ?? []
    expect(primary).toHaveLength(1)
    // the rail carries the members' names only open: folded by itself on a narrow pane
    const named = await ui.find({ type: 'Text', text: 'delta' })
    if (columns >= 56) expect(named).toBeDefined()
    else expect(named).toBeUndefined()
    // the fold button flips it
    await ui.press({ key: 'rail-toggle' })
    await ui.redraw()
    const after = await ui.find({ type: 'Text', text: 'delta' })
    if (columns >= 56) expect(after).toBeUndefined()
    else expect(after).toBeDefined()
    await ui.unmount()
  })
}

// ---- member chips: the status area stays small; a chip opens the full card ------------------------------------------------

const chipView = {
  version: 1,
  room: { id: 'r1', host: 'claude', name: 'dev' },
  me: { id: 'claude' },
  members: ['alpha', 'beta', 'gamma', 'delta'].map((id, i) => ({
    id, vendor: 'opencode', model: 'prov/model-x', context_tokens: 85_000, online: true,
    ...(i < 2 ? { status: 'running', progress: { started_at: T0 / 1000 - 30, tools: 1, text: `${id} is working` } } : {}),
  })),
  timeline: [],
}

test('a member in the rail opens the private chat; its 操作 menu holds the card, pause and a two-press remove', async ($, on) => {
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async () => ({ value: null }))
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: chipView, version: 1 } } : next(e)))
  const acts: any[] = []
  on('http.fetch', async (_$: any, e: any) => {
    acts.push(JSON.parse(String(e.body ?? '{}')))
    return { status: 200, headers: {}, body: '{"ok":true}' }
  })
  const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'terminal', component: 'Pane', requestId: 'xmuse', props: {} })
  // the room is open: the composer says 全员, no member menu
  expect(await ui.find({ type: 'Text', text: '全员' })).toBeDefined()
  for (const id of ['alpha', 'beta', 'gamma', 'delta']) expect(await ui.find({ key: `peer-menu-${id}` })).toBeUndefined()
  expect(await ui.findAll({ type: 'Button', key: 'wk-stop-alpha' })).toHaveLength(1) // running members keep a stop button in the strip
  await ui.press({ key: 'rail-dm-gamma' })
  await ui.redraw()
  expect(await ui.find({ type: 'Text', text: '（私聊）' })).toBeDefined() // the composer now goes to gamma alone
  expect(await ui.find({ key: 'md-gamma' })).toBeUndefined() // the menu is closed
  await ui.press({ key: 'peer-menu-gamma' })
  await ui.redraw()
  expect(await ui.find({ key: 'md-gamma' })).toBeDefined() // model and compact from the card
  expect(await ui.find({ key: 'cp-gamma' })).toBeDefined()
  expect(await ui.find({ key: 'pause-gamma' })).toBeDefined()
  await ui.press({ key: 'remove-gamma' })
  await ui.redraw()
  expect(JSON.stringify(await ui.drawn())).toContain('确认移出？再点一次') // the first press only asks
  expect(acts.some(a => a.act === 'remove')).toBe(false)
  await ui.press({ key: 'peer-menu-gamma' })
  await ui.redraw()
  expect(await ui.find({ key: 'md-gamma' })).toBeUndefined() // closed again
  await ui.unmount()
})
