import {
  boundedText,
  exactObject,
  proxyFixedRoomRead,
  proxyFixedRoomWrite,
  proxyJsonError
} from "./fixed-room-proxy";
import {
  REVIEW_DIGEST_PATTERN,
  REVIEW_PATH_PATTERN,
  REVIEW_SEVERITIES,
  REVIEW_VERDICTS
} from "@/lib/board-review-api";

const MATERIAL_PREFIX = "room_board_review_material";
const DECISION_PREFIX = "room_board_review_decision";
const MATERIAL_TIMEOUT_MS = 30_000;
const DECISION_TIMEOUT_MS = 30_000;
const DECISION_MAX_BODY_BYTES = 64 * 1024;

function trimmedText(value: unknown, maximum: number): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > maximum) return null;
  return trimmed;
}

function normalizeFinding(value: unknown): {
  severity: string;
  path: string | null;
  text: string;
} | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (Object.keys(record).sort().join("") !== ["path", "severity", "text"].sort().join("")) {
    return null;
  }
  const severity = typeof record.severity === "string" ? record.severity : null;
  if (!severity || !REVIEW_SEVERITIES.has(severity)) return null;
  const text = trimmedText(record.text, 1000);
  if (!text) return null;
  const path = record.path === null ? null : typeof record.path === "string" ? record.path : null;
  if (record.path !== null && path === null) return null;
  if (path !== null && !REVIEW_PATH_PATTERN.test(path)) return null;
  return { severity, path, text };
}

function normalizeDecisionBody(value: unknown) {
  const body = exactObject(value, [
    "conversation_id",
    "expected_digest",
    "findings",
    "summary",
    "verdict"
  ]);
  if (!body) return null;
  const conversationId = boundedText(body.conversation_id);
  const verdict = typeof body.verdict === "string" ? body.verdict : null;
  const expectedDigest =
    typeof body.expected_digest === "string" ? body.expected_digest : null;
  const summary = trimmedText(body.summary, 4000);
  if (!conversationId) return null;
  if (!verdict || !REVIEW_VERDICTS.has(verdict)) return null;
  if (!expectedDigest || !REVIEW_DIGEST_PATTERN.test(expectedDigest)) return null;
  if (!summary) return null;
  if (!Array.isArray(body.findings) || body.findings.length > 32) return null;
  const findings: Array<{ severity: string; path: string | null; text: string }> = [];
  for (const item of body.findings) {
    const parsed = normalizeFinding(item);
    if (!parsed) return null;
    findings.push(parsed);
  }
  if (verdict === "object" && !findings.some((item) => item.severity === "blocker" || item.severity === "major")) {
    return null;
  }
  return {
    conversation_id: conversationId,
    verdict,
    expected_digest: expectedDigest,
    summary,
    findings,
    decided_via: "web"
  };
}

export function proxyReviewMaterial(
  request: Request,
  reviewId: string
): Promise<Response> | Response {
  if (request.method !== "GET") {
    return proxyJsonError(405, `${MATERIAL_PREFIX}_method_invalid`, "HTTP method is not allowed");
  }
  const cleanId = boundedText(reviewId);
  if (!cleanId) {
    return proxyJsonError(400, `${MATERIAL_PREFIX}_target_invalid`, "board review id is invalid");
  }
  let url: URL;
  try {
    url = new URL(request.url);
  } catch {
    return proxyJsonError(400, `${MATERIAL_PREFIX}_query_invalid`, "request query is invalid");
  }
  const keys = [...url.searchParams.keys()];
  const conversationId = boundedText(url.searchParams.get("conversation_id"));
  if (!conversationId || keys.length !== 1 || keys[0] !== "conversation_id") {
    return proxyJsonError(400, `${MATERIAL_PREFIX}_query_invalid`, "request query is invalid");
  }
  return proxyFixedRoomRead({
    request,
    upstreamPath: `operator/board-reviews/${encodeURIComponent(cleanId)}/material`,
    query: { conversation_id: conversationId },
    timeoutMs: MATERIAL_TIMEOUT_MS,
    codePrefix: MATERIAL_PREFIX
  });
}

export function proxyReviewDecision(
  request: Request,
  reviewId: string
): Promise<Response> | Response {
  if (request.method !== "POST") {
    return proxyJsonError(405, `${DECISION_PREFIX}_method_invalid`, "HTTP method is not allowed");
  }
  const cleanId = boundedText(reviewId);
  if (!cleanId) {
    return proxyJsonError(400, `${DECISION_PREFIX}_target_invalid`, "board review id is invalid");
  }
  return proxyFixedRoomWrite({
    request,
    upstreamPath: `operator/board-reviews/${encodeURIComponent(cleanId)}/decision`,
    maxBodyBytes: DECISION_MAX_BODY_BYTES,
    timeoutMs: DECISION_TIMEOUT_MS,
    codePrefix: DECISION_PREFIX,
    normalizeBody: normalizeDecisionBody
  });
}
