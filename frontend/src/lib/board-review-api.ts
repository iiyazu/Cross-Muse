import {
  chatApiBaseUrl,
  fetchJson,
  XmuseApiError,
  type ApiClientOptions
} from "./api";
import type { AgentText } from "./board-types";
import type {
  BoardFindingsCount,
  BoardReview,
  BoardReviewDecisionInput,
  BoardReviewDetail,
  BoardReviewEligible,
  BoardReviewEscalation,
  BoardReviewFinding,
  BoardReviewMaterial,
  BoardReviewRuleInputs,
  BoardReviewVerdict
} from "./board-review-types";

const REVIEW_SCHEMA = "room_board_review/v1";
const MATERIAL_SCHEMA = "room_board_review_material/v1";

export const REVIEW_DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;
export const REVIEW_STATUSES = new Set(["none", "pending", "endorsed", "objected", "superseded"]);
export const REVIEW_DETAIL_STATUSES = new Set(["pending", "endorsed", "objected", "superseded"]);
export const REVIEWER_KINDS = new Set(["participant", "operator"]);
export const REVIEW_VERDICTS = new Set(["endorse", "object"]);
export const REVIEW_SEVERITIES = new Set(["blocker", "major", "minor"]);

/**
 * Repository-relative path rule (§3.10). Mirrors the contract schema pattern:
 * no leading `/`, no drive letter, no backslash, no `.`/`..` segment, no
 * control or Unicode format characters, 1–512 chars.
 */
export const REVIEW_PATH_PATTERN: RegExp = /^(?![/])(?![A-Za-z]:)(?!(?:.*\/)?\.{1,2}(?:\/|$))[^\\\u0000-\u001f\u007f-\u009f\u00ad\u0600-\u0605\u061c\u06dd\u070f\u0890-\u0891\u08e2\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb]{1,512}$/;

export function sanitizeReviewTextValue(value: string): string {
  let cleaned = value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/g, "");
  cleaned = cleaned.replace(/\u001B\[[0-9;?]*[ -/]*[@-~]/g, "");
  cleaned = cleaned.replace(/\u001B\][^\u0007]*(?:\u0007|$)/g, "");
  cleaned = cleaned.replace(/\u001B/g, "");
  cleaned = cleaned.replace(/[\u061C\u200E\u200F\u202A-\u202E\u2066-\u2069]/g, "");
  return cleaned;
}

