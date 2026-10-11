// 纯函数：解析 /v1/view、时间线去重、@ 检测、侧栏文本组装。
// 无依赖、无网络，可单元测试。约定见 docs/design/XMUSE2-VIEW-API.zh.md v0。

export function parseSlash(input) {
  const parts = String(input || "").trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return { cmd: "status", args: [] }
  return { cmd: parts[0].toLowerCase(), args: parts.slice(1) }
}

export function dedupeTimeline(existing, incoming) {
  const seen = new Set((existing || []).map((m) => m.id))
  const out = [...(existing || [])]
  for (const m of incoming || []) {
    if (!seen.has(m.id)) {
      seen.add(m.id)
      out.push(m)
    }
  }
  out.sort((a, b) => a.id - b.id)
  return out
}

// 新 @：for_me 且 id 大于上次见过的
export function newMentions(items, lastSeenId) {
  const since = Number(lastSeenId || 0)
  return (items || []).filter((m) => m.for_me && m.id > since)
}

export function groupByThread(timeline) {
  const map = new Map()
  for (const m of timeline || []) {
    if (!map.has(m.thread)) map.set(m.thread, [])
    map.get(m.thread).push(m)
  }
  return map
}

export function memberLine(m) {
  const dot = !m.online ? "○" : m.status === "running" ? "●" : m.status === "paused" ? "⏸" : "·"
  const unread = m.unread > 0 ? ` (${m.unread}未读)` : ""
  const desc = m.description ? ` - ${m.description}` : ""
  return `${dot} ${m.id} [${m.role}]${unread}${desc}`
}

export function msgLine(m) {
  const who = m.from === "human" ? `用户(经${m.via || "侧栏"})` : m.from
  const at = fmtTime(m.at)
  const mark = m.for_me ? " @我" : ""
  const head = `#${m.id} [${m.thread}] ${who}${mark} ${at}`
  const body = String(m.text || "").split("\n").slice(0, 3).join("\n")
  return `${head}\n  ${body}`
}

export function fmtTime(at) {
  try {
    const d = new Date(Number(at) * 1000)
    const p = (n) => String(n).padStart(2, "0")
    return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
  } catch {
    return ""
  }
}

// 侧栏文本摘要（TUI JSX 里逐行渲染；测试断言用它）
export function formatSidebar(view) {
  if (!view || !view.room) return ["xmuse: 未加入房间（/xmuse room new <名> 或 /xmuse join <码>）"]
  const L = []
  L.push(`房间 ${view.room.name} (${view.room.id}) v${view.version}`)
  L.push(`我: ${view.me?.kind}/${view.me?.id}`)
  L.push("— 成员 —")
  for (const m of view.members || []) L.push(memberLine(m))
  L.push("— 时间线(最新10) —")
  const tl = (view.timeline || []).slice(-10)
  for (const m of tl) L.push(msgLine(m))
  if ((view.approvals || []).length) {
    L.push(`— 审批(${view.approvals.length}) —`)
    for (const a of view.approvals) {
      const what = a.summary || a.text || a.id
      const who = a.member ? `${a.member}: ` : ""
      L.push(`[${a.id}] ${who}${what} (${a.kind || "?"}/${a.risk || "?"})`)
    }
  }
  if ((view.alignment || []).length) {
    L.push("— 对齐 —")
    for (const e of (view.alignment || []).slice(-5))
      L.push(`${e.id} ${e.kind}/${e.scope} ${e.author}: ${String(e.text).slice(0, 60)}`)
  }
  if (view.timeline_cursor?.has_more) L.push("(更早消息：/xmuse more)")
  return L
}

export function buildSayArgs(args) {
  // /xmuse say <to> <text...>  或  /xmuse <to> <text> 速记（to 含 # 或 dm: 或为成员 id）
  if (args[0] === "say") args = args.slice(1)
  const to = args[0]
  const text = args.slice(1).join(" ")
  if (!to || !text) return null
  return { to, text }
}
