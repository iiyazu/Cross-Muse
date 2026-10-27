#!/usr/bin/env node
// xmuse 2 mock hub：按侧栏接口约定（v0 + v0.1）实现的内存假 hub。
// 无依赖，只监听 127.0.0.1。三家侧栏在真 hub 之外都用它开发和测试；字段名、返回形状、错误码照真 hub。
// 用法见同目录 README.md。
import http from 'node:http'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import crypto from 'node:crypto'

// ---------- 参数 ----------
const args = process.argv.slice(2)
function opt(name, def) {
  const i = args.indexOf('--' + name)
  if (i < 0) return def
  const v = args[i + 1]
  return v === undefined || v.startsWith('--') ? true : v
}
const PORT = Number(opt('port', 43117))
const STATE_DIR = opt('state-dir', null) // 若给出，写 <dir>/hub.json
const SEED = opt('seed', null) // 预先建房间，值为主控 member id（如 coord）
const INVITE_TTL = Number(opt('invite-ttl', 600))
const QUIET = !!opt('quiet', false)
const WS_DIR = typeof opt('dir', null) === 'string' ? opt('dir') : null // 工作区目录；给出时 POST /v1/rooms 校验 wrong_dir
const HOST_BATCH_MAX_S = Number(opt('host-batch-max-s', 600))

const HUMAN = 'human'
const HUB = 'hub'
const VENDORS = ['claude', 'opencode', 'dsh']
const MODELS = { claude: 'claude-opus-5-5', opencode: 'opencode-go/muse-spark-1.3-contributor', dsh: 'opencode-go/muse-spark-1.3-contributor' }
const OUTCOMES = ['completed', 'needs_alignment', 'blocked', 'progress']
const MEMBER_ACTS = new Set(['say', 'ack'])
const ACTS = new Set(['say', 'ack', 'approve', 'invite', 'remove', 'pause', 'resume', 'transfer_host', 'align',
  'member_add', 'member_edit', 'thread_new', 'thread_add', 'thread_remove', 'share_mark', 'wake_host'])

const now = () => Date.now() / 1000
const rid = n => crypto.randomBytes(n).toString('hex')
const log = (...a) => { if (!QUIET) console.error('[mock-hub]', ...a) }
const uniq = a => [...new Set(a)]

class ApiErr extends Error {
  constructor(status, code, message) { super(message); this.status = status; this.code = code }
}
const fail = (status, code, message) => { throw new ApiErr(status, code, message) }

// ---------- 本机登记表和侧栏凭据（8.1）----------
// 默认关闭（避免测试写真实用户目录）；--registry-dir <目录> / XMUSE_REGISTRY_DIR / --registry（用约定的默认目录）打开。
function defaultRegistryDir() {
  if (process.env.XMUSE_REGISTRY_DIR) return process.env.XMUSE_REGISTRY_DIR
  if (process.platform === 'win32') return path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'xmuse')
  return path.join(process.env.XDG_STATE_HOME || path.join(os.homedir(), '.local', 'state'), 'xmuse')
}
const REG = (() => {
  const a = opt('registry-dir', null)
  if (typeof a === 'string') return a
  if (a === true || opt('registry', false) || process.env.XMUSE_REGISTRY_DIR) return defaultRegistryDir()
  return null
})()
const hubsPath = () => path.join(REG, 'hubs.json')
const keyPath = () => path.join(REG, 'sidebar.key')
const ROOM_ID = 'r-' + rid(2)
const STARTED_AT = now()
let HUB_URL = null

const sleepSync = ms => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)
function pidAlive(pid) {
  try { process.kill(pid, 0); return true } catch (e) { return e.code === 'EPERM' }
}
function withLock(fn) {
  const lock = path.join(REG, 'hubs.lock')
  const end = Date.now() + 10000
  for (;;) {
    try { fs.closeSync(fs.openSync(lock, 'wx')); break } catch (e) {
      if (!['EEXIST', 'EPERM', 'EACCES'].includes(e.code)) throw e
      try { if (Date.now() - fs.statSync(lock).mtimeMs > 15000) fs.rmSync(lock, { force: true }) } catch { /* gone */ }
      if (Date.now() > end) fs.rmSync(lock, { force: true })
      sleepSync(20)
    }
  }
  try { return fn() } finally { fs.rmSync(lock, { force: true }) }
}
function regLoad() {
  try {
    const d = JSON.parse(fs.readFileSync(hubsPath(), 'utf8'))
    return (Array.isArray(d.hubs) ? d.hubs : []).filter(e => e && typeof e === 'object')
  } catch { return [] }
}
function regStore(entries) {
  const tmp = `${hubsPath()}.${process.pid}.${rid(4)}.tmp`
  fs.writeFileSync(tmp, JSON.stringify({ hubs: entries }, null, 1))
  fs.renameSync(tmp, hubsPath())
}
function regEntry() {
  return {
    room_id: ROOM_ID, name: S.room ? S.room.name : 'mock-room', dir: S.room ? S.room.dir : (WS_DIR || process.cwd()),
    url: HUB_URL, host: S.room ? S.room.host : null, pid: process.pid, started_at: STARTED_AT,
  }
}
function regSync() {
  if (!REG || !HUB_URL) return
  try { withLock(() => regStore([...regLoad().filter(e => pidAlive(e.pid) && e.room_id !== ROOM_ID), regEntry()])) } catch (e) { log('registry', e.message) }
}
function regLeave() {
  if (!REG) return
  try { withLock(() => regStore(regLoad().filter(e => pidAlive(e.pid) && !(e.room_id === ROOM_ID && e.pid === process.pid)))) } catch { /* best effort */ }
}
function ensureKey() {
  fs.mkdirSync(REG, { recursive: true })
  try { fs.writeFileSync(keyPath(), crypto.randomBytes(32).toString('hex'), { flag: 'wx', mode: 0o600 }) } catch (e) { if (e.code !== 'EEXIST') throw e }
}
function checkKey(given) {
  let key
  try { key = fs.readFileSync(keyPath(), 'utf8').trim() } catch { return false }
  if (!/^[0-9a-f]{64}$/.test(key) || typeof given !== 'string' || !given.trim()) return false
  const a = Buffer.from(given.trim()), b = Buffer.from(key)
  return a.length === b.length && crypto.timingSafeEqual(a, b)
}
// 没有登记目录（没有凭据可校验）时是 v0 兼容模式：不查 x-xmuse-sidebar
function needKey(req) {
  if (REG && !checkKey(req.headers['x-xmuse-sidebar'])) fail(401, 'bad_sidebar_key', 'missing or wrong x-xmuse-sidebar key')
}

