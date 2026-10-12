// 插件自己的令牌存储：只放插件进程读的文件，不进模型上下文、不写工作区。
// 路径：$XDG_STATE_HOME/xmuse-opencode/xmuse.json，否则 ~/.local/share/xmuse-opencode/xmuse.json。
// 文件模式 600。绝不打印令牌。

import fs from "node:fs"
import os from "node:os"
import path from "node:path"
import { isLoopback, readHubs, registryDir } from "./registry.mjs"

export function storePath(env = process.env) {
  const base = env.XDG_STATE_HOME || path.join(env.HOME || os.homedir(), ".local", "share")
  return path.join(base, "xmuse-opencode", "xmuse.json")
}

export function loadStore(env = process.env) {
  try {
    const p = storePath(env)
    const raw = fs.readFileSync(p, "utf8")
    return JSON.parse(raw)
  } catch {
    return {}
  }
}

const normDir = (d) => {
  const p = path.resolve(String(d)).replace(/[\\/]+$/, "")
  return process.platform === "win32" ? p.toLowerCase() : p
}

// 本机登记表里服务当前目录的 hub（约定 8.1）：真 hub 的 hub.json 在它的状态目录里，不在 <cwd>/.xmuse，
// 所以开房间要靠登记表找到它（10-12 实测：不查登记表时 room new 连到默认端口失败）。只认回环地址。
export function registeredHub(env = process.env, cwd = process.cwd()) {
  const here = normDir(cwd)
  const e = readHubs(registryDir(env)).find((h) => h.dir && normDir(h.dir) === here && isLoopback(h.url))
  return e ? String(e.url).replace(/\/$/, "") : ""
}

// 显式传 env 便于测试；默认读进程 env
export function hubBaseUrl(env = process.env, cwd = process.cwd()) {
  if (env.XMUSE_HUB_URL) return String(env.XMUSE_HUB_URL).replace(/\/$/, "")
  const reg = registeredHub(env, cwd)
  if (reg) return reg
  try {
    const s = loadStore(env)
    if (s.hubUrl) return String(s.hubUrl).replace(/\/$/, "")
  } catch {}
  // hub.json 状态目录：XMUSE_STATE_DIR 或 <cwd>/.xmuse
  const dir = env.XMUSE_STATE_DIR || path.join(process.cwd(), ".xmuse")
  try {
    const raw = fs.readFileSync(path.join(dir, "hub.json"), "utf8")
    const j = JSON.parse(raw)
    if (j.port) return `http://127.0.0.1:${Number(j.port)}`
  } catch {}
  return "http://127.0.0.1:43117"
}

export function saveStore(patch, env = process.env) {
  const p = storePath(env)
  fs.mkdirSync(path.dirname(p), { recursive: true })
  let cur = {}
  try {
    cur = JSON.parse(fs.readFileSync(p, "utf8"))
  } catch {}
  const next = { ...cur, ...patch }
  fs.writeFileSync(p, JSON.stringify(next, null, 2), { mode: 0o600 })
  try {
    fs.chmodSync(p, 0o600)
  } catch {}
  return next
}

export function clearStore(env = process.env) {
  try {
    fs.unlinkSync(storePath(env))
  } catch {}
}
