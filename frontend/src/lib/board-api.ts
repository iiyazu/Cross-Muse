import {
  chatApiBaseUrl,
  fetchJson,
  XmuseApiError,
  type ApiClientOptions
} from "./api";
import type {
  AgentText,
  BoardAttentionItem,
  BoardContractDetail,
  BoardContractKind,
  BoardContractVersion,
  BoardCounters,
  BoardEvent,
  BoardLifecycle,
  BoardModule,
  BoardParticipant,
  BoardSplit,
  BoardSplitContract,
  BoardSplitDecideAction,
  BoardSplitModule,
  BoardStaleDependent,
  BoardState,
  BoardVerification,
  BoardVerificationStatus,
  RoomBoardCounts,
  RoomBoardProjection,
  RoomBoardSummary
} from "./board-types";

const PROJECTION_SCHEMA = "room_board_projection/v2";
const SUMMARY_SCHEMA = "room_board_summary/v1";
const CONTRACT_SCHEMA = "room_board_contract/v2";

function boardError(code: string, message: string): XmuseApiError {
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

function asBool(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

/** Defense in depth: strip C0/C1 (except \n \t), ANSI escapes and bidi controls. */
export function sanitizeAgentTextValue(value: string): string {
  let cleaned = value.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/g, "");
  cleaned = cleaned.replace(/\[[0-9;?]*[ -/]*[@-~]/g, "");
  cleaned = cleaned.replace(/\][^\u0007]*(?:\u0007|$)/g, "");
  cleaned = cleaned.replace(//g, "");
  cleaned = cleaned.replace(/[؜‎‏‪-‮⁦-⁩]/g, "");
  return cleaned;
}

const BOARD_STATES = new Set<string>([
  "assigned",
  "claimed",
  "working",
  "blocked",
  "ready_for_review",
  "done_claimed",
  "verifying",
  "waiting_for_provider",
  "verified",
  "verification_failed",
  "verification_error"
]);

const BOARD_LIFECYCLES = new Set<string>([
  "assigned",
  "claimed",
  "working",
  "blocked",
  "ready_for_review",
  "done_claimed"
]);

const VERIFICATION_STATUSES = new Set<string>([
  "none",
  "waiting_for_provider",
  "pending",
  "running",
  "passed",
  "failed",
  "error"
]);

const SPLIT_STATUSES = new Set<string>(["proposed", "approved", "rejected", "superseded"]);

const CONTRACT_KINDS = new Set<string>(["api_schema", "types", "protocol", "text"]);

const EVENT_KINDS = new Set<string>([
  "split_proposed",
  "split_rejected",
  "charter_assigned",
  "claimed",
  "contract_published",
  "contract_revised",
  "progress",
  "question",
  "verification"
]);

function normalizeState(value: unknown): BoardState {
  return typeof value === "string" && BOARD_STATES.has(value)
    ? (value as BoardState)
    : "unknown";
}

function normalizeLifecycle(value: unknown): BoardLifecycle {
  return typeof value === "string" && BOARD_LIFECYCLES.has(value)
    ? (value as BoardLifecycle)
    : "unknown";
}

function normalizeVerificationStatus(value: unknown): BoardVerificationStatus {
  return typeof value === "string" && VERIFICATION_STATUSES.has(value)
    ? (value as BoardVerificationStatus)
    : "unknown";
}

function normalizeAgentText(value: unknown): AgentText {
  const source = isRecord(value) ? value : {};
  const raw = typeof source.text === "string" ? source.text : "";
  return {
    text: sanitizeAgentTextValue(raw),
    untrusted: true,
    truncated: asBool(source.truncated, false)
  };
}

function normalizeNullableAgentText(value: unknown): AgentText | null {
  if (value === null || value === undefined) return null;
  if (!isRecord(value)) return null;
  return normalizeAgentText(value);
}

function normalizeCapabilities(value: unknown): RoomBoardProjection["capabilities"] {
  const source = isRecord(value) ? value : {};
  return {
    verification: asNonNegativeInt(source.verification),
    reviews: asNonNegativeInt(source.reviews),
    integrations: asNonNegativeInt(source.integrations),
    lessons: asNonNegativeInt(source.lessons)
  };
}

function normalizeParticipant(value: unknown): BoardParticipant | null {
  if (!isRecord(value)) return null;
  const participantId = asOptionalString(value.participant_id);
  if (!participantId) return null;
  return {
    participant_id: participantId,
    display_name: asString(value.display_name, participantId),
    provider_kind: asString(value.provider_kind, "unknown"),
    model_family: asString(value.model_family, "unknown"),
    role_preset: asOptionalString(value.role_preset),
    is_lead: asBool(value.is_lead, false)
  };
}

function normalizeVerification(value: unknown): BoardVerification {
  const source = isRecord(value) ? value : {};
  const stacked = Array.isArray(source.stacked)
    ? source.stacked.flatMap((item) => {
        if (!isRecord(item)) return [];
        const moduleId = asOptionalString(item.module_id);
        const verificationId = asOptionalString(item.verification_id);
        return moduleId && verificationId ? [{ module_id: moduleId, verification_id: verificationId }] : [];
      })
    : [];
  return {
    status: normalizeVerificationStatus(source.status),
    verification_id: asOptionalString(source.verification_id),
    reason_code: asOptionalString(source.reason_code),
    escalated: asBool(source.escalated, false),
    gate_ids: asStringList(source.gate_ids),
    stacked,
    head_commit: asOptionalString(source.head_commit),
    changed_path_count: asNonNegativeInt(source.changed_path_count),
    updated_at: asOptionalString(source.updated_at)
  };
}

function normalizeCounters(value: unknown): BoardCounters {
  const source = isRecord(value) ? value : {};
  return {
    done_reports: asNonNegativeInt(source.done_reports),
    passed: asNonNegativeInt(source.passed),
    failed: asNonNegativeInt(source.failed),
    superseded: asNonNegativeInt(source.superseded),
    errored: asNonNegativeInt(source.errored),
    rework_rounds: asNonNegativeInt(source.rework_rounds)
  };
}

function normalizeModuleAttention(value: unknown): BoardModule["attention"] {
  const source = isRecord(value) ? value : {};
  const kind =
    source.kind === "none" ||
    source.kind === "operator" ||
    source.kind === "lead" ||
    source.kind === "owner"
      ? source.kind
      : "unknown";
  return { kind, reason_code: asOptionalString(source.reason_code) };
}

function normalizeAttentionItem(value: unknown): BoardAttentionItem | null {
  if (!isRecord(value)) return null;
  const kind = value.kind;
  if (kind !== "operator" && kind !== "lead" && kind !== "owner") {
    if (typeof kind === "string") {
      const reasonCode = asOptionalString(value.reason_code);
      if (!reasonCode) return null;
      return {
        kind: "unknown",
        reason_code: reasonCode,
        module_id: asOptionalString(value.module_id),
        split_id: asOptionalString(value.split_id)
      };
    }
    return null;
  }
  const reasonCode = asOptionalString(value.reason_code);
  if (!reasonCode) return null;
  return {
    kind,
    reason_code: reasonCode,
    module_id: asOptionalString(value.module_id),
    split_id: asOptionalString(value.split_id)
  };
}

function normalizeModule(value: unknown): BoardModule | null {
  if (!isRecord(value)) return null;
  const moduleId = asOptionalString(value.module_id);
  if (!moduleId) return null;
  return {
    module_id: moduleId,
    title: normalizeAgentText(value.title),
    owner_participant_id: asString(value.owner_participant_id, ""),
    report_to: asOptionalString(value.report_to),
    charter_version: Math.max(1, asNonNegativeInt(value.charter_version, 1)),
    paths: asStringList(value.paths),
    provides: asStringList(value.provides),
    depends: asStringList(value.depends),
    lifecycle: normalizeLifecycle(value.lifecycle),
    verification: normalizeVerification(value.verification),
    counters: normalizeCounters(value.counters),
    state: normalizeState(value.state),
    attention: normalizeModuleAttention(value.attention)
  };
}

function normalizeContractKind(value: unknown): BoardContractKind {
  return typeof value === "string" && CONTRACT_KINDS.has(value)
    ? (value as BoardContractKind)
    : "unknown";
}

function normalizeSplitDecide(value: unknown): BoardSplitDecideAction | null | undefined {
  if (value === undefined || value === null) return undefined;
  if (!isRecord(value)) return undefined;
  return {
    available: asBool(value.available, false),
    method: asString(value.method, "POST"),
    href: asString(value.href, ""),
    expected_digest: asOptionalString(value.expected_digest),
    allowed_decisions: asStringList(value.allowed_decisions)
  };
}

function normalizeSplit(value: unknown): BoardSplit | null {
  if (!isRecord(value)) return null;
  const splitId = asOptionalString(value.split_id);
  if (!splitId) return null;
  const status =
    typeof value.status === "string" && SPLIT_STATUSES.has(value.status)
      ? value.status
      : "unknown";
  const modules: BoardSplitModule[] = Array.isArray(value.modules)
    ? value.modules.flatMap((item) => {
        if (!isRecord(item)) return [];
        const moduleId = asOptionalString(item.module_id);
        if (!moduleId) return [];
        return [
          {
            module_id: moduleId,
            title: normalizeAgentText(item.title),
            owner_participant_id: asString(item.owner_participant_id, ""),
            paths: asStringList(item.paths),
            provides: asStringList(item.provides),
            depends: asStringList(item.depends)
          }
        ];
      })
    : [];
  const contracts: BoardSplitContract[] = Array.isArray(value.contracts)
    ? value.contracts.flatMap((item) => {
        if (!isRecord(item)) return [];
        const contractId = asOptionalString(item.contract_id);
        if (!contractId) return [];
        return [
          {
            contract_id: contractId,
            provider_module_id: asString(item.provider_module_id, ""),
            kind: normalizeContractKind(item.kind),
            digest: asString(item.digest, "")
          }
        ];
      })
    : [];
  let actions: BoardSplit["actions"];
  if (isRecord(value.actions) && "decide" in value.actions) {
    const decide = normalizeSplitDecide(value.actions.decide);
    if (decide !== undefined) actions = { decide };
  }
  return {
    split_id: splitId,
    status: status as BoardSplit["status"],
    proposed_by_participant_id: asString(value.proposed_by_participant_id, ""),
    created_at: asString(value.created_at, ""),
    decided_at: asOptionalString(value.decided_at),
    digest: asString(value.digest, ""),
    decided_via: asOptionalString(value.decided_via),
    modules,
    contracts,
    ...(actions !== undefined ? { actions } : {})
  };
}

function normalizeStaleDependent(value: unknown): BoardStaleDependent | null {
  if (!isRecord(value)) return null;
  const contractId = asOptionalString(value.contract_id);
  const moduleId = asOptionalString(value.module_id);
  if (!contractId || !moduleId) return null;
  return {
    contract_id: contractId,
    revised_version: Math.max(2, asNonNegativeInt(value.revised_version, 2)),
    revised_seq: Math.max(1, asNonNegativeInt(value.revised_seq, 1)),
    module_id: moduleId,
    owner_participant_id: asString(value.owner_participant_id, "")
  };
}

function normalizeEvent(value: unknown): BoardEvent | null {
  if (!isRecord(value)) return null;
  if (typeof value.seq !== "number" || !Number.isSafeInteger(value.seq)) return null;
  const kind = asString(value.kind, "unknown");
  return {
    seq: value.seq,
    kind,
    typedKind: EVENT_KINDS.has(kind) ? (kind as BoardEvent["typedKind"]) : "unknown",
    at: asString(value.at, ""),
    module_id: asOptionalString(value.module_id),
    actor: {
      kind: asString(isRecord(value.actor) ? value.actor.kind : null, "unknown"),
      participant_id: isRecord(value.actor) ? asOptionalString(value.actor.participant_id) : null
    },
    data: isRecord(value.data) ? (value.data as Record<string, unknown>) : {}
  };
}

function checkSchemaMajor(value: unknown, expectedPrefix: string, expected: string): void {
  if (!isRecord(value) || typeof value.schema_version !== "string") {
    throw boardError("room_board_projection_invalid", `Unsupported board schema: missing schema_version`);
  }
  const actual = value.schema_version as string;
  if (actual === expected) return;
  const actualMajor = actual.split("/")[0];
  const expectedMajor = expectedPrefix.split("/")[0];
  void expectedMajor;
  throw boardError("room_board_projection_schema_unsupported", `Unsupported board schema: ${actual}`);
}

export function normalizeRoomBoardProjection(payload: unknown): RoomBoardProjection {
  if (!isRecord(payload)) {
    throw boardError("room_board_projection_invalid", "Board projection must be an object");
  }
  checkSchemaMajor(payload, "room_board_projection", PROJECTION_SCHEMA);
  if (payload.schema_version !== PROJECTION_SCHEMA) {
    throw boardError(
      "room_board_projection_schema_unsupported",
      `Unsupported board schema: ${String(payload.schema_version)}`
    );
  }
  const participants = Array.isArray(payload.participants)
    ? payload.participants.flatMap((item) => {
        const parsed = normalizeParticipant(item);
        return parsed ? [parsed] : [];
      })
    : [];
  const modules = Array.isArray(payload.modules)
    ? payload.modules.flatMap((item) => {
        const parsed = normalizeModule(item);
        return parsed ? [parsed] : [];
      })
    : [];
  const contracts = Array.isArray(payload.contracts)
    ? payload.contracts.flatMap((item) => {
        if (!isRecord(item)) return [];
        const contractId = asOptionalString(item.contract_id);
        if (!contractId) return [];
        return [
          {
            contract_id: contractId,
            latest_version: Math.max(1, asNonNegativeInt(item.latest_version, 1)),
            versions_count: Math.max(1, asNonNegativeInt(item.versions_count, 1)),
            digest: asString(item.digest, ""),
            provider_module_id: asString(item.provider_module_id, ""),
            kind: normalizeContractKind(item.kind),
            author_participant_id: asString(item.author_participant_id, ""),
            updated_at: asString(item.updated_at, "")
          }
        ];
      })
    : [];
  const splits = Array.isArray(payload.splits)
    ? payload.splits.flatMap((item) => {
        const parsed = normalizeSplit(item);
        return parsed ? [parsed] : [];
      })
    : [];
  const staleDependents = Array.isArray(payload.stale_dependents)
    ? payload.stale_dependents.flatMap((item) => {
        const parsed = normalizeStaleDependent(item);
        return parsed ? [parsed] : [];
      })
    : [];
  const attention = Array.isArray(payload.attention)
    ? payload.attention.flatMap((item) => {
        const parsed = normalizeAttentionItem(item);
        return parsed ? [parsed] : [];
      })
    : [];
  const events = Array.isArray(payload.events)
    ? payload.events.flatMap((item) => {
        const parsed = normalizeEvent(item);
        return parsed ? [parsed] : [];
      })
    : [];
  return {
    schema_version: PROJECTION_SCHEMA,
    metrics_version: asString(payload.metrics_version, "board_metrics/v1"),
    conversation_id: asString(payload.conversation_id, ""),
    server_time: asString(payload.server_time, ""),
    board_seq: asNonNegativeInt(payload.board_seq),
    revision: asString(payload.revision, ""),
    capabilities: normalizeCapabilities(payload.capabilities),
    participants,
    modules,
    contracts,
    splits,
    stale_dependents: staleDependents,
    attention,
    events
  };
}

const COUNT_KEYS = [
  "assigned",
  "claimed",
  "working",
  "blocked",
  "ready_for_review",
  "done_claimed",
  "verifying",
  "waiting_for_provider",
  "verified",
  "verification_failed",
  "verification_error"
] as const;

export function normalizeBoardSummary(payload: unknown): RoomBoardSummary {
  if (!isRecord(payload)) {
    throw boardError("room_board_summary_invalid", "Board summary must be an object");
  }
  if (payload.schema_version !== SUMMARY_SCHEMA) {
    throw boardError(
      "room_board_summary_schema_unsupported",
      `Unsupported board summary schema: ${String(payload.schema_version)}`
    );
  }
  const countsSource = isRecord(payload.counts) ? payload.counts : {};
  const counts = {} as RoomBoardCounts;
  for (const key of COUNT_KEYS) {
    counts[key] = asNonNegativeInt(countsSource[key]);
  }
  const attention = Array.isArray(payload.attention)
    ? payload.attention.flatMap((item) => {
        const parsed = normalizeAttentionItem(item);
        return parsed ? [parsed] : [];
      })
    : [];
  return {
    schema_version: SUMMARY_SCHEMA,
    conversation_id: asString(payload.conversation_id, ""),
    server_time: asString(payload.server_time, ""),
    board_seq: asNonNegativeInt(payload.board_seq),
    revision: asString(payload.revision, ""),
    capabilities: normalizeCapabilities(payload.capabilities),
    modules_total: asNonNegativeInt(payload.modules_total),
    counts,
    attention_total: asNonNegativeInt(payload.attention_total),
    attention
  };
}

function normalizeContractVersion(value: unknown): BoardContractVersion | null {
  if (!isRecord(value)) return null;
  if (typeof value.version !== "number" || value.version < 1) return null;
  return {
    version: Math.floor(value.version),
    digest: asString(value.digest, ""),
    author_participant_id: asString(value.author_participant_id, ""),
    created_at: asString(value.created_at, ""),
    rationale: normalizeNullableAgentText(value.rationale)
  };
}

export function normalizeBoardContract(payload: unknown): BoardContractDetail {
  if (!isRecord(payload)) {
    throw boardError("room_board_contract_invalid", "Board contract must be an object");
  }
  if (payload.schema_version !== CONTRACT_SCHEMA) {
    throw boardError(
      "room_board_contract_schema_unsupported",
      `Unsupported board contract schema: ${String(payload.schema_version)}`
    );
  }
  const versions = Array.isArray(payload.versions)
    ? payload.versions.flatMap((item) => {
        const parsed = normalizeContractVersion(item);
        return parsed ? [parsed] : [];
      })
    : [];
  return {
    schema_version: CONTRACT_SCHEMA,
    conversation_id: asString(payload.conversation_id, ""),
    contract_id: asString(payload.contract_id, ""),
    provider_module_id: asString(payload.provider_module_id, ""),
    kind: normalizeContractKind(payload.kind),
    versions,
    version: Math.max(1, asNonNegativeInt(payload.version, 1)),
    content: normalizeAgentText(payload.content)
  };
}

export async function fetchRoomBoardSummary(
  conversationId: string,
  options: ApiClientOptions = {}
): Promise<RoomBoardSummary> {
  const raw = await fetchJson<unknown>(
    `${chatApiBaseUrl(options)}/conversations/${encodeURIComponent(conversationId)}/board/summary`,
    { method: "GET", cache: "no-store" },
    options
  );
  return normalizeBoardSummary(raw);
}

export async function fetchRoomBoard(
  conversationId: string,
  options: ApiClientOptions = {}
): Promise<RoomBoardProjection> {
  const raw = await fetchJson<unknown>(
    `${chatApiBaseUrl(options)}/conversations/${encodeURIComponent(conversationId)}/board`,
    { method: "GET", cache: "no-store" },
    options
  );
  return normalizeRoomBoardProjection(raw);
}

export async function fetchBoardContract(
  conversationId: string,
  contractId: string,
  options: ApiClientOptions & { version?: number } = {}
): Promise<BoardContractDetail> {
  const params = new URLSearchParams();
  if (options.version !== undefined) params.set("version", String(options.version));
  const query = params.toString() ? `?${params.toString()}` : "";
  const { version: _ignored, ...clientOptions } = options;
  void _ignored;
  const raw = await fetchJson<unknown>(
    `${chatApiBaseUrl(clientOptions)}/conversations/${encodeURIComponent(
      conversationId
    )}/board/contracts/${encodeURIComponent(contractId)}${query}`,
    { method: "GET", cache: "no-store" },
    clientOptions
  );
  return normalizeBoardContract(raw);
}
