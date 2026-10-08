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
    return { toast: REPAIR_TOAST, clearGrant: true, refetch: false };
  }
  return { toast: failureToast(status), clearGrant: false, refetch: false };
}

export const REPAIR_TOAST = "授权已失效，请在终端运行 xmuse-workroom pair 重新配对";

export function failureToast(status: number): string {
  if (status === 0) return "操作失败（网络错误）";
  return "操作失败（" + String(status) + "）";
}

// main_window_control_v1 §5: a write command runs only from the person's
// own Enter at the prompt. Every other origin, a missing one and
// "unclassified" are refused before any request.
export function isHumanOrigin(origin: unknown): boolean {
  if (typeof origin !== "object" || origin === null) return false;
  return (origin as Record<string, unknown>)["kind"] === "composer";
}

export const ORIGIN_REFUSED = "xmuse: 写操作只接受你在输入框里亲自输入的 /xmuse 命令";

const OWNER_KINDS = ["claude", "opencode", "antigravity"];
const LEAD_KINDS = ["claude", "opencode", "antigravity", "codex"];

export type NewRoomArgs = {
  title: string;
  lead: string;
  owners: string[];
  reviewer: string | null;
  review: boolean;
};

export const NEW_USAGE =
  "用法: /xmuse new <标题> [--owners opencode,claude] [--lead opencode] [--reviewer claude] [--no-review]";

// `/xmuse new` arguments (after the word "new"). Flags take one value, except
// --no-review; everything else is the title. Defaults: lead opencode, two
// OpenCode owners, cross-family review on (the Human reviews when no other
// family is in the Room).
export function parseNewArgs(rest: string): { ok: true; value: NewRoomArgs } | { ok: false; hint: string } {
  const words = rest.split(/\s+/).filter((w) => w !== "");
  const titleWords: string[] = [];
  let lead = "opencode";
  let owners = ["opencode", "opencode"];
  let reviewer: string | null = null;
  let review = true;
  for (let i = 0; i < words.length; i++) {
    const w = words[i] ?? "";
    if (w === "--no-review") {
      review = false;
      continue;
    }
    if (w === "--owners" || w === "--lead" || w === "--reviewer") {
      const value = words[i + 1];
      if (value === undefined) return { ok: false, hint: NEW_USAGE };
      i++;
      if (w === "--owners") owners = value.split(",").filter((k) => k !== "");
      else if (w === "--lead") lead = value;
      else reviewer = value;
      continue;
    }
    if (w.startsWith("--")) return { ok: false, hint: NEW_USAGE };
    titleWords.push(w);
  }
  const title = titleWords.join(" ").trim();
  if (title === "" || title.length > 200) return { ok: false, hint: NEW_USAGE };
  if (owners.length < 1 || owners.length > 6 || owners.some((k) => !OWNER_KINDS.includes(k))) {
    return { ok: false, hint: "owner 只能是 claude/opencode/antigravity，1 到 6 个" };
  }
  if (!LEAD_KINDS.includes(lead)) return { ok: false, hint: "lead 只能是 claude/opencode/antigravity/codex" };
  if (reviewer !== null && !LEAD_KINDS.includes(reviewer)) {
    return { ok: false, hint: "reviewer 只能是 claude/opencode/antigravity/codex" };
  }
  if (reviewer !== null && !review) return { ok: false, hint: "--reviewer 和 --no-review 不能同时用" };
  return { ok: true, value: { title, lead, owners, reviewer, review } };
}

export const SAY_USAGE = "用法: /xmuse say [@lead|@owner-1 ...] <消息>";

export function parseSayArgs(rest: string): { ok: true; message: string } | { ok: false; hint: string } {
  const message = rest.trim();
  if (message === "" || message.length > 32768) return { ok: false, hint: SAY_USAGE };
  return { ok: true, message };
}

// Fixed words for a refused write; reason codes are mapped, never echoed.
export function writeFailureText(status: number, code: string | null): string {
  if (status === 401) return REPAIR_TOAST;
  if (status === 403) return "授权不包含这个操作，请重新配对（xmuse-workroom pair）";
  if (status === 404) return "这个房间不在授权范围内";
  if (status === 429) return "操作太频繁，请稍后再试";
  if (status === 409 && code === "plugin_grant_room_limit") return "授权的房间数已满，请重新配对";
  if (status === 422 && code === "room_provider_unavailable") return "所选 agent 当前不可用";
  if (status === 422) return "请求不合法";
  return failureToast(status);
}

export type ReviewDecision = "endorse" | "object";

export function mapReviewOutcome(status: number, detailCode: string | null, decision: ReviewDecision): DecisionOutcome {
  if (status === 200) {
    return { toast: decision === "endorse" ? "已认可复核" : "已提出反对，owner 将返工", clearGrant: false, refetch: true };
  }
  if (status === 409 && detailCode === "plugin_review_not_human") {
    return { toast: "这个复核已不需要你决定，已刷新", clearGrant: false, refetch: true };
  }
  if (status === 409 && detailCode === "room_board_review_digest_mismatch") {
    return { toast: "复核材料已变化，请重新查看", clearGrant: false, refetch: true };
  }
  if (status === 409 && detailCode === "room_board_review_material_incomplete") {
    return { toast: "材料不完整，不能认可", clearGrant: false, refetch: false };
  }
  if (status === 401) return { toast: REPAIR_TOAST, clearGrant: true, refetch: false };
  return { toast: failureToast(status), clearGrant: false, refetch: false };
}
