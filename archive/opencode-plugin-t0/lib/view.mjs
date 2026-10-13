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

// 成员行：`标记 名字 角色 · 状态 · 职责/我`。主控标 ★，角色 coordinator 显示"负责人"（主控本人行显示"主控"）。
export function roleText(role, isHost) {
  if (isHost) return "主控"
  if (!role) return "成员"
  return role === "coordinator" ? "负责人" : role
}

export function statusText(m) {
  if (!m.online) return "离线"
  switch (m.status) {
    case "running": return "运行中"
    case "paused": return "暂停"
    case "queued": return "排队中"
    default: return "在线"
  }
}

export function memberRow(m, meId, hostId) {
  const isMe = m.id === meId
  const isHost = m.id === hostId
  const mark = isHost ? "★" : " "
  const tail = [m.description, isMe ? "我" : ""].filter(Boolean).join(" · ")
  const wakes = m.wakes_hour > 0 ? ` · 本小时唤醒 ${m.wakes_hour} 次` : ""
  const unread = m.unread > 0 ? ` · ${m.unread}未读` : ""
  return `${mark} ${m.id} ${roleText(m.role, isHost)} · ${statusText(m)}${wakes}${unread}${tail ? ` · ${tail}` : ""}`
}

// 线程短名：私信用 dm
export function threadShort(thread) {
  return String(thread || "").startsWith("dm:") ? "dm" : String(thread || "")
}

function fromText(m) {
  if (m.kind === "system") return "系统"
  if (m.from === "human") return "用户"
  return m.from
}

function toText(m) {
  const recips = (m.to && m.to.length ? m.to : m.mentions) || []
  return recips.length ? recips.join("、") : "全体"
}

// done 标签：[完成·已核实]、[阻塞·hub改判]、[未核实]、[进展]
export function doneTag(m) {
  if (m.kind !== "done") return ""
  const base = { completed: "完成", blocked: "阻塞", needs_alignment: "需对齐", progress: "进展" }[m.outcome]
  const parts = []
  if (base) parts.push(base + (m.outcome_by === "hub" ? "·hub改判" : ""))
  if (m.evidence_status === "verified") parts.push("已核实")
  else if (m.evidence_status === "unverified") parts.push("未核实")
  return parts.length ? `[${parts.join("·")}]` : ""
}

// 消息行：`线程 发送者→接收者 [标签] 正文前40字`，单行
export function msgRow(m) {
  const tag = doneTag(m)
  const shared = m.shared_from ? `[分享自${m.shared_from.member || "?"}]` : ""
  const routed = m.routed_to && m.routed_to.length ? `[已路由${m.routed_to.join("、")}]` : ""
  const text = String(m.text || "").split("\n")[0].slice(0, 40)
  return [threadShort(m.thread), `${fromText(m)}→${toText(m)}`, tag, shared, routed, text].filter(Boolean).join(" ")
}

// 群一行：`#room 4名成员 + 你 · #trio 🔒3名成员 + 你`（human 不计入，我在内则缀 + 你）
export function formatGroups(threads, meId) {
  if (!threads || !threads.length) return ""
  return threads.map((t) => {
    const ms = Array.isArray(t.members) ? t.members : []
    const n = ms.filter((m) => m !== "human" && m !== meId).length
    const you = ms.includes(meId) ? " + 你" : ""
    return `${t.id} ${t.private ? "🔒" : ""}${n}名成员${you}`
  }).join(" · ")
}

// 顶行：`xmuse · t0（我：负责人 lead ★主控）`
export function formatHeader(view) {
  const room = view.room || {}
  const me = (view.members || []).find((m) => m.id === view.me?.id) || {}
  const hostMark = room.host && room.host === view.me?.id ? " ★主控" : ""
  return `xmuse · ${room.name || "?"}（我：${roleText(me.role, false)} ${view.me?.id || "?"}${hostMark}）`
}

