import { test } from 'node:test'
import assert from 'node:assert/strict'
import http from 'node:http'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { Script } from 'node:vm'
import { fileURLToPath } from 'node:url'
import { apply } from '../index.js'
import { createSidebar, createTokenStore, SIDEBAR_PREFIX } from '../sidebar-host.js'

const MOCK_HUB = fileURLToPath(new URL('../../../tools/mock-hub/mock-hub.mjs', import.meta.url))
const CLIENT_JS = fileURLToPath(new URL('../client.js', import.meta.url))
const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms))

// ---- 真 mock-hub（v0 约定），随机端口，state-dir 写 hub.json ----
async function startMockHub() {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-sidebar-'))
  const stateDir = path.join(tmp, 'hubstate')
  fs.mkdirSync(stateDir, { recursive: true })
  const child = spawn(process.execPath, [MOCK_HUB, '--port', '0', '--state-dir', stateDir, '--quiet'], { stdio: 'ignore' })
  const hubFile = path.join(stateDir, 'hub.json')
  const t0 = Date.now()
  while (!fs.existsSync(hubFile)) {
    if (Date.now() - t0 > 10000) throw new Error('mock-hub did not write hub.json')
    await tick(50)
  }
  const { port } = JSON.parse(fs.readFileSync(hubFile, 'utf8'))
  // 等到能应答
  for (let i = 0; i < 100; i++) {
    try {
      await fetch(`http://127.0.0.1:${port}/_mock/state`)
      break
    } catch { await tick(50) }
  }
  return { tmp, stateDir, port, close: () => { try { child.kill() } catch { /* ignore */ } } }
}

const hub = await startMockHub()
test.after(() => hub.close())

const hubCtl = async (method, p, body) => {
  const r = await fetch(`http://127.0.0.1:${hub.port}${p}`, {
    method, headers: { 'content-type': 'application/json' }, body: body ? JSON.stringify(body) : undefined,
  })
  return { s: r.status, b: JSON.parse(await r.text() || '{}') }
}

// ---- 侧栏宿主挂到一个本地 HTTP 服务上（扮演 dsh 的 webServer） ----
async function mountSidebar({ sidebarFile } = {}) {
  const dir = hub.tmp
  const file = sidebarFile ?? path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-sb-')), 'sidebar.json')
  const store = createTokenStore(file)
  await store.load()
  const logs = []
  const sb = createSidebar({
    readHub: async () => JSON.parse(fs.readFileSync(path.join(hub.stateDir, 'hub.json'), 'utf8')),
    store, clientFile: CLIENT_JS,
    log: (l, m) => logs.push([l, m]),
    getService: () => undefined, // 没有 connection 服务：回环回退栅栏
  })
  const server = http.createServer((req, res) => sb.handle(req, res))
  await new Promise((r) => server.listen(0, '127.0.0.1', r))
  const port = server.address().port
  const call = (method, p, body, headers = {}) => new Promise((resolve, reject) => {
    const payload = body === undefined ? undefined : (typeof body === 'string' ? body : JSON.stringify(body))
    const req = http.request({
      host: '127.0.0.1', port, path: p, method,
      headers: { 'content-type': 'application/json', ...headers },
    }, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('end', () => resolve({ status: res.statusCode, text: Buffer.concat(chunks).toString('utf8') }))
    })
    req.on('error', reject)
    req.end(payload)
  })
  const close = () => { server.closeAllConnections?.(); server.close() }
  return { sb, store, file, logs, call, close }
}

const j = (r) => JSON.parse(r.text || '{}')
const hasToken = (text) => /(mt_|ot_)[A-Za-z0-9]+/.test(text)