// ---------- 状态 ----------
const S = {
  version: 1,
  room: null,
  members: new Map(), // id -> member
  removed: new Set(), // 被移除的成员 id（id 不再分配）
  tokens: new Map(), // token -> {kind:'member'|'operator', member}
  invites: new Map(), // code -> {vendor, role, description, name, expires_at, used}
  messages: [], // timeline，按 id 递增
  acked: new Map(), // member id -> Set(message id)
  threads: new Map(), // 私有小群 id -> {id, title, members:Set, created_at}
  alignment: [],
  approvals: [],
  marks: [], // share_mark：[{message_id, target}]，target '' = 任何人
  decided: new Set(), // 已处理的 share 审批 id
  waitingOn: [], // 主控派出还没交回的 handoff：[{member, handoff_id, since, notify}]
  hostWait: {}, // 注入口设置的 host_wait 覆盖
  nextMsg: 1001,
  nextAppr: 1,
  nextAlign: 1,
  nextShare: 1,
  waiters: [],
}

function bump() {
  S.version += 1
  const ws = S.waiters.splice(0)
  for (const w of ws) w()
}

function newMember({ id, vendor, model, role, description, session_id, bound }) {
  const m = {
    id, vendor, model: model || '', role, description: description || '',
    status: bound ? 'idle' : 'offline', online: !!bound, paused: false,
    tokens_hour: 0, tokens_hour_cap: 0, session_id: session_id || null, wakes_hour: null,
  }
  S.members.set(id, m)
  S.acked.set(id, new Set())
  return m
}

function issueTokens(member) {
  const member_token = 'mt_' + rid(16)
  const operator_token = 'ot_' + rid(16)
  S.tokens.set(member_token, { kind: 'member', member: member.id })
  S.tokens.set(operator_token, { kind: 'operator', member: member.id })
  return { member_token, operator_token }
}
function tokensOf(member) {
  let member_token = null, operator_token = null
  for (const [tk, v] of S.tokens) if (v.member === member.id) { if (v.kind === 'member') member_token = tk; else operator_token = tk }
  return member_token && operator_token ? { member_token, operator_token } : issueTokens(member)
}

function createRoom({ dir, name, vendor, session_id, member_id, description }) {
  S.room = { id: ROOM_ID, name, dir, host: member_id, info_layer: 'on', created_at: now() }
  const m = newMember({
    id: member_id, vendor, role: 'coordinator',
    description: description || '主控', session_id, bound: !!session_id,
  })
  regSync()
  return { m, ...issueTokens(m) }
}
const roomPub = () => ({ id: S.room.id, name: S.room.name, dir: S.room.dir, host: S.room.host, created_at: S.room.created_at })
const hostId = () => (S.room && S.members.has(S.room.host) ? S.room.host : null)

const validId = s => typeof s === 'string' && /^[A-Za-z0-9][A-Za-z0-9-]{0,39}$/.test(s) && s !== HUMAN && s !== HUB
function freeId(base) {
  const taken = id => S.members.has(id) || S.removed.has(id)
  if (!taken(base)) return base
  let n = 2
  while (taken(`${base}-${n}`)) n++
  return `${base}-${n}`
}
function normDir(s) {
  s = String(s)
  const m = s.match(/^\/mnt\/([a-z])\/(.*)$/i)
  if (m) s = `${m[1]}:\\${m[2].replace(/\//g, '\\')}`
  if (/^[A-Za-z]:|^\\\\/.test(s)) return s.replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase()
  return s.replace(/\/+$/, '')
}
const text = (b, k) => {
  if (b[k] !== undefined && b[k] !== null && typeof b[k] !== 'string') fail(400, 'bad_request', `${k} must be a string`)
  return b[k] ?? null
}
function modelOk(vendor, model) {
  if (!model.trim() || (vendor === 'opencode' && !model.includes('/'))) fail(400, 'bad_request', 'model: a non-empty name (opencode: <provider>/<model>)')
}

// ---------- 线程 ----------
function dmThread(a, b) { return 'dm:' + [a, b].sort().join('+') }
const threadExists = id => id === '#room' || S.threads.has(id) || S.messages.some(m => m.thread === id)
const isPrivate = id => S.threads.has(id)
const isDm = id => id.startsWith('dm:')

function threadMembers(id) {
  if (isDm(id)) return id.slice(3).split('+')
  const t = S.threads.get(id)
  if (t) return [...t.members].sort()
  return [HUMAN, ...S.members.keys()].sort()
}
// 成员令牌能看到的线程：#room、公开群、自己所在的 DM 和私有小群
function visible(id, member) {
  if (member === HUMAN || id === '#room') return true
  if (isDm(id)) return threadMembers(id).includes(member)
  const t = S.threads.get(id)
  return t ? t.members.has(member) : true
}
const hiddenScopes = member => [...S.threads.values()].filter(t => !t.members.has(member)).map(t => `thread:${t.id}`)

function createPrivate(id, creator, members, title) {
  if (typeof id !== 'string' || !id.startsWith('#') || id.length < 2 || /\s/.test(id)) {
    fail(400, 'invalid_arguments', `a group id is '#name' without spaces; got ${JSON.stringify(id)}`)
  }
  if (!Array.isArray(members) || !members.every(m => typeof m === 'string')) fail(400, 'invalid_arguments', 'members must be a list of member ids')
  if (threadExists(id)) fail(409, 'thread_exists', `${id} already exists`)
  const bad = members.filter(m => m !== HUMAN && !S.members.has(m))
  if (bad.length) fail(400, 'unknown_member', `not members of this room: ${bad.join(', ')}; members: ${[...S.members.keys()].sort().join(', ')}`)
  const t = { id, title: String(title || ''), members: new Set([HUMAN, creator, ...members]), created_at: now() }
  S.threads.set(id, t)
  return t
}
function privateThread(tid) {
  if (typeof tid !== 'string' || !threadExists(tid) && !isDm(tid)) fail(404, 'unknown_thread', `no thread ${JSON.stringify(tid)}`)
  if (isDm(tid)) fail(400, 'invalid_arguments', `${tid} is not a group`)
  const t = S.threads.get(tid)
  if (!t) fail(400, 'public_thread', `${tid} is a public group: everyone is in it`)
  return t
}

// ---------- 消息 ----------
function parseMentions(t) {
  const out = []
  for (const mm of t.matchAll(/@([\w.-]+)/g)) if (S.members.has(mm[1]) && !out.includes(mm[1])) out.push(mm[1])
  return out
}

function addMessage({ thread, from, via = null, to, mentions, text: body, kind = 'message', wake = [], ...extra }) {
  const msg = {
    id: S.nextMsg++, thread, from, via, to, mentions: mentions || [], kind, text: body, at: now(), wake, ...extra,
  }
  S.messages.push(msg)
  return msg
}
const notice = (thread, body, to = []) => addMessage({ thread, from: HUB, to, text: body, kind: 'system' })

// from 是 human 且 via 是 "<vendor> sidebar" 或 "cli"：用户自己说的
const userVia = via => via === 'cli' || (typeof via === 'string' && via.endsWith(' sidebar'))

