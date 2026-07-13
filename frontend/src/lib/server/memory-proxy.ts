import {
  boundedText,
  exactObject,
  proxyFixedRoomWrite,
  proxyJsonError
} from "./fixed-room-proxy";

const DECISIONS = new Set(["approve", "reject"]);

function nonnegativeInteger(value: unknown): number | null {
  return Number.isSafeInteger(value) && Number(value) >= 0 ? Number(value) : null;
}

function normalizeResolveBody(value: unknown) {
  const body = exactObject(value, [
    "client_action_id",
    "decision",
    "expected_digest",
    "expected_revision"
  ]);
  if (!body) return null;
  const clientActionId = boundedText(body.client_action_id);
  const decision = boundedText(body.decision);
  const expectedDigest = boundedText(body.expected_digest);
  const expectedRevision = nonnegativeInteger(body.expected_revision);
  return clientActionId && decision && DECISIONS.has(decision) && expectedDigest
    && expectedRevision !== null
    ? {
        client_action_id: clientActionId,
        decision,
        expected_digest: expectedDigest,
        expected_revision: expectedRevision
      }
    : null;
}

export function proxyMemoryCandidateResolve(
  request: Request,
  candidateId: string
): Promise<Response> | Response {
  if (request.method !== "POST") {
    return proxyJsonError(
      405,
      "room_memory_resolve_method_invalid",
      "HTTP method is not allowed"
    );
  }
  if (!boundedText(candidateId)) {
    return proxyJsonError(
      400,
      "room_memory_resolve_target_invalid",
      "memory candidate id is invalid"
    );
  }
  return proxyFixedRoomWrite({
    request,
    upstreamPath: `operator/memory-candidates/${encodeURIComponent(candidateId)}/resolve`,
    maxBodyBytes: 8 * 1024,
    timeoutMs: 30_000,
    codePrefix: "room_memory_resolve",
    normalizeBody: normalizeResolveBody
  });
}