function reviewError(code: string, message: string): XmuseApiError {
  return new XmuseApiError({ code, message, retryable: false, status: 422 });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function asString(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function asOptionalString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function asNonNegativeInt(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : fallback;
}

function asBool(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function normalizeAgentText(value: unknown): AgentText {
  const source = isRecord(value) ? value : {};
  const raw = typeof source.text === "string" ? source.text : "";
  return {
    text: sanitizeReviewTextValue(raw),
    untrusted: true,
    truncated: asBool(source.truncated, false)
  };
}

function normalizeNullableAgentText(value: unknown): AgentText | null {
  if (value === null || value === undefined) return null;
  if (!isRecord(value)) return null;
  return normalizeAgentText(value);
}

export function normalizeFindingsCount(value: unknown): BoardFindingsCount {
  const source = isRecord(value) ? value : {};
  return {
    blocker: asNonNegativeInt(source.blocker),
    major: asNonNegativeInt(source.major),
    minor: asNonNegativeInt(source.minor)
  };
}

export function normalizeReviewEscalation(value: unknown): BoardReviewEscalation | null {
  if (value === null || value === undefined) return null;
  if (!isRecord(value)) return null;
  const participantId = asOptionalString(value.participant_id);
  const family = asOptionalString(value.family);
  const reasonCode = asOptionalString(value.reason_code);
  const at = asOptionalString(value.at);
  if (!participantId || !family || !reasonCode || !at) return null;
  return { participant_id: participantId, family, reason_code: reasonCode, at };
}

function normalizeReviewStatus(value: unknown): { status: BoardReview["status"]; raw: string | null } {
  if (typeof value === "string" && REVIEW_STATUSES.has(value)) {
    return { status: value as BoardReview["status"], raw: null };
  }
  if (typeof value === "string" && value) {
    return { status: "unknown", raw: value };
  }
  return { status: "unknown", raw: null };
}

function normalizeReviewerKind(
  value: unknown
): { kind: BoardReview["reviewer_kind"]; raw: string | null } {
  if (value === null || value === undefined) return { kind: null, raw: null };
  if (typeof value === "string" && REVIEWER_KINDS.has(value)) {
    return { kind: value as BoardReview["reviewer_kind"], raw: null };
  }
  if (typeof value === "string" && value) {
    return { kind: "unknown", raw: value };
  }
  return { kind: "unknown", raw: typeof value === "string" ? value : null };
}

function normalizeDecidedVia(
  value: unknown
): { via: BoardReview["decided_via"]; raw: string | null } {
  if (value === null || value === undefined) return { via: null, raw: null };
  if (value === "board_tool" || value === "web") {
    return { via: value, raw: null };
  }
  if (typeof value === "string" && value) {
    return { via: "unknown", raw: value };
  }
  return { via: "unknown", raw: null };
}

function normalizeDecideAction(value: unknown): BoardReview["actions"]["decide"] {
  if (value === undefined || value === null) return undefined;
  if (!isRecord(value)) return undefined;
  const allowed = Array.isArray(value.allowed_verdicts)
    ? value.allowed_verdicts.filter((item): item is string => typeof item === "string")
    : [];
  return {
    available: asBool(value.available, false),
    method: asString(value.method, "POST"),
    href: asString(value.href, ""),
    expected_digest: asOptionalString(value.expected_digest),
    allowed_verdicts: allowed
  };
}

function normalizeMaterialAction(value: unknown): { available: boolean } | null | undefined {
  if (value === undefined || value === null) return undefined;
  if (!isRecord(value)) return undefined;
  return { available: asBool(value.available, false) };
}

export function normalizeBoardReview(value: unknown): BoardReview {
  const source = isRecord(value) ? value : {};
  const status = normalizeReviewStatus(source.status);
  const reviewer = normalizeReviewerKind(source.reviewer_kind);
  const via = normalizeDecidedVia(source.decided_via);
  let actions: BoardReview["actions"] = {};
  if (isRecord(source.actions)) {
    const decide = normalizeDecideAction(source.actions.decide);
    const material = normalizeMaterialAction(source.actions.material);
    if (decide !== undefined) actions = { ...actions, decide };
    if (material !== undefined) actions = { ...actions, material };
  }
  return {
    status: status.status,
    statusRaw: status.raw,
    review_id: asOptionalString(source.review_id),
    verification_id: asOptionalString(source.verification_id),
    digest: asOptionalString(source.digest),
    rule_id: asOptionalString(source.rule_id),
    author_family: asOptionalString(source.author_family),
    reviewer_kind: reviewer.kind,
    reviewerKindRaw: reviewer.raw,
    reviewer_participant_id: asOptionalString(source.reviewer_participant_id),
    reviewer_family: asOptionalString(source.reviewer_family),
    escalated_from: normalizeReviewEscalation(source.escalated_from),
    findings_count: normalizeFindingsCount(source.findings_count),
    decided_via: via.via,
    decidedViaRaw: via.raw,
    updated_at: asOptionalString(source.updated_at),
    actions
  };
}

function normalizeSeverity(value: unknown): { severity: BoardReviewFinding["severity"]; raw: string | null } {
  if (typeof value === "string" && REVIEW_SEVERITIES.has(value)) {
    return { severity: value as BoardReviewFinding["severity"], raw: null };
  }
  if (typeof value === "string" && value) {
    return { severity: "unknown", raw: value };
  }
  return { severity: "unknown", raw: null };
}

export function normalizeBoardReviewFinding(value: unknown): BoardReviewFinding | null {
  if (!isRecord(value)) return null;
  const severity = normalizeSeverity(value.severity);
  if (severity.severity === "unknown") return null;
  const path = value.path === null ? null : typeof value.path === "string" ? value.path : null;
  if (value.path !== null && path === null) return null;
  if (!isRecord(value.text)) return null;
  return {
    severity: severity.severity,
    severityRaw: severity.raw,
    path,
    text: normalizeAgentText(value.text)
  };
}

function normalizeEligible(value: unknown): BoardReviewEligible | null {
  if (!isRecord(value)) return null;
  const participantId = asOptionalString(value.participant_id);
  const family = asOptionalString(value.family);
  if (!participantId || !family) return null;
  const pending = value.pending;
  if (typeof pending !== "number" || !Number.isSafeInteger(pending) || pending < 0) return null;
  return { participant_id: participantId, family, pending };
}

function normalizeRuleInputs(value: unknown): BoardReviewRuleInputs {
  const source = isRecord(value) ? value : {};
  const eligible = Array.isArray(source.eligible)
    ? source.eligible.flatMap((item) => {
        const parsed = normalizeEligible(item);
        return parsed ? [parsed] : [];
      })
    : [];
  return {
    rule_id: asString(source.rule_id, "cross_family/v1"),
    author_participant_id: asString(source.author_participant_id, ""),
    author_family: asString(source.author_family, ""),
    eligible,
    last_reviewer_participant_id: asOptionalString(source.last_reviewer_participant_id),
    picked_participant_id: asOptionalString(source.picked_participant_id)
  };
}

export function normalizeBoardReviewDetail(payload: unknown): BoardReviewDetail {
  if (!isRecord(payload)) {
    throw reviewError("room_board_review_invalid", "Board review must be an object");
  }
  if (payload.schema_version !== REVIEW_SCHEMA) {
    throw reviewError(
      "room_board_review_schema_unsupported",
      `Unsupported board review schema: ${String(payload.schema_version)}`
    );
  }
  const findings = Array.isArray(payload.findings)
    ? payload.findings.flatMap((item) => {
        const parsed = normalizeBoardReviewFinding(item);
        return parsed ? [parsed] : [];
      })
    : [];
  return {
    schema_version: REVIEW_SCHEMA,
    conversation_id: asString(payload.conversation_id, ""),
    module_id: asString(payload.module_id, ""),
    review: normalizeBoardReview(payload.review),
    head_commit: asString(payload.head_commit, ""),
    summary: normalizeNullableAgentText(payload.summary),
    findings,
    rule_inputs: normalizeRuleInputs(payload.rule_inputs),
    created_at: asString(payload.created_at, ""),
    decided_at: asOptionalString(payload.decided_at)
  };
}

export function normalizeBoardReviewMaterial(payload: unknown): BoardReviewMaterial {
  if (!isRecord(payload)) {
    throw reviewError("room_board_review_material_invalid", "Board review material must be an object");
  }
  if (payload.schema_version !== MATERIAL_SCHEMA) {
    throw reviewError(
      "room_board_review_material_schema_unsupported",
      `Unsupported board review material schema: ${String(payload.schema_version)}`
    );
  }
  const patchSource = isRecord(payload.patch) ? payload.patch : {};
  return {
    schema_version: MATERIAL_SCHEMA,
    review_id: asString(payload.review_id, ""),
    verification_id: asString(payload.verification_id, ""),
    head_commit: asString(payload.head_commit, ""),
    digest: asString(payload.digest, ""),
    patch: {
      text: typeof patchSource.text === "string" ? patchSource.text : "",
      bytes_total: asNonNegativeInt(patchSource.bytes_total),
      truncated: asBool(patchSource.truncated, false),
      hidden_char_count: asNonNegativeInt(patchSource.hidden_char_count)
    }
  };
}

// --- Client-side input validation (§3.10, §8.1) ---

export function isValidReviewDigest(value: unknown): value is string {
  return typeof value === "string" && REVIEW_DIGEST_PATTERN.test(value);
}

export function isValidReviewPath(value: string | null): boolean {
  if (value === null) return true;
  if (typeof value !== "string" || !value) return false;
  return REVIEW_PATH_PATTERN.test(value);
}

export function validateReviewSummary(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 4000) return null;
  return trimmed;
}

export function validateReviewFindingText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > 1000) return null;
  return trimmed;
}

