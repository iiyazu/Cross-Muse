// Fake-host test: loads lib/index.js with a fake plugin ctx, mounts the registered handler on a real
// http server (stand-in for dsh's webServer) and checks GET /view, POST /act, /ping and the loopback fence.
// usage: node test/host-proxy.mjs [hubUrl]   (hub = anything that answers /v1/view and /v1/act, e.g. http-echo-server.js)
import http from 'node:http'
import { apply } from '../lib/index.js'

const hubUrl = process.argv[2] || 'http://127.0.0.1:18080'
let handler = null
const ctx = {
  logger: { warn: console.warn, info: console.log },
  get: () => undefined,
  effect: (fn) => { fn() },
  inject: (names, cb) => cb({ webServer: { register: (r) => { handler = r.handler; return () => {} } } }),
}
apply(ctx, { hubUrl })
if (!handler) throw new Error('route not registered')

const srv = http.createServer((req, res) => handler(req, res)).listen(0, '127.0.0.1')
await new Promise((r) => srv.once('listening', r))
const port = srv.address().port

function call(method, path, body, headers = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port, path, method, headers: { 'content-type': 'application/json', ...headers } }, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => resolve({ status: res.statusCode, body: Buffer.concat(chunks).toString() }))
    })
    req.on('error', reject)
    req.end(body)
  })
}

const out = {
  ping: await call('GET', '/xmuse-probe/ping'),
  view: await call('GET', '/xmuse-probe/view?since=0', undefined, { 'x-xmuse-session': 'sess-123' }),
  act: await call('POST', '/xmuse-probe/act', JSON.stringify({ act: 'say', text: 'hi' })),
  fence_foreign_host: await call('GET', '/xmuse-probe/ping', undefined, { host: 'evil.example.com' }),
  notfound: await call('GET', '/xmuse-probe/nope'),
}
console.log(JSON.stringify(out, null, 1))
srv.close()
