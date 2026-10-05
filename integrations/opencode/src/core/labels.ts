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
// code: callers keep showing those codes as before. Integration
// room-level items share the same table: the operator error toasts,
// the lead gate failure and the owner conflict stay on their existing
// toast/attention paths (no new toast for per-module conflicts).
export function reviewAttentionLabel(reason: unknown): string | null {
  if (reason === "board_attention_review_operator_pending") return "待你复核";
  if (reason === "board_attention_review_objected") return "复核被驳回待返工";
  if (reason === "board_attention_integration_error") return "集成异常（宿主自动重试）";
  if (reason === "board_attention_integration_conflict") return "集成冲突待处理";
  if (reason === "board_attention_integration_gate_failed") return "集成门禁失败";
  return null;
}

// Fixed words for the board_integration_* reason codes (§9). Copied
// exactly from frontend/src/lib/board-labels.ts: the hosts show codes
// through these labels only, never raw gate or path text.
const INTEGRATION_REASON_LABELS: { [code: string]: string } = {
  board_integration_conflict: "集成冲突",
  board_integration_gate_failed: "集成门禁未通过",
  board_integration_waiting_for_dependency: "等待依赖集成",
  board_integration_would_drop_accepted: "集成会丢失已验收代码，已停止",
  board_integration_attempts_exhausted: "集成多次失败",
};

export function integrationReasonLabel(reason: unknown): string | null {
  if (typeof reason === "string" && INTEGRATION_REASON_LABELS[reason] !== undefined)
    return INTEGRATION_REASON_LABELS[reason];
  return null;
}

// Room-level job word (§3.11, §7.1): latest status, or summary status.
// integrated and null/empty show nothing.
export function integrationJobWord(status: unknown): string {
  if (status === null || status === undefined || status === "" || status === "integrated") return "";
  if (status === "pending") return "排队集成";
  if (status === "running") return "集成中";
  if (status === "conflicted") return "集成冲突";
  if (status === "gate_failed") return "集成门禁失败";
  if (status === "error") return "集成异常";
  return "?" + safe(status, 32);
}

// 8 hex of the green head commit. Empty when there is no head.
export function shortGreenHead(commit: unknown): string {
  if (typeof commit !== "string" || commit === "") return "";
  return safe(commit, 64).slice(0, 8);
}

export type ModuleIntegrationInput = {
  status: unknown;
  conflict_path_count?: unknown;
  verification_id?: unknown;
  integrated_verification_id?: unknown;
};

// One fixed-word module integration part (§3.11). Empty when integrations
// are off, when the status is "none"/missing, or when the status is
// unknown-but-empty. Counts and ids only: never a path, never gate text.
export function integrationModuleWord(
  input: ModuleIntegrationInput | null | undefined,
  integrations: unknown,
): string {
  if (integrations !== 1) return "";
  if (input === null || input === undefined) return "";
  const status = input.status;
  if (status === null || status === undefined || status === "" || status === "none") return "";
  let base = "";
  if (status === "pending") base = "排队集成";
  else if (status === "running") base = "集成中";
  else if (status === "integrated") base = "已集成";
  else if (status === "waiting") base = "等待依赖集成";
  else if (status === "conflicted") {
    const n =
      typeof input.conflict_path_count === "number" && Number.isFinite(input.conflict_path_count)
        ? Math.max(0, Math.floor(input.conflict_path_count))
        : 0;
    base = "集成冲突 " + String(n) + " 路径";
  } else if (status === "gate_failed") base = "门禁失败·嫌疑";
  else if (status === "error") base = "集成异常·自动重试";
  else base = "?" + safe(status, 32);
  const ver = typeof input.verification_id === "string" ? input.verification_id : null;
  const old = typeof input.integrated_verification_id === "string" ? input.integrated_verification_id : null;
  if (old !== null && old !== "" && ver !== null && old !== ver) return base + "·分支为旧版本";
  if ((old === null || old === "") && (status === "conflicted" || status === "gate_failed" || status === "error" || status === "waiting"))
    return base + "·未入分支";
  return base;
}
