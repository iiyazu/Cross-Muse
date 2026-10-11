// 真 hub 联调冒烟：node integrations/dsh-bundle/test/real-hub-smoke.mjs
// 地址从 XMUSE_HUB_URL 读（如 http://127.0.0.1:39091）；没设就跳过（默认不跑，不进 npm test）。
// 流程：rooms → view 全量 → invite 别家 → join（另一 session）→ 互 say/for_me →
// 长轮询被唤醒 + 无变化 204 → ack → 部分 ack → rebind → leave → sidebar-host 假宿主代理 view/act。
// 约定 §7(rc c96fe8e)：不要拿 acked 和 unread 对账（acked 含系统通知投递，unread 不含），
// 只断言 unread 的变化和 acked>=1。分段跑：某段失败打印原文后继续后面能跑的段，最后汇总。
import http from 'node:http'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createSidebar, createTokenStore } from '../sidebar-host.js'

const HUB_URL = process.env.XMUSE_HUB_URL || ''
if (!HUB_URL) {
  console.log('real-hub smoke: SKIP (XMUSE_HUB_URL not set)')
  process.exit(0)
}
const u = new URL(HUB_URL)
const HUB_PORT = Number(u.port)
const ROOM_DIR = process.env.XMUSE_ROOM_DIR || 'C:\\Users\\user\\dsh-work\\sidebar-sandbox-dsh'

const results = []
const fail = (step, info) => {
  console.error(`FAIL [${step}]`, typeof info === 'string' ? info : JSON.stringify(info, null, 1))
  throw new Error(`step failed: ${step}`)
}
const ok = (step, note) => console.log(`ok [${step}] ${note}`)
const sec = async (name, needs, fn) => {
  if (needs && needs.some((n) => results.find((r) => r[0] === n && r[1] !== 'ok'))) {
    results.push([name, 'SKIP', `前置段未过: ${needs.join(',')}`])
    console.log(`SKIP [${name}] 前置段未过`)
    return false
  }
  try {
    await fn()
    results.push([name, 'ok'])
    return true
  } catch (e) {
    results.push([name, 'FAIL', e.message])
    return false
  }
}
const need = (cond, step, info) => { if (!cond) fail(step, info) }

const req = (method, p, body, headers = {}) => new Promise((resolve, reject) => {
  const payload = body === undefined ? undefined : JSON.stringify(body)
  const r = http.request({
    host: u.hostname, port: HUB_PORT, path: p, method,
    headers: { 'content-type': 'application/json', ...headers },
    timeout: 15000,
  }, (res) => {
    const chunks = []
    res.on('data', (c) => chunks.push(c))
    res.on('end', () => {
      const text = Buffer.concat(chunks).toString('utf8')
      let data = null
      try { data = text ? JSON.parse(text) : null } catch { data = { _raw: text } }
      resolve({ s: res.statusCode, b: data })
    })
    res.on('error', reject)
  })
  r.on('timeout', () => r.destroy(new Error('timeout')))
  r.on('error', reject)
  r.end(payload)
})
const A = (t, sess) => ({ authorization: `Bearer ${t}`, ...(sess ? { 'x-xmuse-session': sess } : {}) })
const forMe = (tl) => tl.filter((m) => m.for_me).map((m) => m.id)
const cast = (tl, self) => tl.filter((m) => m.thread === '#room' && m.from !== self).map((m) => m.id)
const unreadOf = (v, id) => v.members.find((m) => m.id === id).unread
const S = {} // 跨段状态：tokens、ids、clSess

await sec('rooms', null, async () => {
  const r = await req('POST', '/v1/rooms', { dir: ROOM_DIR, name: 'dsh-sandbox', vendor: 'dsh', session_id: 'sb-s1' })
  if (r.s === 409 && r.b?.error === 'room_exists') fail('rooms not empty', '沙盒 hub 里已有房间，需 coord 重置后再跑')
  need(r.s === 200, 'rooms', r)
  S.dshMt = r.b.member_token; S.dshOt = r.b.operator_token
  need(r.b.member_id === 'dsh', 'rooms member id', `§7: 不带 member_id 应为 vendor 名 dsh，实际 ${r.b.member_id}`)
  S.clSess = 'sb-s2'
  ok('rooms', `room=${r.b.room.id} member_id=dsh`)
})

await sec('view+invite', ['rooms'], async () => {
  let r = await req('GET', '/v1/view?since=0', undefined, A(S.dshMt, 'sb-s1'))
  need(r.s === 200, 'view member', r)
  need(r.b.me?.kind === 'member' && r.b.me?.id === 'dsh', 'view me member', r.b.me)
  ok('view member', `version=${r.b.version} me=member/dsh`)
  r = await req('GET', '/v1/view?since=0', undefined, A(S.dshOt))
  need(r.s === 200, 'view operator', r)
  need(r.b.me?.kind === 'operator' && r.b.me?.id === 'dsh', 'view me operator', r.b.me)
  ok('view operator', `me=operator/dsh version=${r.b.version}`)
  // 第二个成员用 claude（桌面会话承载，hub 不起回合）：opencode 成员会被 hub 真唤醒跑回合，
  // 回合读消息导致 unread/ack 读数不稳定（§7“成员的运行方式”）。
  r = await req('POST', '/v1/act', { act: 'invite', vendor: 'claude', role: 'executor', description: 'smoke', name: 'cl-9' }, A(S.dshOt))
  need(r.s === 200, 'invite', r)
  S.code = r.b.code
  ok('invite', `code=${S.code} command=${r.b.command}`)
})

