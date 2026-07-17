import type {
  ConversationSummary,
  FrontendEventsResponse,
  JsonRecord,
  RoomChatProjection,
  RoomCodexActionDescriptor,
  RoomCodexActionResult,
  RoomCodexCapabilityId,
  RoomCodexProjection,
  RoomCodexSafeRequestByCapability,
  RoomControlActionDescriptor,
  RoomControlResult,
  RoomExecutionActionResult,
  RoomExecutionCancelDescriptor,
  RoomExecutionCandidateProjection,
  RoomExecutionDecisionDescriptor,
  RoomExecutionListProjection,
  RoomExecutionPolicyMode,
  RoomExecutionPolicyUpdateDescriptor,
  RoomListProjection,
  RoomMessageReceipt,
  RoomMemoryRebuildActionResult,
  RoomMemoryRebuildDescriptor,
  RoomMemoryProjection,
  RoomMemoryResolveDescriptor,
  RoomMemoryResolveResult,
  RoomOperationsProjection,
  RoomRuntimeRecoverDescriptor,
  RoomRuntimeRecoverResult,
  RoomSetupOptions,
  XmuseApiErrorShape
} from "./types";

type Fetcher = typeof fetch;

export type ApiClientOptions = {
  fetcher?: Fetcher;
  chatApiBaseUrl?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
};

type CreateConversationOptions = ApiClientOptions & {
  rosterTemplateId?: string | null;
  initialParticipants?: Array<Record<string, unknown>> | null;
  clientRequestId?: string;
};

export class XmuseApiError extends Error implements XmuseApiErrorShape {
  code: string;
  retryable: boolean;
  status: number;

  constructor(error: XmuseApiErrorShape) {
    super(error.message);
    this.name = "XmuseApiError";
    this.code = error.code;
    this.retryable = error.retryable;
    this.status = error.status;
  }
}

const DEFAULT_CHAT_API_BASE_URL =
  process.env.NEXT_PUBLIC_XMUSE_CHAT_API_BASE_URL ?? "http://127.0.0.1:8201/api/chat";

function trimSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function fetcherFrom(options: ApiClientOptions): Fetcher {
  return options.fetcher ?? fetch;
}

export function chatApiBaseUrl(options: ApiClientOptions = {}): string {
  return trimSlash(options.chatApiBaseUrl ?? DEFAULT_CHAT_API_BASE_URL);
}

export function roomAgentStreamsUrl(
  conversationId: string,
  options: ApiClientOptions = {}
): string {
  return `${chatApiBaseUrl(options)}/conversations/${encodeURIComponent(
    conversationId
  )}/agent-streams`;
}

async function readJson(response: Response): Promise<unknown> {
  const value = await response.text();
  if (!value) return {};
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return { message: value };
  }
}