// 发一条消息。返回 {msg, routed_to?}；出错抛 ApiErr
function sendMessage({ fromId, via = null, to, text: body, mentions, kind = 'message', strictDm = false, members, notify }) {
  if (typeof to !== 'string' || !to) fail(400, 'bad_request', 'to must be a string')
  let thread, recips, dm = false
  if (to.startsWith('#')) {
    thread = to
    if (!threadExists(to) && members != null && fromId !== HUMAN) createPrivate(to, fromId, members, '') // 成员发到不存在的群并带 members：私有小群
    const t = S.threads.get(to)
    if (t && !t.members.has(fromId) && fromId !== HUMAN) fail(403, 'not_a_member', `${to} is a private group you are not in`)
    recips = threadMembers(to).filter(x => x !== fromId)
  } else if (to.startsWith('dm:')) {
    const ends = to.slice(3).split('+')
    if (strictDm) {
      if (ends.length !== 2 || !ends.includes(fromId)) fail(400, 'bad_target', `${to} is not a conversation of ${fromId}`)
      to = ends[0] === fromId ? ends[1] : ends[0]
      thread = dmThread(fromId, to); recips = [to]; dm = true
    } else { thread = to; recips = ends.filter(x => x !== fromId); dm = true }
  } else if (to !== fromId && (S.members.has(to) || to === HUMAN)) {
    thread = dmThread(fromId, to); recips = [to]; dm = true
  } else {
    const peers = [...S.members.keys()].filter(x => x !== fromId).join(', ')
    fail(404, 'unknown_recipient', `to must be a member other than yourself (${peers}), 'human' or a '#group'`)
  }
  const ms = uniq([...(mentions || []), ...parseMentions(body)])
  const memberRecips = recips.filter(x => S.members.has(x))
  let wake = dm ? memberRecips : ms.filter(x => memberRecips.includes(x))
  let routed
  const host = hostId()
  // 8.4：用户不点名的话只唤醒主控
  if (fromId === HUMAN && userVia(via) && kind === 'message' && !ms.length && !dm && !isPrivate(thread) && host && recips.includes(host)) {
    wake = [host]; routed = host
  }
  const msg = addMessage({ thread, from: fromId, via, to: recips, mentions: ms, text: body, kind, wake })
  if (fromId === host && kind === 'handoff') {
    for (const m of wake) if (m !== host) S.waitingOn.push({ member: m, handoff_id: msg.id, since: msg.at, notify: notify === 'now' ? 'now' : 'batch' })
  }
  return { msg, routed_to: routed }
}

// 一条消息是否投给了 me：被投递（to/mentions）、不是自己发的、可见，主控那里被合并扣住的结果还没投
function delivered(m, me) {
  if (!me || m.from === me) return false
  if (m.held && me === hostId()) return false
  return (m.to.includes(me) || m.mentions.includes(me)) && visible(m.thread, me)
}
// for_me：点名我，或者是唤醒我的投递；DM 里投给我的都算；done 只在作为唤醒投给主控时算
function forMe(m, me) {
  if (!delivered(m, me)) return false
  if (m.kind === 'done') return m.wake.includes(me)
  if (isDm(m.thread)) return m.to.includes(me)
  return m.wake.includes(me) || m.mentions.includes(me)
}
function unreadFor(me) {
  const acked = S.acked.get(me) || new Set()
  return S.messages.filter(m => m.kind !== 'system' && delivered(m, me) && !acked.has(m.id))
}

const INTERNAL = new Set(['wake', 'held'])
function pub(m, me) {
  const out = {}
  for (const [k, v] of Object.entries(m)) if (!INTERNAL.has(k)) out[k] = v
  out.for_me = forMe(m, me)
  return out
}

// ---------- 结果标签和证据（8.4、8.5）----------
const DECLARE = ['decision', 'assumption', 'question']
function upgrade(outcome, declares, member, es, ep) {
  if (['completed', 'needs_alignment'].includes(outcome) && es === 'unverified' && !(ep || []).some(p => String(p).includes('transcript unavailable'))) {
    return ['blocked', 'evidence not verified' + (ep && ep.length ? `: ${ep.join('; ')}` : '')]
  }
  if (outcome === 'completed') {
    const wide = (declares || []).filter(d => DECLARE.includes(d.kind) && (d.supersedes || ![`member:${member}`, `agent:${member}`].includes(d.scope)))
    if (wide.length) {
      return ['needs_alignment', 'declares ' + uniq(wide.map(d => d.kind + (d.supersedes ? ` superseding ${d.supersedes}` : ''))).join(', ') + ' beyond its own scope']
    }
  }
  return [outcome, null]
}

function releaseHeld() {
  let n = 0
  const host = hostId()
  for (const m of S.messages) {
    if (!m.held) continue
    m.held = false; n++
    if (host && !m.wake.includes(host)) m.wake = [...m.wake, host]
  }
  return n
}

// 注入：成员发 done。返回 {msg, ...回包}
function memberDone(b) {
  const member = b.from
  if (!S.members.has(member)) fail(404, 'unknown_member', `no member ${JSON.stringify(member)}`)
  const body = b.summary ?? b.text
  if (typeof body !== 'string' || !body) fail(400, 'bad_request', 'done needs summary')
  const given = b.outcome || 'completed'
  if (!OUTCOMES.includes(given)) fail(400, 'invalid_arguments', `outcome must be one of: ${OUTCOMES.join(', ')}; got ${JSON.stringify(b.outcome)}`)
  const nxt = typeof b.next === 'string' && b.next ? b.next : 'none'
  const declares = Array.isArray(b.declares) ? b.declares : []
  let es = b.evidence_status, ep = Array.isArray(b.evidence_problems) ? b.evidence_problems.map(String) : null
  if (es === undefined) es = Array.isArray(b.evidence) && b.evidence.length ? 'unverified' : 'none'
  if (!['verified', 'unverified', 'none'].includes(es)) fail(400, 'bad_request', 'evidence_status must be verified, unverified or none')
  if (ep === null) ep = es === 'unverified' && Array.isArray(b.evidence) && b.evidence.length && b.evidence_status === undefined ? ['transcript unavailable'] : []
  const [final, reason] = upgrade(given, declares, member, es, ep)
  // 谁是接收人：next 是主控，或者这条结果对应主控派出的 handoff
  const host = hostId()
  const answers = host && host !== member ? S.waitingOn.filter(w => w.member === member).slice(0, 1) : []
  const forHost = !!host && host !== member && (nxt === host || answers.length > 0)
  const nxtMember = nxt !== 'none' && nxt !== member && S.members.has(nxt) ? nxt : null
  const thread = b.thread || (nxtMember ? dmThread(member, nxtMember) : forHost ? dmThread(member, host) : '#room')
  if (typeof thread !== 'string' || (!thread.startsWith('#') && !isDm(thread))) fail(400, 'bad_request', 'thread must be a #group or a dm: id')
  const to = uniq([...(nxtMember ? [nxtMember] : []), ...(forHost ? [host] : [])])
  const extra = {
    outcome: final, outcome_by: reason ? 'hub' : 'member', ...(reason ? { outcome_reason: reason } : {}),
    evidence_status: es, evidence_problems: ep,
  }
  const msg = addMessage({ thread, from: member, to, mentions: [], text: body, kind: 'done', ...extra })
  if (forHost) {
    const nowNotify = answers.some(w => w.notify === 'now') || b.notify === 'now'
    if (final !== 'progress' && answers.length) S.waitingOn = S.waitingOn.filter(w => w !== answers[0])
    if (final === 'progress') { /* 只被动投递 */ } else if (['needs_alignment', 'blocked'].includes(final) || nowNotify) {
      msg.wake = [host]; releaseHeld()
    } else {
      msg.held = true // completed：按批次等，交回齐了才唤醒
      if (!S.waitingOn.length) releaseHeld()
    }
  }
  return { msg, out: { id: msg.id, thread, recorded: true, ...(reason ? { outcome: final, outcome_by: 'hub', outcome_reason: reason } : { outcome: final }), evidence_status: es, evidence_problems: ep } }
}

