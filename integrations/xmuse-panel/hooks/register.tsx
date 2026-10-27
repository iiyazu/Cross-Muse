import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { ConnInfo } from '../types'
import type { Pal, RailItem, Tone } from './logic'
import {
  C_AMBER, C_BLUE, C_GREEN, C_ORANGE, C_RED, agoText, approvalHasAlways, approvalKindLabel, approvalText, approvalsOf, avatarSvg, backoffMs,
  bigInputPlan, buildRows, buildSay, buildWakePrompt, displayName, doneInfo, expandNewlines, fmtClock, hardBreaks, isAutoForward,
  isDoneMsg, isLoopbackUrl, isToClaude, matchHubs, maxWakeId, membersOf, messagesFor, noiseSummary, parseHubs, parseMentions, replyLabel,
  statusOf, summaryLine, railOf, activeTabOf, dmThreadId, roomSvg, toLabel, toolCount, unreadThreadsFor, wakeCandidates, zhNotice,
  workingMembers, doneLine, finishedMembers, toPosix, structOf,
  badgeOf, completeMention, dayLabel, foldLong, isLightTheme, memberColor, mentionCandidates, mixHex, palOf, rowAt, splitBlocks,
  trailingMention, vendorKey, canCompact, ctxLevel, ctxText, mergeCompactInstructions, hubStartScript,
  TONES, ctxBarSvg, noiseTitle, noiseTone, freshMessage, revealSteps, shortModel, softWrap, clip, sendPayload, sendOutcome,
} from './logic'

// xmuse panel (slice T8d): read-only view of the project's hub plus sending.
// Windowing rule from experiments: `$` may only be passed to functions declared at the top level of this file.
// T8e: approval cards, working strip, add-assistant, wake Claude. T8f: typing effect and done line. H1: open-room button.
// T8 wrap-up: stop, retract, compaction (context size per member, the 压缩 button, the session.compact hook), the hub
// found through WSL instead of fixed paths, and a known room's hub started by itself after a reboot.
// TODO: "open in terminal" (H7).
// DEV (./dev.ts) is false in the repository and true in a dev mod folder. It switches the dev-only things: LOAD_MARK,
// FOCUS_MARK and REBIND_MARK (written for diagnosis), the ROOM_OVERRIDE fallback and DEV_AVATAR_DIR.
import { DEV, DEV_AVATAR_DIR, FOCUS_MARK, LOAD_MARK, REBIND_MARK, ROOM_OVERRIDE } from './dev'

const PANE = 'xmuse'
// The registry directory (hubs.json, sidebar.key, install.json) and how to start a hub are found once through WSL and
// kept in the store: see hubSetup. Nothing machine-specific is written here.
const STORE_SETUP = 'setup' // HubSetup
const STORE_KNOWN = 'knownRooms' // string[]: room directories this panel has joined; one found down gets its hub started
const STORE_CONN = 'conn' // key prefix, 'conn:<room dir>' (connKey): { url, token, member }, the operator token from /v1/join
// The sidebar's Claude joins as the room's coordinator: its id is the room's `host` in hubs.json.
const STORE_AUTO = 'autoWake' // boolean: submit a turn when a message for the panel arrives (default off)
const STORE_SEEN = 'wakeSeen' // number: highest message id already handled (submitted or baseline)

const connAtom = atom({ plugin: 'xmuse', key: 'conn' } as const, { phase: 'idle', error: '' } as ConnInfo)
const viewAtom = atom({ plugin: 'xmuse', key: 'view' } as const, null as any)
const tabAtom = atom({ plugin: 'xmuse', key: 'tab' } as const, '#room') // the open rail entry: '#room', a dm: thread id, or 'all'
const replyAtom = atom({ plugin: 'xmuse', key: 'replyTo' } as const, 0)
const genAtom = atom({ plugin: 'xmuse', key: 'gen' } as const, 0)
const promotedAtom = atom({ plugin: 'xmuse', key: 'promoted' } as const, {} as Record<string, string>)
const lastReadAtom = atom({ plugin: 'xmuse', key: 'lastRead' } as const, '')
const themeAtom = atom({ plugin: 'xmuse', key: 'light' } as const, false) // the /config theme is a light one
const mentionAtom = atom({ plugin: 'xmuse', key: 'mention' } as const, null as string | null) // typed prefix after a trailing @, or null
// the text the Input is drawn with (a @ completion, a retracted message put back), or null: a new `value` on the same
// Input replaces its text in place, so the field keeps the focus (a new key would mount a fresh, unfocused field)
const forcedAtom = atom({ plugin: 'xmuse', key: 'forced' } as const, null as string | null)
const decisionAtom = atom({ plugin: 'xmuse', key: 'decision' } as const, { id: 0, text: '', ok: true })
const avatarVerAtom = atom({ plugin: 'xmuse', key: 'avatarVer' } as const, 0)
let draftLive = '' // the Input's text as last reported by onInput; read at press time, no redraw per key
const avatarImgs: Record<string, string> = {} // member id or 'v:<vendor>' -> data: URI of a custom avatar PNG
let avatarTried: Record<string, boolean> = {}
let decisionN = 0
const toastSeen = new Set<string>()
let toastSeeded = false
const sendNAtom = atom({ plugin: 'xmuse', key: 'sendN' } as const, 0) // goes into the Input key: a new key clears it
// bumped by an @ completion: part of the Input key, so the field is remounted with the completed text
const inputGenAtom = atom({ plugin: 'xmuse', key: 'inputGen' } as const, 0)
const sendingAtom =atom({ plugin: 'xmuse', key: 'sending' } as const, false)
const addOpenAtom = atom({ plugin: 'xmuse', key: 'addOpen' } as const, false)
const expandedAtom = atom({ plugin: 'xmuse', key: 'expanded' } as const, '') // id of the member whose card is open under the chips, or ''
const foldAtom = atom({ plugin: 'xmuse', key: 'fold' } as const, {} as Record<string, boolean>) // opened rows: done lines, noise runs, warnings
// Message actions (reply / promote) show on hover. If hover does not work in the desktop pane, set this to false: the buttons stay visible.
const HOVER_ACTIONS: boolean = true
const STORE_BRIEF = 'briefMissing' // boolean: the room was opened and has no project brief yet
const TOOL = 'xmuse_send' // registered as mcp__xmuse__xmuse_send
const TOOL_BRIEF = 'xmuse_brief' // mcp__xmuse__xmuse_brief: writes the project brief
const openAtom = atom({ plugin: 'xmuse', key: 'open' } as const, { busy: false, msg: '', error: '' })
// The latest full view from the hub, kept outside the atom: its members' `progress` (text, tool, counts) changes every few
// seconds, and every atom write redraws the whole panel. viewAtom holds structOf(view) and is written only when that changes;
// the live parts (live.tsx Clients) read this through the ui.message hook.
let liveView: any = null
let structJson = ''
const doneAtom = atom({ plugin: 'xmuse', key: 'done' } as const, {} as Record<string, { tools: number; startedMs: number; endedMs: number }>)
const briefAtom = atom({ plugin: 'xmuse', key: 'brief' } as const, false) // mirrors STORE_BRIEF so the panel redraws
const DONE_KEEP_MS = 30_000 // how long the grey "finished" line stays
const POOL = 5000 // messages a tab can scroll through: the view's own plus every older page loaded
const OLDER_PAGE = 100 // one "加载更早的消息" press
const seenMsgs = new Map<number, any>() // every timeline item seen this load, by id (the newest copy wins)
let seenRoom = ''
// older pages fetched from /v1/timeline (oldest first), and whether the hub has still older ones
const olderAtom = atom({ plugin: 'xmuse', key: 'older' } as const, { items: [] as any[], hasMore: true, loading: false })
// messages drawn per conversation (newest first): a draw builds only these, the rest waits behind "显示更早的"
const shownAtom = atom({ plugin: 'xmuse', key: 'shown' } as const, {} as Record<string, number>)
const SHOW_STEP = 40
const busyAtom =atom({ plugin: 'xmuse', key: 'busy' } as const, {} as Record<string, boolean>) // approval ids in flight
const selfCtxAtom = atom({ plugin: 'xmuse', key: 'selfCtx' } as const, 0) // this session's own context fill (session.measure)
// a member's message that just arrived, drawn growing to its full length (the vendors give no token stream for it)
const revealAtom = atom({ plugin: 'xmuse', key: 'reveal' } as const, { id: 0, steps: [] as number[], run: 0 })
// the model picker of one member: what the hub offers (act models), or loading / an error
type ModelPick = { member: string; current: string; options: { value: string; label?: string }[]; format: string; note: string; loading: boolean; error: string }
const modelAtom = atom({ plugin: 'xmuse', key: 'modelPick' } as const, null as ModelPick | null)
let feedMaxId = -1 // highest timeline id seen this load; -1 until the first view sets the baseline (history: no effect)
let revealRunN = 0
const REVEAL_STEP_MS = 70
const NARROW_COLS = 56 // below this many cells (about 420 px) member chips shrink to avatar and state dot
const RAIL_COLS = 22 // the vertical list's widest width, in cells (it shrinks with the pane: railW in drawPanel)
const STORE_PROBE = 'probe' // boolean: the two probes (scroll events, the band above the prompt) are on; toggled by `/xmuse probe`
const probeAtom = atom({ plugin: 'xmuse', key: 'probe' } as const, false) // mirrors STORE_PROBE so the panel and the band redraw
type ScrollProbe = { n: number; by: number; offset: number; bodyRows: number; contentRows: number; origin: string }
const scrollProbeAtom = atom({ plugin: 'xmuse', key: 'scrollProbe' } as const, { n: 0, by: 0, offset: 0, bodyRows: 0, contentRows: 0, origin: '' } as ScrollProbe)
let scrollProbe: ScrollProbe = { n: 0, by: 0, offset: 0, bodyRows: 0, contentRows: 0, origin: '' } // every Pane ui.scroll seen this load
let scrollProbeAt = -Infinity // host clock of the last write of scrollProbe to the atom
let bandDraws = 0 // draws of the AbovePrompt probe band
// Layouts: 'chat' (default: oldest message first, the newest and the composer at the bottom, the pane scrolls as a whole page and
// follows the newest message) | 'flow' (newest first under the composer). A stored 'pinned' (an older layout) reads as 'chat'.
const STORE_LAYOUT = 'layout' // toggled by `/xmuse layout`
const layoutAtom = atom({ plugin: 'xmuse', key: 'layout' } as const, 'chat' as 'chat' | 'flow')
// The rail can be folded by hand to avatars only (the `rail-fold` button); kept in the store across loads.
const STORE_RAIL = 'railFold' // boolean
const railFoldAtom = atom({ plugin: 'xmuse', key: 'railFold' } as const, false)
const RAIL_FOLD_COLS = 6 // the folded rail's width in cells
// Following the newest message: true while the person's last scroll left the window at the end (a plugin-made move does not count).
let atBottom = true
let pollMaxId = -1 // highest timeline id the poll has seen
let pollDrafts = '' // ids of the members with a draft row at the last view
let firstViewSeen = false // the first successful view of this loop has been handled
const GROW_GRACE_MS =1500 // a grow Client that has not reported this long after its last step is dropped (growDone clears the atom)

// ---- hub access ----------------------------------------------------------------------------------------------

// token: operator (speaks as the user); memberToken: this session's own member; sid: the session the member was bound
// to last. Both tokens live in the hub's state (db, tokens/), so they outlive a hub restart: only `url` changes then.
type HubConn = { url: string; token: string; member: string; memberToken?: string; dir?: string; sid?: string }
const suspect = new Set<string>() // room dirs whose stored address failed a call: check it before trusting it again
let legacyConnDropped = false

const elapsedStart = (v: any): number => (typeof v === 'number' && isFinite(v) ? v : 0) // started_at as a Client prop (plain JSON)

// Every atom write redraws the whole panel (and voids the handlers of its buttons), so the writes that run on every
// poll skip a value that did not change (read first, compare). `read` and `update` need the atom as a const of this
// file, so the check is written at each call site instead of in a helper.
async function setConn($: any, phase: ConnInfo['phase'], error: string) {
  const cur = await read($, connAtom)
  if (cur.phase === phase && cur.error === error) return
  await update($, connAtom, () => ({ phase, error }))
}

/** One store key per room directory: sessions on different rooms share the plugin's store and must not overwrite each other. */
function connKey(dir: string): string {
  return STORE_CONN + ':' + dir
}

async function clearConn($: any, dir: string) {
  suspect.delete(dir)
  try { await $.store.delete(connKey(dir)) } catch { /* nothing stored */ }
}

/** Does this hub take our operator token? 'ok', 'denied' (another room, or its state was reset) or 'down'. 3 s at most. */
async function probeToken($: any, url: string, token: string): Promise<'ok' | 'denied' | 'down'> {
  try {
    const r: any = await Promise.race([
      $.http.fetch(`${url}/v1/view?since=0&wait=0`, { method: 'GET', headers: { authorization: `Bearer ${token}` } }),
      $.clock.sleep(3000).then(() => { throw new Error('timeout') }),
    ])
    return r.status === 200 || r.status === 204 ? 'ok' : 'denied'
  } catch { return 'down' }
}

/**
 * The member stays bound to the session that uses it: after the desktop app restarted (a new session id) the member
 * is moved over with /v1/rebind (the member token proves it is ours), once per load of this session (`rebound`): the
 * store is shared, so two sessions open on one room would otherwise take the member back from each other on every poll
 * (each take changes the view: both panels redraw without pause). /xmuse takes it over again. Failing that, the panel still
 * works on the operator token; only the model's xmuse_send would be refused as "bound to another session".
 * The rebind races a 3 s timeout like probeToken (no hang: see §3.2); the outcome goes to REBIND_MARK under DEV.
 */
const rebound = new Set<string>() // '<room dir>|<session id>' already bound by this load: never taken back unasked

async function ensureBound($: any, c: HubConn): Promise<HubConn> {
  const sid: string = await $.session.id()
  if (c.sid === sid || !c.memberToken) return c
  const once = `${c.dir ?? ''}|${sid}`
  if (rebound.has(once)) return c // another session took it later: leave it there
  rebound.add(once)
  const mark = async (s: string) => {
    if (DEV) { try { await $.fs.write(REBIND_MARK, `${new Date().toISOString()} ${s}\n`) } catch { /* diagnostics only */ } }
  }
  try {
    const r: any = await Promise.race([
      $.http.fetch(`${c.url}/v1/rebind`, {
        method: 'POST', headers: { authorization: `Bearer ${c.memberToken}`, 'content-type': 'application/json' },
        body: JSON.stringify({ session_id: sid }),
      }),
      $.clock.sleep(3000).then(() => { throw new Error('timeout') }),
    ])
    if (r.status !== 200) { await mark(`rebind ${r.status}`); return c }
  } catch (err) { await mark(`rebind ${errText(err)}`); return c }
  const n = { ...c, sid }
  await $.store.set(connKey(n.dir ?? await roomDirFor($)), n)
  await mark('rebind ok')
  return n
}

function errText(err: unknown): string {
  const s = err instanceof Error ? err.message : String(err)
  return s.slice(0, 200)
}

/** No room for this directory yet: the panel offers the "open room" button instead of retrying. */
class NoRoomError extends Error {}
/** A room this panel has joined before has no hub answering (after a reboot): the panel starts it once by itself. */
class HubDownError extends Error {}

// stateDir: the registry directory as a Windows path; distro and python: from install.json, which every hub writes
type HubSetup = { stateDir: string; distro: string; python: string; path?: string }
let setupCache: HubSetup | null = null
let autoStartTried = false

async function readText($: any, path: string): Promise<string | null> {
  try { return String(await $.fs.read(path)) } catch { return null }
}

async function withInstall($: any, s: HubSetup): Promise<HubSetup> {
  try {
    const j = JSON.parse((await readText($, `${s.stateDir}/install.json`)) ?? '')
    return { ...s, python: typeof j?.python === 'string' ? j.python : s.python, distro: typeof j?.distro === 'string' && j.distro ? j.distro : s.distro,
      path: typeof j?.path === 'string' ? j.path : s.path }
  } catch { return s }
}

/**
 * Where the hub registry is and how to start a hub. The stored answer is used while its directory still reads; else
 * the default WSL distro is asked for its registry directory (registry.py directory()), which also boots WSL after a
 * reboot. install.json, when a hub has written it, names the interpreter.
 */
async function hubSetup($: any): Promise<HubSetup> {
  if (setupCache) return setupCache
  const stored = (await $.store.get(STORE_SETUP)) as HubSetup | undefined
  if (stored?.stateDir && ((await readText($, `${stored.stateDir}/install.json`)) !== null
    || (await readText($, `${stored.stateDir}/hubs.json`)) !== null)) {
    setupCache = await withInstall($, stored)
  } else {
    const r = await $.process.run(['wsl.exe', '-e', 'sh', '-s'], {
      stdin: 'echo "$WSL_DISTRO_NAME"\necho "${XDG_STATE_HOME:-$HOME/.local/state}/xmuse"\n', timeoutMs: 30_000 })
    const [distro, dir] = String(r.stdout ?? '').split(/\r?\n/).map((s: string) => s.trim())
    if (r.exitCode !== 0 || !distro || !dir || !dir.startsWith('/')) {
      throw new Error(`找不到 WSL 里的 xmuse 登记目录（wsl.exe 退出码 ${r.exitCode}）`)
    }
    setupCache = await withInstall($, { stateDir: `//wsl.localhost/${distro}${dir}`, distro, python: '' })
  }
  if (JSON.stringify(stored) !== JSON.stringify(setupCache)) await $.store.set(STORE_SETUP, setupCache)
  return setupCache
}

