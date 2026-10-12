import { test } from "node:test"
import assert from "node:assert/strict"
import { parseSlash, dedupeTimeline, newMentions, formatSidebar, buildSayArgs, memberLine, threadLine, formatRooms, formatShareApproval, formatDone, formatHostWait } from "../lib/view.mjs"

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
  assert.ok(L[0].includes("/xmuse"))
})

test("formatSidebar 全量快照", () => {
  const view = {
    version: 5,
    room: { id: "r-1", name: "demo" },
    me: { kind: "member", id: "oc-1" },
    members: [{ id: "oc-1", role: "executor", status: "running", online: true, unread: 2, description: "侧栏" }],
    threads: [],
    timeline: [{ id: 1, thread: "#d", from: "coord", via: null, to: ["oc-1"], mentions: ["oc-1"], text: "hi", at: 1791726500, for_me: true }],
    timeline_cursor: { oldest: 1, has_more: false },
    alignment: [{ id: "E1", kind: "decision", scope: "room", author: "coord", text: "按 v0" }],
    approvals: [{ id: "A1", kind: "shell", member: "oc-1", summary: "npm i", risk: "normal" }],
  }
  const L = formatSidebar(view)
  assert.ok(L.some((x) => x.includes("oc-1")))
  assert.ok(L.some((x) => x.includes("A1")))
  assert.ok(L.some((x) => x.includes("E1")))
})

test("buildSayArgs", () => {
  assert.deepEqual(buildSayArgs(["say", "#d", "hello", "all"]), { to: "#d", text: "hello all" })
  assert.equal(buildSayArgs(["say", "#d"]), null)
})

test("formatSidebar 审批兼容 alignment/resume（无 member/summary）", () => {
  const view = {
    version: 1,
    room: { id: "r-1", name: "demo" },
    me: { kind: "operator", id: "oc-1" },
    members: [],
    timeline: [],
    timeline_cursor: { oldest: 0, has_more: false },
    alignment: [],
    approvals: [
      { id: "E12", kind: "alignment", text: "按 v0 对接" },
      { id: "resume:oc-1", kind: "resume", member: "oc-1", text: "恢复成员" },
    ],
  }
  const L = formatSidebar(view)
  assert.ok(L.some((x) => x.includes("E12")))
  assert.ok(L.some((x) => x.includes("resume:oc-1")))
})

test("memberLine 离线/未读", () => {
  assert.ok(memberLine({ id: "a", role: "executor", status: "offline", online: false, unread: 0, description: "" }).startsWith("○"))
})

test("memberLine 显示 wakes_hour（无则不显示）", () => {
  const l = memberLine({ id: "a", role: "executor", status: "idle", online: true, unread: 0, description: "", wakes_hour: 3 })
  assert.ok(l.includes("~3/h"))
  assert.ok(!memberLine({ id: "a", role: "executor", status: "idle", online: true, unread: 0 }).includes("/h"))
})

test("threadLine 私有群锁标记", () => {
  assert.ok(threadLine({ id: "#g1", private: true, members: ["a", "b"], unread: 0 }).startsWith("🔒#g1"))
  assert.ok(!threadLine({ id: "#room", members: [], unread: 0 }).startsWith("🔒"))
})

test("formatRooms 房间列表行", () => {
  assert.deepEqual(formatRooms([], {}), ["本机没有房间（/xmuse room new <名> 开一个）"])
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

test("formatDone 结果标签/改判/未核实/分享/路由", () => {
  assert.deepEqual(formatDone({ kind: "done", outcome: "completed" }), ["结果: completed"])
  assert.deepEqual(
    formatDone({ kind: "done", outcome: "needs_alignment", outcome_by: "hub", outcome_reason: "declares question" }),
    ["结果: needs_alignment（hub 改判: declares question）"],
  )
  assert.deepEqual(
    formatDone({ kind: "done", outcome: "blocked", evidence_status: "unverified", evidence_problems: ["no such test"] }),
    ["结果: blocked", "未核实: no such test"],
  )
  assert.deepEqual(formatDone({ kind: "message", shared_from: { member: "e1", message_id: 5 } }), ["分享自 e1"])
  assert.deepEqual(
    formatDone({ kind: "question", routed_to: ["e1", "e2"], route_reason: "e1: drawer" }),
    ["已路由给 e1, e2（e1: drawer）"],
  )
  assert.deepEqual(formatDone({ kind: "message", text: "hi" }), [])
})

test("formatHostWait 等谁/压住/倒计时", () => {
  assert.deepEqual(formatHostWait(null), [])
  assert.deepEqual(formatHostWait({ waiting_on: [], results_held: 0, wake_at: null }, 1000),
    ["主控没在等谁", "压住结果 0 条", "自动唤醒: 无"])
  assert.deepEqual(
    formatHostWait({ waiting_on: [{ member: "e1", handoff_id: 7, since: 900 }], results_held: 2, wake_at: 1120 }, 1000),
    ["主控在等: e1", "压住结果 2 条", "自动唤醒: 还剩约 120 秒"])
})
