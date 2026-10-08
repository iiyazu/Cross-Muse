import {
  fetchJson,
  XmuseApiError,
  type ApiClientOptions
} from "./api";
import {
  PLUGIN_GRANT_SCOPES,
  type PluginGrant,
  type PluginGrantList,
  type PluginGrantListQuery,
  type PluginGrantScope,
  type PluginGrantStatus
} from "./grant-types";

const LIST_SCHEMA = "plugin_grant_list/v2";

const HOST_PATTERN = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const MAX_ROOMS = 16;
const KNOWN_SCOPES = new Set<string>(PLUGIN_GRANT_SCOPES);
const TIMESTAMP_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/;

const GRANT_STATUSES = new Set<string>(["pending", "active", "expired", "revoked"]);

function grantApiError(code: string, message: string): XmuseApiError {
  return new XmuseApiError({ code, message, retryable: false, status: 422 });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function asNonEmptyString(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const cleaned = value.trim();
  return cleaned ? cleaned : null;
}

function asTimestamp(value: unknown): string | null {
  if (typeof value !== "string" || !TIMESTAMP_PATTERN.test(value)) return null;
  return Number.isFinite(Date.parse(value)) ? value : null;
}

function asNullableTimestamp(value: unknown): string | null | undefined {
  if (value === null) return null;
  if (value === undefined) return undefined;
  return asTimestamp(value) ?? undefined;
}

function normalizeGrantStatus(value: unknown): PluginGrantStatus {
  // An unrecognized status is treated as expired behaviourally and shown as
  // "未知状态" by the labels; the raw value never reaches shared state.
  return typeof value === "string" && GRANT_STATUSES.has(value)
    ? (value as PluginGrantStatus)
    : "unknown";
}

function normalizeRoomIds(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.length > MAX_ROOMS) return null;
  const ids = value.map(asNonEmptyString);
  return ids.every((id): id is string => id !== null) ? ids : null;
}

function normalizeScopes(value: unknown): PluginGrantScope[] | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  const scopes = new Set<PluginGrantScope>();
  for (const scope of value) {
    scopes.add(typeof scope === "string" && KNOWN_SCOPES.has(scope) ? (scope as PluginGrantScope) : "unknown");
  }
  return [...scopes];
}

/**
 * Strict `plugin_grant/v2` Grant normalizer. Returns null when the payload cannot be used.
 * No secret or pairing code ever appears in a Grant; the store keeps only Grants.
 */
export function normalizePluginGrant(value: unknown): PluginGrant | null {
  if (!isRecord(value)) return null;
  const grantId = asNonEmptyString(value.grant_id);
  const conversationIds = normalizeRoomIds(value.conversation_ids);
  const scopes = normalizeScopes(value.scopes);
  const host = typeof value.host === "string" && HOST_PATTERN.test(value.host)
    ? value.host
    : null;
  if (!grantId || !conversationIds || !scopes || !host) return null;
  const createdAt = asTimestamp(value.created_at);
  const expiresAt = asTimestamp(value.expires_at);
  if (!createdAt || !expiresAt) return null;
  const activatedAt = asNullableTimestamp(value.activated_at);
  const revokedAt = asNullableTimestamp(value.revoked_at);
  const lastUsedAt = asNullableTimestamp(value.last_used_at);
  if (activatedAt === undefined || revokedAt === undefined || lastUsedAt === undefined) {
    return null;
  }
  const useCount = typeof value.use_count === "number" &&
    Number.isSafeInteger(value.use_count) &&
    value.use_count >= 0
    ? value.use_count
    : null;
  if (useCount === null) return null;
  return {
    grantId,
    conversationIds,
    host,
    scopes,
    status: normalizeGrantStatus(value.status),
    createdAt,
    activatedAt,
    expiresAt,
    revokedAt,
    lastUsedAt,
    useCount
  };
}

export function normalizePluginGrantList(payload: unknown): PluginGrantList {
  if (!isRecord(payload) || payload.schema_version !== LIST_SCHEMA) {
    throw grantApiError("plugin_grant_response_invalid", "Grant list response is unusable");
  }
  if (!Array.isArray(payload.grants)) {
    throw grantApiError("plugin_grant_response_invalid", "Grant list response is unusable");
  }
  return {
    grants: payload.grants.flatMap((item) => {
      const grant = normalizePluginGrant(item);
      return grant ? [grant] : [];
    })
  };
}

function normalizeRevokedGrant(payload: unknown): PluginGrant {
  const grant = normalizePluginGrant(
    isRecord(payload) && "grant" in payload ? payload.grant : payload
  );
  if (!grant) {
    throw grantApiError("plugin_grant_response_invalid", "Grant revoke response is unusable");
  }
  return grant;
}

function clientOptions(options: ApiClientOptions): ApiClientOptions {
  return { ...options, timeoutMs: options.timeoutMs ?? 30_000 };
}

/** Lists the grants that cover one Room, or every grant of one host (main_window_control_v1 §2). */
export async function listPluginGrants(
  query: PluginGrantListQuery,
  options: ApiClientOptions = {}
): Promise<PluginGrantList> {
  const search = "conversationId" in query
    ? `conversation_id=${encodeURIComponent(query.conversationId)}`
    : `host=${encodeURIComponent(query.host)}`;
  const raw = await fetchJson<unknown>(
    `/api/room-plugin-grants?${search}`,
    { method: "GET", cache: "no-store", credentials: "same-origin" },
    clientOptions(options)
  );
  return normalizePluginGrantList(raw);
}

export async function revokePluginGrant(
  grantId: string,
  conversationId: string,
  options: ApiClientOptions = {}
): Promise<PluginGrant> {
  const raw = await fetchJson<unknown>(
    `/api/room-plugin-grants/${encodeURIComponent(grantId)}/revoke`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ conversation_id: conversationId }),
      cache: "no-store",
      credentials: "same-origin"
    },
    clientOptions(options)
  );
  return normalizeRevokedGrant(raw);
}
