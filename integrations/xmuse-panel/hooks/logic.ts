// Pure logic for the xmuse panel: no $, no network, no state, so it can be unit-tested later.
// Hub view shape: hub/src/xmuse/room.py view(). Every field may be missing; callers get safe defaults.

export type Member = {
  id: string
  vendor?: string
  status?: string
  online?: boolean
  paused?: boolean
  unread?: number
  queued?: number
  description?: string
  progress?: Progress | null
  model?: string // what its next turn runs on (member_edit changes it)
  context_tokens?: number // the latest turn's context size (T8c H3)
  compacting?: boolean // a hub-run compaction is in flight
  compacted?: boolean // compacted since its last turn: context_tokens is 0 until the next turn
}
export type Progress = { turn?: number; started_at?: number; tools?: number | unknown[]; last_tool?: string; text?: string; updated_at?: number }
export type Approval = { id: string; kind?: string; member?: string; summary?: string; detail?: unknown; risk?: string; at?: number }
export type Thread = { id: string; kind?: string; title?: string; members?: string[]; private?: boolean; unread?: number }
export type Msg = {
  id: number
  thread?: string
  from?: string
  to?: string[]
  mentions?: string[]
  kind?: string
  text?: string
  at?: number
  reply_to?: number
  via?: string | null
  for_me?: boolean
  outcome?: string | null
}
export type Tab = { id: string; label: string; unread: number; peer?: string; group?: boolean }

// ---- paths ---------------------------------------------------------------------------------------------------

/** Windows or UNC path (as the Claude session sees it) to the POSIX form the hub registry uses. */
export function toPosix(p: string): string {
  let s = String(p || '').trim().replace(/\\/g, '/')
  const unc = s.match(/^\/\/(?:wsl\.localhost|wsl\$)\/[^/]+(\/.*)?$/i)
  if (unc) s = unc[1] ?? '/'
  else {
    const drive = s.match(/^([A-Za-z]):(\/.*)?$/)
    if (drive) s = `/mnt/${drive[1]!.toLowerCase()}${drive[2] ?? ''}`
  }
  if (s.length > 1) s = s.replace(/\/+$/, '')
  return s
}

export type HubEntry = { room_id?: string; name?: string; dir?: string; url?: string; host?: string; pid?: number; started_at?: number }

/** hubs.json text to entries; broken or missing content gives []. */
export function parseHubs(text: string): HubEntry[] {
  try {
    const data = JSON.parse(text)
    const list = Array.isArray(data?.hubs) ? data.hubs : []
    return list.filter((e: any) => e && typeof e === 'object' && typeof e.url === 'string')
  } catch {
    return []
  }
}

/**
 * Entries whose room dir is exactly the session's cwd, newest hub first. Not a parent's: a hub serves only its own
 * directory (join elsewhere is 400 wrong_dir), so a subfolder of a room's directory has no room of its own yet.
 */
export function matchHubs(entries: HubEntry[], cwd: string): HubEntry[] {
  const me = toPosix(cwd).toLowerCase()
  return entries.filter(e => !!e.dir && toPosix(e.dir).toLowerCase() === me)
    .sort((a, b) => (b.started_at ?? 0) - (a.started_at ?? 0))
}

export function isLoopbackUrl(url: string): boolean {
  return /^https?:\/\/(127\.\d+\.\d+\.\d+|localhost|\[::1\])(:\d+)?(\/|$)/i.test(String(url))
}

// ---- people --------------------------------------------------------------------------------------------------

const PALETTE = ['#5B8DEF', '#3FB68B', '#E0A030', '#C86DD7', '#E06C75', '#4FB3C8', '#9AB84A', '#D98B5F']
const FIXED: Record<string, string> = { claude: '#D97757', human: '#9A8CF0' }

export function hashStr(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0
  return h
}

export function colorOf(id: string): string {
  return FIXED[id] ?? PALETTE[hashStr(id) % PALETTE.length]!
}

/** a * (1 - t) + b * t, per channel; both '#RRGGBB'. */
export function mixHex(a: string, b: string, t: number): string {
  const pa = /^#([0-9a-f]{6})$/i.exec(a), pb = /^#([0-9a-f]{6})$/i.exec(b)
  if (!pa || !pb) return a
  const ch = (h: string, i: number) => parseInt(h.slice(i, i + 2), 16)
  const out = [0, 2, 4].map(i => Math.round(ch(pa[1]!, i) * (1 - t) + ch(pb[1]!, i) * t))
  return '#' + out.map(n => n.toString(16).padStart(2, '0')).join('')
}

// ---- vendors: logo avatars and name colours ------------------------------------------------------------------

export type VendorKey = 'claude' | 'opencode' | 'deepseek' | 'google' | ''

/** The vendor family of a member: from the vendor field, else guessed from the id (opencode-2 -> opencode). */
export function vendorKey(id: string, vendor?: string): VendorKey {
  const v = String(vendor ?? '').toLowerCase()
  const base = String(id ?? '').toLowerCase().replace(/-\d+$/, '')
  for (const s of [v, base]) {
    if (s.includes('claude')) return 'claude'
    if (s.includes('opencode')) return 'opencode'
    if (s === 'agy' || s.includes('antigravity') || s.includes('google') || s.includes('gemini')) return 'google'
    if (s === 'dsh' || s.includes('deepseek')) return 'deepseek'
  }
  return ''
}

// [dark theme, light theme]. opencode is teal on purpose: it must not look like Claude's orange.
const VENDOR_COLOR: Record<string, [string, string]> = {
  claude: ['#D97757', '#C4562F'],
  opencode: ['#2DB7A3', '#14806F'],
  deepseek: ['#5B7CFF', '#3350D0'],
  google: ['#E0559E', '#B93580'],
  human: ['#9A8CF0', '#6A4FD0'],
}

/** Colour of a member's name: by vendor, the user in purple, others from the hashed palette (darker in the light theme). */
export function memberColor(id: string, vendor: string | undefined, light: boolean): string {
  const k = id === 'human' ? 'human' : vendorKey(id, vendor)
  const pair = k ? VENDOR_COLOR[k] : undefined
  if (pair) return pair[light ? 1 : 0]
  const c = colorOf(id)
  return light ? mixHex(c, '#000000', 0.25) : c
}

/** Small number for a corner badge when several members share a vendor: opencode-2 -> '2', plain opencode -> '1'. */
export function badgeOf(id: string, vendor: string | undefined, all: { id: string; vendor?: string }[]): string {
  const k = vendorKey(id, vendor)
  if (!k) return ''
  const same = all.filter(m => vendorKey(m.id, m.vendor) === k)
  if (same.length < 2) return ''
  const m = /-(\d+)$/.exec(id)
  return m ? m[1]! : '1'
}

// ---- colour palettes (dark / light) for what must be a concrete colour -----------------------------------------

export type Pal = {
  bubble: string; bubbleBorder: string
  mine: string; mineBorder: string
  toClaude: string
  codeBg: string; hoverBg: string; banner: string
}

export const PAL_DARK: Pal = {
  bubble: '#2A2A2E', bubbleBorder: '#3A3A40',
  mine: '#4B3F8F', mineBorder: '#6A5CC0',
  toClaude: '#2E2723',
  codeBg: '#1A1A1D', hoverBg: '#1F1F23', banner: '#3A2F14',
}

export const PAL_LIGHT: Pal = {
  bubble: '#F1F1F4', bubbleBorder: '#D2D2DA',
  mine: '#E4DFFA', mineBorder: '#A99BEA',
  toClaude: '#FCEEE6',
  codeBg: '#E7E7EC', hoverBg: '#FFFFFF', banner: '#FFF1CF',
}

/** Translucent tints that read on both a dark and a light pane. The desktop app's own light/dark setting is not
 * visible to a mod (the /config theme row is the terminal's), so the panel no longer picks a palette by theme. */
