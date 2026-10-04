// Plugin grant writes (plugin_grant/v1, client rules).
//
// Pure module: no engine calls. The hooks module injects its transport as
// `http`, so these shapes are unit-testable without a session. This is the
// only file in the mod that may name the write method or the bearer header,
// and the header name is spelled exactly once, in `pluginPost` below.

export type GrantHttpInit = {
  method: string;
  headers: Record<string, string>;
  body: string;
};

export type GrantHttpResponse = {
  status: number;
  text: string;
};

export type GrantHttp = (url: string, init: GrantHttpInit) => Promise<GrantHttpResponse>;

export type GrantPostResult = {
  status: number;
  json: unknown;
};

export const GRANT_EXCHANGE_PATH = "/api/chat/plugin/grants/exchange";
export const GRANT_REVOKE_PATH = "/api/chat/plugin/grants/revoke";

export function grantDecisionPath(splitId: string): string {
  return "/api/chat/plugin/board-splits/" + encodeURIComponent(splitId) + "/decision";
}

const LOOPBACK_RE = /^http:\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(\/|$)/;

// The board API keeps its loopback-only rule for writes too: refuse any
// base URL that is not a loopback name before anything is sent.
export function assertLoopbackBaseUrl(baseUrl: string): string {
  const base = baseUrl.replace(/\/+$/, "");
  if (!LOOPBACK_RE.test(base)) throw new Error("room_host_invalid");
  return base;
}

// The single sender for every grant write. Exchange passes a null bearer
// (Content-Type only, never an Origin header); decide and revoke pass the
// in-memory token. Nothing here ever reads the operator token routes.
async function pluginPost(
  http: GrantHttp,
  baseUrl: string,
  path: string,
  body: unknown,
  bearer: string | null,
): Promise<GrantPostResult> {
  const base = assertLoopbackBaseUrl(baseUrl);
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (bearer !== null) headers["Authorization"] = "Bearer " + bearer;
  let res: GrantHttpResponse;
  try {
    res = await http(base + path, { method: "POST", headers, body: JSON.stringify(body) });
  } catch {
    return { status: 0, json: null };
  }
  let json: unknown = null;
  try {
    json = res.text !== "" ? JSON.parse(res.text) : null;
  } catch {
    json = null;
  }
  return { status: res.status, json };
}

export async function exchangeGrant(
  http: GrantHttp,
  baseUrl: string,
  pairingCode: string,
): Promise<GrantPostResult> {
  return pluginPost(http, baseUrl, GRANT_EXCHANGE_PATH, { pairing_code: pairingCode, host: "claude-code" }, null);
}

export async function decideSplit(
  http: GrantHttp,
  baseUrl: string,
  bearer: string,
  splitId: string,
  conversationId: string,
  decision: "approve" | "reject",
  expectedDigest: string,
): Promise<GrantPostResult> {
  return pluginPost(
    http,
    baseUrl,
    grantDecisionPath(splitId),
    { conversation_id: conversationId, decision, expected_digest: expectedDigest },
    bearer,
  );
}

export async function revokeGrant(
  http: GrantHttp,
  baseUrl: string,
  bearer: string,
): Promise<GrantPostResult> {
  return pluginPost(http, baseUrl, GRANT_REVOKE_PATH, {}, bearer);
}

function asRecord(v: unknown): Record<string, unknown> | null {
  if (typeof v === "object" && v !== null && !Array.isArray(v)) return v as Record<string, unknown>;
  return null;
}

const TOKEN_RE = /^xpg_[A-Za-z0-9_-]+_[A-Za-z0-9_-]{43}$/;

export type GrantMeta = {
  grantId: string;
  expiresAt: string;
  conversationId: string;
};

// Narrow a 200 exchange body to the non-secret metadata the pane may keep
// plus the token the hooks module holds in memory. Anything else is null:
// the caller then treats the exchange as failed without touching the grant.
export function parseExchangePayload(json: unknown): { grant: GrantMeta; token: string } | null {
  const root = asRecord(json);
  if (root === null || root["schema_version"] !== "plugin_grant_exchange/v1") return null;
  const grant = asRecord(root["grant"]);
  if (grant === null || grant["status"] !== "active") return null;
  const grantId = grant["grant_id"];
  const expiresAt = grant["expires_at"];
  const conversationId = grant["conversation_id"];
  const token = root["secret"];
  if (
    typeof grantId !== "string" || grantId === "" ||
    typeof expiresAt !== "string" || expiresAt === "" ||
    typeof conversationId !== "string" || conversationId === "" ||
    typeof token !== "string" || !TOKEN_RE.test(token)
  ) {
    return null;
  }
  return { grant: { grantId, expiresAt, conversationId }, token };
}

// The structured reason code of an error body, or null when absent. Toasts
// map it to fixed labels only; the code string itself is never shown.
export function detailCodeOf(json: unknown): string | null {
  const root = asRecord(json);
  const detail = root !== null ? asRecord(root["detail"]) : null;
  const code = detail !== null ? detail["code"] : null;
  return typeof code === "string" ? code : null;
}
