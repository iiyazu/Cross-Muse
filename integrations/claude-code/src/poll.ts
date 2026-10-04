// Pure binding helpers. No engine calls here: every $ use lives in the
// hooks module (hooks/register.tsx), so this file only computes.

import { sortRoomsByUpdated, type RoomEntry } from "./api";
import { safe } from "./text";

export function bindingKey(cwd: string): string {
  return "binding:" + cwd;
}

export function backoffMs(failCount: number, pollMs: number): number {
  const doubled = pollMs * Math.pow(2, Math.max(0, failCount));
  return Math.min(doubled, 60000);
}

export function parseAttachArg(args: string): string | null {
  const words = args.trim().split(/\s+/).filter((w) => w !== "");
  if (words.length === 0 || words[0] !== "attach") return null;
  const id = words[1] ?? "";
  return id === "" ? null : id;
}

export type AttachPick =
  | { ok: true; conversation_id: string }
  | { ok: false; error: string };

// /xmuse attach [<id or unique prefix>]. No argument: most recently
// updated room. Never creates or modifies rooms.
export function pickAttachTarget(rooms: RoomEntry[], args: string): AttachPick {
  if (rooms.length === 0) return { ok: false, error: "xmuse 绑定失败: 暂无房间" };
  const want = parseAttachArg(args);
  if (want === null) {
    return { ok: true, conversation_id: sortRoomsByUpdated(rooms)[0].conversation_id };
  }
  const id = safe(want, 128);
  const matches = rooms.filter((r) => r.conversation_id === id || r.conversation_id.startsWith(id));
  if (matches.length === 0) return { ok: false, error: "xmuse 绑定失败: 未找到房间" };
  if (matches.length > 1) return { ok: false, error: "xmuse 绑定失败: 前缀匹配到多个房间" };
  return { ok: true, conversation_id: matches[0].conversation_id };
}
