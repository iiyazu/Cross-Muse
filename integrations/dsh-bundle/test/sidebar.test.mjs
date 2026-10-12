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
async function mountSidebar({ sidebarFile, registryDir } = {}) {
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
    registryDir: registryDir || '',
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
  assert.deepEqual(j(await m.call('GET', '/xmuse/status')), { bound: false, memberId: null, hubPort: null })
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
  assert.deepEqual(j(await m.call('GET', '/xmuse/status')), { bound: false, memberId: null, hubPort: null })
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

test('v0.1 room list + one-click local join (8.1): key stays host-side', async () => {
  const regDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-reg-'))
  const startRegHub = async (seed) => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-reghub-'))
    const stateDir = path.join(tmp, 'hubstate')
    fs.mkdirSync(stateDir, { recursive: true })
    const child = spawn(process.execPath,
      [MOCK_HUB, '--port', '0', '--seed', seed, '--registry-dir', regDir, '--state-dir', stateDir, '--quiet'],
      { stdio: 'ignore' })
    const hubFile = path.join(stateDir, 'hub.json')
    const t0 = Date.now()
    while (!fs.existsSync(hubFile)) {
      if (Date.now() - t0 > 10000) throw new Error('mock-hub did not write hub.json')
      await tick(50)
    }
    const { port } = JSON.parse(fs.readFileSync(hubFile, 'utf8'))
    for (let i = 0; i < 100; i++) {
      try { await fetch(`http://127.0.0.1:${port}/_mock/state`); break } catch { await tick(50) }
    }
    return { port, close: () => { try { child.kill() } catch { /* ignore */ } } }
  }
  const hubA = await startRegHub('hostA')
  const hubB = await startRegHub('hostB')
  test.after(() => { hubA.close(); hubB.close() })
  // 等两间都登记
  let entries = []
  for (let i = 0; i < 100; i++) {
    try { entries = JSON.parse(fs.readFileSync(path.join(regDir, 'hubs.json'), 'utf8')).hubs } catch { entries = [] }
    if (entries.length >= 2) break
    await tick(50)
  }
  assert.equal(entries.length, 2)
  const key = fs.readFileSync(path.join(regDir, 'sidebar.key'), 'utf8').trim()
  assert.match(key, /^[0-9a-f]{64}$/)

  const m = await mountSidebar({ registryDir: regDir })
  test.after(() => m.close())
  // 房间列表：两间都在，key 不泄漏给浏览器
  const listRes = await m.call('GET', '/xmuse/rooms')
  assert.equal(listRes.status, 200)
  assert.ok(!listRes.text.includes(key), 'sidebar.key never reaches the browser')
  const list = j(listRes)
  assert.equal(list.hubs.length, 2)
  const entB = list.hubs.find((e) => e.host === 'hostB')
  assert.ok(entB && entB.room_id && entB.dir, 'entry has room_id/dir/host')

  // 一键加入（浏览器不带 key，宿主侧带上）：成功后转发跟令牌走 hubB
  const jl = await m.call('POST', '/xmuse/join-local', { room_id: entB.room_id })
  assert.equal(jl.status, 200)
  assert.equal(j(jl).member_id, 'dsh')
  const stored = JSON.parse(fs.readFileSync(m.file, 'utf8'))
  assert.equal(stored.hubPort, hubB.port)
  assert.ok(stored.memberToken && stored.operatorToken)
  const vB = j(await m.call('GET', '/xmuse/view?since=0'))
  assert.equal(vB.room.host, 'hostB')

  // 按目录加入另一间（换会话）：hubA 上 dsh 空闲，直接叫 dsh，转发切到 hubA
  const entA = list.hubs.find((e) => e.host === 'hostA')
  const jd = await m.call('POST', '/xmuse/join-local', { dir: entA.dir }, { 'x-xmuse-session': 's-other' })
  assert.equal(jd.status, 200)
  assert.equal(j(jd).member_id, 'dsh')
  assert.equal(j(await m.call('GET', '/xmuse/view?since=0')).room.host, 'hostA')

  // 错误映射：对不上的目录 400 wrong_dir，不认识的 room_id 404，空表 404 no_room
  assert.equal((await m.call('POST', '/xmuse/join-local', { dir: 'C:\\nope' })).status, 400)
  assert.equal(j(await m.call('POST', '/xmuse/join-local', { dir: 'C:\\nope' })).error, 'wrong_dir')
  assert.equal(j(await m.call('POST', '/xmuse/join-local', { room_id: 'r-deadbeef' })).error, 'unknown_room')
  const emptyReg = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-regempty-'))
  const mE = await mountSidebar({ registryDir: emptyReg })
  test.after(() => mE.close())
  assert.deepEqual(j(await mE.call('GET', '/xmuse/rooms')), { hubs: [] })
  // 空表（有 key 但无房间）：404 no_room；key 也没有时先报 no_sidebar_key
  assert.equal(j(await mE.call('POST', '/xmuse/join-local', { room_id: 'r-x' })).error, 'no_sidebar_key')
  fs.writeFileSync(path.join(emptyReg, 'sidebar.key'), key)
  assert.equal(j(await mE.call('POST', '/xmuse/join-local', { room_id: 'r-x' })).error, 'no_room')

  // 登记表开着但 key 缺失：宿主直接拒绝（502 no_sidebar_key，不会把无 key 请求发给 hub；
  // 有 key 时 200 成功，证明平时是宿主带上的 key 过的关）
  const noKeyReg = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-regnokey-'))
  fs.writeFileSync(path.join(noKeyReg, 'hubs.json'), fs.readFileSync(path.join(regDir, 'hubs.json'), 'utf8'))
  const mK = await mountSidebar({ registryDir: noKeyReg })
  test.after(() => mK.close())
  const noKey = await mK.call('POST', '/xmuse/join-local', { room_id: entB.room_id })
  assert.equal(noKey.status, 502)
  assert.equal(j(noKey).error, 'no_sidebar_key')
  // key 不对：hub 401 bad_sidebar_key 原样透回
  const wrongKeyReg = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-regwrongkey-'))
  fs.writeFileSync(path.join(wrongKeyReg, 'hubs.json'), fs.readFileSync(path.join(regDir, 'hubs.json'), 'utf8'))
  fs.writeFileSync(path.join(wrongKeyReg, 'sidebar.key'), 'f'.repeat(64))
  const mW = await mountSidebar({ registryDir: wrongKeyReg })
  test.after(() => mW.close())
  const wrongKey = await mW.call('POST', '/xmuse/join-local', { room_id: entB.room_id })
  assert.equal(wrongKey.status, 401)
  assert.equal(j(wrongKey).error, 'bad_sidebar_key')

  // 登记表开着时，邀请码加入照旧可用（key 顺手带上，无害；码由默认 hub 开出，走 readHub 那条路）
  const inv = (await hubCtl('POST', '/_mock/invite', { vendor: 'dsh', role: 'executor', name: 'dsh-10' })).b
  const jc = await m.call('POST', '/xmuse/join', { code: inv.code }, { 'x-xmuse-session': 's-code' })
  assert.equal(jc.status, 200)
  assert.equal(j(jc).member_id, 'dsh-10')
})