function hostWaitView() {
  const o = S.hostWait
  const held = S.messages.filter(m => m.held)
  const waiting_on = o.waiting_on ?? S.waitingOn.map(({ member, handoff_id, since }) => ({ member, handoff_id, since }))
  const results_held = o.results_held ?? held.length
  const wake_at = 'wake_at' in o ? o.wake_at : (held.length && waiting_on.length ? held[0].at + HOST_BATCH_MAX_S : null)
  return { waiting_on, results_held, wake_at }
}
function wakesHour(m) {
  if (m.wakes_hour !== null && m.wakes_hour !== undefined) return m.wakes_hour
  const since = now() - 3600
  return new Set(S.messages.filter(x => x.at > since && x.wake.includes(m.id) && !x.held).map(x => Math.floor(x.at))).size
}

// ---------- 视图 ----------
function threadsFor(me) {
  const ids = uniq([...S.messages.map(m => m.thread), ...S.threads.keys()])
  const out = []
  for (const id of ids) {
    if (me && !visible(id, me)) continue
    const last = S.messages.filter(m => m.thread === id).at(-1)
    const t = S.threads.get(id)
    const members = threadMembers(id)
    out.push({
      id, kind: isDm(id) ? 'dm' : 'topic', title: isDm(id) ? members.join(' ↔ ') : (t && t.title) || id, members,
      private: !!t, last_at: last ? last.at : t.created_at, unread: 0,
    })
  }
  return out.sort((a, b) => b.last_at - a.last_at)
}

function approvalsFor(reader, hiddenSc) {
  const hiddenIds = new Set(S.alignment.filter(e => hiddenSc.includes(e.scope)).map(e => e.id))
  const normal = S.approvals.filter(a => a.kind !== 'share' && !hiddenIds.has(a.id))
  const shares = S.approvals.filter(a => a.kind === 'share')
  return reader.kind === 'member' ? normal : [...normal, ...shares] // 成员令牌看不到 share 审批
}

function view(reader) {
  const me = reader.member
  const restrict = reader.kind === 'member'
  const acked = S.acked.get(me) || new Set()
  const hiddenSc = restrict ? hiddenScopes(me) : []
  const members = [...S.members.values()].map(m => {
    const { session_id, wakes_hour, ...pubm } = m
    return { ...pubm, unread: unreadFor(m.id).length, wakes_hour: wakesHour(m) }
  })
  const threads = threadsFor(restrict ? me : null).map(t => ({
    ...t, unread: S.messages.filter(m => m.thread === t.id && m.kind !== 'system' && delivered(m, me) && !acked.has(m.id)).length,
  }))
  const vis = restrict ? S.messages.filter(m => visible(m.thread, me)) : S.messages
  const slice = vis.slice(-50)
  return {
    version: S.version,
    room: S.room,
    me: { kind: reader.kind, id: me },
    members, threads, timeline: slice.map(m => pub(m, me)),
    timeline_cursor: { oldest: slice.length ? slice[0].id : null, has_more: vis.length > slice.length },
    alignment: S.alignment.filter(e => !hiddenSc.includes(e.scope)),
    approvals: approvalsFor(reader, hiddenSc),
    run: null,
    host_wait: hostWaitView(),
  }
}

// ---------- 分享（8.6）----------
function userDm(mid) {
  const m = Number.isInteger(mid) ? S.messages.find(x => x.id === mid) : null
  if (!m || m.from !== HUMAN || !isDm(m.thread)) return null
  const ends = m.thread.slice(3).split('+')
  return ends.length === 2 && ends.includes(HUMAN) ? { m, holder: ends.find(x => x !== HUMAN) } : null
}
function shareTarget(me, to, memberCheck = true) {
  if (typeof to !== 'string' || !to) fail(400, 'invalid_arguments', 'to must be a member id or a thread id')
  if (isDm(to)) {
    const ends = to.slice(3).split('+')
    if (ends.length === 2 && ends.includes(me)) to = ends[0] === me ? ends[1] : ends[0]
  }
  if (S.members.has(to) && to !== me) return to
  if (to.startsWith('#') && threadExists(to) && (!memberCheck || threadMembers(to).includes(me))) return to
  const peers = [...S.members.keys()].filter(x => x !== me).join(', ')
  fail(404, 'unknown_recipient', `to must be a member other than yourself (${peers}) or a thread you are in`)
}
const marked = (mid, to) => S.marks.some(k => k.message_id === mid && (k.target === '' || k.target === to))

function deliverShare(me, m, to) {
  const body = `[shared by ${me}: the user's private message #${m.id} to them, released with the user's approval]\n${m.text}`
  const { msg } = sendMessage({ fromId: me, via: 'shared', to, text: body, mentions: [] })
  msg.shared_from = { member: me, message_id: m.id }
  return { status: 'delivered', id: msg.id, thread: msg.thread, woken: msg.wake }
}
const tell = (member, body) => notice(dmThread(member, HUMAN), body, [member])

// 注入：成员调 xmuse_share
function shareRequest(b) {
  const dm = userDm(b.message_id)
  if (!dm || dm.holder !== b.member) fail(403, 'not_shareable', '403 not_shareable: you can only share a private message the user sent you')
  const to = shareTarget(b.member, b.to)
  if (marked(dm.m.id, to)) return deliverShare(b.member, dm.m, to)
  const open = S.approvals.find(a => a.kind === 'share' && a.member === b.member && a.detail.message_id === dm.m.id && a.detail.to === to)
  if (open) return { status: 'pending_approval', approval: open.id }
  const id = `share:${S.nextShare++}`
  S.approvals.push({
    id, kind: 'share', member: b.member, summary: `${b.member} 想把 #${dm.m.id} 分享给 ${to}`.slice(0, 200),
    detail: { message_id: dm.m.id, to, why: String(b.why ?? ''), excerpt: dm.m.text.slice(0, 200) }, risk: 'normal', at: now(),
  })
  return { status: 'pending_approval', approval: id }
}
function decideShare(aid, decision) {
  const i = S.approvals.findIndex(a => a.id === aid && a.kind === 'share')
  if (i < 0) {
    if (S.decided.has(aid)) fail(400, 'invalid_arguments', `approval ${aid} was already decided`)
    fail(404, 'unknown_approval', `no approval ${aid}`)
  }
  const [ap] = S.approvals.splice(i, 1)
  S.decided.add(aid)
  const d = ap.detail
  if (decision === 'reject') {
    tell(ap.member, `The user rejected your request ${aid} to share #${d.message_id} with ${d.to}.`)
    return { status: 'rejected' }
  }
  if (decision === 'always') S.marks.push({ message_id: d.message_id, target: '' })
  const out = deliverShare(ap.member, S.messages.find(m => m.id === d.message_id), d.to)
  tell(ap.member, `The user approved your request ${aid} (${decision}): #${d.message_id} was delivered to ${d.to}.`)
  return out
}

