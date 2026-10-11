// 对 mock-hub 的端到端：view 长轮询、say/ack/approve/invite、成员令牌隔离。
import { test } from "node:test"
import assert from "node:assert/strict"
import { spawn } from "node:child_process"
import { fileURLToPath } from "node:url"
import path from "node:path"
import { HubClient } from "../lib/hub.mjs"

const PORT = 43992
const B = `http://127.0.0.1:${PORT}`
const MOCK_HUB = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "tools", "mock-hub", "mock-hub.mjs")
let child

test.before(async () => {
  child = spawn(process.execPath, [MOCK_HUB, "--port", String(PORT), "--quiet"], {
    stdio: "ignore",
  })
  for (let i = 0; i < 50; i++) {
    try {
      await fetch(B + "/_mock/state")
      break
    } catch {
      await new Promise((r) => setTimeout(r, 100))
    }
  }
})

test.after(() => child?.kill())

test("rooms -> view -> say -> ack", async () => {
  const boot = new HubClient({ baseUrl: B, fetchFn: fetch })
  const r = await boot.openRoom({ dir: "C:\\x", name: "demo", vendor: "opencode", sessionId: "s-oc-1", memberId: "oc-1" })
  assert.ok(r.member_token && r.operator_token)
  const c = new HubClient({ baseUrl: B, memberToken: r.member_token, operatorToken: r.operator_token, sessionId: "s-oc-1", fetchFn: fetch })
  const v0 = await c.view(0)
  assert.equal(v0.me.id, "oc-1")
  // 邀请一个 dsh 成员并 join
  const inv = await c.invite("dsh", "executor", "worker", "dsh-1")
  assert.ok(inv.code)
  const j = await new HubClient({ baseUrl: B, fetchFn: fetch }).join(inv.code, "dsh", "s-dsh-1", {})
  assert.equal(j.member_id, "dsh-1")
  // dsh 给 oc-1 发 @
  await fetch(B + "/_mock/say", {
    method: "POST",
    body: JSON.stringify({ from: "dsh-1", to: "oc-1", text: "@oc-1 看一下" }),
  })
  const v1 = await c.view(0)
  const last = v1.timeline.at(-1)
  assert.equal(last.for_me, true)
  assert.equal(v1.members.find((m) => m.id === "oc-1").unread, 1)
  // 成员令牌不能 approve
  const ap = await (await fetch(B + "/_mock/approval", { method: "POST", body: JSON.stringify({ member: "dsh-1", summary: "npm i" }) })).json()
  const memberOnly = new HubClient({ baseUrl: B, memberToken: r.member_token, sessionId: "s-oc-1", fetchFn: fetch })
  await assert.rejects(() => memberOnly.act({ act: "approve", id: ap.id, decision: "once" }), /forbidden/)
  await c.approve(ap.id, "once")
  // ack 后未读清零
  await c.ack([last.id])
  const v2 = await c.view(0)
  assert.equal(v2.members.find((m) => m.id === "oc-1").unread, 0)
})

test("长轮询超时 204 与写入唤醒", async () => {
  const st = await (await fetch(B + "/_mock/state")).json()
  const tok = [...(st ? [] : [])]
  // 用一个新房间状态取 token：直接读 view 需要 token，先开第二个 hub？改用现有 token 流程：
  // 这里只验证 204 超时：随便用上面建好的房间 token（从 state 无法拿 token，改走 _mock/invite + join 拿新成员）
  const inv = await (await fetch(B + "/_mock/invite", { method: "POST", body: JSON.stringify({ vendor: "opencode", role: "executor", description: "t", name: "oc-poll" }) })).json()
  const j = await (await fetch(B + "/v1/join", { method: "POST", body: JSON.stringify({ code: inv.code, vendor: "opencode", session_id: "s-poll", client_info: {} }) })).json()
  const c = new HubClient({ baseUrl: B, memberToken: j.member_token, operatorToken: j.operator_token, sessionId: "s-poll", fetchFn: fetch })
  const v = await c.view(0)
  const waiting = c.view(v.version, 3)
  const timeout = await c.view(v.version, 1)
  assert.ok(timeout.timeout)
  await fetch(B + "/_mock/say", { method: "POST", body: JSON.stringify({ from: "dsh-1", to: "#room", text: "hello" }) })
  const woken = await waiting
  assert.ok(!woken.timeout && woken.version > v.version)
  assert.ok(tok !== undefined)
})
