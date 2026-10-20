import { test, expect } from 'claude-code/testing'

// The live parts of a running member (hooks/live.tsx: the working strip's "正在：… m:ss" and the draft bubble's text) run inside
// Client modules that ask the ui.message hook for fresh props once a second, so progress never redraws the whole panel.
// Mounts the panel with one running member.

const T0 = 1_700_000_000_000 // host clock (ms) at the draw
const view = {
  version: 1,
  room: { id: 'r1', host: 'claude' },
  me: { id: 'claude' },
  members: [{ id: 'opencode', status: 'running', progress: { started_at: T0 / 1000 - 65, tools: 2, text: 'hello world' } }],
  timeline: [],
}

function mountPanel($: any, on: any, now: () => number = () => T0) {
  on('clock.now', async () => ({ value: now() }))
  on('store.get', async () => ({ value: null }))
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: view, version: 1 } } : next(e)))
  return $.ui.mount({ plugin: 'xmuse', surface: 'terminal', component: 'Pane', requestId: 'xmuse', props: {} })
}

test('live strip Client shows the elapsed time and a post answers with fresh props', async ($, on) => {
  let nowV = T0
  const ui = await mountPanel($, on, () => nowV)
  const key = 'lv-act-opencode'
  expect(await ui.find({ type: 'Client', key })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: '1:05', in: key }))?.text).toContain('1:05')
  nowV = T0 + 3000
  await ui.post({ live: 'act', id: 'opencode' }, { in: key }) // what the Client's own timer posts once a second
  expect((await ui.find({ type: 'Text', text: '1:08', in: key }))?.text).toContain('1:08')
  await ui.unmount()
})

test('live draft Client draws the partial output of the member', async ($, on) => {
  const ui = await mountPanel($, on)
  const key = 'lv-dr-opencode'
  expect(await ui.find({ type: 'Client', key })).toBeDefined()
  await ui.post({ live: 'draft', id: 'opencode' }, { in: key })
  expect((await ui.find({ type: 'Text', text: 'hello world', in: key }))?.text).toContain('hello world')
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
  test(`list, header, notices and composer all draw at a ${label} pane (${columns} columns)`, async ($, on) => {
    const stored: Record<string, unknown> = { briefMissing: true, wakeSeen: 0 }
    on('clock.now', async () => ({ value: T0 }))
    on('store.get', async (_$: any, e: any) => ({ value: stored[e.key] ?? null }))
    on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: widthView(), version: 1 } } : next(e)))
    const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse', props: { bodyColumns: columns }, viewport: { columns, rows: 40 } })
    await ui.drawn()
    // every control keeps its key at both widths: the list has the room, one entry per member and 全部
    const keys = ['wake-banner', 'brief-ask', 'brief-skip', 'add-toggle', 'auto-wake', 'rail-room', 'rail-all', 'xm-in-0-0',
      'wk-stop-alpha', ...['alpha', 'beta', 'gamma', 'delta'].map(id => `rail-dm-${id}`)]
    for (const k of keys) expect(await ui.find({ key: k })).toBeDefined()
    expect(await ui.find({ key: 'rail-toggle' })).toBeUndefined() // no folding any more
    // only the wake notice is a solid (primary) button; the rest are plain text buttons
    const primary = JSON.stringify(await ui.drawn()).match(/"variant":"primary"/g) ?? []
    expect(primary).toHaveLength(1)
    // the member names are drawn in both layouts
    expect(await ui.find({ type: 'Text', text: 'delta' })).toBeDefined()
    // the sub-line of an entry (its second row) is drawn only when the list is not compact (a wide pane)
    const sub = await ui.find({ key: 'rs-rail-room' })
    if (columns >= 90) expect(sub).toBeDefined()
    else expect(sub).toBeUndefined()
    await ui.unmount()
  })
}

test('the list is compact by the pane width, not by the transcript beside it', async ($, on) => {
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async () => ({ value: null }))
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: widthView(), version: 1 } } : next(e)))
  // a narrow docked pane beside a wide transcript: the list is there, compact (no second line)
  let ui = await $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse', props: { bodyColumns: 40 }, viewport: { columns: 130, rows: 40 } })
  expect(await ui.find({ key: 'rail-room' })).toBeDefined()
  expect(await ui.find({ key: 'rs-rail-room' })).toBeUndefined()
  await ui.unmount()
  // a wide pane beside a narrow transcript: the full list with its second line
  ui =await $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse', props: { bodyColumns: 120 }, viewport: { columns: 50, rows: 40 } })
  expect(await ui.find({ key: 'rs-rail-room' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'delta' })).toBeDefined()
  await ui.unmount()
})

