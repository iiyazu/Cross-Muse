import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'
import { INITIAL_CONN, INITIAL_UI, PANE } from '../src/state'
import { bannerText, clip, isPendingEntry, pickFresh, recipientOptions, renderAlignment, renderHostWait, renderMembers, renderTimeline, wakePrompt } from '../src/format'
import { findRoom, isKeyShape, isLoopbackUrl, parseHubs, registryDirFrom } from '../src/registry'
import type { RegistryEntry } from '../src/registry'
import type { XmuseMessage, XmuseMore, XmuseUi, XmuseView } from '../types/index'

// The validator follows `$` only into functions declared in this file, never
// across an import, so everything that touches `$` lives here. Pure helpers
// (formatting, message selection, state atoms) are in ../src.

// State atoms: the scan needs plugin/key literals in this file.
const uiAtom = atom({ plugin: 'xmuse', key: 'ui' } as const, INITIAL_UI)
const viewAtom = atom({ plugin: 'xmuse', key: 'view' } as const, null as XmuseView | null)
const connAtom = atom({ plugin: 'xmuse', key: 'conn' } as const, INITIAL_CONN)
const moreAtom = atom({ plugin: 'xmuse', key: 'more' } as const, { items: [], hasMore: true } as XmuseMore)

// ===== hub.ts =====

// ---------------------------------------------------------------------------
// Hub client and binding storage. Tokens live in $.store only (never $.state,
// never the model's context, never the workspace).
// ---------------------------------------------------------------------------

const DEFAULT_HUB = 'http://127.0.0.1:43117'

type Binding = {
  hub: string
  memberId: string
  memberToken: string
  operatorToken: string
  sessionId: string
  roomId: string
}

type HubReply = { status: number; ok: boolean; body: any }

let OPTIONS: Record<string, unknown> = {}
// The session id this plugin instance last bound (join / room new / rebind).
// null = unknown (fresh process): a stored binding for another id is "stale".
let ownedId: string | null = null

function setOptions(o: Record<string, unknown> | undefined) {
  OPTIONS = o || {}
}
function option(name: string): unknown {
  return OPTIONS[name]
}
function getOwned(): string | null {
  return ownedId
}
function setOwned(id: string | null) {
  ownedId = id
}

// ---- binding (secrets) ----------------------------------------------------

async function bindingKey($: any): Promise<string> {
  const cwd = await $.session.cwd()
  return 'binding:' + String(cwd)
}

async function loadBinding($: any): Promise<Binding | null> {
  try {
    const v = await $.store.get(await bindingKey($))
    if (v && typeof v === 'object' && (v as any).memberToken) return v as Binding
  } catch {
    // store unreadable: act as unbound
  }
  return null
}

async function saveBinding($: any, b: Binding): Promise<void> {
  await $.store.set(await bindingKey($), b)
}

async function clearBinding($: any): Promise<void> {
  await $.store.delete(await bindingKey($))
}

// ---- hub address ----------------------------------------------------------

async function readPort($: any, dir: string): Promise<string> {
  try {
    const sep = dir.includes('\\') && !dir.includes('/') ? '\\' : '/'
    const raw = (await $.fs.read(dir.replace(/[\\/]+$/, '') + sep + 'hub.json')) as string
    const j = JSON.parse(raw)
    if (j && typeof j.port === 'number') return `http://127.0.0.1:${j.port}`
  } catch {
    // no hub.json there
  }
  return ''
}

async function resolveHub($: any, binding?: Binding | null): Promise<string> {
  let over: unknown
  try {
    over = await $.store.get('hubUrl')
  } catch {
    over = undefined
  }
  if (typeof over === 'string' && over) return over
  const cfg = option('hubUrl')
  if (typeof cfg === 'string' && cfg) return cfg
  const stateDir = option('stateDir')
  if (typeof stateDir === 'string' && stateDir) {
    const u = await readPort($, stateDir)
    if (u) return u
  }
  const cwd = String(await $.session.cwd())
  const u2 = await readPort($, cwd + (cwd.includes('\\') && !cwd.includes('/') ? '\\.xmuse' : '/.xmuse'))
  if (u2) return u2
  if (binding && binding.hub) return binding.hub
  return DEFAULT_HUB
}

// ---- HTTP -----------------------------------------------------------------

