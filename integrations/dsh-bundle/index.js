// xmuse 2 smoke-test Host plugin for dsh (DeepSeek Harness).
//
// What it exercises (nothing else):
//   /xmuse ping | bind <agent> | status   slash command
//   xmuse_whoami                          per-session model tool -> hub POST /v1/tools/xmuse_whoami
//   ping delivers a follow-up user message via schedule's path:
//     sessionController.resolveAgent -> agent.followup(createUserMessage) -> sessions.flush
//
// Every callback is wrapped in try/catch: an unhandled rejection in a Host plugin can take
// the whole app down.
import { readFile, writeFile } from 'node:fs/promises'
import http from 'node:http'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { CommandDefinitionId } from '@deepseek-ai/dsh-commands/brand'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { defineTool } from '@deepseek-ai/dsh-tools'

export const name = 'xmuse'
// Only commands/tools are hard requirements for activation; the rest is self-checked at
// runtime so the plugin still loads (and reports) when a service is missing.
export const inject = ['commands']

const DEFAULT_STATE = String.raw`\\wsl.localhost\Ubuntu-24.04\home\user\.local\state\xmuse\xmuse-desk-c9ddc1e5`
const HERE = (() => {
  try { return path.dirname(fileURLToPath(import.meta.url)) } catch { return '.' }
})()
const HTTP_TIMEOUT_MS = 8000

const errText = (e) => (e && e.message) || String(e)

