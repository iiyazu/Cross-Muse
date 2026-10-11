#!/usr/bin/env node
// xmuse 2 mock hub：按 docs/design/XMUSE2-VIEW-API.zh.md（约定 v0）实现的内存假 hub。
// 无依赖，只监听 127.0.0.1。三家侧栏在 D2 的真 hub 完成前都用它开发和测试。
// 用法见同目录 README.md。
import http from 'node:http'
import fs from 'node:fs'
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

const now = () => Date.now() / 1000
const rid = n => crypto.randomBytes(n).toString('hex')
const log = (...a) => { if (!QUIET) console.error('[mock-hub]', ...a) }

// ---------- 状态 ----------
const S = {
  version: 1,
  room: null,
  members: new Map(), // id -> member
  tokens: new Map(), // token -> {kind:'member'|'operator', member}
  invites: new Map(), // code -> {vendor, role, description, name, expires_at, used}
  messages: [], // timeline，按 id 递增
  acked: new Map(), // member id -> Set(message id)
  alignment: [],
  approvals: [],
  nextMsg: 1001,
  nextAppr: 1,
  nextAlign: 1,
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
    tokens_hour: 0, tokens_hour_cap: 0, session_id: session_id || null,
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

function createRoom({ dir, name, vendor, session_id, member_id, description }) {
  S.room = {
    id: 'r-' + rid(2), name, dir, host: member_id, info_layer: 'on', created_at: now(),
  }
  const m = newMember({
    id: member_id, vendor, role: 'coordinator',
    description: description || '主控', session_id, bound: !!session_id,
  })
  return { m, ...issueTokens(m) }
}

// ---------- 消息 ----------
function dmThread(a, b) { return 'dm:' + [a, b].sort().join('+') }

function parseMentions(text) {
  const out = []
  for (const mm of text.matchAll(/@([\w.-]+)/g)) if (S.members.has(mm[1]) && !out.includes(mm[1])) out.push(mm[1])
  return out
}

function addMessage({ thread, from, via = null, to, mentions, text, kind = 'message' }) {
  const msg = {
    id: S.nextMsg++, thread, from, via, to, mentions: mentions || [], kind, text, at: now(),
  }
  S.messages.push(msg)
  return msg
}

function resolveSay({ fromId, via, to, text, mentions }) {
  // to: 成员 id / #话题 / 线程 id（dm:.. 或 #..）
  let thread, recips
  const others = [...S.members.keys()].filter(k => k !== fromId)
  if (to.startsWith('#')) { thread = to; recips = others }
  else if (to.startsWith('dm:')) {
    thread = to
    recips = to.slice(3).split('+').filter(x => x !== fromId)
  } else if (S.members.has(to)) { thread = dmThread(fromId, to); recips = [to] }
  else return null
  const ms = [...new Set([...(mentions || []), ...parseMentions(text)])]
  return addMessage({ thread, from: fromId, via, to: recips, mentions: ms, text })
}

function forMe(msg, memberId) {
  if (!memberId || msg.from === memberId) return false
  return msg.to.includes(memberId) || msg.mentions.includes(memberId)
}

function unreadFor(memberId) {
  const acked = S.acked.get(memberId) || new Set()
  return S.messages.filter(m => forMe(m, memberId) && !acked.has(m.id))
}

// ---------- 视图 ----------
function threadsFor() {
  const map = new Map()
  for (const m of S.messages) {
    let t = map.get(m.thread)
    if (!t) {
      t = {
        id: m.thread, kind: m.thread.startsWith('#') ? 'topic' : 'dm', title: m.thread,
        members: m.thread.startsWith('dm:') ? m.thread.slice(3).split('+') : [...S.members.keys()],
        last_at: m.at, unread: 0,
      }
      if (t.kind === 'dm') t.title = t.members.join(' ↔ ')
      map.set(m.thread, t)
    }
    t.last_at = m.at
  }
  return [...map.values()].sort((a, b) => b.last_at - a.last_at)
}

function view(reader) {
  const meMember = reader.member
  const acked = S.acked.get(meMember) || new Set()
  const members = [...S.members.values()].map(m => {
    const { session_id, ...pub } = m
    return { ...pub, unread: unreadFor(m.id).length }
  })
  const threads = threadsFor().map(t => ({
    ...t,
    unread: S.messages.filter(m => m.thread === t.id && forMe(m, meMember) && !acked.has(m.id)).length,
  }))
  const slice = S.messages.slice(-50)
  const timeline = slice.map(m => ({ ...m, for_me: forMe(m, meMember) }))
  return {
    version: S.version,
    room: S.room,
    me: { kind: reader.kind, id: meMember },
    members, threads, timeline,
    timeline_cursor: { oldest: slice.length ? slice[0].id : 0, has_more: S.messages.length > slice.length },
    alignment: S.alignment,
    approvals: S.approvals,
    run: null,
  }
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
    const limit = Math.min(200, Number(url.searchParams.get('limit') || 50))
    const older = S.messages.filter(m => m.id < before)
    const items = older.slice(-limit).map(m => ({ ...m, for_me: forMe(m, a.member) }))
    return send(res, 200, { items, has_more: older.length > items.length })
  }

  if (method === 'POST' && p === '/v1/rooms') {
    const b = await readBody(req); if (!b) return err(res, 400, 'bad_json', '无效 JSON')
    if (S.room) return err(res, 409, 'room_exists', '已有房间')
    for (const k of ['dir', 'name', 'vendor', 'session_id']) if (!b[k]) return err(res, 400, 'missing_field', '缺少 ' + k)
    const r = createRoom({ ...b, member_id: b.member_id || 'host' })
    bump()
    return send(res, 200, { room: S.room, member_token: r.member_token, operator_token: r.operator_token, member_id: r.m.id })
  }

  if (method === 'POST' && p === '/v1/join') {
    const b = await readBody(req); if (!b) return err(res, 400, 'bad_json', '无效 JSON')
    const inv = S.invites.get(b.code)
    if (!inv) return err(res, 404, 'no_such_code', '邀请码不存在')
    if (inv.used) return err(res, 409, 'code_used', '邀请码已用过')
    if (inv.expires_at < now()) return err(res, 410, 'code_expired', '邀请码已过期')
    if (inv.vendor !== b.vendor) return err(res, 403, 'vendor_mismatch', '邀请码是给 ' + inv.vendor + ' 的')
    if (!b.session_id) return err(res, 400, 'missing_field', '缺少 session_id')
    inv.used = true
    let id = inv.name || `${inv.vendor}-${rid(2)}`
    while (S.members.has(id)) id += '2'
    const m = newMember({ id, vendor: inv.vendor, model: (b.client_info && b.client_info.model) || '', role: inv.role, description: inv.description, session_id: b.session_id, bound: true })
    const t = issueTokens(m)
    addMessage({ thread: '#room', from: 'hub', to: [], mentions: [], kind: 'system', text: `${id}（${inv.vendor}/${inv.role}）已加入` })
    bump()
    return send(res, 200, { member_id: id, ...t })
  }

  if (method === 'POST' && p === '/v1/rebind') {
    const h = req.headers['authorization'] || ''
    const t = S.tokens.get(h.startsWith('Bearer ') ? h.slice(7) : '')
    if (!t || t.kind !== 'member') return err(res, 401, 'unauthorized', '需要成员令牌')
    const b = await readBody(req); if (!b || !b.session_id) return err(res, 400, 'missing_field', '缺少 session_id')
    const m = S.members.get(t.member); m.session_id = b.session_id; m.online = true; m.status = 'idle'
    bump()
    return send(res, 200, { ok: true })
  }

  if (method === 'POST' && p === '/v1/leave') {
    const a = auth(req, res); if (!a) return
    if (a.kind !== 'member') return err(res, 403, 'forbidden', '需要成员令牌')
    const m = S.members.get(a.member); m.session_id = null; m.online = false; m.status = 'offline'
    for (const [tk, v] of S.tokens) if (v.member === a.member) S.tokens.delete(tk)
    bump()
    return send(res, 200, { ok: true })
  }

  if (method === 'POST' && p === '/v1/act') {
    const a = auth(req, res); if (!a) return
    const b = await readBody(req); if (!b || !b.act) return err(res, 400, 'bad_request', '缺少 act')
    return act(res, a, b)
  }

  err(res, 404, 'not_found', '没有这个接口')
}