async function knownRooms($: any): Promise<string[]> {
  const v = await $.store.get(STORE_KNOWN)
  return Array.isArray(v) ? v.filter((x: unknown) => typeof x === 'string') : []
}

async function addKnown($: any, dir: string) {
  const k = await knownRooms($)
  if (!k.includes(dir)) await $.store.set(STORE_KNOWN, [...k, dir].slice(-20))
}

/** A hub answers at this address (any HTTP status counts); 3 s at most. */
async function hubAlive($: any, url: string, key: string): Promise<boolean> {
  try {
    await Promise.race([
      $.http.fetch(`${url}/v1/rooms`, { method: 'GET', headers: { 'x-xmuse-sidebar': key } }),
      $.clock.sleep(3000).then(() => { throw new Error('timeout') }),
    ])
    return true
  } catch { return false }
}

/**
 * The room directory of this session and the hubs registered for it: the session's cwd, or (DEV, no hub for the cwd)
 * the override file's directory. getConn and roomDirFor use the same rule.
 */
async function lookupRoom($: any) {
  const cwd: string = await $.session.cwd()
  let hubsText = ''
  let hubsErr = ''
  let stateDir = ''
  try {
    stateDir = (await hubSetup($)).stateDir
    hubsText = await $.fs.read(`${stateDir}/hubs.json`)
  } catch {
    hubsErr = '读不到本机登记表（hubs.json）：WSL 没启动，或还没有 hub'
  }
  let roomDir = toPosix(cwd)
  let cands = matchHubs(parseHubs(hubsText), cwd).filter(e => isLoopbackUrl(e.url ?? ''))
  if (!cands.length && DEV) {
    // Dev only: a session whose own directory has no room can point at a test room's directory.
    let alt = ''
    try { alt = String(await $.fs.read(ROOM_OVERRIDE)).trim() } catch { /* no override */ }
    if (alt) { roomDir = alt; cands = matchHubs(parseHubs(hubsText), alt).filter(e => isLoopbackUrl(e.url ?? '')) }
  }
  return { cwd, roomDir, cands, hubsErr, stateDir }
}

async function roomDirFor($: any): Promise<string> {
  return (await lookupRoom($)).roomDir
}

/**
 * Stored connection of this session's room, or find the room for this session's directory and join it with the
 * sidebar key. Connections are kept per room directory (the store is shared by every session of the plugin).
 */
async function getConn($: any): Promise<HubConn> {
  if (!legacyConnDropped) {
    legacyConnDropped = true
    try { await $.store.delete('conn') } catch { /* nothing stored */ } // the old single, session-shared key
  }
  const { cwd, roomDir, cands, hubsErr, stateDir } = await lookupRoom($)
  const stored = (await $.store.get(connKey(roomDir))) as HubConn | undefined
  // joined before (the list, or a connection kept from before the list existed)
  const kr = await knownRooms($)
  const known = kr.includes(roomDir) || kr.includes(toPosix(cwd)) || (!!stored?.dir && stored.dir === roomDir)
  if (known && !kr.includes(roomDir)) await addKnown($, roomDir)
  if (!cands.length && known) throw new HubDownError(hubsErr || '房间的 hub 没在运行')
  if (!cands.length) throw new NoRoomError(hubsErr || '这个目录还没有 xmuse 房间')
  // A stored connection is reused while the hub still takes it. The hub restarted on a new address: the tokens still
  // hold there, so only the address moves (a re-join would be refused: the member is still bound to the session that
  // last used it).
  if (stored && typeof stored.url === 'string' && typeof stored.token === 'string') {
    const urls = cands.map(e => String(e.url).replace(/\/$/, ''))
    if (urls.includes(stored.url) && !suspect.has(roomDir)) {
      return ensureBound($, stored)
    } else {
      let down = 0
      for (const url of [stored.url, ...urls.filter(u => u !== stored.url)].filter(u => urls.includes(u))) {
        const p = await probeToken($, url, stored.token)
        if (p === 'ok') {
          suspect.delete(roomDir)
          const moved = { ...stored, url }
          if (url !== stored.url) await $.store.set(connKey(roomDir), moved)
          return ensureBound($, moved)
        }
        if (p === 'down') down++
      }
      if (known && down === urls.length) throw new HubDownError(`连不上 ${urls.join('、')}`)
      await clearConn($, roomDir) // a hub that refuses our token (its state was reset): join afresh below
    }
  }

  let key = ''
  try { key = String(await $.fs.read(`${stateDir}/sidebar.key`)).trim() } catch { /* handled below */ }
  if (!/^[0-9a-f]{64}$/.test(key)) throw new Error('读不到侧栏凭据（sidebar.key）')

  const sid: string = await $.session.id()
  let last = '没有可用的 hub'
  let unreachable = 0
  for (const e of cands) {
    const url = String(e.url).replace(/\/$/, '')
    // The coordinator id is the room's host from hubs.json (it differs per room); a registry without it: 'claude'.
    const member = typeof e.host === 'string' && e.host ? e.host : 'claude'
    try {
      const body: Record<string, unknown> = { dir: roomDir, vendor: 'claude', session_id: sid, name: member }
      const r = await $.http.fetch(`${url}/v1/join`, {
        method: 'POST',
        headers: { 'content-type': 'application/json', 'x-xmuse-sidebar': key },
        body: JSON.stringify(body),
      })
      let data: any = null
      try { data = JSON.parse(r.text) } catch { /* not JSON */ }
      if (r.status === 200 && data && typeof data.operator_token === 'string') {
        const conn: HubConn = { url, dir: roomDir, token: data.operator_token, member: String(data.member_id ?? ''),
          memberToken: typeof data.member_token === 'string' ? data.member_token : undefined, sid }
        await $.store.set(connKey(roomDir), conn)
        await addKnown($, roomDir)
        rebound.add(`${roomDir}|${sid}`)
        return conn
      }
      if (r.status === 404 && data?.error === 'no_room') throw new NoRoomError('hub 已启动，但还没有房间')
      if (r.status === 409 && data?.error === 'member_exists') {
        // a sidebar join takes a member bound to another session over, so this is a removed member or another vendor's id
        last = `成员 ${member} 不能加入：已被移出房间，或这个 id 属于别的厂商`
        continue
      }
      last = `join 失败 ${r.status}: ${String(data?.message ?? data?.error ?? '').slice(0, 120)}`
    } catch (err) {
      if (err instanceof NoRoomError) throw err
      last = `连不上 ${url}: ${errText(err)}`
      unreachable++
    }
  }
  // every registered address is dead (entries a killed hub left behind, as after a reboot)
  if (known && unreachable === cands.length) throw new HubDownError(last)
  throw new Error(last)
}

/** One authenticated call to the hub. A 401 re-joins once; a network failure drops the stored connection. */
async function callHub($: any, method: string, path: string, body?: unknown): Promise<{ status: number; data: any }> {
  for (let attempt = 0; attempt < 2; attempt++) {
    const conn = await getConn($)
    let r: any
    try {
      r = await $.http.fetch(conn.url + path, {
        method,
        headers: { authorization: `Bearer ${conn.token}`, 'content-type': 'application/json' },
        body: body === undefined ? undefined : JSON.stringify(body),
      })
    } catch (err) {
      if (conn.dir) suspect.add(conn.dir) // the hub may have restarted on another port: getConn checks before trusting it (tokens kept)
      throw new Error(`连不上 ${conn.url}: ${errText(err)}`)
    }
    if (r.status === 401 && attempt === 0) { await clearConn($, conn.dir ?? await roomDirFor($)); continue }
    let data: any = null
    try { data = r.text ? JSON.parse(r.text) : null } catch { /* 204 or not JSON */ }
    return { status: r.status, data }
  }
  throw new Error('令牌失效，重新加入后仍是 401')
}

// ---- polling loop --------------------------------------------------------------------------------------------

async function pollOnce($: any, gen: number, fails: number) {
  if ((await read($, genAtom)) !== gen) return // superseded by a newer loop (retry, reload)
  try {
    const cur = await read($, viewAtom)
    const since = Number(liveView?.version ?? cur?.version ?? 0)
    const r = await callHub($, 'GET', `/v1/view?since=${since}&wait=25`)
    if ((await read($, genAtom)) !== gen) return
    if (r.status === 204) {
      $.clock.after(50, () => { void pollOnce($, gen, 0) })
      return
    }
    if (r.status !== 200 || !r.data) {
      throw new Error(`hub 返回 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 120)}`)
    }
    const oldLive = liveView
    liveView = r.data // the live parts (live.tsx) read progress from here
    await trackDone($, oldLive ?? cur, r.data) // needs the real progress (tool counts): full views
    const grew = await newestGrew($, r.data)
    await revealStart($, r.data) // before the view lands: a new member message is first drawn empty, then grows
    // progress-only changes (text, tool, counts) do not write the atom: the panel is not redrawn for them
    const s = structOf(r.data)
    const j = JSON.stringify({ ...s, version: 0 })
    if (j !== structJson) { structJson = j; await update($, viewAtom, () => s) }
    if (!firstViewSeen) { firstViewSeen = true; scrollEndLater($) } // the first view: show the newest
    else if (grew && atBottom) scrollEndLater($)
    await settleBusy($, r.data)
    await setConn($, 'ok', '')
    await wakeCheck($, r.data, false)
    await refreshStatus($, r.data)
    await refreshTheme($)
    await loadAvatars($, r.data)
    await toastNew($, r.data)
    await autoRead($, r.data)
    $.clock.after(50, () => { void pollOnce($, gen, 0) })
  } catch (err) {
    if (err instanceof NoRoomError) { // not an outage: stop polling, the panel shows the open-room button
      await setConn($, 'noroom', err.message)
      return
    }
    if (err instanceof HubDownError && !autoStartTried) { // a room joined before, no hub (a reboot): start it, once per load
      autoStartTried = true
      await setConn($, 'connecting', '')
      $.clock.after(0, () => { void openRoom($, true) })
      return
    }
    const n = fails + 1
    const wait = backoffMs(n)
    await setConn($, 'error', `${errText(err)}（${Math.round(wait / 1000)} 秒后重试）`)
    $.clock.after(wait, () => { void pollOnce($, gen, n) })
  }
}

async function startLoop($: any) {
  const gen = (await read($, genAtom)) + 1
  await update($, genAtom, () => gen)
  firstViewSeen = false
  await setConn($, 'connecting', '')
  void pollOnce($, gen, 0)
}

// ---- chat layout: following the newest message ----------------------------------------------------------------

/** Scroll the pane to its end (the newest message) and follow it from here on. Never call inside a draw. */
async function scrollToEnd($: any) {
  try { await $.ui.scroll({ to: 'end', in: PANE }) } catch { /* no engine window (not open yet): nothing to scroll */ }
  atBottom = true
}

/** Off the current handler: scroll to the end after the next tick, in the chat layout only (flow keeps the newest at the top). */
function scrollEndLater($: any) {
  $.clock.after(0, () => { void scrollEndIfChat($) })
}

async function scrollEndIfChat($: any) {
  if ((await read($, layoutAtom)) === 'flow') return
  await scrollToEnd($)
}

/** Did the open conversation gain a message or a draft row with this view? The first view only sets the baseline. */
async function newestGrew($: any, view: any): Promise<boolean> {
  const tl: any[] = Array.isArray(view?.timeline) ? view.timeline : []
  const max = tl.reduce((n, m) => (typeof m?.id === 'number' && m.id > n ? m.id : n), 0)
  const prev = pollMaxId
  pollMaxId = Math.max(pollMaxId, max)
  const tab = activeTabOf(view, await read($, tabAtom))
  const item = railOf(view).find(t => t.id === tab)
  const drafts = workingMembers(view).filter(m => (!item?.peer || item.peer === m.id) && m.progress?.has_text).map(m => m.id).join(',')
  const prevDrafts = pollDrafts
  pollDrafts = drafts
  if (prev < 0) return false
  const fresh = max > prev && messagesFor(view, item ? tab : '#room', POOL).some(m => m.id > prev && !m.retracted)
  return fresh || (drafts !== '' && drafts !== prevDrafts)
}

async function toggleRailFold($: any) {
  const on = !(await read($, railFoldAtom))
  await $.store.set(STORE_RAIL, on)
  await update($, railFoldAtom, () => on)
}

// ---- finished line and typing effect (T8f) ---------------------------------------------------------------------

/** A member that stopped running since the last view gets a grey "finished" line for DONE_KEEP_MS. */
async function trackDone($: any, oldView: any, newView: any) {
  const fin = finishedMembers(oldView, newView)
  const runningNow = workingMembers(newView).map(m => m.id)
  const cur = await read($, doneAtom)
  if (!fin.length && !runningNow.some(id => cur[id])) return
  const now = await $.clock.now()
  await update($, doneAtom, m => {
    const n = { ...m }
    for (const id of runningNow) delete n[id] // running again: the old line goes
    for (const f of fin) n[f.id] = { tools: f.tools, startedMs: f.startedMs, endedMs: now }
    return n
  })
  for (const f of fin) $.clock.after(DONE_KEEP_MS, () => { void expireDone($, f.id, now) })
}

async function expireDone($: any, id: string, endedMs: number) {
  const cur = await read($, doneAtom)
  if (cur[id]?.endedMs !== endedMs) return // replaced by a newer run: that one has its own timer
  await update($, doneAtom, m => { const n = { ...m }; delete n[id]; return n })
}

/**
 * Fresh props for a live.tsx Client (the ui.message hook answers its post): the member's progress from the latest full
 * view. A member that is gone or not working gets the same shape, empty.
 */
async function liveProps($: any, part: string, id: string) {
  const v = liveView ?? await read($, viewAtom)
  const m = workingMembers(v).find(x => x.id === id)
  const p = m?.progress
  return {
    part, id,
    tool: typeof p?.last_tool === 'string' ? p.last_tool.trim() : '',
    text: String(p?.text ?? ''),
    tools: toolCount(p),
    startedAt: elapsedStart(p?.started_at),
    nowMs: Number(await $.clock.now()),
  }
}

/**
 * A member's message that a fresh view brought grows to its full length in a few steps (about 40 characters each,
 * REVEAL_STEP_MS apart), so it reads as streamed; a Client (grow.tsx) runs the steps. The first view of a load only
 * sets the baseline; a newer arrival replaces it.
 */
async function revealStart($: any, view: any) {
  const tl: any[] = Array.isArray(view?.timeline) ? view.timeline : []
  const max = tl.reduce((n, m) => (typeof m?.id === 'number' && m.id > n ? m.id : n), 0)
  if (feedMaxId < 0) { feedMaxId = max; return }
  const m = freshMessage(view, feedMaxId)
  feedMaxId = Math.max(feedMaxId, max)
  if (!m) return
  const steps = revealSteps(String(m.text ?? '').length)
  if (!steps.length) return
  const run = ++revealRunN
  await update($, revealAtom, () => ({ id: m.id, steps, run }))
  $.clock.after(steps.length * REVEAL_STEP_MS + GROW_GRACE_MS, () => { void growDone($, { grown: `r:${m.id}:${run}` }) }) // likewise
}

/** ui.message from a grow Client: it showed its last step; the atom goes idle and the normal rendering comes back. */
async function growDone($: any, data: any) {
  const id = typeof data?.grown === 'string' ? data.grown : ''
  const kind = id.slice(0, 2) // 'r:<message id>:<run>'
  const n = Number(id.slice(id.lastIndexOf(':') + 1))
  if (kind === 'r:') await update($, revealAtom, r => (r.run === n ? { id: 0, steps: [], run: 0 } : r))
}

// ---- opening a room (H1) -------------------------------------------------------------------------------------

async function openStep($: any, msg: string) {
  await update($, openAtom, () => ({ busy: true, msg, error: '' }))
}

async function openFail($: any, error: string) {
  await update($, openAtom, () => ({ busy: false, msg: '', error }))
}

/** A registry entry for exactly this (POSIX) directory whose hub answers (a killed hub leaves its entry behind). */
async function findHub($: any, dir: string, key: string): Promise<{ url: string } | null> {
  const text = await readText($, `${(await hubSetup($)).stateDir}/hubs.json`)
  if (text === null) return null
  for (const e of parseHubs(text)) {
    if (!isLoopbackUrl(e.url ?? '') || toPosix(e.dir ?? '').toLowerCase() !== dir.toLowerCase()) continue
    const url = String(e.url).replace(/\/$/, '')
    if (await hubAlive($, url, key)) return { url }
  }
  return null
}

/**
 * The "open room" button: start a hub for this directory inside WSL (unless one is registered already), create the
 * room with the sidebar key (this session becomes a member and the host), keep the tokens, and start the panel loop.
 * Each step shows in the panel; each failure shows its reason there.
 */
/** The directory a room is opened for: the session's own, or (dev) the override file's. getConn uses the same rule. */
async function roomTarget($: any): Promise<string> {
  if (DEV) {
    let alt = ''
    try { alt = String(await $.fs.read(ROOM_OVERRIDE)).trim() } catch { /* no override */ }
    if (alt) return alt
  }
  return toPosix(await $.session.cwd())
}

async function openRoomLater($: any) {
  // A press handler has a 10 s budget; opening a room takes longer, so it runs off the press.
  $.clock.after(0, () => { void openRoom($) })
}

/** The error card's "启动 hub": the automatic start, by hand (it runs once per load by itself). */
async function startHubLater($: any) {
  await setConn($, 'connecting', '')
  $.clock.after(0, () => { void openRoom($, true) })
}

/**
 * `auto`: the panel found a room it had joined with no hub answering (after a reboot). Only the hub is started (no
 * `xmuse init`, no room created); the normal join then takes over, and a hub without that room shows the open button.
 */