// ---- /x and the probes -----------------------------------------------------------------------------------------------------

test('/x sends its text to the open conversation and answers where it went', async ($, on) => {
  const stored: Record<string, unknown> = {
    setup: { stateDir: '/state', distro: 'd', python: '' },
    knownRooms: ['/room'],
    'conn:/room': { url: 'http://127.0.0.1:9', token: 't', member: 'claude', memberToken: 'm', dir: '/room', sid: 'S' },
  }
  const files: Record<string, string> = {
    'install.json': '{}',
    'hubs.json': JSON.stringify({ hubs: [{ url: 'http://127.0.0.1:9', dir: '/room', started_at: 1 }] }),
  }
  const sent: any[] = []
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async (_$: any, e: any) => ({ value: stored[e.key] ?? null }))
  on('session.cwd', async () => ({ value: '/room' }))
  on('session.id', async () => ({ value: 'S' }))
  // the kit's path form differs by platform: match the file name only
  on('fs.read', async (_$: any, e: any, next: any) => {
    const name = String(e.path).replace(/\\/g, '/').split('/').pop() ?? ''
    return name in files ? { value: files[name] } : next(e)
  })
  on('http.fetch', async (_$: any, e: any) => { if (String(e.url).endsWith('/v1/act')) sent.push(e.init?.body ? JSON.parse(String(e.init.body)) : JSON.parse(String(e.body ?? '{}'))); return { value: { status: 200, text: '{"ok":true}' } } })
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: widthView(), version: 1 } } : next(e)))
  const empty = await $.command.run({ command: 'x', args: '  ' })
  expect(empty?.text).toContain('用法')
  expect(sent).toHaveLength(0)
  const r = await $.command.run({ command: 'x', args: ' hello @alpha ' })
  expect(r?.text).toBe('已发到 大群')
  expect(sent).toHaveLength(1)
  expect(JSON.stringify(sent[0])).toContain('"act":"say"')
  expect(String(sent[0].text)).toContain('hello')
  // The scroll to the end after a send runs from a zero-delay clock.after: the kit intercepts clock.after (the hook sees only { ms })
  // and never runs the callback, and it has no engine window to take a ui.scroll, so that call cannot be observed here.
})

test('a stored tab that is not on the rail sends to the room, as the pane shows', async ($, on) => {
  const stored: Record<string, unknown> = {
    setup: { stateDir: '/state', distro: 'd', python: '' },
    knownRooms: ['/room'],
    'conn:/room': { url: 'http://127.0.0.1:9', token: 't', member: 'claude', memberToken: 'm', dir: '/room', sid: 'S' },
  }
  const files: Record<string, string> = {
    'install.json': '{}',
    'hubs.json': JSON.stringify({ hubs: [{ url: 'http://127.0.0.1:9', dir: '/room', started_at: 1 }] }),
  }
  const sent: any[] = []
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async (_$: any, e: any) => ({ value: stored[e.key] ?? null }))
  on('session.cwd', async () => ({ value: '/room' }))
  on('session.id', async () => ({ value: 'S' }))
  on('fs.read', async (_$: any, e: any, next: any) => {
    const name = String(e.path).replace(/\\/g, '/').split('/').pop() ?? ''
    return name in files ? { value: files[name] } : next(e)
  })
  on('http.fetch', async (_$: any, e: any) => { if (String(e.url).endsWith('/v1/act')) sent.push(e.init?.body ? JSON.parse(String(e.init.body)) : JSON.parse(String(e.body ?? '{}'))); return { value: { status: 200, text: '{"ok":true}' } } })
  on('state.get', async (_$: any, e: any, next: any) => {
    if (e.key === 'view') return { value: { value: widthView(), version: 1 } }
    if (e.key === 'tab') return { value: { value: '#plan', version: 1 } } // a tab of the former tab bar, not on the rail
    return next(e)
  })
  const r = await $.command.run({ command: 'x', args: 'hello' })
  expect(r?.text).toBe('已发到 大群')
  expect(sent).toHaveLength(1)
  expect(sent[0].to).toBe('#room')
})

