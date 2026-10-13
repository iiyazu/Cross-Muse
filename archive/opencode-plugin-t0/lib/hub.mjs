// hub HTTP 客户端：按 XMUSE2-VIEW-API v0。fetch 可注入以便测试。
// 令牌只经参数传入，本模块不打印、不持久化。
import { isLoopback } from "./registry.mjs"

export class HubError extends Error {
  constructor(code, message, status) {
    super(`${code}: ${message}`)
    this.code = code
    this.status = status
  }
}

export class HubClient {
  constructor({ baseUrl, memberToken, operatorToken, sessionId, sidebarKey, fetchFn }) {
    this.baseUrl = String(baseUrl || "").replace(/\/$/, "")
    this.memberToken = memberToken || ""
    this.operatorToken = operatorToken || ""
    this.sessionId = sessionId || ""
    this.sidebarKey = isLoopback(this.baseUrl) ? sidebarKey || "" : ""  // 凭据只发给回环地址的 hub
    this.fetch = fetchFn || globalThis.fetch
  }

  headers({ operator, bare } = {}) {
    const h = { "content-type": "application/json" }
    if (!bare) {
      const tok = operator ? this.operatorToken : this.memberToken
      if (tok) h.authorization = "Bearer " + tok
      // 成员令牌请求带会话绑定头；操作令牌按约定不需要但带上无害（mock-hub 忽略）
      if (!operator && this.sessionId) h["x-xmuse-session"] = this.sessionId
    }
    // v0.1 本机入口要凭据头；只在插件进程里持有，绝不打印
    if (this.sidebarKey) h["x-xmuse-sidebar"] = this.sidebarKey
    return h
  }

  async req(method, path, body, opts) {
    const r = await this.fetch(this.baseUrl + path, {
      method,
      headers: this.headers(opts),
      body: body === undefined ? undefined : JSON.stringify(body),
    })
    if (r.status === 204) return { timeout: true }
    const text = await r.text()
    let data = null
    try {
      data = text ? JSON.parse(text) : null
    } catch {
      throw new HubError("bad_json", "hub 返回了非 JSON", r.status)
    }
    if (r.status < 200 || r.status >= 300) {
      throw new HubError(data?.error || "http_error", data?.message || text, r.status)
    }
    return data
  }

  view(since = 0, wait = 25) {
    const w = Math.min(30, Number(wait ?? 25))
    // 读视图：成员令牌优先（需要会话头），无成员令牌时用操作令牌
    const useOp = !this.memberToken && !!this.operatorToken
    return this.req("GET", `/v1/view?since=${Number(since)}&wait=${w}`, undefined, {
      operator: useOp,
    })
  }

  timeline(before, limit = 50) {
    const useOp = !this.memberToken && !!this.operatorToken
    return this.req("GET", `/v1/timeline?before=${Number(before)}&limit=${Number(limit)}`, undefined, {
      operator: useOp,
    })
  }

  act(body, { operator } = {}) {
    return this.req("POST", "/v1/act", body, { operator })
  }

  say(to, text, mentions) {
    // 成员口吻用成员令牌；侧栏按钮/命令代表用户，用操作令牌（from=human）
    const operator = !!this.operatorToken
    return this.act({ act: "say", to, text, mentions }, { operator })
  }

  ack(ids) {
    return this.act({ act: "ack", ids }, {})
  }

  approve(id, decision) {
    return this.act({ act: "approve", id, decision }, { operator: true })
  }

  invite(vendor, role, description, name) {
    return this.act({ act: "invite", vendor, role, description, name }, { operator: true })
  }

  openRoom({ dir, name, vendor, sessionId, memberId, description }) {
    return this.req("POST", "/v1/rooms", {
      dir,
      name,
      vendor: vendor || "opencode",
      session_id: sessionId,
      member_id: memberId,
      description,
    })
  }

  // v0.1 本机入口：GET /v1/rooms 只带凭据头（成员令牌带了反而 403）
  async roomsInfo() {
    const r = await this.fetch(this.baseUrl + "/v1/rooms", {
      headers: {
        ...(this.sidebarKey ? { "x-xmuse-sidebar": this.sidebarKey } : {}),
      },
    })
    const text = await r.text()
    let data = null
    try {
      data = text ? JSON.parse(text) : null
    } catch {
      throw new HubError("bad_json", "hub 返回了非 JSON", r.status)
    }
    if (r.status < 200 || r.status >= 300) {
      throw new HubError(data?.error || "http_error", data?.message || text, r.status)
    }
    return data
  }

  // v0.1 本机加入：不带 code，凭据头认证；dir/room_id 至少给一个。
  // 不带成员令牌（带了会 403 member_forbidden）。
  joinLocal({ dir, roomId, vendor, sessionId, name, role, description, clientInfo }) {
    const body = { vendor: vendor || "opencode", session_id: sessionId }
    if (dir !== undefined) body.dir = dir
    if (roomId !== undefined) body.room_id = roomId
    if (name) body.name = name
    if (role) body.role = role
    if (description) body.description = description
    if (clientInfo) body.client_info = clientInfo
    return this.req("POST", "/v1/join", body, { bare: true })
  }

  // v0.1 新增 act（都要操作令牌）
  memberAdd({ vendor, model, role, description, name }) {
    const body = { act: "member_add", vendor }
    if (model) body.model = model
    if (role) body.role = role
    if (description) body.description = description
    if (name) body.name = name
    return this.act(body, { operator: true })
  }

  memberEdit(member, { role, description, model }) {
    const body = { act: "member_edit", member }
    if (role !== undefined) body.role = role
    if (description !== undefined) body.description = description
    if (model !== undefined) body.model = model
    return this.act(body, { operator: true })
  }

  transferHost(member) {
    return this.act({ act: "transfer_host", member }, { operator: true })
  }

  pauseMember(member) {
    return this.act({ act: "pause", member }, { operator: true })
  }

  resumeMember(member) {
    return this.act({ act: "resume", member }, { operator: true })
  }

  removeMember(member) {
    return this.act({ act: "remove", member }, { operator: true })
  }

  threadNew({ id, members, title }) {
    const body = { act: "thread_new", id, members }
    if (title) body.title = title
    return this.act(body, { operator: true })
  }

  threadAdd(thread, member) {
    return this.act({ act: "thread_add", thread, member }, { operator: true })
  }

  threadRemove(thread, member) {
    return this.act({ act: "thread_remove", thread, member }, { operator: true })
  }

  shareMark(messageId, to) {
    const body = { act: "share_mark", message_id: messageId }
    if (to) body.to = to
    return this.act(body, { operator: true })
  }

  wakeHost() {
    return this.act({ act: "wake_host" }, { operator: true })
  }

  join(code, vendor, sessionId, clientInfo) {
    return this.req("POST", "/v1/join", {
      code,
      vendor: vendor || "opencode",
      session_id: sessionId,
      client_info: clientInfo || {},
    })
  }

  rebind(sessionId) {
    return this.req("POST", "/v1/rebind", { session_id: sessionId })
  }

  leave() {
    return this.req("POST", "/v1/leave", {})
  }
}

export function hubUrlFromStateDir(stateDir, portFallback) {
  return `http://127.0.0.1:${Number(portFallback || 43117)}`
}
