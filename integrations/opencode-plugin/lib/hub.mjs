// hub HTTP 客户端：按 XMUSE2-VIEW-API v0。fetch 可注入以便测试。
// 令牌只经参数传入，本模块不打印、不持久化。

export class HubError extends Error {
  constructor(code, message, status) {
    super(`${code}: ${message}`)
    this.code = code
    this.status = status
  }
}

export class HubClient {
  constructor({ baseUrl, memberToken, operatorToken, sessionId, fetchFn }) {
    this.baseUrl = String(baseUrl || "").replace(/\/$/, "")
    this.memberToken = memberToken || ""
    this.operatorToken = operatorToken || ""
    this.sessionId = sessionId || ""
    this.fetch = fetchFn || globalThis.fetch
  }

  headers({ operator } = {}) {
    const tok = operator ? this.operatorToken : this.memberToken
    const h = { "content-type": "application/json" }
    if (tok) h.authorization = "Bearer " + tok
    // 成员令牌请求带会话绑定头；操作令牌按约定不需要但带上无害（mock-hub 忽略）
    if (!operator && this.sessionId) h["x-xmuse-session"] = this.sessionId
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
