// xmuse dsh-bundle 侧栏（抽屉）宿主侧：XMUSE2-VIEW-API v0。
//
// 浏览器永远拿不到令牌：前端只调同源的 /xmuse/* 路由，宿主在这里加上
// operator 令牌再转发到 hub（127.0.0.1:<port>）。路由前缀与宿主自带的
// /api 一样加 connection.requestRejection 栅栏（dsh web 可能绑 0.0.0.0）。
// 做法来源：experiments/d0-probes/dsh-drawer-probe（D0 已验证）。
import http from 'node:http'
import { readFile, writeFile, rm } from 'node:fs/promises'

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

/** 直连 hub（node:http，不走 fetch 代理）。body 为 undefined 时不发 body。 */
export function hubRequest(port, method, path, { token, sessionId, body, timeoutMs = PROXY_TIMEOUT_MS } = {}) {
  return new Promise((resolve, reject) => {
    const payload = body === undefined || body === null
      ? null
      : Buffer.from(typeof body === 'string' ? body : JSON.stringify(body))
    const req = http.request({
      host: '127.0.0.1', port, path, method,
      headers: {
        'content-type': 'application/json',
        ...(payload ? { 'content-length': payload.length } : {}),
        ...(token ? { authorization: `Bearer ${token}` } : {}),
        ...(sessionId ? { 'x-xmuse-session': sessionId } : {}),
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

/** 侧栏令牌存放在宿主进程侧（sidebar.json），{memberId, memberToken, operatorToken, sessionId}。 */
export function createTokenStore(file) {
  let cur = null
  return {
    get: () => cur,
    load: async () => {
      try {
        const data = JSON.parse(await readFile(file, 'utf8'))
        if (data && data.memberToken && data.operatorToken) {
          cur = {
            memberId: data.memberId ?? null,
            memberToken: data.memberToken,
            operatorToken: data.operatorToken,
            sessionId: data.sessionId ?? null,
          }
        } else cur = null
      } catch { cur = null }
      return cur
    },
    save: async (t) => {
      cur = { memberId: t.memberId ?? null, memberToken: t.memberToken, operatorToken: t.operatorToken, sessionId: t.sessionId ?? null }
      await writeFile(file, JSON.stringify({ version: 1, ...cur }, null, 2))
      return cur
    },
    clear: async () => {
      cur = null
      try { await rm(file, { force: true }) } catch { /* ignore */ }
    },
  }
}

/**
 * @param readHub () => Promise<{port}>  hub.json 的端口
 * @param store token store（createTokenStore）
 * @param clientFile 前端单文件 client.js 的绝对路径
 * @param getService (name) => service | undefined  透给 connection.requestRejection 栅栏
 */
export function createSidebar({ readHub, store, clientFile, log = () => {}, getService = () => undefined }) {
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
    if (!t) return json(res, 409, { error: 'no_room', message: '侧栏还没有加入房间：先用 /xmuse join <邀请码> 加入，或开一个新房间' })
    let hub
    try { hub = await readHub() } catch (e) { return json(res, 502, { error: 'hub_unreachable', message: errText(e) }) }
    try {
      const r = await hubRequest(hub.port, method, hubPath, {
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

  /** POST /v1/rooms（无令牌）：开房间，调用者成为主控。成功只把 member_id 和 room 给浏览器，令牌留下。 */
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
    const r = await hubRequest(hub.port, 'POST', '/v1/rooms', { body })
    const data = parseJson(r.body)
    if (r.status !== 200) {
      const e = new Error(`hub ${r.status}: ${data.error ?? data.message ?? 'rooms failed'}`)
      e.code = data.error
      e.status = r.status
      throw e
    }
    await store.save({ memberId: data.member_id, memberToken: data.member_token, operatorToken: data.operator_token, sessionId })
    return { room: data.room, member_id: data.member_id }
  }

  /** POST /v1/join（无令牌）：凭邀请码加入。码一次性、10 分钟过期、vendor 必须匹配（hub 侧校验）。 */
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
    })
    const data = parseJson(r.body)
    if (r.status !== 200) {
      const e = new Error(`hub ${r.status}: ${data.error ?? data.message ?? 'join failed'}`)
      e.code = data.error
      e.status = r.status
      throw e
    }
    await store.save({ memberId: data.member_id, memberToken: data.member_token, operatorToken: data.operator_token, sessionId })
    return { member_id: data.member_id }
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
    return { bound: !!t, memberId: t?.memberId ?? null }
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
      if (req.method === 'POST' && rest === '/leave') {
        return json(res, 200, await leaveRoom())
      }
      json(res, 404, { ok: false, error: 'not found' })
    } catch (e) {
      log('warn', `sidebar route failed: ${errText(e)}`)
      json(res, 502, { ok: false, error: errText(e) })
    }
  }

  return { handle, createRoom, joinRoom, leaveRoom, status }
}
