// End-to-end: mock hub <-> real `claude -p` (stream-json, haiku) with the xmuse mod.
// join -> an @ arrives -> the idle session wakes (timer + $.prompt.submit) -> the
// model answers through the xmuse `say` tool -> the mock hub sees the reply.
//
//   node integrations/claude-mod/e2e/run-e2e.mjs            (needs `claude` on PATH, logged in)
//
// Side effects: the mod's $.store (a JSON file under the claude config dir) holds
// the binding for the cwd of this run; the script ends with /xmuse leave and
// /xmuse hub clear to remove it. Only claude-haiku-5-5, two very short turns.
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const MOD = path.resolve(here, '..')
const HUB = path.resolve(here, '../../../tools/mock-hub/mock-hub.mjs')
const PORT = Number(process.env.E2E_PORT || 43120)
const B = `http://127.0.0.1:${PORT}`
const MODEL = process.env.E2E_MODEL || 'claude-haiku-5-5'
const sleep = ms => new Promise(r => setTimeout(r, ms))
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a)
const j = async (m, p, body) => {
  const r = await fetch(B + p, { method: m, headers: { 'content-type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
  return r.json()
}

const hub = spawn(process.execPath, [HUB, '--port', String(PORT), '--seed', 'coord', '--quiet'], { stdio: ['ignore', 'ignore', 'inherit'] })
let claude
let ok = false
try {
  for (let i = 0; i < 50; i++) {
    try { await fetch(B + '/_mock/state'); break } catch { await sleep(100) }
  }
  const inv = await j('POST', '/_mock/invite', { vendor: 'claude', role: 'executor', description: 'e2e sidebar test', name: 'claude-1' })
  log('invite created (code not printed)')

  claude = spawn('claude', [
    '-p', '--input-format', 'stream-json', '--output-format', 'stream-json', '--verbose',
    '--plugin-dir', MOD, '--model', MODEL, '--allowedTools', 'mcp__xmuse__say',
  ], { stdio: ['pipe', 'pipe', 'pipe'], cwd: process.env.E2E_CWD || process.cwd() })
  let results = 0
  const events = []
  let buf = ''
  claude.stdout.on('data', d => {
    buf += d
    let i
    while ((i = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, i); buf = buf.slice(i + 1)
      try {
        const ev = JSON.parse(line)
        events.push(ev)
        if (ev.type === 'result') { results++; log('result', JSON.stringify(ev.result).slice(0, 160)) }
        if (ev.type === 'assistant') for (const c of ev.message.content || []) {
          if (c.type === 'tool_use') log('tool_use', c.name, JSON.stringify(c.input).slice(0, 120))
          if (c.type === 'text') log('assistant', c.text.slice(0, 120))
        }
      } catch { /* not json */ }
    }
  })
  claude.stderr.on('data', d => process.stderr.write(d))
  const send = text => claude.stdin.write(JSON.stringify({ type: 'user', message: { role: 'user', content: [{ type: 'text', text }] } }) + '\n')
  const waitResults = async (n, ms = 90000) => {
    const t0 = Date.now()
    while (results < n) { if (Date.now() - t0 > ms) throw new Error('timeout waiting for result ' + n); await sleep(200) }
  }

  send(`/xmuse hub ${B}`); await waitResults(1)
  send(`/xmuse join ${inv.code}`); await waitResults(2)
  let st = await j('GET', '/_mock/state')
  const me = st.members.find(m => m.id === 'claude-1')
  log('joined:', me ? `${me.id} online=${me.online}` : 'NOT JOINED')
  if (!me) throw new Error('join failed')

  await sleep(1500)
  log('injecting @ from coord')
  const sent = await j('POST', '/_mock/say', { from: 'coord', to: 'claude-1', text: '@claude-1 请只回复一个词 pong 给 coord（用 xmuse say 工具），不要做别的。' })
  const t0 = Date.now()
  let reply = null
  while (Date.now() - t0 < 90000 && !reply) {
    await sleep(500)
    st = await j('GET', '/_mock/state')
    reply = st.messages.find(m => m.from === 'claude-1' && m.id > sent.id)
  }
  log('hub saw reply:', JSON.stringify(reply))
  ok = !!reply
  // the wake-up prompt as the model saw it (for the report), minus nothing secret
  const woke = events.find(ev => ev.type === 'user' && JSON.stringify(ev).includes('xmuse 房间'))
  log('wake-up row seen in stream:', woke ? 'yes' : 'no')
  send('/xmuse leave'); await waitResults(results + 1, 20000).catch(() => {})
  send('/xmuse hub clear'); await sleep(1500)
} catch (e) {
  console.error('E2E FAILED:', e.message)
} finally {
  if (claude) { claude.stdin.end(); await sleep(1500); claude.kill() }
  hub.kill()
  console.log(ok ? 'E2E OK' : 'E2E FAIL')
  process.exitCode = ok ? 0 : 1
}
