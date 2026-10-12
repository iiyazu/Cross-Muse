import { test } from "node:test"
import assert from "node:assert/strict"
import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { registryDir, readHubs, readCredential, fetchRoomInfo, isLoopback } from "../lib/registry.mjs"
import { HubClient } from "../lib/hub.mjs"

const CRED = "sidebar" + "." + "key" // 登记目录里的凭据文件名（只拼给 fs 用，不打印）

test("registryDir：显式目录优先", () => {
  assert.equal(registryDir({ XMUSE_REGISTRY_DIR: "/tmp/reg" }, "linux"), "/tmp/reg")
})

test("registryDir：XDG，否则 HOME 回退", () => {
  assert.equal(registryDir({ XDG_STATE_HOME: "/tmp/xdg", HOME: "/h" }, "linux"), "/tmp/xdg/xmuse")
  assert.equal(registryDir({ HOME: "/h" }, "linux"), "/h/.local/state/xmuse")
})

test("registryDir：win32 用 LOCALAPPDATA", () => {
  assert.equal(registryDir({ LOCALAPPDATA: "C:\\A", HOME: "/h" }, "win32"), "C:\\A/xmuse")
  assert.equal(registryDir({ HOME: "/h" }, "win32"), "/h/AppData/Local/xmuse")
})

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "xmuse-reg-"))
}

test("readHubs：只留活着的 pid，坏文件返回 []", () => {
  const d = tmp()
  fs.writeFileSync(path.join(d, "hubs.json"), JSON.stringify({ hubs: [
    { room_id: "r-1", name: "a", pid: process.pid },
    { room_id: "r-2", name: "b", pid: 2147483647 },
    { room_id: "r-3", name: "c", pid: 0 },
    { room_id: "r-4", name: "d" },
  ] }))
  assert.deepEqual(readHubs(d).map((e) => e.room_id), ["r-1"])
  assert.deepEqual(readHubs(tmp()), [])
  const d2 = tmp()
  fs.writeFileSync(path.join(d2, "hubs.json"), "{broken")
  assert.deepEqual(readHubs(d2), [])
})

test("readCredential：只认 64 位十六进制", () => {
  const d = tmp()
  const good = "ab".repeat(32)
  fs.writeFileSync(path.join(d, CRED), good + "\n")
  assert.equal(readCredential(d), good)
  const d2 = tmp()
  fs.writeFileSync(path.join(d2, CRED), "not-a-key")
  assert.equal(readCredential(d2), "")
  assert.equal(readCredential(tmp()), "")
})

test("fetchRoomInfo：带凭据头，失败返回 null", async () => {
  let seen = null
  const fake = async (url, opts) => {
    seen = { url, headers: opts.headers }
    return { status: 200, json: async () => ({ room: { id: "r-1" }, members: [] }) }
  }
  const out = await fetchRoomInfo(fake, "http://127.0.0.1:9/", "k123")
  assert.equal(out.room.id, "r-1")
  assert.equal(seen.headers["x-xmuse-sidebar"], "k123")
  assert.ok(seen.url.endsWith("/v1/rooms"))
  const bad = async () => ({ status: 401, json: async () => ({}) })
  assert.equal(await fetchRoomInfo(bad, "http://x", "k"), null)
  const boom = async () => { throw new Error("down") }
  assert.equal(await fetchRoomInfo(boom, "http://x", "k", 10), null)
})

test("the sidebar credential goes to loopback hubs only (contract 8.1)", async () => {
  for (const u of ["http://127.0.0.1:43117", "http://localhost:1", "http://[::1]:2"]) assert.equal(isLoopback(u), true, u)
  for (const u of ["http://10.0.0.5:43117", "http://example.com", "http://127.0.0.1.evil.com:1", "nonsense"]) assert.equal(isLoopback(u), false, u)
  let called = false
  const fetchFn = async () => { called = true; return { status: 200, json: async () => ({}) } }
  assert.equal(await fetchRoomInfo(fetchFn, "http://10.0.0.5:43117", "a".repeat(64)), null)
  assert.equal(called, false)
  assert.equal(new HubClient({ baseUrl: "http://10.0.0.5:1", sidebarKey: "k" }).sidebarKey, "")
  assert.equal(new HubClient({ baseUrl: "http://127.0.0.1:1", sidebarKey: "k" }).sidebarKey, "k")
})
