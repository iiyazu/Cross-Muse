// v0.1 本机入口与新增 act：对带登记目录的 mock-hub（端口 0 = 随机）。
import { test } from "node:test"
import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"
import { HubClient } from "../lib/hub.mjs"

const MOCK_HUB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "tools", "mock-hub", "mock-hub.mjs")
const CRED = "sidebar" + "." + "key"
const DIR = "/tmp/x-sandbox-oc"

let child, B, cred
const keyHeader = () => ({ "x-xmuse-sidebar": cred })

test.before(async () => {
  const regDir = fs.mkdtempSync(path.join(os.tmpdir(), "xmuse-hubreg-"))
  child = spawn(process.execPath, [MOCK_HUB, "--port", "0", "--registry-dir", regDir, "--quiet"], {
    stdio: ["ignore", "pipe", "ignore"],
  })
  let out = ""
  const port = await new Promise((resolve, reject) => {
    const to = setTimeout(() => reject(new Error("mock-hub 不启动")), 15000)
    child.stdout.on("data", (c) => {
      out += String(c)
      const m = out.match(/127\.0\.0\.1:(\d+)/)
      if (m) { clearTimeout(to); resolve(Number(m[1])) }
    })
    child.on("exit", () => reject(new Error("mock-hub 退出: " + out)))
  })
  B = `http://127.0.0.1:${port}`
  cred = fs.readFileSync(path.join(regDir, CRED), "utf8").trim()
  assert.match(cred, /^[0-9a-f]{64}$/)
  for (let i = 0; i < 50; i++) {
    try { await fetch(B + "/_mock/state"); break } catch { await new Promise((r) => setTimeout(r, 100)) }
  }
})

test.after(() => child?.kill())

const raw = (method, p, body, headers = {}) => fetch(B + p, {
  method, headers: { "content-type": "application/json", ...headers },
  body: body === undefined ? undefined : JSON.stringify(body),
}).then(async (r) => ({ s: r.status, b: r.status === 204 ? null : await r.json() }))

test("rooms 系列要凭据头", async () => {
  let r = await raw("GET", "/v1/rooms")
  assert.equal(r.s, 401); assert.equal(r.b.error, "bad_sidebar_key")
  r = await raw("GET", "/v1/rooms", undefined, keyHeader())
  assert.equal(r.s, 200); assert.equal(r.b.room, null)
  r = await raw("POST", "/v1/rooms", { dir: DIR, name: "demo", vendor: "opencode", session_id: "s1" })
  assert.equal(r.s, 401)
  r = await raw("POST", "/v1/rooms", { dir: DIR, name: "demo", vendor: "opencode", session_id: "s1" }, keyHeader())
  assert.equal(r.s, 200)
  const op = r.b.operator_token, mt = r.b.member_token
  r = await raw("GET", "/v1/rooms", undefined, keyHeader())
  assert.equal(r.s, 200)
  assert.equal(r.b.room.name, "demo")
  assert.deepEqual(r.b.members.map((m) => m.id), ["opencode"])
  // 成员令牌调本机入口一律 403
  r = await raw("GET", "/v1/rooms", undefined, { authorization: "Bearer " + mt, ...keyHeader() })
  assert.equal(r.s, 403); assert.equal(r.b.error, "member_forbidden")
})

test("joinLocal：一键加入与错误码", async () => {
  const c = new HubClient({ baseUrl: B, sidebarKey: cred, fetchFn: fetch })
  const j = await c.joinLocal({ dir: DIR, vendor: "opencode", sessionId: "s2" })
  assert.ok(j.member_id.startsWith("opencode") && j.operator_token)
  assert.equal(j.room.name, "demo")
  await assert.rejects(c.joinLocal({ dir: "/nope", vendor: "opencode", sessionId: "s3" }), /wrong_dir/)
  await assert.rejects(c.joinLocal({ vendor: "opencode", sessionId: "s3" }), /bad_request/)
  const noKey = new HubClient({ baseUrl: B, fetchFn: fetch })
  await assert.rejects(noKey.joinLocal({ dir: DIR, vendor: "opencode", sessionId: "s4" }), /bad_sidebar_key/)
})

test("member_add / member_edit（操作令牌；成员令牌 403）", async () => {
  const c = new HubClient({ baseUrl: B, sidebarKey: cred, fetchFn: fetch })
  const j = await c.joinLocal({ dir: DIR, vendor: "opencode", sessionId: "s-op" })
  const op = new HubClient({ baseUrl: B, operatorToken: j.operator_token, sidebarKey: cred, fetchFn: fetch })
  const mem = new HubClient({ baseUrl: B, memberToken: j.member_token, sessionId: "s-op", sidebarKey: cred, fetchFn: fetch })
  await assert.rejects(mem.act({ act: "member_add", vendor: "dsh" }), /operator_only/)
  await assert.rejects(op.memberAdd({ vendor: "bogus" }), /bad_vendor/)
  const a = await op.memberAdd({ vendor: "dsh", role: "executor", description: "drawer", name: "dsh-9" })
  assert.equal(a.member_id, "dsh-9")
  await assert.rejects(op.memberEdit("dsh-9", {}), /bad_request/)
  assert.deepEqual(await op.memberEdit("dsh-9", { description: "drawer v2" }), { ok: true })
  const info = await c.roomsInfo()
  assert.equal(info.members.find((m) => m.id === "dsh-9").role, "executor")
})

