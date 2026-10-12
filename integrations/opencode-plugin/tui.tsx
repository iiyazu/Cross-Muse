/** @jsxImportSource @opentui/solid */
// xmuse 侧栏：OpenCode 2.x TUI 插件。约定 v0（docs/design/XMUSE2-VIEW-API.zh.md）。
// 薄渲染层：只画画、把操作转成 /v1/view、/v1/act、rooms/join 请求。令牌只在 ctx.storage.store + 插件文件存储里。
import { Plugin } from "@opencode/plugin/tui"
import { HubClient } from "./lib/hub.mjs"
import { hubBaseUrl, loadStore, saveStore, clearStore } from "./lib/store.mjs"
import { registryDir, readHubs, readCredential, fetchRoomInfo } from "./lib/registry.mjs"
import {
  parseSlash, buildSayArgs, newMentions, dedupeTimeline,
  formatRooms, formatShareApproval, formatSidebar,
} from "./lib/view.mjs"
import { COMMANDS, compatHelp } from "./lib/commands.mjs"

export default Plugin.define({
  id: "xmuse",
  setup(ctx) {
    const [auth, setAuth] = ctx.storage.store("xmuse-auth", {
      initial: { hubUrl: "", memberId: "", memberToken: "", operatorToken: "", sessionId: "" },
    })
    const [ui, setUi] = ctx.storage.memory("xmuse-view", {
      initial: { view: null, error: "", loading: true, extraOlder: [], rooms: [] },
    })

    // 文件存储兜底（TUI 重启前已持久化过的）
    try {
      const f = loadStore()
      if (!auth.hubUrl && (f.hubUrl || process.env.XMUSE_HUB_URL)) {
        setAuth((d) => {
          d.hubUrl = f.hubUrl || process.env.XMUSE_HUB_URL || ""
          d.memberId = f.memberId || ""
          d.memberToken = f.memberToken || ""
          d.operatorToken = f.operatorToken || ""
        })
      }
    } catch {}

    let stop = false
    let lastSeen = 0
    let sessionId = ""

    // 侧栏凭据只在插件进程里读：绝不显示、不记日志、不进任何文本
    const credDir = () => registryDir(process.env)
    const cred = () => readCredential(credDir())

    const baseUrl = () =>
      auth.hubUrl || process.env.XMUSE_HUB_URL || hubBaseUrl(process.env)
    const client = (hubUrl) =>
      new HubClient({
        baseUrl: hubUrl || baseUrl(),
        memberToken: auth.memberToken,
        operatorToken: auth.operatorToken,
        sessionId: auth.sessionId || sessionId,
        sidebarKey: cred(),
      })

    // 本机房间列表（登记表 + 逐个问在线情况）
    async function loadRooms() {
      const entries = readHubs(credDir())
      const key = cred()
      const infoMap = {}
      await Promise.all(
        entries.map(async (e) => {
          if (!e.url) return
          const info = await fetchRoomInfo(fetch, e.url, key)
          if (info) infoMap[e.url] = info
        }),
      )
      setUi((d) => {
        d.rooms = entries.map((e) => ({ ...e, online: !!infoMap[e.url] }))
      })
      return { entries, infoMap }
    }
    loadRooms()
    const roomsTimer = setInterval(() => !stop && loadRooms(), 30000)

    const persist = () => {
      try {
        saveStore(
          {
            hubUrl: baseUrl(),
            memberId: auth.memberId,
            memberToken: auth.memberToken,
            operatorToken: auth.operatorToken,
          },
          process.env,
        )
      } catch {}
    }

    async function poll() {
      const c = client()
      if (!c.memberToken && !c.operatorToken) {
        setUi((d) => {
          d.loading = false
          d.error = ""
        })
        setTimeout(() => !stop && poll(), 3000)
        return
      }
      let since = ui.view?.version || 0
      try {
        const v = await c.view(since, 25)
        if (stop) return
        if (v && !v.timeout) {
          const fresh = newMentions(v.timeline, lastSeen)
          if (lastSeen && fresh.length) {
            const first = fresh[0]
            try {
              ctx.ui.toast.show({
                title: "xmuse @我",
                message: `${first.from}: ${String(first.text).slice(0, 120)}`,
                variant: "warning",
              })
            } catch {}
          }
          const maxId = (v.timeline || []).reduce((m, x) => Math.max(m, x.id), lastSeen)
          if (maxId) lastSeen = maxId
          setUi((d) => {
            d.view = v
            d.error = ""
            d.loading = false
            d.extraOlder = []
          })
          // 自动 ack？不自动，只记录未读（按约定 unread 由 hub 算）
        }
        setTimeout(() => !stop && poll(), 200)
      } catch (e) {
        if (stop) return
        const code = e?.code || "error"
        // 会话换了 id（如重开 TUI）：尝试 rebind
        if (code === "not_bound_session" && c.memberToken && (auth.sessionId || sessionId)) {
          try {
            await c.rebind(auth.sessionId || sessionId)
            setTimeout(() => !stop && poll(), 500)
            return
          } catch {}
        }
        setUi((d) => {
          d.loading = false
          d.error = String(e?.message || e).slice(0, 200)
        })
        setTimeout(() => !stop && poll(), 5000)
      }
    }
    poll()

    const off = ctx.ui.slot({
      append: "sidebar.content",
      render: (input) => {
        sessionId = input.sessionID
        if (sessionId && !auth.sessionId) setAuth((d) => void (d.sessionId = sessionId))
        const v = ui.view
        if (ui.loading && !v)
          return (
            <box flexDirection="column">
              <text>xmuse: 连接中…</text>
              <text>/xmuse-join 加入</text>
            </box>
          )
        const lines = formatSidebar(v)
        return (
          <box flexDirection="column">
            {ui.error ? <text>错误: {ui.error}</text> : null}
            {lines.map((l) => (
              <text>{l}</text>
            ))}
            {!v
              ? (ui.rooms || []).slice(0, 5).map((r) => (
                  <text>
                    {r.name || r.room_id}（{r.online ? "在线" : "连不上"}）
                  </text>
                ))
              : null}
          </box>
        )
      },
    })

    async function doStatus() {
      const v = ui.view
      const msg = v
        ? `房间 ${v.room?.name} v${v.version}，成员${v.members?.length}，审批${v.approvals?.length}，时间线${v.timeline?.length}`
        : `未加入房间（hub ${baseUrl()}）`
      try {
        ctx.ui.toast.show({ title: "xmuse status", message: msg, variant: "info" })
      } catch {}
      return msg
    }

    // 选人/选群/选审批：选项都带名字·角色·职责，不让手打 id
    function memberOptions() {
      return (ui.view?.members || []).map((m) => ({
        title: `${m.id} · ${m.role || "成员"} · ${m.description || (m.id === ui.view?.me?.id ? "我" : "")}`,
        value: m.id,
      }))
    }

    async function pickMember(title) {
      const opts = memberOptions()
      if (!opts.length) return ""
      try {
        return (await ctx.ui.dialog.select({ title: title || "选成员", options: opts })) || ""
      } catch {
        return ""
      }
    }

    async function pickThread(title, privateOnly) {
      const ts = (ui.view?.threads || []).filter((t) => !privateOnly || t.private)
      if (!ts.length) return ""
      try {
        return (
          (await ctx.ui.dialog.select({
            title: title || "选群",
            options: ts.map((t) => ({
              title: `${t.private ? "🔒" : ""}${t.id}（${(t.members || []).length}人）`,
              value: t.id,
            })),
          })) || ""
        )
      } catch {
        return ""
      }
    }

    async function pickRoom() {
      const { entries } = await loadRooms()
      if (!entries.length) return null
      try {
        const picked = await ctx.ui.dialog.select({
          title: "加入房间",
          options: entries.map((x) => ({ title: `${x.name || x.room_id} — ${x.dir || "?"}`, value: x.room_id })),
        })
        return entries.find((x) => x.room_id === picked) || null
      } catch {
        return null
      }
    }

    async function doRoomNew(name, memberName) {
      let roomName = name
      if (!roomName) {
        try {
          roomName = await ctx.ui.dialog.prompt({ title: "开房间", description: "房间名", placeholder: "xmuse-dev" })
        } catch {}
      }
      if (!roomName) return "已取消"
      let mName = memberName
      if (!mName) {
        try {
          mName = (await ctx.ui.dialog.prompt({
            title: "开房间",
            description: "你的成员名（留空由 hub 起名，默认用厂商名，如 opencode、opencode-2）",
          })) || ""
        } catch {}
      }
      const c = client()
      const sid = auth.sessionId || sessionId || `opencode-${Date.now()}`
      const r = await c.openRoom({
        dir: process.cwd(),
        name: roomName,
        vendor: "opencode",
        sessionId: sid,
        memberId: mName || undefined,
      })
      setAuth((d) => {
        d.hubUrl = baseUrl()
        d.memberId = r.member_id
        d.memberToken = r.member_token
        d.operatorToken = r.operator_token
        d.sessionId = sid
      })
      persist()
      setTimeout(() => !stop && poll(), 200)
      try {
        ctx.ui.toast.show({ title: "xmuse", message: `已开房间 ${roomName}，你是 ${r.member_id}`, variant: "success" })
      } catch {}
      return `room ${roomName} member ${r.member_id}`
    }

    async function doInvite(vendor, role, desc, name) {
      if (!vendor) {
        try {
          vendor = await ctx.ui.dialog.select({
            title: "邀请：选 provider",
            options: ["opencode", "claude", "dsh"].map((x) => ({ title: x, value: x })),
          })
        } catch {}
      }
      if (!vendor) return "已取消"
      if (!role) {
        try {
          role = await ctx.ui.dialog.prompt({ title: "邀请", description: "角色", value: "executor" })
        } catch {}
      }
      if (!desc) {
        try {
          desc = (await ctx.ui.dialog.prompt({ title: "邀请", description: "职责描述", placeholder: "负责…" })) || ""
        } catch {}
      }
      const c = client()
      const r = await c.invite(vendor, role || "executor", desc || "", name)
      const msg = `邀请码 ${r.code}（10分钟, 一次性）：${r.command}`
      try {
        await ctx.ui.dialog.alert({ title: "邀请已创建", message: msg })
      } catch {
        try {
          ctx.ui.toast.show({ title: "xmuse 邀请", message: msg, variant: "success", duration: 15000 })
        } catch {}
      }
      return msg
    }

    async function doJoin(code) {
      if (!code) {
        try {
          code = await ctx.ui.dialog.prompt({ title: "加入房间", description: "邀请码", placeholder: "XXXX-XX" })
        } catch {}
      }
      if (!code) return "已取消"
      const c = client()
      const sid = auth.sessionId || sessionId || `opencode-${Date.now()}`
      const r = await c.join(String(code).trim(), "opencode", sid, {})
      setAuth((d) => {
        d.hubUrl = baseUrl()
        d.memberId = r.member_id
        d.memberToken = r.member_token
        d.operatorToken = r.operator_token
        d.sessionId = sid
      })
      persist()
      setTimeout(() => !stop && poll(), 200)
      try {
        ctx.ui.toast.show({ title: "xmuse", message: `已加入，你是 ${r.member_id}`, variant: "success" })
      } catch {}
      return `joined as ${r.member_id}`
    }

    async function doRooms() {
      const { entries, infoMap } = await loadRooms()
      const lines = formatRooms(entries, infoMap)
      const msg = lines.join("\n").slice(0, 600)
      try {
        ctx.ui.toast.show({ title: "xmuse 本机房间", message: msg, variant: "info", duration: 12000 })
      } catch {}
      return msg
    }

    async function doJoinLocal(sel, role, name) {
      const { entries } = await loadRooms()
      if (!entries.length) return "本机没有房间，先用 /xmuse-new-room 开一个"
      let e = null
      if (sel && /^\d+$/.test(sel)) e = entries[Number(sel) - 1]
      else if (sel) e = entries.find((x) => x.room_id === sel || x.name === sel)
      if (!e) e = await pickRoom()
      if (!e || !e.url) return "已取消或该房间连不上"
      let r = role
      if (!r) {
        try {
          r = (await ctx.ui.dialog.prompt({ title: "加入房间", description: "角色", value: "executor" })) || "executor"
        } catch {}
      }
      let n = name
      if (!n) {
        try {
          n = (await ctx.ui.dialog.prompt({
            title: "加入房间",
            description: "你的成员名（留空由 hub 起名，默认用厂商名，如 opencode、opencode-2）",
          })) || ""
        } catch {}
      }
      const sid = auth.sessionId || sessionId || `opencode-${Date.now()}`
      const c = client(String(e.url))
      const j = await c.joinLocal({ roomId: e.room_id, vendor: "opencode", sessionId: sid, role: r, name: n || undefined })
      setAuth((d) => {
        d.hubUrl = String(e.url)
        d.memberId = j.member_id
        d.memberToken = j.member_token
        d.operatorToken = j.operator_token
        d.sessionId = sid
      })
      persist()
      setTimeout(() => !stop && poll(), 200)
      try {
        ctx.ui.toast.show({ title: "xmuse", message: `已加入 ${e.name || e.room_id}，你是 ${j.member_id}`, variant: "success" })
      } catch {}
      return `joined ${e.name || e.room_id} as ${j.member_id}`
    }

    async function doAdd(vendor, role, desc, model, name) {
      if (!vendor) {
        try {
          vendor = await ctx.ui.dialog.select({
            title: "添加成员：选厂商",
            options: ["opencode", "claude", "dsh"].map((x) => ({ title: x, value: x })),
          })
        } catch {}
      }
      if (!vendor) return "已取消"
      if (!role) {
        try {
          role = (await ctx.ui.dialog.prompt({ title: "添加成员", description: "角色", value: "executor" })) || "executor"
        } catch {}
      }
      if (desc === undefined) {
        try {
          desc = (await ctx.ui.dialog.prompt({ title: "添加成员", description: "职责描述", placeholder: "负责…" })) || ""
        } catch {}
      }
      const finalRole = role || "executor"
      if (!name) {
        try {
          name = (await ctx.ui.dialog.prompt({
            title: "添加成员",
            description: "名字（留空由 hub 起名，默认用厂商名，如 opencode、opencode-2）",
          })) || ""
        } catch {}
      }
      const r = await client().memberAdd({ vendor, model, role: finalRole, description: desc || "", name })
      try {
        ctx.ui.toast.show({ title: "xmuse", message: `已添加成员 ${r.member_id}`, variant: "success" })
      } catch {}
      return `member ${r.member_id} added`
    }

    async function doEdit(member, field, value) {
      let m = member
      if (!m) m = await pickMember("改谁")
      if (!m) return "已取消"
      let role, description
      if (field === "role") role = value
      else if (field === "desc" || field === "description") description = value
      if (role === undefined && description === undefined) {
        try {
          const f = await ctx.ui.dialog.select({
            title: `改 ${m}：改哪项`,
            options: [
              { title: "角色", value: "role" },
              { title: "职责描述", value: "description" },
            ],
          })
          const v = await ctx.ui.dialog.prompt({ title: `改 ${m}`, description: f === "role" ? "新角色" : "新职责描述" })
          if (f === "role") role = v
          else description = v
        } catch {}
        if (role === undefined && description === undefined) return "已取消"
      }
      await client().memberEdit(m, { role, description })
      return `member ${m} updated`
    }

    async function doMemberOp(op, member) {
      let m = member
      if (!m) m = await pickMember(op === "host" ? "谁当主控" : op === "remove" ? "移出谁" : "选成员")
      if (!m) return "已取消"
      const c = client()
      if (op === "host") await c.transferHost(m)
      else if (op === "pause") await c.pauseMember(m)
      else if (op === "resume") await c.resumeMember(m)
      else if (op === "remove") await c.removeMember(m)
      return `${op} ${m} ok`
    }

    async function doDm(member, text) {
      let m = member
      if (!m) m = await pickMember("私聊给谁")
      if (!m) return "已取消"
      let t = text
      if (!t) {
        try {
          t = await ctx.ui.dialog.prompt({ title: `私聊 ${m}`, description: "内容" })
        } catch {}
      }
      if (!t) return "已取消"
      const r = await client().say(m, t)
      setTimeout(() => !stop && poll(), 200)
      return `已发送 #${r.id}`
    }

    async function doSay(to, text) {
      let dst = to
      if (!dst) {
        const v = ui.view
        const opts = [
          ...((v?.threads || []).map((t) => ({ title: `${t.private ? "🔒" : ""}${t.id}`, value: t.id }))),
          ...memberOptions().map((o) => ({ title: `成员 ${o.title}`, value: o.value })),
        ]
        if (!opts.length) return "还没加入房间"
        try {
          dst = (await ctx.ui.dialog.select({ title: "发到哪里", options: opts })) || ""
        } catch {}
      }
      if (!dst) return "已取消"
      let t = text
      if (!t) {
        try {
          t = await ctx.ui.dialog.prompt({ title: `发到 ${dst}`, description: "内容" })
        } catch {}
      }
      if (!t) return "已取消"
      const r = await client().say(dst, t)
      setTimeout(() => !stop && poll(), 200)
      return `已发送 #${r.id}`
    }

    async function doNewGroup(id, members, title) {
      let gid = id
      if (!gid) {
        try {
          gid = await ctx.ui.dialog.prompt({ title: "新建私有群", description: "群 id（#名字）", placeholder: "#team2" })
        } catch {}
      }
      if (!gid) return "已取消"
      if (!gid.startsWith("#")) gid = "#" + gid
      let ms = members
      if (!ms || !ms.length) {
        try {
          const raw = (await ctx.ui.dialog.prompt({ title: "新建私有群", description: "成员（逗号分隔）", placeholder: "e1,e2" })) || ""
          ms = raw.split(/[,，\s]+/).filter(Boolean)
        } catch {}
      }
      const r = await client().threadNew({ id: gid, members: ms || [], title })
      return `group ${r.thread} created`
    }

    async function doGroupAdd(thread, member) {
      let t = thread
      if (!t) t = await pickThread("拉进哪个群", true)
      if (!t) return "已取消"
      let m = member
      if (!m) m = await pickMember("拉谁进群")
      if (!m) return "已取消"
      await client().threadAdd(t, m)
      return `${m} 已拉进 ${t}`
    }

    async function doGroupRm(thread, member) {
      let t = thread
      if (!t) t = await pickThread("从哪个群移出", true)
      if (!t) return "已取消"
      let m = member
      if (!m) m = await pickMember("移出谁")
      if (!m) return "已取消"
      await client().threadRemove(t, m)
      return `${m} 已移出 ${t}`
    }

    async function doGroup(action, rest) {
      let a = action
      if (!a) {
        try {
          a = await ctx.ui.dialog.select({
            title: "群管理",
            options: [
              { title: "新建私有群", value: "new" },
              { title: "把成员拉进群", value: "add" },
              { title: "把成员移出群", value: "rm" },
            ],
          })
        } catch {}
      }
      if (!a) return "已取消"
      if (a === "new") return doNewGroup(rest[0], rest.slice(1).length ? rest.slice(1) : undefined)
      if (a === "add") return doGroupAdd(rest[0], rest[1])
      if (a === "rm") return doGroupRm(rest[0], rest[1])
      return "用法：/xmuse-group [new|add|rm] …"
    }

    async function doMore(kind, rest) {
      let k = kind
      if (!k) {
        try {
          k = await ctx.ui.dialog.select({
            title: "更多操作",
            options: [
              { title: "邀请码邀请", value: "invite" },
              { title: "暂停成员", value: "pause" },
              { title: "恢复成员", value: "resume" },
              { title: "移出成员", value: "remove" },
              { title: "加载更早消息", value: "more" },
              { title: "确认已读", value: "ack" },
            ],
          })
        } catch {}
      }
      if (!k) return "已取消"
      if (k === "invite") return doInvite(rest[0], rest[1], rest.slice(2).join(" ") || undefined, "")
      if (k === "pause" || k === "resume" || k === "remove") return doMemberOp(k, rest[0])
      if (k === "more") return doMoreMessages()
      if (k === "ack") return doAck()
      return "已取消"
    }

    async function doMoreMessages() {
      const oldest = ui.view?.timeline_cursor?.oldest || ui.view?.timeline?.[0]?.id
      if (!oldest) return "没有更早的消息"
      const t = await client().timeline(oldest, 20)
      setUi((d) => {
        d.view = { ...d.view, timeline: dedupeTimeline(t.items, d.view.timeline) }
      })
      return `载入 ${t.items.length} 条更早消息`
    }

    async function doAck() {
      const ids = (ui.view?.timeline || []).filter((m) => m.for_me).map((m) => m.id)
      if (!ids.length) return "没有 @ 我的消息"
      const r = await client().ack(ids)
      return `已确认 ${r.acked ?? ids.length} 条`
    }

    async function doLeave() {
      await client().leave()
      setAuth((d) => {
        d.memberToken = ""
        d.operatorToken = ""
        d.memberId = ""
      })
      setUi((d) => void (d.view = null))
      try {
        clearStore(process.env)
      } catch {}
      return "已离开房间"
    }

    function toastOut(out) {
      try {
        ctx.ui.toast.show({ title: "xmuse", message: String(out).slice(0, 300), variant: "info" })
      } catch {}
    }

    async function runSafe(fn) {
      try {
        toastOut(await fn())
      } catch (e) {
        try {
          ctx.ui.toast.show({ title: "xmuse", message: `失败: ${String(e?.message || e).slice(0, 200)}`, variant: "error" })
        } catch {}
      }
    }
    async function doApprove(id, decision) {
      const v = ui.view
      let aid = id
      let dec = decision
      if (!aid && v?.approvals?.length) {
        try {
          aid = await ctx.ui.dialog.select({
            title: "审批：选条目",
            options: v.approvals.map((a) => ({
              title: a.kind === "share" ? formatShareApproval(a) : `${a.id} ${a.member ? a.member + ": " : ""}${a.summary || a.text || ""}`,
              value: a.id,
            })),
          })
        } catch {}
      }
      if (!aid) return "无审批或已取消"
      if (!dec) {
        try {
          dec = await ctx.ui.dialog.select({
            title: `审批 ${aid}`,
            options: [
              { title: "批准一次", value: "once" },
              { title: "总是批准", value: "always" },
              { title: "拒绝", value: "reject" },
            ],
          })
        } catch {}
      }
      if (!dec) return "已取消"
      await client().approve(aid, dec)
      return `approval ${aid} -> ${dec}`
    }

    const CODE_RE = /^[A-Za-z0-9]{4}-[A-Za-z0-9]{2}$/
    const splitArgs = (input) => String(input || "").trim().split(/\s+/).filter(Boolean)

    // 兼容入口的老分发（/xmuse <子命令>）：不认识的子命令列出全部命令，不静默、不交给模型
    async function runCompat(input) {
      const { cmd, args } = parseSlash(input)
      switch (cmd) {
        case "status": case "": return doStatus()
        case "room": return args[0] === "new" ? doRoomNew(args.slice(1).join(" ") || undefined) : compatHelp()
        case "invite": return doInvite(args[0], args[1], args.slice(2).join(" ") || undefined, "")
        case "join": return doJoin(args[0])
        case "join-local": case "joinlocal": return doJoinLocal(args[0])
        case "rooms": return doRooms()
        case "leave": return doLeave()
        case "say": {
          const s = buildSayArgs(args)
          if (!s) return compatHelp()
          const r = await client().say(s.to, s.text)
          setTimeout(() => !stop && poll(), 200)
          return `已发送 #${r.id}`
        }
        case "dm": return doDm(args[0], args.slice(1).join(" ") || undefined)
        case "add": return doAdd(args[0], args[1], args[2] === undefined ? undefined : args.slice(2).join(" "))
        case "edit": return doEdit(args[0], args[1], args.slice(2).join(" ") || undefined)
        case "host": case "pause": case "resume": case "remove": return doMemberOp(cmd, args[0])
        case "new-group": case "group-new": {
          const rest = args.slice(1).join(" ").split(/\s+/).filter(Boolean)
          return doNewGroup(args[0], rest.length ? rest : undefined)
        }
        case "group-add": return doGroupAdd(args[0], args[1])
        case "group-rm": return doGroupRm(args[0], args[1])
        case "approve": return doApprove(args[0], args[1])
        case "more": return doMoreMessages()
        case "ack": return doAck()
        case "wake": {
          const r = await client().wakeHost()
          setTimeout(() => !stop && poll(), 200)
          return `已叫醒主控（放出 ${r.released ?? 0} 条结果）`
        }
        default: return compatHelp()
      }
    }

    ctx.keymap.layer(() => ({
      commands: [
        ...COMMANDS.map((c) => ({
          id: c.name,
          title: c.title,
          description: c.description,
          palette: true,
          slash: { name: c.name, arguments: true },
          run: (input) => runSafe(async () => {
            const args = splitArgs(input)
            switch (c.name) {
              case "xmuse-status": return doStatus()
              case "xmuse-rooms": return doRooms()
              case "xmuse-join": {
                const sel = args[0] || ""
                if (!sel) return doJoinLocal(undefined)
                return CODE_RE.test(sel) ? doJoin(sel) : doJoinLocal(sel, args[1], args[2])
              }
              case "xmuse-new-room": return doRoomNew(args[0], args[1])
              case "xmuse-add": return doAdd(args[0], args[1], args[2] === undefined ? undefined : args.slice(2).join(" "))
              case "xmuse-host": return doMemberOp("host", args[0])
              case "xmuse-edit": return doEdit(args[0], args[1], args.slice(2).join(" ") || undefined)
              case "xmuse-dm": return doDm(args[0], args.slice(1).join(" ") || undefined)
              case "xmuse-say": return doSay(args[0], args.slice(1).join(" ") || undefined)
              case "xmuse-group": return doGroup(args[0], args.slice(1))
              case "xmuse-approve": return doApprove(args[0], args[1])
              case "xmuse-wake": {
                const r = await client().wakeHost()
                setTimeout(() => !stop && poll(), 200)
                return `已叫醒主控（放出 ${r.released ?? 0} 条结果）`
              }
              case "xmuse-leave": return doLeave()
              case "xmuse-more": return doMore(args[0], args.slice(1))
              default: return compatHelp()
            }
          }),
        })),
        {
          id: "xmuse.cmd",
          title: "xmuse（兼容：/xmuse <子命令>）",
          description: "旧的子命令入口，照旧可用；不认识的子命令会列出全部命令",
          slash: { name: "xmuse", arguments: true },
          run: (input) => runSafe(() => runCompat(input)),
        },
      ],
    }))

    return () => {
      stop = true
      clearInterval(roomsTimer)
      off()
    }
  },
})
