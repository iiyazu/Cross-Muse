import {
  chatApiBaseUrl,
  fetchJson,
  XmuseApiError,
  type ApiClientOptions
} from "./api";
import { isValidReviewPath, sanitizeReviewTextValue } from "./board-review-api";
import type { AgentText } from "./board-types";
import type {
  BoardIntegrationConflict,
  BoardIntegrationDetail,
  BoardIntegrationGate,
  BoardIntegrationGateStatus,
  BoardIntegrationItem,
  BoardIntegrationItemRole,
  BoardIntegrationItemStatus,
  BoardIntegrationJobStatus,
  BoardModuleIntegration,
  RoomBoardSummaryIntegration,
  RoomIntegration,
  RoomIntegrationLatest
} from "./board-integration-types";
import { emptyRoomIntegration, emptySummaryIntegration, noneModuleIntegration } from "./board-integration-types";

const INTEGRATION_SCHEMA = "room_board_integration/v1";

export const MODULE_INTEGRATION_STATUSES = new Set([
  "none",
  "waiting",
  "pending",
  "running",
  "integrated",
  "conflicted",
  "gate_failed",
  "error"
]);

export const INTEGRATION_JOB_STATUSES = new Set([
  "pending",
  "running",
  "integrated",
  "conflicted",
  "gate_failed",
  "error"
]);

export const INTEGRATION_ITEM_ROLES = new Set(["incumbent", "newcomer"]);

export const INTEGRATION_ITEM_STATUSES = new Set([
  "applied",
  "fell_back",
  "conflicted",
  "waiting",
  "not_applied"
]);

export const INTEGRATION_GATE_STATUSES = new Set([
  "passed",
  "failed",
  "error",
  "pending",
  "running",
  "skipped",
  "waiting"
]);

