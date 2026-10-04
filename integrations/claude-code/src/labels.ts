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
