import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import type { ConnInfo } from '../types'
import type { Pal, Tone } from './logic'
import {
  C_AMBER, C_BLUE, C_GREEN, C_ORANGE, C_RED, agoText, approvalHasAlways, approvalKindLabel, approvalText, approvalsOf, avatarSvg, backoffMs,
  buildRows, buildSay, buildWakePrompt, displayName, doneInfo, expandNewlines, fmtClock, hardBreaks, isAutoForward,
  isDoneMsg, isLoopbackUrl, isToClaude, lastLines, matchHubs, maxWakeId, membersOf, messagesFor, noiseSummary, parseHubs, parseMentions, replyLabel,
  statusOf, summaryLine, tabsOf, toLabel, toolCount, unreadThreadsFor, wakeCandidates, zhNotice,
  workingMembers, changedWorker, doneLine, finishedMembers, textsOf, toPosix, typingSteps,
  badgeOf, completeMention, dayLabel, foldLong, isLightTheme, memberColor, mentionCandidates, mixHex, palOf, rowAt, splitBlocks,
  trailingMention, vendorKey, canCompact, ctxLevel, ctxText, mergeCompactInstructions, hubStartScript,
  TONES, ctxBarSvg, noiseTitle, noiseTone, draftTail, freshMessage, revealSteps, shortModel,
} from './logic'

// xmuse panel (slice T8d): read-only view of the project's hub plus sending. Design: docs/design/XMUSE2-T8.zh.md §2.1, §3.
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
const tabAtom = atom({ plugin: 'xmuse', key: 'tab' } as const, 'all')
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
const sendingAtom = atom({ plugin: 'xmuse', key: 'sending' } as const, false)
const addOpenAtom = atom({ plugin: 'xmuse', key: 'addOpen' } as const, false)
const foldAtom = atom({ plugin: 'xmuse', key: 'fold' } as const, {} as Record<string, boolean>) // opened rows: done lines, noise runs, warnings
// Message actions (reply / promote) show on hover. If hover does not work in the desktop pane, set this to false: the buttons stay visible.
const HOVER_ACTIONS: boolean = true
const STORE_BRIEF = 'briefMissing' // boolean: the room was opened and has no project brief yet
const TOOL = 'xmuse_send' // registered as mcp__xmuse__xmuse_send
const TOOL_BRIEF = 'xmuse_brief' // mcp__xmuse__xmuse_brief: writes the project brief
const openAtom = atom({ plugin: 'xmuse', key: 'open' } as const, { busy: false, msg: '', error: '' })
// the typing effect of one member's partial output: run > 0 while a Client (grow.tsx) is typing it in, 0 when idle
const typedAtom = atom({ plugin: 'xmuse', key: 'typed' } as const, { id: '', full: '', from: 0, steps: [] as number[], run: 0 })
const doneAtom = atom({ plugin: 'xmuse', key: 'done' } as const, {} as Record<string, { tools: number; startedMs: number; endedMs: number }>)
const briefAtom = atom({ plugin: 'xmuse', key: 'brief' } as const, false) // mirrors STORE_BRIEF so the panel redraws
const DONE_KEEP_MS = 30_000 // how long the grey "finished" line stays
let typeRunN = 0 // run counter: part of the grow Client's key, a new run is a fresh instance
let lastTexts: Record<string, string> = {} // partial output seen in the last view, per running member
const POOL = 5000 // messages a tab can scroll through: the view's own plus every older page loaded
const OLDER_PAGE = 100 // one "加载更早的消息" press
const seenMsgs = new Map<number, any>() // every timeline item seen this load, by id (the newest copy wins)
let seenRoom = ''
// older pages fetched from /v1/timeline (oldest first), and whether the hub has still older ones
const olderAtom = atom({ plugin: 'xmuse', key: 'older' } as const, { items: [] as any[], hasMore: true, loading: false })
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
const TYPE_STEP_MS = 150

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
 * is moved over with /v1/rebind (the member token proves it is ours), once per session. Failing that, the panel still
 * works on the operator token; only the model's xmuse_send would be refused as "bound to another session".
 * The rebind races a 3 s timeout like probeToken (no hang: see §3.2); the outcome goes to REBIND_MARK under DEV.
 */
