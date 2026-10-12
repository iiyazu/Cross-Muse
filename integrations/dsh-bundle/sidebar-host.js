// xmuse dsh-bundle 侧栏（抽屉）宿主侧：XMUSE2-VIEW-API v0。
//
// 浏览器永远拿不到令牌：前端只调同源的 /xmuse/* 路由，宿主在这里加上
// operator 令牌再转发到 hub（127.0.0.1:<port>）。路由前缀与宿主自带的
// /api 一样加 connection.requestRejection 栅栏（dsh web 可能绑 0.0.0.0）。
// 做法来源：experiments/d0-probes/dsh-drawer-probe（D0 已验证）。
import http from 'node:http'
import { readFile, writeFile, rm } from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'

export const SIDEBAR_PREFIX = '/xmuse'
const MAX_BODY = 256 * 1024
// 前端长轮询挂起最长 30s，转发超时必须比它大。
const PROXY_TIMEOUT_MS = 40 * 1000

const errText = (e) => (e && e.message) || String(e)

/** 与宿主 /api 同样的栅栏；没有 connection 服务时退化成只放行回环 Host。 */
export function refusalOf(ctx, req) {
  try {
    const connection = ctx.get('connection')
    if (typeof connection?.requestRejection === 'function') return connection.requestRejection(req)
  } catch { /* fall through to the local fence */ }
  const host = req.headers.host
  if (host !== undefined) {
    let hostname
    try { hostname = new URL(`http://${host}`).hostname } catch { return 403 }
    if (hostname !== 'localhost' && hostname !== '[::1]' && !/^127\.\d+\.\d+\.\d+$/.test(hostname)) return 403
  }
  return undefined
}

/** 直连 hub（node:http，不走 fetch 代理）。body 为 undefined 时不发 body。host 缺省 127.0.0.1。 */
export function hubRequest(port, method, path, { host = '127.0.0.1', token, sessionId, headers, body, timeoutMs = PROXY_TIMEOUT_MS } = {}) {
  return new Promise((resolve, reject) => {
    const payload = body === undefined || body === null
      ? null
      : Buffer.from(typeof body === 'string' ? body : JSON.stringify(body))
    const req = http.request({
      host, port, path, method,
      headers: {
        'content-type': 'application/json',
        ...(payload ? { 'content-length': payload.length } : {}),
        ...(token ? { authorization: `Bearer ${token}` } : {}),
        ...(sessionId ? { 'x-xmuse-session': sessionId } : {}),
        ...(headers ?? {}),
      },
      timeout: timeoutMs,
    }, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('error', reject)
      res.on('end', () => resolve({ status: res.statusCode ?? 502, body: Buffer.concat(chunks) }))
    })
    req.on('timeout', () => req.destroy(new Error('hub request timed out')))
    req.on('error', reject)
    req.end(payload ?? undefined)
  })
}

const parseJson = (buf) => {
  const text = buf.toString('utf8') || '{}'
  try { return JSON.parse(text) } catch { return { _raw: text } }
}

/** 侧栏令牌存放在宿主进程侧（sidebar.json），{memberId, memberToken, operatorToken, sessionId, hubPort?}。
 * hubPort 是令牌所属 hub 的端口（一键加入别的房间后，转发跟令牌走，不再读 hub.json）。 */
export function createTokenStore(file) {
  let cur = null
  const norm = (t) => ({
    memberId: t.memberId ?? null,
    memberToken: t.memberToken,
    operatorToken: t.operatorToken,
    sessionId: t.sessionId ?? null,
    hubPort: Number.isInteger(t.hubPort) ? t.hubPort : null,
  })
  return {
    get: () => cur,
    load: async () => {
      try {
        const data = JSON.parse(await readFile(file, 'utf8'))
        cur = (data && data.memberToken && data.operatorToken) ? norm(data) : null
      } catch { cur = null }
      return cur
    },
    save: async (t) => {
      cur = norm(t)
      await writeFile(file, JSON.stringify({ version: 1, ...cur }, null, 2))
      return cur
    },
    clear: async () => {
      cur = null
      try { await rm(file, { force: true }) } catch { /* ignore */ }
    },
  }
}