async function openRoom($: any, auto = false) {
  if ((await read($, openAtom)).busy) return
  try {
    await openStep($, auto ? '房间的 hub 没在运行，自动启动…' : '读取工作目录…')
    const dir = await roomTarget($)
    if (!dir.startsWith('/') || /['\r\n\0]/.test(dir)) throw new Error(`不支持的工作目录: ${dir}`)
    const setup = await hubSetup($)
    // the key may not exist yet on a machine where no hub ever ran: then nothing can answer, and the hub makes it
    let key = String((await readText($, `${setup.stateDir}/sidebar.key`)) ?? '').trim()

    let hub = /^[0-9a-f]{64}$/.test(key) ? await findHub($, dir, key) : null
    if (!hub) {
      if (!setup.python || /[\r\n\0]/.test(setup.python) || !/^[\w.-]*$/.test(setup.distro)) {
        throw new Error('没有 hub 的安装记录（登记目录里的 install.json）：先在 WSL 里手动启动一次 hub，之后面板就能自己启动')
      }
      await openStep($, '在 WSL 里启动 hub…')
      // The script goes in on stdin (no quoting through wsl.exe's command line); see hubStartScript for why a unit.
      // `xmuse init` makes the workspace's state (idempotent); the hub's own output goes to the state dir's hub.log.
      const script = hubStartScript({ python: setup.python, dir, path: setup.path, init: !auto })
      const argv = setup.distro ? ['wsl.exe', '-d', setup.distro, '-e', 'bash', '-l', '-s'] : ['wsl.exe', '-e', 'bash', '-l', '-s']
      const r = await $.process.run(argv, { stdin: script, timeoutMs: 25_000 })
      if (r.exitCode !== 0) throw new Error(`WSL 启动命令失败（退出码 ${r.exitCode}）: ${String(r.stderr || r.stdout).replace(/\s+/g, ' ').slice(0, 160)}`)
      await openStep($, '等 hub 出现在登记表（启动时要先检查各家模型，约 10–30 秒）…')
      for (let i = 0; i < 60 && !hub; i++) {
        await $.clock.sleep(1000)
        if (!/^[0-9a-f]{64}$/.test(key)) key = String((await readText($, `${setup.stateDir}/sidebar.key`)) ?? '').trim()
        if (/^[0-9a-f]{64}$/.test(key)) hub = await findHub($, dir, key)
      }
      if (!hub) throw new Error('60 秒内 hub 没有登记（可能还在启动，稍后点重试；日志在房间状态目录 logs/hub.log，'
        + '单元状态：systemctl --user status xmuse-hub-*）')
    }
    if (auto) {
      await clearConn($, dir) // the old address is dead: join afresh at the new one
      await update($, openAtom, () => ({ busy: false, msg: '', error: '' }))
      await startLoop($)
      return
    }

    await openStep($, '创建房间…')
    if (!/^[0-9a-f]{64}$/.test(key)) throw new Error('读不到侧栏凭据（sidebar.key）')
    const sid: string = await $.session.id()
    const body: Record<string, unknown> = { dir, vendor: 'claude', session_id: sid, member_id: 'claude' } // a new room's host is the sidebar's Claude
    const r = await $.http.fetch(`${hub.url}/v1/rooms`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-xmuse-sidebar': key },
      body: JSON.stringify(body),
    })
    let data: any = null
    try { data = JSON.parse(r.text) } catch { /* not JSON */ }
    if (r.status === 200 && data && typeof data.operator_token === 'string') {
      const conn: HubConn = { url: hub.url, dir, token: data.operator_token, member: String(data.member_id ?? ''),
        memberToken: typeof data.member_token === 'string' ? data.member_token : undefined, sid }
      await $.store.set(connKey(dir), conn)
      await addKnown($, dir)
      if (data.brief_missing === true) { await $.store.set(STORE_BRIEF, true); await update($, briefAtom, () => true) }
    } else if (r.status === 409 && data?.error === 'room_exists') {
      await clearConn($, dir) // the hub already has a room (another session opened it): the normal join takes over below
    } else {
      throw new Error(`建房失败 ${r.status}: ${String(data?.message ?? data?.error ?? r.text ?? '').slice(0, 140)}`)
    }
    await update($, openAtom, () => ({ busy: false, msg: '', error: '' }))
    await startLoop($)
  } catch (err) {
    if (!auto) { await openFail($, errText(err)); return }
    await update($, openAtom, () => ({ busy: false, msg: '', error: '' })) // the error card says it, with a start button
    await setConn($, 'error', `启动 hub 失败：${errText(err)}`)
  }
}

/** The panel's "let Claude write it" button: asks the model for the brief and to save it with xmuse_brief. */
async function askBrief($: any) {
  try {
    await $.prompt.submit({ text: '[xmuse] 这个项目的协作室还没有项目简介。请先读一下项目（README、目录结构、配置文件），'
      + '写一段项目简介（目标、技术栈、约定，200 字内），然后调用工具 xmuse_brief，参数 text 填这段简介，保存到协作室。' })
  } catch (err) {
    $.ui.toast(`发送失败: ${errText(err)}`)
  }
}

async function dismissBrief($: any) {
  await $.store.set(STORE_BRIEF, false)
  await update($, briefAtom, () => false)
}

/** The model's xmuse_brief tool: writes the project brief with the operator token. */
async function briefTool($: any, e: any): Promise<any> {
  const text = typeof e?.text === 'string' ? e.text.trim() : ''
  if (!text) return { deny: '缺少 text（项目简介正文）' }
  try {
    const r = await callHub($, 'POST', '/v1/act', { act: 'brief', text })
    if (r.status !== 200) return { deny: `保存失败 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 200)}` }
    await dismissBrief($)
    return { result: `项目简介已保存${r.data?.entry ? `（${r.data.entry}）` : ''}` }
  } catch (err) {
    return { deny: `保存失败: ${errText(err)}` }
  }
}

// ---- actions -------------------------------------------------------------------------------------------------

async function markRead($: any, threads: string[]) {
  for (const t of threads) {
    try { await callHub($, 'POST', '/v1/act', { act: 'read', thread: t }) } catch { /* the next view shows it unread again */ }
  }
}

/** Move the read cursor of what the current tab shows, once per (tab, view version). */
async function autoRead($: any, view: any) {
  const tab = activeTabOf(view, await read($, tabAtom)) // the tab the pane shows, not a stale one
  const todo = unreadThreadsFor(view, tab)
  if (!todo.length) return
  const mark = `${tab}:${view.version ?? ''}`
  if ((await read($, lastReadAtom)) === mark) return
  await update($, lastReadAtom, () => mark)
  await markRead($, todo)
}

async function setTab($: any, tab: string) {
  await update($, tabAtom, () => tab)
  scrollEndLater($)
  if ((await read($, replyAtom)) !== 0) await update($, replyAtom, () => 0) // every write is a redraw: only a real one
  // the network part runs off the press: switching shows at once
  $.clock.after(0, () => { void markReadFor($, tab) })
}

async function markReadFor($: any, tab: string) {
  const view = await read($, viewAtom)
  if (view) await markRead($, unreadThreadsFor(view, tab))
}

async function setReply($: any, id: number) {
  await update($, replyAtom, () => id)
}

/** The `say` body for the open conversation and the pending reply (null: nothing to send). Shared by the panel box and /x. */
async function sayBody($: any, text: string) {
  const view = await read($, viewAtom)
  return buildSay(expandNewlines(text), activeTabOf(view, await read($, tabAtom)), await read($, replyAtom), view)
}

/** `/x <text>`: the same send as the panel's box, written in Claude's own prompt box. Answers the command's { text }. */
async function sendFromCommand($: any, raw: string): Promise<{ text: string }> {
  const text = raw.trim()
  if (!text) return { text: '用法：/x 消息内容（@名字 可以指定成员）' }
  try {
    const body = await sayBody($, text)
    if (!body) return { text: '发送失败：没有可发的内容' }
    const r = await callHub($, 'POST', '/v1/act', body)
    if (r.status !== 200) return { text: `发送失败 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 100)}` }
    await update($, replyAtom, () => 0)
    scrollEndLater($)
    const view = await read($, viewAtom)
    const tab = activeTabOf(view, await read($, tabAtom))
    const item = railOf(view).find(t => t.id === tab)
    const label = item?.kind === 'dm' ? String(item.peer ?? item.label) : '大群'
    return { text: `已发到 ${label}` }
  } catch (err) {
    return { text: `发送失败: ${errText(err)}` }
  }
}

/** `⤢ 大输入框`: the panel's draft moves into Claude's own multi-line prompt box as `/x <draft>` (Enter there sends it). */
async function openBigInput($: any) {
  try {
    const cur = await $.prompt.read()
    const plan = bigInputPlan(draftLive, String(cur?.text ?? ''))
    if (!plan.ok) { $.ui.toast('先清空 Claude 输入框里的内容'); return }
    const r = await $.prompt.fill({ text: plan.text, mode: 'replace' })
    if (r?.isFilled === false) { $.ui.toast('没能放进 Claude 输入框'); return }
    const view = await read($, viewAtom)
    const tab = activeTabOf(view, await read($, tabAtom))
    const it = railOf(view).find(t => t.id === tab)
    const label = it?.kind === 'dm' ? String(it.peer ?? it.label) : '大群'
    $.ui.toast(`已放进 Claude 输入框：Shift+Enter 换行，回车发到「${label}」`)
  } catch (err) {
    $.ui.toast(`没能放进 Claude 输入框: ${errText(err)}`)
  }
}

async function sendMsg($: any, text: string) {
  if (await read($, sendingAtom)) return // a send is in flight: ignore the repeat press
  const body = await sayBody($, text)
  if (!body) return
  await update($, sendingAtom, () => true)
  try {
    const r = await callHub($, 'POST', '/v1/act', body)
    if (r.status !== 200) {
      $.ui.toast(`发送失败 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 100)}`)
      return
    }
    await update($, replyAtom, () => 0)
    scrollEndLater($)
    draftLive = ''
    await update($, mentionAtom, () => null)
    await update($, forcedAtom, () => null)
    await update($, sendNAtom, n => n + 1) // new Input key: the box comes back empty
    refocusInput($)
  } catch (err) {
    $.ui.toast(`发送失败: ${errText(err)}`)
  } finally {
    await update($, sendingAtom, () => false)
  }
}

async function approve($: any, id: string, decision: 'once' | 'always' | 'reject', label = '') {
  if ((await read($, busyAtom))[id]) return
  await update($, busyAtom, m => ({ ...m, [id]: true }))
  try {
    const r = await callHub($, 'POST', '/v1/act', { act: 'approve', id, decision })
    if (r.status !== 200) $.ui.toast(`审批失败 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 100)}`)
    else await leaveDecision($, decision === 'reject' ? `✗ 已拒绝 ${label}` : `✓ 已批准 ${label}`, decision !== 'reject')
  } catch (err) {
    $.ui.toast(`审批失败: ${errText(err)}`)
  } finally {
    await update($, busyAtom, m => { const n = { ...m }; delete n[id]; return n })
  }
}

/** Enter in the input: with the @ list showing it picks the first member (keyboard completion), else it sends. */
async function submitInput($: any, v: string) {
  draftLive = v
  const q = trailingMention(v)
  if (q !== null) {
    const cands = mentionCandidates(await read($, viewAtom), q, 6)
    if (cands.length) { await pickMention($, String(cands[0]!.id)); return }
  }
  await sendMsg($, v)
}

/** "撤回": the hub cancels what was not delivered yet and interrupts a turn that took it; the text goes back into the input. */
async function retractMsg($: any, id: number, text: string) {
  if ((await read($, busyAtom))[`rt${id}`]) return
  await update($, busyAtom, m => ({ ...m, [`rt${id}`]: true }))
  try {
    const r = await callHub($, 'POST', '/v1/act', { act: 'retract', id })
    if (r.status !== 200) { $.ui.toast(`撤回失败 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 100)}`); return }
    const cut: string[] = Array.isArray(r.data?.canceled) ? r.data.canceled : []
    const hit: string[] = Array.isArray(r.data?.interrupted) ? r.data.interrupted : []
    const parts = [cut.length ? `${cut.map(displayName).join('、')} 还没收到` : '', hit.length ? `已打断 ${hit.map(displayName).join('、')}` : '']
      .filter(Boolean)
    $.ui.toast(`已撤回${parts.length ? '：' + parts.join('；') : '（对方可能已经读过）'}，原文放回输入框`)
    draftLive = text
    await update($, forcedAtom, () => text)
  } catch (err) {
    $.ui.toast(`撤回失败: ${errText(err)}`)
  } finally {
    await update($, busyAtom, m => { const n = { ...m }; delete n[`rt${id}`]; return n })
  }
}

/** "停止" on a working member: its queued mail is canceled and its running turn interrupted (hub act stop). */
async function stopMember($: any, id: string) {
  if ((await read($, busyAtom))[`st${id}`]) return
  await update($, busyAtom, m => ({ ...m, [`st${id}`]: true }))
  try {
    const r = await callHub($, 'POST', '/v1/act', { act: 'stop', member: id })
    if (r.status !== 200) $.ui.toast(`停止失败 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 100)}`)
    else $.ui.toast(r.data?.stopped ? `已停止 ${displayName(id)}` : `${displayName(id)} 没有在执行`)
  } catch (err) {
    $.ui.toast(`停止失败: ${errText(err)}`)
  } finally {
    await update($, busyAtom, m => { const n = { ...m }; delete n[`st${id}`]; return n })
  }
}

/**
 * "压缩" on a member. opencode: the hub compacts it in the background with its own instruction (act compact) and posts
 * a notice when done. This session's own Claude: the engine compacts it ($.session.compact), and the session.compact
 * hook below adds the hub's instruction. A press has a 10 s budget, so the Claude one runs off the press.
 */
async function compactMember($: any, id: string, self: boolean) {
  if ((await read($, busyAtom))[`cp${id}`]) return
  // the button turns into "压缩中…" at once; for opencode it stays so until the view carries the hub's own flag
  await update($, busyAtom, m => ({ ...m, [`cp${id}`]: true }))
  if (self) { $.clock.after(0, () => { void compactSelf($, id) }); return }
  let started = false
  try {
    const r = await callHub($, 'POST', '/v1/act', { act: 'compact', member: id })
    started = r.status === 200
    if (started) $.ui.toast(`${displayName(id)} 开始压缩，完成后会在私聊里通知`)
    else if (r.data?.error === 'busy') $.ui.toast(`${displayName(id)} 正在执行，等它停下再压缩`)
    else if (r.data?.error === 'unsupported') $.ui.toast(`${displayName(id)} 不支持由协作室触发压缩`)
    else if (r.data?.error === 'no_session') $.ui.toast(`${displayName(id)} 还没有会话，不需要压缩`)
    else $.ui.toast(`压缩失败 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 100)}`)
  } catch (err) {
    $.ui.toast(`压缩失败: ${errText(err)}`)
  } finally {
    if (started) $.clock.after(15_000, () => { void unbusy($, `cp${id}`) }) // by then the view shows compacting/compacted
    else await unbusy($, `cp${id}`)
  }
}

/** A view that carries a member's compacting flag takes over from the button's own "压缩中…". */
async function settleBusy($: any, view: any) {
  const busy = await read($, busyAtom)
  for (const m of membersOf(view)) if (m.compacting && busy[`cp${m.id}`]) await unbusy($, `cp${m.id}`)
}

async function unbusy($: any, key: string) {
  await update($, busyAtom, m => { const n = { ...m }; delete n[key]; return n })
}

async function compactSelf($: any, id: string) {
  await update($, busyAtom, m => ({ ...m, [`cp${id}`]: true }))
  try {
    const r = await $.session.compact({})
    if (r?.skip) $.ui.toast(`没有压缩：${String(r.skip).slice(0, 100)}`)
    else {
      const k = (n: unknown) => ctxText(n) || '?'
      $.ui.toast(r?.tokensBefore ? `已压缩：${k(r.tokensBefore)} → ${k(r.tokensAfter)}` : '已压缩')
    }
  } catch (err) {
    $.ui.toast(`压缩失败: ${errText(err)}`)
  } finally {
    await update($, busyAtom, m => { const n = { ...m }; delete n[`cp${id}`]; return n })
  }
}

/**
 * Any compaction of this session's main conversation (/compact, the engine's auto one, the panel button): the hub's
 * instruction goes to the summarizer after the person's own text. Whatever fails, the compaction goes on unchanged.
 */
async function compactHook($: any, e: any, next: any) {
  if (e.agentId || e.trigger === 'precompute') return next(e)
  let hub = ''
  try {
    // at most 5 s in all (room lookup included): a hub that does not answer must not hold the compaction up
    const r: any = await Promise.race([
      (async () => {
        const stored = (await $.store.get(connKey(await roomDirFor($)))) as HubConn | undefined
        if (!stored?.member) return null
        return callHub($, 'GET', `/v1/compact_instructions?member=${encodeURIComponent(stored.member)}`)
      })(),
      $.clock.sleep(5000).then(() => null),
    ])
    if (r?.status === 200 && typeof r.data?.text === 'string') hub = r.data.text
  } catch { /* no hub: the engine's own prompt alone */ }
  if (!hub) return next(e)
  return next({ ...e, instructions: mergeCompactInstructions(e.instructions, hub) })
}

/** The member card's model button: opens (or closes) the picker with what the hub offers for that member. */
async function toggleModelPicker($: any, id: string) {
  if ((await read($, modelAtom))?.member === id) { await update($, modelAtom, () => null); return }
  await update($, modelAtom, () => ({ member: id, current: '', options: [], format: '', note: '', loading: true, error: '' }))
  try {
    const r = await callHub($, 'POST', '/v1/act', { act: 'models', member: id })
    if ((await read($, modelAtom))?.member !== id) return // closed or switched meanwhile
    if (r.status !== 200) {
      await update($, modelAtom, m => m && { ...m, loading: false, error: `读取失败 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 100)}` })
      return
    }
    await update($, modelAtom, () => ({ member: id, current: String(r.data?.current ?? ''), options: Array.isArray(r.data?.options) ? r.data.options : [],
      format: String(r.data?.format ?? ''), note: String(r.data?.note ?? ''), loading: false, error: '' }))
  } catch (err) {
    await update($, modelAtom, m => m && { ...m, loading: false, error: `读取失败: ${errText(err)}` })
  }
}

/** A model picked (or typed): member_edit, which the member's next turn uses. */
async function setModel($: any, id: string, model: string) {
  const name = model.trim()
  const cur = await read($, modelAtom)
  if (!name || (await read($, busyAtom))[`md${id}`]) return
  if (cur && name === cur.current) { await update($, modelAtom, () => null); return }
  await update($, busyAtom, m => ({ ...m, [`md${id}`]: true }))
  try {
    const r = await callHub($, 'POST', '/v1/act', { act: 'member_edit', member: id, model: name })
    if (r.status !== 200) {
      await update($, modelAtom, m => m && { ...m, error: `没有换成：${String(r.data?.message ?? r.data?.error ?? r.status).slice(0, 120)}` })
      return
    }
    $.ui.toast(`${displayName(id)} 换成 ${name}，下一轮起生效`)
    await update($, modelAtom, () => null)
  } catch (err) {
    await update($, modelAtom, m => m && { ...m, error: `没有换成：${errText(err)}` })
  } finally {
    await unbusy($, `md${id}`)
  }
}

const OLDER_MAX_PAGES = 10 // one press fetches up to this many pages while they show nothing but folded notices

/**
 * Older history from /v1/timeline. A page that the panel would fold entirely into notice rows (the same buildRows the
 * draw uses, for the open tab) shows the person nothing new, so the next page is fetched too, up to OLDER_MAX_PAGES.
 * The atom is written once at the end: one redraw, the button reads "加载中…" meanwhile.
 */
async function loadOlder($: any) {
  const cur = await read($, olderAtom)
  if (cur.loading) return
  const view = await read($, viewAtom)
  const ids = [...cur.items, ...seenMsgs.values(), ...(Array.isArray(view?.timeline) ? view.timeline : [])].map((m: any) => m?.id).filter((x: any) => typeof x === 'number')
  if (!ids.length) return
  await update($, olderAtom, o => ({ ...o, loading: true }))
  try {
    const activeTab = activeTabOf(view, await read($, tabAtom))
    let before = Math.min(...ids)
    let got: any[] = []
    let hasMore = true
    let pages = 0
    let shows = false
    while (pages < OLDER_MAX_PAGES && hasMore && !shows) {
      const r = await callHub($, 'GET', `/v1/timeline?before=${before}&limit=${OLDER_PAGE}`)
      if (r.status !== 200) {
        $.ui.toast(`加载失败 ${r.status}`)
        if (!got.length) { await update($, olderAtom, o => ({ ...o, loading: false })); return }
        break
      }
      pages++
      const items: any[] = Array.isArray(r.data?.items) ? r.data.items : []
      got = [...items, ...got]
      hasMore = !!r.data?.has_more && items.length > 0
      const ids2 = items.map((m: any) => m?.id).filter((x: any) => typeof x === 'number')
      if (ids2.length) before = Math.min(before, ...ids2)
      shows = buildRows(messagesFor({ ...view, timeline: items }, activeTab, POOL).reverse()).some(row => row.kind !== 'noise')
    }
    if (!shows && hasMore && pages >= OLDER_MAX_PAGES) $.ui.toast(`更早的 ${pages * OLDER_PAGE} 条都是通知，已折叠；再点继续`)
    await update($, olderAtom, o => ({ items: [...got, ...o.items], hasMore, loading: false }))
    const more = messagesFor({ ...view, timeline: got }, activeTab, POOL).length // what was fetched for this conversation shows
    if (more) await update($, shownAtom, m => ({ ...m, [activeTab]: (m[activeTab] ?? SHOW_STEP) + more }))
  } catch (err) {
    $.ui.toast(`加载失败: ${errText(err)}`)
    await update($, olderAtom, o => ({ ...o, loading: false }))
  }
}

/** "显示更早的": the next SHOW_STEP messages of the open conversation that are already here (no hub call). */
async function showMore($: any, tab: string) {
  await update($, shownAtom, m => ({ ...m, [tab]: (m[tab] ?? SHOW_STEP) + SHOW_STEP }))
}

/** A member chip pressed: its full card opens (one at a time); pressing the open one closes it. */
async function toggleExpand($: any, id: string) {
  await update($, expandedAtom, v => (v === id ? '' : id))
}

/**
 * The member menu's 暂停 / 恢复 / 移出 (hub acts pause, resume, remove). 移出 takes two presses: the first turns the
 * button into "确认移出", the second removes (the member's history stays; its token stops working).
 */
async function memberAct($: any, id: string, act: 'pause' | 'resume' | 'remove') {
  const busy = await read($, busyAtom)
  if (busy[`ma${id}`]) return
  if (act === 'remove' && !busy[`rmq${id}`]) {
    await update($, busyAtom, m => ({ ...m, [`rmq${id}`]: true }))
    return
  }
  await update($, busyAtom, m => ({ ...m, [`ma${id}`]: true }))
  const label = act === 'pause' ? '暂停' : act === 'resume' ? '恢复' : '移出'
  try {
    const r = await callHub($, 'POST', '/v1/act', { act, member: id })
    if (r.status !== 200) $.ui.toast(`${label}失败 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 100)}`)
    else {
      $.ui.toast(`已${label} ${displayName(id)}`)
      if (act === 'remove') { await update($, tabAtom, () => '#room'); await update($, expandedAtom, () => '') }
    }
  } catch (err) {
    $.ui.toast(`${label}失败: ${errText(err)}`)
  } finally {
    await update($, busyAtom, m => { const n = { ...m }; delete n[`ma${id}`]; delete n[`rmq${id}`]; return n })
  }
}

async function toggleAddOpen($: any) {
  await update($, addOpenAtom, v => !v)
}

async function addMember($: any, vendor: string) {
  if ((await read($, busyAtom))['add']) return
  await update($, busyAtom, m => ({ ...m, add: true }))
  try {
    const r = await callHub($, 'POST', '/v1/act', { act: 'member_add', vendor }) // name and model: the hub's defaults
    if (r.status !== 200) {
      $.ui.toast(`添加失败 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 100)}`)
      return
    }
    $.ui.toast(`已添加 ${String(r.data?.member_id ?? vendor)}`)
    await update($, addOpenAtom, () => false)
  } catch (err) {
    $.ui.toast(`添加失败: ${errText(err)}`)
  } finally {
    await update($, busyAtom, m => { const n = { ...m }; delete n.add; return n })
  }
}

// ---- status line, working-strip clock, waking Claude ---------------------------------------------------------

async function pendingForMe($: any, view: any): Promise<number> {
  const seen = await $.store.get(STORE_SEEN)
  return wakeCandidates(view, typeof seen === 'number' ? seen : maxWakeId(view)).length
}

let lastStatus: string | null = null // the status line as last set: set again only when its text changes

async function refreshStatus($: any, view: any) {
  const line = summaryLine(view, await pendingForMe($, view), (await $.store.get(STORE_AUTO)) === true)
  if (line === lastStatus) return
  lastStatus = line
  $.ui.status(line)
}

/** Messages for the panel newer than the handled mark: submit one turn for all of them (auto on, or `force`). */
async function wakeCheck($: any, view: any, force: boolean) {
  let seen = await $.store.get(STORE_SEEN)
  if (typeof seen !== 'number') { // first sight: what is already there is history, not a wake-up
    seen = maxWakeId(view)
    await $.store.set(STORE_SEEN, seen)
  }
  const pend = wakeCandidates(view, seen)
  if (!pend.length) return
  if (!force && (await $.store.get(STORE_AUTO)) !== true) return
  const top = pend.reduce((n, m) => Math.max(n, m.id), seen)
  await $.store.set(STORE_SEEN, top) // mark first so a second view cannot submit the same ones
  $.prompt.submit({ text: buildWakePrompt(pend) }).catch(async (err: unknown) => {
    await $.store.set(STORE_SEEN, seen) // not taken: they count as pending again
    $.ui.toast(`叫醒 Claude 失败: ${errText(err)}`)
  })
}

async function wakeNow($: any) {
  if ((await read($, busyAtom)).wake) return
  await update($, busyAtom, m => ({ ...m, wake: true }))
  try {
    const view = await read($, viewAtom)
    if (view) { await wakeCheck($, view, true); await refreshStatus($, view) }
  } finally {
    await unbusy($, 'wake')
  }
}

async function toggleAuto($: any) {
  const on = (await $.store.get(STORE_AUTO)) === true
  await $.store.set(STORE_AUTO, !on)
  const view = await read($, viewAtom)
  if (view && !on) await wakeCheck($, view, false)
  if (view) await refreshStatus($, view)
}

async function promote($: any, id: number) {
  if ((await read($, busyAtom))[`pr${id}`]) return
  await update($, busyAtom, m => ({ ...m, [`pr${id}`]: true }))
  try {
    const r = await callHub($, 'POST', '/v1/act', { act: 'promote', message_id: id })
    if (r.status !== 200) {
      $.ui.toast(`设为决定失败 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 100)}`)
      return
    }
    const entry = String(r.data?.entry ?? '已设')
    await update($, promotedAtom, m => ({ ...m, [String(id)]: entry }))
  } catch (err) {
    $.ui.toast(`设为决定失败: ${errText(err)}`)
  } finally {
    await unbusy($, `pr${id}`)
  }
}

/** The model's xmuse_send tool: one `say` through the panel's own token. Answers { result } or { deny }. */
/** Claude speaks as its own member (member token, /v1/tools/xmuse_send), never as the user (the operator token). */
async function callAsMember($: any, args: Record<string, unknown>): Promise<{ status: number; data: any }> {
  for (let attempt = 0; attempt < 2; attempt++) {
    const conn = await getConn($)
    if (!conn.memberToken) { await clearConn($, conn.dir ?? await roomDirFor($)); if (attempt === 0) continue; throw new Error('没有成员令牌（重新加入后仍缺）') }
    const r = await $.http.fetch(`${conn.url}/v1/tools/xmuse_send`, {
      method: 'POST',
      // the member is bound to this session (ensureBound): a bound member's tool calls name it
      headers: { authorization: `Bearer ${conn.memberToken}`, 'content-type': 'application/json',
        ...(conn.sid ? { 'x-xmuse-session': conn.sid } : {}) },
      body: JSON.stringify({ args }), // the hub's tool route reads body.args
    })
    if (r.status === 401 && attempt === 0) { await clearConn($, conn.dir ?? await roomDirFor($)); continue }
    let data: any = null
    try { data = r.text ? JSON.parse(r.text) : null } catch { /* not JSON */ }
    return { status: r.status, data }
  }
  throw new Error('成员令牌失效，重新加入后仍是 401')
}

async function sendTool($: any, e: any): Promise<any> {
  const view = await read($, viewAtom)
  const built = sendPayload(e, view)
  if ('deny' in built) return built
  try {
    const r = await callAsMember($, built.args)
    return sendOutcome(r, String(built.args.to))
  } catch (err) {
    return { deny: `发送失败: ${errText(err)}` }
  }
}

async function registerTool($: any) {
  try {
    await $.tool.register({
      name: TOOL,
      description: '通过 xmuse 协作室发消息给其他助手或用户（以本会话成员身份）。to 填 "#room"、群 id 或成员 id；回复某条消息时带 reply_to。kind 可为 message、handoff、review_request、decision、assumption、question：交接用 kind=handoff 并带 why；决定/假设/问题用对应 kind 并可带 scope、supersedes、resolves。',
      isDeferred: false,
      inputSchema: {
        type: 'object',
        properties: {
          to: { type: 'string', description: '"#room"、群 id 或成员 id' },
          body: { type: 'string', description: '消息正文' },
          mentions: { type: 'array', items: { type: 'string' }, description: '要 @ 的成员 id；省略时按正文里的 @名字 自动识别' },
          reply_to: { type: 'number', description: '回复的消息 id' },
          kind: { type: 'string', enum: ['message', 'handoff', 'review_request', 'decision', 'assumption', 'question'], description: '默认 message' },
          scope: { type: 'string', description: '决定/假设/问题的生效范围' },
          supersedes: { type: 'string', description: '被取代的条目 id（如 E7）' },
          resolves: { type: 'array', items: { type: 'string' }, description: '解决的问题/分派 id' },
          depends_on: { type: 'array', items: { type: 'string' }, description: '依赖的条目 id（仅 handoff）' },
          notify: { type: 'string', enum: ['batch', 'now'], description: 'host 交接的回执方式' },
          members: { type: 'array', items: { type: 'string' }, description: '新建私群时的成员' },
          why: { type: 'object', description: 'Why-First 交接（kind=handoff 时必填）',
                 properties: { what: { type: 'string' }, why: { type: 'string' }, tradeoff: { type: 'string' },
                               open_questions: { type: 'string' }, next_action: { type: 'string' } } },
        },
        required: ['to', 'body'],
      },
    })
  } catch { /* the model just does not get the tool; the panel still works */ }
  try {
    await $.tool.register({
      name: TOOL_BRIEF,
      description: '把项目简介（目标、技术栈、约定，200 字内）保存到 xmuse 协作室；新加入的助手会在入场包里读到它。',
      isDeferred: false,
      inputSchema: {
        type: 'object',
        properties: { text: { type: 'string', description: '项目简介正文' } },
        required: ['text'],
      },
    })
  } catch { /* no brief tool: the user writes it by hand */ }
}

async function openPanel($: any) {
  let title = 'xmuse'
  try {
    const base = (await roomTarget($)).split('/').filter(Boolean).pop()
    if (base) title = `xmuse · ${base}`
  } catch { /* plain title */ }
  try { await $.ui.open({ id: PANE, title }) } catch { /* not placeable now; /xmuse retries */ }
}

// ---- theme, avatars, copy, draft, toasts ---------------------------------------------------------------------

/** The `theme` row of /config decides the palette; read at start, after each view and on config.set. */
let themeAt = -Infinity // host clock of the last look at the theme: polls look at most every THEME_EVERY_MS
const THEME_EVERY_MS = 30_000

async function refreshTheme($: any, force = false) {
  const now = await $.clock.now()
  if (!force && now - themeAt < THEME_EVERY_MS) return
  themeAt = now
  try {
    const rows = await $.config.list()
    const row = rows.find((r: any) => r.key === 'theme')
    const light = isLightTheme(row?.value)
    if (light !== (await read($, themeAtom))) await update($, themeAtom, () => light)
  } catch { /* keep the current palette */ }
}

// the names a vendor's avatar file may go by besides its key (people name them after the product or the CLI)
const AVATAR_ALIASES: Record<string, string[]> = { google: ['gemini', 'agy', 'antigravity'], deepseek: ['dsh'], opencode: [], claude: [] }
const AVATAR_MAX_B64 = 90_000 // the PNG goes into the Svg source (at most 131072 characters): about 67 KB of file

/**
 * Custom avatars: <dir>/<member id>.png, else the vendor's: <key>.png or one of its aliases (gemini.png, dsh.png...).
 * Each is looked up once per load; the Svg embeds the PNG. A file too big to embed is said once, with its size.
 */
async function loadAvatars($: any, view: any) {
  let changed = false
  let dir = DEV_AVATAR_DIR
  if (!DEV) { try { dir = `${(await hubSetup($)).stateDir}/avatars` } catch { return } }
  const list: any[] = Array.isArray(view?.members) ? view.members : []
  const tries: [string, string[]][] = []
  for (const m of list) {
    tries.push([String(m.id), [String(m.id)]])
    const vk = vendorKey(String(m.id), m.vendor)
    if (vk) tries.push(['v:' + vk, [vk, ...(AVATAR_ALIASES[vk] ?? [])]])
  }
  tries.push(['human', ['human']])
  const tooBig: string[] = []
  for (const [key, files] of tries) {
    if (avatarTried[key]) continue
    avatarTried[key] = true
    for (const file of files) {
      try {
        const r = await $.fs.read(`${dir}/${file}.png`, { as: 'bytes' })
        const b64 = String(r?.base64 ?? '')
        if (!b64) continue
        if (b64.length >= AVATAR_MAX_B64) { tooBig.push(`${file}.png（${Math.round((b64.length * 3) / 4 / 1024)}KB）`); continue }
        avatarImgs[key] = `data:image/png;base64,${b64}`
        changed = true
        break
      } catch { /* no such file: the next name, else the drawn logo stays */ }
    }
  }
  if (tooBig.length) $.ui.toast(`头像太大没有用上：${tooBig.join('、')}，请缩到 60KB 以内（如 96×96）`)
  if (changed) await update($, avatarVerAtom, n => n + 1)
}

async function copyText($: any, text: string, surface: any) {
  try {
    const r = await $.ui.copy({ text, surface })
    $.ui.toast(r.isCopied ? '已复制' : `复制失败（${r.reason}）`)
  } catch (err) {
    $.ui.toast(`复制失败: ${errText(err)}`)
  }
}

/** A line under the approval cards for 8 seconds after a decision. */
async function leaveDecision($: any, text: string, ok: boolean) {
  const n = ++decisionN
  await update($, decisionAtom, () => ({ id: n, text, ok }))
  $.clock.after(8000, () => { void clearDecision($, n) })
}

async function clearDecision($: any, n: number) {
  if ((await read($, decisionAtom)).id === n) await update($, decisionAtom, () => ({ id: n, text: '', ok: true }))
}

/** onInput: remember the text; redraw only when the trailing @word changes (that shows or hides the member list). */
async function inputChanged($: any, v: string) {
  draftLive = v
  const q = trailingMention(v)
  if (q !== (await read($, mentionAtom))) await update($, mentionAtom, () => q)
}

/**
 * A member picked from the @ list: the trailing @word becomes "@id " (completeMention ends with one space). The Input is
 * remounted (new key via inputGen) and refocused: a freshly mounted field puts the caret at the end of its text, whereas a
 * new `value` on the same field would leave the caret where it was ("@op|encode").
 */
async function pickMention($: any, id: string) {
  draftLive = completeMention(draftLive, id)
  await update($, forcedAtom, () => draftLive)
  await update($, inputGenAtom, n => n + 1)
  await update($, mentionAtom, () => null)
  refocusInput($) // the remounted field has no focus yet
}

/**
 * After a send the Input takes a new key (that is what empties it), and a fresh field has no focus: put the ring
 * back on it. Off the handler (the engine awaits the new element); a refusal changes nothing. DEV: the answer is
 * written next to the load mark, to see what the surface does with it.
 */
function refocusInput($: any) {
  $.clock.after(0, () => { void focusInput($) })
}

async function focusInput($: any) {
  let res: unknown
  try { res = await $.ui.focus({ requestId: PANE, key: `xm-in-${await read($, sendNAtom)}-${await read($, inputGenAtom)}` }) } catch (err) { res = errText(err) }
  if (DEV) { try { await $.fs.write(FOCUS_MARK, `${new Date().toISOString()} ${JSON.stringify(res)}\n`) } catch { /* diagnostics only */ } }
}

/** One toast for a new approval, a member that paused, or a message for Claude (not for what was there at the first view). */
async function toastNew($: any, view: any) {
  const items: [string, string][] = []
  for (const a of approvalsOf(view)) items.push([`ap:${a.id}`, `新审批：${displayName(a.member)} 请求${approvalKindLabel(a.kind)}`])
  for (const m of membersOf(view)) if (m.paused || m.status === 'paused') items.push([`pz:${m.id}`, `${m.id} 已暂停`])
  if ((await $.store.get(STORE_AUTO)) !== true) {
    for (const m of wakeCandidates(view, 0)) items.push([`fm:${m.id}`, `${displayName(m.from)} 给 Claude 发了消息`])
  }
  const fresh = items.filter(([k]) => !toastSeen.has(k))
  for (const [k] of items) toastSeen.add(k)
  if (!toastSeeded) { toastSeeded = true; return }
  if (fresh.length) $.ui.toast(fresh.slice(0, 2).map(x => x[1]).join('；') + (fresh.length > 2 ? ` 等 ${fresh.length} 件` : ''))
}

// ---- drawing -------------------------------------------------------------------------------------------------

function avatar(ui: any, id: string, size: number, look: Look) {
  const v = look.vend[id]
  const img = avatarImgs[id] ?? avatarImgs['v:' + vendorKey(id, v)] ?? ''
  return <ui.Svg source={avatarSvg(id, size, v, look.badges[id] ?? '', img)} alt={displayName(id)} width={size} height={size} />
}

type Look = { light: boolean; pal: Pal; vend: Record<string, string>; badges: Record<string, string> }

async function toggleFold($: any, key: string) {
  await update($, foldAtom, m => ({ ...m, [key]: !m[key] }))
}

let drawStage = '' // the last step drawPanel reached (shown when a draw throws or does not settle)

async function drawPanel($: any, e: any) {
  drawStage = 'resolve'
  const ui = $.ui.resolve(e) as any
  const { Box, Text, Button, Input, Markdown, Code, Select, Client } = ui
  const desk = e?.surface === 'desktop'
  // a shrinkable one-line text part of a row; `shrink` 0 keeps it whole (a short name), `grow` takes the free room
  const cut = (key: string, text: string, tp: Record<string, unknown> = {}, o: { grow?: boolean; shrink?: number } = {}) => (
    <Box key={key} flexGrow={o.grow ? 1 : 0} flexShrink={o.shrink ?? 1} minWidth={0} overflow="hidden"><Text wrap="truncate-end" {...tp}>{text}</Text></Box>
  )
  // a part of a row that never shrinks (a time, an icon, a button, a Client)
  const fix = (key: string, node: any) => <Box key={key} flexShrink={0}>{node}</Box>
  // a member name: whole when short, truncated when long
  const nameShrink = (id: string) => (displayName(id).length > 14 ? 1 : 0)
  // the pane's own width in cells (a code-font advance each, about 7 px; absent before the first layout: then wide).
  // Not viewport.columns: beside a docked pane that is the transcript's column, which widens as the pane narrows.
  const cols = Number(e?.props?.bodyColumns ?? e?.viewport?.columns ?? 0)
  const narrow = cols > 0 && cols < NARROW_COLS
  // the conversation list is always vertical beside the main column; it narrows with the pane and goes compact (one row per entry)
  const railFold = (await read($, railFoldAtom)) === true // folded by hand to avatars only
  const railW = railFold ? RAIL_FOLD_COLS : cols > 0 ? Math.max(12, Math.min(RAIL_COLS, Math.round(cols * 0.24))) : RAIL_COLS
  const railCompact = railW < 17
  const bodyRows = Number(e?.props?.scroll?.bodyRows ?? e?.viewport?.rows ?? 0)
  drawStage = 'read view'
  // every value the draw reads, at once: one round trip to the host instead of one per value (a draw ran ~30 in a row)
  const [view, conn, tab, replyTo, promoted, done, fold, light, _avatarVer, open, briefFlag, briefStored, older, nowMs, sendN, sending, addOpen, expanded, busy, decision, mq, forced, autoStored, seenRaw, selfCtx, reveal, mp, shown, probeOn, sp, layout, inputGen] = await Promise.all([
    read($, viewAtom),
    read($, connAtom),
    read($, tabAtom),
    read($, replyAtom),
    read($, promotedAtom),
    read($, doneAtom),
    read($, foldAtom),
    read($, themeAtom),
    read($, avatarVerAtom),
    read($, openAtom),
    read($, briefAtom),
    $.store.get(STORE_BRIEF),
    read($, olderAtom),
    $.clock.now(),
    read($, sendNAtom),
    read($, sendingAtom),
    read($, addOpenAtom),
    read($, expandedAtom),
    read($, busyAtom),
    read($, decisionAtom),
    read($, mentionAtom),
    read($, forcedAtom),
    $.store.get(STORE_AUTO),
    $.store.get(STORE_SEEN),
    read($, selfCtxAtom),
    read($, revealAtom),
    read($, modelAtom),
    read($, shownAtom),
    read($, probeAtom),
    read($, scrollProbeAtom),
    read($, layoutAtom),
    read($, inputGenAtom),
  ])
  const chat = layout !== 'flow' // chat order (newest at the bottom); 'flow' draws the newest first
  drawStage = 'read state'
  const pal = palOf(light)

  drawStage = 'store brief'
  const briefMissing = briefFlag || briefStored === true
  const noRoom = conn.phase === 'noroom'
  drawStage = 'room target'
  const target = noRoom ? await roomTarget($) : ''
  drawStage = `build (view ${view ? 'yes' : 'no'}, conn ${conn.phase})`
  // "no room here yet" with the button, the progress of opening it, or why it failed
  const roomBar = (noRoom || open.busy || open.error) ? (
    <Box flexDirection="column" gap={1}>
      {noRoom ? <Text>这个目录还没有 xmuse 房间{conn.error ? `（${conn.error}）` : ''}</Text> : null}
      {open.busy ? <Text color={C_AMBER}>… {open.msg}</Text> : null}
      {open.error ? <Text color={C_RED}>⚠ 开房间失败：{open.error}</Text> : null}
      {noRoom && !open.busy ? (
        <Box flexDirection="column" gap={1}>
          <Text dimColor>{`将在 ${target} 开房间：会在该目录写入 .xmuse.json、AGENTS.md 和技能目录，并在 CLAUDE.md 末尾加一行 @AGENTS.md。`}</Text>
          <Button key="open-room" variant="primary" onPress={() => openRoomLater($)}>确认在此目录开房间</Button>
        </Box>
      ) : null}
    </Box>
  ) : null

  // X1: cannot connect: a red card with the reason and a primary retry
  const errorCard = conn.phase === 'error' ? (
    <Box flexDirection="column" borderStyle="round" borderColor={C_RED} paddingX={1}>
      <Text color={C_RED}>连不上 hub</Text>
      <Text wrap="truncate-end">{conn.error}</Text>
      <Text dimColor>hub 没启动？点"启动 hub"，或在别处启动后点重试；也会自动重试。</Text>
      <Box flexDirection="row" gap={1}>
        <Button key="retry" variant="primary" onPress={() => startLoop($)}>重试</Button>
        <Button key="start-hub" variant="secondary" onPress={() => startHubLater($)}>启动 hub</Button>
      </Box>
    </Box>
  ) : null

  if (!view) {
    return (
      <Box flexDirection="column" gap={1}>
        <Text bold>xmuse</Text>
        {noRoom ? roomBar : (
          <Box flexDirection="column" gap={1}>
            {roomBar}
            {errorCard}
            {conn.phase === 'connecting' ? <Text dimColor>正在连接 hub…</Text> : null}
            {conn.phase !== 'error' && conn.phase !== 'connecting' ? (
              <Box flexDirection="row" gap={1} alignItems="center">
                <Text dimColor>未连接</Text>
                <Button key="retry" onPress={() => startLoop($)}>重试</Button>
              </Box>
            ) : null}
          </Box>
        )}
      </Box>
    )
  }

  const rawMembers: any[] = Array.isArray(view.members) ? view.members : []
  const look: Look = { light, pal, vend: {}, badges: {} }
  for (const m of rawMembers) {
    look.vend[m.id] = String(m.vendor ?? '')
    look.badges[m.id] = badgeOf(m.id, m.vendor, rawMembers)
  }
  const nc = (id: string) => memberColor(id, look.vend[id], light)

  const members = membersOf(view)
  const hostId: string = view.room?.host ?? ''
  const meId: string = view.me?.id ?? ''
  const rail = railOf(view)
  const activeTab = activeTabOf(view, tab)
  const activeItem = rail.find(t => t.id === activeTab)!
  const peerOf = activeItem.peer
  // the view's recent page plus any older pages loaded with the button at the bottom
  // (the view carries only the latest page, so every message seen is kept: one that slid out of the page stays)
  if (seenRoom !== String(view.room?.id ?? '')) { seenRoom = String(view.room?.id ?? ''); seenMsgs.clear() }
  for (const m of older.items) if (typeof m?.id === 'number' && !seenMsgs.has(m.id)) seenMsgs.set(m.id, m)
  for (const m of (Array.isArray(view.timeline) ? view.timeline : [])) if (typeof m?.id === 'number') seenMsgs.set(m.id, m)
  const histView = { ...view, timeline: [...seenMsgs.values()].sort((a, b) => a.id - b.id) }
  const hasOlder = older.items.length ? older.hasMore : !!view.timeline_cursor?.has_more
  const tabMsgs = messagesFor(histView, activeTab, POOL).reverse() // newest first (see the layout note below)
  const msgs = tabMsgs.slice(0, shown[activeTab] ?? SHOW_STEP) // only these are built: a long history costs nothing per draw
  const hiddenHere = tabMsgs.length - msgs.length
  const rows = buildRows(msgs)
  const replied = tabMsgs.find(m => m.id === replyTo)
  const replySnip = replied ? `${displayName(replied.from)}：${String(replied.text ?? '').replace(/\s+/g, ' ').slice(0, 40)}` : ''
  const activeLabel = activeItem.kind === 'room' ? '全员' : activeItem.kind === 'all' ? '全员（大群）' : activeItem.label
  const placeholder = narrow ? '说点什么' : '说点什么，@ 指定成员'
  const probeLine = probeOn
    ? `探针 · 滚动事件 ${sp.n ? `${sp.n}（by ${sp.by}，窗口 ${sp.bodyRows}/${sp.contentRows} 行，来源 ${sp.origin}）` : '未收到'} · 横幅绘制 ${bandDraws} 次`
    : ''
  const approvals = approvalsOf(view)
  const working = workingMembers(view)
  const autoWake = autoStored === true
  const wakePending = wakeCandidates(view, typeof seenRaw === 'number' ? seenRaw : maxWakeId(view)).length
  const stale = conn.phase === 'error' // the view is old: no live-looking states
  const cands = mq !== null ? mentionCandidates(view, mq, 6) : []
  const cpBusy = (id: string) => !!busy[`cp${id}`]

  // one message: optional header, bubble, hover actions. `head` false = continuation inside a group
  const unit = (m: any, head: boolean) => {
    const from = m.from ?? '?'
    const mine = from === 'human'
    if (m.retracted) {
      return (
        <Box key={`m-${m.id}`} flexDirection="row" justifyContent="center">
          <Text dimColor>{`${mine ? '你' : displayName(from)}撤回了一条消息 · ${fmtClock(m.at)}`}</Text>
        </Box>
      )
    }
    const toMe = isToClaude(m, meId)
    const decided = promoted[String(m.id)]
    const full = String(m.text ?? '')
    const expanded = !!fold[`l${m.id}`]
    // just arrived: a grow Client draws its prefix and a caret until the reveal reaches the end, then reports back
    const growing = reveal.run > 0 && reveal.id === m.id && reveal.steps.length > 0
    const folded = expanded || growing ? null : foldLong(full)
    const longOpen = expanded && foldLong(full) !== null
    const blocks = growing ? [] : splitBlocks(folded ? folded.text : full)
    const quote = m.reply_to ? replyLabel(view, m.reply_to) : ''
    const bg = mine ? pal.mine : toMe ? pal.toClaude : pal.bubble
    const bd = mine ? pal.mineBorder : toMe ? C_ORANGE : mixHex(pal.bubbleBorder, nc(from), 0.35)
    const actions = (
      <Box flexDirection="row" gap={1} flexShrink={0}>
        {head ? null : <Text dimColor>{fmtClock(m.at)}</Text>}
        <Button key={`re-${m.id}`} plain onPress={() => setReply($, m.id)}>回复</Button>
        {decided ? null : <Button key={`pr-${m.id}`} plain onPress={() => promote($, m.id)}>{busy[`pr${m.id}`] ? '处理中…' : narrow ? '决定' : '设为决定'}</Button>}
        <Button key={`cp-${m.id}`} plain onPress={(p: any) => copyText($, full, p?.surface)}>复制</Button>
        {mine ? <Button key={`rt-${m.id}`} plain hover={{ color: C_RED }} onPress={() => retractMsg($, m.id, full)}>{busy[`rt${m.id}`] ? '撤回中…' : '撤回'}</Button> : null}
      </Box>
    )
    // actions sit in the flow, never over other text (an absolute overlay covered the header and lost clicks):
    // in the header row of a first message, in a row of their own above a continuation; shown while hovered
    const hoverActs = HOVER_ACTIONS
      ? <Box display="none" hover={{ display: 'flex' }} flexDirection="row">{actions}</Box>
      : actions
    const overlay = head ? null : (
      <Box flexDirection="row" justifyContent={mine ? 'flex-end' : 'flex-start'}>{hoverActs}</Box>
    )
    const bubble = (
      <Box backgroundColor={bg} borderStyle="round" borderColor={desk && !toMe ? bg : bd} paddingX={1} flexDirection="column" minWidth={0}>
        {quote ? <Text dimColor wrap="truncate-end">{quote}</Text> : null}
        {blocks.map((b, i) => b.kind === 'diff'
          ? <Code key={`cd-${m.id}-${i}`} source={b.text} format="diff" />
          : <Markdown key={`md-${m.id}-${i}`} text={hardBreaks(softWrap(b.text))} />)}
        {growing ? (
          <Client key={`gr-m-${m.id}`} module="./grow.tsx"
            props={{ id: `r:${m.id}:${reveal.run}`, text: full, from: 0, stepMs: REVEAL_STEP_MS, steps: reveal.steps, mode: 'md' }} />
        ) : null}
        {folded ? (
          <Box flexDirection="row"><Button key={`lg-${m.id}`} plain dimColor onPress={() => toggleFold($, `l${m.id}`)}>{`展开 (+${folded.hidden} 行)`}</Button></Box>
        ) : null}
        {longOpen ? (
          <Box flexDirection="row"><Button key={`lg-${m.id}`} plain dimColor onPress={() => toggleFold($, `l${m.id}`)}>收起</Button></Box>
        ) : null}
      </Box>
    )
    if (mine) {
      return (
        <Box key={`m-${m.id}`} flexDirection="row" justifyContent="flex-end" marginLeft={narrow ? 4 : 8}>
          <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0}>
            {head ? (
              <Box flexDirection="row" gap={1} justifyContent="flex-end" alignItems="center" minWidth={0}>
                {hoverActs}
                {decided ? fix(`dc-${m.id}`, <Text color={C_AMBER}>{`◆ ${clip(decided, 12)}`}</Text>) : null}
                {cut(`to-${m.id}`, `你 → ${toLabel(m)}`, { dimColor: true })}
                {fix(`at-${m.id}`, <Text dimColor>{fmtClock(m.at)}</Text>)}
              </Box>
            ) : decided ? <Text color={C_AMBER}>{`◆ 已决定 ${decided}`}</Text> : null}
            {overlay}
            {bubble}
          </Box>
        </Box>
      )
    }
    const header = head ? (
      <Box flexDirection="row" gap={1} alignItems="center" minWidth={0}>
        {cut(`nm-${m.id}`, displayName(from), { bold: true, color: nc(from) }, { shrink: nameShrink(from) })}
        {isAutoForward(m) ? fix(`af-${m.id}`, <Text dimColor>自动转发</Text>) : null}
        {cut(`to-${m.id}`, `→ ${toLabel(m)}`, { color: toMe ? C_ORANGE : undefined, dimColor: !toMe })}
        {fix(`at-${m.id}`, <Text dimColor>{fmtClock(m.at)}</Text>)}
        {decided ? fix(`dc-${m.id}`, <Text color={C_AMBER}>{`◆ ${clip(decided, 12)}`}</Text>) : null}
        <Box flexGrow={1} />
        {hoverActs}
      </Box>
    ) : decided ? <Text color={C_AMBER}>{`◆ 已决定 ${decided}`}</Text> : null
    return (
      <Box key={`m-${m.id}`} flexDirection="row" gap={1} marginLeft={head ? 0 : 5}>
        {/* top-aligned with the name: the desktop centres an image in a stretched row */}
        {head ? <Box flexShrink={0} alignSelf="flex-start">{avatar(ui, from, 28, look)}</Box> : null}
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0}>
          {header}
          {overlay}
          {bubble}
        </Box>
      </Box>
    )
  }

  // An event in the feed (commands, approvals, joins, a finished turn, a warning): a tinted card with an icon by kind,
  // the time and the expand control at the right, so actions read apart from messages at a glance.
  const eventCard = (key: string, tone: Tone, title: string, at: number | undefined,
    o: { fold?: string; foldLabel?: string; titleColor?: string; who?: string; detail?: any } = {}) => (
    <Box key={key} flexDirection="column" borderStyle="round" borderColor={tone.border} backgroundColor={tone.bg} paddingX={1}>
      <Box flexDirection="row" gap={1} alignItems="center" minWidth={0}>
        {fix(`${key}-ic`, <Text color={tone.fg} bold>{tone.icon}</Text>)}
        {o.who ? cut(`${key}-who`, displayName(o.who), { color: nc(o.who), bold: true }, { shrink: nameShrink(o.who) }) : null}
        <Box flexGrow={1} flexShrink={1} minWidth={0}>
          <Text wrap="truncate-end" color={o.titleColor} dimColor={!o.titleColor}>{title}</Text>
        </Box>
        {at ? fix(`${key}-at`, <Text dimColor>{fmtClock(at)}</Text>) : null}
        {o.fold ? fix(`${key}-fb`, <Button key={`${key}-b`} plain dimColor onPress={() => toggleFold($, o.fold!)}>{o.foldLabel ?? '展开'}</Button>) : null}
      </Box>
      {o.detail ?? null}
    </Box>
  )

  // Live drafts, newest of all so at the top: each member at work (in this tab) as a bubble in the making, with what
  // it is writing (the latest part, typed in) or the tool it runs, and three dots that step with the clock.
  // a member with nothing written yet is only a state, which the working strip above already shows (its first two)
  // The text and the clock are live.tsx Clients (they refresh themselves once a second without a panel redraw); this tree
  // only gives them their first props, from the latest full view (liveView) so the first second is not blank.
  const liveOf = (id: string, part: string) => {
    const m = workingMembers(liveView ?? view).find(x => x.id === id)
    const p = m?.progress
    return { part, id, tool: typeof p?.last_tool === 'string' ? p.last_tool.trim() : '', text: String(p?.text ?? ''), tools: toolCount(p),
      startedAt: elapsedStart(p?.started_at), nowMs: Number(nowMs) }
  }
  const drafts = stale ? [] : working.filter(w => (!peerOf || peerOf === w.id)
    // has_text is structural (structOf): the row appears with the first written word, one redraw per turn
    && (!!w.progress?.has_text || liveOf(w.id, 'draft').text.trim() !== '' || working.indexOf(w) >= 2)).map(w => {
    const lv = liveOf(w.id, 'draft')
    return (
      <Box key={`dr-${w.id}`} flexDirection="row" gap={1}>
        <Box flexShrink={0} alignSelf="flex-start">{avatar(ui, w.id, 28, look)}</Box>
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0}>
          <Box flexDirection="row" gap={1} alignItems="center" minWidth={0}>
            {cut(`dr-nm-${w.id}`, displayName(w.id), { bold: true, color: nc(w.id) }, { shrink: nameShrink(w.id) })}
            {cut(`dr-st-${w.id}`, w.progress?.has_text || lv.text.trim() ? '正在写' : '正在执行', { color: C_BLUE })}
          </Box>
          <Box borderStyle="round" borderColor={mixHex(pal.bubbleBorder, '#4C8DF6', 0.5)} paddingX={1} minWidth={0}>
            <Client key={`lv-dr-${w.id}`} module="./live.tsx" props={lv} />
          </Box>
        </Box>
      </Box>
    )
  })


  // message rows with day dividers between them
  const msgNodes: any[] = []
  rows.forEach((row, idx) => {
    if (row.kind === 'noise') {
      // S1: a run of notices is one card; it opens into one line per event, its commands as wrapped code under it
      const isOpen = !!fold[row.key]
      const nCmd = row.items.reduce((n, it) => n + (it.cmds?.length ?? 0), 0)
      const openable = row.items.length > 1 || nCmd > 0
      // the light tier: one faint centred line (as a chat app's "X joined"), only its icon coloured; framed once opened
      const last = row.items[row.items.length - 1]
      const tone = TONES[noiseTone(row.items)]
      msgNodes.push(
        <Box key={row.key} flexDirection="column" alignItems="stretch">
          <Box flexDirection="row" gap={1} alignItems="center" justifyContent="center" minWidth={0}>
            {fix(`${row.key}-ic`, <Text color={tone.fg}>{tone.icon}</Text>)}
            {cut(`${row.key}-t`, `${noiseTitle(row.items)}${last?.at ? ' · ' + fmtClock(last.at) : ''}`, { dimColor: true })}
            {openable ? fix(`${row.key}-fb`, (
              <Button key={`${row.key}-b`} plain dimColor onPress={() => toggleFold($, row.key)}>
                {isOpen ? '收起' : nCmd ? `${nCmd} 条命令 ›` : '详情 ›'}
              </Button>
            )) : null}
          </Box>
          {isOpen ? (
            <Box flexDirection="column" gap={1} width="100%" borderStyle="round" borderColor={tone.border} backgroundColor={tone.bg} paddingX={1}>
              {row.items.map(it => (
                <Box key={`${row.key}-${it.id}`} flexDirection="column">
                  <Text dimColor>{`${fmtClock(it.at)}  ${softWrap(it.text, false)}`}</Text>
                  {it.cmds?.length ? (
                    <Box backgroundColor={pal.codeBg} paddingX={1}>
                      <Code source={it.cmds.join('\n')} language="bash" wrap="wrap" />
                    </Box>
                  ) : null}
                </Box>
              ))}
            </Box>
          ) : null}
        </Box>,
      )
    } else if (row.kind === 'group') {
      msgNodes.push(
        <Box key={row.key} flexDirection="column">
          {row.items.map((m, i) => unit(m, i === 0))}
        </Box>,
      )
    } else if (row.m.kind === 'system') {
      // S2: warnings and errors are not folded away: a card in their own colour
      const m = row.m
      const n = zhNotice(String(m.text ?? ''))
      const isOpen = !!fold[`w${m.id}`]
      const tone = TONES[n.kind === 'error' ? 'error' : 'warn']
      msgNodes.push(eventCard(`m-${m.id}`, tone, n.text, m.at, {
        titleColor: tone.fg,
        fold: n.raw !== n.text ? `w${m.id}` : undefined, foldLabel: isOpen ? '收起' : '详情',
        detail: isOpen ? <Text dimColor>{softWrap(n.raw, false)}</Text> : null,
      }))
    } else if (isDoneMsg(row.m)) {
      // a member ended its turn with xmuse_done: one card, the full report on demand
      const m = row.m
      const d = doneInfo(m)
      const blocked = d.outcome === 'blocked'
      const isOpen = !!fold[`d${m.id}`]
      const title = `完成：${d.summary}${d.outcome && d.outcome !== 'completed' ? ` · ${d.outcome}` : ''}`
      const report = isOpen ? (
        <Box flexDirection="column" marginBottom={1}>
          <Box backgroundColor={pal.bubble} borderStyle="round" borderColor={pal.bubbleBorder} paddingX={1}>
            <Markdown key={`md-${m.id}`} text={hardBreaks(softWrap(String(m.text ?? '')))} />
          </Box>
          <Box flexDirection="row">
            <Button key={`dn-${m.id}-cp`} plain dimColor onPress={(p: any) => copyText($, String(m.text ?? ''), p?.surface)}>复制全文</Button>
          </Box>
        </Box>
      ) : null
      if (blocked) {
        // the heavy tier: a blocked turn needs the user, so it is framed like a warning
        msgNodes.push(eventCard(`m-${m.id}`, TONES.warn, title, m.at, {
          who: m.from ?? '?', titleColor: C_AMBER, fold: `d${m.id}`, foldLabel: isOpen ? '收起' : '报告', detail: report }))
      } else {
        // the middle tier: a tinted row with a coloured edge and no frame, quieter than a warning, louder than a notice
        const tone = TONES.done
        msgNodes.push(
          <Box key={`m-${m.id}`} flexDirection="column">
            <Box flexDirection="row" gap={1} alignItems="center" backgroundColor={tone.bg} paddingRight={1} minWidth={0}>
              {fix(`m-${m.id}-bar`, <Text color={tone.fg}>▌</Text>)}
              {fix(`m-${m.id}-ic`, <Text color={tone.fg}>{tone.icon}</Text>)}
              {cut(`m-${m.id}-who`, displayName(m.from ?? '?'), { color: nc(m.from ?? '?'), bold: true }, { shrink: nameShrink(m.from ?? '?') })}
              <Box flexGrow={1} flexShrink={1} minWidth={0}><Text wrap="truncate-end">{title}</Text></Box>
              {fix(`m-${m.id}-at`, <Text dimColor>{fmtClock(m.at)}</Text>)}
              {fix(`m-${m.id}-fb`, <Button key={`m-${m.id}-b`} plain dimColor onPress={() => toggleFold($, `d${m.id}`)}>{isOpen ? '收起' : '报告 ›'}</Button>)}
            </Box>
            {report}
          </Box>,
        )
      }
    } else {
      msgNodes.push(unit(row.m, true))
    }
    // M5: a divider after the last row of a day, headed with that day
    const here = dayLabel(rowAt(row), nowMs)
    const next = rows[idx + 1]
    const there = next ? dayLabel(rowAt(next), nowMs) : (here === '今天' ? '今天' : '')
    if (here && there !== here) {
      msgNodes.push(<Box key={`dv-${idx}`} flexDirection="row" justifyContent="center"><Text dimColor>{`── ${here} ──`}</Text></Box>)
    }
  })

  const approvalCard = (a: any) => {
    const isShell = (a.kind ?? 'shell') === 'shell'
    const text = approvalText(a)
    const ago = agoText(a.at, nowMs)
    const risky = !!a.risk && a.risk !== 'low'
    const long = text.length > 60
    const isOpen = !!fold[`ap-${a.id}`]
    const label = `${displayName(a.member)}: ${text.replace(/\s+/g, ' ').slice(0, 40)}`
    return (
      <Box key={`ap-${a.id}`} flexDirection="column" borderStyle="round" borderColor={C_AMBER} paddingX={1}>
        <Box flexDirection="row" columnGap={1} flexWrap="wrap">
          <Text color={C_AMBER}>⚠</Text>
          <Text color={a.member ? nc(a.member) : undefined}>{a.member ? clip(displayName(a.member), 20) : '?'}</Text>
          <Text color={C_AMBER}>{`请求${approvalKindLabel(a.kind)}`}</Text>
          {risky ? <Text color={C_RED}>风险:高</Text> : null}
          {ago ? <Text dimColor>{ago}</Text> : null}
        </Box>
        {isShell ? (
          <Box backgroundColor={pal.codeBg} paddingX={1}>
            <Code source={text} language="bash" wrap={isOpen ? 'wrap' : 'truncate-end'} />
          </Box>
        ) : (
          <Text wrap={isOpen ? 'wrap' : 'truncate-end'}>{text}</Text>
        )}
        <Box flexDirection="row" columnGap={1} flexWrap="wrap">
          {long ? <Button key={`ap-${a.id}-more`} plain dimColor onPress={() => toggleFold($, `ap-${a.id}`)}>{isOpen ? '收起' : '展开'}</Button> : null}
          <Button key={`ap-${a.id}-cp`} plain dimColor onPress={(p: any) => copyText($, text, p?.surface)}>{isShell ? '复制命令' : '复制'}</Button>
        </Box>
        {busy[a.id] ? (
          <Text dimColor>处理中…</Text>
        ) : (
          <Box flexDirection="row" columnGap={1} flexWrap="wrap">
            <Button key={`ap-${a.id}-once`} variant="primary" onPress={() => approve($, a.id, 'once', label)}>
              {approvalHasAlways(a) ? '批准一次' : '批准'}
            </Button>
            {approvalHasAlways(a) ? (
              <Button key={`ap-${a.id}-always`} variant="secondary" onPress={() => approve($, a.id, 'always', label)}>总是批准</Button>
            ) : null}
            <Button key={`ap-${a.id}-reject`} plain dimColor hover={{ color: C_RED }} onPress={() => approve($, a.id, 'reject', label)}>拒绝</Button>
          </Box>
        )}
      </Box>
    )
  }
  const allOpen = !!fold['ap-all']
  const shownApprovals = allOpen ? approvals : approvals.slice(0, 1)

  // one member's numbers, for its chip and for its card
  const bitsOf = (m: any) => {
    const waiting = approvals.some(a => a.member === m.id)
    const st = statusOf(m, waiting)
    const tokens = m.id === meId && selfCtx > 0 ? selfCtx : m.context_tokens
    const ctx = stale ? '' : ctxText(tokens)
    // real colours (the theme names for idle / subtle are close to invisible): idle green, running blue, waiting or paused
    // amber, offline grey, a lost connection red
    const dot = stale ? '#F85149' : st.label === '执行中' ? '#4C8DF6' : st.label === '空闲' ? '#3FB950' : st.label === '离线' ? '#8B949E' : '#D29922'
    return { st, tokens, ctx, dot, cl: ctxLevel(tokens), compacting: !!m.compacting || cpBusy(m.id), running: !stale && st.label === '执行中' }
  }

  // the full card of the member whose chip is open: its model picker button, context meter and compact control (the
  // compact control reads 压缩中… from the press on, and "已压缩" until the next reply measures again)
  const cardOf = (m: any) => {
    const b = bitsOf(m)
    const q = Number(m.queued ?? 0)
    // only with a size to show (no session yet: nothing to compact); a running opencode answers busy
    const offer = !stale && !!b.ctx && !b.compacting && canCompact(m, meId) && (m.id === meId || b.st.label !== '执行中')
    return (
      <Box key={`mate-${m.id}`} flexDirection="row" gap={1} alignItems="center" borderStyle="round"
        borderColor={b.running ? mixHex(pal.bubbleBorder, '#4C8DF6', 0.6) : pal.bubbleBorder}
        backgroundColor={pal.bubble} paddingX={1}>
        {avatar(ui, m.id, 32, look)}
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0}>
          <Box flexDirection="row" gap={1} alignItems="center" minWidth={0}>
            {cut(`cd-nm-${m.id}`, m.id, { bold: true, color: nc(m.id) })}
            {m.id === hostId ? fix(`cd-host-${m.id}`, <Text color={C_AMBER}>★ 主控</Text>) : null}
          </Box>
          <Box flexDirection="row" flexWrap="wrap" columnGap={1}>
            <Text color={b.dot}>{b.st.dot}</Text>
            <Text dimColor>{` ${stale ? '未知' : b.st.label}`}</Text>
            {b.running ? (
              <Client key={`el-${m.id}-card`} module="./elapsed.tsx" props={{ startedAt: elapsedStart(m.progress?.started_at), baseMs: nowMs, kind: 'plain' }} />
            ) : null}
            {b.running ? <Client key={`lv-tools-${m.id}`} module="./live.tsx" props={liveOf(m.id, 'tools')} /> : null}
            {q > 0 ? <Text color={C_AMBER}>{` · 排队 ${q}`}</Text> : null}
          </Box>
          {/* its model, a button that opens the picker; this session's own Claude is the desktop app's to set */}
          {m.model && m.id !== meId ? (
            <Button key={`md-${m.id}`} plain dimColor={mp?.member !== m.id} hover={{ color: C_BLUE }} onPress={() => toggleModelPicker($, m.id)}>
              {`${narrow ? clip(shortModel(m.model), 14) : shortModel(m.model)} ${mp?.member === m.id ? '▴' : '▾'}`}
            </Button>
          ) : null}
          {!stale && (b.ctx || m.compacted || b.compacting) ? (
            <Box flexDirection="row" columnGap={1} alignItems="center" flexWrap="wrap">
              {b.compacting ? <Text color={C_BLUE}>◌ 压缩中…</Text>
                : m.compacted ? <Text dimColor>已压缩 · 待下次回复</Text>
                : (
                  <Box flexDirection="row" gap={1} alignItems="center">
                    <ui.Svg source={ctxBarSvg(b.tokens)} alt={`上下文 ${b.ctx}`} width={56} height={6} />
                    <Text color={b.cl === 2 ? C_RED : b.cl === 1 ? C_AMBER : undefined} dimColor={b.cl === 0}>{b.ctx}</Text>
                  </Box>
                )}
              {offer ? <Button key={`cp-${m.id}`} plain dimColor={b.cl === 0} hover={{ color: C_BLUE }} onPress={() => compactMember($, m.id, m.id === meId)}>压缩</Button> : null}
            </Box>
          ) : null}
          {b.running ? (
            <Button key={`card-stop-${m.id}`} plain hover={{ color: C_RED }} onPress={() => stopMember($, m.id)}>
              {busy[`st${m.id}`] ?'停止中…' : '■ 停止'}
            </Button>
          ) : null}
        </Box>
      </Box>
    )
  }
  const openMember = members.find(x => x.id === expanded)
  const peerMember = peerOf ? members.find(x => x.id === peerOf) : undefined

  // The conversation list: the room, one entry per member (the user's private chat with it), everything. Always a
  // vertical list of cards beside the main column, as tall as the pane; its width follows the pane (railW) and a narrow
  // one is compact (one row per entry, the status as a dot). Never folded. Only a Button takes a press (an avatar
  // cannot), so the name is the target; the row Box has a key, which makes it a hover scope (the highlight needs no code).
  const railIcon = (it: RailItem, size: number) => it.kind === 'room'
    ? <ui.Svg source={roomSvg(size)} alt="大群" width={size} height={size} />
    : it.peer ? avatar(ui, it.peer, size, look)
    : <Box width={3} justifyContent="center"><Text dimColor>≡</Text></Box>
  const unreadPill = (n: number) => (
    <Text color={desk ? '#FFFFFF' : C_RED} backgroundColor={desk ? '#E5534B' : undefined} bold>{desk ? ` ${Math.min(n, 99)} ` : String(Math.min(n, 99))}</Text>
  )
  const railRow = (it: RailItem) => {
    const sel = it.id === activeTab
    const m = it.peer ? members.find(x => x.id === it.peer) : undefined
    const b = m ? bitsOf(m) : null
    const key = it.kind === 'dm' ? `rail-dm-${it.peer}` : `rail-${it.kind}`
    const name = it.kind === 'room' ? '大群' : it.kind === 'all' ? '全部' : it.label
    const sub = it.kind === 'room' ? `${members.length} 位成员` :it.kind === 'all' ? '所有消息' : stale ? '未知' : (b?.st.label ?? '')
    if (railFold) {
      // avatars only: a blank Button over the whole cell is the click target (a Button cannot hold an image), painted last
      return (
        <Box key={`rw-${key}`} position="relative" alignItems="center" justifyContent="center" paddingY={1} width="100%"
          {...(sel ? { backgroundColor: pal.bubble } : {})} hover={{ backgroundColor: pal.hoverBg }}>
          {it.kind === 'all'
            ? <Box key={`${key}-ic`} width={4} height={2} alignItems="center" justifyContent="center"><Text dimColor>≡</Text></Box>
            : railIcon(it, 28)}
          {sel ? <Box key={`${key}-sel`} position="absolute" left={0} top={1}><Text color={C_BLUE}>▍</Text></Box> : null}
          {it.unread > 0 ? <Box key={`${key}-un`} position="absolute" top={0} right={0}>{unreadPill(it.unread)}</Box> : null}
          {b ? <Box key={`${key}-dot`} position="absolute" bottom={0} right={0}><Text color={b.dot}>●</Text></Box> : null}
          <Box key={`${key}-hit`} position="absolute" top={0} left={0} right={0} bottom={0}>
            <Button key={key} plain onPress={() => setTab($, it.id)} label={'　　'} />
          </Box>
        </Box>
      )
    }
    return (
      <Box key={`rw-${key}`} flexDirection="row" alignItems="center" columnGap={1} paddingX={1} paddingY={0} marginX={1} marginBottom={1}
        borderStyle="round" borderColor={sel ? pal.bubble : '#00000000'} {...(sel ? { backgroundColor: pal.bubble } : {})}
        hover={{ backgroundColor: pal.hoverBg }}>
        {fix(`${key}-ic`, railIcon(it, railCompact ? 24 : 28))}
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0}>
          <Button key={key} plain dimColor={!sel} onPress={() => setTab($, it.id)}>
            <Text bold={sel} color={m ? nc(m.id) : undefined}>{clip(name, railCompact ? railW - 7 : railW - 9)}</Text>
            {railCompact && b ? <Text color={b.dot}>{' ●'}</Text> : null}
          </Button>
          {railCompact ? null : b ? (
            <Box flexDirection="row" columnGap={1} minWidth={0}>
              {fix(`rs-${key}-dot`, <Text color={b.dot}>●</Text>)}
              {cut(`rs-${key}`, sub, { dimColor: true })}
            </Box>
          ) : cut(`rs-${key}`, sub, { dimColor: true })}
        </Box>
        {it.unread > 0 ? fix(`${key}-un`, unreadPill(it.unread)) : null}
      </Box>
    )
  }
  // the fold control closes the rail
  const railFoldBtn = (
    <Box key="rw-rail-fold" flexDirection="row" justifyContent={railFold ? 'center' : 'flex-start'} marginX={railFold ? 0 : 1} flexShrink={0}>
      <Button key="rail-fold" plain dimColor onPress={() => toggleRailFold($)}>{railFold ? '›' : '‹ 收起'}</Button>
    </Box>
  )
  // chat: the entries sit at the bottom of the column, which is as tall as the pane (the root stretches it); the fold toggle is last
  const railNode = (
    <Box flexDirection="column" flexShrink={0} width={railW} backgroundColor={pal.codeBg} paddingY={1}
      {...(chat ? { justifyContent: 'flex-end' } : {})}>
      {rail.map(railRow)}
      {railFoldBtn}
    </Box>
  )

  // the decision line and the approval cards: the first one open, the rest behind one line (chat: above the composer; flow: in the top box)
  const approvalsNode = (
    <Box flexDirection="column">
      {decision.text ? <Box marginTop={1}><Text color={decision.ok ? C_GREEN : C_RED} wrap="truncate-end">{decision.text}</Text></Box> : null}
      {shownApprovals.map(a => <Box key={`apw-${a.id}`} flexDirection="column" marginTop={1}>{approvalCard(a)}</Box>)}
      {approvals.length > 1 ? (
        <Box flexDirection="row" gap={1} alignItems="center" marginTop={1}>
          <Text color={C_AMBER}>{allOpen ? `共 ${approvals.length} 条待审批` : `还有 ${approvals.length - 1} 条待审批`}</Text>
          <Button key="ap-all-toggle" plain onPress={() => toggleFold($, 'ap-all')}>{allOpen ? '只看第一条' : '全部展开'}</Button>
        </Box>
      ) : null}
    </Box>
  )

  // The controls of the header, as parts: the flow layout draws them in the top box, the chat layout in actionsNode just above
  // the composer (the chat follows the bottom, so they must not sit at the far top). Each key is drawn once per tree.
  // Every unit (a notice with its buttons, the header's button group) is one unbreakable box: when the pane is too
  // narrow the row wraps between units, never inside one. Buttons are plain text buttons; the one solid button in the
  // area is the main action of a notice.
  const wakeNotice = !autoWake && wakePending > 0 ? (
    <Box key="wake-notice" flexDirection="row" alignItems="center" gap={1} flexShrink={0}>
      <Text color={C_AMBER}>{`⚠ ${wakePending} 条待处理`}</Text>
      <Button key="wake-banner" variant="primary" onPress={() => wakeNow($)}>{busy.wake ? '处理中…' : '处理'}</Button>
    </Box>
  ) : null
  const briefNotice = briefMissing ? (
    <Box key="brief-notice" flexDirection="row" alignItems="center" gap={1} flexShrink={0}>
      <Text color={C_AMBER}>无项目简介</Text>
      <Button key="brief-ask" plain onPress={() => askBrief($)}>写一份</Button>
      <Button key="brief-skip" plain dimColor onPress={() => dismissBrief($)}>忽略</Button>
    </Box>
  ) : null
  // flow: one line of notices
  const noticesRow = wakeNotice || briefNotice ? (
    <Box flexDirection="row" flexWrap="wrap" alignItems="center" columnGap={3}>
      {wakeNotice}
      {briefNotice}
    </Box>
  ) : null
  // a member tab's 操作 button
  const peerMenuBtn = peerMember ? fix('peer-menu-f', (
    <Button key={`peer-menu-${peerMember.id}`} plain dimColor={chat} hover={chat ? { color: C_BLUE } : undefined} onPress={() => toggleExpand($, peerMember.id)}>
      {expanded === peerMember.id ? '收起 ▴' : '操作 ▾'}
    </Button>
  )) : null
  // the room's buttons
  // in the chat layout they are a quiet toolbar: dim, with a hover colour; the flow layout keeps them as they were
  const roomActions = (
    <Box key="room-actions" flexDirection="row" alignItems="center" columnGap={chat ? 2 : 3} flexShrink={0}>
      {members.length ? <Button key="add-toggle" plain dimColor={chat} hover={chat ? { color: C_BLUE } : undefined} onPress={() => toggleAddOpen($)}>{addOpen ? '✕ 收起' : '＋ 助手'}</Button> : null}
      <Button key="auto-wake" plain dimColor={chat} hover={chat ? { color: C_BLUE } : undefined} onPress={() => toggleAuto($)}>
        {autoWake ? <Text>{chat ? <Text dimColor>自动叫醒 </Text> : '自动叫醒 '}<Text color={C_GREEN}>●</Text></Text> : <Text dimColor>自动叫醒 ○</Text>}
      </Button>
    </Box>
  )
  const addRow = addOpen && members.length ? (
    <Box flexDirection="row" flexWrap="wrap" alignItems="center" columnGap={3}>
      <Text dimColor>添加</Text>
      {busy.add ? <Text color={C_BLUE}>正在添加…</Text> : (
        <Box flexDirection="row" columnGap={3}>
          <Button key="add-opencode" plain onPress={() => addMember($, 'opencode')}>OpenCode</Button>
          <Button key="add-dsh" plain onPress={() => addMember($, 'dsh')}>dsh</Button>
          <Button key="add-agy" plain onPress={() => addMember($, 'agy')}>agy</Button>
        </Box>
      )}
    </Box>
  ) : null
  const memberMenu = peerMember && openMember?.id === peerMember.id ? (
    <Box flexDirection="column" marginTop={1}>
      {cardOf(peerMember)}
      <Box key={`menu-${peerMember.id}`} flexDirection="row" flexWrap="wrap" alignItems="center" columnGap={3}>
        {peerMember.paused || peerMember.status === 'paused'
          ? <Button key={`resume-${peerMember.id}`} plain onPress={() => memberAct($, peerMember.id, 'resume')}>▶ 恢复</Button>
          : <Button key={`pause-${peerMember.id}`} plain onPress={() => memberAct($, peerMember.id, 'pause')}>⏸ 暂停</Button>}
        {peerMember.id !== hostId ? (
          <Button key={`remove-${peerMember.id}`} plain dimColor={!busy[`rmq${peerMember.id}`]} hover={{ color: C_RED }}
            onPress={() => memberAct($, peerMember.id, 'remove')}>
            {busy[`rmq${peerMember.id}`] ? '确认移出？再点一次' : '移出房间'}
          </Button>
        ) : null}
        {busy[`ma${peerMember.id}`] ? <Text color={C_BLUE}>处理中…</Text> : null}
      </Box>
    </Box>
  ) : null
  // model picker of one member: the hub's options (its catalog, the defaults, what the room ran) or a typed
  // name; a pick is saved at once and takes effect at the member's next turn
  const modelPicker = mp && members.some(x => x.id === mp.member) ? (
    <Box key="model-pick" flexDirection="column" borderStyle="round" borderColor={mixHex(pal.bubbleBorder, '#4C8DF6', 0.6)}
      backgroundColor={pal.bubble} paddingX={1} gap={1} marginTop={1}>
      <Box flexDirection="row" gap={1} alignItems="center" minWidth={0}>
        {cut('mp-t', `更换 ${displayName(mp.member)} 的模型 · 下一轮起生效`, { bold: true }, { grow: true })}
        {fix('mp-xf', <Button key="mp-x" plain dimColor onPress={() => toggleModelPicker($, mp.member)}>✕</Button>)}
      </Box>
      {mp.loading ? <Text color={C_BLUE}>读取可选模型…</Text> : (
        <Box flexDirection="column" gap={1}>
          {mp.options.length ? (
            <Select key={`mp-sel-${mp.member}`} label="选择" value={mp.current}
              options={mp.options.map(o => ({ value: o.value, label: o.value === mp.current ? `${o.label ?? o.value}（当前）` : (o.label ?? o.value) }))}
              onSelect={(v: string) => setModel($, mp.member, v)} />
          ) : null}
          <Input key={`mp-in-${mp.member}`} placeholder={mp.format ? `或输入其他模型（格式 ${mp.format}）` : '或输入其他模型名'}
            submitLabel="换成这个" onSubmit={(v: string) => setModel($, mp.member, v)} />
        </Box>
      )}
      {busy[`md${mp.member}`] ? <Text color={C_BLUE}>正在更换…</Text> : null}
      {mp.note ? <Text dimColor>{mp.note}</Text> : null}
      {mp.error ? <Text color={C_RED}>{mp.error}</Text> : null}
    </Box>
  ) : null
  // chat layout: above the composer card, only what needs attention — notices (when any), and the add row / member
  // menu / model picker while open. The room's buttons live in the card's header row.
  const actionsNode = (
    <Box flexDirection="column">
      {wakeNotice || briefNotice ? (
        <Box flexDirection="row" flexWrap="wrap" alignItems="center" columnGap={3}>
          {wakeNotice}
          {briefNotice}
        </Box>
      ) : null}
      {addRow}
      {memberMenu}
      {modelPicker}
    </Box>
  )

  // The main column in parts (the chat layout draws them as top / feed / bottom, the flow layout as before):
  // topBox (header, notices, approvals), the working strip, the composer, and the messages.
  const topBox = (
     <Box flexDirection="column" flexShrink={0} marginBottom={1}>
      {probeLine ? <Text key="probe-line" dimColor wrap="truncate-end">{probeLine}</Text> : null}
      {errorCard}
      {roomBar}

      {/* X2: an empty room gets a first-step card with the two add buttons right there */}
      {members.length === 0 ? (
        <Box flexDirection="column" gap={1} borderStyle="round" borderColor="promptBorder" paddingX={1}>
          <Text>拉一个助手进来，然后在下面发第一句话</Text>
          <Box flexDirection="row" gap={1}>
            {busy.add ? <Text color={C_BLUE}>正在添加…</Text> : (
              <Box flexDirection="row" gap={1}>
                <Button key="guide-opencode" variant="primary" onPress={() => addMember($, 'opencode')}>+ OpenCode</Button>
                <Button key="guide-dsh" variant="primary" onPress={() => addMember($, 'dsh')}>+ dsh</Button>
                <Button key="guide-agy" variant="primary" onPress={() => addMember($, 'agy')}>+ agy</Button>
              </Box>
            )}
          </Box>
        </Box>
      ) : null}

      <Box flexDirection="column">
      {/* one line of notices: messages waiting for Claude while auto-wake is off, and a missing project brief */}
      {/* Every unit below (a notice with its buttons, the header's button group) is one unbreakable box: when the
          pane is too narrow the row wraps between units, never inside one. Buttons are plain text buttons; the one
          solid button in the area is the main action of a notice. */}
      {chat ? null : noticesRow}
      {/* the open conversation's header: the room (name, members, add an assistant, auto-wake), a member (its state and
          the 操作 menu: model, compact, stop, pause, remove), or everything */}
      {peerMember ? (
        <Box flexDirection="row" flexWrap="wrap" alignItems="center" justifyContent="space-between" columnGap={2}>
          <Box flexDirection="row" alignItems="center" gap={1} flexShrink={1} minWidth={0}>
            {fix('peer-av', avatar(ui, peerMember.id, 20, look))}
            {cut('peer-nm', peerMember.id, { bold: true, color: nc(peerMember.id) }, { shrink: nameShrink(peerMember.id) })}
            {peerMember.id === hostId ? fix('peer-host', <Text color={C_AMBER}>★ 主控</Text>) : null}
            {fix('peer-dot', <Text color={bitsOf(peerMember).dot}>●</Text>)}
            {fix('peer-st', <Text dimColor>{stale ? '未知' : bitsOf(peerMember).st.label}</Text>)}
            {bitsOf(peerMember).ctx && !narrow ? fix('peer-ctx', <Text dimColor>{bitsOf(peerMember).ctx}</Text>) : null}
          </Box>
          {chat ? null : peerMenuBtn}
        </Box>
      ) : (
        <Box flexDirection="row" flexWrap="wrap" alignItems="center" justifyContent="space-between" columnGap={3}>
          <Box flexDirection="row" alignItems="center" gap={1} flexShrink={1} minWidth={0}>
            {activeItem.kind === 'room' ? fix('room-svg', <ui.Svg source={roomSvg(20)} alt="大群" width={20} height={20} />) : null}
            {cut('room-nm', activeItem.kind === 'all' ? '全部消息' : String(view.room?.name ?? 'xmuse'), { bold: true })}
            {fix('room-n', <Text dimColor>{activeItem.kind === 'all' ? '· 含成员之间的私聊' : narrow ? `· ${members.length}` : `· ${members.length} 位成员`}</Text>)}
          </Box>
          {chat ? null : roomActions}
        </Box>
      )}
      {chat ? null : addRow}
      {chat ? null : memberMenu}
      </Box>

      {/* model picker of one member: the hub's options (its catalog, the defaults, what the room ran) or a typed
          name; a pick is saved at once and takes effect at the member's next turn */}
      {chat ? null : modelPicker}

      {chat ? null : approvalsNode}
     </Box>
  )

  // working strip: one line per running member (two at most): who, what it is doing, how long, stop
  const workingNode = working.length ? (
        <Box key="wk-box" flexDirection="column">
          {working.slice(0, 2).map(m => {
            return (
              <Box key={`wk-${m.id}`} flexDirection="row" alignItems="center" gap={1} minWidth={0}>
                {fix(`wk-dot-${m.id}`, <Text color={C_BLUE}>●</Text>)}
                {cut(`wk-nm-${m.id}`, m.id, { color: nc(m.id) }, { shrink: nameShrink(m.id) })}
                <Box key={`wk-do-${m.id}`} flexGrow={1} flexShrink={1} minWidth={0}>
                  <Client key={`lv-act-${m.id}`} module="./live.tsx" flexGrow={1} props={liveOf(m.id, 'act')} />
                </Box>
                {fix(`wk-sf-${m.id}`, (
                  <Button key={`wk-stop-${m.id}`} plain hover={{ color: C_RED }} onPress={() => stopMember($, m.id)}>
                    {busy[`st${m.id}`] ? '停止中…' : '■ 停止'}
                  </Button>
                ))}
              </Box>
            )
          })}
          {working.length > 2 ? <Text dimColor>{`另有 ${working.length - 2} 位在执行`}</Text> : null}
        </Box>
  ) : null
  const doneNodes = Object.keys(done).filter(id => !working.some(w => w.id === id) && members.some(x => x.id === id)).map(id => (
        <Text key={`dn-${id}`} dimColor wrap="truncate-end">{doneLine(id, done[id]!.tools, done[id]!.startedMs, done[id]!.endedMs)}</Text>
  ))

  // composer: a full-width card as an agent's prompt box: who it goes to (and the reply) on top, the field
  // across the whole width, the @ list inside it, the keys at the bottom. The platform's field is one line.
  // chat: one round card; its header row holds the target and reply on the left (shrinks first) and the quiet buttons
  // (add an assistant, auto-wake / 操作, expand) on the right as one unbreakable group; the row wraps when too narrow.
  const composerNode = (
      <Box flexDirection="column" marginTop={chat ? 0 : 1}
        {...(chat ? { borderStyle: 'round', borderColor: pal.bubbleBorder, paddingX: 1 } : {})}>
        {/* one small line above the field: who it goes to (the open tab) and the reply it answers */}
        <Box flexDirection="row" gap={chat ? undefined : 1} columnGap={chat ? 2 : undefined} flexWrap={chat ? 'wrap' : undefined} alignItems="center" minWidth={0}>
          <Box flexDirection="row" gap={1} alignItems="center" flexGrow={1} flexShrink={1} minWidth={0}>
            {fix('to-lbl', <Text dimColor>发给</Text>)}
            {cut('to-tab', activeLabel, { bold: true, color: peerOf ? nc(peerOf) : undefined }, { shrink: 0 })}
            {peerOf ? fix('to-dm', <Text dimColor>（私聊）</Text>) : null}
            {replyTo > 0 ? (
              <Box flexDirection="row" gap={1} alignItems="center" flexShrink={1} flexGrow={1} minWidth={0}>
                {cut('re-snip', `↩ #${replyTo} ${replySnip}`, { color: 'permission' }, { grow: true })}
                {fix('re-cancel-f', <Button key="re-cancel" plain dimColor onPress={() => setReply($, 0)}>✕</Button>)}
              </Box>
            ) : <Box flexGrow={1} />}
          </Box>
          {chat ? (
            <Box key="card-actions" flexDirection="row" alignItems="center" columnGap={2} flexShrink={0}>
              {peerMember ? peerMenuBtn : roomActions}
              <Button key="big-input" plain dimColor hover={{ color: C_BLUE }} onPress={() => openBigInput($)}>{narrow ? '⤢' : '⤢ 展开'}</Button>
            </Box>
          ) : fix('big-input-f', <Button key="big-input" plain dimColor onPress={() => openBigInput($)}>⤢ 大输入框</Button>)}
        </Box>
        {/* the Input draws its own send button (submitLabel) and takes the row's whole width; a retract gives it a new
            value (same key), an @ completion a new key (inputGen) so the caret lands at the end. The key hints are its placeholder.
            Chat: a column with stretch makes the leaf Input fill the card's width. */}
        <Box flexDirection={chat ? 'column' : 'row'} alignItems={chat ? 'stretch' : undefined} width={chat ? '100%' : undefined} flexGrow={1}>
          <Input key={`xm-in-${sendN}-${inputGen}`} placeholder={placeholder}
            {...(typeof forced === 'string' ? { value: forced } : {})}
            submitLabel={sending ? '发送中…' : '发送'} onInput={(v: string) => inputChanged($, v)} onSubmit={(v: string) => submitInput($, v)} />
        </Box>
        {cands.length ? (
          <Box flexDirection="column" {...(chat ? {} : { borderStyle: 'round', borderColor: pal.bubbleBorder, paddingX: 1 })}>
            {cands.map((c, i) => (
              <Box key={`mc-${c.id}`} flexDirection="row" gap={1} alignItems="center">
                {avatar(ui, c.id, 20, look)}
                {fix(`mcbf-${c.id}`, (
                  <Button key={`mcb-${c.id}`} plain onPress={() => pickMention($, c.id)}>
                    <Text color={nc(c.id)} bold={i === 0}>{`@${c.id}`}</Text>
                  </Button>
                ))}
                {cut(`mcd-${c.id}`, c.description ? String(c.description) : statusOf(c).label, { dimColor: true }, { grow: true })}
                {i === 0 ? fix(`mce-${c.id}`, <Text dimColor>↵</Text>) : null}
              </Box>
            ))}
          </Box>
        ) : null}
        {cands.length ? <Text dimColor>{`Enter 选 @${cands[0]!.id} · 继续输入缩小范围`}</Text> : null}
      </Box>
  )

  const emptyText = rows.length === 0 && !drafts.length
    ? <Text dimColor>{peerOf ? `和 ${peerOf} 的私聊：只有你们两个看得到` : '这里还没有消息：发一句话试试，@名字 可以指定对象'}</Text> : null
  // the "load earlier" control (flow: under the oldest message; chat: above it)
  const olderControl = hiddenHere > 0 ? (
        <Box flexDirection="row" justifyContent="center">
          <Button key="show-more" variant="secondary" onPress={() => showMore($, activeTab)}>{`显示更早的 ${Math.min(SHOW_STEP, hiddenHere)} 条`}</Button>
        </Box>
      ) : hasOlder ? (
        <Box flexDirection="row" justifyContent="center">
          <Button key="older" variant="secondary" onPress={() => loadOlder($)}>{older.loading ? '加载中…' : '加载更早的消息'}</Button>
        </Box>
      ) : rows.length ? <Box flexDirection="row" justifyContent="center"><Text dimColor>── 没有更早的消息了 ──</Text></Box> : null

  if (chat) {
    // chat order: header on top, the conversation oldest to newest, working strip / approvals / composer at the bottom.
    // msgNodes is newest first with each day's divider after that day's oldest row: reversed, the feed reads oldest to
    // newest and every divider heads its day (a group's own items are already oldest first).
    const chrono = msgNodes.slice().reverse()
    return (
      <Box flexDirection="row" columnGap={1} alignItems="stretch" minHeight={bodyRows > 0 ? bodyRows : undefined}>
        {railNode}
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0}>
          {topBox}
          <Box key="xm-feed" flexDirection="column" rowGap={1}>
            {emptyText}
            {olderControl}
            {chrono}
            {drafts}
          </Box>
          <Box flexDirection="column" flexShrink={0} marginTop={1} paddingBottom={1}>
            {workingNode}
            {doneNodes}
            {approvalsNode}
            {actionsNode}
            {composerNode}
          </Box>
        </Box>
      </Box>
    )
  }
  {
    return (
      <Box flexDirection="row" gap={1} alignItems="stretch" minHeight={bodyRows > 0 ? bodyRows : undefined}>
      {railNode}
      <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0}>
       {topBox}

       {/* working strip and input sit right under the header: the desktop pane scrolls natively, so nothing can be
           pinned; newest messages come first below them and scrolling down reads history */}
       <Box flexDirection="column" flexShrink={0} marginBottom={1}>
        {workingNode}
        {doneNodes}
        {composerNode}
       </Box>

       {/* messages, newest first */}
       <Box flexDirection="column">
        <Box flexDirection="column" gap={1}>
        {emptyText}
        {drafts}
        {msgNodes}
        {olderControl}
        </Box>
       </Box>

      </Box>
      </Box>
    )
  }
}