test('sidebar prefix and full flow against mock-hub: rooms -> view -> act -> timeline -> approve -> leave', async () => {
  assert.equal(SIDEBAR_PREFIX, '/xmuse')
  const m = await mountSidebar()
  test.after(() => m.close())

  // 未加入：status 未绑定，view 回 409 no_room
  assert.deepEqual(j(await m.call('GET', '/xmuse/status')), { bound: false, memberId: null })
  const noview = await m.call('GET', '/xmuse/view?since=0')
  assert.equal(noview.status, 409)
  assert.equal(j(noview).error, 'no_room')

  // 开房间（POST /v1/rooms，无令牌）：返回里不能有令牌，但宿主落盘了
  const rooms = await m.call('POST', '/xmuse/rooms', { dir: 'C:\\x', name: 'demo' })
  assert.equal(rooms.status, 200)
  const rj = j(rooms)
  assert.ok(rj.room && rj.member_id, 'returns room + member_id')
  assert.ok(!hasToken(rooms.text), 'no token leaks to the browser')
  const stored = JSON.parse(fs.readFileSync(m.file, 'utf8'))
  assert.ok(stored.memberToken && stored.operatorToken, 'tokens persisted host-side')
  assert.equal(stored.memberId, rj.member_id)

  // status 也不泄漏令牌
  const st = await m.call('GET', '/xmuse/status')
  assert.equal(j(st).bound, true)
  assert.ok(!hasToken(st.text))

  // /v1/view 跑通（长轮询首包 since=0 全量）
  const view = await m.call('GET', '/xmuse/view?since=0')
  assert.equal(view.status, 200)
  assert.ok(!hasToken(view.text), 'view must not leak tokens')
  const v = j(view)
  assert.ok(typeof v.version === 'number' && v.room && Array.isArray(v.members) && Array.isArray(v.timeline))
  assert.equal(v.me.kind, 'operator')
  const ver = v.version

  // 操作令牌发消息：from=human via=dsh sidebar
  const say = await m.call('POST', '/xmuse/act', { act: 'say', to: '#room', text: 'hi all' })
  assert.equal(say.status, 200)
  const v2 = j(await m.call('GET', '/xmuse/view?since=0'))
  const last = v2.timeline.at(-1)
  assert.equal(last.from, 'human')
  assert.equal(last.via, 'dsh sidebar')

  // 长轮询：挂起的 view 被一次写操作唤醒
  const waiting = m.call('GET', `/xmuse/view?since=${v2.version}&wait=5`)
  await tick(200)
  await hubCtl('POST', '/_mock/say', { from: rj.member_id, to: '#room', text: 'hub note' })
  const woken = await waiting
  assert.equal(woken.status, 200)
  assert.ok(j(woken).version > v2.version)

  // 更早的时间线分页（用最新消息 id 往前翻一页，应拿到那条 say）
  const newest = j(woken).timeline.at(-1).id
  const tl = await m.call('GET', `/xmuse/timeline?before=${newest}&limit=1`)
  assert.equal(tl.status, 200)
  assert.equal(j(tl).items.length, 1)
  assert.equal(j(tl).items[0].text, 'hi all')

  // 审批：成员令牌不能批（403 经代理原样透回），操作令牌可以
  const ap = (await hubCtl('POST', '/_mock/approval', { member: rj.member_id, summary: 'npm i' })).b
  const v3 = j(await m.call('GET', '/xmuse/view?since=0'))
  assert.equal(v3.approvals.length, 1)
  const ok = await m.call('POST', '/xmuse/act', { act: 'approve', id: ap.id, decision: 'once' })
  assert.equal(ok.status, 200)
  assert.equal(j(await m.call('GET', '/xmuse/view?since=0')).approvals.length, 0)

  // §7 新审批种类：kind=alignment（对齐提案）和 kind=resume（被暂停成员）同样经 approve 处理，代理原样透回
  const apA = (await hubCtl('POST', '/_mock/approval', { member: rj.member_id, kind: 'alignment', summary: 'E12 提案' })).b
  const apR = (await hubCtl('POST', '/_mock/approval', { member: rj.member_id, kind: 'resume', summary: '恢复 dsh-1' })).b
  const vA = j(await m.call('GET', '/xmuse/view?since=0'))
  assert.deepEqual(vA.approvals.map((a) => a.kind).sort(), ['alignment', 'resume'])
  assert.equal((await m.call('POST', '/xmuse/act', { act: 'approve', id: apA.id, decision: 'once' })).status, 200)
  assert.equal((await m.call('POST', '/xmuse/act', { act: 'approve', id: apR.id, decision: 'always' })).status, 200)
  assert.equal(j(await m.call('GET', '/xmuse/view?since=0')).approvals.length, 0)

  // 前端单文件下发
  const js = await m.call('GET', '/xmuse/sidebar.js')
  assert.equal(js.status, 200)
  assert.match(js.text, /window\.__ModuleLoader__\.load/)

  // 栅栏：外部 Host 被拒绝
  const evil = await m.call('GET', '/xmuse/ping', undefined, { host: 'evil.example.com' })
  assert.equal(evil.status, 403)
  assert.equal(j(await m.call('GET', '/xmuse/ping')).ok, true)

  // @我的高亮：第二个成员 join 后 @ 主控，view 里 for_me=true
  const inv = (await hubCtl('POST', '/_mock/invite', { vendor: 'dsh', role: 'executor', description: 'w', name: 'dsh-1' })).b
  const m2 = await mountSidebar()
  test.after(() => m2.close())
  const join = await m2.call('POST', '/xmuse/join', { code: inv.code }, { 'x-xmuse-session': 's2' })
  assert.equal(join.status, 200)
  assert.equal(j(join).member_id, 'dsh-1')
  await hubCtl('POST', '/_mock/say', { from: 'dsh-1', to: rj.member_id, text: `@${rj.member_id} 请看一下` })
  const v4 = j(await m.call('GET', '/xmuse/view?since=0'))
  assert.equal(v4.timeline.at(-1).for_me, true)
  // 主控的未读 = 操作令牌发的那条 #room say（收件人含主控）+ 这条私聊 @
  assert.equal(v4.members.find((x) => x.id === rj.member_id).unread, 2)
  // 用过的码再用一次：409（经代理透回）
  assert.equal((await m2.call('POST', '/xmuse/join', { code: inv.code })).status, 409)

  // leave：本地解绑，之后 view 回到 409
  assert.equal((await m.call('POST', '/xmuse/leave')).status, 200)
  assert.deepEqual(j(await m.call('GET', '/xmuse/status')), { bound: false, memberId: null })
  assert.equal((await m.call('GET', '/xmuse/view?since=0')).status, 409)
  void ver
})