test('the expanded card of a running member shows its tool count, live', async ($, on) => {
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async () => ({ value: null }))
  on('state.get', async (_$: any, e: any, next: any) => {
    if (e.key === 'view') return { value: { value: view, version: 1 } }
    return next(e)
  })
  const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'terminal', component: 'Pane', requestId: 'xmuse', props: {} })
  await ui.press({ key: 'rail-dm-opencode' })
  await ui.redraw()
  await ui.press({ key: 'peer-menu-opencode' }) // opens the member card
  await ui.redraw()
  const key = 'lv-tools-opencode'
  expect(await ui.find({ type: 'Client', key })).toBeDefined()
  await ui.post({ live: 'tools', id: 'opencode' }, { in: key })
  expect((await ui.find({ type: 'Text', text: '2 个工具', in: key }))?.text).toContain('2 个工具')
  await ui.unmount()
})

test('with the probe on the panel draws the probe line',async ($, on) => {
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async () => ({ value: null }))
  on('state.get', async (_$: any, e: any, next: any) => {
    if (e.key === 'view') return { value: { value: widthView(), version: 1 } }
    if (e.key === 'probe') return { value: { value: true, version: 1 } }
    return next(e)
  })
  const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse', props: { bodyColumns: 130 }, viewport: { columns: 130, rows: 40 } })
  expect((await ui.find({ type: 'Text', text: '滚动事件' }))?.text).toContain('未收到')
  await ui.unmount()
})

test('the outermost box is at least as tall as the pane body', async ($, on) => {
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async () => ({ value: null }))
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: widthView(), version: 1 } } : next(e)))
  const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse',
    props: { bodyColumns: 130, scroll: { offset: 0, bodyRows: 50 } }, viewport: { columns: 130, rows: 40 } })
  const tree: any = await ui.drawn()
  expect(JSON.stringify(tree).match(/"minHeight":50/)).not.toBeNull()
  const root = tree?.props ? tree : tree?.tree ?? tree
  expect(root?.props?.minHeight).toBe(50)
  await ui.unmount()
})

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

// ---- chat layout: top / feed (oldest first) / bottom block ------------------------------------------------------------------

const manyMsgs = (n: number) => Array.from({ length: n }, (_, i) => ({
  id: 10 + i, from: i % 2 ? 'alpha' : 'beta', thread: '#room', at: 1_699_000_000 + i * 60,
  text: i === 0 ? 'the oldest message' : i === n - 1 ? 'the newest message' : `message number ${i} with some words to fill a line or two of the list`,
}))
const pinnedView = (n: number, approvals: any[] = []) => ({ ...chipView, members: chipView.members.slice(2), approvals, timeline: manyMsgs(n) })

function mountPinned($: any, on: any, v: any, extra: Record<string, unknown> = {}) {
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async () => ({ value: null }))
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: v, version: 1 } } : next(e)))
  return $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse',
    props: { bodyColumns: 120, scroll: { offset: 0, bodyRows: 40 }, ...extra }, viewport: { columns: 120, rows: 40 } })
}

test('chat layout: the root keeps the pane height, oldest message first, approvals and the composer after the newest', async ($, on) => {
  const ap = [{ id: 'ap1', kind: 'shell', member: 'alpha', summary: 'git status -s', at: 1_699_000_100 }]
  const ui = await mountPinned($, on, pinnedView(6, ap))
  const tree: any = await ui.drawn()
  const root = tree?.props ? tree : tree?.tree ?? tree
  expect(root?.props?.minHeight).toBe(40)
  const json = JSON.stringify(tree)
  const oldest = json.indexOf('the oldest message')
  const newest = json.indexOf('the newest message')
  expect(oldest).toBeGreaterThan(-1)
  expect(newest).toBeGreaterThan(oldest) // chronological
  expect(json.indexOf('"xm-in-0-0"')).toBeGreaterThan(newest) // the composer is under the newest message
  expect(json.indexOf('"ap-ap1"')).toBeGreaterThan(newest) // so is the approval card
  expect(json.indexOf('"ap-ap1"')).toBeLessThan(json.indexOf('"xm-in-0-0"')) // above the composer
  for (const gone of ['xm-root', 'xm-spare', 'xm-list', 'to-latest', 'scroll-up', 'scroll-down']) expect(await ui.find({ key: gone })).toBeUndefined()
  await ui.unmount()
})