test('v0.1 member_add/edit + member menu acts + private groups (8.2/8.3)', async () => {
  const regDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-reg2-'))
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-reghub2-'))
  const stateDir = path.join(tmp, 'hubstate')
  fs.mkdirSync(stateDir, { recursive: true })
  const child = spawn(process.execPath,
    [MOCK_HUB, '--port', '0', '--seed', 'boss', '--registry-dir', regDir, '--state-dir', stateDir, '--quiet'],
    { stdio: 'ignore' })
  test.after(() => { try { child.kill() } catch { /* ignore */ } })
  const hubFile = path.join(stateDir, 'hub.json')
  const t0 = Date.now()
  while (!fs.existsSync(hubFile)) {
    if (Date.now() - t0 > 10000) throw new Error('mock-hub did not write hub.json')
    await tick(50)
  }
  const { port } = JSON.parse(fs.readFileSync(hubFile, 'utf8'))
  const reqHub = async (method, p, body, headers = {}) => {
    const r = await fetch(`http://127.0.0.1:${port}${p}`, {
      method, headers: { 'content-type': 'application/json', ...headers },
      body: body ? JSON.stringify(body) : undefined,
    })
    return { s: r.status, b: JSON.parse(await r.text() || '{}') }
  }
  for (let i = 0; i < 100; i++) {
    try { await reqHub('GET', '/_mock/state'); break } catch { await tick(50) }
  }
  const m = await mountSidebar({ registryDir: regDir })
  test.after(() => m.close())
  const view = async () => j(await m.call('GET', '/xmuse/view?since=0'))
  const actP = async (body) => {
    const r = await m.call('POST', '/xmuse/act', body)
    return { status: r.status, b: j(r) }
  }

  // 先一键加入（成员 dsh）
  const list = j(await m.call('GET', '/xmuse/rooms'))
  assert.equal(list.hubs.length, 1)
  assert.equal((await m.call('POST', '/xmuse/join-local', { room_id: list.hubs[0].room_id })).status, 200)

  // member_add：成功 + 非法 vendor 400
  let r = await actP({ act: 'member_add', vendor: 'dsh', role: 'executor', description: 'w', name: 'n-1' })
  assert.equal(r.status, 200)
  assert.equal(r.b.member_id, 'n-1')
  r = await actP({ act: 'member_add', vendor: 'slack' })
  assert.equal(r.status, 400)
  assert.equal(r.b.error, 'bad_vendor')

  // member_edit：改角色成功；空改 400
  r = await actP({ act: 'member_edit', member: 'n-1', role: 'reviewer', description: 'rv' })
  assert.equal(r.status, 200)
  assert.equal((await view()).members.find((x) => x.id === 'n-1').role, 'reviewer')
  r = await actP({ act: 'member_edit', member: 'n-1' })
  assert.equal(r.status, 400)

  // pause/resume：状态翻转
  assert.equal((await actP({ act: 'pause', member: 'n-1' })).status, 200)
  assert.equal((await view()).members.find((x) => x.id === 'n-1').status, 'paused')
  assert.equal((await actP({ act: 'resume', member: 'n-1' })).status, 200)
  assert.equal((await view()).members.find((x) => x.id === 'n-1').status, 'idle')

  // thread_new：成功 + 私有标记；重复 409
  r = await actP({ act: 'thread_new', id: '#g1', members: ['n-1'], title: 'G1' })
  assert.equal(r.status, 200)
  assert.equal(r.b.thread, '#g1')
  const th = (await view()).threads.find((t) => t.id === '#g1')
  assert.equal(th.private, true)
  assert.ok(th.members.includes('n-1'))
  r = await actP({ act: 'thread_new', id: '#g1', members: [] })
  assert.equal(r.status, 409)
  assert.equal(r.b.error, 'thread_exists')

  // thread_add/remove：拉 boss 进群再移出；再移一次 400 not_in_thread
  assert.equal((await actP({ act: 'thread_add', thread: '#g1', member: 'boss' })).status, 200)
  assert.ok((await view()).threads.find((t) => t.id === '#g1').members.includes('boss'))
  assert.equal((await actP({ act: 'thread_remove', thread: '#g1', member: 'boss' })).status, 200)
  r = await actP({ act: 'thread_remove', thread: '#g1', member: 'boss' })
  assert.equal(r.status, 400)
  assert.equal(r.b.error, 'not_in_thread')

  // transfer_host + remove：主控不能直接删（409 is_host），移交后可删
  assert.equal((await actP({ act: 'transfer_host', member: 'n-1' })).status, 200)
  assert.equal((await view()).room.host, 'n-1')
  r = await actP({ act: 'remove', member: 'n-1' })
  assert.equal(r.status, 409)
  assert.equal(r.b.error, 'is_host')
  assert.equal((await actP({ act: 'transfer_host', member: 'boss' })).status, 200)
  assert.equal((await actP({ act: 'remove', member: 'n-1' })).status, 200)
  assert.ok(!(await view()).members.some((x) => x.id === 'n-1'))

  // 成员令牌调 member_add 一律 403（直接打 hub，拿 sidebar.json 里存的成员令牌）
  const stored = JSON.parse(fs.readFileSync(m.file, 'utf8'))
  r = await reqHub('POST', '/v1/act', { act: 'member_add', vendor: 'dsh' },
    { authorization: `Bearer ${stored.memberToken}`, 'x-xmuse-session': stored.sessionId })
  assert.equal(r.s, 403)
})

