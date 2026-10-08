// Plugin grant requests (plugin_grant/v2, main_window_control_v1 client rules).
//
// Pure module: no engine calls. The hooks module injects its transport as
// `http`, so these shapes are unit-testable without a session. This is the
// only file in the mod that may name the write method or the bearer header,
// and the header name is spelled exactly once, in `pluginRequest` below.

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

// The single sender for every grant request. Exchange passes a null bearer
// (Content-Type only, never an Origin header); the other writes pass the
// in-memory token. A GET (review material) sends no body and so no
// Content-Type. Nothing here ever reads the operator token routes.
async function pluginRequest(
  http: GrantHttp,
  baseUrl: string,
  method: "POST" | "GET",
  path: string,
  body: unknown,
  bearer: string | null,
): Promise<GrantPostResult> {
  const base = assertLoopbackBaseUrl(baseUrl);
  const headers: Record<string, string> = method === "POST" ? { "Content-Type": "application/json" } : {};
  if (bearer !== null) headers["Authorization"] = "Bearer " + bearer;
  let res: GrantHttpResponse;
  try {
    res = await http(base + path, { method, headers, body: method === "POST" ? JSON.stringify(body) : "" });
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

function pluginPost(
  http: GrantHttp,
  baseUrl: string,
  path: string,
  body: unknown,
  bearer: string | null,
): Promise<GrantPostResult> {
  return pluginRequest(http, baseUrl, "POST", path, body, bearer);
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

// main_window_control_v1 §4.1. Only provider kinds and the title travel;
// the server picks models and the workspace.
export type RoomCreateRequest = {
  clientRequestId: string;
  title: string;
  lead: string;
  owners: string[];
  reviewer: string | null;
};

export async function createRoom(
  http: GrantHttp,
  baseUrl: string,
  bearer: string,
  req: RoomCreateRequest,
): Promise<GrantPostResult> {
  return pluginPost(
    http,
    baseUrl,
    "/api/chat/plugin/rooms",
    {
      client_request_id: req.clientRequestId,
      title: req.title,
      lead: { cli_kind: req.lead },
      owners: req.owners.map((kind) => ({ cli_kind: kind })),
      reviewer: req.reviewer === null ? null : { cli_kind: req.reviewer },
      review_policy: req.reviewer === null ? "off" : "cross_family",
    },
    bearer,
  );
}

// §4.2. Mentions are written in the text (@lead, @owner-1); the server
// resolves them by role.
export async function postMessage(
  http: GrantHttp,
  baseUrl: string,
  bearer: string,
  conversationId: string,
  clientRequestId: string,
  message: string,
): Promise<GrantPostResult> {
  return pluginPost(
    http,
    baseUrl,
    "/api/chat/plugin/rooms/" + encodeURIComponent(conversationId) + "/messages",
    { client_request_id: clientRequestId, message },
    bearer,
  );
}

export type ReviewVerdict = "endorse" | "object";

// §4.4. An objection carries the human's reason as one major finding.
export async function decideReview(
  http: GrantHttp,
  baseUrl: string,
  bearer: string,
  reviewId: string,
  conversationId: string,
  verdict: ReviewVerdict,
  expectedDigest: string,
  reason: string | null,
): Promise<GrantPostResult> {
  const text = reason !== null && reason.trim() !== "" ? reason.trim() : "";
  return pluginPost(
    http,
    baseUrl,
    "/api/chat/plugin/board-reviews/" + encodeURIComponent(reviewId) + "/decision",
    {
      conversation_id: conversationId,
      verdict,
      expected_digest: expectedDigest,
      summary: verdict === "endorse" ? "Endorsed by the Human from the main window." : text,
      findings: verdict === "object" ? [{ severity: "major", text }] : [],
    },
    bearer,
  );
}

// §4.5: a GET with the bearer and no body (so no Content-Type).
export async function fetchReviewMaterial(
  http: GrantHttp,
  baseUrl: string,
  bearer: string,
  reviewId: string,
  conversationId: string,
): Promise<GrantPostResult> {
  const path =
    "/api/chat/plugin/board-reviews/" +
    encodeURIComponent(reviewId) +
    "/material?conversation_id=" +
    encodeURIComponent(conversationId);
  return pluginRequest(http, baseUrl, "GET", path, null, bearer);
}

export type MaterialMeta = { digest: string; text: string; truncated: boolean };

export function parseMaterialPayload(json: unknown): MaterialMeta | null {
  const root = asRecord(json);
  if (root === null || root["schema_version"] !== "room_board_review_material/v1") return null;
  const digest = root["digest"];
  const patch = asRecord(root["patch"]);
  if (typeof digest !== "string" || !/^sha256:[0-9a-f]{64}$/.test(digest) || patch === null) return null;
  const text = patch["text"];
  return {
    digest,
    text: typeof text === "string" ? text : "",
    truncated: patch["truncated"] === true,
  };
}

export type RoomCreated = { conversationId: string; roomCount: number; owners: number };

export function parseRoomCreatePayload(json: unknown): RoomCreated | null {
  const root = asRecord(json);
  if (root === null || root["schema_version"] !== "plugin_room_create/v1") return null;
  const conversationId = root["conversation_id"];
  const roomCount = root["room_count"];
  const participants = root["participants"];
  if (typeof conversationId !== "string" || conversationId === "" || typeof roomCount !== "number") return null;
  const owners = Array.isArray(participants)
    ? participants.filter((p) => {
        const r = asRecord(p);
        return r !== null && typeof r["role"] === "string" && String(r["role"]).startsWith("owner-");
      }).length
    : 0;
  return { conversationId, roomCount, owners };
}

function asRecord(v: unknown): Record<string, unknown> | null {
  if (typeof v === "object" && v !== null && !Array.isArray(v)) return v as Record<string, unknown>;
  return null;
}

const TOKEN_RE = /^xpg_[A-Za-z0-9_-]+_[A-Za-z0-9_-]{43}$/;

export type GrantMeta = {
  grantId: string;
  expiresAt: string;
  conversationIds: string[];
  scopes: string[];
};

function stringList(v: unknown): string[] | null {
  if (!Array.isArray(v)) return null;
  const out: string[] = [];
  for (const item of v) {
    if (typeof item !== "string" || item === "") return null;
    out.push(item);
  }
  return out;
}

// Narrow a 200 exchange body (plugin_grant/v2) to the non-secret metadata
// the pane may keep plus the token the hooks module holds in memory.
// Anything else is null: the caller then treats the exchange as failed
// without touching the grant.
export function parseExchangePayload(json: unknown): { grant: GrantMeta; token: string } | null {
  const root = asRecord(json);
  if (root === null || root["schema_version"] !== "plugin_grant_exchange/v2") return null;
  const grant = asRecord(root["grant"]);
  if (grant === null || grant["status"] !== "active") return null;
  const grantId = grant["grant_id"];
  const expiresAt = grant["expires_at"];
  const conversationIds = stringList(grant["conversation_ids"]);
  const scopes = stringList(grant["scopes"]);
  const token = root["secret"];
  if (
    typeof grantId !== "string" || grantId === "" ||
    typeof expiresAt !== "string" || expiresAt === "" ||
    conversationIds === null || scopes === null || scopes.length === 0 ||
    typeof token !== "string" || !TOKEN_RE.test(token)
  ) {
    return null;
  }
  return { grant: { grantId, expiresAt, conversationIds, scopes }, token };
}

// The structured reason code of an error body, or null when absent. Toasts
// map it to fixed labels only; the code string itself is never shown.
export function detailCodeOf(json: unknown): string | null {
  const root = asRecord(json);
  const detail = root !== null ? asRecord(root["detail"]) : null;
  const code = detail !== null ? detail["code"] : null;
  return typeof code === "string" ? code : null;
}
