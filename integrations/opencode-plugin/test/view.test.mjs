import { test } from "node:test"
import assert from "node:assert/strict"
import { parseSlash, dedupeTimeline, newMentions, formatSidebar, buildSayArgs, memberLine } from "../lib/view.mjs"

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
