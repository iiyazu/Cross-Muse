/**
 * Host half of dsh-drawer-probe (D0 feasibility probe, not product code).
 *
 * Shows the three things the xmuse sidebar needs from a dsh plugin's host half:
 *   1. register HTTP routes on the dsh web server (ctx.inject(['webServer']) -> scope.webServer.register),
 *   2. fence them like the host's own /api (connection.requestRejection(req)), and
 *   3. forward them to a loopback hub with plain node:http (the token would live here, never in the browser).
 *
 * Routes (prefix /xmuse-probe):
 *   GET  /xmuse-probe/ping   -> {ok, at, hubUrl}              proves the route is reachable from the page
 *   GET  /xmuse-probe/view   -> proxied GET  <hubUrl>/v1/view  (the shared view model)
 *   POST /xmuse-probe/act    -> proxied POST <hubUrl>/v1/act   (user actions; body is forwarded as is)
 */
import http from 'node:http'

export const name = 'dsh-drawer-probe'

const PREFIX = '/xmuse-probe'
const MAX_BODY = 64 * 1024

/** Same fence the host applies to /api; a loopback-only stand-in when the host has no connection service. */
function refusalOf(ctx, req) {
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

/** Forward one request to the hub with node:http; the hub token (probe: none) would be added here. */
function forward(hubUrl, method, path, body, sessionHeader) {
  return new Promise((resolve, reject) => {
    const u = new URL(path, hubUrl)
    const payload = body ? Buffer.from(body) : null
    const req = http.request({
      host: u.hostname, port: u.port, path: u.pathname + u.search, method,
      headers: {
        'content-type': 'application/json',
        ...(payload ? { 'content-length': payload.length } : {}),
        ...(sessionHeader ? { 'x-xmuse-session': sessionHeader } : {}),
      },
      timeout: 8000,
    }, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => resolve({ status: res.statusCode ?? 502, body: Buffer.concat(chunks) }))
      res.on('error', reject)
    })
    req.on('timeout', () => req.destroy(new Error('hub request timed out')))
    req.on('error', reject)
    req.end(payload ?? undefined)
  })
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []
    let size = 0
    req.on('data', (c) => {
      size += c.length
      if (size > MAX_BODY) { reject(new Error('body too large')); req.destroy(); return }
      chunks.push(c)
    })
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')))
    req.on('error', reject)
  })
}

function json(res, status, obj) {
  const text = JSON.stringify(obj)
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store', 'content-length': Buffer.byteLength(text) })
  res.end(text)
}

export function apply(ctx, config) {
  const hubUrl = typeof config?.hubUrl === 'string' && config.hubUrl ? config.hubUrl : 'http://127.0.0.1:18080'
  const log = (level, msg) => { try { (ctx.logger?.[level] ?? ctx.logger?.info)?.call(ctx.logger, `xmuse-probe: ${msg}`) } catch { /* never throw */ } }

  const handler = async (req, res) => {
    try {
      const rejected = refusalOf(ctx, req)
      if (rejected !== undefined) { res.writeHead(rejected); res.end('refused'); return }
      const url = new URL(req.url ?? '/', 'http://127.0.0.1')
      const rest = url.pathname.slice(PREFIX.length + 1)
      if (rest === 'ping' && req.method === 'GET') return json(res, 200, { ok: true, at: Date.now(), hubUrl })
      if (rest === 'view' && req.method === 'GET') {
        const r = await forward(hubUrl, 'GET', '/v1/view' + url.search, null, req.headers['x-xmuse-session'])
        res.writeHead(r.status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
        res.end(r.body)
        return
      }
      if (rest === 'act' && req.method === 'POST') {
        const r = await forward(hubUrl, 'POST', '/v1/act', await readBody(req), req.headers['x-xmuse-session'])
        res.writeHead(r.status, { 'content-type': 'application/json; charset=utf-8' })
        res.end(r.body)
        return
      }
      json(res, 404, { ok: false, error: 'not found' })
    } catch (e) {
      log('warn', `route failed: ${e?.message ?? e}`)
      json(res, 502, { ok: false, error: String(e?.message ?? e) })
    }
  }

  // inject() waits for the service; a host without a web server simply never registers (the plugin still activates).
  let off = null
  ctx.effect(() => () => { try { off?.() } catch { /* ignore */ } }, 'dsh-drawer-probe: teardown')
  if (typeof ctx.inject === 'function') {
    ctx.inject(['webServer'], (scope) => { off = scope.webServer.register({ kind: 'prefix', path: PREFIX, handler }) })
  } else {
    off = ctx.webServer.register({ kind: 'prefix', path: PREFIX, handler })
  }
}