function act(res, a, b) {
  const isOp = a.kind === 'operator'
  const memberOnly = new Set(['say', 'ack'])
  if (!isOp && !memberOnly.has(b.act)) return err(res, 403, 'forbidden', '成员令牌不能做 ' + b.act)
  const actor = S.members.get(a.member)
  switch (b.act) {
    case 'say': {
      if (!b.to || typeof b.text !== 'string' || !b.text) return err(res, 400, 'bad_request', 'say 需要 to 和 text')
      const fromId = isOp ? 'human' : a.member
      const via = isOp ? `${actor ? actor.vendor : '?'} sidebar` : null
      const msg = resolveSay({ fromId, via, to: b.to, text: b.text, mentions: b.mentions })
      if (!msg) return err(res, 404, 'no_such_target', '没有这个收件人或话题')
      bump()
      return send(res, 200, { id: msg.id })
    }
    case 'ack': {
      const set = S.acked.get(a.member)
      for (const id of b.ids || []) set.add(id)
      bump()
      return send(res, 200, { ok: true })
    }
    case 'approve': {
      const i = S.approvals.findIndex(x => x.id === b.id)
      if (i < 0) return err(res, 404, 'no_such_approval', '没有这个审批')
      if (!['once', 'always', 'reject'].includes(b.decision)) return err(res, 400, 'bad_request', 'decision 无效')
      const [ap] = S.approvals.splice(i, 1)
      addMessage({ thread: '#room', from: 'hub', to: [], mentions: [], kind: 'system', text: `审批 ${ap.id}（${ap.member}：${ap.summary}）→ ${b.decision}` })
      bump()
      return send(res, 200, { ok: true })
    }
    case 'invite': {
      if (!b.vendor || !b.role) return err(res, 400, 'bad_request', 'invite 需要 vendor 和 role')
      const code = (rid(2) + '-' + rid(1)).toUpperCase().slice(0, 7)
      const expires_at = now() + INVITE_TTL
      S.invites.set(code, { vendor: b.vendor, role: b.role, description: b.description || '', name: b.name || null, expires_at, used: false })
      bump()
      return send(res, 200, { code, expires_at, command: `/xmuse join ${code}` })
    }
    case 'remove': {
      const m = S.members.get(b.member)
      if (!m) return err(res, 404, 'no_such_member', '没有这个成员')
      S.members.delete(b.member)
      for (const [tk, v] of S.tokens) if (v.member === b.member) S.tokens.delete(tk)
      bump(); return send(res, 200, { ok: true })
    }
    case 'pause': case 'resume': {
      const m = S.members.get(b.member)
      if (!m) return err(res, 404, 'no_such_member', '没有这个成员')
      m.paused = b.act === 'pause'; m.status = m.paused ? 'paused' : (m.online ? 'idle' : 'offline')
      bump(); return send(res, 200, { ok: true })
    }
    case 'transfer_host': {
      if (!S.members.has(b.member)) return err(res, 404, 'no_such_member', '没有这个成员')
      S.room.host = b.member; bump(); return send(res, 200, { ok: true })
    }
    case 'align': {
      const e = S.alignment.find(x => x.id === b.id)
      if (!e) return err(res, 404, 'no_such_entry', '没有这个对齐条目')
      e.status = b.decision === 'confirm' ? 'active' : 'rejected'
      bump(); return send(res, 200, { ok: true })
    }
    default:
      return err(res, 400, 'unknown_act', '未知 act：' + b.act)
  }
}