function stringFrom(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

export async function parseApiError(response: Response): Promise<XmuseApiErrorShape> {
  const payload = await readJson(response);
  const detail =
    payload && typeof payload === "object" && "detail" in payload
      ? (payload as { detail?: unknown }).detail
      : payload;
  const detailRecord = detail && typeof detail === "object" ? (detail as JsonRecord) : null;
  const code =
    stringFrom(detailRecord?.code) ??
    (typeof detail === "string" ? detail : undefined) ??
    `http_${response.status}`;
  const message =
    stringFrom(detailRecord?.message) ??
    (typeof detail === "string" ? detail : undefined) ??
    response.statusText ??
    "请求失败";
  return {
    code,
    message,
    retryable: response.status >= 500 && response.status !== 501,
    status: response.status
  };
}

async function fetchJson<T>(url: string, init: RequestInit, options: ApiClientOptions): Promise<T> {
  const controller = new AbortController();
  const callerSignal = init.signal ?? options.signal;
  let deadlineExpired = false;
  const abortFromCaller = () => controller.abort(callerSignal?.reason);
  if (callerSignal?.aborted) abortFromCaller();
  else callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
  const timeout = options.timeoutMs === 0 ? null : setTimeout(() => {
    deadlineExpired = true;
    controller.abort();
  }, options.timeoutMs ?? 10_000);
  try {
    const response = await fetcherFrom(options)(url, {
      ...init,
      signal: controller.signal
    });
    if (!response.ok) throw new XmuseApiError(await parseApiError(response));
    return (await readJson(response)) as T;
  } catch (error) {
    if (deadlineExpired) {
      throw new XmuseApiError({
        code: "frontend_request_timeout",
        message: "请求超时，请稍后重试。",
        retryable: true,
        status: 0
      });
    }
    throw error;
  } finally {
    if (timeout) clearTimeout(timeout);
    callerSignal?.removeEventListener("abort", abortFromCaller);
  }
}

export async function fetchRooms(options: ApiClientOptions = {}): Promise<RoomListProjection> {
  return fetchJson<RoomListProjection>(
    `${chatApiBaseUrl(options)}/rooms`,
    { method: "GET", cache: "no-store" },
    options
  );
}

export async function fetchRoomOperations(
  options: ApiClientOptions = {}
): Promise<RoomOperationsProjection> {
  return fetchJson<RoomOperationsProjection>(
    `${chatApiBaseUrl(options)}/runtime/operations`,
    { method: "GET", cache: "no-store" },
    options
  );
}

export async function fetchRoomExecutions(
  conversationId: string,
  options: ApiClientOptions & { limit?: number; cursor?: string | null } = {}
): Promise<RoomExecutionListProjection> {
  const params = new URLSearchParams({
    limit: String(Math.max(1, Math.min(50, options.limit ?? 20)))
  });
  if (options.cursor) params.set("cursor", options.cursor);
  return fetchJson<RoomExecutionListProjection>(
    `${chatApiBaseUrl(options)}/conversations/${encodeURIComponent(
      conversationId
    )}/executions?${params.toString()}`,
    { method: "GET", cache: "no-store" },
    options
  );
}

export async function fetchRoomMemory(
  conversationId: string,
  options: ApiClientOptions = {}
): Promise<RoomMemoryProjection> {
  return fetchJson<RoomMemoryProjection>(
    `${chatApiBaseUrl(options)}/conversations/${encodeURIComponent(conversationId)}/memory`,
    { method: "GET", cache: "no-store" },
    options
  );
}

export async function fetchRoomCodexAgents(
  conversationId: string,
  options: ApiClientOptions & {
    limit?: number;
    beforeEventSeq?: number;
    afterEventSeq?: number;
  } = {}
): Promise<RoomCodexProjection> {
  if (options.beforeEventSeq !== undefined && options.afterEventSeq !== undefined) {
    throw new XmuseApiError({
      code: "room_codex_projection_cursor_conflict",
      message: "Codex event cursors cannot be used in both directions",
      retryable: false,
      status: 400
    });
  }
  const params = new URLSearchParams({
    limit: String(Math.max(1, Math.min(100, options.limit ?? 100)))
  });
  if (options.beforeEventSeq !== undefined) {
    params.set("before_event_seq", String(Math.max(1, options.beforeEventSeq)));
  }
  if (options.afterEventSeq !== undefined) {
    params.set("after_event_seq", String(Math.max(0, options.afterEventSeq)));
  }
  const projection = await fetchJson<RoomCodexProjection>(
    `${chatApiBaseUrl(options)}/conversations/${encodeURIComponent(
      conversationId
    )}/codex-agents?${params.toString()}`,
    { method: "GET", cache: "no-store" },
    options
  );
  if (projection.schema_version !== "room_codex_projection/v1") {
    throw new XmuseApiError({
      code: "room_codex_projection_schema_unsupported",
      message: "This Codex Agent projection version is not supported",
      retryable: false,
      status: 422
    });
  }
  return projection;
}

const OPAQUE_CODEX_GUARD = /^sha256:[0-9a-f]{64}$/;

function validCodexGuard(value: string | null, required = false): boolean {
  return value === null ? !required : OPAQUE_CODEX_GUARD.test(value);
}

export async function submitRoomCodexAction<K extends RoomCodexCapabilityId>(
  participantId: string,
  capabilityId: K,
  request: RoomCodexSafeRequestByCapability[K],
  descriptor: RoomCodexActionDescriptor,
  options: ApiClientOptions & {
    clientActionId?: string;
    confirmedPendingObservations?: boolean;
  } = {}
): Promise<RoomCodexActionResult> {
  const expectedHref = `/api/chat/operator/room-participants/${encodeURIComponent(
    participantId
  )}/codex-actions`;
  const confirmation = options.confirmedPendingObservations === true;
  const guardsValid =
    validCodexGuard(descriptor.expected_session_guard, true) &&
    validCodexGuard(descriptor.expected_goal_guard) &&
    validCodexGuard(descriptor.expected_settings_guard) &&
    validCodexGuard(descriptor.expected_turn_guard);
  if (
    !descriptor.available ||
    descriptor.method !== "POST" ||
    descriptor.href !== expectedHref ||
    descriptor.capability_id !== capabilityId ||
    !guardsValid ||
    (descriptor.confirmation_required && !confirmation)
  ) {
    throw new XmuseApiError({
      code: "room_codex_action_descriptor_invalid",
      message: "Native Codex action is unavailable or its projection guard is invalid",
      retryable: false,
      status: 400
    });
  }
  return fetchJson<RoomCodexActionResult>(
    `/api/room-participants/${encodeURIComponent(participantId)}/codex-actions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_action_id: options.clientActionId ?? `ui_codex_action_${crypto.randomUUID()}`,
        capability_id: capabilityId,
        request,
        expected_session_guard: descriptor.expected_session_guard,
        expected_goal_guard: descriptor.expected_goal_guard,
        expected_settings_guard: descriptor.expected_settings_guard,
        expected_turn_guard: descriptor.expected_turn_guard,
        confirmed_pending_observations: confirmation
      }),
      cache: "no-store",
      credentials: "same-origin"
    },
    { ...options, timeoutMs: options.timeoutMs ?? 30_000 }
  );
}

export async function resolveRoomMemoryCandidate(
  candidateId: string,
  decision: "approve" | "reject",
  descriptor: RoomMemoryResolveDescriptor,
  options: ApiClientOptions & { clientActionId?: string } = {}
): Promise<RoomMemoryResolveResult> {
  const expectedHref = `/api/chat/operator/memory-candidates/${encodeURIComponent(
    candidateId
  )}/resolve`;
  if (
    !descriptor.available ||
    descriptor.method !== "POST" ||
    descriptor.href !== expectedHref ||
    !descriptor.allowed_decisions.includes(decision)
  ) {
    throw new XmuseApiError({
      code: "room_memory_resolve_descriptor_invalid",
      message: "Memory candidate is no longer actionable",
      retryable: false,
      status: 400
    });
  }
  return fetchJson<RoomMemoryResolveResult>(
    `/api/room-memory-candidates/${encodeURIComponent(candidateId)}/resolve`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_action_id: options.clientActionId ?? `ui_memory_resolve_${crypto.randomUUID()}`,
        decision,
        expected_digest: descriptor.expected_digest,
        expected_revision: descriptor.expected_revision
      }),
      cache: "no-store",
      credentials: "same-origin"
    },
    { ...options, timeoutMs: options.timeoutMs ?? 30_000 }
  );
}

export async function rebuildRoomMemoryIndex(
  descriptor: RoomMemoryRebuildDescriptor,
  options: ApiClientOptions & { clientActionId?: string } = {}
): Promise<RoomMemoryRebuildActionResult> {
  if (
    !descriptor.available ||
    descriptor.pending ||
    descriptor.method !== "POST" ||
    descriptor.href !== "/api/chat/operator/memory-runtime/rebuild" ||
    !descriptor.expected_incident_id
  ) {
    throw new XmuseApiError({
      code: "room_memory_rebuild_descriptor_invalid",
      message: "MemoryOS derived index is no longer rebuildable",
      retryable: false,
      status: 400
    });
  }
  return fetchJson<RoomMemoryRebuildActionResult>(
    "/api/room-memory/rebuild",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_action_id: options.clientActionId ?? `ui_memory_rebuild_${crypto.randomUUID()}`,
        expected_incident_id: descriptor.expected_incident_id
      }),
      cache: "no-store",
      credentials: "same-origin"
    },
    { ...options, timeoutMs: options.timeoutMs ?? 35_000 }
  );
}

export async function fetchRoomExecutionCandidate(
  candidateId: string,
  options: ApiClientOptions = {}
): Promise<RoomExecutionCandidateProjection> {
  return fetchJson<RoomExecutionCandidateProjection>(
    `${chatApiBaseUrl(options)}/execution-candidates/${encodeURIComponent(candidateId)}`,
    { method: "GET", cache: "no-store" },
    options
  );
}

export async function updateRoomExecutionPolicy(
  conversationId: string,
  mode: RoomExecutionPolicyMode,
  descriptor: RoomExecutionPolicyUpdateDescriptor,
  options: ApiClientOptions & { clientActionId?: string } = {}
): Promise<RoomExecutionActionResult> {
  const expectedHref = `/api/chat/operator/conversations/${encodeURIComponent(
    conversationId
  )}/execution-policy`;
  if (
    !descriptor.available ||
    descriptor.method !== "PUT" ||
    descriptor.href !== expectedHref ||
    !descriptor.allowed_modes.includes(mode)
  ) {
    throw new XmuseApiError({
      code: "room_execution_policy_descriptor_invalid",
      message: "Room execution policy is unavailable or its revision guard is invalid",
      retryable: false,
      status: 400
    });
  }
  return fetchJson<RoomExecutionActionResult>(
    `/api/room-execution-policy/${encodeURIComponent(conversationId)}`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_action_id: options.clientActionId ?? `ui_execution_policy_${crypto.randomUUID()}`,
        mode,
        expected_revision: descriptor.expected_revision
      }),
      cache: "no-store",
      credentials: "same-origin"
    },
    { ...options, timeoutMs: options.timeoutMs ?? 30_000 }
  );
}

export async function decideRoomExecutionCandidate(
  candidateId: string,
  decision: "execute" | "reject",
  descriptor: RoomExecutionDecisionDescriptor,
  options: ApiClientOptions & { clientActionId?: string } = {}
): Promise<RoomExecutionActionResult> {
  const expectedHref = `/api/chat/operator/execution-candidates/${encodeURIComponent(
    candidateId
  )}/decision`;
  if (
    !descriptor.available ||
    descriptor.method !== "POST" ||
    descriptor.href !== expectedHref
  ) {
    throw new XmuseApiError({
      code: "room_execution_decision_descriptor_invalid",
      message: "Execution candidate is no longer actionable",
      retryable: false,
      status: 400
    });
  }
  return fetchJson<RoomExecutionActionResult>(
    `/api/room-execution-candidates/${encodeURIComponent(candidateId)}/decision`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_action_id: options.clientActionId ?? `ui_execution_decision_${crypto.randomUUID()}`,
        decision,
        expected_candidate_digest: descriptor.expected_candidate_digest,
        expected_candidate_revision: descriptor.expected_candidate_revision,
        expected_policy_revision: descriptor.expected_policy_revision
      }),
      cache: "no-store",
      credentials: "same-origin"
    },
    { ...options, timeoutMs: options.timeoutMs ?? 30_000 }
  );
}

export async function cancelRoomExecutionRun(
  runId: string,
  descriptor: RoomExecutionCancelDescriptor,
  options: ApiClientOptions & { clientActionId?: string } = {}
): Promise<RoomExecutionActionResult> {
  const expectedHref = `/api/chat/operator/execution-runs/${encodeURIComponent(runId)}/cancel`;
  if (!descriptor.available || descriptor.method !== "POST" || descriptor.href !== expectedHref) {
    throw new XmuseApiError({
      code: "room_execution_cancel_descriptor_invalid",
      message: "Execution run is no longer cancellable",
      retryable: false,
      status: 400
    });
  }
  return fetchJson<RoomExecutionActionResult>(
    `/api/room-execution-runs/${encodeURIComponent(runId)}/cancel`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_action_id: options.clientActionId ?? `ui_execution_cancel_${crypto.randomUUID()}`,
        expected_run_state: descriptor.expected_run_state,
        expected_run_revision: descriptor.expected_run_revision
      }),
      cache: "no-store",
      credentials: "same-origin"
    },
    { ...options, timeoutMs: options.timeoutMs ?? 30_000 }
  );
}

export async function recoverRoomRuntime(
  descriptor: RoomRuntimeRecoverDescriptor,
  options: ApiClientOptions & { clientActionId?: string } = {}
): Promise<RoomRuntimeRecoverResult> {
  if (
    !descriptor.available ||
    descriptor.method !== "POST" ||
    descriptor.href !== "/api/chat/operator/room-runtime/recover" ||
    !descriptor.expected_incident_id
  ) {
    throw new XmuseApiError({
      code: "room_runtime_recover_descriptor_invalid",
      message: "Room runtime recovery is unavailable or its incident guard is invalid",
      retryable: false,
      status: 400
    });
  }
  return fetchJson<RoomRuntimeRecoverResult>(
    "/api/room-runtime/recover",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_action_id: options.clientActionId ?? `ui_runtime_recover_${crypto.randomUUID()}`,
        expected_incident_id: descriptor.expected_incident_id
      }),
      cache: "no-store",
      credentials: "same-origin"
    },
    { ...options, timeoutMs: options.timeoutMs ?? 35_000 }
  );
}

export async function fetchRoomProjection(
  conversationId: string,
  options: ApiClientOptions & {
    limit?: number;
    beforeRoomSeq?: number;
    afterRoomSeq?: number;
  } = {}
): Promise<RoomChatProjection> {
  if (options.beforeRoomSeq !== undefined && options.afterRoomSeq !== undefined) {
    throw new XmuseApiError({
      code: "room_projection_cursor_conflict",
      message: "before_room_seq 与 after_room_seq 不能同时使用",
      retryable: false,
      status: 400
    });
  }
  const params = new URLSearchParams({
    limit: String(Math.max(1, Math.min(100, options.limit ?? 60)))
  });
  if (options.beforeRoomSeq !== undefined) {
    params.set("before_room_seq", String(Math.max(0, options.beforeRoomSeq)));
  }
  if (options.afterRoomSeq !== undefined) {
    params.set("after_room_seq", String(Math.max(0, options.afterRoomSeq)));
  }
  return fetchJson<RoomChatProjection>(
    `${chatApiBaseUrl(options)}/conversations/${encodeURIComponent(
      conversationId
    )}/room-projection?${params.toString()}`,
    { method: "GET", cache: "no-store" },
    options
  );
}

export async function submitRoomObservationControl(
  observationId: string,
  action: "cancel" | "retry",
  descriptor: RoomControlActionDescriptor,
  options: ApiClientOptions & { clientActionId?: string } = {}
): Promise<RoomControlResult> {
  const upstreamHref = `/api/chat/operator/room-observations/${encodeURIComponent(
    observationId
  )}/${action}`;
  if (!descriptor.available || descriptor.href !== upstreamHref) {
    throw new XmuseApiError({
      code: "room_control_descriptor_invalid",
      message: "Room control descriptor is unavailable or does not match the requested action",
      retryable: false,
      status: 400
    });
  }
  return fetchJson<RoomControlResult>(
    `/api/room-observations/${encodeURIComponent(observationId)}/${action}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        client_action_id: options.clientActionId ?? `ui_room_control_${crypto.randomUUID()}`,
        expected_state: descriptor.expected_state,
        expected_attempt_count: descriptor.expected_attempt_count,
        expected_control_seq: descriptor.expected_control_seq
      }),
      cache: "no-store",
      credentials: "same-origin"
    },
    { ...options, timeoutMs: options.timeoutMs ?? 19_000 }
  );
}