// ---- probes (/xmuse probe) -----------------------------------------------------------------------------------

async function toggleProbe($: any): Promise<{ text: string }> {
  const on = (await $.store.get(STORE_PROBE)) !== true
  await $.store.set(STORE_PROBE, on)
  await update($, probeAtom, () => on)
  return { text: on ? 'xmuse 探针已开：滚动面板、看 Claude 输入框上方' : 'xmuse 探针已关' }
}

/** `/xmuse layout`: chat (newest at the bottom) <-> flow (newest first). */
async function toggleLayout($: any): Promise<{ text: string }> {
  const next = (await read($, layoutAtom)) === 'flow' ? 'chat' : 'flow'
  await $.store.set(STORE_LAYOUT, next)
  await update($, layoutAtom, () => next)
  if (next === 'chat') scrollEndLater($)
  return { text: next === 'chat' ? 'xmuse 布局：聊天（新消息在底部）' : 'xmuse 布局：最新在上' }
}

/** Record a Pane scroll event; with the probe on, show it in the panel at most once a second. */
async function noteScroll($: any, e: any) {
  scrollProbe = { n: scrollProbe.n + 1, by: Number(e.by ?? 0), offset: Number(e.offset ?? 0), bodyRows: Number(e.bodyRows ?? 0),
    contentRows: Number(e.contentRows ?? 0), origin: String(e.origin?.kind ?? '') }
  if (!(await read($, probeAtom))) return
  const now = Number(await $.clock.now())
  if (now - scrollProbeAt < 1000) return
  scrollProbeAt = now
  await update($, scrollProbeAtom, () => scrollProbe)
}