test("成员操作：transfer_host / pause / resume / remove", async () => {
  const c = new HubClient({ baseUrl: B, sidebarKey: cred, fetchFn: fetch })
  const j = await c.joinLocal({ dir: DIR, vendor: "opencode", sessionId: "s-adm" })
  const op = new HubClient({ baseUrl: B, operatorToken: j.operator_token, sidebarKey: cred, fetchFn: fetch })
  await op.memberAdd({ vendor: "dsh", name: "dsh-x" })
  assert.deepEqual(await op.pauseMember("dsh-x"), { ok: true })
  assert.deepEqual(await op.resumeMember("dsh-x"), { ok: true })
  assert.deepEqual(await op.transferHost("dsh-x"), { ok: true })
  assert.equal((await c.roomsInfo()).room.host, "dsh-x")
  assert.deepEqual(await op.transferHost(j.member_id), { ok: true })
  assert.deepEqual(await op.removeMember("dsh-x"), { ok: true })
  assert.ok(!(await c.roomsInfo()).members.some((m) => m.id === "dsh-x"))
})

test("thread_new / thread_add / thread_remove 与错误码", async () => {
  const c = new HubClient({ baseUrl: B, sidebarKey: cred, fetchFn: fetch })
  const j = await c.joinLocal({ dir: DIR, vendor: "opencode", sessionId: "s-th" })
  const op = new HubClient({ baseUrl: B, operatorToken: j.operator_token, sidebarKey: cred, fetchFn: fetch })
  await op.memberAdd({ vendor: "dsh", name: "dsh-t" })
  await op.say("#pub", "公开群先建出来")
  await assert.rejects(op.threadAdd("#pub", "dsh-t"), /public_thread/)
  const t = await op.threadNew({ id: "#g1", members: ["dsh-t"], title: "G1" })
  assert.equal(t.thread, "#g1")
  await assert.rejects(op.threadNew({ id: "#g1", members: [] }), /thread_exists/)
  assert.deepEqual(await op.threadAdd("#g1", j.member_id), { ok: true })
  await assert.rejects(op.threadRemove("#g1", "nobody"), /not_in_thread/)
  assert.deepEqual(await op.threadRemove("#g1", "dsh-t"), { ok: true })
  const v = await op.view(0)
  const g1 = v.threads.find((t) => t.id === "#g1")
  assert.equal(g1.private, true)
})

test("wake_host 与 share_mark 参数校验", async () => {
  const c = new HubClient({ baseUrl: B, sidebarKey: cred, fetchFn: fetch })
  const j = await c.joinLocal({ dir: DIR, vendor: "opencode", sessionId: "s-wh" })
  const op = new HubClient({ baseUrl: B, operatorToken: j.operator_token, sidebarKey: cred, fetchFn: fetch })
  const w = await op.wakeHost()
  assert.equal(w.ok, true)
  await assert.rejects(op.shareMark("nan"), /invalid_arguments/)
})

test("第2步形状：done 标签/host_wait/share 审批走通视图", async () => {
  const c = new HubClient({ baseUrl: B, sidebarKey: cred, fetchFn: fetch })
  const j = await c.joinLocal({ dir: DIR, vendor: "opencode", sessionId: "s-s2", name: "oc-s2" })
  const op = new HubClient({ baseUrl: B, operatorToken: j.operator_token, sidebarKey: cred, fetchFn: fetch })
  const mock = (p, body) => fetch(B + p, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }).then((r) => r.json())
  // done：改判标签 / 未核实（证据规则优先于 declares 改判，分两条测）
  const d1 = await mock("/_mock/done", { from: "oc-s2", summary: "做完", outcome: "completed", declares: [{ kind: "question", scope: "room" }] })
  assert.equal(d1.outcome, "needs_alignment")
  assert.equal(d1.outcome_by, "hub")
  const d2 = await mock("/_mock/done", { from: "oc-s2", summary: "有证据", evidence_status: "unverified", evidence_problems: ["no such test"] })
  assert.equal(d2.outcome, "blocked")
  // host_wait 注入口
  const hw = await mock("/_mock/host_wait", { waiting_on: [{ member: "oc-s2", handoff_id: 1, since: 100 }], results_held: 2, wake_at: 9999999999 })
  assert.equal(hw.results_held, 2)
  // 用户私信 -> 分享审批 -> 批准
  const dm = await mock("/_mock/send", { from: "human", to: "oc-s2", text: "密钥是 hunter2，请转告" })
  const sh = await mock("/_mock/share", { member: "oc-s2", message_id: dm.id, to: "#room", why: "转告" })
  assert.ok(sh.approval.startsWith("share:"))
  const v = await op.view(0)
  assert.deepEqual(v.host_wait.waiting_on.map((w) => w.member), ["oc-s2"])
  assert.equal(v.host_wait.results_held, 2)
  const done = v.timeline.find((m) => m.kind === "done" && m.outcome === "needs_alignment")
  assert.equal(done.outcome_by, "hub")
  assert.ok(String(done.outcome_reason).includes("question"))
  const blocked = v.timeline.find((m) => m.kind === "done" && m.outcome === "blocked")
  assert.equal(blocked.evidence_status, "unverified")
  assert.deepEqual(blocked.evidence_problems, ["no such test"])
  const share = v.approvals.find((a) => a.kind === "share")
  assert.ok(share && share.detail.excerpt.includes("hunter2"))
  const approved = await op.approve(share.id, "once")
  assert.equal(approved.ok, true)
  assert.equal(approved.status, "delivered")
  const v2 = await op.view(0)
  assert.ok(!v2.approvals.some((a) => a.id === share.id))
  const shared = v2.timeline.find((m) => m.via === "shared")
  assert.deepEqual(shared.shared_from, { member: "oc-s2", message_id: dm.id })
})