export async function createConversation(
  title: string,
  options: CreateConversationOptions = {}
): Promise<ConversationSummary> {
  return fetchJson<ConversationSummary>(
    "/api/rooms",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title,
        client_request_id: options.clientRequestId ?? `ui_room_create_${crypto.randomUUID()}`,
        ...(options.initialParticipants
          ? { initial_participants: options.initialParticipants }
          : { roster_template_id: options.rosterTemplateId ?? "builtin.development" })
      }),
      cache: "no-store",
      credentials: "same-origin"
    },
    { ...options, timeoutMs: options.timeoutMs ?? 14_000 }
  );
}

export async function fetchRoomSetupOptions(
  options: ApiClientOptions = {}
): Promise<RoomSetupOptions> {
  const payload = await fetchJson<RoomSetupOptions>(
    `${chatApiBaseUrl(options)}/room-setup-options`,
    { method: "GET", cache: "no-store" },
    options
  );
  if (payload.schema_version !== "room_setup_options/v1") {
    throw new XmuseApiError({
      code: "room_setup_options_schema_unsupported",
      message: "Room setup options use an unsupported schema",
      retryable: false,
      status: 422
    });
  }
  return payload;
}

export async function fetchEvents(
  conversationId: string,
  afterSeq: number,
  options: ApiClientOptions & { limit?: number } = {}
): Promise<FrontendEventsResponse> {
  const params = new URLSearchParams({
    after_seq: String(Math.max(0, afterSeq)),
    limit: String(options.limit ?? 100)
  });
  return fetchJson<FrontendEventsResponse>(
    `${chatApiBaseUrl(options)}/conversations/${encodeURIComponent(
      conversationId
    )}/events?${params.toString()}`,
    { method: "GET", cache: "no-store" },
    options
  );
}

export async function sendThreadMessage(
  conversationId: string,
  message: string,
  options: ApiClientOptions & { clientRequestId?: string } = {}
): Promise<RoomMessageReceipt> {
  return fetchJson<RoomMessageReceipt>(
    `/api/rooms/${encodeURIComponent(conversationId)}/messages`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        client_request_id: options.clientRequestId ?? `ui_${crypto.randomUUID()}`
      }),
      cache: "no-store",
      credentials: "same-origin"
    },
    { ...options, timeoutMs: options.timeoutMs ?? 24_000 }
  );
}

export function isCallerAbort(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

export function describeError(error: unknown): XmuseApiErrorShape {
  if (error instanceof XmuseApiError) {
    return {
      code: error.code,
      message: error.message,
      retryable: error.retryable,
      status: error.status
    };
  }
  if (error instanceof Error) {
    return { code: "frontend_error", message: error.message, retryable: true, status: 0 };
  }
  return { code: "frontend_error", message: "未知错误", retryable: true, status: 0 };
}