test('v0.1 done/share/host_wait/wakes (8.4/8.5/8.6)', async () => {
  const regDir = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-reg3-'))
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-reghub3-'))
  const stateDir = path.join(tmp, 'hubstate')
  fs.mkdirSync(stateDir, { recursive: true })
  const child = spawn(process.execPath,
    [MOCK_HUB, '--port', '0', '--seed', 'boss', '--registry-dir', regDir, '--state-dir', stateDir, '--quiet'],
    { stdio: 'ignore' })
  test.after(() => { try { child.kill() } catch { /* ignore */ } })
  const hubFile = path.join(stateDir, 'hub.json')
  const t0 = Date.now()
  while (!fs.existsSync(hubFile)) {
    if (Date.now() - t0 > 10000) throw new Error('mock-hub did not write hub.json')
    await tick(50)
  }
  const { port } = JSON.parse(fs.readFileSync(hubFile, 'utf8'))
  const reqHub = async (method, p, body, headers = {}) => {
    const r = await fetch(`http://127.0.0.1:${port}${p}`, {
      method, headers: { 'content-type': 'application/json', ...headers },
      body: body ? JSON.stringify(body) : undefined,
    })
    return { s: r.status, b: JSON.parse(await r.text() || '{}') }
  }
  for (let i = 0; i < 100; i++) {
    try { await reqHub('GET', '/_mock/state'); break } catch { await tick(50) }
  }
  const m = await mountSidebar({ registryDir: regDir })
  test.after(() => m.close())
  const view = async () => j(await m.call('GET', '/xmuse/view?since=0'))
  const actP = async (body) => {
    const r = await m.call('POST', '/xmuse/act', body)
    return { status: r.status, b: j(r) }
  }
  const list = j(await m.call('GET', '/xmuse/rooms'))
  assert.equal((await m.call('POST', '/xmuse/join-local', { room_id: list.hubs[0].room_id })).status, 200)

  // 分享：用户私信 cl-9，cl-9 申请分享给 boss → share 审批带 excerpt；批准后 via=shared + shared_from
  await reqHub('POST', '/_mock/member', { id: 'cl-9', vendor: 'claude', description: 'c', wakes_hour: 7 })
  const dm1 = (await reqHub('POST', '/_mock/send', { from: 'human', to: 'cl-9', text: '密钥 ALPHA-1' })).b.id
  const sh = await reqHub('POST', '/_mock/share', { member: 'cl-9', message_id: dm1, to: 'boss', why: 'need' })
  assert.equal(sh.b.status, 'pending_approval')
  assert.equal(sh.b.approval, 'share:1')
  const shares = (await view()).approvals.filter((a) => a.kind === 'share')
  assert.equal(shares.length, 1)
  assert.ok(shares[0].detail.excerpt.includes('ALPHA-1'), 'excerpt in approval detail')
  assert.equal(shares[0].detail.to, 'boss')
  let r = await actP({ act: 'approve', id: 'share:1', decision: 'once' })
  assert.equal(r.status, 200)
  assert.equal(r.b.status, 'delivered')
  const got = (await view()).timeline.filter((x) => x.via === 'shared').at(-1)
  assert.equal(got.shared_from.member, 'cl-9')
  assert.equal(got.shared_from.message_id, dm1)

  // done 改判：completed + 跨 scope 的 decision → needs_alignment，outcome_by=hub + reason
  await reqHub('POST', '/_mock/done', { from: 'boss', summary: '做完 X', outcome: 'completed', declares: [{ kind: 'decision', scope: 'module:x' }] })
  const d1 = (await view()).timeline.filter((x) => x.kind === 'done').at(-1)
  assert.equal(d1.outcome, 'needs_alignment')
  assert.equal(d1.outcome_by, 'hub')
  assert.ok(d1.outcome_reason.includes('decision'), 'reason mentions declares')

  // 证据：交了 evidence 但没状态 → unverified + transcript unavailable，不改判（无 declares）
  await reqHub('POST', '/_mock/done', { from: 'boss', summary: '做完 Y', evidence: [{ kind: 'test', ref: 'npm test', result: 'pass' }] })
  const d2 = (await view()).timeline.filter((x) => x.kind === 'done').at(-1)
  assert.equal(d2.outcome, 'completed')
  assert.equal(d2.outcome_by, 'member')
  assert.equal(d2.evidence_status, 'unverified')
  assert.deepEqual(d2.evidence_problems, ['transcript unavailable'])

  // host_wait：等谁、压住几条、何时唤醒；wake_host 立刻放行
  const nowS = Math.floor(Date.now() / 1000)
  await reqHub('POST', '/_mock/host_wait', { waiting_on: [{ member: 'cl-9', handoff_id: 'h1', since: nowS }], results_held: 2, wake_at: nowS + 300 })
  assert.deepEqual((await view()).host_wait, { waiting_on: [{ member: 'cl-9', handoff_id: 'h1', since: nowS }], results_held: 2, wake_at: nowS + 300 })
  r = await actP({ act: 'wake_host' })
  assert.equal(r.status, 200)
  assert.equal(r.b.ok, true)

  // 成员卡片 wakes_hour（注入口直设，确定性读数）
  assert.equal((await view()).members.find((x) => x.id === 'cl-9').wakes_hour, 7)
})