// ---------- HTTP ----------
function send(res, status, obj) {
  const body = obj === undefined ? '' : JSON.stringify(obj)
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'content-length': Buffer.byteLength(body) })
  res.end(body)
}
const err = (res, status, error, message) => send(res, status, { error, message })

function readBody(req) {
  return new Promise(resolve => {
    const chunks = []
    req.on('data', c => chunks.push(c))
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8')
      if (!raw) return resolve({})
      try { resolve(JSON.parse(raw)) } catch { resolve(null) }
    })
  })
}

const bearer = req => {
  const h = req.headers['authorization'] || ''
  return S.tokens.get(h.startsWith('Bearer ') ? h.slice(7) : '')
}
function auth(req, res) {
  const h = req.headers['authorization'] || ''
  const tok = h.startsWith('Bearer ') ? h.slice(7) : ''
  const t = S.tokens.get(tok)
  if (!t) { err(res, 401, 'unauthorized', '缺少或无效的令牌'); return null }
  if (t.kind === 'member') {
    const m = S.members.get(t.member)
    const sess = req.headers['x-xmuse-session']
    if (m && m.session_id && sess !== m.session_id) { err(res, 409, 'not_bound_session', '会话与绑定的不一致'); return null }
  }
  return { kind: t.kind, member: t.member, token: tok }
}

function visibleMessages(a) {
  return a.kind === 'member' ? S.messages.filter(m => visible(m.thread, a.member)) : S.messages
}

async function handle(req, res) {
  const url = new URL(req.url, 'http://127.0.0.1')
  const p = url.pathname
  const method = req.method

  // ---- 测试用注入口（不在约定里，仅假 hub）----
  if (p.startsWith('/_mock/')) return mockCtl(req, res, p, method)

  if (method === 'GET' && p === '/v1/view') {
    const a = auth(req, res); if (!a) return
    const since = Number(url.searchParams.get('since') || 0)
    const wait = Math.min(30, Number(url.searchParams.get('wait') ?? 25))
    if (!(since !== 0 && since === S.version)) return send(res, 200, view(a))
    // since == version：挂起
    let done = false
    const finish = () => { if (done) return; done = true; clearTimeout(timer); if (!res.writableEnded) send(res, 200, view(a)) }
    const timer = setTimeout(() => {
      if (done) return; done = true
      const i = S.waiters.indexOf(finish); if (i >= 0) S.waiters.splice(i, 1)
      res.writeHead(204); res.end()
    }, wait * 1000)
    S.waiters.push(finish)
    req.on('close', () => { done = true; clearTimeout(timer); const i = S.waiters.indexOf(finish); if (i >= 0) S.waiters.splice(i, 1) })
    return
  }

  if (method === 'GET' && p === '/v1/timeline') {
    const a = auth(req, res); if (!a) return
    const before = Number(url.searchParams.get('before') || Infinity)
    const limit = Math.max(1, Math.min(200, Number(url.searchParams.get('limit') || 50)))
    const older = visibleMessages(a).filter(m => m.id < before)
    const items = older.slice(-limit).map(m => pub(m, a.member))
    return send(res, 200, { items, has_more: older.length > items.length })
  }

  // 本机侧栏的入口（8.1）：成员令牌一律 403；不带 code 的 join、POST/GET /v1/rooms 要 x-xmuse-sidebar
  if (p === '/v1/rooms' || (method === 'POST' && p === '/v1/join')) {
    const t = bearer(req)
    if (t && t.kind === 'member') return err(res, 403, 'member_forbidden', `${p} is for sidebars, not for members`)
    if (method === 'GET' && p === '/v1/rooms') {
      needKey(req)
      return send(res, 200, {
        room: S.room ? roomPub() : null,
        members: [...S.members.values()].map(m => ({ id: m.id, vendor: m.vendor, role: m.role, online: m.online })),
      })
    }
    if (method === 'POST') {
      const b = await readBody(req); if (!b || typeof b !== 'object' || Array.isArray(b)) return err(res, 400, 'bad_request', 'the body must be a JSON object')
      if (p === '/v1/rooms') { needKey(req); return send(res, 200, createRoomHttp(b)) }
      const keyed = !String(b.code || '').trim()
      if (keyed) needKey(req)
      return send(res, 200, keyed ? joinLocal(b) : joinCode(b))
    }
  }

  if (method === 'POST' && p === '/v1/rebind') {
    const t = bearer(req)
    if (!t || t.kind !== 'member') return err(res, 401, 'unauthorized', '需要成员令牌')
    const b = await readBody(req); if (!b || !b.session_id) return err(res, 400, 'bad_request', 'rebind needs session_id (string)')
    const m = S.members.get(t.member); m.session_id = b.session_id; m.online = true; m.status = 'idle'
    bump()
    return send(res, 200, { ok: true, member_id: m.id })
  }

  if (method === 'POST' && p === '/v1/leave') {
    const a = auth(req, res); if (!a) return
    if (a.kind !== 'member') return err(res, 403, 'member_only', '/v1/leave takes the member token')
    const m = S.members.get(a.member); m.session_id = null; m.online = false; m.status = 'offline'
    for (const [tk, v] of S.tokens) if (v.member === a.member) S.tokens.delete(tk)
    notice('#room', `${a.member} left its sidebar session (still a member; mail is kept)`)
    bump()
    return send(res, 200, { ok: true })
  }

  if (method === 'POST' && p === '/v1/act') {
    const a = auth(req, res); if (!a) return
    const b = await readBody(req); if (!b || !b.act) return err(res, 400, 'bad_request', '缺少 act')
    return send(res, 200, act(a, b))
  }

  err(res, 404, 'not_found', '没有这个接口')
}

function createRoomHttp(b) {
  if (S.room) fail(409, 'room_exists', 'this hub already has a room: join it with an invitation code')
  for (const k of ['dir', 'name', 'vendor', 'session_id']) if (!b[k]) fail(400, 'bad_request', '缺少 ' + k)
  if (!VENDORS.includes(b.vendor) || typeof b.session_id !== 'string' || typeof b.dir !== 'string') fail(400, 'bad_request', 'rooms needs dir, vendor (claude|opencode|dsh) and session_id')
  if (WS_DIR && normDir(b.dir) !== normDir(WS_DIR)) fail(400, 'wrong_dir', `this hub serves ${WS_DIR}, not ${b.dir}`)
  const member_id = b.member_id || b.vendor
  if (!validId(member_id)) fail(400, 'bad_request', "member_id: letters, digits and '-', not 'human' or 'hub'")
  const r = createRoom({ ...b, member_id })
  notice('#room', `${member_id} opened the room (${b.vendor} sidebar)`)
  bump()
  return { room: roomPub(), member_token: r.member_token, operator_token: r.operator_token, member_id: r.m.id }
}