// 注入口：POST /_mock/say  {from, to, text, mentions?, via?}  —— 别的成员发来的消息
//          POST /_mock/approval {member, kind?, summary, detail?, risk?}
//          POST /_mock/align {kind, scope, author, text, status?}
//          POST /_mock/invite {vendor, role, description, name?} → {code,..}（免令牌）
//          POST /_mock/member {id, vendor, role, description, status?, online?} —— 直接加一个假成员
//          POST /_mock/status {member, status}
//          GET  /_mock/state    POST /_mock/reset
async function mockCtl(req, res, p, method) {
  if (method === 'GET' && p === '/_mock/state') {
    return send(res, 200, {
      version: S.version, room: S.room, members: [...S.members.values()],
      messages: S.messages, approvals: S.approvals, alignment: S.alignment,
      acked: Object.fromEntries([...S.acked].map(([k, v]) => [k, [...v]])),
      invites: Object.fromEntries(S.invites),
    })
  }
  const b = (await readBody(req)) || {}
  if (p === '/_mock/reset') { resetState(); return send(res, 200, { ok: true }) }
  if (!S.room) return err(res, 409, 'no_room', '还没有房间（先 POST /v1/rooms 或用 --seed 启动）')
  switch (p) {
    case '/_mock/say': {
      const msg = resolveSay({ fromId: b.from, via: b.via ?? null, to: b.to, text: b.text, mentions: b.mentions })
      if (!msg) return err(res, 404, 'no_such_target', '没有这个收件人或话题')
      bump(); return send(res, 200, { id: msg.id })
    }
    case '/_mock/approval': {
      const ap = { id: 'A' + S.nextAppr++, kind: b.kind || 'shell', member: b.member, summary: b.summary || '', detail: b.detail || '', risk: b.risk || 'normal', at: now() }
      S.approvals.push(ap); bump(); return send(res, 200, ap)
    }
    case '/_mock/align': {
      const e = { id: 'E' + S.nextAlign++, kind: b.kind || 'decision', scope: b.scope || 'room', author: b.author || 'coord', text: b.text || '', supersedes: b.supersedes ?? null, status: b.status || 'active', at: now() }
      S.alignment.push(e); bump(); return send(res, 200, e)
    }
    case '/_mock/invite': {
      const code = (rid(2) + '-' + rid(1)).toUpperCase().slice(0, 7)
      const expires_at = now() + INVITE_TTL
      S.invites.set(code, { vendor: b.vendor, role: b.role || 'executor', description: b.description || '', name: b.name || null, expires_at, used: false })
      bump(); return send(res, 200, { code, expires_at, command: `/xmuse join ${code}` })
    }
    case '/_mock/member': {
      const m = newMember({ id: b.id, vendor: b.vendor || 'dsh', model: b.model, role: b.role || 'executor', description: b.description, session_id: null, bound: false })
      m.online = b.online !== false; m.status = b.status || (m.online ? 'idle' : 'offline')
      bump(); return send(res, 200, { ok: true })
    }
    case '/_mock/status': {
      const m = S.members.get(b.member); if (!m) return err(res, 404, 'no_such_member', '没有这个成员')
      m.status = b.status; bump(); return send(res, 200, { ok: true })
    }
    default: return err(res, 404, 'not_found', '没有这个注入口')
  }
}