test('client.js: single-file ModuleLoader drawer, no imports, no innerHTML, covers v0 UI', async () => {
  const src = fs.readFileSync(CLIENT_JS, 'utf8')
  new Script(src, { filename: 'client.js' }) // 只解析不执行：语法检查（沙箱里不能 spawn，用 vm）
  assert.match(src, /window\.__ModuleLoader__\.load/)
  assert.ok(!/^\s*import\s/m.test(src), 'no imports')
  assert.ok(!src.includes('innerHTML'), 'DOM-only, no innerHTML')
  assert.ok(!hasToken(src), 'no token placeholder in frontend')
  for (const marker of [
    "'/view?since='", "'/timeline?before='", "'/rooms'", "'/join'", "'/join-local'",
    "act: 'say'", "act: 'ack'", "act: 'approve'", "act: 'invite'",
    "act: 'member_add'", "act: 'member_edit'", "act: 'thread_new'", "act: 'thread_add'",
    "act: 'thread_remove'", "act: 'transfer_host'", "act: 'remove'", "'pause'", "'resume'",
    '批准一次', '总是', '拒绝', '加载更早', '邀请码', '复制命令',
    '本机房间', '添加成员', '新建群', '设为主控', '拉进群', '私聊', '移出', '🔒',
    '结果：', 'hub 改判', '未核实', '分享自', 'host_wait', "act: 'wake_host'", '现在叫醒',
    '主控在等谁', '唤醒', 'excerpt', 'share',
    'data-me', 'mode: push', 'mode: overlay',
  ]) assert.ok(src.includes(marker), `client covers ${marker}`)
})