async function hubCall(
  $: any,
  hub: string,
  method: string,
  path: string,
  body?: unknown,
  token?: string,
  session?: string,
  key?: string,
): Promise<HubReply> {
  const headers: Record<string, string> = { 'content-type': 'application/json' }
  if (token) headers.authorization = 'Bearer ' + token
  if (session) headers['x-xmuse-session'] = session
  // 侧栏凭据（约定 8.1）：只在插件进程里出现，绝不进模型上下文和渲染；只发给回环地址的 hub
  // （hubUrl 配置项不做回环检查，这里兜底）。
  if (key && isLoopbackUrl(hub)) headers['x-xmuse-sidebar'] = key
  try {
    const r = await $.http.fetch(hub + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    let j: any = null
    if (r.text) {
      try {
        j = JSON.parse(r.text)
      } catch {
        j = { error: 'bad_json', message: String(r.text).slice(0, 200) }
      }
    }
    return { status: r.status, ok: r.ok, body: j }
  } catch (err) {
    return { status: 0, ok: false, body: { error: 'unreachable', message: `连不上 hub ${hub}：${String(err)}` } }
  }
}

function errText(r: HubReply): string {
  const b = r.body || {}
  return `${b.error || 'error'}${b.message ? '：' + b.message : ''}（HTTP ${r.status}）`
}

// act with the operator token (user's action in the sidebar / command) or the
// member token (agent tools, background loop).
async function actCall($: any, b: Binding, payload: Record<string, unknown>, as: 'operator' | 'member'): Promise<HubReply> {
  const hub = await resolveHub($, b)
  const tok = as === 'operator' ? b.operatorToken : b.memberToken
  return hubCall($, hub, 'POST', '/v1/act', payload, tok, b.sessionId)
}

// ---- local registry and sidebar key (8.1) ------------------------------------
// Both are read here in the plugin process. The key goes into the
// x-xmuse-sidebar header only; it never reaches $.state, the model, prompts,
// pane rendering, command output, or logs.

function procEnv(): Record<string, string | undefined> {
  try {
    if (typeof process !== 'undefined' && process && (process as any).env) return (process as any).env as Record<string, string | undefined>
  } catch {
    // no process in this host
  }
  return {}
}

function procPlatform(): string {
  try {
    if (typeof process !== 'undefined' && process && (process as any).platform) return String((process as any).platform)
  } catch {
    // ignore
  }
  return ''
}

function homeDir(): string {
  const e = procEnv()
  if (typeof e.HOME === 'string' && e.HOME) return e.HOME
  if (typeof e.USERPROFILE === 'string' && e.USERPROFILE) return e.USERPROFILE
  return ''
}

async function fsRead($: any, p: string): Promise<string> {
  try {
    const v = await $.fs.read(p)
    return typeof v === 'string' ? v : ''
  } catch {
    return ''
  }
}

function joinPath(dir: string, file: string): string {
  const sep = dir.includes('\\') && !dir.includes('/') ? '\\' : '/'
  return dir.replace(/[\\/]+$/, '') + sep + file
}

async function resolveRegistryDir($: any): Promise<string> {
  const cfg = option('registryDir')
  if (typeof cfg === 'string' && cfg) return cfg
  return registryDirFrom(procEnv(), procPlatform(), homeDir())
}

async function readSidebarKey($: any): Promise<string> {
  const d = await resolveRegistryDir($)
  if (!d) return ''
  const k = (await fsRead($, joinPath(d, 'sidebar.key'))).trim()
  return isKeyShape(k) ? k : ''
}

function pidAliveHere(pid: number): boolean {
  try {
    if (typeof process !== 'undefined' && process && typeof (process as any).kill === 'function') {
      ;(process as any).kill(pid, 0)
      return true
    }
  } catch (e) {
    return (e as any) && (e as any).code === 'EPERM'
  }
  return true // cannot check in this host: keep the entry, a failed join surfaces it
}

async function listLocalRooms($: any): Promise<{ dir: string; rooms: RegistryEntry[] }> {
  const d = await resolveRegistryDir($)
  if (!d) return { dir: '', rooms: [] }
  const text = await fsRead($, joinPath(d, 'hubs.json'))
  if (!text) return { dir: d, rooms: [] }
  return { dir: d, rooms: parseHubs(text, pidAliveHere) }
}

// ---- state helpers --------------------------------------------------------

async function setConn($: any, status: string, error: string, b?: Binding | null): Promise<void> {
  const now = await $.clock.now()
  const cur = (await read($, connAtom)) as any
  if (cur && cur.status === status && cur.error === error && (!b || (cur.memberId === b.memberId && cur.hub === b.hub && cur.roomId === b.roomId))) return
  await update($, connAtom, c => ({
    ...c,
    status,
    error,
    at: now,
    memberId: b ? b.memberId : status === 'none' ? '' : c.memberId,
    hub: b ? b.hub : status === 'none' ? '' : c.hub,
    roomId: b ? b.roomId : status === 'none' ? '' : c.roomId,
  }))
}

async function setNotice($: any, text: string): Promise<void> {
  await update($, uiAtom, u => ({ ...u, notice: text }))
}

async function resetView($: any): Promise<void> {
  await update($, viewAtom, () => null)
  await update($, moreAtom, () => ({ items: [], hasMore: true }))
}

// ---- flows (shared by commands and the pane) -------------------------------

type FlowResult = { ok: boolean; text: string }

async function createRoom($: any, name: string, memberId?: string, description?: string): Promise<FlowResult> {
  if (!name) return { ok: false, text: '用法：/xmuse room new <名字>' }
  const existing = await loadBinding($)
  if (existing) return { ok: false, text: '这个会话已经在房间里了，先 /xmuse leave' }
  const hub = await resolveHub($)
  const sid = String(await $.session.id())
  const cwd = String(await $.session.cwd())
  const payload: Record<string, unknown> = { dir: cwd, name, vendor: 'claude', session_id: sid }
  if (memberId) payload.member_id = memberId
  if (description) payload.description = description
  const key = await readSidebarKey($)
  const r = await hubCall($, hub, 'POST', '/v1/rooms', payload, undefined, undefined, key || undefined)
  if (!r.ok) {
    return { ok: false, text: '开房间失败：' + errText(r) + (r.status === 0 ? '。hub 没有运行？可用 /xmuse hub <url> 指定地址。' : '') }
  }
  const b: Binding = {
    hub,
    memberId: r.body.member_id,
    memberToken: r.body.member_token,
    operatorToken: r.body.operator_token,
    sessionId: sid,
    roomId: (r.body.room && r.body.room.id) || '',
  }
  await saveBinding($, b)
  setOwned(sid)
  await resetView($)
  await setConn($, 'ok', '', b)
  return { ok: true, text: `房间「${name}」已创建，你是主控 ${b.memberId}` }
}

async function joinRoom($: any, code: string): Promise<FlowResult> {
  if (!code) return { ok: false, text: '用法：/xmuse join <邀请码>' }
  const existing = await loadBinding($)
  if (existing) return { ok: false, text: '这个会话已经在房间里了，先 /xmuse leave' }
  const hub = await resolveHub($)
  const sid = String(await $.session.id())
  let ver = ''
  try {
    ver = String(await $.session.version())
  } catch {
    ver = ''
  }
  const r = await hubCall($, hub, 'POST', '/v1/join', {
    code,
    vendor: 'claude',
    session_id: sid,
    client_info: { client: 'claude-mod', mod: 'xmuse', version: ver },
  }, undefined, undefined, (await readSidebarKey($)) || undefined)
  if (!r.ok) {
    return { ok: false, text: '加入失败：' + errText(r) + (r.status === 0 ? '。hub 没有运行？可用 /xmuse hub <url> 指定地址。' : '') }
  }
  const b: Binding = {
    hub,
    memberId: r.body.member_id,
    memberToken: r.body.member_token,
    operatorToken: r.body.operator_token,
    sessionId: sid,
    roomId: '',
  }
  await saveBinding($, b)
  setOwned(sid)
  await resetView($)
  await setConn($, 'ok', '', b)
  return { ok: true, text: `已绑定为成员 ${b.memberId}` }
}

// One-click join of a local room (8.1): match by room_id or name in the
// registry, talk to that hub's own url with the sidebar key, save the binding.
async function joinLocalRoom(
  $: any,
  arg: string,
  extra?: { name?: string; role?: string; description?: string },
): Promise<FlowResult> {
  if (!arg) return { ok: false, text: '用法：/xmuse join-local <房间名或 room_id>' }
  const existing = await loadBinding($)
  if (existing) return { ok: false, text: '这个会话已经在房间里了，先 /xmuse leave' }
  const { rooms } = await listLocalRooms($)
  if (!rooms.length) return { ok: false, text: '本机没有登记的房间（hub 没启动？登记表目录对吗）' }
  let found = findRoom(rooms, { roomId: arg })
  if (found.error) found = findRoom(rooms, { name: arg })
  if (found.error || !found.entry) return { ok: false, text: '加入失败：' + (found.error || '找不到房间') }
  const entry = found.entry
  if (!isLoopbackUrl(entry.url)) return { ok: false, text: '加入失败：登记表里的 hub 地址不是本机回环地址，拒绝连接' }
  const key = await readSidebarKey($)
  if (!key) return { ok: false, text: '加入失败：读不到 sidebar.key（hub 还没生成？登记表目录对吗）' }
  const sid = String(await $.session.id())
  let ver = ''
  try {
    ver = String(await $.session.version())
  } catch {
    ver = ''
  }
  const hub = entry.url.replace(/\/$/, '')
  const body: Record<string, unknown> = {
    room_id: entry.room_id,
    vendor: 'claude',
    session_id: sid,
    client_info: { client: 'claude-mod', mod: 'xmuse', version: ver },
  }
  if (extra) {
    if (extra.name) body.name = extra.name
    if (extra.role) body.role = extra.role
    if (extra.description) body.description = extra.description
  }
  const r = await hubCall($, hub, 'POST', '/v1/join', body, undefined, undefined, key)
  if (!r.ok) return { ok: false, text: '加入失败：' + errText(r) }
  const b: Binding = {
    hub,
    memberId: r.body.member_id,
    memberToken: r.body.member_token,
    operatorToken: r.body.operator_token,
    sessionId: sid,
    roomId: (r.body.room && r.body.room.id) || entry.room_id,
  }
  await saveBinding($, b)
  setOwned(sid)
  await resetView($)
  await setConn($, 'ok', '', b)
  return { ok: true, text: `已加入房间「${entry.name}」，绑定为成员 ${b.memberId}` }
}

async function leaveRoom($: any): Promise<FlowResult> {
  const b = await loadBinding($)
  if (!b) return { ok: false, text: '这个会话没有在房间里' }
  const hub = await resolveHub($, b)
  const r = await hubCall($, hub, 'POST', '/v1/leave', {}, b.memberToken, b.sessionId)
  await clearBinding($)
  setOwned(null)
  await resetView($)
  await update($, uiAtom, u => ({ ...INITIAL_UI, section: u.section }))
  await update($, connAtom, () => INITIAL_CONN)
  return {
    ok: true,
    text: r.ok ? '已离开房间' : '已在本地解绑（hub 返回：' + errText(r) + '）',
  }
}

async function rebindSession($: any): Promise<FlowResult> {
  const b = await loadBinding($)
  if (!b) return { ok: false, text: '这个会话没有绑定记录' }
  const hub = await resolveHub($, b)
  const sid = String(await $.session.id())
  // No x-xmuse-session header: the old id is exactly what we are replacing.
  const r = await hubCall($, hub, 'POST', '/v1/rebind', { session_id: sid }, b.memberToken)
  if (!r.ok) return { ok: false, text: '重新声明失败：' + errText(r) }
  await saveBinding($, { ...b, hub, sessionId: sid })
  setOwned(sid)
  await setConn($, 'ok', '', { ...b, hub, sessionId: sid })
  return { ok: true, text: '已把成员 ' + b.memberId + ' 重新绑定到当前会话' }
}

async function currentView($: any) {
  return read($, viewAtom)
}

// ===== poll.ts =====

// ---------------------------------------------------------------------------
// Background loop: long-poll /v1/view with the MEMBER token only, keep the
// sidebar state fresh, and wake the session for new `for_me` messages.
// Started from session.start with $.clock.every; every wake-up is submitted
// from the timer callback (D0: submit from command.run does not start a turn).
// ---------------------------------------------------------------------------

let busy = false
let pending = false // a wake-up prompt was submitted and its turn has not started
let skipUntil = 0
const MAX_PER_WAKE = 10
const MAX_TEXT = 2000

async function pollOnce($: any, waitOverride?: number): Promise<void> {
  if (busy) return
  busy = true
  try {
    await pollInner($, waitOverride)
  } catch (err) {
    try {
      await setConn($, 'down', String(err))
    } catch {
      // the environment is going away (reload / session end): nothing to report to
    }
  } finally {
    busy = false
  }
}

async function pollInner($: any, waitOverride?: number): Promise<void> {
  const now = await $.clock.now()
  if (now < skipUntil) return
  let b = await loadBinding($)
  if (!b) return
  const cur = String(await $.session.id())

  if (getOwned() === null) {
    if (b.sessionId === cur) setOwned(cur)
    else {
      await setConn($, 'stale', '绑定的是另一个会话，/xmuse rebind 把成员接到当前会话', b)
      return
    }
  }
  if (getOwned() !== cur) {
    // same plugin instance, new session id (e.g. /clear): re-declare, no new code
    const r = await rebindSession($)
    if (!r.ok) {
      await setConn($, 'down', r.text, b)
      skipUntil = now + 5000
      return
    }
    const nb = await loadBinding($)
    if (!nb) return
    b = nb
  }

  const hub = await resolveHub($, b)
  const prev = (await read($, viewAtom)) as XmuseView | null
  const since = prev ? prev.version : 0
  const cfgWait = Number(option('pollWaitSeconds') ?? 15)
  const wait = waitOverride !== undefined ? waitOverride : Math.max(1, Math.min(30, isFinite(cfgWait) ? cfgWait : 15))
  const r = await hubCall($, hub, 'GET', `/v1/view?since=${since}&wait=${wait}`, undefined, b.memberToken, cur)

  // the binding may have been changed (leave / join) while we were hanging
  const still = await loadBinding($)
  if (!still || still.memberToken !== b.memberToken) return

  if (r.status === 204) {
    await setConn($, 'ok', '', b)
    return
  }
  if (r.status === 0) {
    await setConn($, 'down', (r.body && r.body.message) || '连不上 hub', b)
    skipUntil = now + 3000
    return
  }
  if (r.status === 401) {
    await setConn($, 'unauth', '令牌已失效（可能被移出房间）：' + errText(r), b)
    skipUntil = now + 10000
    return
  }
  if (r.status === 409 && r.body && r.body.error === 'not_bound_session') {
    setOwned(null)
    await setConn($, 'stale', '会话与 hub 记录的不一致，/xmuse rebind', b)
    skipUntil = now + 5000
    return
  }
  if (!r.ok || !r.body || !r.body.version) {
    await setConn($, 'down', errText(r), b)
    skipUntil = now + 3000
    return
  }

  const view = r.body as XmuseView
  await update($, viewAtom, () => view)
  // a fresh snapshot replaces the first page; keep older pages only if consistent
  await update($, moreAtom, m => {
    const oldest = view.timeline.length ? view.timeline[0].id : 0
    const items = m.items.filter(x => x.id < oldest)
    return { items, hasMore: items.length ? m.hasMore : view.timeline_cursor.has_more }
  })
  await setConn($, 'ok', '', { ...b, roomId: view.room.id })
  await maybeWake($, b, view)
}

async function maybeWake($: any, b: Binding, view: XmuseView): Promise<void> {
  const me = view.members.find(m => m.id === b.memberId)
  const mine = view.timeline.filter(m => m.for_me && m.kind === 'message' && m.from !== b.memberId)
  const key = 'delivered:' + b.memberId + ':' + view.room.id
  let deliveredMax: number | undefined
  try {
    const v = await $.store.get(key)
    if (typeof v === 'number') deliveredMax = v
  } catch {
    deliveredMax = undefined
  }
  const { fresh, newMax } = pickFresh(mine, me ? me.unread : 0, deliveredMax)
  if (deliveredMax === undefined && fresh.length === 0) {
    await $.store.set(key, newMax)
    return
  }
  if (fresh.length === 0 || pending) return // held until the previous wake-up's turn has started
  const batch = fresh.slice(-MAX_PER_WAKE)
  const text = wakePrompt(view, b.memberId, batch)
  pending = true
  await $.store.set(key, newMax)
  const p = $.prompt.submit({ text })
  void Promise.resolve(p).then(
    () => {
      pending = false
    },
    () => {
      pending = false
    },
  )
}

// ===== actions.ts =====

// Handlers for the sidebar's buttons and inputs. All of them run in a press /
// submit handler (never in render) and report through ui.notice.

async function sendDraft($: any): Promise<void> {
  const ui = await read($, uiAtom)
  const b = await loadBinding($)
  if (!b) return setNotice($, '还没有绑定房间')
  const text = ui.draft.trim()
  if (!text) return setNotice($, '消息是空的')
  if (!ui.to) return setNotice($, '先选收件人或话题')
  const view = (await read($, viewAtom)) as XmuseView | null
  const mentions = (view ? view.members : []).map(m => m.id).filter(id => text.includes('@' + id))
  const r = await actCall($, b, { act: 'say', to: ui.to, text, mentions }, 'operator')
  if (!r.ok) return setNotice($, '发送失败：' + errText(r))
  await update($, uiAtom, u => ({ ...u, draft: '', notice: '' }))
}

async function markRead($: any): Promise<void> {
  const b = await loadBinding($)
  const view = (await read($, viewAtom)) as XmuseView | null
  if (!b || !view) return
  const ids = view.timeline.filter(m => m.for_me).map(m => m.id)
  if (ids.length === 0) return
  const r = await actCall($, b, { act: 'ack', ids }, 'member')
  if (!r.ok) await setNotice($, '标已读失败：' + errText(r))
}

async function loadOlder($: any): Promise<void> {
  const b = await loadBinding($)
  const view = (await read($, viewAtom)) as XmuseView | null
  const more = await read($, moreAtom)
  if (!b || !view) return
  const oldest = more.items.length ? more.items[0].id : view.timeline.length ? view.timeline[0].id : 0
  const hub = await resolveHub($, b)
  const r = await hubCall($, hub, 'GET', `/v1/timeline?before=${oldest}&limit=50`, undefined, b.operatorToken, b.sessionId)
  if (!r.ok) return setNotice($, '加载更早消息失败：' + errText(r))
  const items = (r.body.items || []) as XmuseMessage[]
  await update($, moreAtom, m => ({ items: [...items, ...m.items], hasMore: !!r.body.has_more }))
}

async function decide($: any, id: string, decision: 'once' | 'always' | 'reject'): Promise<void> {
  const b = await loadBinding($)
  if (!b) return
  const r = await actCall($, b, { act: 'approve', id, decision }, 'operator')
  if (!r.ok) await setNotice($, `审批 ${id} 失败：` + errText(r))
  else await setNotice($, '')
}

async function alignDecide($: any, id: string, decision: 'confirm' | 'reject'): Promise<void> {
  const b = await loadBinding($)
  if (!b) return
  const r = await actCall($, b, { act: 'align', id, decision }, 'operator')
  if (!r.ok) await setNotice($, `对齐条目 ${id} 操作失败：` + errText(r))
}

async function memberAct($: any, kind: 'pause' | 'resume' | 'remove' | 'transfer_host'): Promise<void> {
  const ui = await read($, uiAtom)
  const b = await loadBinding($)
  if (!b) return
  if (!ui.target) return setNotice($, '先选一个成员')
  const r = await actCall($, b, { act: kind, member: ui.target }, 'operator')
  if (!r.ok) await setNotice($, `${kind} 失败：` + errText(r))
  else await setNotice($, '')
}

async function makeInvite($: any): Promise<void> {
  const ui = await read($, uiAtom)
  const b = await loadBinding($)
  if (!b) return setNotice($, '还没有绑定房间')
  const description = ui.invDesc.trim()
  if (!description) return setNotice($, '邀请需要填一段职责描述')
  const r = await actCall($, b, { act: 'invite', vendor: ui.invVendor, role: ui.invRole, description }, 'operator')
  if (!r.ok) return setNotice($, '创建邀请失败：' + errText(r))
  const inv = { code: r.body.code, command: r.body.command, expires_at: r.body.expires_at, vendor: ui.invVendor, role: ui.invRole }
  await update($, uiAtom, u => ({ ...u, lastInvite: inv, invDesc: '', notice: '' }))
  try {
    $.ui.toast(`邀请码 ${inv.code}（${inv.vendor}）：在目标会话里运行 ${inv.command}`)
  } catch {
    // toast is a convenience
  }
}

// Room list for the pane: re-read at most every 15 s (rooms come and go).
let roomsCache: { at: number; rooms: RegistryEntry[] } = { at: 0, rooms: [] }

async function cachedRooms($: any, force?: boolean): Promise<RegistryEntry[]> {
  let now = 0
  try {
    now = await $.clock.now()
  } catch {
    now = Date.now() / 1000
  }
  if (!force && now - roomsCache.at < 15) return roomsCache.rooms
  const { rooms } = await listLocalRooms($)
  roomsCache = { at: now, rooms }
  return rooms
}

async function joinLocalFromPane($: any, roomId: string): Promise<void> {
  const r = await joinLocalRoom($, roomId)
  await setNotice($, r.ok ? '' : r.text)
  if (r.ok) {
    roomsCache = { at: 0, rooms: [] }
    void pollOnce($, 0)
  }
}

async function addFromPane($: any): Promise<void> {
  const ui = await read($, uiAtom)
  const b = await loadBinding($)
  if (!b) return setNotice($, '还没有绑定房间')
  if (!ui.addDesc.trim()) return setNotice($, '添加成员需要填一段职责描述')
  const body: Record<string, unknown> = { act: 'member_add', vendor: ui.addVendor, role: ui.addRole, description: ui.addDesc.trim() }
  if (ui.addModel.trim()) body.model = ui.addModel.trim()
  if (ui.addName.trim()) body.name = ui.addName.trim()
  const r = await actCall($, b, body, 'operator')
  if (!r.ok) return setNotice($, '添加成员失败：' + errText(r))
  await update($, uiAtom, u => ({ ...u, addDesc: '', addName: '', addModel: '', notice: `已添加成员 ${r.body.member_id}` }))
}

async function memberEditFromPane($: any): Promise<void> {
  const ui = await read($, uiAtom)
  const b = await loadBinding($)
  if (!b) return
  if (!ui.target) return setNotice($, '先选一个成员')
  const body: Record<string, unknown> = { act: 'member_edit', member: ui.target }
  if (ui.editRole) body.role = ui.editRole
  if (ui.editDesc.trim()) body.description = ui.editDesc.trim()
  if (ui.editModel.trim()) body.model = ui.editModel.trim()
  if (!body.role && !body.description && !body.model) return setNotice($, '至少改一项（角色/描述/模型）')
  const r = await actCall($, b, body, 'operator')
  if (!r.ok) await setNotice($, `改成员失败：` + errText(r))
  else await update($, uiAtom, u => ({ ...u, editRole: '', editDesc: '', editModel: '', notice: '' }))
}

async function dmFromPane($: any): Promise<void> {
  const ui = await read($, uiAtom)
  const view = (await read($, viewAtom)) as XmuseView | null
  if (!view) return
  if (!ui.target) return setNotice($, '先选一个成员')
  const id = 'dm:' + [view.me.id, ui.target].sort().join('+')
  await setUi($, { thread: id, section: 'timeline' })
}

async function groupAddFromPane($: any): Promise<void> {
  const ui = await read($, uiAtom)
  const b = await loadBinding($)
  if (!b) return
  if (!ui.target) return setNotice($, '先选一个成员')
  if (!ui.grpPick) return setNotice($, '先选一个私有群')
  const r = await actCall($, b, { act: 'thread_add', thread: ui.grpPick, member: ui.target }, 'operator')
  if (!r.ok) await setNotice($, `拉进群失败：` + errText(r))
  else await setNotice($, '')
}

async function groupNewFromPane($: any): Promise<void> {
  const ui = await read($, uiAtom)
  const b = await loadBinding($)
  if (!b) return setNotice($, '还没有绑定房间')
  const id = ui.grpId.trim()
  if (!id || id.charAt(0) !== '#') return setNotice($, '群 id 形如 #名字')
  const members = ui.grpMembers.split(/[\s,]+/).filter(Boolean)
  const r = await actCall($, b, { act: 'thread_new', id, members, title: ui.grpTitle.trim() || id }, 'operator')
  if (!r.ok) return setNotice($, '新建群失败：' + errText(r))
  await update($, uiAtom, u => ({ ...u, grpId: '', grpTitle: '', grpMembers: '', notice: `已建私有群 ${r.body.thread}` }))
}

async function groupRemoveFromPane($: any, thread: string, member: string): Promise<void> {
  const b = await loadBinding($)
  if (!b) return
  const r = await actCall($, b, { act: 'thread_remove', thread, member }, 'operator')
  if (!r.ok) await setNotice($, `移出失败：` + errText(r))
  else await setNotice($, '')
}

async function wakeHostFromPane($: any): Promise<void> {
  const b = await loadBinding($)
  if (!b) return setNotice($, '还没有绑定房间')
  const r = await actCall($, b, { act: 'wake_host' }, 'operator')
  if (!r.ok) return setNotice($, '叫醒失败：' + errText(r))
  await setNotice($, `已叫醒主控，放出 ${r.body && r.body.released !== undefined ? r.body.released : '?'} 条结果`)
}

async function newRoomFromPane($: any): Promise<void> {
  const ui = await read($, uiAtom)
  const r = await createRoom($, ui.newRoom.trim())
  await setNotice($, r.ok ? '' : r.text)
  if (r.ok) await update($, uiAtom, u => ({ ...u, newRoom: '' }))
}

async function joinFromPane($: any): Promise<void> {
  const ui = await read($, uiAtom)
  const r = await joinRoom($, ui.joinCode.trim())
  await setNotice($, r.ok ? '' : r.text)
  if (r.ok) await update($, uiAtom, u => ({ ...u, joinCode: '' }))
}

async function leaveFromPane($: any): Promise<void> {
  const r = await leaveRoom($)
  await setNotice($, r.ok ? '' : r.text)
}

async function rebindFromPane($: any): Promise<void> {
  const r = await rebindSession($)
  await setNotice($, r.ok ? '' : r.text)
}

async function openPane($: any): Promise<boolean> {
  try {
    const r = await $.ui.open({ id: PANE, title: 'xmuse' })
    return !!(r && r.isPlaced)
  } catch {
    return false
  }
}

// ===== commands.ts =====

const USAGE = [
  '/xmuse room new <名字>        开房间（本会话成为主控）',
  '/xmuse invite <provider> <角色> <职责描述>   生成邀请码（码显示在侧栏里）',
  '/xmuse join <邀请码>          把本会话绑定为房间成员',
  '/xmuse rooms                  列出本机房间（一键加入不用邀请码）',
  '/xmuse join-local <房间名或 room_id>   一键加入本机房间',
  '/xmuse add <厂商> <模型|-> <角色> <描述>   添加成员（hub 起回合）',
  '/xmuse group new #id [成员 …]  新建私有群',
  '/xmuse wake-host               现在叫醒主控',
  '/xmuse status | open | leave | rebind',
  '/xmuse hub <url>             指定 hub 地址（hub clear 清除）',
].join('\n')

// NOTE: command output is written to the transcript and read by the model.
// Never print tokens; an invite code goes to the pane and a toast, not here.
async function runCommand($: any, args: string): Promise<{ text: string; exitCode?: number }> {
  const parts = args.trim().split(/\s+/).filter(Boolean)
  const sub = (parts[0] || 'status').toLowerCase()
  const rest = parts.slice(1)

  if (sub === 'room') {
    if ((rest[0] || '').toLowerCase() !== 'new' || rest.length < 2) return { text: USAGE, exitCode: 2 }
    const r = await createRoom($, rest.slice(1).join(' '))
    if (r.ok) {
      await openPane($)
      void pollOnce($, 0)
    }
    return { text: r.text, exitCode: r.ok ? 0 : 1 }
  }

  if (sub === 'join') {
    const r = await joinRoom($, rest[0] || '')
    if (r.ok) {
      await openPane($)
      void pollOnce($, 0)
    }
    return { text: r.text, exitCode: r.ok ? 0 : 1 }
  }

  if (sub === 'rooms') {
    const { rooms } = await listLocalRooms($)
    if (!rooms.length) return { text: '本机没有登记的房间（hub 没启动？登记表目录对吗）。也可以 /xmuse room new 开一间。' }
    const lines = rooms.map(r => `- ${r.name} \`${r.room_id}\` · 目录 ${r.dir} · 主控 ${r.host || '?'}`)
    return { text: `本机房间（${rooms.length}）：\n${lines.join('\n')}\n用 /xmuse join-local <房间名或 room_id> 一键加入` }
  }

  if (sub === 'join-local') {
    const r = await joinLocalRoom($, rest[0] || '')
    if (r.ok) {
      await openPane($)
      void pollOnce($, 0)
    }
    return { text: r.text, exitCode: r.ok ? 0 : 1 }
  }

  if (sub === 'add') {
    if (rest.length < 4) return { text: '用法：/xmuse add <厂商> <模型|-> <角色> <描述…>', exitCode: 2 }
    const b = await loadBinding($)
    if (!b) return { text: '这个会话还没有加入房间（/xmuse room new 或 /xmuse join）', exitCode: 1 }
    const [vendor, model, role, ...desc] = rest
    const body: Record<string, unknown> = { act: 'member_add', vendor, role, description: desc.join(' ') }
    if (model && model !== '-') body.model = model
    const r = await actCall($, b, body, 'operator')
    if (!r.ok) return { text: '添加成员失败：' + errText(r), exitCode: 1 }
    return { text: `已添加成员 ${r.body.member_id}（${vendor}/${role}），hub 会起它的回合` }
  }

  if (sub === 'group') {
    if ((rest[0] || '').toLowerCase() !== 'new' || rest.length < 2) return { text: '用法：/xmuse group new #id [成员 …]', exitCode: 2 }
    const b = await loadBinding($)
    if (!b) return { text: '这个会话还没有加入房间（/xmuse room new 或 /xmuse join）', exitCode: 1 }
    const id = rest[1]
    const members = rest.slice(2)
    const r = await actCall($, b, { act: 'thread_new', id, members, title: id }, 'operator')
    if (!r.ok) return { text: '新建群失败：' + errText(r), exitCode: 1 }
    return { text: `私有群 ${r.body.thread} 已建${members.length ? '，成员：' + members.join('、') : ''}（你自动在内）` }
  }

  if (sub === 'wake-host') {
    const b = await loadBinding($)
    if (!b) return { text: '这个会话还没有加入房间（/xmuse room new 或 /xmuse join）', exitCode: 1 }
    const r = await actCall($, b, { act: 'wake_host' }, 'operator')
    if (!r.ok) return { text: '叫醒失败：' + errText(r), exitCode: 1 }
    return { text: `已叫醒主控，放出 ${r.body && r.body.released !== undefined ? r.body.released : '?'} 条结果` }
  }

  if (sub === 'invite') {
    if (rest.length < 3) return { text: '用法：/xmuse invite <provider> <角色> <职责描述>', exitCode: 2 }
    const b = await loadBinding($)
    if (!b) return { text: '这个会话还没有加入房间（/xmuse room new 或 /xmuse join）', exitCode: 1 }
    const [vendor, role, ...desc] = rest
    const r = await actCall($, b, { act: 'invite', vendor, role, description: desc.join(' ') }, 'operator')
    if (!r.ok) return { text: '创建邀请失败：' + errText(r), exitCode: 1 }
    const inv = { code: r.body.code, command: r.body.command, expires_at: r.body.expires_at, vendor, role }
    await update($, uiAtom, u => ({ ...u, section: 'room', lastInvite: inv }))
    await openPane($)
    try {
      $.ui.toast(`邀请码 ${inv.code}（${vendor}）：在目标会话里运行 ${inv.command}`)
    } catch {
      // toast is a convenience
    }
    return { text: `邀请已创建（${vendor}/${role}，10 分钟内有效）。邀请码和命令见 xmuse 侧栏「房间」，没有侧栏时看刚才的提示条。` }
  }

  if (sub === 'open') {
    const placed = await openPane($)
    return { text: placed ? 'xmuse 侧栏已打开' : '侧栏没有摆出来（终端太窄？加宽到 110 列以上，或在桌面版里使用）' }
  }

  if (sub === 'leave') {
    const r = await leaveRoom($)
    return { text: r.text, exitCode: r.ok ? 0 : 1 }
  }

  if (sub === 'rebind') {
    const r = await rebindSession($)
    if (r.ok) void pollOnce($, 0)
    return { text: r.text, exitCode: r.ok ? 0 : 1 }
  }

  if (sub === 'hub') {
    if (rest[0] === 'clear') {
      await $.store.delete('hubUrl')
      return { text: '已清除 hub 地址覆盖，按配置/ hub.json / 默认值推断' }
    }
    if (rest[0]) {
      if (!/^https?:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?\/?$/.test(rest[0])) {
        return { text: 'hub 地址只接受本机回环地址，如 http://127.0.0.1:43117', exitCode: 2 }
      }
      await $.store.set('hubUrl', rest[0].replace(/\/$/, ''))
      return { text: 'hub 地址已设为 ' + rest[0] }
    }
    const b = await loadBinding($)
    return { text: 'hub 地址：' + (await resolveHub($, b)) }
  }

  if (sub === 'status') {
    const b = await loadBinding($)
    if (!b) return { text: 'xmuse：这个会话没有在房间里。\n' + USAGE }
    const view = (await read($, viewAtom)) as XmuseView | null
    if (!view) {
      void pollOnce($, 0)
      return { text: `xmuse：已绑定为 ${b.memberId}，还没取到房间数据（hub ${await resolveHub($, b)}）` }
    }
    const online = view.members.filter(m => m.online).length
    const banner = bannerText(view, b.memberId)
    return {
      text:
        `xmuse 房间「${view.room.name}」· 我是 ${b.memberId}${view.room.host === b.memberId ? '（主控）' : ''} · 成员 ${view.members.length}（在线 ${online}）` +
        (banner ? ` · ${banner}` : ''),
    }
  }

  void option
  return { text: USAGE, exitCode: 2 }
}

// ===== ui.tsx =====

const SECTIONS: { id: string; label: string }[] = [
  { id: 'timeline', label: '时间线' },
  { id: 'members', label: '成员' },
  { id: 'groups', label: '群组' },
  { id: 'host', label: '主控' },
  { id: 'approvals', label: '审批' },
  { id: 'alignment', label: '对齐' },
  { id: 'room', label: '房间' },
]

const VENDORS = [
  { value: 'claude', label: 'Claude' },
  { value: 'opencode', label: 'OpenCode' },
  { value: 'dsh', label: 'dsh' },
]
const ROLES = [
  { value: 'executor', label: 'executor 执行' },
  { value: 'reviewer', label: 'reviewer 审查' },
  { value: 'planner', label: 'planner 规划' },
  { value: 'coordinator', label: 'coordinator 协调' },
]

function setUi($: any, patch: Partial<XmuseUi>) {
  return update($, uiAtom, (u: XmuseUi) => ({ ...u, ...patch }))
}

// ---- room list (shared by the unbound box and the room section) --------------

function roomsList($: any, rooms: RegistryEntry[], current: string) {
  if (!rooms.length) return <Text dimColor>本机没有登记的房间（hub 没启动？登记表目录对吗）</Text>
  return (
    <Box flexDirection="column" gap={1}>
      {rooms.map(r => (
        <Box key={'rl-row-' + r.room_id}>
          <Text>
            {r.room_id === current ? '● ' : ''}{r.name}（{r.room_id}）· {r.dir} · 主控 {r.host || '?'}
            {r.room_id === current ? '（当前）' : ''}{' '}
          </Text>
          {r.room_id === current ? null : (
            <Button key={'rl-go-' + r.room_id} label="加入" variant="primary" onPress={() => joinLocalFromPane($, r.room_id)} />
          )}
        </Box>
      ))}
    </Box>
  )
}

// ---- the sidebar pane -----------------------------------------------------

async function renderPane($: any, e: any) {
  const { Box, Text, Button, Markdown, Input, Select } = $.ui.resolve(e) as any
  const ui = (await read($, uiAtom)) as XmuseUi
  const conn = await read($, connAtom)
  const view = await read($, viewAtom)
  const more = await read($, moreAtom)

  const notice = ui.notice ? <Text color="red">{ui.notice}</Text> : null

  // --- not in a room: rooms / open / join forms ---
  const preRooms = await cachedRooms($)
  if (conn.status === 'none') {
    return (
      <Box flexDirection="column" gap={1}>
        <Text bold>xmuse：这个会话还没有加入房间</Text>
        <Text bold>本机房间（一键加入，不用邀请码）</Text>
        {roomsList($, preRooms, '')}
        <Button key="rl-refresh" label="刷新房间列表" onPress={() => cachedRooms($, true).then(() => setNotice($, '房间列表已刷新'))} />
        <Text dimColor>开房间：当前会话成为主控（也是房间里的一个成员）。</Text>
        <Input
          key="new-room"
          label="房间名"
          placeholder="xmuse-dev"
          value={ui.newRoom}
          submitLabel="开房间"
          onInput={(v: string) => setUi($, { newRoom: v })}
          onSubmit={() => newRoomFromPane($)}
        />
        <Button key="new-room-go" label="开房间" variant="primary" onPress={() => newRoomFromPane($)} />
        <Text dimColor>加入：粘贴别处生成的邀请码（10 分钟内有效，只能用一次）。</Text>
        <Input
          key="join-code"
          label="邀请码"
          placeholder="K7Q2-9F"
          value={ui.joinCode}
          submitLabel="加入"
          onInput={(v: string) => setUi($, { joinCode: v })}
          onSubmit={() => joinFromPane($)}
        />
        <Button key="join-go" label="加入" onPress={() => joinFromPane($)} />
        {notice}
      </Box>
    )
  }

  const connLine =
    conn.status === 'ok'
      ? null
      : (
          <Box flexDirection="column">
            <Text color="yellow">
              {conn.status === 'down' ? 'hub 连接中断，重试中：' : conn.status === 'stale' ? '会话已变：' : conn.status === 'unauth' ? '令牌失效：' : ''}
              {clip(conn.error, 200)}
            </Text>
            {conn.status === 'stale' ? <Button key="rebind" label="接管：把成员绑定到当前会话" variant="primary" onPress={() => rebindFromPane($)} /> : null}
          </Box>
        )

  if (!view) {
    return (
      <Box flexDirection="column" gap={1}>
        <Text bold>xmuse：已绑定为 {conn.memberId || '?'}，正在从 hub 取数据…</Text>
        {connLine}
        <Button key="leave" label="离开房间" onPress={() => leaveFromPane($)} />
        {notice}
      </Box>
    )
  }

  const meId = view.me.id
  const isHost = view.room.host === meId
  const nApprovals = view.approvals.length
  const nUnread = (view.members.find(m => m.id === meId) || { unread: 0 }).unread

  const tabs = (
    <Box>
      {SECTIONS.map(s => {
        const badge = s.id === 'approvals' && nApprovals ? ` ${nApprovals}` : s.id === 'timeline' && nUnread ? ` ${nUnread}` : ''
        return (
          <Button
            key={'sec-' + s.id}
            label={(ui.section === s.id ? '● ' : '') + s.label + badge}
            variant={ui.section === s.id ? 'primary' : undefined}
            onPress={() => setUi($, { section: s.id })}
          />
        )
      })}
    </Box>
  )

  let body: any = null
  if (ui.section === 'timeline') {
    const threadOptions = [{ value: 'all', label: '全部（按话题/私聊分组）' }].concat(
      view.threads.map(t => ({ value: t.id, label: t.title + (t.unread ? ` (${t.unread})` : '') })),
    )
    const recips = recipientOptions(view, meId)
    const to = recips.some(r => r.value === ui.to) ? ui.to : recips.length ? recips[0].value : ''
    body = (
      <Box flexDirection="column" gap={1}>
        <Select
          key="thread"
          label="查看"
          value={threadOptions.some(o => o.value === ui.thread) ? ui.thread : 'all'}
          options={threadOptions}
          onSelect={(v: string) => setUi($, { thread: v })}
        />
        <Markdown text={renderTimeline(view, more.items, ui.thread)} />
        <Box>
          {more.hasMore || view.timeline_cursor.has_more ? <Button key="older" label="加载更早的" onPress={() => loadOlder($)} /> : null}
          {nUnread ? <Button key="markread" label={`@我的 ${nUnread} 条标为已读`} onPress={() => markRead($)} /> : null}
        </Box>
        {recips.length ? (
          <Box flexDirection="column">
            <Select key="to" label="发给" value={to} options={recips} onSelect={(v: string) => setUi($, { to: v })} />
            <Input
              key="draft"
              label="消息"
              placeholder="可以用 @成员 点名"
              value={ui.draft}
              submitLabel="发送"
              onInput={(v: string) => setUi($, { draft: v, to })}
              onSubmit={() => sendDraft($)}
            />
            <Button key="send" label="发送" variant="primary" onPress={() => setUi($, { to }).then(() => sendDraft($))} />
          </Box>
        ) : (
          <Text dimColor>房间里还没有其他成员，先到「房间」里邀请。</Text>
        )}
      </Box>
    )
  } else if (ui.section === 'members') {
    const others = view.members.map(m => ({ value: m.id, label: m.id }))
    const target = others.some(o => o.value === ui.target) ? ui.target : others.length ? others[0].value : ''
    const privates = view.threads.filter(t => t.private)
    const grpPick = privates.some(t => t.id === ui.grpPick) ? ui.grpPick : privates.length ? privates[0].id : ''
    body = (
      <Box flexDirection="column" gap={1}>
        <Markdown text={renderMembers(view, meId)} />
        {target ? (
          <Box flexDirection="column">
            <Select key="target" label="成员菜单" value={target} options={others} onSelect={(v: string) => setUi($, { target: v })} />
            <Box>
              <Button key="m-pause" label="暂停" onPress={() => setUi($, { target }).then(() => memberAct($, 'pause'))} />
              <Button key="m-resume" label="恢复" onPress={() => setUi($, { target }).then(() => memberAct($, 'resume'))} />
              <Button key="m-host" label="设为主控" onPress={() => setUi($, { target }).then(() => memberAct($, 'transfer_host'))} />
              <Button key="m-remove" label="移出" onPress={() => setUi($, { target }).then(() => memberAct($, 'remove'))} />
              <Button key="m-dm" label="私聊" onPress={() => setUi($, { target }).then(() => dmFromPane($))} />
            </Box>
            <Box>
              <Select
                key="m-edit-role"
                label="改角色"
                value={ui.editRole}
                options={[{ value: '', label: '不改' }].concat(ROLES)}
                onSelect={(v: string) => setUi($, { editRole: v })}
              />
              <Input
                key="m-edit-desc"
                label="改描述"
                placeholder="职责描述（空=不改）"
                value={ui.editDesc}
                submitLabel="保存修改"
                onInput={(v: string) => setUi($, { editDesc: v })}
                onSubmit={() => memberEditFromPane($)}
              />
              <Input
                key="m-edit-model"
                label="改模型"
                placeholder="模型（空=不改）"
                value={ui.editModel}
                submitLabel="保存修改"
                onInput={(v: string) => setUi($, { editModel: v })}
                onSubmit={() => memberEditFromPane($)}
              />
              <Button key="m-edit-go" label="保存修改" variant="primary" onPress={() => memberEditFromPane($)} />
            </Box>
            {privates.length ? (
              <Box>
                <Select
                  key="m-grp"
                  label="拉进群"
                  value={grpPick}
                  options={privates.map(t => ({ value: t.id, label: t.title || t.id }))}
                  onSelect={(v: string) => setUi($, { grpPick: v })}
                />
                <Button key="m-grp-go" label="拉进群" onPress={() => setUi($, { grpPick }).then(() => groupAddFromPane($))} />
              </Box>
            ) : null}
          </Box>
        ) : null}
      </Box>
    )
  } else if (ui.section === 'groups') {
    const privates = view.threads.filter(t => t.private)
    body = (
      <Box flexDirection="column" gap={1}>
        <Text bold>新建私有群（你自动在内）</Text>
        <Input
          key="grp-id"
          label="群 id"
          placeholder="#g1"
          value={ui.grpId}
          submitLabel="新建群"
          onInput={(v: string) => setUi($, { grpId: v })}
          onSubmit={() => groupNewFromPane($)}
        />
        <Input
          key="grp-title"
          label="标题"
          placeholder="可空，默认同 id"
          value={ui.grpTitle}
          submitLabel="新建群"
          onInput={(v: string) => setUi($, { grpTitle: v })}
          onSubmit={() => groupNewFromPane($)}
        />
        <Input
          key="grp-members"
          label="成员"
          placeholder="空格分隔，如 dsh-1 claude-2"
          value={ui.grpMembers}
          submitLabel="新建群"
          onInput={(v: string) => setUi($, { grpMembers: v })}
          onSubmit={() => groupNewFromPane($)}
        />
        <Button key="grp-go" label="新建群" variant="primary" onPress={() => groupNewFromPane($)} />
        {privates.length ? (
          <Box flexDirection="column" gap={1}>
            {privates.map(t => (
              <Box key={'grp-' + t.id} flexDirection="column">
                <Text bold>🔒{t.title || t.id}（{t.id}）</Text>
                <Text dimColor>{t.members.join('、')}</Text>
                <Box>
                  {t.members.filter(mid => mid !== 'human').map(mid => (
                    <Button key={`grm-${t.id}-${mid}`} label={`移出 ${mid}`} onPress={() => groupRemoveFromPane($, t.id, mid)} />
                  ))}
                </Box>
              </Box>
            ))}
          </Box>
        ) : (
          <Text dimColor>还没有私有群</Text>
        )}
      </Box>
    )
  } else if (ui.section === 'host') {
    body = (
      <Box flexDirection="column" gap={1}>
        <Markdown text={renderHostWait(view)} />
        <Button key="wake-go" label="现在叫醒主控" variant="primary" onPress={() => wakeHostFromPane($)} />
      </Box>
    )
  } else if (ui.section === 'approvals') {
    body =
      nApprovals === 0 ? (
        <Text dimColor>没有待审批的请求</Text>
      ) : (
        <Box flexDirection="column" gap={1}>
          {view.approvals.map(a => (
            <Box key={'ap-' + a.id} flexDirection="column">
              <Text bold>
                {a.id} · {a.member} · {a.kind}
                {a.risk === 'high' ? '（高风险：hub 会弹 Windows Hello）' : ''}
              </Text>
              <Text>{clip(a.summary, 200)}</Text>
              {(() => {
                const d = a.detail as any
                if (d && typeof d === 'object') {
                  // share 审批的 detail 是对象（8.6）：显示摘录、目标和原因。
                  const bits = [
                    d.message_id !== undefined ? '#' + d.message_id : '',
                    d.to ? '给 ' + d.to : '',
                    d.why ? '原因 ' + d.why : '',
                  ].filter(Boolean)
                  return (
                    <Box flexDirection="column">
                      {d.excerpt ? <Text>{clip(String(d.excerpt), 300)}</Text> : null}
                      {bits.length ? <Text dimColor>{bits.join(' · ')}</Text> : null}
                    </Box>
                  )
                }
                return d ? <Text dimColor>{clip(d, 300)}</Text> : null
              })()}
              <Box>
                <Button key={`ap-${a.id}-once`} label="批准一次" variant="primary" onPress={() => decide($, a.id, 'once')} />
                <Button key={`ap-${a.id}-always`} label="总是批准" onPress={() => decide($, a.id, 'always')} />
                <Button key={`ap-${a.id}-reject`} label="拒绝" onPress={() => decide($, a.id, 'reject')} />
              </Box>
            </Box>
          ))}
        </Box>
      )
  } else if (ui.section === 'alignment') {
    const pend = view.alignment.filter(x => isPendingEntry(x.status))
    body = (
      <Box flexDirection="column" gap={1}>
        <Markdown text={renderAlignment(view)} />
        {pend.map(x => (
          <Box key={'al-' + x.id}>
            <Text>{x.id}：</Text>
            <Button key={`al-${x.id}-ok`} label="确认" onPress={() => alignDecide($, x.id, 'confirm')} />
            <Button key={`al-${x.id}-no`} label="驳回" onPress={() => alignDecide($, x.id, 'reject')} />
          </Box>
        ))}
      </Box>
    )
  } else {
    const inv = ui.lastInvite
    body = (
      <Box flexDirection="column" gap={1}>
        <Markdown
          text={
            `**房间「${view.room.name}」** \`${view.room.id}\`\n\n` +
            `- 工作目录：${view.room.dir}\n- 主控：${view.room.host}${isHost ? '（本会话）' : ''}\n- 我是：${meId}（${view.me.kind}）\n- 信息层：${view.room.info_layer}\n- hub：${conn.hub}（版本 ${view.version}）`
          }
        />
        <Text bold>本机房间（一键加入，不用邀请码）</Text>
        {roomsList($, await cachedRooms($), view.room.id)}
        <Button key="rl-refresh" label="刷新房间列表" onPress={() => cachedRooms($, true).then(() => setNotice($, '房间列表已刷新'))} />
        <Text bold>邀请新成员</Text>
        <Select key="inv-vendor" label="provider" value={ui.invVendor} options={VENDORS} onSelect={(v: string) => setUi($, { invVendor: v })} />
        <Select key="inv-role" label="角色" value={ui.invRole} options={ROLES} onSelect={(v: string) => setUi($, { invRole: v })} />
        <Input
          key="inv-desc"
          label="职责描述"
          placeholder="负责什么、擅长什么"
          value={ui.invDesc}
          submitLabel="生成邀请码"
          onInput={(v: string) => setUi($, { invDesc: v })}
          onSubmit={() => makeInvite($)}
        />
        <Button key="inv-go" label="生成邀请码" variant="primary" onPress={() => makeInvite($)} />
        {inv ? (
          <Markdown
            text={`**邀请码 \`${inv.code}\`**（${inv.vendor}/${inv.role}，10 分钟内有效，只能用一次）\n\n在目标会话里运行：\n\n\`\`\`\n${inv.command}\n\`\`\``}
          />
        ) : null}
        <Text bold>添加成员（hub 起它的回合，不用邀请码）</Text>
        <Select key="add-vendor" label="provider" value={ui.addVendor} options={VENDORS} onSelect={(v: string) => setUi($, { addVendor: v })} />
        <Input
          key="add-model"
          label="模型"
          placeholder="可空"
          value={ui.addModel}
          submitLabel="添加成员"
          onInput={(v: string) => setUi($, { addModel: v })}
          onSubmit={() => addFromPane($)}
        />
        <Select key="add-role" label="角色" value={ui.addRole} options={ROLES} onSelect={(v: string) => setUi($, { addRole: v })} />
        <Input
          key="add-desc"
          label="职责描述"
          placeholder="负责什么、擅长什么"
          value={ui.addDesc}
          submitLabel="添加成员"
          onInput={(v: string) => setUi($, { addDesc: v })}
          onSubmit={() => addFromPane($)}
        />
        <Input
          key="add-name"
          label="名字"
          placeholder="可空"
          value={ui.addName}
          submitLabel="添加成员"
          onInput={(v: string) => setUi($, { addName: v })}
          onSubmit={() => addFromPane($)}
        />
        <Button key="add-go" label="添加成员" variant="primary" onPress={() => addFromPane($)} />
        <Button key="leave" label="离开房间" onPress={() => leaveFromPane($)} />
      </Box>
    )
  }

  return (
    <Box flexDirection="column" gap={1}>
      <Text bold>
        {view.room.name} · 我是 {meId}
        {isHost ? ' ★主控' : ''} · 版本 {view.version}
      </Text>
      {connLine}
      {tabs}
      {body}
      {notice}
    </Box>
  )
}

// ---- the band above the prompt -------------------------------------------

async function renderBand($: any, e: any, next: any) {
  if (e.props.hasSurvey) return next(e)
  const view = await read($, viewAtom)
  const conn = await read($, connAtom)
  if (conn.status === 'stale') {
    const { Box, Text, Button } = $.ui.resolve(e) as any
    return (
      <Box>
        <Text color="yellow">xmuse：绑定的是另一个会话 </Text>
        <Button key="open" label="打开" onPress={() => openPane($)} />
      </Box>
    )
  }
  if (!view) return next(e)
  const text = bannerText(view, view.me.id)
  if (!text) return next(e)
  const { Box, Text, Button } = $.ui.resolve(e) as any
  return (
    <Box>
      <Text dimColor>{text} </Text>
      <Button key="open" label="打开" onPress={() => openPane($)} />
    </Box>
  )
}

// ===== hooks =====

const SAY = 'mcp__xmuse__say'

async function registerTools($: any): Promise<void> {
  const b = await loadBinding($)
  if (!b) return
  await $.tool.register({
    name: 'say',
    description:
      'Send a message to another member of the xmuse room, or to a topic. Use it to answer messages that arrived from the xmuse plugin. to = member id (e.g. "coord") or a topic like "#d3". Keep text short.',
    inputSchema: {
      type: 'object',
      properties: {
        to: { type: 'string', description: 'member id or #topic' },
        text: { type: 'string', description: 'the message' },
        mentions: { type: 'array', items: { type: 'string' }, description: 'member ids to @-mention (optional)' },
      },
      required: ['to', 'text'],
    },
    isDeferred: false,
  })
}

async function sayTool($: any, e: any): Promise<{ result: string; isError?: true }> {
  const b = await loadBinding($)
  if (!b) return { result: 'xmuse: this session is not in a room', isError: true }
  const to = String(e.to || '')
  const text = String(e.text || '')
  if (!to || !text) return { result: 'xmuse say: "to" and "text" are required', isError: true }
  const mentions = Array.isArray(e.mentions) ? e.mentions.map(String) : undefined
  // member token only: an agent can talk, never approve or manage
  const r = await actCall($, b, { act: 'say', to, text, mentions }, 'member')
  if (!r.ok) return { result: 'xmuse say failed: ' + errText(r), isError: true }
  return { result: `sent (message ${r.body.id})` }
}

export const register: Register = (on, options) => {
  setOptions(options as any)

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'xmuse',
      description: 'xmuse room: room new | invite | join | join-local | rooms | add | group | wake-host | status | open | leave | rebind | hub',
      argumentHint: 'room new <name> | invite <provider> <role> <description> | join <code> | join-local <room> | status | open | leave',
    })
    await registerTools($)
    // long-poll loop; overlapping ticks are skipped inside pollOnce
    $.clock.every(1000, () => pollOnce($))
    return next(e)
  })

  on('command.run', { command: 'xmuse' }, async ($, e) => {
    const r = await runCommand($, e.args)
    // the tool appears the moment this session joins a room
    if (/^(room|join|join-local)$/i.test(e.args.trim().split(/\s+/)[0] || '')) {
      try {
        await registerTools($)
      } catch {
        // registration is retried at the next session.start
      }
    }
    return r
  })

  on('tool.call', { tool: SAY }, async ($, e) => {
    return sayTool($, e as any)
  }).catch(($, e, next) => (next.called ? next(e) : { deny: 'xmuse: the say tool failed (see /xmuse status)' }))

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    return renderPane($, e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    return renderBand($, e, next)
  })
}