/** POST /v1/tools/<tool> on the hub. Uses node:http directly (no global-proxy interference). */
function hubCall(port, token, tool, args) {
  return new Promise((resolve, reject) => {
    const payload = Buffer.from(JSON.stringify({ args: args ?? {} }))
    const req = http.request({
      host: '127.0.0.1', port, path: `/v1/tools/${tool}`, method: 'POST',
      headers: {
        authorization: `Bearer ${token}`,
        'content-type': 'application/json',
        'content-length': payload.length,
      },
      timeout: HTTP_TIMEOUT_MS,
    }, (res) => {
      const chunks = []
      res.on('data', (c) => chunks.push(c))
      res.on('error', reject)
      res.on('end', () => {
        try {
          resolve({ status: res.statusCode, body: JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}') })
        } catch (e) { reject(e) }
      })
    })
    req.on('timeout', () => req.destroy(new Error(`hub request timed out after ${HTTP_TIMEOUT_MS}ms`)))
    req.on('error', reject)
    req.end(payload)
  })
}

export function apply(ctx, config) {
  const cfg = (config && typeof config === 'object') ? config : {}
  const stateDir = typeof cfg.state === 'string' && cfg.state ? cfg.state : DEFAULT_STATE
  const bindingsFile = typeof cfg.bindingsFile === 'string' && cfg.bindingsFile
    ? cfg.bindingsFile : path.join(HERE, 'bindings.json')
  const log = (level, msg) => {
    try { (ctx.logger?.[level] ?? ctx.logger?.info)?.call(ctx.logger, `xmuse: ${msg}`) } catch { /* never throw */ }
  }

  /** @type {Map<string,string>} sessionId -> xmuse agent id */
  const bindings = new Map()
  const selfCheck = { services: {}, hubState: 'unchecked', persistedBindings: 'unchecked' }

  const persist = async () => {
    try {
      await writeFile(bindingsFile, JSON.stringify(Object.fromEntries(bindings), null, 2))
      selfCheck.persistedBindings = 'ok'
    } catch (e) {
      selfCheck.persistedBindings = `write failed: ${errText(e)}`
      log('warn', `could not persist bindings: ${errText(e)}`)
    }
  }
  const restore = async () => {
    try {
      const data = JSON.parse(await readFile(bindingsFile, 'utf8'))
      for (const [k, v] of Object.entries(data)) if (typeof v === 'string') bindings.set(k, v)
      selfCheck.persistedBindings = `loaded ${bindings.size}`
    } catch (e) {
      selfCheck.persistedBindings = e && e.code === 'ENOENT' ? 'none yet' : `read failed: ${errText(e)}`
    }
  }

  const readHub = async () => {
    const hub = JSON.parse(await readFile(path.join(stateDir, 'hub.json'), 'utf8'))
    if (!hub || !Number.isInteger(hub.port)) throw new Error('hub.json has no integer port')
    return hub
  }
  const checkHubState = async () => {
    try {
      const hub = await readHub()
      selfCheck.hubState = `ok (port ${hub.port})`
    } catch (e) {
      selfCheck.hubState = `unreadable: ${errText(e)}`
    }
  }

  const runSelfCheck = async () => {
    try {
      for (const svc of ['sessionController', 'sessions', 'commands', 'agents', 'tools']) {
        selfCheck.services[svc] = ctx[svc] !== undefined && ctx[svc] !== null
      }
      selfCheck.services['sessionController.resolveAgent'] = typeof ctx.sessionController?.resolveAgent === 'function'
      selfCheck.services['sessions.flush'] = typeof ctx.sessions?.flush === 'function'
      await checkHubState()
      await restore()
      log('info', `self-check ${JSON.stringify(selfCheck)} stateDir=${stateDir}`)
    } catch (e) {
      log('warn', `self-check failed: ${errText(e)}`)
    }
  }

  const statusText = () => {
    const lines = ['xmuse smoke bundle 0.0.1', `state dir: ${stateDir}`, 'self-check:']
    for (const [k, v] of Object.entries(selfCheck.services)) lines.push(`  ${k}: ${v ? 'yes' : 'NO'}`)
    lines.push(`  hub state: ${selfCheck.hubState}`, `  bindings file: ${selfCheck.persistedBindings}`)
    lines.push(`bindings (${bindings.size}):`)
    for (const [s, a] of bindings) lines.push(`  ${s} -> ${a}`)
    if (bindings.size === 0) lines.push('  (none)')
    return lines.join('\n')
  }

  // ---- ping: schedule's delivery path ----
  const ping = async (sessionId) => {
    const sc = ctx.sessionController
    if (typeof sc?.resolveAgent !== 'function') throw new Error('ctx.sessionController.resolveAgent is not available')
    const resolved = await sc.resolveAgent(sessionId)
    if (!resolved || 'error' in resolved) throw (resolved && resolved.error) || new Error('resolveAgent returned nothing')
    const text = `[xmuse] smoke delivery ${new Date().toISOString()}: reply "pong" in one line.`
    resolved.agent.followup(createUserMessage({
      content: [{ type: 'text', text }],
      source: { kind: 'xmuse' },
    }))
    if (typeof ctx.sessions?.flush !== 'function') throw new Error('ctx.sessions.flush is not available')
    if (!await ctx.sessions.flush(resolved.agent.session)) throw new Error('session persistence did not acknowledge the message')
    return text
  }

  const handler = async (invocation) => {
    try {
      const sessionId = invocation?.agent?.id
      const raw = String(invocation?.rawInput ?? '').trim()
      const [sub, ...rest] = raw.split(/\s+/).filter(Boolean)
      switch (sub) {
        case 'ping': {
          const text = await ping(sessionId)
          return { kind: 'success', text: `ping queued as a follow-up in session ${sessionId} (source.kind=xmuse):\n${text}` }
        }
        case 'bind': {
          const agentId = rest[0]
          if (!agentId) return { kind: 'error', text: 'Usage: /xmuse bind <agent-id>' }
          bindings.set(sessionId, agentId)
          await persist()
          return { kind: 'success', text: `session ${sessionId} bound to xmuse agent "${agentId}" (persist: ${selfCheck.persistedBindings})` }
        }
        case 'status':
          await checkHubState()
          return { kind: 'success', text: statusText() }
        default:
          return { kind: 'error', text: 'Usage: /xmuse ping | bind <agent-id> | status' }
      }
    } catch (e) {
      log('warn', `/xmuse failed: ${errText(e)}`)
      return { kind: 'error', text: `xmuse: ${errText(e)}` }
    }
  }

  // ---- xmuse_whoami tool (binding is looked up at call time) ----
  const whoamiTool = (agent) => defineTool({
    name: 'xmuse_whoami',
    description: 'Ask the xmuse hub which xmuse agent this session is (smoke test). Requires /xmuse bind <agent> first.',
    parameters: {},
    output: { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: value }] },
    async execute() {
      try {
        const agentId = bindings.get(agent.id)
        if (!agentId) return 'This session is not bound to an xmuse agent. Ask the user to run `/xmuse bind <agent>`.'
        const hub = await readHub()
        const token = (await readFile(path.join(stateDir, 'tokens', agentId), 'utf8')).trim()
        const res = await hubCall(hub.port, token, 'xmuse_whoami', {})
        if (res.body && res.body.error) return `hub error ${res.body.error.code}: ${res.body.error.message}`
        if (res.status !== 200) return `hub HTTP ${res.status}: ${JSON.stringify(res.body)}`
        return JSON.stringify(res.body.result)
      } catch (e) {
        log('warn', `xmuse_whoami failed: ${errText(e)}`)
        return `xmuse_whoami failed: ${errText(e)}`
      }
    },
  })

  // ---- wiring ----
  ctx.effect(() => {
    try {
      return ctx.commands.register({
        definitionId: CommandDefinitionId('xmuse-dsh-bundle'),
        name: 'xmuse',
        description: 'xmuse smoke test: ping | bind <agent-id> | status',
        input: { hint: 'ping | bind <agent-id> | status' },
        recordInput: false,
        handler,
      })
    } catch (e) {
      log('warn', `command registration failed: ${errText(e)}`)
      return () => {}
    }
  }, 'xmuse.command')

  const attached = new Map()
  const attach = (agent) => {
    try {
      if (!agent || attached.has(agent)) return
      attached.set(agent, ctx.effect(() => agent.ctx.effect(() => agent.ctx.tools.register(whoamiTool(agent)), 'xmuse.tools'), 'xmuse.agent'))
    } catch (e) {
      log('warn', `tool registration failed for ${agent?.id}: ${errText(e)}`)
    }
  }
  const detach = (agent) => {
    try {
      const off = attached.get(agent)
      attached.delete(agent)
      if (off) off()
    } catch (e) { log('warn', `detach failed: ${errText(e)}`) }
  }
  ctx.on('agent/created', ({ agent }) => { attach(agent) })
  ctx.on('agent/disposed', ({ agent }) => { detach(agent) })
  try {
    for (const agent of ctx.agents?.roots?.() ?? []) attach(agent)
  } catch (e) { log('warn', `agent backfill failed: ${errText(e)}`) }

  runSelfCheck().catch((e) => log('warn', `self-check crashed: ${errText(e)}`))
}
