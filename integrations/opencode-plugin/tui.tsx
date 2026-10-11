/** @jsxImportSource @opentui/solid */
// xmuse 侧栏：OpenCode 2.x TUI 插件。约定 v0（docs/design/XMUSE2-VIEW-API.zh.md）。
// 薄渲染层：只画画、把操作转成 /v1/view、/v1/act、rooms/join 请求。令牌只在 ctx.storage.store + 插件文件存储里。
import { Plugin } from "@opencode/plugin/tui"
import { HubClient } from "./lib/hub.mjs"
import { hubBaseUrl, loadStore, saveStore, clearStore } from "./lib/store.mjs"
import { parseSlash, buildSayArgs, newMentions, dedupeTimeline } from "./lib/view.mjs"

export default Plugin.define({
  id: "xmuse",
  setup(ctx) {
    const [auth, setAuth] = ctx.storage.store("xmuse-auth", {
      initial: { hubUrl: "", memberId: "", memberToken: "", operatorToken: "", sessionId: "" },
    })
    const [ui, setUi] = ctx.storage.memory("xmuse-view", {
      initial: { view: null, error: "", loading: true, extraOlder: [] },
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

    const baseUrl = () =>
      auth.hubUrl || process.env.XMUSE_HUB_URL || hubBaseUrl(process.env)
    const client = () =>
      new HubClient({
        baseUrl: baseUrl(),
        memberToken: auth.memberToken,
        operatorToken: auth.operatorToken,
        sessionId: auth.sessionId || sessionId,
      })

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
              <text>/xmuse room new {"<名>"}</text>
              <text>/xmuse join {"<码>"}</text>
            </box>
          )
        const members = v.members || []
        const tl = (v.timeline || []).slice(-8)
        const appr = v.approvals || []
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
              <text>
                {(m.online ? (m.status === "running" ? "●" : "·") : "○") + " " + m.id + (m.unread ? ` (${m.unread})` : "")}
              </text>
            ))}
            <text>— 消息 —</text>
            {tl.map((m) => (
              <text>
                {(m.for_me ? "▶" : "-") + (m.from === "human" ? "用户" : m.from) + ": " + String(m.text).slice(0, 80)}
              </text>
            ))}
            {appr.length ? <text>— 审批 —</text> : null}
            {appr.slice(0, 4).map((a) => (
              <text>
                [{a.id}] {String(a.summary || a.text || a.id).slice(0, 60)}
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

    async function doApprove(id, decision) {
      const v = ui.view
      let aid = id
      let dec = decision
      if (!aid && v?.approvals?.length) {
        try {
          aid = await ctx.ui.dialog.select({
            title: "审批：选条目",
            options: v.approvals.map((a) => ({ title: `${a.id} ${a.member ? a.member + ": " : ""}${a.summary || a.text || ""}`, value: a.id })),
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
          description: "xmuse 房间操作（room/invite/join/status/leave/say/approve）",
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
              else if (cmd === "more") {
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
                if (ids.length) await client().ack(ids)
                out = `已确认 ${ids.length} 条`
              } else out = "用法：/xmuse status|room new <名>|invite <provider> <角色> <描述>|join <码>|leave|say <to> <文字>|approve [id] [once|always|reject]|more|ack"
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
      off()
    }
  },
})