// 主控行：只在有人等或有压住时显示
export function formatHostLine(hw, nowSec) {
  if (!hw) return ""
  const waiting = hw.waiting_on || []
  const held = hw.results_held ?? 0
  if (!waiting.length && !held) return ""
  const mins = hw.wake_at === null || hw.wake_at === undefined
    ? "不自动叫醒"
    : `${Math.max(0, Math.round((hw.wake_at - (nowSec !== undefined ? nowSec : Date.now() / 1000)) / 60))} 分钟后自动叫醒`
  return `主控在等：${waiting.map((w) => w.member).join("、") || "—"} · 压住 ${held} 条 · ${mins} · /xmuse-wake`
}

// v0.1 房间列表行：entry 来自登记表 hubs.json，info 是 GET /v1/rooms 结果（连不上为 null）
export function roomEntryLine(i, entry, info) {
  const head = `${i}. ${entry.name || entry.room_id} — ${entry.dir || "?"}`
  if (!info || !info.room) return `${head} (连不上)`
  const ms = info.members || []
  const on = ms.filter((m) => m.online).length
  const cur = info.room.id === entry.room_id ? " ←当前" : ""
  return `${head}（主控${info.room.host || "?"}，${ms.length}成员/${on}在线）${cur}`
}

export function formatRooms(entries, infoMap) {
  if (!entries || !entries.length) return ["本机没有房间（/xmuse-new-room 开一个）"]
  return entries.map((e, i) => roomEntryLine(i + 1, e, infoMap && infoMap[e.url || e.room_id]))
}

// v0.1 分享审批行：显示摘要和私信摘录
export function formatShareApproval(a) {
  const d = a.detail || {}
  const excerpt = d.excerpt ? `: ${String(d.excerpt).slice(0, 80)}` : ""
  return `[${a.id}] ${a.summary || ""}${excerpt}（once/always/reject）`
}

// v0.1 done 消息行（旧的多行版，已被行内标签 doneTag 取代，保留做兼容）
export function formatDone(m) {
  const tag = doneTag(m)
  const L = tag ? [tag] : []
  if (m.shared_from) L.push(`分享自 ${m.shared_from.member || "?"}`)
  if (m.routed_to && m.routed_to.length) {
    L.push(`已路由给 ${m.routed_to.join("、")}`)
  }
  return L
}

// v0.1 主控等待行（旧的三行版，已被单行 formatHostLine 取代，保留做兼容）
export function formatHostWait(hw, nowSec) {
  const line = formatHostLine(hw, nowSec)
  return line ? [line] : []
}

export function msgLine(m) {
  return msgRow(m)
}

// 旧名兼容：无"我/主控"上下文时按普通成员显示
export function memberLine(m) {
  return memberRow(m || {})
}

export function threadLine(t) {
  t = t || {}
  const lock = t.private ? "🔒" : ""
  const n = Array.isArray(t.members) ? ` (${t.members.length}人)` : ""
  const unread = t.unread > 0 ? ` [${t.unread}未读]` : ""
  return `${lock}${t.id}${n}${unread}`
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
  if (!view || !view.room) return ["xmuse：未加入房间", "/xmuse-join 加入", "/xmuse-new-room 开房间"]
  const L = []
  L.push(formatHeader(view))
  const appr = view.approvals || []
  if (appr.length) L.push(`⚠ 待审批 ${appr.length} 条：/xmuse-approve`)
  const members = view.members || []
  if (members.length) {
    L.push("— 成员 —")
    for (const m of members) L.push(memberRow(m, view.me?.id, view.room.host))
  }
  const groups = formatGroups(view.threads || [], view.me?.id)
  if (groups) {
    L.push("— 群 —")
    L.push(groups)
  }
  const tl = (view.timeline || []).slice(-8)
  if (tl.length) {
    L.push("— 消息 —")
    for (const m of tl) L.push(msgRow(m))
  }
  const hw = formatHostLine(view.host_wait)
  if (hw) L.push(hw)
  if ((view.alignment || []).length) {
    L.push("— 对齐 —")
    for (const e of (view.alignment || []).slice(-3))
      L.push(`${e.id} ${e.kind}: ${String(e.text).slice(0, 40)}`)
  }
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
