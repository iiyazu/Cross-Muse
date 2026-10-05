// Fixed labels for module states. done_claimed and verified are
// unmistakable everywhere: glyph plus Chinese, never colour only.
// Unknown state codes are shown as ?<value> (contract compatibility).

import { safe } from "./text";

const BADGES: { [state: string]: string } = {
  verified: "✓ 已验证",
  done_claimed: "◌ 自称完成·未验证",
  verification_failed: "✗",
  verifying: "…",
  waiting_for_provider: "⧗",
  verification_error: "‼",
};

export function stateBadge(state: unknown): string {
  if (typeof state === "string" && BADGES[state] !== undefined) return BADGES[state];
  return "?" + safe(state, 48);
}

// Compact glyphs for the one-line status row, in fixed order.
export const STATUS_GROUPS: { state: string; glyph: string }[] = [
  { state: "verified", glyph: "✓" },
  { state: "done_claimed", glyph: "◌" },
  { state: "verifying", glyph: "…" },
  { state: "waiting_for_provider", glyph: "⧗" },
  { state: "verification_failed", glyph: "✗" },
  { state: "verification_error", glyph: "‼" },
];

export function isKnownState(state: unknown): boolean {
  if (typeof state !== "string") return false;
  if (BADGES[state] !== undefined) return true;
  return (
    state === "assigned" ||
    state === "claimed" ||
    state === "working" ||
    state === "blocked" ||
    state === "ready_for_review"
  );
}

export function displayState(state: unknown): string {
  if (isKnownState(state)) {
    const badge = typeof state === "string" ? BADGES[state] : undefined;
    if (badge !== undefined) return badge;
    return safe(state, 48);
  }
  return "?" + safe(state, 48);
}

// The one completion mark (§4.4): shown only when accepted is true, never
// for a merely verified module.
export const ACCEPTED_BADGE = "✓ 已验收";

// Fixed one-word review part for a module row. Empty when there is no
// review (status "none"). An unknown status is shown as ?value, never
// hidden. Counts only: no summary or finding text is ever rendered.
export function reviewStatusWord(status: unknown, reviewerKind: unknown): string {
  if (status === "none") return "";
  if (status === "pending") return reviewerKind === "operator" ? "待你复核" : "待复核";
  if (status === "endorsed") return "已背书";
  if (status === "objected") return "已驳回";
  return "?" + safe(status, 48);
}

export function findingsPart(blocker: number, major: number, minor: number): string {
  const b = Math.max(0, Math.floor(blocker));
  const mj = Math.max(0, Math.floor(major));
  const mn = Math.max(0, Math.floor(minor));
  if (b + mj + mn === 0) return "";
  return "阻塞 " + String(b) + " 主要 " + String(mj) + " 次要 " + String(mn);
}

// Fixed labels for review attention rows. Null for every other reason
// code: callers keep showing those codes as before.
export function reviewAttentionLabel(reason: unknown): string | null {
  if (reason === "board_attention_review_operator_pending") return "待你复核";
  if (reason === "board_attention_review_objected") return "复核被驳回待返工";
  return null;
}
