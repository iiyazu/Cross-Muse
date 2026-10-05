import {
  boundedText,
  exactObject,
  proxyFixedRoomRead,
  proxyFixedRoomWrite,
  proxyJsonError
} from "./fixed-room-proxy";

const CODE_PREFIX = "plugin_grant";
const GRANT_SCOPE = "board.split.decide";
const HOST_PATTERN = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const MAX_BODY_BYTES = 8 * 1024;
const TIMEOUT_MS = 30_000;

function normalizeIssueBody(value: unknown) {
  const body = exactObject(value, ["conversation_id", "host", "scope", "ttl_seconds"]);
  if (!body) return null;
  const conversationId = boundedText(body.conversation_id);
  const host = typeof body.host === "string" ? body.host : null;
  const scope = typeof body.scope === "string" ? body.scope : null;
  const ttlSeconds = body.ttl_seconds;
  if (!conversationId) return null;
  if (!host || !HOST_PATTERN.test(host)) return null;
  if (scope !== GRANT_SCOPE) return null;
  if (
    typeof ttlSeconds !== "number" ||
    !Number.isInteger(ttlSeconds) ||
    ttlSeconds < 60 ||
    ttlSeconds > 3600
  ) return null;
  return {
    conversation_id: conversationId,
    host,
    scope,
    ttl_seconds: ttlSeconds
  };
}

function normalizeRevokeBody(value: unknown) {
  const body = exactObject(value, ["conversation_id"]);
  if (!body) return null;
  const conversationId = boundedText(body.conversation_id);
  return conversationId ? { conversation_id: conversationId } : null;
}

export function proxyGrantIssue(request: Request): Promise<Response> | Response {
  if (request.method !== "POST") {
    return proxyJsonError(
      405,
      `${CODE_PREFIX}_method_invalid`,
      "HTTP method is not allowed"
    );
  }
  return proxyFixedRoomWrite({
    request,
    upstreamPath: "operator/plugin-grants",
    maxBodyBytes: MAX_BODY_BYTES,
    timeoutMs: TIMEOUT_MS,
    codePrefix: CODE_PREFIX,
    normalizeBody: normalizeIssueBody
  });
}

export function proxyGrantList(request: Request): Promise<Response> | Response {
  if (request.method !== "GET") {
    return proxyJsonError(
      405,
      `${CODE_PREFIX}_method_invalid`,
      "HTTP method is not allowed"
    );
  }
  let url: URL;
  try {
    url = new URL(request.url);
  } catch {
    return proxyJsonError(400, `${CODE_PREFIX}_query_invalid`, "request query is invalid");
  }
  const keys = [...url.searchParams.keys()];
  const conversationId = boundedText(url.searchParams.get("conversation_id"));
  if (!conversationId || keys.length !== 1 || keys[0] !== "conversation_id") {
    return proxyJsonError(400, `${CODE_PREFIX}_query_invalid`, "request query is invalid");
  }
  return proxyFixedRoomRead({
    request,
    upstreamPath: "operator/plugin-grants",
    query: { conversation_id: conversationId },
    timeoutMs: TIMEOUT_MS,
    codePrefix: CODE_PREFIX
  });
}

export function proxyGrantRevoke(
  request: Request,
  grantId: string
): Promise<Response> | Response {
  if (request.method !== "POST") {
    return proxyJsonError(
      405,
      `${CODE_PREFIX}_method_invalid`,
      "HTTP method is not allowed"
    );
  }
  const cleanId = boundedText(grantId);
  if (!cleanId) {
    return proxyJsonError(
      400,
      `${CODE_PREFIX}_target_invalid`,
      "plugin grant id is invalid"
    );
  }
  return proxyFixedRoomWrite({
    request,
    upstreamPath: `operator/plugin-grants/${encodeURIComponent(cleanId)}/revoke`,
    maxBodyBytes: MAX_BODY_BYTES,
    timeoutMs: TIMEOUT_MS,
    codePrefix: CODE_PREFIX,
    normalizeBody: normalizeRevokeBody
  });
}