export type ReviewFindingDraft = {
  severity: string;
  path: string;
  text: string;
};

export function normalizeFindingDraftForSubmit(
  draft: ReviewFindingDraft
): { severity: string; path: string | null; text: string } | null {
  if (!REVIEW_SEVERITIES.has(draft.severity)) return null;
  const text = validateReviewFindingText(draft.text);
  if (!text) return null;
  const rawPath = draft.path.trim();
  const path = rawPath ? rawPath : null;
  if (path !== null && !isValidReviewPath(path)) return null;
  return { severity: draft.severity, path, text };
}

export function validateReviewFindingsForSubmit(
  drafts: ReviewFindingDraft[]
): Array<{ severity: string; path: string | null; text: string }> | null {
  if (!Array.isArray(drafts) || drafts.length > 32) return null;
  const out: Array<{ severity: string; path: string | null; text: string }> = [];
  for (const draft of drafts) {
    const parsed = normalizeFindingDraftForSubmit(draft);
    if (!parsed) return null;
    out.push(parsed);
  }
  return out;
}

export function reviewFindingsHaveBlockerOrMajor(
  findings: Array<{ severity: string }>
): boolean {
  return findings.some((item) => item.severity === "blocker" || item.severity === "major");
}

export function validateReviewDecisionBody(value: unknown): BoardReviewDecisionInput | null {
  if (!isRecord(value)) return null;
  const keys = Object.keys(value).sort();
  const expected = ["conversation_id", "expected_digest", "findings", "summary", "verdict"].sort();
  if (keys.join("") !== expected.join("")) return null;
  const conversationId =
    typeof value.conversation_id === "string" && value.conversation_id.trim()
      ? value.conversation_id.trim()
      : null;
  const verdict = value.verdict;
  const expectedDigest = value.expected_digest;
  const summary = validateReviewSummary(value.summary);
  if (!conversationId) return null;
  if (verdict !== "endorse" && verdict !== "object") return null;
  if (!isValidReviewDigest(expectedDigest)) return null;
  if (!summary) return null;
  if (!Array.isArray(value.findings) || value.findings.length > 32) return null;
  const findings: Array<{ severity: string; path: string | null; text: string }> = [];
  for (const item of value.findings) {
    if (!isRecord(item)) return null;
    const itemKeys = Object.keys(item).sort();
    if (itemKeys.join("") !== ["path", "severity", "text"].sort().join("")) return null;
    if (typeof item.severity !== "string" || !REVIEW_SEVERITIES.has(item.severity)) return null;
    const text = validateReviewFindingText(item.text);
    if (!text) return null;
    const path = item.path === null ? null : typeof item.path === "string" ? item.path : null;
    if (item.path !== null && path === null) return null;
    if (path !== null && !isValidReviewPath(path)) return null;
    findings.push({ severity: item.severity, path, text });
  }
  if (verdict === "object" && !reviewFindingsHaveBlockerOrMajor(findings)) return null;
  return {
    conversation_id: conversationId,
    verdict,
    expected_digest: expectedDigest as string,
    summary,
    findings
  };
}