test('/xmuse join | room new | leave slash commands (old bind untouched)', async () => {
  await hubCtl('POST', '/_mock/reset', {})
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-slash-'))
  const commands = new Map()
  let webHandler = null
  const ctx = {
    logger: { info: () => {}, warn: () => {} },
    effect: (fn) => fn(),
    on: () => () => {},
    commands: { register: (c) => { commands.set(c.name, c); return () => commands.delete(c.name) } },
    agents: { roots: () => [] },
    sessions: { flush: async () => true },
    sessionController: { resolveAgent: async () => ({ error: new Error('no') }) },
    inject: (names, cb) => { assert.deepEqual(names, ['webServer']); cb({ webServer: { register: (r) => { webHandler = r; return () => {} } } }) },
    get: () => undefined,
  }
  apply(ctx, {
    state: hub.stateDir, bindingsFile: path.join(dir, 'bindings.json'),
    sidebarFile: path.join(dir, 'sidebar.json'), pollWaitS: 1, backoffMinMs: 20, backoffMaxMs: 80,
  })
  assert.ok(webHandler, 'sidebar routes registered via ctx.inject(webServer)')
  assert.equal(webHandler.path, '/xmuse')
  const run = (sid, raw) => commands.get('xmuse').handler({ agent: { id: sid }, rawInput: raw })

  assert.match((await run('s1', 'join')).text, /Usage: \/xmuse join/)
  assert.match((await run('s1', 'room')).text, /Usage: \/xmuse room new/)
  assert.match((await run('s1', 'room new')).text, /Usage: \/xmuse room new/)

  const created = await run('s1', 'room new demo C:\\x')
  assert.equal(created.kind, 'success')
  assert.match(created.text, /you are the host/)
  assert.match((await run('s1', 'status')).text, /sidebar: bound as/)

  // 已有房间时再开：hub 409 原样报给用户
  assert.match((await run('s1', 'room new other C:\\x')).text, /room new failed/)

  const inv = (await hubCtl('POST', '/_mock/invite', { vendor: 'dsh', role: 'executor', description: 'w', name: 'dsh-9' })).b
  const joined = await run('s9', `join ${inv.code}`)
  assert.equal(joined.kind, 'success')
  assert.match(joined.text, /dsh-9/)
  // 一次性码：第二次 join 失败
  assert.equal((await run('s8', `join ${inv.code}`)).kind, 'error')
  // 不存在的码：404 透回
  assert.equal((await run('s8', 'join NOPE-00')).kind, 'error')

  const left = await run('s9', 'leave')
  assert.equal(left.kind, 'success')
  assert.match((await run('s9', 'status')).text, /sidebar: no room/)
})

test('client.js: single-file ModuleLoader drawer, no imports, no innerHTML, covers v0 UI', async () => {
  const src = fs.readFileSync(CLIENT_JS, 'utf8')
  new Script(src, { filename: 'client.js' }) // 只解析不执行：语法检查（沙箱里不能 spawn，用 vm）
  assert.match(src, /window\.__ModuleLoader__\.load/)
  assert.ok(!/^\s*import\s/m.test(src), 'no imports')
  assert.ok(!src.includes('innerHTML'), 'DOM-only, no innerHTML')
  assert.ok(!hasToken(src), 'no token placeholder in frontend')
  for (const marker of [
    "'/view?since='", "'/timeline?before='", "'/rooms'", "'/join'",
    "act: 'say'", "act: 'ack'", "act: 'approve'", "act: 'invite'",
    '批准一次', '总是', '拒绝', '加载更早', '邀请码', '复制命令',
    'data-me', 'mode: push', 'mode: overlay',
  ]) assert.ok(src.includes(marker), `client covers ${marker}`)
})