async function ensureBound($: any, c: HubConn): Promise<HubConn> {
  const sid: string = await $.session.id()
  if (c.sid === sid || !c.memberToken) return c
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
    const since = Number(cur?.version ?? 0)
    const r = await callHub($, 'GET', `/v1/view?since=${since}&wait=25`)
    if ((await read($, genAtom)) !== gen) return
    if (r.status === 204) {
      $.clock.after(50, () => { void pollOnce($, gen, 0) })
      return
    }
    if (r.status !== 200 || !r.data) {
      throw new Error(`hub 返回 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 120)}`)
    }
    await trackDone($, cur, r.data)
    await typeStart($, r.data) // before the view lands, so the new text is drawn from its typed prefix
    await revealStart($, r.data) // likewise: a new member message is first drawn empty, then grows
    await update($, viewAtom, () => r.data)
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
  await setConn($, 'connecting', '')
  void pollOnce($, gen, 0)
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
 * Partial output of the last member whose text changed is typed in over 4 steps of TYPE_STEP_MS. The steps run in a
 * Client (grow.tsx), not here: the atom is written once at the start and once when the Client reports it is done.
 */
async function typeStart($: any, newView: any) {
  const ch = changedWorker(lastTexts, newView)
  lastTexts = textsOf(newView)
  if (!ch) return
  const prev = await read($, typedAtom)
  // Continue from what was on screen for this member; text that is not an extension of it appears at once.
  let from = ch.text.length
  if (ch.text.startsWith(ch.old)) {
    from = ch.old.length
    if (prev.run > 0 && prev.id === ch.id && prev.full === ch.old) from = Math.min(from, prev.from) // still typing: restart from its start
  }
  if (from >= ch.text.length) { await update($, typedAtom, () => ({ id: ch.id, full: ch.text, from, steps: [], run: 0 })); return }
  await update($, typedAtom, () => ({ id: ch.id, full: ch.text, from, steps: typingSteps(from, ch.text.length, 4), run: ++typeRunN }))
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
  await update($, revealAtom, () => ({ id: m.id, steps, run: ++revealRunN }))
}

/** ui.message from a grow Client: it showed its last step; the atom goes idle and the normal rendering comes back. */
async function growDone($: any, data: any) {
  const id = typeof data?.grown === 'string' ? data.grown : ''
  const kind = id.slice(0, 2) // 't:<member>:<run>' | 'r:<message id>:<run>'
  const n = Number(id.slice(id.lastIndexOf(':') + 1))
  if (kind === 't:') await update($, typedAtom, t => (t.run === n ? { ...t, steps: [], run: 0 } : t))
  else if (kind === 'r:') await update($, revealAtom, r => (r.run === n ? { id: 0, steps: [], run: 0 } : r))
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
  const tab = await read($, tabAtom)
  const todo = unreadThreadsFor(view, tab)
  if (!todo.length) return
  const mark = `${tab}:${view.version ?? ''}`
  if ((await read($, lastReadAtom)) === mark) return
  await update($, lastReadAtom, () => mark)
  await markRead($, todo)
}

async function setTab($: any, tab: string) {
  await update($, tabAtom, () => tab)
  await update($, replyAtom, () => 0)
  const view = await read($, viewAtom)
  if (view) await markRead($, unreadThreadsFor(view, tab))
}

async function setReply($: any, id: number) {
  await update($, replyAtom, () => id)
}

async function sendMsg($: any, text: string) {
  if (await read($, sendingAtom)) return // a send is in flight: ignore the repeat press
  const view = await read($, viewAtom)
  const body = buildSay(expandNewlines(text), await read($, tabAtom), await read($, replyAtom), view)
  if (!body) return
  await update($, sendingAtom, () => true)
  try {
    const r = await callHub($, 'POST', '/v1/act', body)
    if (r.status !== 200) {
      $.ui.toast(`发送失败 ${r.status}: ${String(r.data?.message ?? r.data?.error ?? '').slice(0, 100)}`)
      return
    }
    await update($, replyAtom, () => 0)
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
    const tabId = await read($, tabAtom)
    const activeTab = tabsOf(view).some(t => t.id === tabId) ? tabId : 'all'
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
  } catch (err) {
    $.ui.toast(`加载失败: ${errText(err)}`)
    await update($, olderAtom, o => ({ ...o, loading: false }))
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

async function refreshStatus($: any, view: any) {
  $.ui.status(summaryLine(view, await pendingForMe($, view), (await $.store.get(STORE_AUTO)) === true))
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
  const kind = typeof e?.kind === 'string' && e.kind ? e.kind : 'message'
  if (kind !== 'message') return { deny: '面板工具暂只支持 message' }
  const to = typeof e?.to === 'string' ? e.to.trim() : ''
  const text = typeof e?.body === 'string' ? e.body.trim() : ''
  if (!to) return { deny: '缺少 to（#room、群 id 或成员 id）' }
  if (!text) return { deny: '缺少 body' }
  const view = await read($, viewAtom)
  const ments: string[] = Array.isArray(e?.mentions) ? e.mentions.filter((x: unknown) => typeof x === 'string') : parseMentions(text, view)
  const body: Record<string, unknown> = { act: 'say', to, text, mentions: ments }
  if (typeof e?.reply_to === 'number' && e.reply_to > 0) body.reply_to = e.reply_to
  try {
    const r = await callAsMember($, { to, body: text, mentions: ments, ...(body.reply_to ? { reply_to: body.reply_to } : {}) })
    const brief = r.data ? JSON.stringify(r.data).slice(0, 300) : ''
    // A tool error comes back as 200 with {error: {code, message}}: report it as a failure, never as "sent".
    const err = r.data?.error
    if (r.status !== 200 || err) {
      const why = typeof err === 'object' && err ? `${err.code ?? ''} ${err.message ?? ''}`.trim() : String(r.data?.message ?? err ?? brief)
      return { deny: `发送失败 ${r.status}: ${why.slice(0, 200)}` }
    }
    return { result: `已发送到 ${to}${brief ? `：${brief}` : ''}` }
  } catch (err) {
    return { deny: `发送失败: ${errText(err)}` }
  }
}

async function registerTool($: any) {
  try {
    await $.tool.register({
      name: TOOL,
      description: '通过 xmuse 协作室发消息给其他助手或用户（以本会话成员身份）。to 填 "#room"、群 id 或成员 id；回复某条消息时带 reply_to。',
      isDeferred: false,
      inputSchema: {
        type: 'object',
        properties: {
          to: { type: 'string', description: '"#room"、群 id 或成员 id' },
          body: { type: 'string', description: '消息正文' },
          mentions: { type: 'array', items: { type: 'string' }, description: '要 @ 的成员 id；省略时按正文里的 @名字 自动识别' },
          reply_to: { type: 'number', description: '回复的消息 id' },
          kind: { type: 'string', description: '默认 message；面板暂只支持 message' },
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
async function refreshTheme($: any) {
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

/** A member picked from the @ list: the trailing @word becomes "@id ", drawn as the same Input's new value (it keeps focus). */
async function pickMention($: any, id: string) {
  draftLive = completeMention(draftLive, id)
  await update($, forcedAtom, () => draftLive)
  await update($, mentionAtom, () => null)
  refocusInput($) // in case the surface still moved the ring (Enter went to the field's submit)
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
  try { res = await $.ui.focus({ requestId: PANE, key: `xm-in-${await read($, sendNAtom)}` }) } catch (err) { res = errText(err) }
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

async function drawPanel($: any, e: any) {
  const ui = $.ui.resolve(e) as any
  const { Box, Text, Button, Input, Markdown, Code, Select, Client } = ui
  const view = await read($, viewAtom)
  const conn = await read($, connAtom)
  const tab = await read($, tabAtom)
  const replyTo = await read($, replyAtom)
  const promoted = await read($, promotedAtom)
  const typed = await read($, typedAtom)
  const done = await read($, doneAtom)
  const fold = await read($, foldAtom)
  const light = await read($, themeAtom)
  const pal = palOf(light)
  await read($, avatarVerAtom) // redraw when a custom avatar file has been picked up

  const open = await read($, openAtom)
  const briefMissing = (await read($, briefAtom)) || (await $.store.get(STORE_BRIEF)) === true
  const noRoom = conn.phase === 'noroom'
  const target = noRoom ? await roomTarget($) : ''
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
  const tabs = tabsOf(view)
  const activeTab = tabs.some(t => t.id === tab) ? tab : 'all'
  // the view's recent page plus any older pages loaded with the button at the bottom
  // (the view carries only the latest page, so every message seen is kept: one that slid out of the page stays)
  const older = await read($, olderAtom)
  if (seenRoom !== String(view.room?.id ?? '')) { seenRoom = String(view.room?.id ?? ''); seenMsgs.clear() }
  for (const m of older.items) if (typeof m?.id === 'number' && !seenMsgs.has(m.id)) seenMsgs.set(m.id, m)
  for (const m of (Array.isArray(view.timeline) ? view.timeline : [])) if (typeof m?.id === 'number') seenMsgs.set(m.id, m)
  const histView = { ...view, timeline: [...seenMsgs.values()].sort((a, b) => a.id - b.id) }
  const hasOlder = older.items.length ? older.hasMore : !!view.timeline_cursor?.has_more
  const msgs = messagesFor(histView, activeTab, POOL).reverse() // newest first (see the layout note below)
  const rows = buildRows(msgs)
  const replied = msgs.find(m => m.id === replyTo)
  const replySnip = replied ? `${displayName(replied.from)}：${String(replied.text ?? '').replace(/\s+/g, ' ').slice(0, 40)}` : ''
  const activeLabel = tabs.find(t => t.id === activeTab)?.label ?? activeTab
  const placeholder = '和大家说点什么…'
  const approvals = approvalsOf(view)
  const working = workingMembers(view)
  const nowMs = await $.clock.now() // the host clock; the per-second times are drawn by the elapsed Client (elapsed.tsx)
  const sendN = await read($, sendNAtom)
  const sending = await read($, sendingAtom)
  const addOpen = await read($, addOpenAtom)
  const busy = await read($, busyAtom)
  const decision = await read($, decisionAtom)
  const mq = await read($, mentionAtom)
  const forced = await read($, forcedAtom)
  const autoWake = (await $.store.get(STORE_AUTO)) === true
  const seenRaw = await $.store.get(STORE_SEEN)
  const wakePending = wakeCandidates(view, typeof seenRaw === 'number' ? seenRaw : maxWakeId(view)).length
  const stale = conn.phase === 'error' // the view is old: no live-looking states
  const cands = mq !== null ? mentionCandidates(view, mq, 6) : []
  const selfCtx = await read($, selfCtxAtom)
  const reveal = await read($, revealAtom)
  const mp = await read($, modelAtom)
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
    const growing = reveal.run > 0 && reveal.id === m.id
    const folded = expanded || growing ? null : foldLong(full)
    const longOpen = expanded && foldLong(full) !== null
    const blocks = growing ? [] : splitBlocks(folded ? folded.text : full)
    const quote = m.reply_to ? replyLabel(view, m.reply_to) : ''
    const bg = mine ? pal.mine : toMe ? pal.toClaude : pal.bubble
    const bd = mine ? pal.mineBorder : toMe ? C_ORANGE : mixHex(pal.bubbleBorder, nc(from), 0.35)
    const actions = (
      <Box flexDirection="row" gap={1}>
        {head ? null : <Text dimColor>{fmtClock(m.at)}</Text>}
        <Button key={`re-${m.id}`} plain onPress={() => setReply($, m.id)}>回复</Button>
        {decided ? null : <Button key={`pr-${m.id}`} plain onPress={() => promote($, m.id)}>{busy[`pr${m.id}`] ? '处理中…' : '设为决定'}</Button>}
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
      <Box backgroundColor={bg} borderStyle="round" borderColor={bd} paddingX={1} flexDirection="column">
        {quote ? <Text dimColor wrap="truncate-end">{quote}</Text> : null}
        {blocks.map((b, i) => b.kind === 'diff'
          ? <Code key={`cd-${m.id}-${i}`} source={b.text} format="diff" />
          : <Markdown key={`md-${m.id}-${i}`} text={hardBreaks(b.text)} />)}
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
        <Box key={`m-${m.id}`} flexDirection="row" justifyContent="flex-end" marginLeft={8}>
          <Box flexDirection="column" flexGrow={1}>
            {head ? (
              <Box flexDirection="row" gap={1} justifyContent="flex-end" alignItems="center">
                {hoverActs}
                {decided ? <Text color={C_AMBER}>{`◆ 已决定 ${decided}`}</Text> : null}
                <Text dimColor>{`你 → ${toLabel(m)} · ${fmtClock(m.at)}`}</Text>
              </Box>
            ) : decided ? <Text color={C_AMBER}>{`◆ 已决定 ${decided}`}</Text> : null}
            {overlay}
            {bubble}
          </Box>
        </Box>
      )
    }
    const header = head ? (
      <Box flexDirection="row" gap={1} alignItems="center">
        <Text bold color={nc(from)}>{displayName(from)}</Text>
        {isAutoForward(m) ? <Text dimColor>自动转发</Text> : null}
        <Text color={toMe ? C_ORANGE : undefined} dimColor={!toMe}>{`→ ${toLabel(m)} · ${fmtClock(m.at)}`}</Text>
        {decided ? <Text color={C_AMBER}>{`◆ 已决定 ${decided}`}</Text> : null}
        <Box flexGrow={1} />
        {hoverActs}
      </Box>
    ) : decided ? <Text color={C_AMBER}>{`◆ 已决定 ${decided}`}</Text> : null
    return (
      <Box key={`m-${m.id}`} flexDirection="row" gap={1} marginLeft={head ? 0 : 5}>
        {head ? avatar(ui, from, 28, look) : null}
        <Box flexDirection="column" flexGrow={1}>
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
      <Box flexDirection="row" gap={1} alignItems="center">
        <Text color={tone.fg} bold>{tone.icon}</Text>
        {o.who ? <Text color={nc(o.who)} bold>{displayName(o.who)}</Text> : null}
        <Box flexGrow={1} flexShrink={1}>
          <Text wrap="truncate-end" color={o.titleColor} dimColor={!o.titleColor}>{title}</Text>
        </Box>
        {at ? <Text dimColor>{fmtClock(at)}</Text> : null}
        {o.fold ? <Button key={`${key}-b`} plain dimColor onPress={() => toggleFold($, o.fold!)}>{o.foldLabel ?? '展开'}</Button> : null}
      </Box>
      {o.detail ?? null}
    </Box>
  )

  // Live drafts, newest of all so at the top: each member at work (in this tab) as a bubble in the making, with what
  // it is writing (the latest part, typed in) or the tool it runs, and three dots that step with the clock.
  const peerOf = tabs.find(t => t.id === activeTab)?.peer
  const drafts = stale ? [] : working.filter(w => activeTab === 'all' || peerOf === w.id).map(w => {
    const p = w.progress
    const lt = typeof p?.last_tool === 'string' ? p.last_tool.trim() : ''
    const raw = String(p?.text ?? '')
    const typing = typed.run > 0 && typed.id === w.id && typed.full === raw // a grow Client types it in
    const text = typing ? raw : draftTail(raw)
    return (
      <Box key={`dr-${w.id}`} flexDirection="row" gap={1}>
        {avatar(ui, w.id, 28, look)}
        <Box flexDirection="column" flexGrow={1}>
          <Box flexDirection="row" gap={1} alignItems="center">
            <Text bold color={nc(w.id)}>{displayName(w.id)}</Text>
            <Text color={C_BLUE}>{lt ? `正在调用 ${lt}` : text ? '正在写' : '正在思考'}</Text>
            <Client key={`el-${w.id}-dots`} module="./elapsed.tsx" props={{ startedAt: elapsedStart(p?.started_at), baseMs: nowMs, kind: 'dots' }} />
          </Box>
          {text ? (
            <Box borderStyle="round" borderColor={mixHex(pal.bubbleBorder, '#4C8DF6', 0.5)} paddingX={1}>
              {typing ? (
                <Client key={`gr-t-${w.id}-${typed.run}`} module="./grow.tsx"
                  props={{ id: `t:${w.id}:${typed.run}`, text: raw, from: typed.from, stepMs: TYPE_STEP_MS, steps: typed.steps, mode: 'draft' }} />
              ) : <Text dimColor>{`${text} ▍`}</Text>}
            </Box>
          ) : null}
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
        <Box key={row.key} flexDirection="column" alignItems="center">
          <Box flexDirection="row" gap={1} alignItems="center">
            <Text color={tone.fg}>{tone.icon}</Text>
            <Text dimColor wrap="truncate-end">{`${noiseTitle(row.items)}${last?.at ? ' · ' + fmtClock(last.at) : ''}`}</Text>
            {openable ? (
              <Button key={`${row.key}-b`} plain dimColor onPress={() => toggleFold($, row.key)}>
                {isOpen ? '收起' : nCmd ? `${nCmd} 条命令 ›` : '详情 ›'}
              </Button>
            ) : null}
          </Box>
          {isOpen ? (
            <Box flexDirection="column" gap={1} width="100%" borderStyle="round" borderColor={tone.border} backgroundColor={tone.bg} paddingX={1}>
              {row.items.map(it => (
                <Box key={`${row.key}-${it.id}`} flexDirection="column">
                  <Text dimColor>{`${fmtClock(it.at)}  ${it.text}`}</Text>
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
        detail: isOpen ? <Text dimColor>{n.raw}</Text> : null,
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
            <Markdown key={`md-${m.id}`} text={hardBreaks(String(m.text ?? ''))} />
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
            <Box flexDirection="row" gap={1} alignItems="center" backgroundColor={tone.bg} paddingRight={1}>
              <Text color={tone.fg}>▌</Text>
              <Text color={tone.fg}>{tone.icon}</Text>
              <Text color={nc(m.from ?? '?')} bold>{displayName(m.from ?? '?')}</Text>
              <Box flexGrow={1} flexShrink={1}><Text wrap="truncate-end">{title}</Text></Box>
              <Text dimColor>{fmtClock(m.at)}</Text>
              <Button key={`m-${m.id}-b`} plain dimColor onPress={() => toggleFold($, `d${m.id}`)}>{isOpen ? '收起' : '报告 ›'}</Button>
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
        <Box flexDirection="row" gap={1}>
          <Text color={C_AMBER}>⚠</Text>
          <Text color={a.member ? nc(a.member) : undefined}>{a.member ? displayName(a.member) : '?'}</Text>
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
        <Box flexDirection="row" gap={1}>
          {long ? <Button key={`ap-${a.id}-more`} plain dimColor onPress={() => toggleFold($, `ap-${a.id}`)}>{isOpen ? '收起' : '展开'}</Button> : null}
          <Button key={`ap-${a.id}-cp`} plain dimColor onPress={(p: any) => copyText($, text, p?.surface)}>{isShell ? '复制命令' : '复制'}</Button>
        </Box>
        {busy[a.id] ? (
          <Text dimColor>处理中…</Text>
        ) : (
          <Box flexDirection="row" gap={1}>
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

  return (
    <Box flexDirection="column">
     <Box flexDirection="column" gap={1} flexShrink={0} marginBottom={1}>
      {/* messages waiting for Claude while auto-wake is off: the most prominent thing in the panel */}
      {!autoWake && wakePending > 0 ? (
        <Box flexDirection="row" gap={1} alignItems="center" borderStyle="round" borderColor={C_AMBER} backgroundColor={pal.banner} paddingX={1}>
          <Text color={C_AMBER}>{`⚠ 有 ${wakePending} 条消息等 Claude 处理`}</Text>
          <Button key="wake-banner" variant="primary" onPress={() => wakeNow($)}>{busy.wake ? '处理中…' : '现在处理'}</Button>
        </Box>
      ) : null}
      {errorCard}
      {roomBar}
      {briefMissing ? (
        <Box flexDirection="row" gap={1} alignItems="center">
          <Text color={C_AMBER}>还没有项目简介</Text>
          <Button key="brief-ask" onPress={() => askBrief($)}>让 Claude 写</Button>
          <Button key="brief-skip" plain onPress={() => dismissBrief($)}>忽略</Button>
        </Box>
      ) : null}

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

      {/* header: the room, then one segmented control at the right: add an assistant | auto-wake */}
      <Box flexDirection="row" alignItems="center" gap={1}>
        <Text bold>{String(view.room?.name ?? 'xmuse')}</Text>
        <Text dimColor>{`· ${members.length} 位成员`}</Text>
        <Box flexGrow={1} />
        <Box flexDirection="row" alignItems="center" borderStyle="round" borderColor={pal.bubbleBorder} backgroundColor={pal.bubble} paddingX={1} gap={1}>
          {members.length ? <Button key="add-toggle" plain onPress={() => toggleAddOpen($)}>{addOpen ? '✕ 收起' : '＋ 添加助手'}</Button> : null}
          {members.length ? <Text dimColor>│</Text> : null}
          <Button key="auto-wake" plain onPress={() => toggleAuto($)}>
            {autoWake ? <Text color={C_GREEN}>● 自动叫醒</Text> : <Text dimColor>○ 自动叫醒</Text>}
          </Button>
        </Box>
      </Box>
      {addOpen && members.length ? (
        <Box flexDirection="row" alignItems="center" gap={1} borderStyle="round" borderColor={pal.bubbleBorder} paddingX={1}>
          <Text dimColor>添加</Text>
          {busy.add ? <Text color={C_BLUE}>正在添加…</Text> : (
            <Box flexDirection="row" gap={1}>
              <Button key="add-opencode" variant="secondary" onPress={() => addMember($, 'opencode')}>OpenCode</Button>
              <Button key="add-dsh" variant="secondary" onPress={() => addMember($, 'dsh')}>dsh</Button>
              <Button key="add-agy" variant="secondary" onPress={() => addMember($, 'agy')}>agy</Button>
            </Box>
          )}
        </Box>
      ) : null}

      {/* member cards: one framed card each, the same height: name and host star, state, then a context meter with
          its size and the compact control (压缩中… from the press on; "已压缩" until the next reply measures again) */}
      <Box flexDirection="row" flexWrap="wrap" gap={1} rowGap={1}>
        {members.map(m => {
          const waiting = approvals.some(a => a.member === m.id)
          const st = statusOf(m, waiting)
          const q = Number(m.queued ?? 0)
          const dot = stale ? 'subtle' : st.color
          const tokens = m.id === meId && selfCtx > 0 ? selfCtx : m.context_tokens
          const ctx = stale ? '' : ctxText(tokens)
          const cl = ctxLevel(tokens)
          const compacting = !!m.compacting || cpBusy(m.id)
          // only with a size to show (no session yet: nothing to compact); a running opencode answers busy
          const offer = !stale && !!ctx && !compacting && canCompact(m, meId) && (m.id === meId || st.label !== '执行中')
          return (
            <Box key={`mate-${m.id}`} flexDirection="row" gap={1} alignItems="center" borderStyle="round"
              borderColor={st.label === '执行中' && !stale ? mixHex(pal.bubbleBorder, '#4C8DF6', 0.6) : pal.bubbleBorder}
              backgroundColor={pal.bubble} paddingX={1} minWidth={26}>
              {avatar(ui, m.id, 32, look)}
              <Box flexDirection="column" flexGrow={1}>
                <Box flexDirection="row" gap={1} alignItems="center">
                  <Text bold color={nc(m.id)}>{m.id}</Text>
                  {m.id === hostId ? <Text color={C_AMBER}>★ 主控</Text> : null}
                </Box>
                <Box flexDirection="row">
                  <Text color={dot}>{st.dot}</Text>
                  <Text dimColor>{` ${stale ? '未知' : st.label}`}</Text>
                  {!stale && st.label === '执行中' ? (
                    <Client key={`el-${m.id}-card`} module="./elapsed.tsx" props={{ startedAt: elapsedStart(m.progress?.started_at), baseMs: nowMs, kind: 'plain' }} />
                  ) : null}
                  {q > 0 ? <Text color={C_AMBER}>{` · 排队 ${q}`}</Text> : null}
                </Box>
                {/* its model, a button that opens the picker; this session's own Claude is the desktop app's to set */}
                {m.model && m.id !== meId ? (
                  <Button key={`md-${m.id}`} plain dimColor={mp?.member !== m.id} hover={{ color: C_BLUE }} onPress={() => toggleModelPicker($, m.id)}>
                    {`${shortModel(m.model)} ${mp?.member === m.id ? '▴' : '▾'}`}
                  </Button>
                ) : null}
                {!stale && (ctx || m.compacted || compacting) ? (
                  <Box flexDirection="row" gap={1} alignItems="center">
                    {compacting ? <Text color={C_BLUE}>◌ 压缩中…</Text>
                      : m.compacted ? <Text dimColor>已压缩 · 待下次回复</Text>
                      : (
                        <Box flexDirection="row" gap={1} alignItems="center">
                          <ui.Svg source={ctxBarSvg(tokens)} alt={`上下文 ${ctx}`} width={56} height={6} />
                          <Text color={cl === 2 ? C_RED : cl === 1 ? C_AMBER : undefined} dimColor={cl === 0}>{ctx}</Text>
                        </Box>
                      )}
                    {offer ? <Button key={`cp-${m.id}`} plain dimColor={cl === 0} hover={{ color: C_BLUE }} onPress={() => compactMember($, m.id, m.id === meId)}>压缩</Button> : null}
                  </Box>
                ) : null}
              </Box>
            </Box>
          )
        })}
      </Box>

      {/* model picker of one member: the hub's options (its catalog, the defaults, what the room ran) or a typed
          name; a pick is saved at once and takes effect at the member's next turn */}
      {mp && members.some(x => x.id === mp.member) ? (
        <Box key="model-pick" flexDirection="column" borderStyle="round" borderColor={mixHex(pal.bubbleBorder, '#4C8DF6', 0.6)}
          backgroundColor={pal.bubble} paddingX={1} gap={1}>
          <Box flexDirection="row" gap={1} alignItems="center">
            <Text bold>{'更换 '}</Text>
            <Text bold color={nc(mp.member)}>{displayName(mp.member)}</Text>
            <Text bold>的模型</Text>
            <Text dimColor>· 下一轮起生效</Text>
            <Box flexGrow={1} />
            <Button key="mp-x" plain dimColor onPress={() => toggleModelPicker($, mp.member)}>✕</Button>
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
      ) : null}

      {/* tabs: a colour dot before a private chat, # before a group */}
      <Box flexDirection="row" flexWrap="wrap" gap={1} rowGap={1}>
        {tabs.map(t => (
          <Button key={`tab-${t.id}`} variant={activeTab === t.id ? 'primary' : 'secondary'} onPress={() => setTab($, t.id)}>
            {t.peer ? <Text color={nc(t.peer)}>● </Text> : t.group ? '# ' : ''}
            {t.label}
            {t.unread > 0 ? <Text color={C_RED}>{` ${t.unread}`}</Text> : ''}
          </Button>
        ))}
      </Box>

      {/* approval cards, pinned above the messages: the first one open, the rest behind one line */}
      {decision.text ? <Text color={decision.ok ? C_GREEN : C_RED} wrap="truncate-end">{decision.text}</Text> : null}
      {shownApprovals.map(a => approvalCard(a))}
      {approvals.length > 1 ? (
        <Box flexDirection="row" gap={1} alignItems="center">
          <Text color={C_AMBER}>{allOpen ? `共 ${approvals.length} 条待审批` : `还有 ${approvals.length - 1} 条待审批`}</Text>
          <Button key="ap-all-toggle" plain onPress={() => toggleFold($, 'ap-all')}>{allOpen ? '只看第一条' : '全部展开'}</Button>
        </Box>
      ) : null}
     </Box>

     {/* working strip and input sit right under the header: the desktop pane scrolls natively, so nothing can be
         pinned; newest messages come first below them and scrolling down reads history */}
     <Box flexDirection="column" flexShrink={0} marginBottom={1}>
      {/* working strip (E1, E2, E3): one box, two rows per member: who and for how long, then what it is doing */}
      {working.length ? (
        <Box flexDirection="column" borderStyle="round" borderColor={C_BLUE} paddingX={1}>
          {working.map(m => {
            const p = m.progress
            const lt = typeof p?.last_tool === 'string' ? p.last_tool.trim() : ''
            const tail = lastLines(String(p?.text ?? ''), 1) // the typing effect is the draft bubble's alone
            const doing = lt ? `正在：${lt}` : tail
            const q = Number(m.queued ?? 0)
            return (
              <Box key={`wk-${m.id}`} flexDirection="column">
                <Box flexDirection="row">
                  <Text color={C_BLUE}>● </Text>
                  <Text color={nc(m.id)}>{m.id}</Text>
                  <Client key={`el-${m.id}-strip`} module="./elapsed.tsx" props={{ startedAt: elapsedStart(p?.started_at), baseMs: nowMs, kind: 'level' }} />
                  <Text dimColor>{` · ${toolCount(p)} 个工具`}</Text>
                  {q > 0 ? <Text color={C_AMBER}>{` · 排队 ${q}`}</Text> : null}
                  <Box flexGrow={1} />
                  <Button key={`wk-stop-${m.id}`} variant="secondary" hover={{ color: C_RED }} onPress={() => stopMember($, m.id)}>
                    {busy[`st${m.id}`] ? '停止中…' : '■ 停止'}
                  </Button>
                </Box>
                {doing ? <Text key={`wk-do-${m.id}`} dimColor wrap="truncate-end">{doing}</Text> : null}
              </Box>
            )
          })}
        </Box>
      ) : null}
      {Object.keys(done).filter(id => !working.some(w => w.id === id) && members.some(x => x.id === id)).map(id => (
        <Text key={`dn-${id}`} dimColor>{doneLine(id, done[id]!.tools, done[id]!.startedMs, done[id]!.endedMs)}</Text>
      ))}

      {/* composer: a full-width card as an agent's prompt box: who it goes to (and the reply) on top, the field
          across the whole width, the @ list inside it, the keys at the bottom. The platform's field is one line. */}
      <Box flexDirection="column" borderStyle="round" borderColor={replyTo > 0 ? 'permission' : 'promptBorder'}
        backgroundColor={pal.bubble} paddingX={1} paddingY={1} gap={1}>
        <Box flexDirection="row" gap={1} alignItems="center">
          <Text dimColor>发给</Text>
          <Box backgroundColor={pal.codeBg} paddingX={1}>
            <Text color={activeTab === 'all' ? undefined : nc(tabs.find(t => t.id === activeTab)?.peer ?? '')} bold>
              {activeTab === 'all' ? '全员' : activeLabel}
            </Text>
          </Box>
          {replyTo > 0 ? (
            <Box flexDirection="row" gap={1} alignItems="center" flexShrink={1}>
              <Text color="permission" wrap="truncate-end">{`↩ 回复 #${replyTo} ${replySnip}`}</Text>
              <Button key="re-cancel" plain dimColor onPress={() => setReply($, 0)}>✕</Button>
            </Box>
          ) : null}
        </Box>
        {/* the Input draws its own send button (submitLabel); a completion or a retract gives it a new value, not a
            new key, so it keeps the focus */}
        <Input key={`xm-in-${sendN}`} placeholder={placeholder}
          {...(typeof forced === 'string' ? { value: forced } : {})}
          submitLabel={sending ? '发送中…' : '发送'} onInput={(v: string) => inputChanged($, v)} onSubmit={(v: string) => submitInput($, v)} />
        {cands.length ? (
          <Box flexDirection="column" borderStyle="round" borderColor={pal.bubbleBorder} paddingX={1}>
            {cands.map((c, i) => (
              <Box key={`mc-${c.id}`} flexDirection="row" gap={1} alignItems="center">
                {avatar(ui, c.id, 20, look)}
                <Button key={`mcb-${c.id}`} plain onPress={() => pickMention($, c.id)}>
                  <Text color={nc(c.id)} bold={i === 0}>{`@${c.id}`}</Text>
                </Button>
                <Text dimColor wrap="truncate-end">{c.description ? String(c.description) : statusOf(c).label}</Text>
                {i === 0 ? <Text dimColor>↵</Text> : null}
              </Box>
            ))}
          </Box>
        ) : null}
        <Text dimColor>{cands.length ? `Enter 选 @${cands[0]!.id} · 继续输入缩小范围` : 'Enter 发送 · @ 指定成员 · \\n 换行'}</Text>
      </Box>
     </Box>

     {/* messages, newest first */}
     <Box flexDirection="column">
      <Box flexDirection="column" gap={1}>
      {rows.length === 0 && !drafts.length ? <Text dimColor>{activeTab === 'all' ? '这里还没有消息：发一句话试试，@名字 可以指定对象' : `和 ${activeLabel} 说点什么吧`}</Text> : null}
      {drafts}
      {msgNodes}
      {hasOlder ? (
        <Box flexDirection="row" justifyContent="center">
          <Button key="older" variant="secondary" onPress={() => loadOlder($)}>{older.loading ? '加载中…' : '加载更早的消息'}</Button>
        </Box>
      ) : rows.length ? <Box flexDirection="row" justifyContent="center"><Text dimColor>── 没有更早的消息了 ──</Text></Box> : null}
      </Box>
     </Box>

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
    await registerTool($)
    await refreshTheme($)
    await openPanel($)
    // a reload keeps the last view: its avatars are looked up now, not at the next change in the room
    const kept = await read($, viewAtom)
    if (kept) await loadAvatars($, kept)
    await startLoop($)
    return started
  })

  on('session.compact', async ($, e, next) => compactHook($, e, next))

  // a grow Client (grow.tsx) showed its last step: e.data is { grown: '<t|r>:<id>:<run>' }
  on('ui.message', async ($, e, next) => {
    const d: any = e.data
    if (typeof d?.grown === 'string') await growDone($, d) // validated there: kind and run must match the live atom
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

  on('command.run', { command: 'xmuse' }, async $ => {
    avatarTried = {} // pick up avatar files added since the last load
    await openPanel($)
    await startLoop($)
    return { text: 'xmuse panel opened' }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => drawPanel($, e))
}
