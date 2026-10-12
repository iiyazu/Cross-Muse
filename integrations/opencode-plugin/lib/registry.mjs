// 本机登记表（hubs.json）和侧栏凭据的读取：只在插件进程里用。
// 目录规则照 hub/src/xmuse/registry.py：XMUSE_REGISTRY_DIR，否则按平台默认。
// 凭据只返回给调用者，本模块绝不打印、不记日志。

import fs from "node:fs"
import os from "node:os"
import path from "node:path"

const CRED_FILE = "sidebar.key";

export function registryDir(env = process.env, platform = process.platform) {
  if (env.XMUSE_REGISTRY_DIR) return env.XMUSE_REGISTRY_DIR
  if (platform === "win32") {
    const base = env.LOCALAPPDATA || path.join(env.HOME || os.homedir(), "AppData", "Local")
    return path.join(base, "xmuse")
  }
  const base = env.XDG_STATE_HOME || path.join(env.HOME || os.homedir(), ".local", "state")
  return path.join(base, "xmuse")
}

export function pidAlive(pid, killFn) {
  const kill = killFn || ((p) => process.kill(p, 0))
  if (!Number.isInteger(pid) || pid <= 0) return false
  try {
    kill(pid)
    return true
  } catch (e) {
    return e && e.code === "EPERM" // 有进程但无权发信号：算活着
  }
}

// 登记表里的活着的 hub 条目；文件缺失/损坏返回 []。
export function readHubs(dir, killFn) {
  try {
    const raw = fs.readFileSync(path.join(dir, "hubs.json"), "utf8")
    const data = JSON.parse(raw)
    const list = Array.isArray(data.hubs) ? data.hubs : []
    return list.filter((e) => e && typeof e === "object" && pidAlive(e.pid, killFn))
  } catch {
    return []
  }
}

// 读侧栏凭据并校验形状（64 位十六进制）；不对返回 ""。
export function readCredential(dir) {
  try {
    const v = fs.readFileSync(path.join(dir, CRED_FILE), "utf8").trim()
    return /^[0-9a-f]{64}$/.test(v) ? v : ""
  } catch {
    return ""
  }
}

// 凭据只发给本机回环地址的 hub（约定 8.1）；登记表或环境变量里的其他地址一律不带。
export function isLoopback(url) {
  try {
    const h = new URL(String(url)).hostname.replace(/^\[(.*)\]$/, "$1")
    return h === "localhost" || h === "::1" || /^127\.\d+\.\d+\.\d+$/.test(h)
  } catch {
    return false
  }
}

// 对某 hub 的 GET /v1/rooms（带凭据头）：连不上/鉴权失败/不是回环地址返回 null。
export async function fetchRoomInfo(fetchFn, url, cred, timeoutMs = 3000) {
  if (!isLoopback(url)) return null
  try {
    const ctl = new AbortController()
    const t = setTimeout(() => ctl.abort(), timeoutMs)
    const r = await fetchFn(String(url).replace(/\/$/, "") + "/v1/rooms", {
      headers: { "x-xmuse-sidebar": cred },
      signal: ctl.signal,
    })
    clearTimeout(t)
    if (r.status !== 200) return null
    return await r.json()
  } catch {
    return null
  }
}