/** The probe band: one row that says whether the area above the prompt box can be drawn into, and how wide and tall. */
async function drawBand($: any, e: any) {
  const { Box, Text } = $.ui.resolve(e) as any
  bandDraws++
  return (
    <Box flexDirection="row" columnGap={1}>
      <Text color="warning">xmuse 探针</Text>
      <Text>{`看得到这一行 = 输入框上方的横幅可用（宽 ${e.props?.bodyColumns ?? '?'} 列，最多 ${e.props?.maxRows ?? '?'} 行）`}</Text>
    </Box>
  )
}

/**
 * Pending approvals in the band above the prompt: the first one with its buttons (a decision never needs the panel
 * open), the rest behind one dim line. Every part truncates: the band is only as wide as the column it sits in.
 */
async function drawApprovalBand($: any, e: any, pending: any[]) {
  const { Box, Text, Button } = $.ui.resolve(e) as any
  const busy = await read($, busyAtom)
  const a = pending[0]
  const text = approvalText(a).replace(/\s+/g, ' ')
  const label = `${displayName(a.member)}: ${text.slice(0, 40)}`
  const always = approvalHasAlways(a)
  const line = (key: string, s: string, tp: Record<string, unknown> = {}) => (
    <Box key={key} flexShrink={1} minWidth={0} overflow="hidden"><Text wrap="truncate-end" {...tp}>{s}</Text></Box>
  )
  return (
    <Box flexDirection="column" minWidth={0} overflow="hidden">
      {line('band-ap-title', `⚠ xmuse 审批（${pending.length}）`, { color: C_AMBER })}
      {line('band-ap-who', `${displayName(a.member)} 请求${approvalKindLabel(a.kind)}`)}
      {line('band-ap-text', text, { dimColor: true })}
      {busy[a.id] ? <Text dimColor>处理中…</Text> : (
        <Box flexDirection="row" columnGap={1} flexWrap="wrap">
          <Button key="band-ap-once" variant="primary" onPress={() => approve($, a.id, 'once', label)}>{always ? '批准一次' : '批准'}</Button>
          {always ? <Button key="band-ap-always" variant="secondary" onPress={() => approve($, a.id, 'always', label)}>总是批准</Button> : null}
          <Button key="band-ap-reject" plain dimColor onPress={() => approve($, a.id, 'reject', label)}>拒绝</Button>
        </Box>
      )}
      {pending.length > 1 ? line('band-ap-more', `还有 ${pending.length - 1} 条，在 xmuse 面板里看`, { dimColor: true }) : null}
    </Box>
  )
}