test('chat layout: the room buttons sit in the bottom block above the composer; the flow layout keeps them in the header', async ($, on) => {
  const stored: Record<string, unknown> = {}
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async (_$: any, e: any) => ({ value: stored[e.key] ?? null }))
  on('store.set', async (_$: any, e: any) => { stored[e.key] = e.value; return { value: undefined } })
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: pinnedView(6), version: 1 } } : next(e)))
  const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse',
    props: { bodyColumns: 120, scroll: { offset: 0, bodyRows: 40 } }, viewport: { columns: 120, rows: 40 } })
  const at = async (k: string) => JSON.stringify(await ui.drawn()).indexOf(`"${k}"`)
  const newestAt = async () => JSON.stringify(await ui.drawn()).indexOf('the newest message')
  for (const k of ['add-toggle', 'auto-wake', 'big-input']) expect(await ui.find({ key: k })).toBeDefined()
  expect(await at('add-toggle')).toBeGreaterThan(await newestAt()) // chat: below the conversation
  expect(await at('auto-wake')).toBeLessThan(await at('xm-in-0-0')) // and above the composer
  expect(await at('big-input')).toBeLessThan(await at('xm-in-0-0'))
  await $.command.run({ command: 'xmuse', args: 'layout' })
  await ui.redraw()
  expect(await ui.find({ key: 'add-toggle' })).toBeDefined()
  expect(await ui.find({ key: 'auto-wake' })).toBeDefined()
  expect(await at('add-toggle')).toBeLessThan(await newestAt()) // flow: the header, above the messages
  await ui.unmount()
})

test('Enter on "@ga" completes to "@gamma " in a remounted, refocused Input (the caret ends up at the end)', async ($, on) => {
  const focused: any[] = []
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async () => ({ value: null }))
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: pinnedView(4), version: 1 } } : next(e)))
  on('ui.focus', async (_$: any, e: any) => { focused.push(e); return { value: true } })
  const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse',
    props: { bodyColumns: 120, scroll: { offset: 0, bodyRows: 40 } }, viewport: { columns: 120, rows: 40 } })
  expect(await ui.find({ key: 'xm-in-0-0' })).toBeDefined()
  await ui.input({ key: 'xm-in-0-0', text: '@ga', kind: 'change' })
  await ui.redraw()
  await ui.input({ key: 'xm-in-0-0', text: '@ga' }) // Enter
  await ui.redraw()
  expect(await ui.find({ key: 'xm-in-0-0' })).toBeUndefined()
  const inp: any = await ui.find({ key: 'xm-in-0-1' })
  expect(inp).toBeDefined()
  expect(JSON.stringify(inp)).toContain('@gamma ')
  await new Promise(r => setTimeout(r, 20))
  if (focused.length) expect(JSON.stringify(focused)).toContain('xm-in-0-1') // the harness may not surface the deferred focus call
  await ui.unmount()
})

test('the big-input button puts "/x <draft>" in the prompt box when it is empty and refuses when it holds other text', async ($, on) => {
  let promptText = ''
  const filled: any[] = []
  const toasts: string[] = []
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async () => ({ value: null }))
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: pinnedView(4), version: 1 } } : next(e)))
  on('ui.toast', async (_$: any, e: any) => { toasts.push(String(e.text ?? JSON.stringify(e))); return { value: undefined } })
  on('prompt.read', async () => ({ value: { text: promptText, cursor: promptText.length } }))
  on('prompt.fill', async (_$: any, e: any) => { filled.push(e); return { isFilled: true } })
  const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse',
    props: { bodyColumns: 120, scroll: { offset: 0, bodyRows: 40 } }, viewport: { columns: 120, rows: 40 } })
  await ui.press({ key: 'big-input' })
  expect(filled).toHaveLength(1)
  expect(filled[0].text).toBe('/x ')
  expect(filled[0].mode).toBe('replace')
  expect(toasts.join('|')).toContain('已放进 Claude 输入框')
  promptText = 'some other text'
  await ui.press({ key: 'big-input' })
  expect(filled).toHaveLength(1) // not overwritten
  expect(toasts.join('|')).toContain('先清空 Claude 输入框里的内容')
  await ui.unmount()
})

test('chat layout: the rail column is anchored to the bottom', async ($, on) => {
  const ui = await mountPinned($, on, pinnedView(4))
  const tree: any = await ui.drawn()
  const json = JSON.stringify(tree)
  expect(json).toContain('"justifyContent":"flex-end"')
  // the rail column is the first child of the root and holds the fold toggle last
  const root = tree?.props ? tree : tree?.tree ?? tree
  const rail = (root?.children ?? root?.props?.children ?? [])[0]
  expect(JSON.stringify(rail)).toContain('"justifyContent":"flex-end"')
  const rj = JSON.stringify(rail)
  expect(rj.indexOf('rail-fold')).toBeGreaterThan(rj.indexOf('rail-room'))
  await ui.unmount()
})