// 加入：同名、同 vendor、还没绑定会话的成员被接管；否则新建
function addJoined(id, vendor, role, description, sid) {
  const old = S.members.get(id)
  if (S.removed.has(id) || (old && (old.vendor !== vendor || old.session_id))) fail(409, 'member_exists', `${id} is already a member; pick another name`)
  if (old) {
    old.session_id = sid; old.online = true; old.status = old.paused ? 'paused' : 'idle'
    if (role) old.role = role
    if (description) old.description = description
    return old
  }
  return newMember({ id, vendor, role: role || '', description, session_id: sid, bound: true })
}
function joinedNotice(m, vendor, role, desc) {
  notice('#room', `${m.id} joined the room (${vendor}${role ? ', ' + role : ''})${desc ? ': ' + desc : ''}`)
}

function joinCode(b) {
  const code = String(b.code || '').trim().toUpperCase()
  if (typeof b.session_id !== 'string' || !b.session_id) fail(400, 'bad_request', 'join needs code, vendor and session_id')
  const inv = S.invites.get(code)
  if (!inv) fail(404, 'unknown_code', 'no such invitation code')
  if (inv.used) fail(409, 'code_used', 'this invitation code was already used')
  if (inv.expires_at < now()) fail(410, 'code_expired', 'this invitation code has expired: ask for a new one')
  if (inv.vendor !== b.vendor) fail(403, 'vendor_mismatch', `this code is for a ${inv.vendor} member, not ${b.vendor}`)
  const id = inv.name || freeId(inv.vendor)
  const m = addJoined(id, inv.vendor, inv.role, inv.description, b.session_id) // 失败时码不作废
  if (!m.model && b.client_info && b.client_info.model) m.model = b.client_info.model
  inv.used = true
  const t = tokensOf(m)
  joinedNotice(m, inv.vendor, inv.role, inv.description)
  bump()
  return { member_id: id, ...t, room: S.room ? roomPub() : null }
}

function joinLocal(b) {
  const { vendor, session_id: sid, dir, room_id: rid_ } = b
  if (!VENDORS.includes(vendor) || typeof sid !== 'string' || !sid) fail(400, 'bad_request', 'join needs dir or room_id, vendor and session_id')
  if (dir === undefined && rid_ === undefined) fail(400, 'bad_request', 'join needs dir or room_id')
  if (dir !== undefined && typeof dir !== 'string') fail(400, 'bad_request', 'dir must be a string')
  const ws = S.room ? S.room.dir : (WS_DIR || process.cwd())
  if (dir !== undefined && normDir(dir) !== normDir(ws)) fail(400, 'wrong_dir', `this hub serves ${ws}, not ${dir}`)
  if (rid_ !== undefined && rid_ !== ROOM_ID) fail(404, 'unknown_room', `this hub serves room ${ROOM_ID}, not ${JSON.stringify(rid_)}`)
  const name = text(b, 'name') || null
  const role = text(b, 'role') || '', desc = text(b, 'description') || ''
  if (name !== null && !validId(name)) fail(400, 'bad_request', "name: letters, digits and '-', not 'human' or 'hub'")
  if (!S.room) fail(404, 'no_room', 'this hub has no room yet: open it with POST /v1/rooms')
  const id = name || freeId(vendor)
  const m = addJoined(id, vendor, role, desc, sid)
  if (!m.model && b.client_info && b.client_info.model) m.model = b.client_info.model
  const t = tokensOf(m)
  joinedNotice(m, vendor, role, desc)
  bump()
  return { member_id: id, ...t, room: roomPub() }
}

