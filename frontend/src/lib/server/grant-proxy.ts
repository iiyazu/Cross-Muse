import {
  boundedText,
  exactObject,
  proxyFixedRoomRead,
  proxyFixedRoomWrite,
  proxyJsonError
} from "./fixed-room-proxy";

const CODE_PREFIX = "plugin_grant";
const HOST_PATTERN = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const MAX_BODY_BYTES = 8 * 1024;
const TIMEOUT_MS = 30_000;

function normalizeRevokeBody(value: unknown) {
  const body = exactObject(value, ["conversation_id"]);
  if (!body) return null;
  const conversationId = boundedText(body.conversation_id);
  return conversationId ? { conversation_id: conversationId } : null;
}

/**
 * Lists grants by `conversation_id` (the grants covering a Room) or by `host` (every grant of
 * that host, so the panel can say a live grant leaves the Room out). Issuing is terminal-only
 * (`xmuse-workroom pair`, main_window_control_v1 §3, T16): this server injects the operator
 * token, so an issue route here would hand any local process a pairing code.
 */
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
  const key = keys.length === 1 ? keys[0] : null;
  const value = key ? url.searchParams.get(key) : null;
  const conversationId = key === "conversation_id" ? boundedText(value) : null;
  const host = key === "host" && value && HOST_PATTERN.test(value) ? value : null;
  const query: Record<string, string> | null = conversationId
    ? { conversation_id: conversationId }
    : host
      ? { host }
      : null;
  if (!query) {
    return proxyJsonError(400, `${CODE_PREFIX}_query_invalid`, "request query is invalid");
  }
  return proxyFixedRoomRead({
    request,
    upstreamPath: "operator/plugin-grants",
    query,
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
