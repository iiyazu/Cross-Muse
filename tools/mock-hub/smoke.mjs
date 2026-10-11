// 假 hub 冒烟测试：node tools/mock-hub/smoke.mjs   （自己起一个 hub 子进程，端口 43991）
import { spawn } from 'node:child_process'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'

const PORT = 43991
const B = `http://127.0.0.1:${PORT}`
const child = spawn(process.execPath, [fileURLToPath(new URL('./mock-hub.mjs', import.meta.url)), '--port', String(PORT), '--quiet'], { stdio: 'ignore' })
const j = async (m, p, body, h = {}) => {
  const r = await fetch(B + p, { method: m, headers: { 'content-type': 'application/json', ...h }, body: body ? JSON.stringify(body) : undefined })
  const t = await r.text()
  return { s: r.status, b: t ? JSON.parse(t) : null }
}
const A = t => ({ authorization: 'Bearer ' + t })
try {
  for (let i = 0; i < 50; i++) { try { await fetch(B + '/_mock/state'); break } catch { await new Promise(r => setTimeout(r, 100)) } }
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
  await j('POST', '/v1/act', { act: 'ack', ids: [id] }, { ...A(host.member_token), 'x-xmuse-session': 's1' })
  r = await j('GET', '/v1/view?since=0', null, A(host.operator_token)); assert.equal(r.b.members.find(m => m.id === 'coord').unread, 0)
  // operator say -> from human via claude sidebar
  r = await j('POST', '/v1/act', { act: 'say', to: '#dev', text: 'hi all' }, A(host.operator_token)); assert.equal(r.s, 200)
  const t = (await j('GET', '/v1/view?since=0', null, A(host.operator_token))).b.timeline.at(-1)
  assert.equal(t.from, 'human'); assert.equal(t.via, 'claude sidebar')
  // 审批
  const ap = (await j('POST', '/_mock/approval', { member: 'dsh-1', summary: 'npm i' })).b
  assert.equal((await j('POST', '/v1/act', { act: 'approve', id: ap.id, decision: 'once' }, { ...A(host.member_token), 'x-xmuse-session': 's1' })).s, 403)
  assert.equal((await j('POST', '/v1/act', { act: 'approve', id: ap.id, decision: 'once' }, A(host.operator_token))).s, 200)
  // timeline 分页
  r = await j('GET', `/v1/timeline?before=${t.id}&limit=1`, null, A(host.operator_token)); assert.equal(r.s, 200); assert.ok(r.b.items.length === 1)
  console.log('mock-hub smoke: OK')
} catch (e) { console.error('FAIL', e); process.exitCode = 1 } finally { child.kill() }