// --- Fetchers (browser only calls fixed Next routes for writes/material) ---

export async function fetchBoardReviewDetail(
  conversationId: string,
  reviewId: string,
  options: ApiClientOptions = {}
): Promise<BoardReviewDetail> {
  const raw = await fetchJson<unknown>(
    `${chatApiBaseUrl(options)}/conversations/${encodeURIComponent(
      conversationId
    )}/board/reviews/${encodeURIComponent(reviewId)}`,
    { method: "GET", cache: "no-store" },
    options
  );
  return normalizeBoardReviewDetail(raw);
}

export async function fetchBoardReviewMaterial(
  conversationId: string,
  reviewId: string,
  options: ApiClientOptions = {}
): Promise<BoardReviewMaterial> {
  const raw = await fetchJson<unknown>(
    `/api/room-board-reviews/${encodeURIComponent(reviewId)}/material?conversation_id=${encodeURIComponent(
      conversationId
    )}`,
    { method: "GET", cache: "no-store", credentials: "same-origin" },
    { ...options, timeoutMs: options.timeoutMs ?? 30_000 }
  );
  return normalizeBoardReviewMaterial(raw);
}

export type BoardReviewDecisionArgs = {
  conversationId: string;
  reviewId: string;
  verdict: BoardReviewVerdict;
  expectedDigest: string;
  summary: string;
  findings: Array<{ severity: string; path: string | null; text: string }>;
};

export function reviewDecideDescriptorValid(
  review: BoardReview,
  reviewId: string,
  verdict: BoardReviewVerdict
): boolean {
  const descriptor = review.actions?.decide;
  const expectedHref = `/api/chat/operator/board-reviews/${encodeURIComponent(reviewId)}/decision`;
  if (
    !descriptor ||
    descriptor.available !== true ||
    descriptor.method !== "POST" ||
    descriptor.href !== expectedHref ||
    !descriptor.allowed_verdicts.includes(verdict) ||
    !descriptor.expected_digest ||
    !isValidReviewDigest(descriptor.expected_digest)
  ) {
    return false;
  }
  return true;
}

export async function submitBoardReviewDecision(
  args: BoardReviewDecisionArgs,
  options: ApiClientOptions = {}
): Promise<unknown> {
  const body = validateReviewDecisionBody({
    conversation_id: args.conversationId,
    verdict: args.verdict,
    expected_digest: args.expectedDigest,
    summary: args.summary,
    findings: args.findings
  });
  if (!body) {
    throw new XmuseApiError({
      code: "room_board_review_request_invalid",
      message: "Board review decision is invalid",
      retryable: false,
      status: 400
    });
  }
  return fetchJson<unknown>(
    `/api/room-board-reviews/${encodeURIComponent(args.reviewId)}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      cache: "no-store",
      credentials: "same-origin"
    },
    { ...options, timeoutMs: options.timeoutMs ?? 30_000 }
  );
}
