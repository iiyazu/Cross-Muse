// Poll state: one atom the pane subscribes to, plus the status line,
// toast-diff and command/tool text builders. All outputs are structured
// fields only (counts, state codes, module ids, reason codes, short ids).

import type { XmuseAttentionItem, XmuseCache, XmuseSummary } from "../types/index";
import { COUNT_KEYS } from "./api";
import { STATUS_GROUPS } from "./labels";
import { safe, safeId, shortRev, shortRoom } from "./text";

export function attentionKey(a: XmuseAttentionItem): string {
  return safe(a.reason_code, 64) + "|" + safe(a.module_id ?? "", 64) + "|" + safe(a.split_id ?? "", 64);
}

function operatorCount(summary: XmuseSummary): number {
  let n = 0;
  for (const a of summary.attention) if (a.kind === "operator") n += 1;
  return n;
}

// One status line. Examples:
//   "xmuse 离线"  "xmuse 未绑定房间"
//   "看板 3 模块 · ✓1 …1 ✗1 · 待你处理 1"
export function statusText(cache: XmuseCache): string {
  if (cache.offline) return "xmuse 离线";
  if (cache.binding === null) return "xmuse 未绑定房间";
  if (cache.summary === null) return "xmuse " + shortRoom(cache.binding) + " …";
  const s = cache.summary;
  const parts: string[] = [];
  for (const g of STATUS_GROUPS) {
    const n = s.counts[g.state] ?? 0;
    if (n > 0) parts.push(g.glyph + String(n));
  }
  let line = "看板 " + String(s.modules_total) + " 模块";
  if (parts.length > 0) line += " · " + parts.join(" ");
  const op = operatorCount(s);
  if (op > 0) line += " · 待你处理 " + String(op);
  return line;
}

// Compact structured block (<= 8 lines) for /xmuse status and the tool.
export function statusBlock(cache: XmuseCache): string {
  if (cache.offline) return "xmuse 离线";
  if (cache.binding === null) return "xmuse 未绑定房间";
  if (cache.summary === null) return "xmuse " + shortRoom(cache.binding) + " …";
  const s = cache.summary;
  const lines: string[] = [];
  lines.push("xmuse " + shortRoom(s.conversation_id) + " rev " + shortRev(s.revision));
  const parts: string[] = [];
  for (const g of STATUS_GROUPS) {
    const n = s.counts[g.state] ?? 0;
    if (n > 0) parts.push(g.glyph + String(n));
  }
  lines.push("模块 " + String(s.modules_total) + (parts.length > 0 ? " " + parts.join(" ") : ""));
  const op = s.attention.filter((a) => a.kind === "operator").slice(0, 5);
  lines.push("待你处理 " + String(operatorCount(s)));
  for (const a of op) {
    const target = a.module_id !== null ? safeId(a.module_id) : safe(a.split_id ?? "?", 32);
    lines.push("! " + safe(a.reason_code, 64) + " " + target);
  }
  return lines.slice(0, 8).join("\n");
}

export type ToastPlan = { text: string } | null;

// At most one toast per tick (coalesced). No toast on the first successful
// poll (baseline). Fixed labels plus module/split ids only.
export function planToast(prev: XmuseCache, next: XmuseSummary, stateNotes: string[]): ToastPlan {
  if (!prev.baselined || prev.summary === null) return null;
  const items: string[] = [];
  const before = new Set(prev.seenAttention);
  for (const a of next.attention) {
    if (a.kind !== "operator") continue;
    if (!before.has(attentionKey(a))) {
      const target = a.module_id !== null ? safeId(a.module_id) : safe(a.split_id ?? "?", 32);
      items.push("待处理 " + safe(a.reason_code, 64) + " " + target);
    }
  }
  for (const note of stateNotes.slice(0, 3)) items.push(note);
  if (stateNotes.length === 0) {
    // The board is only fetched while the pane is open; the summary counts
    // still show verification outcomes, so toast their growth without ids.
    const was = prev.summary.counts;
    const gained = (state: string): number => (next.counts[state] ?? 0) - (was[state] ?? 0);
    if (gained("verified") > 0) items.push("✓ 新增已验证 " + String(gained("verified")));
    const failed = gained("verification_failed") + gained("verification_error");
    if (failed > 0) items.push("✗ 新增验证失败 " + String(failed));
  }
  return items.length > 0 ? { text: "xmuse: " + items.slice(0, 3).join("; ") } : null;
}

// Module-state transitions are diffed from the board when available;
// the summary path below covers state moves visible in counts.
export function planStateToasts(
  prevStates: { [id: string]: string },
  nextStates: { [id: string]: string },
): string[] {
  const out: string[] = [];
  for (const id of Object.keys(nextStates)) {
    const from = prevStates[id];
    const to = nextStates[id];
    if (from === to) continue;
    if (to === "verified") out.push(safeId(id) + " 已验证");
    else if (to === "verification_failed" || to === "verification_error") out.push(safeId(id) + " 验证失败");
  }
  return out;
}

export function emptyCounts(): { [state: string]: number } {
  const c: { [state: string]: number } = {};
  for (const k of COUNT_KEYS) c[k] = 0;
  return c;
}
