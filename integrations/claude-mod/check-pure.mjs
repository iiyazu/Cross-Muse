// Pure-function checks that run without the Claude CLI:
// node integrations/claude-mod/check-pure.mjs (from the repo root).
// Covers src/registry.ts and the v0.1 additions in src/format.ts.
// The full harness suite (xmuse.test.ts) still needs `claude plugin test`.
import { findRoom, isKeyShape, isLoopbackUrl, normDir, parseHubs, registryDirFrom } from './src/registry.ts'
import { doneMd, messageMd, renderHostWait, renderMembers } from './src/format.ts'

let fails = 0
const a = (c, m) => {
  if (!c) {
    console.error('FAIL', m)
    fails++
  }
}

a(normDir('C:\\X\\Y') === 'c:\\x\\y', 'normDir win')
a(normDir('/mnt/c/X/Y/') === 'c:\\x\\y', 'normDir mnt')
a(normDir('/home/u/x/') === '/home/u/x', 'normDir posix')
const es = parseHubs(JSON.stringify({ hubs: [
  { room_id: 'r-1', name: 'a', dir: 'C:\\p', url: 'http://127.0.0.1:1/', host: 'h', pid: 11, started_at: 1 },
  { room_id: 'r-2', name: 'a', dir: 'C:\\q', url: 'http://127.0.0.1:2/', host: 'h', pid: 12, started_at: 1 },
  { room_id: 'r-3', name: 'b', url: 'http://127.0.0.1:3/', host: 'h', pid: 11, started_at: 1 },
  'junk',
  { room_id: 'r-4' },
] }), p => p === 11)
a(es.map(e => e.room_id).join(',') === 'r-1,r-3', 'parseHubs live+valid')
a(parseHubs('not json', () => true).length === 0, 'parseHubs bad json')
a(findRoom(es, { roomId: 'r-3' }).entry.name === 'b', 'find id')
a((findRoom(es, { roomId: 'r-x' }).error || '').includes('unknown room'), 'find unknown')
const dup = [{ ...es[0], name: 'a' }, { ...es[0], room_id: 'r-9', name: 'a' }]
a((findRoom(dup, { name: 'a' }).error || '').includes('2'), 'find ambiguous')
a(findRoom(es, { name: 'b' }).entry.room_id === 'r-3', 'find name')
a(findRoom(es, { dir: '/mnt/c/p' }).entry.room_id === 'r-1', 'find dir')
a((findRoom(es, { dir: 'C:\\nope' }).error || '').includes('没有服务'), 'find wrong dir')
a((findRoom([], { dir: 'C:\\x' }).error || '').includes('没有登记'), 'find no rooms')
a(findRoom(es, {}).error !== undefined, 'find empty query')
a(isLoopbackUrl('http://127.0.0.1:9/') && isLoopbackUrl('http://localhost:9') && isLoopbackUrl('http://[::1]:9/'), 'loopback yes')
a(!isLoopbackUrl('http://192.168.1.2:9') && !isLoopbackUrl('https://example.com') && !isLoopbackUrl('nope'), 'loopback no')
a(isKeyShape('ab'.repeat(32)) && !isKeyShape('xyz'), 'key shape')
a(registryDirFrom({ XMUSE_REGISTRY_DIR: '/r' }, 'linux', '/h') === '/r', 'dir env')
a(registryDirFrom({}, 'win32', 'C:\\U\\me') === 'C:\\U\\me\\AppData\\Local\\xmuse', 'dir win')
a(registryDirFrom({ LOCALAPPDATA: 'D:\\L' }, 'win32', '') === 'D:\\L\\xmuse', 'dir win env')
a(registryDirFrom({}, 'linux', '/h') === '/h/.local/state/xmuse', 'dir posix')

const base = { id: 9, thread: '#room', from: 'dsh-1', via: null, to: [], mentions: [], text: '做完 X', at: 100, for_me: false }
const t1 = doneMd({ ...base, kind: 'done', outcome: 'needs_alignment', outcome_by: 'hub', outcome_reason: 'declares decision beyond its own scope' })
a(t1.includes('结果：needs_alignment') && t1.includes('hub 改判'), 'done upgrade tag')
const t2 = doneMd({ ...base, kind: 'done', outcome: 'completed', outcome_by: 'member', evidence_status: 'unverified', evidence_problems: ['transcript unavailable'] })
a(t2.includes('结果：completed') && t2.includes('未核实'), 'done unverified tag')
a(messageMd({ ...base, kind: 'message', via: 'shared', shared_from: { member: 'cl-9', message_id: 3 } }).includes('分享自 cl-9（#3）'), 'shared_from')
a(messageMd({ ...base, kind: 'question', routed_to: ['dsh-1', 'op-1'], route_reason: 'r' }).includes('已路由给 dsh-1、op-1'), 'routed list')
a(messageMd({ ...base, kind: 'question', routed_to: 'dsh-1' }).includes('已路由给 dsh-1'), 'routed single')
a(!messageMd({ ...base, kind: 'question' }).includes('已路由给'), 'unrouted clean')
const hw = renderHostWait({ host_wait: { waiting_on: [{ member: 'dsh-1', handoff_id: 'h7', since: 50 }], results_held: 2, wake_at: null } })
a(hw.includes('h7') && hw.includes('压住了 2 条结果'), 'host wait')
a(renderHostWait({}).includes('暂无等待'), 'host wait empty')
const mm = renderMembers({ room: { host: 'coord' }, members: [{ id: 'dsh-1', vendor: 'dsh', role: 'executor', description: '', status: 'idle', online: true, paused: false, unread: 0, wakes_hour: 7 }] }, 'coord')
a(mm.includes('唤醒7/h'), 'wakes_hour')

if (fails) {
  console.error(`PURE CHECKS: ${fails} failed`)
  process.exit(1)
}
console.log('PURE CHECKS: OK (33 assertions)')
