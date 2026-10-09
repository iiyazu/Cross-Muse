// xmuse MCP stdio shim: forwards the 7 xmuse tools to the local hub; nothing else.
//
// env: XMUSE_STATE (hub state dir), XMUSE_AGENT (this agent's id), XMUSE_CHANNEL=1 (Claude only).
// - Tool schemas come from <state>/tools.json (written by `xmuse init` from the hub's Python schemas).
// - Hub address is re-read from <state>/hub.json on every call, so a hub restart is transparent.
// - In an interactive Claude Code session (CLAUDE_CODE_ENTRYPOINT=cli) with XMUSE_CHANNEL=1 it
//   declares `claude/channel`, listens on a dynamic loopback port and registers that endpoint with
//   the hub (M0: a fixed port collides between the TUI and headless runs). Only POSTs carrying the
//   nonce it registered are pushed into the session (sender gating).
//
// Run with Node >= 23.6 (native type stripping): `node server.ts`.
import { randomBytes } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { createServer } from 'node:http'
import { join } from 'node:path'
import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js'

const STATE = process.env.XMUSE_STATE ?? ''
const AGENT = process.env.XMUSE_AGENT ?? ''
const CHANNEL = process.env.XMUSE_CHANNEL === '1' && process.env.CLAUDE_CODE_ENTRYPOINT === 'cli'
const SESSION = process.env.CLAUDE_CODE_SESSION_ID ?? null
const TOKEN = readFileSync(join(STATE, 'tokens', AGENT), 'utf8').trim()
const TOOLS = JSON.parse(readFileSync(join(STATE, 'tools.json'), 'utf8'))

async function hub(path: string, body: unknown, attempts = 3): Promise<any> {
  let last: unknown
  for (let i = 0; i < attempts; i++) {
    try {
      const { port } = JSON.parse(readFileSync(join(STATE, 'hub.json'), 'utf8'))
      const r = await fetch(`http://127.0.0.1:${port}${path}`, {
        method: 'POST',
        headers: { authorization: `Bearer ${TOKEN}`, 'content-type': 'application/json' },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(30_000),
      })
      return await r.json()
    } catch (e) {
      last = e
      await new Promise(res => setTimeout(res, 500 * (i + 1)))
    }
  }
  return { error: { code: 'hub_unreachable', message: `xmuse hub not reachable: ${String(last)}` } }
}

const mcp = new Server(
  { name: 'xmuse', version: '0.1.0' },
  {
    capabilities: { tools: {}, experimental: CHANNEL ? { 'claude/channel': {} } : {} },
    instructions:
      'xmuse relays messages between you and peer agents the user assigned to this workspace. ' +
      (CHANNEL ? 'Relayed messages arrive as <channel source="xmuse">. ' : '') +
      'Reply with xmuse_send; end each turn with xmuse_done. See skill xmuse-collab.',
  },
)

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }))

mcp.setRequestHandler(CallToolRequestSchema, async req => {
  // Retries are safe: the hub dedupes a repeated send within one turn.
  const out = await hub(`/v1/tools/${req.params.name}`, { args: req.params.arguments ?? {} })
  const isError = 'error' in out
  const payload = isError ? out.error : out.result
  return { content: [{ type: 'text', text: JSON.stringify(payload) }], isError }
})

await mcp.connect(new StdioServerTransport())
process.stdin.on('close', () => process.exit(0))

if (CHANNEL) {
  const nonce = randomBytes(16).toString('hex')
  const http = createServer((req, res) => {
    if (req.method !== 'POST' || req.url !== '/push' || req.headers['x-xmuse-nonce'] !== nonce) {
      res.writeHead(403).end()
      return
    }
    let raw = ''
    req.on('data', c => { raw += c })
    req.on('end', async () => {
      const { content, meta } = JSON.parse(raw)
      await mcp.notification({ method: 'notifications/claude/channel', params: { content, meta } })
      res.writeHead(200).end('ok\n')
    })
  })
  http.listen(0, '127.0.0.1', async () => {
    const port = (http.address() as { port: number }).port
    const reg = { port, nonce, session_id: SESSION, claude_pid: process.ppid, pid: process.pid }
    // the hub may start after the TUI: keep trying, and re-register when the hub restarts
    let registeredWith = ''
    setInterval(async () => {
      let hubFile = ''
      try { hubFile = readFileSync(join(STATE, 'hub.json'), 'utf8') } catch { return }
      if (hubFile === registeredWith) return
      const out = await hub('/v1/shim/register', reg, 1)
      if (!('error' in out)) registeredWith = hubFile
    }, 2000).unref()
  })
}
