import {
  fetchJson,
  XmuseApiError,
  type ApiClientOptions
} from "./api";
import {
  PLUGIN_GRANT_SCOPE,
  type PluginGrant,
  type PluginGrantIssue,
  type PluginGrantList,
  type PluginGrantStatus
} from "./grant-types";

const ISSUE_SCHEMA = "plugin_grant_issue/v1";
const LIST_SCHEMA = "plugin_grant_list/v1";

const HOST_PATTERN = /^[a-z0-9][a-z0-9_-]{0,31}$/;
const PAIRING_PATTERN = /^[ABCDEFGHJKMNPQRSTVWXYZ23456789]{4}-[ABCDEFGHJKMNPQRSTVWXYZ23456789]{4}$/;
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

/**
 * Strict Grant normalizer. Returns null when the payload cannot be used.
 * The pairing code and secret never appear here; the store keeps only Grants.
 */
export function normalizePluginGrant(value: unknown): PluginGrant | null {
  if (!isRecord(value)) return null;
  const grantId = asNonEmptyString(value.grant_id);
  const conversationId = asNonEmptyString(value.conversation_id);
  const host = typeof value.host === "string" && HOST_PATTERN.test(value.host)
    ? value.host
    : null;
  if (!grantId || !conversationId || !host) return null;
  if (value.scope !== PLUGIN_GRANT_SCOPE) return null;
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
    conversationId,
    host,
    scope: PLUGIN_GRANT_SCOPE,
    status: normalizeGrantStatus(value.status),
    createdAt,
    activatedAt,
    expiresAt,
    revokedAt,
    lastUsedAt,
    useCount
  };
}

function asPairingCode(value: unknown): string | null {
  return typeof value === "string" && PAIRING_PATTERN.test(value) ? value : null;
}

/**
 * Normalizes a `plugin_grant_issue/v1` payload. The caller must keep the
 * returned pairing code in component state only; it is dropped from the store.
 */
export function normalizePluginGrantIssue(payload: unknown): PluginGrantIssue {
  if (!isRecord(payload) || payload.schema_version !== ISSUE_SCHEMA) {
    throw grantApiError("plugin_grant_response_invalid", "Grant issue response is unusable");
  }
  const grant = normalizePluginGrant(payload.grant);
  const pairingCode = asPairingCode(payload.pairing_code);
  const pairingExpiresAt = asTimestamp(payload.pairing_expires_at);
  if (!grant || !pairingCode || !pairingExpiresAt) {
    throw grantApiError("plugin_grant_response_invalid", "Grant issue response is unusable");
  }
  return { grant, pairingCode, pairingExpiresAt };
}

export function normalizePluginGrantList(payload: unknown): PluginGrantList {
  if (!isRecord(payload) || payload.schema_version !== LIST_SCHEMA) {
    throw grantApiError("plugin_grant_response_invalid", "Grant list response is unusable");
  }
  const conversationId = asNonEmptyString(payload.conversation_id);
  if (!conversationId || !Array.isArray(payload.grants)) {
    throw grantApiError("plugin_grant_response_invalid", "Grant list response is unusable");
  }
  return {
    conversationId,
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

export type IssuePluginGrantArgs = {
  conversationId: string;
  host: string;
  ttlSeconds: number;
};

export async function issuePluginGrant(
  args: IssuePluginGrantArgs,
  options: ApiClientOptions = {}
): Promise<PluginGrantIssue> {
  const raw = await fetchJson<unknown>(
    "/api/room-plugin-grants",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        conversation_id: args.conversationId,
        host: args.host,
        scope: PLUGIN_GRANT_SCOPE,
        ttl_seconds: args.ttlSeconds
      }),
      cache: "no-store",
      credentials: "same-origin"
    },
    clientOptions(options)
  );
  return normalizePluginGrantIssue(raw);
}

export async function listPluginGrants(
  conversationId: string,
  options: ApiClientOptions = {}
): Promise<PluginGrantList> {
  const raw = await fetchJson<unknown>(
    `/api/room-plugin-grants?conversation_id=${encodeURIComponent(conversationId)}`,
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