function integrationError(code: string, message: string): XmuseApiError {
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

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

function asNonNegativeInt(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : fallback;
}

function asOptionalInt(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) ? value : null;
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

function normalizeModuleStatus(value: unknown): {
  status: BoardModuleIntegration["status"];
  raw: string | null;
} {
  if (typeof value === "string" && MODULE_INTEGRATION_STATUSES.has(value)) {
    return { status: value as BoardModuleIntegration["status"], raw: null };
  }
  if (typeof value === "string" && value) {
    return { status: "unknown", raw: value };
  }
  return { status: "unknown", raw: null };
}

function normalizeJobStatus(value: unknown): {
  status: BoardIntegrationJobStatus;
  raw: string | null;
} {
  if (typeof value === "string" && INTEGRATION_JOB_STATUSES.has(value)) {
    return { status: value as BoardIntegrationJobStatus, raw: null };
  }
  if (typeof value === "string" && value) {
    return { status: "unknown", raw: value };
  }
  return { status: "unknown", raw: null };
}

function normalizeItemRole(value: unknown): {
  role: BoardIntegrationItemRole;
  raw: string | null;
} {
  if (typeof value === "string" && INTEGRATION_ITEM_ROLES.has(value)) {
    return { role: value as BoardIntegrationItemRole, raw: null };
  }
  if (typeof value === "string" && value) {
    return { role: "unknown", raw: value };
  }
  return { role: "unknown", raw: null };
}

function normalizeItemStatus(value: unknown): {
  status: BoardIntegrationItemStatus;
  raw: string | null;
} {
  if (typeof value === "string" && INTEGRATION_ITEM_STATUSES.has(value)) {
    return { status: value as BoardIntegrationItemStatus, raw: null };
  }
  if (typeof value === "string" && value) {
    return { status: "unknown", raw: value };
  }
  return { status: "unknown", raw: null };
}

function normalizeGateStatus(value: unknown): {
  status: BoardIntegrationGateStatus;
  raw: string | null;
} {
  if (typeof value === "string" && INTEGRATION_GATE_STATUSES.has(value)) {
    return { status: value as BoardIntegrationGateStatus, raw: null };
  }
  if (typeof value === "string" && value) {
    return { status: "unknown", raw: value };
  }
  return { status: "unknown", raw: null };
}

export function normalizeBoardModuleIntegration(value: unknown): BoardModuleIntegration {
  if (!isRecord(value)) return noneModuleIntegration();
  const status = normalizeModuleStatus(value.status);
  return {
    status: status.status,
    statusRaw: status.raw,
    integration_id: asOptionalString(value.integration_id),
    verification_id: asOptionalString(value.verification_id),
    integrated_verification_id: asOptionalString(value.integrated_verification_id),
    reason_code: asOptionalString(value.reason_code),
    conflict_path_count: asNonNegativeInt(value.conflict_path_count),
    gate_ids: asStringList(value.gate_ids),
    updated_at: asOptionalString(value.updated_at)
  };
}

function normalizeRoomIntegrationLatest(value: unknown): RoomIntegrationLatest | null {
  if (!isRecord(value)) return null;
  const integrationId = asOptionalString(value.integration_id);
  if (!integrationId) return null;
  const status = normalizeJobStatus(value.status);
  return {
    integration_id: integrationId,
    status: status.status,
    statusRaw: status.raw,
    reason_code: asOptionalString(value.reason_code),
    module_count: asNonNegativeInt(value.module_count),
    finished_at: asOptionalString(value.finished_at)
  };
}

export function normalizeRoomIntegration(value: unknown): RoomIntegration {
  if (!isRecord(value)) return emptyRoomIntegration();
  return {
    green_head_commit: asOptionalString(value.green_head_commit),
    latest: normalizeRoomIntegrationLatest(value.latest)
  };
}

export function normalizeBoardSummaryIntegration(value: unknown): RoomBoardSummaryIntegration {
  if (!isRecord(value)) return emptySummaryIntegration();
  const rawStatus = value.status;
  if (rawStatus === null || rawStatus === undefined) {
    return {
      status: null,
      statusRaw: null,
      green_head_commit: asOptionalString(value.green_head_commit)
    };
  }
  const status = normalizeJobStatus(rawStatus);
  return {
    status: status.status,
    statusRaw: status.raw,
    green_head_commit: asOptionalString(value.green_head_commit)
  };
}

function normalizeIntegrationConflict(value: unknown): BoardIntegrationConflict | null {
  if (!isRecord(value)) return null;
  if (typeof value.path !== "string") return null;
  return {
    path: value.path,
    attributed_module_ids: asStringList(value.attributed_module_ids)
  };
}

function normalizeIntegrationItem(value: unknown): BoardIntegrationItem | null {
  if (!isRecord(value)) return null;
  const moduleId = asOptionalString(value.module_id);
  const verificationId = asOptionalString(value.verification_id);
  if (!moduleId || !verificationId) return null;
  const role = normalizeItemRole(value.role);
  const status = normalizeItemStatus(value.status);
  const conflicts = Array.isArray(value.conflicts)
    ? value.conflicts.flatMap((item) => {
        const parsed = normalizeIntegrationConflict(item);
        return parsed ? [parsed] : [];
      })
    : [];
  return {
    module_id: moduleId,
    verification_id: verificationId,
    order: Math.max(1, asNonNegativeInt(value.order, 1)),
    role: role.role,
    roleRaw: role.raw,
    status: status.status,
    statusRaw: status.raw,
    applied_verification_id: asOptionalString(value.applied_verification_id),
    conflicts,
    conflicts_total: asNonNegativeInt(value.conflicts_total)
  };
}

function normalizeIntegrationGate(value: unknown): BoardIntegrationGate | null {
  if (!isRecord(value)) return null;
  const gateId = asOptionalString(value.gate_id);
  if (!gateId) return null;
  const status = normalizeGateStatus(value.status);
  return {
    gate_id: gateId,
    status: status.status,
    statusRaw: status.raw,
    exit_code: asOptionalInt(value.exit_code),
    reason_code: asOptionalString(value.reason_code),
    output_tail: normalizeNullableAgentText(value.output_tail)
  };
}

export function normalizeBoardIntegrationDetail(payload: unknown): BoardIntegrationDetail {
  if (!isRecord(payload)) {
    throw integrationError("room_board_integration_invalid", "Board integration must be an object");
  }
  if (payload.schema_version !== INTEGRATION_SCHEMA) {
    throw integrationError(
      "room_board_integration_schema_unsupported",
      `Unsupported board integration schema: ${String(payload.schema_version)}`
    );
  }
  const status = normalizeJobStatus(payload.status);
  const items = Array.isArray(payload.items)
    ? payload.items.flatMap((item) => {
        const parsed = normalizeIntegrationItem(item);
        return parsed ? [parsed] : [];
      })
    : [];
  const gates = Array.isArray(payload.gates)
    ? payload.gates.flatMap((item) => {
        const parsed = normalizeIntegrationGate(item);
        return parsed ? [parsed] : [];
      })
    : [];
  return {
    schema_version: INTEGRATION_SCHEMA,
    conversation_id: asString(payload.conversation_id, ""),
    integration_id: asString(payload.integration_id, ""),
    status: status.status,
    statusRaw: status.raw,
    reason_code: asOptionalString(payload.reason_code),
    green_head_commit: asOptionalString(payload.green_head_commit),
    result_commit: asOptionalString(payload.result_commit),
    items,
    gates,
    attempt_count: asNonNegativeInt(payload.attempt_count),
    created_at: asString(payload.created_at, ""),
    finished_at: asOptionalString(payload.finished_at)
  };
}

/**
 * Escape every UTF-16 code unit the review-path pattern rejects as `<U+XXXX>`
 * (uppercase hex, at least 4 digits). Defence in depth for conflict paths:
 * the server never lists such a path, but the UI must still render it safely.
 */
export function escapeInvalidIntegrationPath(path: string): string {
  const allowedSingle = /[^\\\u0000-\u001f\u007f-\u009f\u00ad\u0600-\u0605\u061c\u06dd\u070f\u0890-\u0891\u08e2\u180e\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb]/;
  let out = "";
  for (let index = 0; index < path.length; index += 1) {
    const unit = path[index] as string;
    if (allowedSingle.test(unit)) {
      out += unit;
    } else {
      const code = (path.charCodeAt(index) as number).toString(16).toUpperCase().padStart(4, "0");
      out += `<U+${code}>`;
    }
  }
  return out;
}

export function isValidIntegrationPath(path: string): boolean {
  return isValidReviewPath(path);
}

export async function fetchBoardIntegrationDetail(
  conversationId: string,
  integrationId: string,
  options: ApiClientOptions = {}
): Promise<BoardIntegrationDetail> {
  const raw = await fetchJson<unknown>(
    `${chatApiBaseUrl(options)}/conversations/${encodeURIComponent(
      conversationId
    )}/board/integrations/${encodeURIComponent(integrationId)}`,
    { method: "GET", cache: "no-store" },
    options
  );
  return normalizeBoardIntegrationDetail(raw);
}