/** 本机登记表目录：显式配置 > XMUSE_REGISTRY_DIR > 平台默认（约定 8.1）。读不到/没配时返回 null。 */
export function resolveRegistryDir(explicit) {
  if (explicit) return explicit
  if (process.env.XMUSE_REGISTRY_DIR) return process.env.XMUSE_REGISTRY_DIR
  if (process.platform === 'win32') return path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local'), 'xmuse')
  return path.join(process.env.XDG_STATE_HOME || path.join(os.homedir(), '.local', 'state'), 'xmuse')
}

export function pidAlive(pid) {
  try { process.kill(pid, 0); return true } catch (e) { return e && e.code === 'EPERM' }
}

/** 读 hubs.json，只留 pid 还在的条目。目录没配或读不到返回 []。 */
export async function readRegistry(regDir) {
  if (!regDir) return []
  try {
    const data = JSON.parse(await readFile(path.join(regDir, 'hubs.json'), 'utf8'))
    const hubs = Array.isArray(data.hubs) ? data.hubs : []
    return hubs.filter((e) => e && typeof e === 'object' && Number.isInteger(e.pid) && pidAlive(e.pid))
  } catch { return [] }
}

/** 读 sidebar.key。只在宿主进程里用：绝不传给前端、不写日志。读不到返回 null。 */
export async function readSidebarKey(regDir) {
  if (!regDir) return null
  try {
    const k = (await readFile(path.join(regDir, 'sidebar.key'), 'utf8')).trim()
    return k ? k : null
  } catch { return null }
}

/** 和 hub 侧相同的目录比较：Windows 写法和 /mnt/c 写法视为同一目录。 */
export function normDir(s) {
  s = String(s)
  const m = s.match(/^\/mnt\/([a-z])\/(.*)$/i)
  if (m) s = `${m[1]}:\\${m[2].replace(/\//g, '\\')}`
  if (/^[A-Za-z]:|^\\\\/.test(s)) return s.replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase()
  return s.replace(/\/+$/, '')
}

/**
 * @param readHub () => Promise<{port}>  hub.json 的端口（令牌没记 hubPort 时用）
 * @param store token store（createTokenStore）
 * @param clientFile 前端单文件 client.js 的绝对路径
 * @param getService (name) => service | undefined  透给 connection.requestRejection 栅栏
 * @param registryDir 本机登记表目录（显式配置；空则按约定 8.1 推导）
 */
