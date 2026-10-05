// Pure state machine for the plugin grant flow: pairing code validation,
// expiry, confirm-digest check, and result-to-toast mapping. No engine
// calls, no transport: every output is a fixed structured label plus at most
// a status number. Agent-authored strings never reach these toasts.

const PAIRING_RE = /^[ABCDEFGHJKMNPQRSTVWXYZ23456789]{4}-[ABCDEFGHJKMNPQRSTVWXYZ23456789]{4}$/;
const DIGEST_RE = /^sha256:([0-9a-fA-F]{64})$/;

// Trim and upper-case before matching. Lower-case input from the field is
// accepted; anything outside the grant alphabet is rejected locally.
export function normalizePairingCode(raw: unknown): string {
  return typeof raw === "string" ? raw.trim().toUpperCase() : "";
}

export function pairingHint(): string {
  return "配对码格式不对，应为 XXXX-XXXX（字母数字，不含易混字符）";
}

export function validatePairingCode(raw: unknown): { ok: true; code: string } | { ok: false; hint: string } {
  const code = normalizePairingCode(raw);
  if (PAIRING_RE.test(code)) return { ok: true, code };
  return { ok: false, hint: pairingHint() };
}

// Fail closed: an unparseable timestamp counts as expired.
export function grantExpired(expiresAt: string, nowMs: number): boolean {
  const t = Date.parse(expiresAt);
  if (!Number.isFinite(t)) return true;
  return nowMs >= t;
}

export function grantMinutesLeft(expiresAt: string, nowMs: number): number {
  const t = Date.parse(expiresAt);
  if (!Number.isFinite(t)) return 0;
  return Math.max(0, Math.ceil((t - nowMs) / 60000));
}

export function remainingMmSs(expiresAt: string, nowMs: number): string {
  const t = Date.parse(expiresAt);
  const left = Math.max(0, Math.floor(((Number.isFinite(t) ? t : 0) - nowMs) / 1000));
  const mm = String(Math.floor(left / 60)).padStart(2, "0");
  const ss = String(left % 60).padStart(2, "0");
  return mm + ":" + ss;
}

export function exchangeToast(expiresAt: string, nowMs: number): string {
  return "已授权，" + String(Math.max(1, grantMinutesLeft(expiresAt, nowMs))) + " 分钟内有效";
}

// The first 6 hex characters after `sha256:`, lower-cased, or null when the
// stored digest is malformed (then nothing can confirm it).
export function confirmPrefixOf(digest: string): string | null {
  const m = DIGEST_RE.exec(digest);
  if (m === null || m[1] === undefined) return null;
  return m[1].slice(0, 6).toLowerCase();
}

export function confirmHint(): string {
  return "摘要不匹配，请重新输入前 6 位";
}

export function checkConfirmInput(digest: string, raw: unknown): { ok: true } | { ok: false; hint: string } {
  const prefix = confirmPrefixOf(digest);
  const given = typeof raw === "string" ? raw.trim().toLowerCase() : "";
  if (prefix !== null && given !== "" && given === prefix) return { ok: true };
  return { ok: false, hint: confirmHint() };
}

export type SplitDecision = "approve" | "reject";

export type DecisionOutcome = {
  toast: string;
  clearGrant: boolean;
  refetch: boolean;
};

// Maps a decide response to a fixed toast. Only the status number may
// appear in the generic arm; reason codes stay untranslated.
export function mapDecisionOutcome(
  status: number,
  detailCode: string | null,
  decision: SplitDecision,
): DecisionOutcome {
  if (status === 200) {
    return { toast: decision === "approve" ? "已批准拆分" : "已拒绝拆分", clearGrant: false, refetch: true };
  }
  if (
    status === 409 &&
    (detailCode === "room_board_split_decided" || detailCode === "room_board_split_not_proposed")
  ) {
    return { toast: "拆分已不能决定，已刷新", clearGrant: false, refetch: true };
  }
  if (status === 409 && detailCode === "room_board_split_digest_mismatch") {
    return { toast: "拆分已变化，请重新确认", clearGrant: false, refetch: true };
  }
  if (status === 401) {
    return { toast: "授权已失效，请在 Web 重新授权", clearGrant: true, refetch: false };
  }
  return { toast: failureToast(status), clearGrant: false, refetch: false };
}

export function failureToast(status: number): string {
  if (status === 0) return "操作失败（网络错误）";
  return "操作失败（" + String(status) + "）";
}
