/** @jsxImportSource @opentui/solid */
// xmuse 侧栏：OpenCode 2.x TUI 插件。约定 v0（docs/design/XMUSE2-VIEW-API.zh.md）。
// 薄渲染层：只画画、把操作转成 /v1/view、/v1/act、rooms/join 请求。令牌只在 ctx.storage.store + 插件文件存储里。
import { Plugin } from "@opencode/plugin/tui"
import { HubClient } from "./lib/hub.mjs"
import { hubBaseUrl, loadStore, saveStore, clearStore } from "./lib/store.mjs"
import { registryDir, readHubs, readCredential, fetchRoomInfo } from "./lib/registry.mjs"
import {
  parseSlash, buildSayArgs, newMentions, dedupeTimeline,
  memberLine, threadLine, formatRooms, formatShareApproval,
  formatDone, formatHostWait,
} from "./lib/view.mjs"

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
              <text>/xmuse join {"<码>"} 加入</text>
            </box>
          )
        if (!v)
          return (
            <box flexDirection="column">
              <text>xmuse: 未加入房间</text>
              {ui.error ? <text>错误: {ui.error}</text> : null}
              <text>— 本机房间 —</text>
              {(ui.rooms || []).slice(0, 5).map((r) => (
                <text>
                  {r.name || r.room_id}（{r.online ? "在线" : "连不上"}）
                </text>
              ))}
              <text>/xmuse rooms 看列表</text>
              <text>/xmuse join-local {"<序号>"} 一键加入</text>
              <text>/xmuse room new {"<名>"} 开房间</text>
              <text>/xmuse join {"<码>"} 邀请码加入</text>
            </box>
          )
        const members = v.members || []
        const tl = (v.timeline || []).slice(-8)
        const appr = v.approvals || []
        const threads = v.threads || []
        const hwLines = formatHostWait(v.host_wait)
        const shares = appr.filter((a) => a.kind === "share")
        const others = appr.filter((a) => a.kind !== "share")
        return (
          <box flexDirection="column">
            <text>
              xmuse {v.room?.name} v{v.version}
            </text>
            <text>
              我 {v.me?.id} · 成员{String(members.length)} · 审批{String(appr.length)}
            </text>
            {ui.error ? <text>错误: {ui.error}</text> : null}
            <text>— 成员 —</text>
            {members.slice(0, 8).map((m) => (
              <text>{memberLine(m)}</text>
            ))}
            {threads.length ? <text>— 群 —</text> : null}
            {threads.slice(0, 6).map((t) => (
              <text>{threadLine(t)}</text>
            ))}
            <text>— 消息 —</text>
            {tl.map((m) => (
              <text>
                {(m.for_me ? "▶" : "-") + (m.from === "human" ? "用户" : m.from) + ": " + String(m.text).slice(0, 80)}
              </text>
            ))}
            {tl.filter((m) => m.kind === "done" && formatDone(m).length).slice(-3).map((m) => (
              <text>
                {`#${m.id} ` + formatDone(m).join("；").slice(0, 100)}
              </text>
            ))}
            {hwLines.length ? <text>— 主控 —</text> : null}
            {hwLines.map((l) => (
              <text>{l}</text>
            ))}
            {hwLines.length ? <text>/xmuse wake 现在叫醒</text> : null}
            {others.length ? <text>— 审批 —</text> : null}
            {others.slice(0, 3).map((a) => (
              <text>
                [{a.id}] {String(a.summary || a.text || a.id).slice(0, 60)}
              </text>
            ))}
            {shares.length ? <text>— 分享审批 —</text> : null}
            {shares.slice(0, 3).map((a) => (
              <text>
                {formatShareApproval(a).slice(0, 100)}
              </text>
            ))}
            {appr.length ? <text>/xmuse approve {"<id> once|always|reject"}</text> : null}
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

    async function doRoomNew(name) {
      let roomName = name
      if (!roomName) {
        try {
          roomName = await ctx.ui.dialog.prompt({ title: "开房间", description: "房间名", placeholder: "xmuse-dev" })
        } catch {}
      }
      if (!roomName) return "已取消"
      const c = client()
      const sid = auth.sessionId || sessionId || `opencode-${Date.now()}`
      const r = await c.openRoom({
        dir: process.cwd(),
        name: roomName,
        vendor: "opencode",
        sessionId: sid,
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

    async function doJoinLocal(sel) {
      const { entries } = await loadRooms()
      if (!entries.length) return "本机没有房间，先 /xmuse room new 开一个"
      let e = null
      if (sel && /^\d+$/.test(sel)) e = entries[Number(sel) - 1]
      else if (sel) e = entries.find((x) => x.room_id === sel || x.name === sel)
      if (!e) {
        try {
          const picked = await ctx.ui.dialog.select({
            title: "加入房间",
            options: entries.map((x) => ({ title: `${x.name || x.room_id} — ${x.dir || "?"}`, value: x.room_id })),
          })
          e = entries.find((x) => x.room_id === picked)
        } catch {}
      }
      if (!e || !e.url) return "已取消或该房间连不上"
      const sid = auth.sessionId || sessionId || `opencode-${Date.now()}`
      const c = client(String(e.url))
      // 先问房间要概况（认路），再本机加入
      const r = await c.joinLocal({ roomId: e.room_id, vendor: "opencode", sessionId: sid })
      setAuth((d) => {
        d.hubUrl = String(e.url)
        d.memberId = r.member_id
        d.memberToken = r.member_token
        d.operatorToken = r.operator_token
        d.sessionId = sid
      })
      persist()
      setTimeout(() => !stop && poll(), 200)
      try {
        ctx.ui.toast.show({ title: "xmuse", message: `已加入 ${e.name || e.room_id}，你是 ${r.member_id}`, variant: "success" })
      } catch {}
      return `joined ${e.name || e.room_id} as ${r.member_id}`
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
      const r = await client().memberAdd({ vendor, model, role: role || "executor", description: desc || "", name })
      try {
        ctx.ui.toast.show({ title: "xmuse", message: `已添加成员 ${r.member_id}`, variant: "success" })
      } catch {}
      return `member ${r.member_id} added`
    }

    async function doEdit(member, field, value) {
      if (!member) return "用法：/xmuse edit <成员> [role|desc] [新值]"
      let role, description
      if (field === "role") role = value
      else if (field === "desc" || field === "description") description = value
      if (role === undefined && description === undefined) {
        try {
          description = await ctx.ui.dialog.prompt({ title: `改 ${member}`, description: "新职责描述" })
        } catch {}
        if (!description) return "已取消"
      }
      await client().memberEdit(member, { role, description })
      return `member ${member} updated`
    }

    async function doMemberOp(op, member) {
      if (!member) return `用法：/xmuse ${op} <成员>`
      const c = client()
      if (op === "host") await c.transferHost(member)
      else if (op === "pause") await c.pauseMember(member)
      else if (op === "resume") await c.resumeMember(member)
      else if (op === "remove") await c.removeMember(member)
      return `${op} ${member} ok`
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

    ctx.keymap.layer(() => ({
      commands: [
        {
          id: "xmuse.cmd",
          title: "xmuse",
          description: "xmuse 房间操作（room/invite/join/status/leave/say/approve/rooms/add/edit/host/pause/dm/new-group）",
          slash: { name: "xmuse", arguments: true },
          run: async (input) => {
            const { cmd, args } = parseSlash(input)
            try {
              let out = ""
              if (cmd === "status" || cmd === "") out = await doStatus()
              else if (cmd === "room" && args[0] === "new") out = await doRoomNew(args.slice(1).join(" "))
              else if (cmd === "invite") out = await doInvite(args[0], args[1], args.slice(2).join(" ") || "", "")
              else if (cmd === "join") out = await doJoin(args[0])
              else if (cmd === "leave") {
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
                out = "已离开房间"
              } else if (cmd === "say") {
                const s = buildSayArgs(args)
                if (!s) out = "用法：/xmuse say <to> <文字>（to: 成员/#话题/线程id）"
                else {
                  const r = await client().say(s.to, s.text)
                  out = `已发送 #${r.id}`
                  setTimeout(() => !stop && poll(), 200)
                }
              } else if (cmd === "approve") out = await doApprove(args[0], args[1])
              else if (cmd === "rooms") out = await doRooms()
              else if (cmd === "join-local" || cmd === "joinlocal") out = await doJoinLocal(args[0])
              else if (cmd === "add") out = await doAdd(args[0], args[1], args[2] === undefined ? undefined : args.slice(2).join(" "))
              else if (cmd === "edit") out = await doEdit(args[0], args[1], args.slice(2).join(" ") || undefined)
              else if (cmd === "host" || cmd === "pause" || cmd === "resume" || cmd === "remove") out = await doMemberOp(cmd, args[0])
              else if (cmd === "dm") {
                if (args.length < 2) out = "用法：/xmuse dm <成员> <文字>"
                else {
                  const r = await client().say(args[0], args.slice(1).join(" "))
                  out = `已发送 #${r.id}`
                  setTimeout(() => !stop && poll(), 200)
                }
              } else if (cmd === "new-group" || cmd === "group-new") {
                const rest = args.slice(1).join(" ").split(/\s+/).filter(Boolean)
                out = await doNewGroup(args[0], rest.length ? rest : undefined)
              } else if (cmd === "group-add") {
                if (args.length < 2) out = "用法：/xmuse group-add <群> <成员>"
                else {
                  await client().threadAdd(args[0], args[1])
                  out = `${args[1]} 已拉进 ${args[0]}`
                }
              } else if (cmd === "group-rm") {
                if (args.length < 2) out = "用法：/xmuse group-rm <群> <成员>"
                else {
                  await client().threadRemove(args[0], args[1])
                  out = `${args[1]} 已移出 ${args[0]}`
                }
              } else if (cmd === "more") {
                const oldest = ui.view?.timeline_cursor?.oldest || ui.view?.timeline?.[0]?.id
                if (!oldest) out = "没有更早的消息"
                else {
                  const t = await client().timeline(oldest, 20)
                  setUi((d) => {
                    d.view = { ...d.view, timeline: dedupeTimeline(t.items, d.view.timeline) }
                  })
                  out = `载入 ${t.items.length} 条更早消息`
                }
              } else if (cmd === "ack") {
                const ids = (ui.view?.timeline || []).filter((m) => m.for_me).map((m) => m.id)
                if (ids.length) {
                  const r = await client().ack(ids)
                  out = `已确认 ${r.acked ?? ids.length} 条`
                } else out = "没有 @ 我的消息"
              } else if (cmd === "wake") {
                const r = await client().wakeHost()
                out = `已叫醒主控（放出 ${r.released ?? 0} 条结果）`
                setTimeout(() => !stop && poll(), 200)
              } else out = "用法：/xmuse status|rooms|room new <名>|join-local [序号]|join <码>|add [厂商 角色 描述]|edit <成员> [role|desc] [值]|host|pause|resume|remove <成员>|dm <成员> <文字>|new-group [#群] [成员..]|group-add|group-rm <群> <成员>|say <to> <文字>|approve [id] [once|always|reject]|more|ack|wake"
              try {
                ctx.ui.toast.show({ title: "xmuse", message: out.slice(0, 300), variant: "info" })
              } catch {}
            } catch (e) {
              const msg = `失败: ${String(e?.message || e).slice(0, 200)}`
              try {
                ctx.ui.toast.show({ title: "xmuse", message: msg, variant: "error" })
              } catch {}
            }
          },
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
