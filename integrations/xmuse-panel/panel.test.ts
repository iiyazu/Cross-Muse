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
