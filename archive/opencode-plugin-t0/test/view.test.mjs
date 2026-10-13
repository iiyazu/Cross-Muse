import { test } from "node:test"
import assert from "node:assert/strict"
import { parseSlash, dedupeTimeline, newMentions, formatSidebar, buildSayArgs, memberRow, msgRow, doneTag, threadShort, formatGroups, formatHeader, formatHostLine, roleText, statusText, formatRooms, formatShareApproval } from "../lib/view.mjs"
import { COMMANDS, compatHelp, COMPAT_SUBS } from "../lib/commands.mjs"

test("parseSlash 基本", () => {
  assert.deepEqual(parseSlash("room new demo"), { cmd: "room", args: ["new", "demo"] })
  assert.deepEqual(parseSlash("  "), { cmd: "status", args: [] })
  assert.deepEqual(parseSlash("JOIN k7-1"), { cmd: "join", args: ["k7-1"] })
})

test("dedupeTimeline 去重并排序", () => {
  const a = [{ id: 3 }, { id: 1 }]
  const b = [{ id: 2 }, { id: 3 }]
  assert.deepEqual(dedupeTimeline(a, b).map((m) => m.id), [1, 2, 3])
})

test("newMentions 只返回 for_me 且更新的", () => {
  const items = [
    { id: 10, for_me: true },
    { id: 11, for_me: false },
    { id: 12, for_me: true },
  ]
  assert.deepEqual(newMentions(items, 10).map((m) => m.id), [12])
})

test("formatSidebar 未加入时提示命令", () => {
  const L = formatSidebar(null)
  assert.ok(L.join("\n").includes("/xmuse-join"))
})

test("formatSidebar 全量快照", () => {
  const view = {
    version: 5,
    room: { id: "r-1", name: "demo", host: "coord" },
    me: { kind: "member", id: "oc-1" },
    members: [
      { id: "coord", role: "coordinator", status: "idle", online: true, unread: 0 },
      { id: "oc-1", role: "executor", status: "running", online: true, unread: 2, description: "侧栏" },
    ],
    threads: [{ id: "#d", members: ["coord", "oc-1"] }],
    timeline: [{ id: 1, thread: "#d", from: "coord", via: null, to: ["oc-1"], mentions: ["oc-1"], text: "hi", at: 1791726500, for_me: true }],
    timeline_cursor: { oldest: 1, has_more: false },
    alignment: [{ id: "E1", kind: "decision", scope: "room", author: "coord", text: "按 v0" }],
    approvals: [{ id: "A1", kind: "shell", member: "oc-1", summary: "npm i", risk: "normal" }],
    host_wait: { waiting_on: [], results_held: 0, wake_at: null },
  }
  const L = formatSidebar(view)
  assert.ok(L[0].includes("demo") && L[0].includes("oc-1") && !L[0].includes("v5"))
  assert.ok(L.some((x) => x.includes("★ coord")))
  assert.ok(L.some((x) => x.includes("oc-1 executor · 运行中")))
  assert.ok(L.some((x) => x.includes("⚠ 待审批 1 条")))
  assert.ok(L.some((x) => x.includes("#d coord→oc-1 hi")))
  assert.ok(L.some((x) => x.includes("E1 decision")))
})

test("formatSidebar 空区块隐藏", () => {
  const view = {
    version: 1, room: { id: "r-1", name: "demo", host: "c" }, me: { kind: "member", id: "c" },
    members: [{ id: "c", role: "", status: "idle", online: true, unread: 0 }],
    threads: [], timeline: [], timeline_cursor: { oldest: 0, has_more: false },
    alignment: [], approvals: [], host_wait: { waiting_on: [], results_held: 0, wake_at: null },
  }
  const L = formatSidebar(view)
  assert.ok(!L.some((x) => x.includes("— 群 —") || x.includes("— 消息 —") || x.includes("待审批") || x.includes("主控在等")))
})

test("buildSayArgs", () => {
  assert.deepEqual(buildSayArgs(["say", "#d", "hello", "all"]), { to: "#d", text: "hello all" })
  assert.equal(buildSayArgs(["say", "#d"]), null)
})

test("formatRooms 房间列表行", () => {
  assert.deepEqual(formatRooms([], {}), ["本机没有房间（/xmuse-new-room 开一个）"])
  const entries = [
    { room_id: "r-1", name: "dev", dir: "/x", url: "http://h1", host: "c" },
    { room_id: "r-2", name: "t", dir: "/y", url: "http://h2", host: "c" },
  ]
  const L = formatRooms(entries, {
    "http://h1": { room: { id: "r-1", host: "c" }, members: [{ id: "c", online: true }, { id: "e", online: false }] },
  })
  assert.ok(L[0].includes("2成员/1在线"))
  assert.ok(L[1].includes("连不上"))
})

test("formatShareApproval 显示摘要和摘录", () => {
  const l = formatShareApproval({ id: "share:1", summary: "e1 想把 #5 分享给 e2", detail: { excerpt: "秘密计划" } })
  assert.ok(l.includes("share:1") && l.includes("秘密计划") && l.includes("once/always/reject"))
})

test("memberRow 说明示例格式", () => {
  assert.equal(memberRow({ id: "lead", role: "coordinator", status: "idle", online: true, unread: 0 }, "lead", "lead"), "★ lead 主控 · 在线 · 我")
  assert.equal(
    memberRow({ id: "oc-exec", role: "executor", status: "running", online: true, unread: 0, description: "负责实现" }, "lead", "lead"),
    "  oc-exec executor · 运行中 · 负责实现")
  assert.equal(
    memberRow({ id: "e", role: "", status: "idle", online: true, unread: 0, wakes_hour: 0 }, "x", "lead"),
    "  e 成员 · 在线")
  assert.equal(
    memberRow({ id: "e", role: "executor", status: "paused", online: true, unread: 2, wakes_hour: 3 }, "x", "lead"),
    "  e executor · 暂停 · 本小时唤醒 3 次 · 2未读")
  assert.ok(memberRow({ id: "e", status: "offline", online: false }, "x", "y").includes("离线"))
})