// ---------- act ----------
function act(a, b) {
  if (!ACTS.has(b.act)) fail(400, 'unknown_act', `act must be one of: ${[...ACTS].sort().join(', ')}`)
  const isOp = a.kind === 'operator'
  if (!isOp && !MEMBER_ACTS.has(b.act)) fail(403, 'operator_only', `forbidden: ${b.act} needs the operator token (the user, from a sidebar)`)
  const actor = S.members.get(a.member)
  switch (b.act) {
    case 'say': {
      const to = b.to || '#room' // 没有 to：房间（8.4）
      const mentions = b.mentions || []
      if (typeof to !== 'string' || typeof b.text !== 'string' || !b.text.trim() || !Array.isArray(mentions)) fail(400, 'bad_request', 'say needs to (string), text (string), mentions (list)')
      const fromId = isOp ? HUMAN : a.member
      const via = isOp ? `${actor ? actor.vendor : '?'} sidebar` : null
      const r = sendMessage({ fromId, via, to, text: b.text, mentions, strictDm: true })
      bump()
      return { id: r.msg.id, thread: r.msg.thread, ...(r.routed_to ? { routed_to: r.routed_to } : {}) }
    }
    case 'ack': {
      if (!Array.isArray(b.ids) || !b.ids.every(Number.isInteger)) fail(400, 'bad_request', 'ack needs ids (list of message ids)')
      const set = S.acked.get(a.member)
      let n = 0
      for (const id of b.ids) {
        const m = S.messages.find(x => x.id === id)
        if (m && delivered(m, a.member)) { if (!set.has(id)) n++; set.add(id) }
      }
      bump()
      return { ok: true, acked: n }
    }
    case 'approve': {
      if (!['once', 'always', 'reject'].includes(b.decision)) fail(400, 'bad_request', 'decision must be once, always or reject')
      const aid = String(b.id || '')
      if (aid.startsWith('share:')) { const out = decideShare(aid, b.decision); bump(); return { ok: true, ...out } }
      const i = S.approvals.findIndex(x => x.id === aid && x.kind !== 'share')
      if (i < 0) fail(404, 'unknown_approval', `no approval ${aid}`)
      const [ap] = S.approvals.splice(i, 1)
      const e = S.alignment.find(x => x.id === ap.id)
      if (e) e.status = b.decision === 'reject' ? 'rejected' : 'active'
      notice('#room', `审批 ${ap.id}（${ap.member}：${ap.summary}）→ ${b.decision}`)
      bump()
      return { ok: true }
    }
    case 'invite': {
      if (!VENDORS.includes(b.vendor)) fail(400, 'bad_request', `vendor must be one of: ${VENDORS.join(', ')}`)
      if (b.name && !validId(b.name)) fail(400, 'bad_request', "name: letters, digits and '-', not 'human' or 'hub'")
      const code = newCode()
      const expires_at = now() + INVITE_TTL
      S.invites.set(code, { vendor: b.vendor, role: String(b.role || ''), description: String(b.description || ''), name: b.name || null, expires_at, used: false })
      bump()
      return { code, expires_at, command: `/xmuse join ${code}` }
    }
    case 'remove': {
      const m = member(b.member)
      if (S.room && S.room.host === m.id) fail(409, 'is_host', `${m.id} hosts the room: transfer_host first`)
      S.members.delete(m.id); S.removed.add(m.id)
      for (const [tk, v] of S.tokens) if (v.member === m.id) S.tokens.delete(tk)
      notice('#room', `${m.id} was removed from the room`)
      bump(); return { ok: true }
    }
    case 'pause': case 'resume': {
      const m = member(b.member)
      m.paused = b.act === 'pause'; m.status = m.paused ? 'paused' : (m.online ? 'idle' : 'offline')
      bump(); return { ok: true }
    }
    case 'transfer_host': {
      const m = member(b.member)
      S.room.host = m.id
      notice('#room', `${m.id} now hosts the room`)
      regSync(); bump(); return { ok: true }
    }
    case 'align': {
      if (!['confirm', 'reject'].includes(b.decision)) fail(400, 'bad_request', 'decision must be confirm or reject')
      const e = S.alignment.find(x => x.id === b.id)
      if (!e) fail(404, 'unknown_entry', '没有这个对齐条目')
      e.status = b.decision === 'confirm' ? 'active' : 'rejected'
      S.approvals = S.approvals.filter(x => !(x.kind === 'alignment' && x.id === e.id))
      bump(); return { ok: true }
    }
    case 'member_add': {
      if (!VENDORS.includes(b.vendor)) fail(400, 'bad_vendor', `vendor must be one of: ${VENDORS.join(', ')}`)
      const name = text(b, 'name') || null
      const role = text(b, 'role'), desc = text(b, 'description'), model = text(b, 'model') || null
      if (name !== null && !validId(name)) fail(400, 'bad_request', "name: letters, digits and '-', not 'human' or 'hub'")
      if (model) modelOk(b.vendor, model)
      const id = name || freeId(b.vendor)
      if (S.members.has(id) || S.removed.has(id)) fail(409, 'member_exists', `${id} is already a member; pick another name`)
      // 假 hub：只加一个假成员，hub 驱动、没有会话、状态 idle
      const m = newMember({ id, vendor: b.vendor, model: model || MODELS[b.vendor], role: role || '', description: desc || '', session_id: null, bound: true })
      issueTokens(m)
      notice('#room', `${id} was added to the room (${b.vendor}${role ? ', ' + role : ''}${model ? ', ' + model : ''})${desc ? ': ' + desc : ''}`)
      bump(); return { member_id: id }
    }
    case 'member_edit': {
      const m = member(b.member)
      const neu = { role: text(b, 'role'), description: text(b, 'description'), model: text(b, 'model') }
      if (Object.values(neu).every(v => v === null)) fail(400, 'bad_request', 'member_edit needs role, description or model')
      if (neu.model !== null) modelOk(m.vendor, neu.model)
      const short = s => (s.length <= 80 ? s : s.slice(0, 79) + '…')
      for (const [k, v] of Object.entries(neu)) if (v !== null) m[k] = v
      const changes = Object.entries(neu).filter(([, v]) => v !== null).map(([k, v]) => `${k} = ${short(v)}`).join(', ')
      notice('#room', `${m.id} was edited: ${changes}`)
      bump(); return { ok: true }
    }
    case 'thread_new': {
      if (b.members === undefined || b.members === null) fail(400, 'bad_request', 'thread_new needs id and members (list)')
      const t = createPrivate(b.id, HUMAN, b.members, b.title)
      notice(t.id, `private group ${t.id} created with ${[...t.members].sort().join(', ')}`)
      bump(); return { thread: t.id }
    }
    case 'thread_add': {
      const t = privateThread(b.thread)
      if (typeof b.member !== 'string' || !S.members.has(b.member)) fail(400, 'unknown_member', `no member ${JSON.stringify(b.member)} in this room`)
      if (!t.members.has(b.member)) { t.members.add(b.member); notice(t.id, `${b.member} was added to ${t.id}`) }
      bump(); return { ok: true }
    }
    case 'thread_remove': {
      if (b.member === HUMAN) fail(400, 'invalid_arguments', 'the user is always in a private group')
      const t = privateThread(b.thread)
      if (typeof b.member !== 'string' || !t.members.delete(b.member)) {
        fail(400, 'not_in_thread', `${JSON.stringify(b.member)} is not in ${t.id}: ${[...t.members].sort().join(', ')}`)
      }
      notice(t.id, `${b.member} was removed from ${t.id}`)
      bump(); return { ok: true }
    }
    case 'share_mark': {
      if (!Number.isInteger(b.message_id)) fail(400, 'invalid_arguments', 'share_mark needs message_id (integer)')
      if (!S.messages.some(m => m.id === b.message_id)) fail(404, 'unknown_message', `no message ${b.message_id}`)
      const dm = userDm(b.message_id)
      if (!dm) fail(403, 'not_shareable', `#${b.message_id} is not a user's private message to a member`)
      const target = b.to ? shareTarget(dm.holder, b.to, false) : ''
      if (!S.marks.some(k => k.message_id === b.message_id && k.target === target)) S.marks.push({ message_id: b.message_id, target })
      bump(); return { ok: true }
    }
    case 'wake_host': {
      // 不等合并：扣住的结果马上投给主控
      const n = releaseHeld()
      if (S.hostWait.results_held !== undefined) S.hostWait.results_held = 0
      if ('wake_at' in S.hostWait) S.hostWait.wake_at = null
      bump(); return { ok: true, released: n }
    }
  }
}
const member = id => {
  const m = typeof id === 'string' ? S.members.get(id) : null
  if (!m) fail(404, 'unknown_member', `no member ${JSON.stringify(id)}`)
  return m
}
function newCode() {
  const ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
  for (;;) {
    const c = Array.from(crypto.randomBytes(6), x => ALPHABET[x % ALPHABET.length])
    const code = c.slice(0, 4).join('') + '-' + c.slice(4).join('')
    if (!S.invites.has(code)) return code
  }
}

