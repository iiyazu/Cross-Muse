// xmuse 2 relay plugin for dsh (DeepSeek Harness), v0.1.
//
//   /xmuse bind <agent> | unbind | status | ping     slash command
//   xmuse_* (all 7 hub tools)                        per-session model tools -> hub POST /v1/tools/<name>
//   relay loop (one per bound agent)                 long-polls hub POST /v1/relay/poll and delivers the rendered
//                                                    text into the bound session as a follow-up user message
//                                                    (resolveAgent -> followup -> sessions.flush), then reports
//                                                    POST /v1/relay/delivered.
//
// Every callback is wrapped in try/catch: an unhandled rejection in a Host plugin can take the whole app down.
import { readFile, writeFile } from 'node:fs/promises'
import { readFileSync } from 'node:fs'
import http from 'node:http'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { CommandDefinitionId } from '@deepseek-ai/dsh-commands/brand'
import { createUserMessage } from '@deepseek-ai/dsh-llm'
import { defineTool } from '@deepseek-ai/dsh-tools'
import { SIDEBAR_PREFIX, createSidebar, createTokenStore } from './sidebar-host.js'

export const name = 'xmuse'
export const VERSION = '0.2.0'
// Cordis refuses ctx.<service> access for services not declared here. Same set dsh-schedule declares,
// plus webServer for the sidebar drawer routes (registered via ctx.inject, see D0 probe).
export const inject = ['commands', 'agents', 'sessions', 'tools', 'sessionController', 'webServer']

// No built-in default: the state dir is per machine and per workspace. `xmuse doctor` prints the value for config.state.
const NO_STATE = 'config.state is not set: put the hub state dir there as a \\\\wsl.localhost\\<distro>\\... path (`xmuse doctor` prints it)'
const HERE = (() => {
  try { return path.dirname(fileURLToPath(import.meta.url)) } catch { return '.' }
})()
const HTTP_TIMEOUT_MS = 8000
const POLL_WAIT_S = 25
const BACKOFF_MIN_MS = 1000
const BACKOFF_MAX_MS = 30000

const errText = (e) => (e && e.message) || String(e)

/** POST <urlPath> on the hub with a JSON body (+ x-xmuse-session when sessionId is given). node:http directly
 * (no global-proxy interference). */