await sec('join+say', ['view+invite'], async () => {
  let r = await req('POST', '/v1/join', { code: S.code, vendor: 'claude', session_id: 'sb-s2', client_info: { client: 'smoke' } })
  need(r.s === 200, 'join', r)
  need(r.b.member_id === 'cl-9', 'join member id', r.b)
  S.ocMt = r.b.member_token; S.ocOt = r.b.operator_token
  ok('join', 'member_id=cl-9')
  r = await req('POST', '/v1/act', { act: 'say', to: 'dsh', text: '@dsh 你好' }, A(S.ocMt, 'sb-s2'))
  need(r.s === 200, 'say member', r)
  S.sayId = r.b.id
  r = await req('GET', '/v1/view?since=0', undefined, A(S.dshOt))
  need(r.s === 200, 'view after say', r)
  const got = r.b.timeline.at(-1)
  need(got.for_me && got.from === 'cl-9', 'for_me', `期望最后一条 from=cl-9 for_me=true，实际 ${JSON.stringify(got)}`)
  ok('say+for_me', `id=${S.sayId} for_me=true unread(dsh)=${unreadOf(r.b, 'dsh')}`)
  r = await req('POST', '/v1/act', { act: 'say', to: '#room', text: 'hi all' }, A(S.dshOt))
  need(r.s === 200, 'say operator', r)
  r = await req('GET', '/v1/view?since=0', undefined, A(S.ocOt))
  const lastOp = r.b.timeline.at(-1)
  need(lastOp.from === 'human' && /sidebar/.test(lastOp.via || ''), 'operator say', `期望 from=human via=*sidebar，实际 ${JSON.stringify(lastOp)}`)
  S.ver = r.b.version
  ok('say operator', `from=human via=${lastOp.via}`)
})

await sec('longpoll', ['join+say'], async () => {
  const waiting = req('GET', `/v1/view?since=${S.ver}&wait=25`, undefined, A(S.dshOt))
  await new Promise((x) => setTimeout(x, 500))
  await req('POST', '/v1/act', { act: 'say', to: 'dsh', text: 'wake' }, A(S.ocMt, S.clSess))
  const r = await waiting
  need(r.s === 200 && r.b.version > S.ver, 'long-poll wake', r)
  ok('long-poll wake', `version ${S.ver} → ${r.b.version}`)
  const t0 = Date.now()
  const r2 = await req('GET', `/v1/view?since=${r.b.version}&wait=2`, undefined, A(S.dshOt))
  need(r2.s === 204, 'long-poll 204', r2)
  ok('long-poll 204', `等了 ${((Date.now() - t0) / 1000).toFixed(1)}s 回 204`)
})

await sec('ack', ['join+say'], async () => {
  // §7(rc c96fe8e)：不拿 acked 和 unread 对账；只断言 unread 变化，acked>=1。
  let r = await req('GET', '/v1/view?since=0', undefined, A(S.ocMt, S.clSess))
  need(unreadOf(r.b, 'cl-9') === 1, 'ack setup', { members: r.b.members, timeline: r.b.timeline.map((m) => ({ id: m.id, from: m.from, thread: m.thread, for_me: m.for_me, text: m.text })) })
  const mine = [...new Set([...forMe(r.b.timeline), ...cast(r.b.timeline, 'cl-9')])]
  r = await req('POST', '/v1/act', { act: 'ack', ids: mine }, A(S.ocMt, S.clSess))
  need(r.s === 200, 'ack', r)
  need(typeof r.b.acked === 'number' && r.b.acked >= 1, 'ack count', r.b)
  const acked = r.b.acked
  r = await req('GET', '/v1/view?since=0', undefined, A(S.ocMt, S.clSess))
  need(unreadOf(r.b, 'cl-9') === 0, 'ack unread', r.b.members)
  ok('ack', `acked=${acked} unread 1→0`)
})