test('the rail folds to avatars with rail-fold: names go, the buttons stay, and it unfolds again', async ($, on) => {
  const stored: Record<string, unknown> = {}
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async (_$: any, e: any) => ({ value: stored[e.key] ?? null }))
  on('store.set', async (_$: any, e: any) => { stored[e.key] = e.value; return { value: undefined } })
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: pinnedView(4), version: 1 } } : next(e)))
  const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse',
    props: { bodyColumns: 120, scroll: { offset: 0, bodyRows: 40 } }, viewport: { columns: 120, rows: 40 } })
  expect(await ui.find({ type: 'Text', text: 'delta' })).toBeDefined()
  await ui.press({ key: 'rail-fold' })
  await ui.redraw()
  expect(await ui.find({ type: 'Text', text: 'delta' })).toBeUndefined()
  expect(await ui.find({ key: 'rail-dm-delta' })).toBeDefined()
  expect(await ui.find({ key: 'rail-room' })).toBeDefined()
  expect(stored.railFold).toBe(true)
  await ui.press({ key: 'rail-fold' })
  await ui.redraw()
  expect(await ui.find({ type: 'Text', text: 'delta' })).toBeDefined()
  await ui.unmount()
})

test('the folded rail still draws the unread badge of an entry', async ($, on) => {
  const v: any = { ...pinnedView(4), threads: [{ id: 'dm:delta+human', unread: 3 }] }
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async () => ({ value: null }))
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: v, version: 1 } }
    : e.key === 'railFold' ? { value: { value: true, version: 1 } } : next(e)))
  const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse',
    props: { bodyColumns: 120, scroll: { offset: 0, bodyRows: 40 } }, viewport: { columns: 120, rows: 40 } })
  expect(await ui.find({ type: 'Text', text: 'delta' })).toBeUndefined() // folded
  expect(await ui.find({ key: 'rail-dm-delta-un' })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: '3' }))?.text).toContain('3')
  await ui.unmount()
})

test('/xmuse layout flips to the newest-first flow and back', async ($, on) => {
  const stored: Record<string, unknown> = {}
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async (_$: any, e: any) => ({ value: stored[e.key] ?? null }))
  on('store.set', async (_$: any, e: any) => { stored[e.key] = e.value; return { value: undefined } })
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: pinnedView(4), version: 1 } } : next(e)))
  const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'Pane', requestId: 'xmuse',
    props: { bodyColumns: 120, scroll: { offset: 0, bodyRows: 40 } }, viewport: { columns: 120, rows: 40 } })
  const order = async () => { const j = JSON.stringify(await ui.drawn()); return j.indexOf('the newest message') - j.indexOf('the oldest message') }
  expect(await order()).toBeGreaterThan(0) // chat: oldest first
  const r = await $.command.run({ command: 'xmuse', args: 'layout' })
  expect(r?.text).toBe('xmuse 布局：最新在上')
  await ui.redraw()
  expect(await order()).toBeLessThan(0) // flow: newest first
  expect(await ui.find({ key: 'xm-in-0-0' })).toBeDefined()
  const r2 = await $.command.run({ command: 'xmuse', args: 'layout' })
  expect(r2?.text).toBe('xmuse 布局：聊天（新消息在底部）')
  await ui.redraw()
  expect(await order()).toBeGreaterThan(0)
  await ui.unmount()
})

test('the band above the prompt draws a pending approval with its buttons', async ($, on) => {
  const ap = [{ id: 'ap1', kind: 'shell', member: 'alpha', summary: 'git status -s', at: 1_699_000_100 }, { id: 'ap2', kind: 'shell', member: 'beta', summary: 'ls' }]
  on('clock.now', async () => ({ value: T0 }))
  on('store.get', async () => ({ value: null }))
  on('state.get', async (_$: any, e: any, next: any) => (e.key === 'view' ? { value: { value: pinnedView(2, ap), version: 1 } } : next(e)))
  const ui = await $.ui.mount({ plugin: 'xmuse', surface: 'desktop', component: 'AbovePrompt', requestId: 'band',
    props: { hasSurvey: false, isWorking: false, maxRows: 12, bodyColumns: 53, scroll: { offset: 0, bodyRows: 12 } } as any, viewport: { columns: 53, rows: 40 } })
  expect(await ui.find({ key: 'band-ap-once' })).toBeDefined()
  expect(await ui.find({ key: 'band-ap-always' })).toBeDefined()
  expect(await ui.find({ key: 'band-ap-reject' })).toBeDefined()
  expect((await ui.find({ type: 'Text', text: 'git status -s' }))?.text).toContain('git status -s')
  expect(await ui.find({ type: 'Text', text: '还有 1 条' })).toBeDefined()
  await ui.unmount()
})
