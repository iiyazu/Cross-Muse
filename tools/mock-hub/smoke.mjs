// 假 hub 冒烟测试：node tools/mock-hub/smoke.mjs
// 自己起两个 hub 子进程（端口 0 随机，结束时都关掉）：
//   L 兼容模式（无登记目录，v0 用法，原有用例）；H 带临时登记目录（v0.1 全部新增能力）。
import { spawn } from 'node:child_process'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HUB = fileURLToPath(new URL('./mock-hub.mjs', import.meta.url))
const A = t => ({ authorization: 'Bearer ' + t })
const M = (t, sess) => ({ ...A(t), 'x-xmuse-session': sess })
const children = []

async function startHub(extra = []) {
  const child = spawn(process.execPath, [HUB, '--port', '0', '--quiet', ...extra], { stdio: ['ignore', 'pipe', 'inherit'] })
  children.push(child)
  const exited = new Promise(r => child.on('exit', r))
  const base = await new Promise((resolve, reject) => {
    let buf = ''
    child.stdout.on('data', d => { buf += d; const m = buf.match(/listening on (http:\/\/127\.0\.0\.1:\d+)/); if (m) resolve(m[1]) })
    child.on('exit', () => reject(new Error('mock-hub exited early')))
    setTimeout(() => reject(new Error('mock-hub did not start')), 10000)
  })
  const j = async (m, p, body, h = {}) => {
    const r = await fetch(base + p, { method: m, headers: { 'content-type': 'application/json', ...h }, body: body ? JSON.stringify(body) : undefined })
    const t = await r.text()
    return { s: r.status, b: t ? JSON.parse(t) : null }
  }
  return { child, base, j, exited }
}

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'xmuse-mockhub-smoke-'))
try {
  // =============== 兼容模式：原有用例（v0）===============
  {
    const { j } = await startHub()
    let r = await j('POST', '/v1/rooms', { dir: 'C:\\x', name: 'demo', vendor: 'claude', session_id: 's1', member_id: 'coord' })
    assert.equal(r.s, 200); const host = r.b
    assert.equal((await j('POST', '/v1/rooms', { dir: 'x', name: 'y', vendor: 'claude', session_id: 's' })).s, 409)
    r = await j('GET', '/v1/view?since=0', null, { ...A(host.member_token), 'x-xmuse-session': 's1' })
    assert.equal(r.s, 200); assert.equal(r.b.me.id, 'coord'); const v0 = r.b.version
    assert.equal((await j('GET', '/v1/view?since=0', null, { ...A(host.member_token), 'x-xmuse-session': 'zzz' })).s, 409)
    // 成员令牌不能邀请
    assert.equal((await j('POST', '/v1/act', { act: 'invite', vendor: 'dsh', role: 'executor' }, { ...A(host.member_token), 'x-xmuse-session': 's1' })).s, 403)
    r = await j('POST', '/v1/act', { act: 'invite', vendor: 'dsh', role: 'executor', description: 'worker', name: 'dsh-1' }, A(host.operator_token))
    assert.equal(r.s, 200); const code = r.b.code
    assert.equal((await j('POST', '/v1/join', { code, vendor: 'claude', session_id: 's2', client_info: {} })).s, 403)
    r = await j('POST', '/v1/join', { code, vendor: 'dsh', session_id: 's2', client_info: {} })
    assert.equal(r.s, 200); const dsh = r.b; assert.equal(dsh.member_id, 'dsh-1')
    assert.equal((await j('POST', '/v1/join', { code, vendor: 'dsh', session_id: 's3', client_info: {} })).s, 409)
    // 长轮询：先挂起，再被写操作唤醒
    r = await j('GET', '/v1/view?since=0', null, A(host.operator_token)); const ver = r.b.version
    const waiting = j('GET', `/v1/view?since=${ver}&wait=5`, null, A(host.operator_token))
    await new Promise(r => setTimeout(r, 200))
    await j('POST', '/_mock/say', { from: 'dsh-1', to: 'coord', text: '@coord 你好' })
    r = await waiting; assert.equal(r.s, 200); assert.equal(r.b.timeline.at(-1).for_me, true)
    assert.equal(r.b.members.find(m => m.id === 'coord').unread, 1)
    // 超时 204
    r = await j('GET', `/v1/view?since=${r.b.version}&wait=1`, null, A(host.operator_token)); assert.equal(r.s, 204)
    // ack
    const id = (await j('GET', '/v1/view?since=0', null, A(host.operator_token))).b.timeline.at(-1).id
    r = await j('POST', '/v1/act', { act: 'ack', ids: [id] }, { ...A(host.member_token), 'x-xmuse-session': 's1' })
    assert.equal(r.s, 200); assert.equal(r.b.acked, 1)
    r = await j('GET', '/v1/view?since=0', null, A(host.operator_token)); assert.equal(r.b.members.find(m => m.id === 'coord').unread, 0)
    // operator say -> from human via claude sidebar
    r = await j('POST', '/v1/act', { act: 'say', to: '#dev', text: 'hi all' }, A(host.operator_token)); assert.equal(r.s, 200)
    const t = (await j('GET', '/v1/view?since=0', null, A(host.operator_token))).b.timeline.at(-1)
    assert.equal(t.from, 'human'); assert.equal(t.via, 'claude sidebar')
    // 审批
    const ap = (await j('POST', '/_mock/approval', { member: 'dsh-1', summary: 'npm i' })).b
    r = await j('POST', '/v1/act', { act: 'approve', id: ap.id, decision: 'once' }, { ...A(host.member_token), 'x-xmuse-session': 's1' })
    assert.equal(r.s, 403); assert.equal(r.b.error, 'operator_only'); assert.match(r.b.message, /forbidden/)
    assert.equal((await j('POST', '/v1/act', { act: 'approve', id: ap.id, decision: 'once' }, A(host.operator_token))).s, 200)
    // timeline 分页
    r = await j('GET', `/v1/timeline?before=${t.id}&limit=1`, null, A(host.operator_token)); assert.equal(r.s, 200); assert.ok(r.b.items.length === 1)
    // 兼容模式：没有登记目录，不查 x-xmuse-sidebar；v0 的 vendor 不在列表里的邀请不再接受
    assert.equal((await j('POST', '/v1/act', { act: 'invite', vendor: 'gemini', role: 'x' }, A(host.operator_token))).s, 400)
    void v0
    console.log('mock-hub smoke (v0 compat): OK')
  }

  // =============== v0.1：带登记目录的 hub ===============
  const reg = path.join(tmp, 'registry')
  const WS = '/mnt/c/Users/x/ws'
  const { j, child, exited } = await startHub(['--registry-dir', reg, '--dir', 'C:\\Users\\x\\ws', '--host-batch-max-s', '600'])
  let r

  // ---- 8.1 登记表和侧栏凭据 ----
  const key = fs.readFileSync(path.join(reg, 'sidebar.key'), 'utf8').trim()
  assert.match(key, /^[0-9a-f]{64}$/)
  if (process.platform !== 'win32') assert.equal(fs.statSync(path.join(reg, 'sidebar.key')).mode & 0o777, 0o600)
  const hubs = () => JSON.parse(fs.readFileSync(path.join(reg, 'hubs.json'), 'utf8')).hubs
  assert.equal(hubs().length, 1)
  let ent = hubs()[0]
  assert.deepEqual(Object.keys(ent).sort(), ['dir', 'host', 'name', 'pid', 'room_id', 'started_at', 'url'])
  assert.equal(ent.pid, child.pid); assert.equal(ent.host, null); assert.match(ent.url, /^http:\/\/127\.0\.0\.1:\d+$/)
  const K = { 'x-xmuse-sidebar': key }

  const body = { dir: 'C:\\Users\\x\\ws', name: 'demo', vendor: 'claude', session_id: 'sc', member_id: 'coord' }
  for (const h of [{}, { 'x-xmuse-sidebar': 'wrong' }, { 'x-xmuse-sidebar': key.toUpperCase() }]) {
    r = await j('POST', '/v1/rooms', body, h); assert.equal(r.s, 401); assert.equal(r.b.error, 'bad_sidebar_key')
  }
  r = await j('POST', '/v1/rooms', { ...body, dir: 'C:\\other' }, K); assert.equal(r.s, 400); assert.equal(r.b.error, 'wrong_dir')
  r = await j('GET', '/v1/rooms', null, K); assert.equal(r.s, 200); assert.equal(r.b.room, null); assert.deepEqual(r.b.members, [])
  r = await j('POST', '/v1/join', { dir: WS, vendor: 'claude', session_id: 'x' }, K); assert.equal(r.s, 404); assert.equal(r.b.error, 'no_room')
  r = await j('POST', '/v1/rooms', body, K); assert.equal(r.s, 200)
  const coord = r.b; assert.equal(coord.member_id, 'coord'); assert.ok(coord.room.id && coord.member_token && coord.operator_token)
  ent = hubs()[0]; assert.equal(ent.host, 'coord'); assert.equal(ent.name, 'demo'); assert.equal(ent.room_id, coord.room.id)
  const CM = M(coord.member_token, 'sc'), CO = A(coord.operator_token)

  // GET /v1/rooms：要凭据；成员令牌 403（先于凭据）
  assert.equal((await j('GET', '/v1/rooms')).s, 401)
  assert.equal((await j('GET', '/v1/rooms', null, CO)).s, 401)
  r = await j('GET', '/v1/rooms', null, K)
  assert.deepEqual(Object.keys(r.b.room).sort(), ['created_at', 'dir', 'host', 'id', 'name'])
  assert.deepEqual(r.b.members, [{ id: 'coord', vendor: 'claude', role: 'coordinator', online: true }])
  for (const [m, p, b] of [['GET', '/v1/rooms'], ['POST', '/v1/rooms', body], ['POST', '/v1/join', { dir: WS, vendor: 'claude', session_id: 'z' }]]) {
    for (const h of [K, {}]) {
      r = await j(m, p, b, { ...CM, ...h }); assert.equal(r.s, 403); assert.equal(r.b.error, 'member_forbidden')
    }
  }

  // 不带 code 的 join
  const join = (b, h = K) => j('POST', '/v1/join', { dir: WS, vendor: 'claude', session_id: 'sj', ...b }, h)
  r = await join({}, {}); assert.equal(r.s, 401); assert.equal(r.b.error, 'bad_sidebar_key')
  r = await join({ dir: 'C:\\nope' }); assert.equal(r.s, 400); assert.equal(r.b.error, 'wrong_dir')
  r = await join({ dir: undefined, room_id: 'r-nope' }); assert.equal(r.s, 404); assert.equal(r.b.error, 'unknown_room')
  r = await join({ dir: undefined }); assert.equal(r.s, 400)
  r = await join({ vendor: 'gemini' }); assert.equal(r.s, 400)
  r = await join({ name: 'human' }); assert.equal(r.s, 400)
  r = await join({ role: 5 }); assert.equal(r.s, 400)
  r = await join({ role: 'reviewer', description: 'reviews D4', session_id: 's-cl' }); assert.equal(r.s, 200)
  assert.equal(r.b.member_id, 'claude'); assert.equal(r.b.room.id, coord.room.id); assert.deepEqual(Object.keys(r.b).sort(), ['member_id', 'member_token', 'operator_token', 'room'])
  const cl = r.b, CLM = M(cl.member_token, 's-cl'), CLO = A(cl.operator_token)
  r = await join({ dir: undefined, room_id: coord.room.id, session_id: 's-cl2' }); assert.equal(r.b.member_id, 'claude-2')
  const cl2 = r.b, CL2M = M(cl2.member_token, 's-cl2')
  r = await join({ name: 'rev-1', role: 'reviewer', session_id: 's-rev', vendor: 'dsh' }); assert.equal(r.b.member_id, 'rev-1')
  const rev = r.b, REVM = M(rev.member_token, 's-rev')
  // 接管：同名、同 vendor、没绑会话的成员；已绑定 / vendor 不同 → 409 member_exists
  await j('POST', '/_mock/member', { id: 'dog', vendor: 'claude', role: 'executor' })
  r = await join({ name: 'dog', vendor: 'dsh' }); assert.equal(r.s, 409); assert.equal(r.b.error, 'member_exists')
  r = await join({ name: 'dog', session_id: 's-dog' }); assert.equal(r.s, 200); assert.equal(r.b.member_id, 'dog')
  r = await join({ name: 'dog', session_id: 's-dog2' }); assert.equal(r.s, 409); assert.equal(r.b.error, 'member_exists')
  const dog = (await j('POST', '/v1/join', { dir: WS, vendor: 'claude', session_id: 's-d', name: 'dog2' }, K)).b
  // 旧路径（带 code）照旧，不查凭据
  r = await j('POST', '/v1/act', { act: 'invite', vendor: 'opencode', role: 'executor', name: 'oc-1' }, CO); assert.match(r.b.code, /^[A-Z0-9]{4}-[A-Z0-9]{2}$/)
  r = await j('POST', '/v1/join', { code: r.b.code.toLowerCase(), vendor: 'opencode', session_id: 's-oc' }); assert.equal(r.s, 200); assert.equal(r.b.member_id, 'oc-1')
  r = await j('POST', '/v1/join', { code: 'ZZZZ-ZZ', vendor: 'opencode', session_id: 's' }); assert.equal(r.s, 404); assert.equal(r.b.error, 'unknown_code')
  // 加入写进 #room 事件
  let v = (await j('GET', '/v1/view?since=0', null, CLO)).b
  assert.ok(v.timeline.some(t => t.kind === 'system' && t.from === 'hub' && t.thread === '#room' && /claude joined the room \(claude, reviewer\)/.test(t.text)))
  assert.ok(v.timeline.some(t => /coord opened the room/.test(t.text)))
  assert.equal((await j('GET', '/v1/view?since=0', null, M(cl.member_token, 'wrong'))).s, 409)

  // ---- 8.2 member_add / member_edit ----
  const act = (h, b) => j('POST', '/v1/act', b, h)
  for (const b of [{ act: 'member_add', vendor: 'opencode' }, { act: 'member_edit', member: 'coord', role: 'x' }, { act: 'thread_new', id: '#z', members: [] },
    { act: 'thread_add', thread: '#z', member: 'coord' }, { act: 'thread_remove', thread: '#z', member: 'coord' }, { act: 'share_mark', message_id: 1 }, { act: 'wake_host' }]) {
    r = await act(CM, b); assert.equal(r.s, 403, b.act); assert.equal(r.b.error, 'operator_only', b.act)
  }
  assert.equal((await act(CO, { act: 'nope' })).b.error, 'unknown_act')
  const n0 = (await j('GET', '/_mock/state')).b.members.length
  for (const [b, st, code] of [[{ vendor: 'gemini' }, 400, 'bad_vendor'], [{}, 400, 'bad_vendor'], [{ vendor: 'opencode', name: 'coord' }, 409, 'member_exists'],
    [{ vendor: 'opencode', name: 'human' }, 400, 'bad_request'], [{ vendor: 'opencode', name: 'a b' }, 400, 'bad_request'],
    [{ vendor: 'opencode', model: 'no-provider' }, 400, 'bad_request'], [{ vendor: 'opencode', role: 7 }, 400, 'bad_request']]) {
    r = await act(CO, { act: 'member_add', ...b }); assert.deepEqual([r.s, r.b.error], [st, code], JSON.stringify(b))
  }
  assert.equal((await j('GET', '/_mock/state')).b.members.length, n0)
  r = await act(CO, { act: 'member_add', vendor: 'opencode' }); assert.deepEqual(r.b, { member_id: 'opencode' })
  r = await act(CO, { act: 'member_add', vendor: 'opencode' }); assert.deepEqual(r.b, { member_id: 'opencode-2' })
  r = await act(CO, { act: 'member_add', vendor: 'dsh', name: 'dsh-w', role: 'executor', description: 'worker', model: 'p/m' }); assert.deepEqual(r.b, { member_id: 'dsh-w' })
  v = (await j('GET', '/v1/view?since=0', null, CO)).b
  let mm = v.members.find(m => m.id === 'dsh-w')
  assert.deepEqual([mm.vendor, mm.role, mm.description, mm.model, mm.status, mm.online, mm.paused], ['dsh', 'executor', 'worker', 'p/m', 'idle', true, false])
  assert.equal(v.members.find(m => m.id === 'opencode').model, 'opencode-go/muse-spark-1.3-contributor')
  assert.ok(v.timeline.some(t => t.kind === 'system' && t.thread === '#room' && /dsh-w was added to the room \(dsh, executor, p\/m\): worker/.test(t.text)))
  for (const m of v.members) assert.ok(Number.isInteger(m.wakes_hour) && !('session_id' in m), m.id)
  for (const [b, st, code] of [[{ member: 'ghost', role: 'x' }, 404, 'unknown_member'], [{ role: 'x' }, 404, 'unknown_member'], [{ member: 'claude' }, 400, 'bad_request'],
    [{ member: 'claude', role: 3 }, 400, 'bad_request'], [{ member: 'claude', model: ' ' }, 400, 'bad_request'], [{ member: 'opencode', model: 'no-slash' }, 400, 'bad_request']]) {
    r = await act(CO, { act: 'member_edit', ...b }); assert.deepEqual([r.s, r.b.error], [st, code], JSON.stringify(b))
  }
  r = await act(CO, { act: 'member_edit', member: 'claude', role: 'coder', description: 'writes code', model: 'claude-sonnet-x' }); assert.deepEqual(r.b, { ok: true })
  v = (await j('GET', '/v1/view?since=0', null, CO)).b
  mm = v.members.find(m => m.id === 'claude'); assert.deepEqual([mm.role, mm.description, mm.model], ['coder', 'writes code', 'claude-sonnet-x'])
  assert.ok(v.timeline.some(t => /claude was edited: role = coder, description = writes code, model = claude-sonnet-x/.test(t.text)))
  assert.equal((await act(CO, { act: 'remove', member: 'coord' })).b.error, 'is_host')
  r = await act(CO, { act: 'remove', member: 'dog2' }); assert.equal(r.s, 200)
  r = await join({ name: 'dog2', session_id: 'again' }); assert.equal(r.s, 409) // 被移除的 id 不再分配
  void dog

  // ---- 8.3 私有小群 ----
  r = await act(CO, { act: 'thread_new', id: '#pair', members: ['claude', 'claude-2'], title: 'Secret plans' }); assert.deepEqual(r.b, { thread: '#pair' })
  for (const [b, st, code] of [[{ id: '#pair', members: [] }, 409, 'thread_exists'], [{ id: '#room', members: [] }, 409, 'thread_exists'],
    [{ id: '#fresh', members: ['claude', 'ghost'] }, 400, 'unknown_member'], [{ id: 'fresh', members: [] }, 400, 'invalid_arguments'],
    [{ id: '#fresh' }, 400, 'bad_request'], [{ id: '#fresh', members: 'claude' }, 400, 'invalid_arguments']]) {
    r = await act(CO, { act: 'thread_new', ...b }); assert.deepEqual([r.s, r.b.error], [st, code], JSON.stringify(b))
  }
  await act(CO, { act: 'say', to: '#pub', text: 'public chatter @claude' })
  r = await act(CO, { act: 'say', to: '#pair', text: 'pair secret @claude' }); assert.equal(r.s, 200); assert.equal(r.b.thread, '#pair')
  v = (await j('GET', '/v1/view?since=0', null, CO)).b
  let th = v.threads.find(t => t.id === '#pair')
  assert.deepEqual([th.private, th.members, th.title, th.kind], [true, ['claude', 'claude-2', 'human'], 'Secret plans', 'topic'])
  assert.equal(v.threads.find(t => t.id === '#pub').private, false)
  assert.ok(v.timeline.some(t => t.thread === '#pair' && t.kind === 'system' && /private group #pair created/.test(t.text)))
  const tl = (view, id) => view.timeline.filter(t => t.thread === id)
  // 成员令牌：只看见 #room、公开群、自己所在的线程
  const rv = (await j('GET', '/v1/view?since=0', null, REVM)).b
  assert.ok(!rv.threads.some(t => t.id === '#pair') && !tl(rv, '#pair').length && rv.threads.some(t => t.id === '#pub'))
  assert.ok(rv.threads.some(t => t.id === '#room') && rv.threads.every(t => typeof t.private === 'boolean'))
  assert.equal(rv.members.find(m => m.id === 'rev-1').unread, 1) // 只有公开群的那条
  const cv = (await j('GET', '/v1/view?since=0', null, CLM)).b
  assert.ok(tl(cv, '#pair').length >= 2 && cv.threads.find(t => t.id === '#pair').private === true)
  assert.equal(cv.timeline.find(t => t.text === 'pair secret @claude').for_me, true) // 点名了它
  assert.equal(cv.members.find(m => m.id === 'claude-2').unread, 2) // 公开群那条加私有群里的 pair secret
  r = await j('GET', `/v1/timeline?before=99999&limit=200`, null, REVM); assert.ok(!r.b.items.some(t => t.thread === '#pair'))
  r = await j('GET', `/v1/timeline?before=99999&limit=200`, null, CLM); assert.ok(r.b.items.some(t => t.thread === '#pair'))
  r = await j('GET', `/v1/timeline?before=99999&limit=200`, null, CO); assert.ok(r.b.items.some(t => t.thread === '#pair'))
  // 非成员写私有群：403 not_a_member，也不能经注入口绕过
  r = await act(REVM, { act: 'say', to: '#pair', text: 'let me in' }); assert.equal(r.s, 403); assert.equal(r.b.error, 'not_a_member')
  r = await j('POST', '/_mock/say', { from: 'rev-1', to: '#pair', text: 'x' }); assert.equal(r.s, 403); assert.equal(r.b.error, 'not_a_member')
  // 对齐条目和审批的过滤
  await j('POST', '/_mock/align', { kind: 'decision', scope: 'thread:#pair', author: 'claude', text: 'the codeword is plum' })
  await j('POST', '/_mock/align', { kind: 'decision', scope: 'thread:#pair', author: 'claude', text: 'proposal in pair', status: 'proposed' })
  await j('POST', '/_mock/align', { kind: 'decision', scope: 'room', author: 'claude', text: 'public decision' })
  const al = view => view.alignment.map(e => e.text)
  assert.deepEqual(al((await j('GET', '/v1/view?since=0', null, REVM)).b), ['public decision'])
  assert.equal((await j('GET', '/v1/view?since=0', null, REVM)).b.approvals.filter(a => a.kind === 'alignment').length, 0)
  assert.equal(al((await j('GET', '/v1/view?since=0', null, CLM)).b).length, 3)
  assert.equal((await j('GET', '/v1/view?since=0', null, CLM)).b.approvals.filter(a => a.kind === 'alignment').length, 1)
  assert.equal(al((await j('GET', '/v1/view?since=0', null, CO)).b).length, 3)
  // thread_add / thread_remove
  for (const [b, st, code] of [[{ thread: '#pub', member: 'claude' }, 400, 'public_thread'], [{ thread: '#room', member: 'claude' }, 400, 'public_thread'],
    [{ thread: '#pair', member: 'ghost' }, 400, 'unknown_member'], [{ thread: '#nothing', member: 'claude' }, 404, 'unknown_thread']]) {
    r = await act(CO, { act: 'thread_add', ...b }); assert.deepEqual([r.s, r.b.error], [st, code], JSON.stringify(b))
  }
  assert.deepEqual((await act(CO, { act: 'thread_add', thread: '#pair', member: 'rev-1' })).b, { ok: true })
  assert.ok((await j('GET', '/v1/view?since=0', null, REVM)).b.threads.some(t => t.id === '#pair'))
  assert.deepEqual((await act(CO, { act: 'thread_add', thread: '#pair', member: 'rev-1' })).b, { ok: true }) // 已在：不重复
  assert.equal((await j('GET', '/v1/view?since=0', null, CO)).b.timeline.filter(t => /rev-1 was added to #pair/.test(t.text)).length, 1)
  assert.deepEqual((await act(CO, { act: 'thread_remove', thread: '#pair', member: 'rev-1' })).b, { ok: true })
  for (const [b, st, code] of [[{ thread: '#pair', member: 'rev-1' }, 400, 'not_in_thread'], [{ thread: '#pair', member: 'human' }, 400, 'invalid_arguments'],
    [{ thread: '#pub', member: 'claude' }, 400, 'public_thread'], [{ thread: '#nothing', member: 'claude' }, 404, 'unknown_thread']]) {
    r = await act(CO, { act: 'thread_remove', ...b }); assert.deepEqual([r.s, r.b.error], [st, code], JSON.stringify(b))
  }
  assert.ok(!(await j('GET', '/v1/view?since=0', null, REVM)).b.threads.some(t => t.id === '#pair'))
  // 成员自建私有群（模拟 xmuse_send 带 members），发送者和用户自动在内
  r = await j('POST', '/_mock/send', { from: 'claude', to: '#duo', text: 'just us @claude-2', members: ['claude-2'] }); assert.equal(r.s, 200); assert.equal(r.b.thread, '#duo')
  th = (await j('GET', '/v1/view?since=0', null, CO)).b.threads.find(t => t.id === '#duo')
  assert.deepEqual([th.private, th.members], [true, ['claude', 'claude-2', 'human']])
  assert.ok(!(await j('GET', '/v1/view?since=0', null, REVM)).b.threads.some(t => t.id === '#duo'))
  assert.equal((await j('POST', '/_mock/send', { from: 'claude', to: '#oops', text: 'x', members: ['ghost'] })).b.error, 'unknown_member')
  assert.equal((await j('POST', '/_mock/send', { from: 'claude', to: '#oops2', text: 'x', members: 'claude-2' })).b.error, 'invalid_arguments')
  assert.ok(!(await j('GET', '/_mock/state')).b.threads.some(t => t.id === '#oops'))
  r = await j('POST', '/_mock/send', { from: 'claude', to: '#pub', text: 'ignored members', members: ['claude-2'] }); assert.equal(r.s, 200) // 已存在的公开群：members 无效
  assert.equal((await j('GET', '/v1/view?since=0', null, CO)).b.threads.find(t => t.id === '#pub').private, false)
  // 退出自己所在的私有小群
  r = await j('POST', '/_mock/leave_thread', { member: 'claude-2', thread: '#duo' }); assert.deepEqual(r.b, { ok: true, thread: '#duo' })
  r = await j('POST', '/_mock/leave_thread', { member: 'claude-2', thread: '#duo' }); assert.equal(r.b.error, 'unknown_thread')
  r = await j('POST', '/_mock/leave_thread', { member: 'claude', thread: '#pub' }); assert.equal(r.b.error, 'public_thread')

  // ---- 8.4 主控分派和结果标签 ----
  r = await act(CO, { act: 'say', to: '#room', text: '做个登录页' })
  assert.equal(r.s, 200); assert.equal(r.b.routed_to, 'coord'); assert.equal(r.b.thread, '#room'); const routed = r.b.id
  r = await act(CO, { act: 'say', text: '没有 to 也归主控' }); assert.equal(r.b.routed_to, 'coord'); assert.equal(r.b.thread, '#room')
  r = await act(CO, { act: 'say', to: '#room', text: '@claude 点名的话', mentions: [] }); assert.equal(r.b.routed_to, undefined)
  r = await act(CO, { act: 'say', to: '#room', text: '带 mentions', mentions: ['claude-2'] }); assert.equal(r.b.routed_to, undefined)
  r = await act(CO, { act: 'say', to: 'claude', text: '私聊' }); assert.equal(r.b.routed_to, undefined); assert.equal(r.b.thread, 'dm:claude+human')
  r = await act(CO, { act: 'say', to: '#pub', text: '公开群不点名' }); assert.equal(r.b.routed_to, 'coord')
  r = await act(CO, { act: 'say', to: '#pair', text: '私有群不路由' }); assert.equal(r.b.routed_to, undefined)
  r = await act(CO, { act: 'say', to: 'dm:claude+claude-2', text: 'x' }); assert.equal(r.s, 400); assert.equal(r.b.error, 'bad_target')
  r = await act(CO, { act: 'say', to: 'nobody', text: 'x' }); assert.equal(r.s, 404); assert.equal(r.b.error, 'unknown_recipient')
  v = (await j('GET', '/v1/view?since=0', null, CLM)).b
  assert.equal(v.timeline.find(t => t.id === routed).for_me, false) // 其他人只收被动投递
  assert.equal(v.members.find(m => m.id === 'claude').unread >= 1, true) // 但仍算未读
  const cvw = (await j('GET', '/v1/view?since=0', null, CM)).b
  assert.equal(cvw.timeline.find(t => t.id === routed).for_me, true)
  assert.ok(cvw.members.find(m => m.id === 'coord').wakes_hour >= 1) // 同一秒到的一批算一次（真 hub 的近似口径）
  // 注入：用户经侧栏说话同样路由；wakes_hour / tokens_hour 可设
  r = await j('POST', '/_mock/say', { from: 'human', via: 'dsh sidebar', to: '#room', text: '再来一个' }); assert.equal(r.b.routed_to, 'coord')
  await j('POST', '/_mock/status', { member: 'claude', wakes_hour: 7, tokens_hour: 412000 })
  mm = (await j('GET', '/v1/view?since=0', null, CO)).b.members.find(m => m.id === 'claude'); assert.deepEqual([mm.wakes_hour, mm.tokens_hour], [7, 412000])

  // done 消息：标签、改判、证据
  const done = b => j('POST', '/_mock/done', { from: 'claude', next: 'coord', ...b })
  const item = async (id, h = CO) => (await j('GET', '/v1/view?since=0', null, h)).b.timeline.find(t => t.id === id)
  const hw = async (h = CO) => (await j('GET', '/v1/view?since=0', null, h)).b.host_wait
  assert.deepEqual(await hw(), { waiting_on: [], results_held: 0, wake_at: null })
  // 主控派两个活：claude 先交回 completed 时，claude-2 还没交回，结果按批次压住
  r = await j('POST', '/_mock/send', { from: 'coord', to: '#room', text: '分活', kind: 'handoff', mentions: ['claude', 'claude-2'] })
  assert.equal(r.s, 200); assert.equal((await hw()).waiting_on.length, 2)
  r = await done({ summary: '登录页做完了', evidence_status: 'verified' }); assert.equal(r.s, 200); assert.equal(r.b.outcome, 'completed'); const d1 = r.b.id
  let it = await item(d1)
  assert.deepEqual([it.kind, it.from, it.outcome, it.outcome_by, it.evidence_status, it.evidence_problems], ['done', 'claude', 'completed', 'member', 'verified', []])
  assert.ok(!('outcome_reason' in it))
  assert.equal(it.for_me, false) // completed：按批次等，不是马上给主控
  assert.equal((await item(d1, CM)).for_me, false)
  assert.equal((await hw()).results_held, 1)
  assert.equal((await hw(REVM)).results_held, 1) // 成员令牌也有 host_wait
  assert.ok(!('outcome' in (await item(routed))) && !('evidence_status' in (await item(routed)))) // 只有 done 有
  r = await done({ summary: '要改契约', declares: [{ kind: 'decision', statement: '改 v1', scope: 'room' }] })
  it = await item(r.b.id); assert.deepEqual([it.outcome, it.outcome_by], ['needs_alignment', 'hub']); assert.match(it.outcome_reason, /declares decision beyond its own scope/)
  assert.equal(it.for_me, true) // needs_alignment 立即唤醒
  assert.equal((await item(d1)).for_me, true) // 带着之前扣住的结果一起
  assert.equal((await hw()).results_held, 0)
  r = await done({ summary: '声称测试过了', evidence: [{ kind: 'test', ref: 'npm test', result: 'ok' }], evidence_status: 'unverified', evidence_problems: ['npm test was not run in this turn'] })
  it = await item(r.b.id); assert.deepEqual([it.outcome, it.outcome_by, it.evidence_status, it.evidence_problems], ['blocked', 'hub', 'unverified', ['npm test was not run in this turn']])
  assert.match(it.outcome_reason, /evidence not verified: npm test was not run/); assert.equal(it.for_me, true)
  r = await done({ summary: '读不到日志', evidence: [{ kind: 'diff', ref: 'a.js' }] })
  it = await item(r.b.id); assert.deepEqual([it.outcome, it.outcome_by, it.evidence_status, it.evidence_problems], ['completed', 'member', 'unverified', ['transcript unavailable']])
  r = await done({ summary: '没交证据', outcome: 'progress' })
  it = await item(r.b.id); assert.deepEqual([it.outcome, it.outcome_by, it.evidence_status, it.evidence_problems, it.for_me], ['progress', 'member', 'none', [], false])
  assert.equal((await hw()).results_held, 1) // 读不到日志那条 completed 被扣住
  const heldId = (await j('GET', '/_mock/state')).b.messages.find(m => m.text === '读不到日志').id
  assert.equal((await item(heldId)).for_me, false)
  assert.equal((await done({ summary: 'x', outcome: 'weird' })).b.error, 'invalid_arguments')
  assert.equal((await j('POST', '/_mock/done', { from: 'ghost', summary: 'x' })).s, 404)
  // wake_host：不等合并，立即把扣住的结果投给主控
  r = await act(CM, { act: 'wake_host' }); assert.equal(r.s, 403)
  r = await act(CO, { act: 'wake_host' }); assert.deepEqual(r.b, { ok: true, released: 1 })
  assert.equal((await hw()).results_held, 0)
  assert.equal((await item(heldId)).for_me, true)
  await j('POST', '/_mock/done', { from: 'claude-2', next: 'coord', summary: '分活那一批交回' }) // 清掉上面那批
  assert.deepEqual(await hw(), { waiting_on: [], results_held: 0, wake_at: null })
  // 主控派 handoff：waiting_on，交回齐了自动合并唤醒；notify now 立即
  r = await j('POST', '/_mock/send', { from: 'coord', to: 'claude', kind: 'handoff', text: '做 A' }); assert.equal(r.s, 200); const h1 = r.b.id
  await j('POST', '/_mock/send', { from: 'coord', to: 'claude-2', kind: 'handoff', text: '做 B', notify: 'now' })
  let w = await hw(); assert.deepEqual(w.waiting_on.map(x => [x.member, x.handoff_id === h1 || typeof x.handoff_id === 'number', typeof x.since]), [['claude', true, 'number'], ['claude-2', true, 'number']])
  r = await done({ summary: 'A 完成' }); it = await item(r.b.id); assert.equal(it.for_me, false)
  w = await hw(); assert.deepEqual([w.waiting_on.map(x => x.member), w.results_held, typeof w.wake_at], [['claude-2'], 1, 'number'])
  r = await j('POST', '/_mock/done', { from: 'claude-2', summary: 'B 完成' }) // 没有 next 但对应 handoff；notify now
  it = await item(r.b.id); assert.equal(it.for_me, true); assert.equal((await item((await j('GET', '/_mock/state')).b.messages.find(m => m.text === 'A 完成').id)).for_me, true)
  assert.deepEqual(await hw(), { waiting_on: [], results_held: 0, wake_at: null })
  // 注入 host_wait
  r = await j('POST', '/_mock/host_wait', { waiting_on: [{ member: 'dsh-w', handoff_id: 1, since: 100 }], results_held: 2, wake_at: 1791726999 })
  assert.deepEqual(r.b, { waiting_on: [{ member: 'dsh-w', handoff_id: 1, since: 100 }], results_held: 2, wake_at: 1791726999 })
  assert.deepEqual(await hw(CM), r.b)
  assert.deepEqual((await j('POST', '/_mock/host_wait', { reset: true })).b, { waiting_on: [], results_held: 0, wake_at: null })

  // ---- 8.6 私信分享 ----
  const sh = b => j('POST', '/_mock/share', b)
  const dm1 = (await act(CO, { act: 'say', to: 'claude', text: '重试上限是 MAX_RETRY=7，别外传' })).b.id
  r = await j('GET', '/v1/view?since=0', null, CO); const nApp = r.b.approvals.length
  for (const [b, st, code] of [[{ member: 'claude', message_id: routed, to: 'claude-2' }, 403, 'not_shareable'], [{ member: 'claude-2', message_id: dm1, to: 'claude' }, 403, 'not_shareable'],
    [{ member: 'claude', message_id: 99999, to: 'claude-2' }, 403, 'not_shareable'], [{ member: 'claude', message_id: dm1, to: 'nobody' }, 404, 'unknown_recipient'],
    [{ member: 'claude', message_id: dm1, to: 'claude' }, 404, 'unknown_recipient'], [{ member: 'claude', message_id: dm1, to: '#pair2' }, 404, 'unknown_recipient']]) {
    r = await sh(b); assert.deepEqual([r.s, r.b.error], [st, code], JSON.stringify(b))
  }
  r = await sh({ member: 'claude', message_id: dm1, to: 'claude-2', why: 'claude-2 needs the limit' }); assert.deepEqual(r.b, { status: 'pending_approval', approval: 'share:1' })
  assert.deepEqual((await sh({ member: 'claude', message_id: dm1, to: 'claude-2' })).b, { status: 'pending_approval', approval: 'share:1' }) // 同一个问题只问一次
  assert.deepEqual((await sh({ member: 'claude', message_id: dm1, to: 'dm:claude+rev-1' })).b, { status: 'pending_approval', approval: 'share:2' }) // dm: 取另一端
  v = (await j('GET', '/v1/view?since=0', null, CO)).b
  const shares = v.approvals.filter(a => a.kind === 'share')
  assert.deepEqual(shares.map(a => a.id), ['share:1', 'share:2']); assert.equal(v.approvals.length, nApp + 2)
  assert.deepEqual(Object.keys(shares[0]).sort(), ['at', 'detail', 'id', 'kind', 'member', 'risk', 'summary'])
  assert.deepEqual([shares[0].member, shares[0].risk, shares[0].summary], ['claude', 'normal', `claude 想把 #${dm1} 分享给 claude-2`])
  assert.deepEqual(shares[0].detail, { message_id: dm1, to: 'claude-2', why: 'claude-2 needs the limit', excerpt: '重试上限是 MAX_RETRY=7，别外传' })
  for (const h of [CM, CLM, REVM]) assert.equal((await j('GET', '/v1/view?since=0', null, h)).b.approvals.filter(a => a.kind === 'share').length, 0) // 成员令牌看不到
  assert.equal((await act(CLM, { act: 'approve', id: 'share:1', decision: 'once' })).b.error, 'operator_only')
  assert.equal((await act(CO, { act: 'approve', id: 'share:1', decision: 'maybe' })).b.error, 'bad_request')
  assert.equal((await act(CO, { act: 'approve', id: 'share:99', decision: 'once' })).s, 404)
  r = await act(CO, { act: 'approve', id: 'share:1', decision: 'once' })
  assert.equal(r.s, 200); assert.deepEqual([r.b.ok, r.b.status, r.b.thread, r.b.woken], [true, 'delivered', 'dm:claude+claude-2', ['claude-2']]); const sid1 = r.b.id
  it = await item(sid1)
  assert.deepEqual([it.from, it.via, it.thread, it.kind, it.for_me], ['claude', 'shared', 'dm:claude+claude-2', 'message', false])
  assert.deepEqual(it.shared_from, { member: 'claude', message_id: dm1 }); assert.match(it.text, /^\[shared by claude: the user's private message #\d+ to them/); assert.ok(it.text.endsWith('\n重试上限是 MAX_RETRY=7，别外传'))
  assert.equal((await item(sid1, CL2M)).for_me, true) // 接收人被唤醒
  assert.ok(!('shared_from' in (await item(dm1))))
  assert.equal((await act(CO, { act: 'approve', id: 'share:1', decision: 'once' })).b.error, 'invalid_arguments') // 已处理
  assert.equal((await j('GET', '/v1/view?since=0', null, CO)).b.approvals.filter(a => a.kind === 'share').length, 1)
  // 一次性：下一次再问
  assert.equal((await sh({ member: 'claude', message_id: dm1, to: 'claude-2' })).b.approval, 'share:3')
  // reject：通知申请人，不投递
  r = await act(CO, { act: 'approve', id: 'share:2', decision: 'reject' }); assert.deepEqual(r.b, { ok: true, status: 'rejected' })
  v = (await j('GET', '/v1/view?since=0', null, CLM)).b
  const rj = v.timeline.filter(t => t.thread === 'dm:claude+human' && t.kind === 'system').at(-1)
  assert.equal(rj.from, 'hub'); assert.match(rj.text, /rejected your request share:2 to share #\d+ with rev-1/)
  assert.ok(!v.timeline.some(t => t.via === 'shared' && t.thread === 'dm:claude+rev-1'))
  // always：投递，并从此这条消息分享给任何人都不再问
  r = await act(CO, { act: 'approve', id: 'share:3', decision: 'always' }); assert.equal(r.b.status, 'delivered')
  r = await sh({ member: 'claude', message_id: dm1, to: 'rev-1' }); assert.equal(r.b.status, 'delivered'); assert.equal(r.b.thread, 'dm:claude+rev-1')
  assert.equal((await j('GET', '/v1/view?since=0', null, CO)).b.approvals.filter(a => a.kind === 'share').length, 0)
  const ok1 = (await j('GET', '/v1/view?since=0', null, CLM)).b.timeline.filter(t => t.thread === 'dm:claude+human' && t.kind === 'system').at(-1)
  assert.match(ok1.text, /approved your request share:3 \(always\): #\d+ was delivered to claude-2/)
  // share_mark
  const dm2 = (await act(CO, { act: 'say', to: 'claude-2', text: 'TIMEOUT_MS 是 3000' })).b.id
  for (const [b, st, code] of [[{ message_id: 'x' }, 400, 'invalid_arguments'], [{}, 400, 'invalid_arguments'], [{ message_id: 99999 }, 404, 'unknown_message'],
    [{ message_id: routed }, 403, 'not_shareable'], [{ message_id: sid1 }, 403, 'not_shareable'], [{ message_id: dm2, to: 'nobody' }, 404, 'unknown_recipient']]) {
    r = await act(CO, { act: 'share_mark', ...b }); assert.deepEqual([r.s, r.b.error], [st, code], JSON.stringify(b))
  }
  assert.deepEqual((await act(CO, { act: 'share_mark', message_id: dm2, to: 'claude' })).b, { ok: true })
  r = await sh({ member: 'claude-2', message_id: dm2, to: 'claude', why: 'x' }); assert.equal(r.b.status, 'delivered') // 标过：直接投递
  assert.equal((await sh({ member: 'claude-2', message_id: dm2, to: 'rev-1' })).b.status, 'pending_approval') // 标记只给 claude
  assert.deepEqual((await act(CO, { act: 'share_mark', message_id: dm2 })).b, { ok: true }) // 不带 to：任何人
  assert.equal((await sh({ member: 'claude-2', message_id: dm2, to: 'coord' })).b.status, 'delivered')

  // ---- 重置 / 注销 ----
  assert.equal((await j('POST', '/_mock/reset', {})).b.ok, true)
  assert.deepEqual((await j('GET', '/_mock/state')).b.threads, [])
  assert.equal(hubs()[0].host, null)
  child.kill()
  await exited
  assert.equal(hubs().length, 0) // 退出时注销
  console.log('mock-hub smoke (v0.1): OK')
  console.log('mock-hub smoke: OK')
} catch (e) { console.error('FAIL', e); process.exitCode = 1 } finally {
  for (const c of children) c.kill()
  fs.rmSync(tmp, { recursive: true, force: true })
}