function resetState() {
  S.room = null; S.members.clear(); S.tokens.clear(); S.invites.clear(); S.messages = []
  S.acked.clear(); S.alignment = []; S.approvals = []
  S.nextMsg = 1001; S.nextAppr = 1; S.nextAlign = 1
  bump()
}

// ---------- 启动 ----------
if (SEED) {
  const r = createRoom({ dir: process.cwd(), name: 'mock-room', vendor: 'claude', session_id: null, member_id: String(SEED), description: '假主控' })
  S.members.get(String(SEED)).online = true
  S.members.get(String(SEED)).status = 'idle'
  console.log('seed ' + JSON.stringify({ member_id: String(SEED), member_token: r.member_token, operator_token: r.operator_token }))
}

const server = http.createServer((req, res) => {
  handle(req, res).catch(e => { log('error', e); if (!res.headersSent) err(res, 500, 'internal', String(e)) })
})
server.listen(PORT, '127.0.0.1', () => {
  const addr = server.address()
  console.log(`mock-hub listening on http://127.0.0.1:${addr.port}`)
  if (STATE_DIR) {
    fs.mkdirSync(STATE_DIR, { recursive: true })
    fs.writeFileSync(path.join(STATE_DIR, 'hub.json'), JSON.stringify({ port: addr.port, pid: process.pid, mock: true }))
  }
})