// ---- hooks ---------------------------------------------------------------------------------------------------

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    if (DEV) {
      try { await $.fs.write(LOAD_MARK, `xmuse loaded ${new Date().toISOString()}\n`) } catch { /* diagnostics only */ }
    }
    await $.command.register({ name: 'xmuse', description: 'Open the xmuse collaboration panel' })
    await $.command.register({ name: 'x', description: '发到 xmuse 当前会话（@名字 指定成员）', argumentHint: '<消息>' })
    if ((await $.store.get(STORE_PROBE)) === true) await update($, probeAtom, () => true)
    if ((await $.store.get(STORE_LAYOUT)) === 'flow') await update($, layoutAtom, () => 'flow')
    if ((await $.store.get(STORE_RAIL)) === true) await update($, railFoldAtom, () => true)
    await registerTool($)
    await refreshTheme($, true)
    await openPanel($)
    // a reload keeps the last view: its avatars are looked up now, not at the next change in the room
    const kept = await read($, viewAtom)
    if (kept) await loadAvatars($, kept)
    await startLoop($)
    return started
  })

  on('session.compact', async ($, e, next) => compactHook($, e, next))

  // a grow Client (grow.tsx) showed its last step: e.data is { grown: 'r:<id>:<run>' }; a live Client (live.tsx) asks for
  // fresh props once a second: e.data is { live: 'act' | 'draft', id } and the answer reaches it without a panel redraw
  on('ui.message', async ($, e, next) => {
    const d: any = e.data
    if (typeof d?.grown === 'string') await growDone($, d) // validated there: kind and run must match the live atom
    if (d?.live === 'act' || d?.live === 'draft' || d?.live === 'tools') return { props: await liveProps($, d.live, String(d.id ?? '')) }
    return next(e)
  })

  // this session's own context size for its member card (the hub knows only its helpers' sizes); redraw per 1k moved
  on('session.measure', async ($, e, next) => {
    const t = Number(e.context?.tokens ?? 0)
    if (t > 0 && Math.abs(t - (await read($, selfCtxAtom))) >= 1000) await update($, selfCtxAtom, () => t)
    return next(e)
  })

  on('tool.call', { tool: /^mcp__xmuse__xmuse_send$/ }, async ($, e) => sendTool($, e))

  on('tool.call', { tool: /^mcp__xmuse__xmuse_brief$/ }, async ($, e) => briefTool($, e))

  // Only watches the theme row; the change itself passes through untouched.
  on('config.set', { key: 'theme' }, async ($, e, next) => {
    const r = await next(e)
    if (!r?.deny) await update($, themeAtom, () => isLightTheme(e.value))
    return r
  })

  on('command.run', { command: 'x' }, async ($, e) => sendFromCommand($, String(e.args ?? '')))

  on('command.run', { command: 'xmuse' }, async ($, e) => {
    if (String(e.args ?? '').trim() === 'probe') return toggleProbe($)
    if (String(e.args ?? '').trim() === 'layout') return toggleLayout($)
    rebound.clear() // opened by hand here: this session takes the member back once
    avatarTried = {} // pick up avatar files added since the last load
    await openPanel($)
    await startLoop($)
    scrollEndLater($)
    return { text: 'xmuse panel opened' }
  })

  // Probe 1 (`/xmuse probe`): do the pane's scroll events reach us, and with what numbers? Observes only; the move is never changed.
  on('ui.scroll', async ($, e, next) => {
    if (e.component === 'Pane' && e.requestId === PANE) {
      if (e.origin?.kind === 'plugin') return next(e) // our own scroll to the end
      if (e.origin?.kind === 'person') atBottom = Number(e.offset ?? 0) + Number(e.bodyRows ?? 0) >= Number(e.contentRows ?? 0) - 2
      await noteScroll($, e)
    }
    return next(e)
  })

  // The band above Claude's prompt box: pending approvals with their buttons; else the probe line while the probe is on.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props?.hasSurvey) return next(e)
    const sv = await read($, viewAtom) // read: the band redraws when the approvals change
    const pending = approvalsOf(liveView ?? sv)
    if (pending.length) return drawApprovalBand($, e, pending)
    if (!(await read($, probeAtom))) return next(e)
    return drawBand($, e)
  })

  // A throw would leave the pane to the engine's "Nothing to show yet" with no reason: show the error and the last step.
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    drawStage = 'start'
    const failed = (title: string, detail: string) => {
      const { Box, Text } = $.ui.resolve(e) as any
      return (
        <Box flexDirection="column" gap={1}>
          <Text color={C_RED}>{title}</Text>
          <Text wrap="wrap">{detail.slice(0, 2000)}</Text>
        </Box>
      )
    }
    // no timeout race: a timer per draw is one more host call on every redraw, and the hook's own budget already ends
    // a draw that hangs (the engine then draws its own and logs why)
    try {
      return await drawPanel($, e)
    } catch (err: any) {
      return failed('xmuse 面板绘制出错', `${String(err?.stack ?? err)}\n停在：${drawStage}`)
    }
  })
}