// 注入口见 README.md
async function mockCtl(req, res, p, method) {
  try {
    return await mockCtl_(req, res, p, method)
  } catch (e) {
    if (e instanceof ApiErr) return err(res, e.status, e.code, e.message)
    throw e
  }
}
async function mockCtl_(req, res, p, method) {
  if (method === 'GET' && p === '/_mock/state') {
    return send(res, 200, {
      version: S.version, room: S.room, members: [...S.members.values()],
      messages: S.messages, approvals: S.approvals, alignment: S.alignment,
      acked: Object.fromEntries([...S.acked].map(([k, v]) => [k, [...v]])),
      invites: Object.fromEntries(S.invites),
      threads: [...S.threads.values()].map(t => ({ ...t, members: [...t.members].sort() })),
      removed: [...S.removed], marks: S.marks, waiting_on: S.waitingOn, host_wait: hostWaitView(),
      registry: REG, room_id: ROOM_ID,
    })
  }
  const b = (await readBody(req)) || {}
  if (p === '/_mock/reset') { resetState(); return send(res, 200, { ok: true }) }
  if (!S.room) return err(res, 409, 'no_room', '还没有房间（先 POST /v1/rooms 或用 --seed 启动）')
  switch (p) {
    case '/_mock/say': case '/_mock/send': {
      // 别的成员（或 from=human 模拟用户）发消息；成员发到不存在的 #群 并带 members：建私有小群（模拟 xmuse_send）
      if (b.from !== HUMAN && !S.members.has(b.from)) fail(404, 'unknown_member', `no member ${JSON.stringify(b.from)}`)
      const via = b.via ?? (b.from === HUMAN ? 'cli' : null)
      const r = sendMessage({ fromId: b.from, via, to: b.to, text: b.text, mentions: b.mentions, kind: b.kind || 'message', members: b.members, notify: b.notify })
      bump(); return send(res, 200, { id: r.msg.id, thread: r.msg.thread, ...(r.routed_to ? { routed_to: r.routed_to } : {}) })
    }
    case '/_mock/leave_thread': {
      // 模拟 xmuse_leave_thread
      if (typeof b.thread !== 'string' || !b.thread) fail(400, 'invalid_arguments', 'thread is required')
      const t = S.threads.get(b.thread)
      if (!member_(b.member) || !threadExists(b.thread) || (t && !t.members.has(b.member))) {
        fail(404, 'unknown_thread', `id must be one of your threads`)
      }
      if (!t) fail(400, 'public_thread', `${b.thread} is not a private group: you can only leave private groups`)
      t.members.delete(b.member)
      notice(t.id, `${b.member} left ${t.id}`)
      bump(); return send(res, 200, { ok: true, thread: t.id })
    }
    case '/_mock/done': {
      // 成员发 done：{from, summary, next?, outcome?, declares?, evidence?, evidence_status?, evidence_problems?, thread?, notify?}
      const r = memberDone(b)
      bump(); return send(res, 200, r.out)
    }
    case '/_mock/share': {
      // 成员调 xmuse_share：{member, message_id, to, why?}
      if (!S.members.has(b.member)) fail(404, 'unknown_member', `no member ${JSON.stringify(b.member)}`)
      const out = shareRequest(b)
      bump(); return send(res, 200, out)
    }
    case '/_mock/host_wait': {
      // 设置 view.host_wait：{waiting_on?, results_held?, wake_at?}；值为 null（wake_at 用 "auto"）取消覆盖；{reset:true} 全清
      const o = S.hostWait
      if (b.reset) for (const k of Object.keys(o)) delete o[k]
      for (const k of ['waiting_on', 'results_held']) if (k in b) { if (b[k] === null) delete o[k]; else o[k] = b[k] }
      if ('wake_at' in b) { if (b.wake_at === 'auto') delete o.wake_at; else o.wake_at = b.wake_at }
      bump(); return send(res, 200, hostWaitView())
    }
    case '/_mock/approval': {
      const ap = { id: 'A' + S.nextAppr++, kind: b.kind || 'shell', member: b.member, summary: b.summary || '', detail: b.detail || '', risk: b.risk || 'normal', at: now() }
      S.approvals.push(ap); bump(); return send(res, 200, ap)
    }
    case '/_mock/align': {
      const e = { id: 'E' + S.nextAlign++, kind: b.kind || 'decision', scope: b.scope || 'room', author: b.author || 'coord', text: b.text || '', supersedes: b.supersedes ?? null, status: b.status || 'active', at: now() }
      S.alignment.push(e)
      if (e.status === 'proposed') {
        S.approvals.push({ id: e.id, kind: 'alignment', member: e.author, summary: `${e.kind}: ${e.text}`.slice(0, 200), detail: e.text, risk: 'normal', at: e.at })
      }
      bump(); return send(res, 200, e)
    }
    case '/_mock/invite': {
      const code = newCode()
      const expires_at = now() + INVITE_TTL
      S.invites.set(code, { vendor: b.vendor, role: b.role || 'executor', description: b.description || '', name: b.name || null, expires_at, used: false })
      bump(); return send(res, 200, { code, expires_at, command: `/xmuse join ${code}` })
    }
    case '/_mock/member': {
      const m = newMember({ id: b.id, vendor: b.vendor || 'dsh', model: b.model, role: b.role || 'executor', description: b.description, session_id: null, bound: false })
      m.online = b.online !== false; m.status = b.status || (m.online ? 'idle' : 'offline')
      for (const k of ['wakes_hour', 'tokens_hour', 'tokens_hour_cap']) if (typeof b[k] === 'number') m[k] = b[k]
      bump(); return send(res, 200, { ok: true })
    }
    case '/_mock/status': {
      const m = S.members.get(b.member); if (!m) return err(res, 404, 'unknown_member', '没有这个成员')
      if (b.status) m.status = b.status
      for (const k of ['wakes_hour', 'tokens_hour', 'tokens_hour_cap']) if (typeof b[k] === 'number') m[k] = b[k]
      bump(); return send(res, 200, { ok: true })
    }
    default: return err(res, 404, 'not_found', '没有这个注入口')
  }
}
const member_ = id => (typeof id === 'string' ? S.members.get(id) : null)

function resetState() {
  S.room = null; S.members.clear(); S.removed.clear(); S.tokens.clear(); S.invites.clear(); S.messages = []
  S.acked.clear(); S.threads.clear(); S.alignment = []; S.approvals = []; S.marks = []; S.decided.clear()
  S.waitingOn = []; S.hostWait = {}
  S.nextMsg = 1001; S.nextAppr = 1; S.nextAlign = 1; S.nextShare = 1
  regSync()
  bump()
}

// ---------- 启动 ----------
if (REG) ensureKey()
if (SEED) {
  const r = createRoom({ dir: WS_DIR || process.cwd(), name: 'mock-room', vendor: 'claude', session_id: null, member_id: String(SEED), description: '假主控' })
  S.members.get(String(SEED)).online = true
  S.members.get(String(SEED)).status = 'idle'
  console.log('seed ' + JSON.stringify({ member_id: String(SEED), member_token: r.member_token, operator_token: r.operator_token }))
}

const server = http.createServer((req, res) => {
  handle(req, res).catch(e => {
    if (e instanceof ApiErr) return err(res, e.status, e.code, e.message)
    log('error', e); if (!res.headersSent) err(res, 500, 'internal', String(e))
  })
})
server.listen(PORT, '127.0.0.1', () => {
  const addr = server.address()
  HUB_URL = `http://127.0.0.1:${addr.port}`
  if (STATE_DIR) {
    fs.mkdirSync(STATE_DIR, { recursive: true })
    fs.writeFileSync(path.join(STATE_DIR, 'hub.json'), JSON.stringify({ port: addr.port, pid: process.pid, mock: true }))
  }
  if (REG) { regSync(); console.log(`registry ${REG}`) }
  console.log(`mock-hub listening on ${HUB_URL}`) // 最后打印：看到这行时登记表和 hub.json 都已写好
})
process.on('exit', regLeave)
for (const sig of ['SIGINT', 'SIGTERM', 'SIGHUP']) process.on(sig, () => process.exit(0))