export function createSidebar({ readHub, store, clientFile, log = () => {}, getService = () => undefined, registryDir = '' }) {
  const regDir = () => resolveRegistryDir(registryDir || '')
  /** 转发目标端口：跟令牌走（一键加入别的房间后），没记才读 hub.json。 */
  const portOf = async () => {
    const t = store.get()
    if (t && Number.isInteger(t.hubPort)) return t.hubPort
    return (await readHub()).port
  }
  /** 侧栏凭据头（约定 8.1）：读不到 key 时返回空，hub 侧按 v0 兼容/401 处理。 */
  const keyHeaders = async () => {
    const k = await readSidebarKey(regDir())
    return k ? { 'x-xmuse-sidebar': k } : {}
  }
  const json = (res, status, obj) => {
    const text = JSON.stringify(obj)
    res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', 'content-length': Buffer.byteLength(text) })
    res.end(text)
  }

  const readBody = (req) => new Promise((resolve, reject) => {
    const chunks = []
    let size = 0
    req.on('data', (c) => {
      size += c.length
      if (size > MAX_BODY) { reject(new Error('body too large')); req.destroy(); return }
      chunks.push(c)
    })
    req.on('end', () => {
      const text = Buffer.concat(chunks).toString('utf8')
      if (!text) return resolve({})
      try { resolve(JSON.parse(text)) } catch { reject(new Error('bad json')) }
    })
    req.on('error', reject)
  })

  /** 需要操作令牌的代理：GET /v1/view、GET /v1/timeline、POST /v1/act。 */
  const proxyAuthed = async (req, res, method, hubPath) => {
    const t = store.get()
    if (!t) return json(res, 409, { error: 'no_room', message: '侧栏还没有加入房间：先在房间页一键加入，或用邀请码加入，或开一个新房间' })
    let port
    try { port = await portOf() } catch (e) { return json(res, 502, { error: 'hub_unreachable', message: errText(e) }) }
    try {
      const r = await hubRequest(port, method, hubPath, {
        token: t.operatorToken,
        sessionId: req.headers['x-xmuse-session'] || undefined,
        body: method === 'POST' ? await readBody(req) : undefined,
      })
      res.writeHead(r.status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
      res.end(r.body)
    } catch (e) {
      log('warn', `sidebar proxy ${hubPath} failed: ${errText(e)}`)
      json(res, 502, { error: 'hub_unreachable', message: errText(e) })
    }
  }

  /** POST /v1/rooms：开房间，调用者成为主控。v0.1 起要带 x-xmuse-sidebar（有 key 才带）。
   * 成功只把 member_id 和 room 给浏览器，令牌留下。 */
  const createRoom = async ({ dir, name, vendor = 'dsh', sessionId, memberId, description }) => {
    if (!dir || !name) {
      const e = new Error('rooms 需要 dir 和 name')
      e.code = 'missing_field'
      e.status = 400
      throw e
    }
    let hub
    try { hub = await readHub() } catch (e) { e.status = 502; throw e }
    const body = { dir, name, vendor, session_id: sessionId }
    if (memberId) body.member_id = memberId
    if (description) body.description = description
    const r = await hubRequest(hub.port, 'POST', '/v1/rooms', { body, headers: await keyHeaders() })
    const data = parseJson(r.body)
    if (r.status !== 200) {
      const e = new Error(`hub ${r.status}: ${data.error ?? data.message ?? 'rooms failed'}`)
      e.code = data.error
      e.status = r.status
      throw e
    }
    await store.save({ memberId: data.member_id, memberToken: data.member_token, operatorToken: data.operator_token, sessionId, hubPort: hub.port })
    return { room: data.room, member_id: data.member_id }
  }

  /** POST /v1/join（邀请码路径）：码一次性、过期、vendor 不符都由 hub 校验。key 有就带上。 */
  const joinRoom = async ({ code, vendor = 'dsh', sessionId, clientInfo }) => {
    if (!code) {
      const e = new Error('join 需要邀请码')
      e.code = 'missing_field'
      e.status = 400
      throw e
    }
    let hub
    try { hub = await readHub() } catch (e) { e.status = 502; throw e }
    const r = await hubRequest(hub.port, 'POST', '/v1/join', {
      body: { code, vendor, session_id: sessionId, client_info: clientInfo ?? { client: 'dsh-sidebar' } },
      headers: await keyHeaders(),
    })
    const data = parseJson(r.body)
    if (r.status !== 200) {
      const e = new Error(`hub ${r.status}: ${data.error ?? data.message ?? 'join failed'}`)
      e.code = data.error
      e.status = r.status
      throw e
    }
    await store.save({ memberId: data.member_id, memberToken: data.member_token, operatorToken: data.operator_token, sessionId, hubPort: hub.port })
    return { member_id: data.member_id }
  }

  /** 本机登记表：只留 pid 还在的条目。目录没配返回空列表 + 说明，前端降级显示。 */
  const listRooms = async () => {
    const kd = regDir()
    if (!kd) return { hubs: [], note: '本机登记表未配置（XMUSE_REGISTRY_DIR / registryDir），房间列表不可用' }
    const hubs = await readRegistry(kd)
    return { hubs: hubs.map((e) => ({ ...e, alive: true })) }
  }

  /** 一键加入本机房间（约定 8.1，不带 code 的 join）：按 room_id 或 dir 在登记表里找 hub，
   * 直连它的 url，用 sidebar.key 加入。之后 view/act 转发都跟令牌走这个 hub。 */
  const joinLocal = async ({ roomId, dir, vendor = 'dsh', sessionId, name, role, description, clientInfo }) => {
    const kd = regDir()
    if (!kd) {
      const e = new Error('本机登记表未配置：设 XMUSE_REGISTRY_DIR 或 registryDir')
      e.code = 'no_registry'; e.status = 502; throw e
    }
    const key = await readSidebarKey(kd)
    if (!key) {
      const e = new Error('读不到 sidebar.key：hub 还没生成它，或登记表目录不对')
      e.code = 'no_sidebar_key'; e.status = 502; throw e
    }
    if (!roomId && !dir) {
      const e = new Error('join-local 需要 room_id 或 dir')
      e.code = 'missing_field'; e.status = 400; throw e
    }
    const entries = await readRegistry(kd)
    let entry = null
    if (roomId) entry = entries.find((e) => e.room_id === roomId) || null
    else entry = entries.find((e) => e.dir && normDir(e.dir) === normDir(dir)) || null
    if (!entry) {
      if (!entries.length) {
        const e = new Error('本机没有登记的房间')
        e.code = 'no_room'; e.status = 404; throw e
      }
      if (roomId) {
        const e = new Error(`不认识的房间 ${roomId}`)
        e.code = 'unknown_room'; e.status = 404; throw e
      }
      const e = new Error(`没有服务 ${dir} 的房间`)
      e.code = 'wrong_dir'; e.status = 400; throw e
    }
    if (roomId && dir && entry.dir && normDir(entry.dir) !== normDir(dir)) {
      const e = new Error('dir 与 room_id 对不上')
      e.code = 'wrong_dir'; e.status = 400; throw e
    }
    let hu
    try { hu = new URL(entry.url) } catch {
      const e = new Error('登记表里的 url 非法')
      e.code = 'bad_registry'; e.status = 502; throw e
    }
    if (!/^(localhost|127\.\d+\.\d+\.\d+|\[?::1\]?)$/.test(hu.hostname)) {
      const e = new Error('登记表里的 url 不是回环地址，拒绝连接')
      e.code = 'not_loopback'; e.status = 502; throw e
    }
    const port = Number(hu.port) || (hu.protocol === 'https:' ? 443 : 80)
    const body = { room_id: entry.room_id, vendor, session_id: sessionId }
    if (name) body.name = name
    if (role) body.role = role
    if (description) body.description = description
    if (clientInfo) body.client_info = clientInfo
    const r = await hubRequest(port, 'POST', '/v1/join', {
      host: hu.hostname.replace(/^\[(.*)\]$/, '$1'),
      body, headers: { 'x-xmuse-sidebar': key },
    })
    const data = parseJson(r.body)
    if (r.status !== 200) {
      const e = new Error(`hub ${r.status}: ${data.error ?? data.message ?? 'join failed'}`)
      e.code = data.error
      e.status = r.status
      throw e
    }
    await store.save({ memberId: data.member_id, memberToken: data.member_token, operatorToken: data.operator_token, sessionId, hubPort: port })
    return { member_id: data.member_id, room: data.room }
  }

  /** POST /v1/leave（成员令牌）：解绑。hub 挂了也清本地，调用方在返回里说明。 */
  const leaveRoom = async () => {
    const t = store.get()
    if (!t) return { ok: true, already: true }
    let hubNote = 'hub binding cleared'
    try {
      const hub = await readHub()
      const r = await hubRequest(hub.port, 'POST', '/v1/leave', { token: t.memberToken, sessionId: t.sessionId })
      if (r.status !== 200) hubNote = `hub said ${r.status} ${parseJson(r.body).error ?? ''}`.trim()
    } catch (e) {
      hubNote = `hub NOT told (${errText(e)}); 本地已解绑`
    }
    await store.clear()
    return { ok: true, note: hubNote }
  }

  const status = () => {
    const t = store.get()
    return { bound: !!t, memberId: t?.memberId ?? null, hubPort: t?.hubPort ?? null }
  }

  const handle = async (req, res) => {
    try {
      const rejected = refusalOf({ get: getService }, req)
      if (rejected !== undefined) { res.writeHead(rejected); res.end('refused'); return }
      const url = new URL(req.url ?? '/', 'http://127.0.0.1')
      const rest = url.pathname.slice(SIDEBAR_PREFIX.length) || '/'
      if (req.method === 'GET' && rest === '/sidebar.js') {
        try {
          const text = await readFile(clientFile, 'utf8')
          res.writeHead(200, { 'content-type': 'text/javascript; charset=utf-8', 'cache-control': 'no-store', 'content-length': Buffer.byteLength(text) })
          res.end(text)
        } catch (e) {
          json(res, 502, { error: 'no_client', message: errText(e) })
        }
        return
      }
      if (req.method === 'GET' && rest === '/ping') {
        const st = status()
        return json(res, 200, { ok: true, at: Date.now(), bound: st.bound, member: st.memberId })
      }
      if (req.method === 'GET' && rest === '/status') return json(res, 200, status())
      if (req.method === 'GET' && rest === '/rooms') {
        // 本机房间列表（读登记表 hubs.json）：房间名、目录、主控、在线状态，每间一键加入。
        try {
          return json(res, 200, await listRooms())
        } catch (e) {
          log('warn', `sidebar rooms failed: ${errText(e)}`)
          return json(res, 502, { error: 'rooms_failed', message: errText(e) })
        }
      }
      if (req.method === 'GET' && rest === '/view') {
        return proxyAuthed(req, res, 'GET', '/v1/view' + url.search)
      }
      if (req.method === 'GET' && rest === '/timeline') {
        return proxyAuthed(req, res, 'GET', '/v1/timeline' + url.search)
      }
      if (req.method === 'POST' && rest === '/act') {
        return proxyAuthed(req, res, 'POST', '/v1/act')
      }
      if (req.method === 'POST' && rest === '/rooms') {
        let b
        try { b = await readBody(req) } catch (e) { return json(res, 400, { error: 'bad_json', message: errText(e) }) }
        try {
          const out = await createRoom({
            dir: b.dir, name: b.name, memberId: b.member_id, description: b.description,
            sessionId: req.headers['x-xmuse-session'] || b.session_id || store.get()?.sessionId || 'dsh-sidebar',
          })
          return json(res, 200, out)
        } catch (e) {
          return json(res, e.status ?? 502, { error: e.code ?? 'rooms_failed', message: errText(e) })
        }
      }
      if (req.method === 'POST' && rest === '/join') {
        let b
        try { b = await readBody(req) } catch (e) { return json(res, 400, { error: 'bad_json', message: errText(e) }) }
        try {
          const out = await joinRoom({
            code: b.code,
            sessionId: req.headers['x-xmuse-session'] || b.session_id || store.get()?.sessionId || 'dsh-sidebar',
          })
          return json(res, 200, out)
        } catch (e) {
          return json(res, e.status ?? 502, { error: e.code ?? 'join_failed', message: errText(e) })
        }
      }
      if (req.method === 'POST' && rest === '/join-local') {
        // 一键加入本机房间（约定 8.1）：{room_id} 或 {dir}，key 只在宿主侧带上。
        let b
        try { b = await readBody(req) } catch (e) { return json(res, 400, { error: 'bad_json', message: errText(e) }) }
        try {
          const out = await joinLocal({
            roomId: b.room_id, dir: b.dir, name: b.name, role: b.role, description: b.description,
            sessionId: req.headers['x-xmuse-session'] || b.session_id || store.get()?.sessionId || 'dsh-sidebar',
            clientInfo: b.client_info,
          })
          return json(res, 200, out)
        } catch (e) {
          return json(res, e.status ?? 502, { error: e.code ?? 'join_failed', message: errText(e) })
        }
      }
      if (req.method === 'POST' && rest === '/leave') {
        return json(res, 200, await leaveRoom())
      }
      json(res, 404, { ok: false, error: 'not found' })
    } catch (e) {
      log('warn', `sidebar route failed: ${errText(e)}`)
      json(res, 502, { ok: false, error: errText(e) })
    }
  }

  return { handle, createRoom, joinRoom, joinLocal, listRooms, leaveRoom, status }
}