export const PAL_TINT: Pal = {
  bubble: '#8C8C9614', bubbleBorder: '#8C8C9659',
  mine: '#7C6AE62E', mineBorder: '#7C6AE6A6',
  toClaude: '#E8875B24',
  codeBg: '#8C8C961F', hoverBg: '#8C8C9640', banner: '#F0B42938',
}

export function palOf(_light: boolean): Pal {
  return PAL_TINT
}

/** The `theme` row of /config: any value naming "light" is a light theme (auto and unknown count as dark). */
export function isLightTheme(value: unknown): boolean {
  return /light/i.test(String(value ?? ''))
}

// ---- logo avatars ---------------------------------------------------------------------------------------------

function esc(s: string): string {
  return s.replace(/[<>&"]/g, '')
}

/**
 * Avatar as SVG. Logos are simplified shapes drawn here (no official bitmaps): Claude an orange burst, OpenCode a black
 * terminal square, DeepSeek a blue whale; unknown vendors the initial on a coloured disc. `image` (a data: URI of a PNG)
 * replaces the logo; `badge` is a small number in the corner.
 */
export function avatarSvg(id: string, size: number, vendor?: string, badge = '', image = ''): string {
  const k = id === 'human' ? 'human' : vendorKey(id, vendor)
  let body: string
  if (image) {
    body = `<defs><clipPath id="c"><circle cx="16" cy="16" r="16"/></clipPath></defs>`
      + `<image href="${image}" x="0" y="0" width="32" height="32" preserveAspectRatio="xMidYMid slice" clip-path="url(#c)"/>`
  } else if (k === 'claude') {
    let rays = ''
    for (let i = 0; i < 12; i++) {
      const a = (i * Math.PI) / 6
      const r1 = 3, r2 = i % 2 ? 9 : 12.5
      rays += `<line x1="${(16 + Math.cos(a) * r1).toFixed(2)}" y1="${(16 + Math.sin(a) * r1).toFixed(2)}" x2="${(16 + Math.cos(a) * r2).toFixed(2)}" y2="${(16 + Math.sin(a) * r2).toFixed(2)}"/>`
    }
    body = `<circle cx="16" cy="16" r="16" fill="#D97757"/><g stroke="#FFF4EC" stroke-width="2.6" stroke-linecap="round">${rays}</g>`
  } else if (k === 'opencode') {
    body = `<rect x="1" y="1" width="30" height="30" rx="6" fill="#0E0E10" stroke="#8A8A92" stroke-width="1.5"/>`
      + `<polyline points="8,11 14,16 8,21" fill="none" stroke="#FFFFFF" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>`
      + `<line x1="17" y1="22" x2="24" y2="22" stroke="#9A9AA2" stroke-width="2.6" stroke-linecap="round"/>`
  } else if (k === 'deepseek') {
    body = `<circle cx="16" cy="16" r="16" fill="#4D6BFE"/>`
      + `<path d="M5 17 C5 11.5 10 9 15 10 C19 10.8 21 13 23 14.5 C24.5 12.5 26 11.5 27.5 11 C27.5 13.5 26.5 15.5 25 17 C26.5 18 27.5 20 27.5 22.5 C25.5 21.8 24 21 22.5 19.5 C20 23.5 14 24.5 9.5 22 C7 20.6 5.4 19 5 17 Z" fill="#FFFFFF"/>`
      + `<circle cx="10" cy="16.5" r="1.3" fill="#4D6BFE"/>`
      + `<path d="M13 9.5 C13 7.5 12 6.5 10.5 6 M13 9.5 C13.5 7.5 14.5 6.5 16 6.2" fill="none" stroke="#FFFFFF" stroke-width="1.6" stroke-linecap="round"/>`
  } else if (k === 'google') {
    body = '<circle cx="16" cy="16" r="16" fill="#E0559E"/>'
      + '<path d="M16 5 C17 11.5 20.5 15 27 16 C20.5 17 17 20.5 16 27 C15 20.5 11.5 17 5 16 C11.5 15 15 11.5 16 5 Z" fill="#FFFFFF"/>'
  } else {
    const letter = esc(initialOf(id))
    const fs = letter.length > 1 || letter === '你' ? 13 : 15
    body = `<circle cx="16" cy="16" r="16" fill="${k === 'human' ? '#7B6CE0' : colorOf(id)}"/>`
      + `<text x="16" y="21" font-size="${fs}" font-family="sans-serif" font-weight="600" fill="#fff" text-anchor="middle">${letter}</text>`
  }
  const bdg = badge
    ? `<circle cx="25.5" cy="25.5" r="6.5" fill="#1B1B1F" stroke="#FFFFFF" stroke-width="1.2"/>`
      + `<text x="25.5" y="28.6" font-size="9" font-family="sans-serif" font-weight="700" fill="#fff" text-anchor="middle">${esc(badge).slice(0, 2)}</text>`
    : ''
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 32 32">${body}${bdg}</svg>`
}

export function displayName(id: string | undefined): string {
  if (!id) return '?'
  if (id === 'human') return '你'
  if (id === 'hub') return 'hub'
  return id
}

export function initialOf(id: string | undefined): string {
  if (id === 'human') return '你'
  const c = (id ?? '?').trim().charAt(0)
  return c ? c.toUpperCase() : '?'
}

export function statusLine(m: Member): string {
  let s: string
  if (m.paused || m.status === 'paused') s = '⏸ 已暂停'
  else if (m.status === 'running') s = '● 执行中'
  else if (m.online === false || m.status === 'offline') s = '○ 离线'
  else s = '○ 空闲'
  const q = Number(m.queued ?? 0)
  return q > 0 ? `${s} · 排队 ${q}` : s
}

// ---- view ----------------------------------------------------------------------------------------------------

export function membersOf(view: any): Member[] {
  const list: Member[] = Array.isArray(view?.members) ? view.members.filter((m: any) => m && typeof m.id === 'string') : []
  // Only the panel's own member is hidden; a host that is someone else shows (the caller marks it with a star).
  const me = view?.me?.id
  return list.filter(m => m.id !== me)
}

export function threadsOf(view: any): Thread[] {
  return Array.isArray(view?.threads) ? view.threads.filter((t: any) => t && typeof t.id === 'string') : []
}

export function timelineOf(view: any): Msg[] {
  return Array.isArray(view?.timeline) ? view.timeline.filter((m: any) => m && typeof m.id === 'number') : []
}

function tabLabel(t: Thread, hostIds: string[]): string {
  const ms = (t.members ?? []).filter(x => x !== 'human' && !hostIds.includes(x))
  if (t.kind === 'dm') {
    if (ms.length === 1) return ms[0]!
    const other = (t.members ?? []).filter(x => x !== 'human')
    if (other.length === 1) return other[0]!
    return t.title || t.id
  }
  return t.title || t.id
}

/** "全部" first, then every thread except #room (which "全部" sends to). */
export function tabsOf(view: any): Tab[] {
  const hostIds = [view?.room?.host, view?.me?.id].filter((x): x is string => typeof x === 'string')
  const ths = threadsOf(view).filter(t => t.id !== '#room')
  const roomT = threadsOf(view).find(t => t.id === '#room')
  const allUnread = threadsOf(view).reduce((n, t) => n + Number(t.unread ?? 0), 0)
  void roomT
  const out: Tab[] = [{ id: 'all', label: '全部', unread: allUnread }]
  const dms = ths.filter(t => t.kind === 'dm')
  const groups = ths.filter(t => t.kind !== 'dm')
  for (const t of [...dms, ...groups]) {
    const tab: Tab = { id: t.id, label: (t.private && t.kind !== 'dm' ? '🔒' : '') + tabLabel(t, hostIds), unread: Number(t.unread ?? 0) }
    if (t.kind === 'dm') tab.peer = tabLabel(t, hostIds) // a private chat: the draw puts that member's colour dot before the label
    else tab.group = true
    out.push(tab)
  }
  return out
}

/** The private chat between the user and a member, as the hub names it (mail.dm_id): `dm:` + the two ids sorted. */
export function dmThreadId(member: string): string {
  return 'dm:' + ['human', member].sort().join('+')
}

/** One entry of the left rail: the room, a member (its private chat with the user), or everything. */
export type RailItem = { id: string; kind: 'room' | 'dm' | 'all'; label: string; unread: number; peer?: string }

/**
 * The left rail, IM style: the room (#room) first, then one entry per member (the user's private chat with it, which
 * the hub creates on the first message), then "全部" (every thread the user can see, the other members' DMs included).
 * Unread counts come from the view's threads; a chat that does not exist yet has none.
 */
export function railOf(view: any): RailItem[] {
  const ths = threadsOf(view)
  const unread = (id: string) => Number(ths.find(t => t.id === id)?.unread ?? 0)
  const out: RailItem[] = [{ id: '#room', kind: 'room', label: String(view?.room?.name ?? '') || '大群', unread: unread('#room') }]
  for (const m of membersOf(view)) {
    const id = dmThreadId(m.id)
    out.push({ id, kind: 'dm', label: m.id, unread: unread(id), peer: m.id })
  }
  // threads that are neither the room nor one of the user's chats (members' DMs, groups): only counted under 全部
  const mine = new Set(out.map(x => x.id))
  const rest = ths.filter(t => !mine.has(t.id)).reduce((n, t) => n + Number(t.unread ?? 0), 0)
  out.push({ id: 'all', kind: 'all', label: '全部', unread: rest })
  return out
}

/** The stored tab if the rail still has it, else '#room' (a tab from the former tab bar, e.g. a `#plan` group, is not on the rail). */
export function activeTabOf(view: any, tab: string): string {
  return railOf(view).some(t => t.id === tab) ? tab : '#room'
}

/** The room's avatar: a disc with three heads, the group's mark in the rail and the room header. */
export function roomSvg(size: number): string {
  const head = (x: number, y: number, r: number) => `<circle cx="${x}" cy="${y}" r="${r}" fill="#FFFFFF"/>`
  const body = (x: number, y: number, w: number) =>
    `<path d="M${x - w} ${y + 6} C${x - w} ${y} ${x + w} ${y} ${x + w} ${y + 6} Z" fill="#FFFFFF"/>`
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 32 32">`
    + `<circle cx="16" cy="16" r="16" fill="#3D8B6E"/>`
    + `<g opacity="0.75">${head(9.5, 13, 3)}${body(9.5, 18, 4.5)}${head(22.5, 13, 3)}${body(22.5, 18, 4.5)}</g>`
    + `${head(16, 11.5, 3.6)}${body(16, 17, 5.6)}</svg>`
}

/** Thread id to use for `say` and `read` on a tab. */
export function threadForTab(tab: string): string {
  return tab === 'all' ? '#room' : tab
}

/** Thread ids whose read cursor should move when the tab is shown. */
export function unreadThreadsFor(view: any, tab: string): string[] {
  const ths = threadsOf(view)
  if (tab === 'all') return ths.filter(t => Number(t.unread ?? 0) > 0).map(t => t.id)
  const t = ths.find(x => x.id === tab)
  return t && Number(t.unread ?? 0) > 0 ? [t.id] : []
}

export function messagesFor(view: any, tab: string, limit = 50): Msg[] {
  const all = timelineOf(view)
  const shown = tab === 'all' ? all : all.filter(m => m.thread === tab)
  return shown.slice(-limit)
}

export function toLabel(m: Msg): string {
  const ments = Array.isArray(m.mentions) ? m.mentions : []
  const to = Array.isArray(m.to) ? m.to : []
  const th = m.thread ?? ''
  // in the room everyone reads it: @ only says whom it wakes, so it must not read as a private message
  if ((th === '#room' || th === '') && ments.length) return `全员 · @${ments.map(displayName).join(' @')}`
  let who: string[]
  if (ments.length) who = ments
  else if (th.startsWith('dm:')) who = to
  else if (th === '#room' || th === '') who = []
  else who = [th]
  return who.length ? who.map(displayName).join('、') : '全员'
}

export function fmtClock(at: number | undefined): string {
  if (typeof at !== 'number' || !isFinite(at)) return ''
  const d = new Date(at * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

/** "xmuse · opencode 执行中 · 1 条待审批 · 2 条给你"; with nothing going on: "xmuse · 3 助手 · 0 未读". */
export function summaryLine(view: any, forMe = 0, auto = true): string {
  // Most urgent first: approvals, messages waiting for Claude, paused, running, unread (the line has no colour).
  const ms = membersOf(view)
  const unread = threadsOf(view).reduce((s, t) => s + Number(t.unread ?? 0), 0)
  const running = ms.filter(m => m.status === 'running' || m.progress).map(m => m.id)
  const paused = ms.filter(m => m.paused || m.status === 'paused').map(m => m.id)
  const appr = approvalsOf(view).length
  const parts: string[] = []
  if (appr) parts.push(`⚠ ${appr} 条待审批`)
  if (forMe) parts.push(auto ? `${forMe} 条给你` : `⚠ ${forMe} 条消息等 Claude 处理`)
  if (paused.length) parts.push(`${paused.join('、')} 已暂停`)
  if (running.length) parts.push(`${running.join('、')} 执行中`)
  if (unread) parts.push(`${unread} 未读`)
  if (!parts.length) parts.push(`${ms.length} 助手`, '空闲')
  return ['xmuse', ...parts].join(' · ')
}

export function approvalsOf(view: any): Approval[] {
  return Array.isArray(view?.approvals) ? view.approvals.filter((a: any) => a && typeof a.id === 'string') : []
}

/** What the card shows for an approval: the summary (or detail text), cut to 200 chars. */
export function approvalText(a: Approval): string {
  let t = typeof a.summary === 'string' && a.summary ? a.summary : typeof a.detail === 'string' ? a.detail : ''
  if (!t && a.detail && typeof a.detail === 'object') { try { t = JSON.stringify(a.detail) } catch { t = '' } }
  return t.length > 200 ? t.slice(0, 200) + '…' : t
}

/** Alignment proposals and resume requests have one yes; shell and share requests have once / always / reject. */
export function approvalHasAlways(a: Approval): boolean {
  return a.kind !== 'alignment' && a.kind !== 'resume'
}

// ---- working strip -------------------------------------------------------------------------------------------

export function workingMembers(view: any): Member[] {
  return membersOf(view).filter(m => m.progress && typeof m.progress === 'object')
}

/** "1:12" or "1:02:03"; startedAt in epoch seconds (milliseconds also accepted), nowMs in milliseconds. */
export function fmtElapsed(startedAt: number | undefined, nowMs: number): string {
  if (typeof startedAt !== 'number' || !isFinite(startedAt) || !nowMs) return '0:00'
  const startMs = startedAt > 1e11 ? startedAt : startedAt * 1000
  const sec = Math.max(0, Math.floor((nowMs - startMs) / 1000))
  const p = (n: number) => String(n).padStart(2, '0')
  const h = Math.floor(sec / 3600)
  const m = Math.floor((sec % 3600) / 60)
  return h > 0 ? `${h}:${p(m)}:${p(sec % 60)}` : `${m}:${p(sec % 60)}`
}

export function toolCount(p: Progress | null | undefined): number {
  if (!p) return 0
  return Array.isArray(p.tools) ? p.tools.length : Number(p.tools ?? 0) || 0
}

/** "● opencode 执行中 1:12 · 9 个工具 · 排队 2" */
export function workingLine(m: Member, nowMs: number): string {
  const p = m.progress
  const parts = [`● ${m.id} 执行中 ${fmtElapsed(p?.started_at, nowMs)}`, `${toolCount(p)} 个工具`]
  const lt = typeof p?.last_tool === 'string' ? p.last_tool.trim() : ''
  if (lt) parts.push(`最近: ${lt.length > 40 ? lt.slice(0, 40) + '…' : lt}`)
  const q = Number(m.queued ?? 0)
  if (q > 0) parts.push(`排队 ${q}`)
  return parts.join(' · ')
}

/** "49 秒" or "1 分 49 秒" or "1 小时 2 分". */
export function fmtDuration(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  if (s < 60) return `${s} 秒`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} 分 ${s % 60} 秒`
  return `${Math.floor(m / 60)} 小时 ${m % 60} 分`
}

export function startedMsOf(startedAt: number | undefined): number {
  if (typeof startedAt !== 'number' || !isFinite(startedAt) || startedAt <= 0) return 0
  return startedAt > 1e11 ? startedAt : startedAt * 1000
}

/** Members that were running in the old view and are present but idle in the new one (last seen tools and start). */
export function finishedMembers(oldView: any, newView: any): { id: string; tools: number; startedMs: number }[] {
  if (!oldView) return []
  const now = membersOf(newView)
  const out: { id: string; tools: number; startedMs: number }[] = []
  for (const m of workingMembers(oldView)) {
    const cur = now.find(x => x.id === m.id)
    if (cur && !(cur.progress && typeof cur.progress === 'object')) {
      out.push({ id: m.id, tools: toolCount(m.progress), startedMs: startedMsOf(m.progress?.started_at) })
    }
  }
  return out
}

/** "✓ opencode 已完成 · 3 个工具 · 1 分 49 秒" */
export function doneLine(id: string, tools: number, startedMs: number, endedMs: number): string {
  const parts = [`✓ ${id} 已完成`, `${tools} 个工具`]
  if (startedMs > 0 && endedMs > startedMs) parts.push(fmtDuration((endedMs - startedMs) / 1000))
  return parts.join(' · ')
}

export function textsOf(view: any): Record<string, string> {
  const out: Record<string, string> = {}
  for (const m of workingMembers(view)) out[m.id] = String(m.progress?.text ?? '')
  return out
}

/** The last running member whose partial output differs from `prev`. */
export function changedWorker(prev: Record<string, string>, view: any): { id: string; text: string; old: string } | null {
  let hit: { id: string; text: string; old: string } | null = null
  for (const m of workingMembers(view)) {
    const text = String(m.progress?.text ?? '')
    const old = prev[m.id] ?? ''
    if (text !== old) hit = { id: m.id, text, old }
  }
  return hit
}

/** Shown lengths of the typing effect, from `from` (exclusive) to `to` (inclusive), in n steps. */
export function typingSteps(from: number, to: number, n = 4): number[] {
  const out: number[] = []
  for (let i = 1; i <= n; i++) out.push(Math.min(to, from + Math.ceil(((to - from) * i) / n)))
  out[out.length - 1] = to
  return out
}

/** What of a member's partial output to draw: the typed prefix while the typing effect runs for that member. */
export function typedText(full: string, typed: { id: string; full: string; shown: number } | undefined, id: string): string {
  if (typed && typed.id === id && typed.full === full && typed.shown < full.length) return full.slice(0, Math.max(0, typed.shown))
  return full
}

/**
 * The message a fresh view brought that the feed reveals as if typed: the newest one past `sinceId` that a member
 * (not the user) wrote as plain chat text. null when there is none.
 */
export function freshMessage(view: any, sinceId: number): Msg | null {
  const tl: Msg[] = Array.isArray(view?.timeline) ? view.timeline : []
  let hit: Msg | null = null
  for (const m of tl) {
    if (typeof m?.id !== 'number' || m.id <= sinceId || m.from === 'human') continue
    if (m.kind === 'system' || m.kind === 'done' || (m as any).retracted || !String(m.text ?? '').trim()) continue
    if (!hit || m.id > hit.id) hit = m
  }
  return hit
}

/** Shown lengths for revealing a message of `len` characters: about 40 characters a step, 3 to 10 steps. */
export function revealSteps(len: number): number[] {
  return len > 0 ? typingSteps(0, len, Math.min(10, Math.max(3, Math.ceil(len / 40)))) : []
}

/** The tail of a live draft: its last `max` characters, cut at a line start when one is near, "…" before a cut. */
export function draftTail(text: string, max = 280): string {
  const t = String(text ?? '').trim()
  if (t.length <= max) return t
  let s = t.slice(-max)
  const nl = s.indexOf('\n')
  if (nl >= 0 && nl < 80) s = s.slice(nl + 1)
  return '…' + s
}

/**
 * The view without the live parts: a shallow copy whose members' `progress` keeps only `started_at`. A view that
 * differs from the last one only in progress text / tool / tool counts is the same structure: it does not redraw the panel.
 */
export function structOf(view: any): any {
  if (!view || typeof view !== 'object') return view
  if (!Array.isArray(view.members)) return { ...view }
  return {
    ...view,
    members: view.members.map((m: any) => (m && typeof m === 'object' && 'progress' in m
      ? { ...m, progress: m.progress && typeof m.progress === 'object' ? { started_at: m.progress.started_at, has_text: String(m.progress.text ?? '').trim() !== '' } : m.progress }
      : m)),
  }
}

/** Last n non-empty lines of the member's partial output ('' when there is none). */
export function lastLines(text: string | undefined, n = 2): string {
  const ls = String(text ?? '').split('\n').map(x => x.trimEnd()).filter(x => x.trim())
  return ls.slice(-n).map(x => (x.length > 160 ? x.slice(0, 160) + '…' : x)).join('\n')
}

// ---- messages ------------------------------------------------------------------------------------------------

/** "↩ #12 first 30 chars" when the replied-to message is on the timeline, else "↩ #12". */
export function replyLabel(view: any, id: number): string {
  const orig = timelineOf(view).find(m => m.id === id)
  const t = orig ? String(orig.text ?? '').replace(/\s+/g, ' ').trim() : ''
  return t ? `↩ #${id} ${t.length > 30 ? t.slice(0, 30) + '…' : t}` : `↩ #${id}`
}

/** A reply the hub forwarded by itself: `via` is set and is not a human relay (cli / sidebar / coordinator). */
export function isAutoForward(m: Msg): boolean {
  const v = m.via
  if (!v || typeof v !== 'string') return false
  return v !== 'cli' && v !== 'coordinator' && !v.endsWith(' sidebar')
}

// ---- waking Claude -------------------------------------------------------------------------------------------

function isForPanel(m: Msg, me: string): boolean {
  if (m.for_me === true) return true
  if (Array.isArray(m.mentions) && m.mentions.includes(me)) return true
  const th = m.thread ?? ''
  return th.startsWith('dm:') && th.slice(3).split('+').includes(me)
}

/** Messages to the panel's own member from someone who is not the user (the user's go through the prompt box). */
export function wakeCandidates(view: any, afterId = 0): Msg[] {
  const me = view?.me?.id
  if (typeof me !== 'string' || !me) return []
  return timelineOf(view).filter(m =>
    m.id > afterId && m.kind !== 'system' && m.from !== me && m.from !== 'human' && m.from !== 'hub' && isForPanel(m, me))
}

export function maxWakeId(view: any): number {
  return wakeCandidates(view, 0).reduce((n, m) => Math.max(n, m.id), 0)
}

export function buildWakePrompt(msgs: Msg[]): string {
  if (msgs.length === 1) {
    const m = msgs[0]!
    return `[xmuse] ${m.from ?? '?'} 在 ${m.thread ?? '#room'} 给你发了消息 #${m.id}：${String(m.text ?? '').slice(0, 500)}。用 xmuse_send 工具回复（reply_to=${m.id}）。`
  }
  const lines = msgs.slice(0, 8).map(m => `- ${m.from ?? '?'} 在 ${m.thread ?? '#room'}，消息 #${m.id}：${String(m.text ?? '').slice(0, 300)}`)
  const more = msgs.length > 8 ? `\n（另有 ${msgs.length - 8} 条更早的没列出）` : ''
  return `[xmuse] 有 ${msgs.length} 条消息给你：\n${lines.join('\n')}${more}\n用 xmuse_send 工具逐条回复（reply_to 填对应消息 id）。`
}

// ---- sending -------------------------------------------------------------------------------------------------

/** @names in the text that are real member ids (host included: the user may @claude). Order kept, no repeats. */
export function parseMentions(text: string, view: any): string[] {
  const ids: string[] = Array.isArray(view?.members) ? view.members.map((m: any) => String(m.id)) : []
  const found: string[] = []
  const re = /@([A-Za-z0-9][A-Za-z0-9-]*)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const name = m[1]!
    const hit = ids.find(i => i.toLowerCase() === name.toLowerCase())
    if (hit && !found.includes(hit)) found.push(hit)
  }
  return found
}

export type SayBody = { act: 'say'; to: string; text: string; mentions: string[]; reply_to?: number }

/** The Input is one line: a literal backslash-n in the text becomes a real line break. */
export function expandNewlines(text: string): string {
  return text.replace(/\\n/g, '\n')
}

/**
 * The big-input button moves the panel's draft into Claude's own (multi-line) prompt box as `/x <draft>`. Allowed when that
 * box is empty or already a /x line (it is replaced); any other text there is never overwritten.
 */
export function bigInputPlan(draft: string, promptText: string): { ok: true; text: string } | { ok: false } {
  const p = promptText.trim()
  if (p && !(p === '/x' || p.startsWith('/x ') || p.startsWith('/x\n'))) return { ok: false }
  return { ok: true, text: '/x ' + draft }
}

export function buildSay(text: string, tab: string, replyTo: number, view: any): SayBody | null {
  const t = text.trim()
  if (!t) return null
  const to = threadForTab(tab)
  let mentions = parseMentions(t, view)
  // a private chat has two members: an @ of anyone else is just text there (the hub refuses mentions outside a thread)
  if (to.startsWith('dm:')) mentions = mentions.filter(m => to.slice(3).split('+').includes(m))
  const body: SayBody = { act: 'say', to, text: t, mentions }
  if (replyTo > 0) body.reply_to = replyTo
  return body
}

// ---- the model's xmuse_send tool (register.tsx sendTool): args building and result mapping, pure for tests ----

/** Fields sendTool forwards to hub /v1/tools/xmuse_send besides to/body/mentions/reply_to (hub validates them). */
const SEND_EXTRA = ['kind', 'scope', 'supersedes', 'resolves', 'depends_on', 'notify', 'members', 'why'] as const

/** Validate a tool call and build the hub args. kind defaults to 'message'; extra fields pass through untouched. */
export function sendPayload(e: any, view: any): { deny: string } | { args: Record<string, unknown> } {
  const to = typeof e?.to === 'string' ? e.to.trim() : ''
  const text = typeof e?.body === 'string' ? e.body.trim() : ''
  if (!to) return { deny: '缺少 to（#room、群 id 或成员 id）' }
  if (!text) return { deny: '缺少 body' }
  const mentions: string[] = Array.isArray(e?.mentions)
    ? e.mentions.filter((x: unknown) => typeof x === 'string')
    : parseMentions(text, view)
  const args: Record<string, unknown> = {
    to, body: text, mentions,
    kind: typeof e?.kind === 'string' && e.kind ? e.kind : 'message',
  }
  if (typeof e?.reply_to === 'number' && e.reply_to > 0) args.reply_to = e.reply_to
  for (const k of SEND_EXTRA.slice(1)) if (e?.[k] !== undefined) args[k] = e[k]
  return { args }
}

/** Map the hub's answer to the tool result: a tool error (or non-200) is a deny, never "sent". */
export function sendOutcome(r: { status: number; data: any }, to: string): { result: string } | { deny: string } {
  const brief = r.data ? JSON.stringify(r.data).slice(0, 300) : ''
  const err = r.data?.error
  if (r.status !== 200 || err) {
    const why = typeof err === 'object' && err
      ? `${err.code ?? ''} ${err.message ?? ''}`.trim()
      : String(r.data?.message ?? err ?? brief)
    return { deny: `发送失败 ${r.status}: ${why.slice(0, 200)}` }
  }
  return { result: `已发送到 ${to}${brief ? `：${brief}` : ''}` }
}

// ---- display -------------------------------------------------------------------------------------------------

/**
 * The Markdown renderer treats a single newline as a space. Outside ``` / ~~~ fences, a non-blank line followed
 * directly by a non-blank line gets two trailing spaces (a hard break). Blank lines, fence lines and everything
 * inside a fence stay as they are; list, table, heading and quote lines are not harmed by trailing spaces.
 */
export function hardBreaks(text: string): string {
  const lines = String(text ?? '').replace(/\r\n?/g, '\n').split('\n')
  let fence = ''
  const out: string[] = []
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!
    const m = line.match(/^\s{0,3}(`{3,}|~{3,})/)
    if (fence) {
      if (m && m[1]![0] === fence[0] && m[1]!.length >= fence.length && !line.replace(m[0], '').trim()) fence = ''
      out.push(line)
      continue
    }
    if (m) { fence = m[1]!; out.push(line); continue }
    const next = lines[i + 1]
    const brk = line.trim() !== '' && next !== undefined && next.trim() !== '' && !/ {2}$/.test(line)
    out.push(brk ? line + '  ' : line)
  }
  return out.join('\n')
}

const URL_RE = /^(https?:\/\/[^\s<>()]+?)([.,;:!?)\]，。；：！？）」』]*)$/
const ZWSP = '​'

/** The label a long bare URL is drawn with: host, the last path part, '…' between (the link keeps the full target). */
export function urlLabel(url: string, max = 28): string {
  const m = /^https?:\/\/([^/?#]+)(.*)$/.exec(url)
  if (!m) return clip(url, max)
  const host = m[1]!, rest = m[2]!
  if ((host + rest).length <= max) return host + rest
  const last = rest.split(/[/?#]/).filter(Boolean).pop() ?? ''
  return clip(`${host}/…/${last}`, max)
}

/**
 * Text the pane can wrap at any width. The desktop draws Markdown with the browser's line breaking, which never breaks
 * inside a long run of letters (a path, a hash, a URL): the bubble then grows past the pane. Outside ``` / ~~~ fences
 * and inline code, a bare URL longer than 40 characters becomes a link with a short label, and any other run of 28 or
 * more non-space characters gets a zero-width break every 16. Copy uses the original text. `links` false (plain Text,
 * not Markdown): URLs get breaks like any other run.
 */
export function softWrap(text: string, links = true): string {
  const lines = String(text ?? '').split('\n')
  let fence = ''
  return lines.map(line => {
    const m = line.match(/^\s{0,3}(`{3,}|~{3,})/)
    if (fence) { if (m && m[1]![0] === fence[0] && m[1]!.length >= fence.length) fence = ''; return line }
    if (m) { fence = m[1]!; return line }
    if (!/\S{28,}/.test(line)) return line
    return line.split(/(\s+)/).map(tok => {
      if (tok.length < 28 || /\s/.test(tok) || tok.includes('`') || tok.includes('](') || tok.startsWith('<')) return tok
      const u = links ? URL_RE.exec(tok) : null
      if (u) return u[1]!.length > 40 ? `[${urlLabel(u[1]!)}](${u[1]})${u[2]}` : tok
      return tok.replace(/[^\s　-鿿＀-￯]{16}(?=[^\s　-鿿＀-￯])/g, s => s + ZWSP)
    }).join('')
  }).join('\n')
}

/** At most `n` characters, '…' as the last one when cut (for labels the layout cannot truncate: a tab, a button). */
export function clip(s: string, n: number): string {
  const t = String(s ?? '')
  return t.length > n ? t.slice(0, Math.max(1, n - 1)) + '…' : t
}

// ---- retry ---------------------------------------------------------------------------------------------------

/** 2s, 4s, 8s ... capped at 30s. `fails` is the number of consecutive failures so far (>= 1). */
export function backoffMs(fails: number): number {
  return Math.min(30000, 2000 * 2 ** Math.max(0, fails - 1))
}

// ---- status, notices, done lines, approvals (polish batch 1) -------------------------------------------------

// Text and border colours are theme keys, so they follow the light / dark theme by themselves.
export const C_BLUE = 'suggestion'
export const C_AMBER = 'warning'
export const C_RED = 'error'
export const C_GREEN = 'success'
export const C_ORANGE = 'claude'

/** Dot colour and label of a member's state (A1, A2). Waiting for approval wins, then paused, running, offline, idle. */
export function statusOf(m: Member, waiting = false): { dot: string; label: string; color: string } {
  if (waiting) return { dot: '⚠', label: '等审批', color: C_AMBER }
  if (m.paused || m.status === 'paused') return { dot: '⏸', label: '已暂停', color: C_AMBER }
  if (m.status === 'running' || (m.progress && typeof m.progress === 'object')) return { dot: '●', label: '执行中', color: C_BLUE }
  if (m.online === false || m.status === 'offline') return { dot: '●', label: '离线', color: 'subtle' }
  return { dot: '●', label: '空闲', color: 'inactive' }
}

// ---- starting a hub inside WSL ---------------------------------------------------------------------------------

/** A POSIX shell single-quoted word. */
export function shq(s: string): string {
  return `'${String(s).replace(/'/g, `'\\''`)}'`
}

/**
 * The bash script (fed to `wsl.exe ... bash -l -s` on stdin) that starts the hub for `dir`. A process left behind by
 * a wsl.exe call dies when that call returns, so with a systemd user manager the hub runs as a transient unit
 * (`hub run` itself, as `hub start` would launch it: XMUSE_STATE set, output appended to the state's logs/hub.log;
 * --collect unloads it when the hub exits); without one it falls back to setsid. `path`: the PATH a hub last ran with
 * (install.json), since a login shell may lack the agent CLIs. `init`: also make the workspace (`xmuse init`).
 * WSL_INTEROP points at init's socket, which outlives this call (Windows exes such as agy need it).
 */
export function hubStartScript(o: { python: string; dir: string; path?: string; init: boolean }): string {
  const unit = 'xmuse-hub-' + Array.from(o.dir).reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7).toString(16)
  return [
    'set -e',
    `PY=${shq(o.python)}`,
    `D=${shq(o.dir)}`,
    'cd "$D"',
    // no recorded PATH (a hub older than the record): the usual per-user CLI dirs a login shell skips
    o.path ? `export PATH=${shq(o.path)}`
      : 'for p in "$HOME/.opencode/bin" "$HOME/.local/bin"; do [ -d "$p" ] && PATH="$p:$PATH"; done; export PATH',
    o.init ? '"$PY" -m xmuse init "$D" >/dev/null' : '',
    'I=/run/WSL/1_interop; [ -S "$I" ] || I=$(ls -t /run/WSL/*_interop 2>/dev/null | head -1)',
    'if command -v systemd-run >/dev/null && systemctl --user show-environment >/dev/null 2>&1; then',
    // the unit runs `hub run` itself, so it lives exactly as long as the hub; a unit of the same name still loaded
    // is a hub that does not answer (the panel found none alive): it is stopped first
    '  ST=$("$PY" -c \'import sys; from pathlib import Path; from xmuse import config; print(config.find_state(Path(sys.argv[1])))\' "$D")',
    '  mkdir -p "$ST/logs"',
    // a stopped transient unit can stay loaded under its name: each start takes a fresh one (dir hash + time)
    `  systemctl --user stop '${unit}*' 2>/dev/null || true`,
    `  systemctl --user reset-failed '${unit}*' 2>/dev/null || true`,
    `  U=${unit}-$(date +%s)`,
    '  systemd-run --user --unit="$U" --collect --working-directory="$D" --setenv=XMUSE_STATE="$ST" \\',
    '    --setenv=PATH="$PATH" --setenv=HOME="$HOME" ${I:+--setenv=WSL_INTEROP=$I} \\',
    '    ${WSL_DISTRO_NAME:+--setenv=WSL_DISTRO_NAME=$WSL_DISTRO_NAME} \\',
    '    /bin/sh -c \'exec "$0" -m xmuse hub run >> "$1/logs/hub.log" 2>&1\' "$PY" "$ST" >/dev/null',
    '  echo "started unit $U"',
    'else',
    '  setsid nohup "$PY" -m xmuse --ws "$D" hub start </dev/null >/dev/null 2>&1 &',
    '  echo started',
    'fi',
  ].filter(Boolean).join('\n') + '\n'
}

// ---- context size and compaction (T8c H3) ----------------------------------------------------------------------

export const AUTO_COMPACT_TOKENS = 500_000 // the hub's auto_compact_tokens default

/** "312k" for a member's latest context size; '' when the hub has none (no turn yet, or a vendor that reports none). */
export function ctxText(tokens: unknown): string {
  const t = Number(tokens)
  if (!isFinite(t) || t <= 0) return ''
  return t >= 1_000_000 ? `${(t / 1_000_000).toFixed(1)}M` : `${Math.max(1, Math.round(t / 1000))}k`
}

/** 0 normal, 1 past 80% of the auto-compact mark, 2 past it. */
export function ctxLevel(tokens: unknown, mark = AUTO_COMPACT_TOKENS): number {
  const t = Number(tokens)
  if (!isFinite(t) || t <= 0) return 0
  return t >= mark ? 2 : t >= mark * 0.8 ? 1 : 0
}

/** A model name short enough for a member card: the part after the provider, at most 24 characters. */
export function shortModel(model: unknown): string {
  const s = String(model ?? '').trim()
  const tail = s.includes('/') ? s.slice(s.lastIndexOf('/') + 1) : s
  return tail.length > 24 ? tail.slice(0, 23) + '…' : tail
}

/** Whether the panel offers "压缩" for this member: opencode via the hub, or this session's own Claude via the engine. */
export function canCompact(m: Member, meId: string): boolean {
  return (!!meId && m.id === meId) || vendorKey(String(m.id), String(m.vendor ?? '')) === 'opencode'
}

/**
 * What Claude's summarizer is told: the person's own /compact text first (it wins where they differ), then the hub's
 * instruction (task, handoffs, alignment points). Either may be empty.
 */
export function mergeCompactInstructions(user: string | undefined, hub: string | undefined): string {
  const u = String(user ?? '').trim()
  const x = String(hub ?? '').trim()
  if (!x) return u
  if (!u) return x
  return `${u}\n\n（以下是 xmuse 协作室的压缩要求；和上面冲突时以上面为准）\n${x}`
}

/** 0 normal, 1 over 5 minutes, 2 over 15 minutes (E3). */
export function elapsedLevel(startedAt: number | undefined, nowMs: number): number {
  const s = startedMsOf(startedAt)
  if (!s || !nowMs) return 0
  const sec = (nowMs - s) / 1000
  return sec > 900 ? 2 : sec > 300 ? 1 : 0
}

/** The trailing "@word" of the draft (what is after the last @ when that word starts with @), or null. */
export function trailingMention(draft: string): string | null {
  const m = /(?:^|\s)@([A-Za-z0-9-]*)$/.exec(draft)
  return m ? m[1]! : null
}

/** Members whose id starts with the typed prefix, at most n; the user's own member is not offered. */
export function mentionCandidates(view: any, q: string, n = 6): Member[] {
  const me = view?.me?.id
  const list: Member[] = Array.isArray(view?.members) ? view.members.filter((m: any) => m && typeof m.id === 'string' && m.id !== me) : []
  const lq = q.toLowerCase()
  return list.filter(m => m.id.toLowerCase().startsWith(lq)).slice(0, n)
}

/** The draft with its trailing @word replaced by "@id ". */
export function completeMention(draft: string, id: string): string {
  return draft.replace(/@[A-Za-z0-9-]*$/, `@${id} `)
}

/** Long text folded to its first lines: null when it is short. Never cuts inside a ``` fence (a closing fence is added). */
export function foldLong(text: string, maxLines = 14, maxChars = 900, keep = 8): { text: string; hidden: number } | null {
  const lines = String(text ?? '').split('\n')
  if (lines.length <= maxLines && text.length <= maxChars) return null
  let cut = Math.min(keep, lines.length)
  while (cut > 1 && lines.slice(0, cut).join('\n').length > maxChars) cut--
  const head = lines.slice(0, cut)
  let open = false
  for (const l of head) if (/^\s{0,3}(```|~~~)/.test(l)) open = !open
  if (open) head.push('```')
  return { text: head.join('\n'), hidden: lines.length - cut }
}

export type Block = { kind: 'md' | 'diff'; text: string }

/** Splits text at ```diff fences: diff blocks are drawn with Code, the rest with Markdown. */
export function splitBlocks(text: string): Block[] {
  const out: Block[] = []
  const lines = String(text ?? '').split('\n')
  let cur: string[] = []
  let diff: string[] | null = null
  const pushMd = () => { if (cur.join('\n').trim()) out.push({ kind: 'md', text: cur.join('\n') }); cur = [] }
  for (const l of lines) {
    if (diff === null) {
      if (/^\s{0,3}```diff\s*$/.test(l)) { pushMd(); diff = []; continue }
      cur.push(l)
    } else if (/^\s{0,3}```\s*$/.test(l)) {
      if (diff.length) out.push({ kind: 'diff', text: diff.join('\n') })
      diff = null
    } else diff.push(l)
  }
  if (diff !== null) cur.push('```diff', ...diff) // unterminated: leave it as plain text
  pushMd()
  return out.length ? out : [{ kind: 'md', text: String(text ?? '') }]
}

/** Day heading for the divider between days: 今天 / 昨天 / "10-11 周日". */
export function dayLabel(at: number | undefined, nowMs: number): string {
  if (typeof at !== 'number' || !isFinite(at)) return ''
  const d = new Date(at * 1000)
  const n = new Date(nowMs)
  const key = (x: Date) => x.getFullYear() * 400 + x.getMonth() * 32 + x.getDate()
  const y = new Date(nowMs - 86400000)
  if (key(d) === key(n)) return '今天'
  if (key(d) === key(y)) return '昨天'
  const p = (v: number) => String(v).padStart(2, '0')
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} 周${'日一二三四五六'[d.getDay()]}`
}

export type NoticeInfo = { kind: 'noise' | 'warn' | 'error'; text: string; raw: string; cmds?: string[] }

/** The quoted strings of a Python/JSON list literal as the hub prints a shell request: ['a', "b"] -> [a, b]. */
export function parseCmdList(s: string): string[] {
  const out: string[] = []
  const re = /'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)"/g
  let m: RegExpExecArray | null
  while ((m = re.exec(s))) out.push((m[1] ?? m[2] ?? '').replace(/\\(["'\\])/g, '$1').replace(/\\n/g, '\n'))
  return out
}

const DECISION_ZH: Record<string, string> = { once: '已批准一次', always: '已总是批准', reject: '已拒绝', expired: '已过期' }

/** A hub system notice (first line) as short Chinese. Warnings and errors are kept apart; unknown text stays as it is. */
export function zhNotice(rawText: string): NoticeInfo {
  const raw = String(rawText ?? '').split('\n')[0]!.trim()
  const warn = (text: string): NoticeInfo => ({ kind: 'warn', text, raw })
  let m: RegExpMatchArray | null
  const noise = (text: string, cmds?: string[]): NoticeInfo => ({ kind: 'noise', text, raw, ...(cmds ? { cmds } : {}) })
  // command traces first: an assistant asked to run commands, and how the approval ended (the commands
  // themselves may say "error", which must not turn the trace into a red warning)
  if ((m = raw.match(/^(\S+) asks permission: (\w+) (\[.*?\])(?: —|$)/))) {
    const cmds = parseCmdList(m[3]!)
    return noise(`${m[1]} 请求${approvalKindLabel(m[2])}（${cmds.length} 条）`, cmds)
  }
  if ((m = raw.match(/^approval \S+ \((\w+) (\[.*\])\): (\w+)/))) {
    const cmds = parseCmdList(m[2]!)
    return noise(`${DECISION_ZH[m[3]!] ?? m[3]}：${approvalKindLabel(m[1])}（${cmds.length} 条）`, cmds)
  }
  if (/^审批 \S+ 已过期/.test(raw)) return noise('审批已过期（助手那边的请求已不存在）')
  if ((m = raw.match(/^(\S+) paused(?: \((.*)\))?/))) return warn(`⏸ ${m[1]} 已暂停${m[2] ? `（${m[2]}）` : ''}`)
  if ((m = raw.match(/^(\S+) hit its vendor usage limit/))) return warn(`⚠ ${m[1]} 触到厂商额度上限，消息已挂起`)
  if ((m = raw.match(/^turn \S+ of (\S+) ended without xmuse_send/))) return warn(`⚠ ${m[1]} 的回合结束了，但没有回复`)
  if ((m = raw.match(/^chain (\S+) capped/))) return warn(`⚠ 连锁对话 ${m[1]} 已封顶，待处理消息被扣下`)
  if (/no longer bound/i.test(raw) || /\bstall/i.test(raw)) return warn(`⚠ ${raw}`)
  if (/\b(failed|error)\b/i.test(raw)) return { kind: 'error', text: `⚠ ${raw}`, raw }
  if ((m = raw.match(/^(\S+) joined the room \((.*)\)$/))) return noise(`${m[1]} 加入（${m[2]}）`)
  if ((m = raw.match(/^(\S+) opened the room/))) return noise(`${m[1]} 打开了房间`)
  if ((m = raw.match(/^(\S+) left its sidebar session/))) return noise(`${m[1]} 离开了侧栏（仍是成员）`)
  if ((m = raw.match(/^(\S+) was removed from the room/))) return noise(`${m[1]} 被移出房间`)
  if ((m = raw.match(/^(\S+) now hosts the room/))) return noise(`${m[1]} 成为主控`)
  if ((m = raw.match(/^(\S+) was edited: (.*)$/))) return noise(`${m[1]} 的设置已修改：${m[2]}`)
  if ((m = raw.match(/^private group (\S+) created with (.*)$/))) return noise(`私有小群 ${m[1]} 已建立：${m[2]!.split(/,\s*/).join('、')}`)
  if ((m = raw.match(/^(\S+) was added to (\S+)$/))) return noise(`${m[1]} 加入 ${m[2]}`)
  if ((m = raw.match(/^(\S+) was removed from (\S+)$/))) return noise(`${m[1]} 被移出 ${m[2]}`)
  if ((m = raw.match(/^(\S+) left (\S+)$/))) return noise(`${m[1]} 退出 ${m[2]}`)
  return noise(raw)
}

export type NoiseItem = { id: number; text: string; at?: number; cmds?: string[] }
export type Row =
  | { kind: 'msg'; m: Msg }
  | { kind: 'group'; key: string; items: Msg[] } // same sender, same place, within 3 minutes: items oldest first
  | { kind: 'noise'; key: string; items: NoiseItem[] }

const GROUP_GAP_SEC = 180
const GROUP_MAX = 6

function plainMsg(m: Msg): boolean {
  return m.kind !== 'system' && m.kind !== 'done' && !(m as any).retracted
}

/** older and newer (newest-first list) go under one avatar: same sender, thread and addressees, close in time. */
function groupable(older: Msg, newer: Msg): boolean {
  if (!plainMsg(older) || !plainMsg(newer)) return false
  if (older.from !== newer.from || (older.thread ?? '') !== (newer.thread ?? '')) return false
  if (toLabel(older) !== toLabel(newer)) return false
  const a = older.at, b = newer.at
  return typeof a === 'number' && typeof b === 'number' && b - a <= GROUP_GAP_SEC
}

/** Newest-first messages to display rows: a run of consecutive noise notices becomes one row (items oldest first). */
export function buildRows(msgs: Msg[]): Row[] {
  const rows: Row[] = []
  let run: NoiseItem[] = []
  const flush = () => {
    if (!run.length) return
    const items = run.slice().reverse()
    rows.push({ kind: 'noise', key: `ns-${items[0]!.id}`, items })
    run = []
  }
  for (const m of msgs) {
    const zn = m.kind === 'system' ? zhNotice(String(m.text ?? '')) : null
    if (zn && zn.kind === 'noise') {
      run.push({ id: m.id, text: zn.text, at: m.at, ...(zn.cmds ? { cmds: zn.cmds } : {}) })
      continue
    }
    flush()
    const last = rows[rows.length - 1]
    const newer = last?.kind === 'msg' ? last.m : last?.kind === 'group' ? last.items[0]! : null
    if (last && newer && groupable(m, newer)) {
      if (last.kind === 'msg') { rows[rows.length - 1] = { kind: 'group', key: `g-${m.id}`, items: [m, last.m] }; continue }
      if (last.kind === 'group' && last.items.length < GROUP_MAX) { rows[rows.length - 1] = { kind: 'group', key: `g-${m.id}`, items: [m, ...last.items] }; continue }
    }
    rows.push({ kind: 'msg', m })
  }
  flush()
  return rows
}

/** Time (epoch seconds) a row stands for: its newest item. */
export function rowAt(r: Row): number | undefined {
  if (r.kind === 'msg') return r.m.at
  if (r.kind === 'group') return r.items[r.items.length - 1]?.at
  return r.items[r.items.length - 1]?.at
}

// ---- event cards in the feed: a tone per kind of event, so actions read apart from messages ----------------------

export type ToneKey = 'ask' | 'ok' | 'no' | 'info' | 'warn' | 'error' | 'done'
// fg: a theme colour name for the icon; bg / border: translucent tints that read on a dark and a light pane
export type Tone = { icon: string; fg: string; bg: string; border: string }
export const TONES: Record<ToneKey, Tone> = {
  ask: { icon: '⌘', fg: 'warning', bg: '#D299220F', border: '#D2992240' },
  ok: { icon: '✓', fg: 'success', bg: '#3FB9500D', border: '#3FB95038' },
  no: { icon: '✕', fg: 'error', bg: '#F851490D', border: '#F8514938' },
  info: { icon: '•', fg: 'subtle', bg: '#8C8C960A', border: '#8C8C962E' },
  warn: { icon: '!', fg: 'warning', bg: '#D299220F', border: '#D2992240' },
  error: { icon: '!', fg: 'error', bg: '#F851490F', border: '#F8514945' },
  done: { icon: '✓', fg: 'success', bg: '#3FB9500A', border: '#3FB95030' },
}

/** The tone of a run of notices: a pending request wins, then a rejection, an approval; else plain information. */
export function noiseTone(items: NoiseItem[]): ToneKey {
  const t = items.map(i => i.text)
  if (t.some(x => x.includes('请求'))) return 'ask'
  if (t.some(x => x.includes('拒绝'))) return 'no'
  if (t.some(x => x.includes('批准'))) return 'ok'
  return 'info'
}

/** A noise run's title without its time (the card shows the time apart): the events joined, or "N 件事" past three. */
export function noiseTitle(items: NoiseItem[]): string {
  return items.length > 3 ? `${items[items.length - 1]!.text} 等 ${items.length} 件事` : items.map(i => i.text).join('、')
}

/** A small context meter: a rounded track and a fill up to the auto-compact mark, green / amber / red. */
export function ctxBarSvg(tokens: unknown, mark = AUTO_COMPACT_TOKENS, w = 56, h = 6): string {
  const t = Math.max(0, Number(tokens) || 0)
  const ratio = Math.min(1, t / mark)
  const lvl = ctxLevel(t, mark)
  const fill = lvl === 2 ? '#F85149' : lvl === 1 ? '#D29922' : '#3FB950'
  const fw = t > 0 ? Math.max(h, Math.round(ratio * w)) : 0
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">`
    + `<rect width="${w}" height="${h}" rx="${h / 2}" fill="#8C8C9640"/>`
    + (fw ? `<rect width="${fw}" height="${h}" rx="${h / 2}" fill="${fill}"/>` : '') + '</svg>'
}

/** One line for a noise run: the events joined, or "共 N 件事" past three. */
export function noiseSummary(items: NoiseItem[]): string {
  const when = fmtClock(items[items.length - 1]?.at)
  const body = items.length > 3 ? `共 ${items.length} 件事` : items.map(i => i.text).join('、')
  return `· ${when ? when + ' · ' : ''}${body}`
}

const KIND_ZH: Record<string, string> = { shell: '执行命令', share: '分享私信', alignment: '对齐提案', resume: '恢复会话' }
export function approvalKindLabel(kind: string | undefined): string {
  const k = kind || 'shell'
  return KIND_ZH[k] ?? k
}

/** "3 分钟前" for an epoch-seconds time ('' when unknown). */
export function agoText(at: number | undefined, nowMs: number): string {
  if (typeof at !== 'number' || !isFinite(at) || !nowMs) return ''
  const sec = Math.max(0, Math.floor((nowMs - (at > 1e11 ? at : at * 1000)) / 1000))
  if (sec < 60) return '刚刚'
  if (sec < 3600) return `${Math.floor(sec / 60)} 分钟前`
  if (sec < 86400) return `${Math.floor(sec / 3600)} 小时前`
  return `${Math.floor(sec / 86400)} 天前`
}

/** A message the assistant wrote when it ended its turn with xmuse_done: text is "{summary}\nnext: {who}". */
export function isDoneMsg(m: Msg): boolean {
  return m.kind === 'done'
}

export function doneInfo(m: Msg): { summary: string; next: string; outcome: string } {
  const t = String(m.text ?? '')
  const k = t.lastIndexOf('\nnext: ')
  const body = k >= 0 ? t.slice(0, k) : t
  const next = k >= 0 ? t.slice(k + 7).trim() : ''
  let summary = body.split('\n').find(l => l.trim())?.trim() ?? ''
  if (summary.length > 80) summary = summary.slice(0, 80) + '…'
  return { summary, next, outcome: typeof m.outcome === 'string' ? m.outcome : '' }
}

/** Gets the emphasised "to Claude" look: addressed to the panel's member, and not written by the user or by itself. */
export function isToClaude(m: Msg, me: string): boolean {
  return m.for_me === true && m.from !== 'human' && m.from !== me
}