export function hubCall(port, token, urlPath, body, { timeoutMs = HTTP_TIMEOUT_MS, onReq, sessionId } = {}) {
  return new Promise((resolve, reject) => {
    const payload = Buffer.from(JSON.stringify(body ?? {}))
    const req = http.request({
      host: '127.0.0.1', port, path: urlPath, method: 'POST',
      headers: {
        authorization: `Bearer ${token}`,
        'content-type': 'application/json',
        'content-length': payload.length,
        // The hub checks it against the session this agent is bound to (identity enforcement).
        ...(sessionId ? { 'x-xmuse-session': sessionId } : {}),
      },
      timeout: timeoutMs,
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
    req.on('timeout', () => req.destroy(new Error(`hub request timed out after ${timeoutMs}ms`)))
    req.on('error', reject)
    if (onReq) onReq(req)
    req.end(payload)
  })
}

/**
 * Hub tool schema (JSON Schema, tools.py TOOLS) -> dsh author DSL for defineTool `parameters`:
 * per-property nodes, `required: true` on the property, objects need an explicit additionalProperties boolean.
 */
export function toDsl(schema, required = false) {
  const node = {}
  if (schema.description) node.description = schema.description
  if (required) node.required = true
  switch (schema.type) {
    case 'object': {
      node.type = 'object'
      node.additionalProperties = schema.additionalProperties !== false
      if (schema.properties) node.properties = propertyMap(schema)
      break
    }
    case 'array':
      node.type = 'array'
      if (schema.items) node.items = toDsl(schema.items)
      break
    default:
      node.type = schema.type
      if (schema.enum) node.enum = [...schema.enum]
  }
  return node
}
export function propertyMap(schema) {
  const req = new Set(schema.required ?? [])
  return Object.fromEntries(Object.entries(schema.properties ?? {}).map(([k, v]) => [k, toDsl(v, req.has(k))]))
}

const COORDINATOR_ONLY = new Set(['xmuse_approve'])

const loadToolSpecs = (stateDir, log) => {
  const read = (p) => {
    const specs = JSON.parse(readFileSync(p, 'utf8'))
    if (!Array.isArray(specs) || !specs.length || !specs.every((t) => t && t.name && t.inputSchema)) throw new Error('bad tools.json')
    return specs
  }
  try {
    if (!stateDir) throw new Error(NO_STATE)
    return { specs: read(path.join(stateDir, 'tools.json')), source: 'hub state tools.json' }
  } catch (e) {
    log('warn', `hub tools.json unusable (${errText(e)}); using the bundled copy`)
  }
  return { specs: read(path.join(HERE, 'tools.json')), source: 'bundled tools.json' }
}

export function apply(ctx, config) {
  const cfg = (config && typeof config === 'object') ? config : {}
  const stateDir = typeof cfg.state === 'string' && cfg.state ? cfg.state : (process.env.XMUSE_STATE_WIN || '')
  const bindingsFile = typeof cfg.bindingsFile === 'string' && cfg.bindingsFile
    ? cfg.bindingsFile : path.join(HERE, 'bindings.json')
  const sidebarFile = typeof cfg.sidebarFile === 'string' && cfg.sidebarFile
    ? cfg.sidebarFile : path.join(HERE, 'sidebar.json')
  const roomDir = typeof cfg.roomDir === 'string' && cfg.roomDir ? cfg.roomDir : process.cwd()
  const pollWaitS = Number.isFinite(cfg.pollWaitS) ? cfg.pollWaitS : POLL_WAIT_S
  const backoffMin = Number.isFinite(cfg.backoffMinMs) ? cfg.backoffMinMs : BACKOFF_MIN_MS
  const backoffMax = Number.isFinite(cfg.backoffMaxMs) ? cfg.backoffMaxMs : BACKOFF_MAX_MS
  const log = (level, msg) => {
    try { (ctx.logger?.[level] ?? ctx.logger?.info)?.call(ctx.logger, `xmuse: ${msg}`) } catch { /* never throw */ }
  }

  /** @type {Map<string,string>} sessionId -> xmuse agent id (one session per agent: last binding wins) */
  const bindings = new Map()
  /** @type {Map<string,number>} agent id -> last delivery cursor acknowledged by the hub */
  const cursors = new Map()
  /** @type {Map<string,object>} agent id -> relay loop entry */
  const relays = new Map()
  const selfCheck = { services: {}, hubState: 'unchecked', persistedBindings: 'unchecked', tools: 'unchecked', sidebar: 'unchecked' }
  let disposed = false

  // ---- sidebar drawer (v0 view API): token store + host routes, tokens never reach the browser ----
  const sidebarStore = createTokenStore(sidebarFile)
  const sidebar = createSidebar({
    readHub: () => readHub(), // readHub 在下面定义：调用时才求值（TDZ 前不能直写）
    store: sidebarStore,
    clientFile: path.join(HERE, 'client.js'),
    log,
    getService: (n) => { try { return ctx.get(n) } catch { return undefined } },
  })

  // ---- persistence (bundle dir, JSON) ----
  let writing = Promise.resolve()
  const persist = () => {
    const run = async () => {
      try {
        const data = { version: 1, bindings: Object.fromEntries(bindings), cursors: Object.fromEntries(cursors) }
        await writeFile(bindingsFile, JSON.stringify(data, null, 2))
        selfCheck.persistedBindings = 'ok'
      } catch (e) {
        selfCheck.persistedBindings = `write failed: ${errText(e)}`
        log('warn', `could not persist bindings: ${errText(e)}`)
      }
    }
    writing = writing.then(run, run)
    return writing
  }
  const restore = async () => {
    try {
      const data = JSON.parse(await readFile(bindingsFile, 'utf8'))
      const b = data && typeof data.bindings === 'object' && data.bindings ? data.bindings : data // 0.0.x: flat map
      const seenAgents = new Set()
      for (const [k, v] of Object.entries(b ?? {})) {
        if (typeof v === 'string' && !seenAgents.has(v)) { bindings.set(k, v); seenAgents.add(v) }
      }
      for (const [k, v] of Object.entries(data?.cursors ?? {})) if (Number.isInteger(v)) cursors.set(k, v)
      selfCheck.persistedBindings = `loaded ${bindings.size}`
    } catch (e) {
      selfCheck.persistedBindings = e && e.code === 'ENOENT' ? 'none yet' : `read failed: ${errText(e)}`
    }
  }

  // ---- hub access ----
  const readHub = async () => {
    if (!stateDir) throw new Error(NO_STATE)
    const hub = JSON.parse(await readFile(path.join(stateDir, 'hub.json'), 'utf8'))
    if (!hub || !Number.isInteger(hub.port)) throw new Error('hub.json has no integer port')
    return hub
  }
  const readToken = async (agentId) => {
    if (!/^[A-Za-z0-9._-]+$/.test(agentId)) throw new Error(`bad agent id "${agentId}"`)
    if (!stateDir) throw new Error(NO_STATE)
    return (await readFile(path.join(stateDir, 'tokens', agentId), 'utf8')).trim()
  }
  const checkHubState = async () => {
    try {
      const hub = await readHub()
      selfCheck.hubState = `ok (port ${hub.port})`
    } catch (e) {
      selfCheck.hubState = `unreadable: ${errText(e)}`
    }
  }

  // ---- delivery into a session: schedule's path ----
  const deliver = async (sessionId, text) => {
    const sc = ctx.sessionController
    if (typeof sc?.resolveAgent !== 'function') throw new Error('ctx.sessionController.resolveAgent is not available')
    const resolved = await sc.resolveAgent(sessionId)
    if (!resolved || 'error' in resolved) throw (resolved && resolved.error) || new Error('resolveAgent returned nothing')
    resolved.agent.followup(createUserMessage({
      content: [{ type: 'text', text }],
      source: { kind: 'xmuse' },
    }))
    if (typeof ctx.sessions?.flush !== 'function') throw new Error('ctx.sessions.flush is not available')
    if (!await ctx.sessions.flush(resolved.agent.session)) throw new Error('session persistence did not acknowledge the message')
  }

  // ---- relay loop: one per agent ----
  const sleep = (entry, ms) => new Promise((resolve) => {
    const t = setTimeout(resolve, ms)
    entry.wake = () => { clearTimeout(t); resolve() }
  })

  const relayLoop = async (entry) => {
    let backoff = backoffMin
    while (!entry.stop && !disposed) {
      try {
        const hub = await readHub()
        const token = await readToken(entry.agentId)
        // The hub's binding is the authority: (re)assert it (a no-op when unchanged), e.g. after a dsh restart.
        if (entry.needBind) {
          await hubBind(hub, token, entry.sessionId)
          entry.needBind = false
        }
        // Delivered into the session but not yet reported: report first, never deliver twice.
        if (entry.pendingAck) {
          await reportDelivered(hub, token, entry)
        }
        entry.state = 'polling'
        const t0 = Date.now()
        const res = await hubCall(hub.port, token, '/v1/relay/poll', { cursor: entry.cursor, wait_s: pollWaitS }, {
          timeoutMs: (pollWaitS + 10) * 1000, onReq: (r) => { entry.req = r }, sessionId: entry.sessionId,
        })
        entry.req = null
        if (entry.stop) break
        checkHub(res)
        const out = res.body.result
        const items = Array.isArray(out?.items) ? out.items : []
        entry.state = 'idle'
        if (!items.length) {
          backoff = backoffMin
          if (Date.now() - t0 < 100) await sleep(entry, 250) // a hub that answers an empty poll at once must not be spun on
          continue
        }
        await deliver(entry.sessionId, String(out.text ?? ''))
        // Only now (flush acknowledged) does the cursor move.
        entry.cursor = Number.isInteger(out.cursor) ? out.cursor : entry.cursor
        entry.lastDeliveryAt = new Date().toISOString()
        entry.pendingAck = items.map((i) => i.delivery_id).filter((i) => Number.isInteger(i))
        await reportDelivered(hub, token, entry)
        entry.lastError = null
        backoff = backoffMin
      } catch (e) {
        entry.req = null
        if (entry.stop || disposed) break
        if (e && e.code === 'not_bound_session') { // another session was bound to this agent: this one lost the role
          log('warn', `relay ${entry.agentId}: ${errText(e)}; dropping the local binding`)
          dropBinding(entry)
          break
        }
        entry.state = 'error'
        entry.lastError = errText(e)
        log('warn', `relay ${entry.agentId}: ${errText(e)} (retry in ${backoff}ms)`)
        await sleep(entry, backoff)
        backoff = Math.min(backoffMax, backoff * 2)
      }
    }
    entry.state = 'stopped'
  }

  /** Throws on a hub error (keeping its code on the Error) or a non-200 reply. */
  const checkHub = (res) => {
    if (res.body?.error) {
      const e = new Error(`hub error ${res.body.error.code}: ${res.body.error.message}`)
      e.code = res.body.error.code
      throw e
    }
    if (res.status !== 200) throw new Error(`hub HTTP ${res.status}`)
  }
  const hubBind = async (hub, token, sessionId) => {
    const res = await hubCall(hub.port, token, '/v1/relay/bind', { session_id: sessionId }, { sessionId })
    checkHub(res)
    return res.body.result
  }

  const reportDelivered = async (hub, token, entry) => {
    const res = await hubCall(hub.port, token, '/v1/relay/delivered',
      { delivery_ids: entry.pendingAck, session_id: entry.sessionId }, { sessionId: entry.sessionId })
    checkHub(res)
    entry.pendingAck = null
    cursors.set(entry.agentId, entry.cursor)
    await persist()
  }

  const stopRelay = (agentId) => {
    const entry = relays.get(agentId)
    if (!entry) return
    relays.delete(agentId)
    entry.stop = true
    try { entry.req?.destroy() } catch { /* ignore */ }
    try { entry.wake?.() } catch { /* ignore */ }
  }
  const startRelay = (agentId, sessionId, needBind = false) => {
    stopRelay(agentId)
    if (disposed) return
    const entry = {
      agentId, sessionId, cursor: cursors.get(agentId) ?? 0, state: 'idle', stop: false,
      lastDeliveryAt: null, lastError: null, pendingAck: null, req: null, wake: null, needBind,
    }
    relays.set(agentId, entry)
    relayLoop(entry).catch((e) => log('warn', `relay ${agentId} crashed: ${errText(e)}`))
  }
  /** The hub bound another session to this agent: forget the local binding (nothing to tell the hub). */
  const dropBinding = (entry) => {
    if (relays.get(entry.agentId) === entry) relays.delete(entry.agentId)
    if (bindings.get(entry.sessionId) === entry.agentId) bindings.delete(entry.sessionId)
    entry.stop = true
    entry.state = 'stopped'
    persist()
  }
  const stopAll = () => {
    disposed = true
    for (const id of [...relays.keys()]) stopRelay(id)
  }

  /** Last binding wins: one session per agent, one agent per session. Returns what was replaced. */
  const bind = (sessionId, agentId) => {
    const replaced = []
    for (const [s, a] of [...bindings]) {
      if (a === agentId && s !== sessionId) { bindings.delete(s); replaced.push(`session ${s} no longer bound to "${a}"`) }
    }
    const old = bindings.get(sessionId)
    if (old && old !== agentId) { stopRelay(old); replaced.push(`session ${sessionId} was bound to "${old}"`) }
    bindings.set(sessionId, agentId)
    startRelay(agentId, sessionId)
    return replaced
  }
  const unbind = (sessionId) => {
    const agentId = bindings.get(sessionId)
    if (!agentId) return null
    bindings.delete(sessionId)
    stopRelay(agentId)
    return agentId
  }

  const runSelfCheck = async () => {
    try {
      for (const svc of ['sessionController', 'sessions', 'commands', 'agents', 'tools', 'webServer']) {
        selfCheck.services[svc] = ctx[svc] !== undefined && ctx[svc] !== null
      }
      selfCheck.services['sessionController.resolveAgent'] = typeof ctx.sessionController?.resolveAgent === 'function'
      selfCheck.services['sessions.flush'] = typeof ctx.sessions?.flush === 'function'
      await checkHubState()
      await restore()
      try {
        await sidebarStore.load()
        const st = sidebar.status()
        selfCheck.sidebar = st.bound ? `bound as "${st.memberId}"` : 'no room (use /xmuse join or room new)'
      } catch (e) {
        selfCheck.sidebar = `store read failed: ${errText(e)}`
      }
      for (const [s, a] of bindings) startRelay(a, s, true)
      log('info', `self-check ${JSON.stringify(selfCheck)} stateDir=${stateDir}`)
    } catch (e) {
      log('warn', `self-check failed: ${errText(e)}`)
    }
  }

  const statusText = () => {
    const lines = [`xmuse relay bundle ${VERSION}`, `state dir: ${stateDir}`, 'self-check:']
    for (const [k, v] of Object.entries(selfCheck.services)) lines.push(`  ${k}: ${v ? 'yes' : 'NO'}`)
    lines.push(`  hub state: ${selfCheck.hubState}`, `  bindings file: ${selfCheck.persistedBindings}`, `  tools: ${selfCheck.tools}`)
    lines.push(`  sidebar: ${selfCheck.sidebar} (routes at ${SIDEBAR_PREFIX}/*)`)
    lines.push(`bindings (${bindings.size}):`)
    for (const [s, a] of bindings) {
      const r = relays.get(a)
      lines.push(`  ${s} -> ${a}`)
      lines.push(r
        ? `    relay: ${r.state}, cursor ${r.cursor}, last delivery ${r.lastDeliveryAt ?? '-'}, last error ${r.lastError ?? '-'}`
        : '    relay: not running')
    }
    if (bindings.size === 0) lines.push('  (none)')
    return lines.join('\n')
  }

  const ping = async (sessionId) => {
    const text = `[xmuse] smoke delivery ${new Date().toISOString()}: reply "pong" in one line.`
    await deliver(sessionId, text)
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
          if (!/^[A-Za-z0-9._-]+$/.test(agentId)) return { kind: 'error', text: `bad agent id "${agentId}"` }
          // The hub is the authority: it must accept the binding (agent exists, is a foreground agent) before
          // anything is recorded locally; its own token is read here, never by the model.
          let hubSays
          try {
            hubSays = await hubBind(await readHub(), await readToken(agentId), sessionId)
          } catch (e) {
            return { kind: 'error', text: `xmuse: the hub did not accept the binding: ${errText(e)}` }
          }
          const replaced = bind(sessionId, agentId)
          if (hubSays?.replaced) replaced.push(`the hub had session ${hubSays.replaced} bound to "${agentId}"`)
          await persist()
          const extra = replaced.length ? `\nreplaced: ${replaced.join('; ')}` : ''
          return { kind: 'success', text: `session ${sessionId} bound to xmuse agent "${agentId}" (hub confirmed); relay started (persist: ${selfCheck.persistedBindings})${extra}` }
        }
        case 'unbind': {
          const agentId = unbind(sessionId)
          if (!agentId) return { kind: 'error', text: `session ${sessionId} is not bound` }
          await persist()
          let hubNote = 'hub binding cleared'
          try {
            const res = await hubCall((await readHub()).port, await readToken(agentId), '/v1/relay/unbind', {}, { sessionId })
            checkHub(res)
          } catch (e) {
            hubNote = `hub NOT told (${errText(e)}); it may still list this session as bound`
          }
          return { kind: 'success', text: `session ${sessionId} unbound from "${agentId}"; relay stopped; ${hubNote} (persist: ${selfCheck.persistedBindings})` }
        }
        case 'status':
          await checkHubState()
          {
            const st = sidebar.status()
            selfCheck.sidebar = st.bound ? `bound as "${st.memberId}"` : 'no room (use /xmuse join or room new)'
          }
          return { kind: 'success', text: statusText() }
        case 'join': {
          // v0 邀请码加入（POST /v1/join）：旧的 bind 保留兼容，见下。
          const code = rest[0]
          if (!code) return { kind: 'error', text: 'Usage: /xmuse join <邀请码>' }
          try {
            const out = await sidebar.joinRoom({ code, sessionId, clientInfo: { client: 'dsh-slash' } })
            return { kind: 'success', text: `joined the room as xmuse member "${out.member_id}" (sidebar tokens stored host-side); 抽屉里现在能看到整个房间` }
          } catch (e) {
            return { kind: 'error', text: `xmuse: join failed: ${errText(e)}` }
          }
        }
        case 'room': {
          if (rest[0] !== 'new' || !rest[1]) return { kind: 'error', text: 'Usage: /xmuse room new <名字> [工作目录]' }
          const roomName = rest[1]
          const dir = rest[2] || roomDir
          try {
            const out = await sidebar.createRoom({ dir, name: roomName, sessionId })
            return { kind: 'success', text: `room "${out.room.name}" created (${out.room.id}), you are the host as "${out.member_id}" (sidebar tokens stored host-side)` }
          } catch (e) {
            return { kind: 'error', text: `xmuse: room new failed: ${errText(e)}` }
          }
        }
        case 'leave': {
          const out = await sidebar.leaveRoom()
          return { kind: 'success', text: out.already ? 'sidebar is not in a room' : `sidebar left the room; ${out.note}` }
        }
        default:
          return { kind: 'error', text: 'Usage: /xmuse bind <agent-id> | join <邀请码> | room new <名字> [工作目录] | leave | unbind | status | ping' }
      }
    } catch (e) {
      log('warn', `/xmuse failed: ${errText(e)}`)
      return { kind: 'error', text: `xmuse: ${errText(e)}` }
    }
  }

  // ---- model tools: the hub's tools, binding looked up at call time ----
  let toolSpecs = []
  try {
    const loaded = loadToolSpecs(stateDir, log)
    // a dsh session is never the desktop coordinator: the hub would refuse xmuse_approve, so do not offer it
    toolSpecs = loaded.specs.filter((t) => !COORDINATOR_ONLY.has(t.name))
    selfCheck.tools = `${toolSpecs.length} from ${loaded.source}`
  } catch (e) {
    selfCheck.tools = `unavailable: ${errText(e)}`
    log('warn', `no tool specs: ${errText(e)}`)
  }

  const UNBOUND_PREFIX = 'Only for sessions the user bound with `/xmuse bind <agent>`; do not call this tool in an unbound session. '
  const makeTool = (agent, spec) => defineTool({
    name: spec.name,
    description: UNBOUND_PREFIX + spec.description,
    parameters: propertyMap(spec.inputSchema),
    output: { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: value }] },
    async execute(args) {
      try {
        const agentId = bindings.get(agent.id)
        if (!agentId) return 'This session is not bound to an xmuse agent. Ask the user to run `/xmuse bind <agent>` (do not retry this tool until they have).'
        const hub = await readHub()
        const token = await readToken(agentId)
        const res = await hubCall(hub.port, token, `/v1/tools/${spec.name}`, { args: args ?? {} }, { sessionId: agent.id })
        if (res.body && res.body.error) return `hub error ${res.body.error.code}: ${res.body.error.message}`
        if (res.status !== 200) return `hub HTTP ${res.status}: ${JSON.stringify(res.body)}`
        return JSON.stringify(res.body.result)
      } catch (e) {
        log('warn', `${spec.name} failed: ${errText(e)}`)
        return `${spec.name} failed: ${errText(e)}`
      }
    },
  })

  // ---- wiring ----
  ctx.effect(() => {
    try {
      return ctx.commands.register({
        definitionId: CommandDefinitionId('xmuse-dsh-bundle'),
        name: 'xmuse',
        description: 'xmuse relay: bind <agent-id> | join <邀请码> | room new <名字> [工作目录] | leave | unbind | status | ping',
        input: { hint: 'bind <agent-id> | join <邀请码> | room new <名字> [工作目录] | leave | unbind | status | ping' },
        recordInput: false,
        handler,
      })
    } catch (e) {
      log('warn', `command registration failed: ${errText(e)}`)
      return () => {}
    }
  }, 'xmuse.command')

  // Sidebar drawer routes: host prefix -> loopback hub, tokens stay host-side (D0 probe pattern).
  // inject() waits for the service; a host without a web server simply never registers.
  ctx.effect(() => {
    let off = null
    try {
      const register = (scope) => {
        try {
          off = scope.webServer.register({
            kind: 'prefix', path: SIDEBAR_PREFIX,
            handler: (req, res) => { sidebar.handle(req, res).catch((e) => log('warn', `sidebar route crashed: ${errText(e)}`)) },
          })
        } catch (e) {
          log('warn', `sidebar route registration failed: ${errText(e)}`)
        }
      }
      if (typeof ctx.inject === 'function') ctx.inject(['webServer'], register)
      else if (ctx.webServer) register(ctx)
      else log('warn', 'no webServer service: sidebar drawer routes not registered')
    } catch (e) {
      log('warn', `sidebar route setup failed: ${errText(e)}`)
    }
    return () => { try { off?.() } catch { /* ignore */ } }
  }, 'xmuse.sidebar')

  ctx.effect(() => stopAll, 'xmuse.relay')

  const attached = new Map()
  const attach = (agent) => {
    try {
      if (!agent || attached.has(agent)) return
      attached.set(agent, ctx.effect(() => agent.ctx.effect(() => {
        const offs = toolSpecs.map((spec) => agent.ctx.tools.register(makeTool(agent, spec)))
        return () => { for (const off of offs) { try { off?.() } catch { /* ignore */ } } }
      }, 'xmuse.tools'), 'xmuse.agent'))
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