test("roleText/statusText", () => {
  assert.equal(roleText("coordinator", false), "负责人")
  assert.equal(roleText("", false), "成员")
  assert.equal(roleText("executor", true), "主控")
  assert.equal(statusText({ online: true, status: "running" }), "运行中")
  assert.equal(statusText({ online: true, status: "idle" }), "在线")
  assert.equal(statusText({ online: false, status: "idle" }), "离线")
})

test("msgRow 说明示例格式", () => {
  assert.equal(msgRow({ thread: "#room", from: "human", to: [], mentions: [], text: "做个 hello.py" }), "#room 用户→全体 做个 hello.py")
  assert.equal(
    msgRow({ thread: "dm:lead+oc-exec", from: "oc-exec", to: ["lead"], mentions: [], kind: "done", outcome: "completed", evidence_status: "verified", text: "hello.py 已写好" }),
    "dm oc-exec→lead [完成·已核实] hello.py 已写好")
  assert.equal(msgRow({ thread: "#room", kind: "system", from: "hub", text: "dsh 加入了房间" }), "#room 系统→全体 dsh 加入了房间")
  assert.equal(msgRow({ thread: "#r", from: "a", to: [], mentions: ["b"], kind: "done", outcome: "blocked", outcome_by: "hub", text: "x" }), "#r a→b [阻塞·hub改判] x")
  assert.equal(msgRow({ thread: "#r", from: "a", text: "x", kind: "done", evidence_status: "unverified" }), "#r a→全体 [未核实] x")
  assert.equal(threadShort("dm:a+b"), "dm")
  assert.equal(threadShort("#room"), "#room")
})

test("doneTag 标签", () => {
  assert.equal(doneTag({ kind: "done", outcome: "completed", evidence_status: "verified" }), "[完成·已核实]")
  assert.equal(doneTag({ kind: "done", outcome: "blocked", outcome_by: "hub" }), "[阻塞·hub改判]")
  assert.equal(doneTag({ kind: "done", evidence_status: "unverified" }), "[未核实]")
  assert.equal(doneTag({ kind: "done", outcome: "progress" }), "[进展]")
  assert.equal(doneTag({ kind: "message" }), "")
})

test("formatHeader/formatGroups/formatHostLine", () => {
  const view = {
    room: { name: "t0", host: "lead" }, me: { id: "lead" },
    members: [{ id: "lead", role: "coordinator" }],
  }
  assert.equal(formatHeader(view), "xmuse · t0（我：负责人 lead ★主控）")
  assert.equal(formatGroups([{ id: "#room", members: ["human", "lead", "a", "b", "c", "d"] }, { id: "#trio", private: true, members: ["human", "lead", "a", "b"] }], "lead"), "#room 4名成员 + 你 · #trio 🔒2名成员 + 你")
  assert.equal(formatGroups([{ id: "#trio", private: true, members: ["human", "a", "b", "c"] }], "lead"), "#trio 🔒3名成员")
  assert.equal(formatGroups([]), "")
  assert.equal(formatHostLine(null), "")
  assert.equal(formatHostLine({ waiting_on: [], results_held: 0, wake_at: null }), "")
  assert.equal(
    formatHostLine({ waiting_on: [{ member: "a" }, { member: "b" }], results_held: 3, wake_at: 1600 }, 1000),
    "主控在等：a、b · 压住 3 条 · 10 分钟后自动叫醒 · /xmuse-wake")
})

test("formatSidebar 新布局（审批置顶、空区块隐藏）", () => {
  const view = {
    version: 9, room: { id: "r-1", name: "t0", host: "lead" }, me: { kind: "member", id: "lead" },
    members: [{ id: "lead", role: "coordinator", status: "idle", online: true, unread: 0 }],
    threads: [{ id: "#room", members: ["lead"] }],
    timeline: [{ id: 1, thread: "#room", from: "human", to: [], mentions: [], text: "hi", kind: "message" }],
    timeline_cursor: { oldest: 1, has_more: false },
    alignment: [],
    approvals: [{ id: "A1", kind: "shell", member: "e", summary: "run", risk: "normal" }],
    host_wait: { waiting_on: [], results_held: 0, wake_at: null },
  }
  const L = formatSidebar(view)
  assert.equal(L[0], "xmuse · t0（我：负责人 lead ★主控）")
  assert.equal(L[1], "⚠ 待审批 1 条：/xmuse-approve")
  assert.ok(!L.some((x) => x.includes("v9")))
  assert.ok(L.some((x) => x.includes("★ lead")))
})

test("命令表：人人有标题和说明；兼容入口列出命令", () => {
  const names = COMMANDS.map((c) => c.name)
  for (const n of ["xmuse-status", "xmuse-rooms", "xmuse-join", "xmuse-new-room", "xmuse-add", "xmuse-host", "xmuse-edit", "xmuse-dm", "xmuse-say", "xmuse-group", "xmuse-approve", "xmuse-wake", "xmuse-leave"]) {
    assert.ok(names.includes(n), n)
  }
  for (const c of COMMANDS) {
    assert.ok(c.title && c.description, c.name)
    assert.ok(c.name.startsWith("xmuse-"), c.name)
  }
  const help = compatHelp()
  for (const n of names) assert.ok(help.includes("/" + n), n)
  assert.ok(COMPAT_SUBS.includes("approve") && COMPAT_SUBS.includes("wake"))
})
