// Pure registry helpers (no `$`, no node:fs): parse the local hubs.json,
// match a room, resolve the registry dir. The mod reads files through $.fs;
// unit tests feed strings directly. sidebar.key handling: read it in the
// plugin process, send it as x-xmuse-sidebar, never render or log it.

export type RegistryEntry = {
  room_id: string
  name: string
  dir: string
  url: string
  host: string | null
  pid: number
  started_at: number
}

// Same comparison as the hub: Windows and /mnt/c spellings are one directory.
export function normDir(s: string): string {
  s = String(s)
  const m = s.match(/^\/mnt\/([a-z])\/(.*)$/i)
  if (m) s = `${m[1]}:\\${m[2].replace(/\//g, '\\')}`
  if (/^[A-Za-z]:|^\\\\/.test(s)) return s.replace(/\//g, '\\').replace(/\\+$/, '').toLowerCase()
  return s.replace(/\/+$/, '')
}

// Directory rule from hub/src/xmuse/registry.py (convention 8.1).
export function registryDirFrom(
  env: Record<string, string | undefined>,
  platform: string,
  home: string,
): string {
  if (env.XMUSE_REGISTRY_DIR) return env.XMUSE_REGISTRY_DIR
  if (platform === 'win32') {
    const base = env.LOCALAPPDATA || (home ? home + '\\AppData\\Local' : '')
    return base ? base + '\\xmuse' : ''
  }
  const base = env.XDG_STATE_HOME || (home ? home + '/.local/state' : '')
  return base ? base + '/xmuse' : ''
}

function validEntry(e: unknown): e is RegistryEntry {
  if (!e || typeof e !== 'object') return false
  const x = e as Record<string, unknown>
  return typeof x.room_id === 'string' && typeof x.url === 'string' && Number.isInteger(x.pid)
}

// Parse hubs.json text; keep only entries whose pid is alive.
export function parseHubs(text: string, isAlive: (pid: number) => boolean): RegistryEntry[] {
  let data: unknown
  try {
    data = JSON.parse(text)
  } catch {
    return []
  }
  const list = data && typeof data === 'object' && Array.isArray((data as { hubs?: unknown }).hubs)
    ? (data as { hubs: unknown[] }).hubs
    : []
  return list.filter(validEntry).filter(e => {
    try {
      return isAlive(e.pid)
    } catch {
      return false
    }
  })
}

// Match one room by room_id, name, or dir. Room wins over name; both given must agree.
export function findRoom(
  entries: RegistryEntry[],
  q: { roomId?: string; name?: string; dir?: string },
): { entry?: RegistryEntry; error?: string } {
  if (!q.roomId && !q.name && !q.dir) return { error: 'need room_id, name or dir' }
  if (q.roomId) {
    const hit = entries.find(e => e.room_id === q.roomId)
    if (!hit) return { error: `unknown room ${q.roomId}` }
    if (q.dir && hit.dir && normDir(hit.dir) !== normDir(q.dir)) return { error: 'dir 与 room_id 对不上' }
    return { entry: hit }
  }
  if (q.name) {
    const hits = entries.filter(e => e.name === q.name)
    if (hits.length === 1) return { entry: hits[0] }
    if (hits.length > 1) return { error: `叫 ${q.name} 的房间有 ${hits.length} 个，用 room_id 指明：${hits.map(h => h.room_id).join('、')}` }
  }
  if (q.dir) {
    const hit = entries.find(e => e.dir && normDir(e.dir) === normDir(q.dir))
    if (hit) return { entry: hit }
    return { error: entries.length ? `没有服务 ${q.dir} 的房间` : '本机没有登记的房间' }
  }
  return { error: `没有叫 ${q.name} 的房间` }
}

// Only loopback hub urls, like the /xmuse hub command and the dsh drawer.
export function isLoopbackUrl(url: string): boolean {
  let u: URL
  try {
    u = new URL(url)
  } catch {
    return false
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return false
  const h = u.hostname.replace(/^\[(.*)\]$/, '$1')
  return h === 'localhost' || h === '::1' || /^127\.\d+\.\d+\.\d+$/.test(h)
}

// sidebar.key shape (32 random bytes, hex). Anything else is treated as missing.
export function isKeyShape(k: string): boolean {
  return /^[0-9a-f]{64}$/.test(k)
}