await sec('ack-partial', ['ack'], async () => {
  let r = await req('POST', '/v1/act', { act: 'say', to: '#room', text: 'b2' }, A(S.dshOt))
  need(r.s === 200, 'ack setup b2', r)
  r = await req('POST', '/v1/act', { act: 'say', to: 'cl-9', text: '@cl-9 看 b2' }, A(S.dshMt, 'sb-s1'))
  need(r.s === 200, 'ack setup dm', r)
  r = await req('GET', '/v1/view?since=0', undefined, A(S.ocMt, S.clSess))
  need(unreadOf(r.b, 'cl-9') === 2, 'ack setup', r.b.members)
  const onlyMe = forMe(r.b.timeline)
  r = await req('POST', '/v1/act', { act: 'ack', ids: onlyMe }, A(S.ocMt, S.clSess))
  need(r.s === 200, 'ack for_me only', r)
  r = await req('GET', '/v1/view?since=0', undefined, A(S.ocMt, S.clSess))
  need(unreadOf(r.b, 'cl-9') === 1, 'ack leftover', r.b.members)
  ok('ack partial', '只 ack 点名，unread 2→1（剩广播）')
  r = await req('POST', '/v1/act', { act: 'ack', ids: cast(r.b.timeline, 'cl-9') }, A(S.ocMt, S.clSess))
  need(r.s === 200, 'ack rest', r)
  r = await req('GET', '/v1/view?since=0', undefined, A(S.ocMt, S.clSess))
  need(unreadOf(r.b, 'cl-9') === 0, 'ack final', r.b.members)
  ok('ack final', '补 ack 广播后 unread=0')
})

await sec('rebind', ['join+say'], async () => {
  let r = await req('POST', '/v1/rebind', { session_id: 'sb-s2b' }, A(S.ocMt)) // §7: rebind 只凭成员令牌
  need(r.s === 200, 'rebind', r)
  S.clSess = 'sb-s2b'
  r = await req('GET', '/v1/view?since=0', undefined, A(S.ocMt, 'sb-s2'))
  need(r.s === 409, 'rebind old session', `旧会话应 409，实际 ${r.s} ${JSON.stringify(r.b)}`)
  r = await req('GET', '/v1/view?since=0', undefined, A(S.ocMt, 'sb-s2b'))
  need(r.s === 200, 'rebind new session', r)
  ok('rebind', '旧会话 409，新会话 200')
})

await sec('leave', ['join+say'], async () => {
  const r0 = await req('POST', '/v1/leave', {}, A(S.ocMt, S.clSess))
  need(r0.s === 200, 'leave', r0)
  const r = await req('GET', '/v1/view?since=0', undefined, A(S.dshOt))
  const left = r.b.members.find((m) => m.id === 'cl-9')
  need(left && left.online === false, 'leave state', r.b.members)
  ok('leave', 'cl-9 online=false')
})

await sec('proxy', ['rooms'], async () => {
  const store = createTokenStore(path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'sb-real-')), 'sidebar.json'))
  await store.save({ memberId: 'dsh', memberToken: S.dshMt, operatorToken: S.dshOt, sessionId: 'sb-s1' })
  const sb = createSidebar({
    readHub: async () => ({ port: HUB_PORT }),
    store,
    clientFile: fileURLToPath(new URL('../client.js', import.meta.url)),
    log: () => {},
    getService: () => undefined,
  })
  const srv = http.createServer((q, s) => sb.handle(q, s))
  await new Promise((x) => srv.listen(0, '127.0.0.1', x))
  try {
    const P = srv.address().port
    const via = (method, p, body) => new Promise((resolve, reject) => {
      const payload = body === undefined ? undefined : JSON.stringify(body)
      const q = http.request({ host: '127.0.0.1', port: P, path: p, method, headers: { 'content-type': 'application/json' }, timeout: 30000 },
        (res) => {
          const chunks = []
          res.on('data', (c) => chunks.push(c))
          res.on('end', () => {
            const text = Buffer.concat(chunks).toString('utf8')
            resolve({ s: res.statusCode, b: JSON.parse(text || '{}'), raw: text })
          })
          res.on('error', reject)
        })
      q.on('error', reject)
      q.end(payload)
    })
    let r = await via('GET', '/xmuse/view?since=0')
    need(r.s === 200 && r.b.me?.kind === 'operator', 'proxy view', r.s)
    need(!/mt_|ot_[A-Za-z0-9]+/.test(r.raw), 'proxy leak', 'view 泄漏令牌')
    ok('proxy view', `version=${r.b.version} 无令牌泄漏`)
    r = await via('POST', '/xmuse/act', { act: 'say', to: '#room', text: 'via sidebar proxy' })
    need(r.s === 200, 'proxy act', r)
    r = await via('GET', '/xmuse/timeline?before=999999999&limit=3')
    need(r.s === 200 && Array.isArray(r.b.items), 'proxy timeline', r)
    ok('proxy act+timeline', 'say 200，timeline items 数组')
  } finally {
    srv.closeAllConnections?.()
    srv.close()
  }
})

console.log('--- summary ---')
for (const [n, st, d] of results) console.log(`${st} ${n}${d ? ' ' + d : ''}`)
if (results.some((r) => r[1] === 'FAIL')) {
  console.log('REAL-HUB SMOKE: FAILURES')
  process.exitCode = 1
} else {
  console.log('REAL-HUB SMOKE: OK')
}
