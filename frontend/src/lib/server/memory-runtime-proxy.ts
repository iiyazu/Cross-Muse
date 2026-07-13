import {
  boundedText,
  exactObject,
  proxyFixedRoomWrite,
  proxyJsonError
} from "./fixed-room-proxy";

const RESULT_SCHEMA = "room_memory_rebuild_action/v1";
const PROOF_BOUNDARY = "operator_action_receipt_not_room_or_memory_index_authority";
const STATUSES = new Set(["requested", "applied", "rejected", "failed"]);
const PHASES = new Set([
  "requested",
  "stopping",
  "stopped",
  "cache_cleared",
  "authority_reset",
  "restarting",
  "replaying",
  "complete"
]);
const RUNTIME_STATES = new Set([
  "disabled",
  "starting",
  "recovering",
  "ready",
  "degraded",
  "rebuilding",
  "stopped",
  "unknown"
]);
const SAFE_CODE = /^[a-z][a-z0-9_]{0,127}$/;
const ACTION_ID = /^mra_[0-9a-f]{32}$/;
const ISO_TIMESTAMP = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/;

type RebuildBody = {
  client_action_id: string;
  expected_incident_id: string;
};

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function nullableText(value: unknown, maximum = 200): string | null | undefined {
  if (value === null) return null;
  return boundedText(value, maximum) ?? undefined;
}

function nonnegativeInteger(value: unknown): number | null {
  return Number.isSafeInteger(value) && Number(value) >= 0 ? Number(value) : null;
}

function normalizeRebuildBody(value: unknown): RebuildBody | null {
  const body = exactObject(value, ["client_action_id", "expected_incident_id"]);
  if (!body) return null;
  const clientActionId = boundedText(body.client_action_id);
  const incidentId = boundedText(body.expected_incident_id);
  return clientActionId && incidentId
    ? { client_action_id: clientActionId, expected_incident_id: incidentId }
    : null;
}

function normalizeState(value: unknown): { state: string | null; code: string | null } | null {
  const source = record(value);
  if (!source) return null;
  const state = nullableText(source.state, 64);
  const code = nullableText(source.code, 128);
  if (
    state === undefined ||
    code === undefined ||
    (state !== null && !RUNTIME_STATES.has(state)) ||
    (code !== null && !SAFE_CODE.test(code))
  ) return null;
  return { state, code };
}

function validTimestamp(value: string | null): boolean {
  return value === null || ISO_TIMESTAMP.test(value);
}

function normalizeResult(value: unknown) {
  if (value === null) return null;
  const source = record(value);
  if (!source) return undefined;
  const cacheCleared = source.cache_cleared;
  const bindingsReset = nonnegativeInteger(source.bindings_reset);
  const deliveriesReopened = nonnegativeInteger(source.deliveries_reopened);
  const claimedAttemptsFenced = nonnegativeInteger(source.claimed_attempts_fenced);
  const candidatesRequeued = nonnegativeInteger(source.candidates_requeued);
  if (
    typeof cacheCleared !== "boolean" ||
    bindingsReset === null ||
    deliveriesReopened === null ||
    claimedAttemptsFenced === null ||
    candidatesRequeued === null
  ) return undefined;
  return {
    cache_cleared: cacheCleared,
    bindings_reset: bindingsReset,
    deliveries_reopened: deliveriesReopened,
    claimed_attempts_fenced: claimedAttemptsFenced,
    candidates_requeued: candidatesRequeued
  };
}

function normalizeActionReceipt(value: unknown, clientActionId: string) {
  const source = record(value);
  if (!source || source.schema_version !== RESULT_SCHEMA ||
    source.proof_boundary !== PROOF_BOUNDARY) return null;
  const actionId = boundedText(source.action_id);
  const responseClientActionId = boundedText(source.client_action_id);
  const status = boundedText(source.status, 32);
  const phase = nullableText(source.phase, 64);
  const reasonCode = nullableText(source.reason_code, 128);
  const before = normalizeState(source.before);
  const after = normalizeState(source.after);
  const result = normalizeResult(source.result);
  const requestedAt = nullableText(source.requested_at, 100);
  const appliedAt = nullableText(source.applied_at, 100);
  if (
    !actionId ||
    !ACTION_ID.test(actionId) ||
    responseClientActionId !== clientActionId ||
    !status ||
    !STATUSES.has(status) ||
    phase === undefined ||
    phase === null ||
    !PHASES.has(phase) ||
    reasonCode === undefined ||
    (reasonCode !== null && !SAFE_CODE.test(reasonCode)) ||
    !before ||
    !after ||
    result === undefined ||
    requestedAt === undefined ||
    appliedAt === undefined ||
    requestedAt === null ||
    !validTimestamp(requestedAt) ||
    !validTimestamp(appliedAt) ||
    (status === "requested" ? appliedAt !== null : appliedAt === null) ||
    (status === "requested" ? phase === "complete" : phase !== "complete")
  ) return null;
  return {
    schema_version: RESULT_SCHEMA,
    action_id: actionId,
    client_action_id: responseClientActionId,
    status,
    phase,
    reason_code: reasonCode,
    before,
    after,
    result,
    requested_at: requestedAt,
    applied_at: appliedAt,
    proof_boundary: PROOF_BOUNDARY
  };
}

async function safeErrorResponse(response: Response): Promise<Response> {
  let code = "room_memory_rebuild_upstream_rejected";
  try {
    const payload = record(await response.json());
    const detail = record(payload?.detail);
    const candidate = boundedText(detail?.code, 128);
    if (candidate && SAFE_CODE.test(candidate)) code = candidate;
  } catch {
    // The status is useful; an untrusted or malformed upstream body is not.
  }
  return proxyJsonError(response.status, code, "MemoryOS rebuild request was rejected");
}

export async function proxyMemoryRuntimeRebuild(request: Request): Promise<Response> {
  if (request.method !== "POST") {
    return proxyJsonError(
      405,
      "room_memory_rebuild_method_invalid",
      "HTTP method is not allowed"
    );
  }
  let forwarded: RebuildBody | null = null;
  const response = await proxyFixedRoomWrite({
    request,
    upstreamPath: "operator/memory-runtime/rebuild",
    maxBodyBytes: 8 * 1024,
    timeoutMs: 30_000,
    codePrefix: "room_memory_rebuild",
    normalizeBody: (value) => {
      forwarded = normalizeRebuildBody(value);
      return forwarded;
    }
  });
  if (!response.ok) return safeErrorResponse(response);
  const forwardedBody = forwarded as RebuildBody | null;
  if (!forwardedBody) {
    return proxyJsonError(502, "room_memory_rebuild_response_invalid", "MemoryOS rebuild response is invalid");
  }
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return proxyJsonError(502, "room_memory_rebuild_response_invalid", "MemoryOS rebuild response is invalid");
  }
  const normalized = normalizeActionReceipt(payload, forwardedBody.client_action_id);
  if (!normalized) {
    return proxyJsonError(502, "room_memory_rebuild_response_invalid", "MemoryOS rebuild response is invalid");
  }
  return Response.json(normalized, {
    status: response.status,
    headers: { "Cache-Control": "no-store" }
  });
}
