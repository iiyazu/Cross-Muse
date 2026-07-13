import type {
  JsonRecord,
  RoomActor,
  RoomAttemptRecovery,
  RoomChatProjection,
  RoomControlActionDescriptor,
  RoomListProjection,
  RoomMemoryCandidate,
  RoomMemoryProjection,
  RoomMemoryRecall,
  RoomMemoryRuntimeState,
  RoomObservationBatchEvidence,
  RoomObservationFrontier,
  RoomOutcomeSummary,
  RoomOperationsIncident,
  RoomOperationsNextAction,
  RoomOperationsProjection,
  RoomParticipant,
  RoomParticipantState,
  RoomSkillDecision,
  RoomState,
  RoomSummary,
  RoomTimelineItem,
  RoomTurn,
  RoomTurnParticipant
} from "./types";

function record(value: unknown): JsonRecord {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function optionalText(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

function number(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function bool(value: unknown, fallback = false): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function strings(value: unknown): string[] {
  return list(value).flatMap((item) => (typeof item === "string" && item.trim() ? [item] : []));
}

const OPERATIONS_NEXT_ACTIONS = new Set<RoomOperationsNextAction>([
  "wait",
  "open_room",
  "retry_observation",
  "recover_runtime",
  "rebuild_memory_index",
  "repair_then_recover"
]);

const MEMORY_RUNTIME_STATES = new Set<RoomMemoryRuntimeState>([
  "disabled",
  "starting",
  "ready",
  "recovering",
  "rebuilding",
  "degraded",
  "stopping",
  "stopped",
  "failed",
  "unknown"
]);

function boundedOptionalText(value: unknown, maximum: number): string | null {
  if (typeof value !== "string") return null;
  const cleaned = value.trim();
  return cleaned && cleaned.length <= maximum ? cleaned : null;
}

function boundedNullableText(
  value: unknown,
  maximum: number
): string | null | undefined {
  if (value === null) return null;
  return boundedOptionalText(value, maximum) ?? undefined;
}

function nonnegativeInteger(value: unknown): number {
  return Number.isSafeInteger(value) && Number(value) >= 0 ? Number(value) : 0;
}

function memoryRuntimeState(value: unknown): RoomMemoryRuntimeState | null {
  const candidate = boundedOptionalText(value, 32);
  return candidate && MEMORY_RUNTIME_STATES.has(candidate as RoomMemoryRuntimeState)
    ? candidate as RoomMemoryRuntimeState
    : null;
}

function normalizeOperationsIncident(value: unknown): RoomOperationsIncident | null {
  const incident = record(value);
  const incidentId = optionalText(incident.incident_id);
  const kind = optionalText(incident.kind);
  const severity = optionalText(incident.severity);
  const code = optionalText(incident.code);
  const title = optionalText(incident.title);
  const detail = optionalText(incident.detail);
  const nextAction = optionalText(incident.next_action);
  if (
    !incidentId ||
    (kind !== "runtime" && kind !== "host" && kind !== "memory" && kind !== "observation") ||
    (severity !== "attention" && severity !== "blocked") ||
    !code ||
    !title ||
    !detail ||
    !nextAction ||
    !OPERATIONS_NEXT_ACTIONS.has(nextAction as RoomOperationsNextAction)
  ) return null;
  return {
    incident_id: incidentId,
    kind,
    severity,
    code,
    title,
    detail,
    started_at: optionalText(incident.started_at),
    conversation_id: optionalText(incident.conversation_id),
    conversation_title: optionalText(incident.conversation_title),
    participant_id: optionalText(incident.participant_id),
    participant_display_name: optionalText(incident.participant_display_name),
    observation_id: optionalText(incident.observation_id),
    next_action: nextAction as RoomOperationsNextAction
  };
}

export function normalizeRoomOperationsProjection(payload: unknown): RoomOperationsProjection {
  const source = record(payload);
  if (source.schema_version !== "room_operations_projection/v2") {
    throw new Error("room_operations_projection_invalid");
  }
  const overall = optionalText(source.overall);
  if (overall !== "healthy" && overall !== "attention" && overall !== "blocked") {
    throw new Error("room_operations_projection_invalid");
  }
  const runtime = record(source.runtime);
  const runner = record(runtime.runner);
  const mcp = record(runtime.mcp);
  const host = record(runtime.host);
  const memory = record(runtime.memory);
  const runnerState = optionalText(runner.state);
  const mcpState = optionalText(mcp.state);
  const hostState = optionalText(host.state);
  const memoryState = memoryRuntimeState(memory.state);
  if (
    (runnerState !== "healthy" && runnerState !== "blocked" && runnerState !== "stopped") ||
    (mcpState !== "healthy" && mcpState !== "blocked" && mcpState !== "stopped") ||
    (hostState !== "healthy" &&
      hostState !== "attention" &&
      hostState !== "blocked" &&
      hostState !== "unknown") ||
    !memoryState ||
    typeof memory.enabled !== "boolean"
  ) throw new Error("room_operations_projection_invalid");
  const counts = record(source.counts);
  const recover = record(record(source.actions).recover_runtime);
  const method = optionalText(recover.method);
  const href = optionalText(recover.href);
  const mode = optionalText(recover.mode);
  const expectedIncidentId = optionalText(recover.expected_incident_id);
  const recoverDescriptor = Object.keys(recover).length &&
    method === "POST" &&
    href === "/api/chat/operator/room-runtime/recover" &&
    (mode === "start" || mode === "restart") &&
    (!bool(recover.available) || expectedIncidentId)
    ? {
        available: bool(recover.available),
        method,
        href,
        expected_incident_id: expectedIncidentId,
        mode,
        confirmation_required: bool(recover.confirmation_required, true)
      } as const
    : undefined;
  const rebuild = record(record(source.actions).rebuild_memory_index);
  const rebuildMethod = optionalText(rebuild.method);
  const rebuildHref = optionalText(rebuild.href);
  const rebuildIncidentId = boundedNullableText(rebuild.expected_incident_id, 200);
  const rebuildStatus = boundedNullableText(rebuild.status, 64);
  const rebuildPhase = boundedNullableText(rebuild.phase, 64);
  const rebuildDescriptor = Object.keys(rebuild).length &&
    typeof rebuild.available === "boolean" &&
    typeof rebuild.pending === "boolean" &&
    rebuildMethod === "POST" &&
    rebuildHref === "/api/chat/operator/memory-runtime/rebuild" &&
    rebuildIncidentId !== undefined &&
    rebuildStatus !== undefined &&
    rebuildPhase !== undefined &&
    (!rebuild.available || rebuildIncidentId) &&
    (!rebuild.pending || (!rebuild.available && rebuildStatus && rebuildPhase))
    ? {
        available: rebuild.available,
        pending: rebuild.pending,
        status: rebuildStatus,
        phase: rebuildPhase,
        method: rebuildMethod,
        href: rebuildHref,
        expected_incident_id: rebuildIncidentId,
        confirmation_required: bool(rebuild.confirmation_required, true)
      } as const
    : undefined;
  if (!recoverDescriptor || !rebuildDescriptor) {
    throw new Error("room_operations_projection_invalid");
  }
  return {
    schema_version: "room_operations_projection/v2",
    generated_at: optionalText(source.generated_at),
    overall,
    runtime: {
      runner: { state: runnerState, code: optionalText(runner.code) },
      mcp: { state: mcpState, code: optionalText(mcp.code) },
      host: {
        state: hostState,
        code: optionalText(host.code),
        active_delivery_count: Math.max(0, number(host.active_delivery_count)),
        retained_cleanup_count: Math.max(0, number(host.retained_cleanup_count))
      },
      memory: {
        enabled: memory.enabled,
        state: memoryState,
        code: boundedOptionalText(memory.code, 128),
        consecutive_restart_count: nonnegativeInteger(memory.consecutive_restart_count),
        next_retry_at: boundedOptionalText(memory.next_retry_at, 100),
        last_healthy_at: boundedOptionalText(memory.last_healthy_at, 100)
      }
    },
    counts: {
      active_delivery: Math.max(0, number(counts.active_delivery)),
      retained_cleanup: Math.max(0, number(counts.retained_cleanup)),
      recovery_pending: Math.max(0, number(counts.recovery_pending)),
      cancel_pending: Math.max(0, number(counts.cancel_pending)),
      provider_cleanup_pending: Math.max(0, number(counts.provider_cleanup_pending)),
      exhausted: Math.max(0, number(counts.exhausted))
    },
    incident_total: Math.max(0, number(source.incident_total)),
    incidents: list(source.incidents).slice(0, 20).flatMap((item) => {
      const normalized = normalizeOperationsIncident(item);
      return normalized ? [normalized] : [];
    }),
    actions: {
      recover_runtime: recoverDescriptor,
      rebuild_memory_index: rebuildDescriptor
    }
  };
}

function normalizeMemoryRecall(value: unknown): RoomMemoryRecall | null {
  const source = record(value);
  const receiptId = boundedOptionalText(source.receipt_id, 200);
  const participantId = boundedOptionalText(source.participant_id, 200);
  const status = boundedOptionalText(source.status, 128);
  if (!status) return null;
  return {
    receipt_id: receiptId,
    participant_id: participantId,
    status,
    schema_version: boundedOptionalText(source.schema_version, 128),
    latency_ms: nonnegativeInteger(source.latency_ms),
    item_count: nonnegativeInteger(source.item_count),
    source_refs: list(source.source_refs).slice(0, 32).flatMap((item) => {
      const ref = record(item);
      const activityId = boundedOptionalText(ref.activity_id, 200);
      return activityId
        ? [{
            activity_id: activityId,
            content_sha256: boundedOptionalText(ref.content_sha256, 200),
            archive_scope: boundedOptionalText(ref.archive_scope, 64)
          }]
        : [];
    }),
    evidence_sha256: boundedOptionalText(source.evidence_sha256, 200),
    created_at: boundedOptionalText(source.created_at, 100)
  };
}

function normalizeMemoryCandidate(
  value: unknown,
  conversationId: string
): RoomMemoryCandidate | null {
  const source = record(value);
  const candidateId = boundedOptionalText(source.candidate_id, 200);
  const candidateConversationId = boundedOptionalText(source.conversation_id, 200);
  const kind = boundedOptionalText(source.kind, 32);
  const digest = boundedOptionalText(source.digest, 200);
  const content = boundedOptionalText(source.content, 8 * 1024);
  const approvalState = boundedOptionalText(source.approval_state, 32);
  const targetScope = boundedOptionalText(source.target_scope, 32);
  const action = record(record(source.actions).resolve);
  const expectedHref = candidateId
    ? `/api/chat/operator/memory-candidates/${encodeURIComponent(candidateId)}/resolve`
    : null;
  const decisions = strings(action.allowed_decisions);
  if (
    !candidateId ||
    candidateConversationId !== conversationId ||
    (kind !== "room_fact" && kind !== "room_decision" &&
      kind !== "user_preference" && kind !== "project_rule") ||
    !digest ||
    !content ||
    (approvalState !== "pending" && approvalState !== "approved" && approvalState !== "rejected") ||
    (targetScope !== "room" && targetScope !== "local_user" && targetScope !== "project") ||
    action.method !== "POST" ||
    action.href !== expectedHref ||
    action.expected_digest !== digest ||
    !Number.isSafeInteger(action.expected_revision) ||
    !decisions.includes("approve") ||
    !decisions.includes("reject")
  ) return null;
  const revision = nonnegativeInteger(source.revision);
  if (nonnegativeInteger(action.expected_revision) !== revision) return null;
  return {
    candidate_id: candidateId,
    conversation_id: candidateConversationId,
    author_participant_id: boundedOptionalText(source.author_participant_id, 200),
    kind,
    content,
    digest,
    source_activity_ids: strings(source.source_activity_ids)
      .slice(0, 64)
      .flatMap((item) => boundedOptionalText(item, 200) ?? []),
    approval_state: approvalState,
    publish_state: boundedOptionalText(source.publish_state, 64) ?? "unknown",
    target_scope: targetScope,
    revision,
    reason_code: boundedOptionalText(source.reason_code, 128),
    created_at: boundedOptionalText(source.created_at, 100),
    resolved_at: boundedOptionalText(source.resolved_at, 100),
    updated_at: boundedOptionalText(source.updated_at, 100),
    actions: {
      resolve: {
        available: bool(action.available),
        method: "POST",
        href: expectedHref!,
        expected_digest: digest,
        expected_revision: revision,
        allowed_decisions: ["approve", "reject"]
      }
    }
  };
}

export function normalizeRoomMemoryProjection(payload: unknown): RoomMemoryProjection {
  const source = record(payload);
  if (
    source.schema_version !== "room_memory_projection/v1" ||
    source.projection_only !== true ||
    source.proof_boundary !== "memory_projection_not_room_or_memory_index_authority" ||
    typeof source.enabled !== "boolean" ||
    typeof source.degraded !== "boolean"
  ) throw new Error("room_memory_projection_invalid");
  const conversationId = boundedOptionalText(source.conversation_id, 200);
  const generatedAt = boundedOptionalText(source.generated_at, 100);
  const runtime = record(source.runtime);
  const state = memoryRuntimeState(runtime.state);
  const runtimeCode = boundedNullableText(runtime.code, 128);
  const nextRetryAt = boundedNullableText(runtime.next_retry_at, 100);
  const lastHealthyAt = boundedNullableText(runtime.last_healthy_at, 100);
  const startedAt = boundedNullableText(runtime.started_at, 100);
  const updatedAt = boundedNullableText(runtime.updated_at, 100);
  if (!conversationId || !generatedAt || !state || typeof runtime.enabled !== "boolean" ||
    typeof runtime.degraded !== "boolean" ||
    runtimeCode === undefined ||
    !Number.isSafeInteger(runtime.consecutive_restart_count) ||
    Number(runtime.consecutive_restart_count) < 0 ||
    nextRetryAt === undefined ||
    lastHealthyAt === undefined ||
    startedAt === undefined ||
    updatedAt === undefined) {
    throw new Error("room_memory_projection_invalid");
  }
  const binding = record(source.binding);
  const sync = record(source.sync);
  const pendingCandidates = list(source.pending_candidates).slice(0, 20).flatMap((item) => {
    const candidate = normalizeMemoryCandidate(item, conversationId);
    return candidate ? [candidate] : [];
  });
  return {
    schema_version: "room_memory_projection/v1",
    projection_only: true,
    proof_boundary: "memory_projection_not_room_or_memory_index_authority",
    generated_at: generatedAt,
    conversation_id: conversationId,
    enabled: source.enabled,
    degraded: source.degraded,
    runtime: {
      enabled: runtime.enabled,
      degraded: runtime.degraded,
      state,
      code: runtimeCode,
      consecutive_restart_count: nonnegativeInteger(runtime.consecutive_restart_count),
      next_retry_at: nextRetryAt,
      last_healthy_at: lastHealthyAt,
      started_at: startedAt,
      updated_at: updatedAt
    },
    binding: {
      present: bool(binding.present),
      session_state: boundedOptionalText(binding.session_state, 64),
      attachment_state: boundedOptionalText(binding.attachment_state, 64),
      revision: nonnegativeInteger(binding.revision),
      updated_at: boundedOptionalText(binding.updated_at, 100)
    },
    sync: {
      backlog: nonnegativeInteger(sync.backlog),
      pending: nonnegativeInteger(sync.pending),
      processing: nonnegativeInteger(sync.processing),
      failed: nonnegativeInteger(sync.failed),
      conflict: nonnegativeInteger(sync.conflict),
      delivered: nonnegativeInteger(sync.delivered)
    },
    recent_recalls: list(source.recent_recalls).slice(0, 8).flatMap((item) => {
      const recall = normalizeMemoryRecall(item);
      return recall ? [recall] : [];
    }),
    pending_candidate_total: nonnegativeInteger(source.pending_candidate_total),
    pending_candidates: pendingCandidates
  };
}

function roomState(value: unknown): RoomState {
  return value === "attention" || value === "active" ? value : "settled";
}

function participantState(value: unknown): RoomParticipantState {
  return text(value, "pending");
}

function normalizeControlAction(value: unknown): RoomControlActionDescriptor | undefined {
  const action = record(value);
  if (!Object.keys(action).length) return undefined;
  return {
    available: bool(action.available),
    href: text(action.href),
    expected_state: text(action.expected_state, "active") as RoomControlActionDescriptor["expected_state"],
    expected_attempt_count: number(action.expected_attempt_count),
    expected_control_seq: number(action.expected_control_seq)
  };
}

function normalizeSkillDecision(value: unknown): RoomSkillDecision | undefined {
  const decision = record(value);
  const skillId = optionalText(decision.skill_id);
  const version = optionalText(decision.version);
  const contentSha256 = optionalText(decision.content_sha256);
  const selectionReason = optionalText(decision.selection_reason);
  const contextStatus = optionalText(decision.context_status);
  if (
    !skillId ||
    !version ||
    !contentSha256 ||
    !selectionReason ||
    (contextStatus !== "selected" && contextStatus !== "submitted")
  ) return undefined;
  return {
    skill_id: skillId,
    version,
    content_sha256: contentSha256,
    selection_reason: selectionReason,
    matched_terms: strings(decision.matched_terms),
    context_status: contextStatus,
    context_submitted_at: optionalText(decision.context_submitted_at)
  };
}

function normalizeAttemptRecovery(value: unknown): RoomAttemptRecovery | undefined {
  const recovery = record(value);
  const state = optionalText(recovery.state);
  if (
    state !== "none" &&
    state !== "fenced" &&
    state !== "cleanup_pending" &&
    state !== "recovered"
  ) return undefined;
  const candidateNextAction = optionalText(recovery.next_action);
  const nextAction =
    candidateNextAction === "cleanup_pending" ||
    candidateNextAction === "will_retry" ||
    candidateNextAction === "will_exhaust"
      ? candidateNextAction
      : "none";
  return {
    state,
    reason_code: optionalText(recovery.reason_code),
    started_at: optionalText(recovery.started_at),
    completed_at: optionalText(recovery.completed_at),
    next_action: nextAction
  };
}

function normalizeAttempt(value: unknown): RoomObservationFrontier["current_attempt"] {
  const attempt = record(value);
  if (!Object.keys(attempt).length || !text(attempt.state)) return null;
  return {
    attempt_number: number(attempt.attempt_number),
    effective_attempt_limit: number(attempt.effective_attempt_limit),
    state: text(attempt.state),
    reason_code: optionalText(attempt.reason_code),
    claimed_at: optionalText(attempt.claimed_at),
    expires_at: optionalText(attempt.expires_at),
    transport_started_at: optionalText(attempt.transport_started_at),
    finished_at: optionalText(attempt.finished_at),
    updated_at: optionalText(attempt.updated_at),
    recovery: normalizeAttemptRecovery(attempt.recovery),
    skill_decision: normalizeSkillDecision(attempt.skill_decision)
  };
}

function normalizeBatchEvidence(value: unknown): RoomObservationBatchEvidence {
  const evidence = record(value);
  const coverage = record(evidence.coverage);
  const normalizedCoverage = Object.keys(coverage).length
    ? {
        mode: text(coverage.mode, "singleton_fallback"),
        cutoff_room_seq: Math.max(0, number(coverage.cutoff_room_seq)),
        included_member_count: Math.max(0, number(coverage.included_member_count)),
        omitted_member_count: Math.max(0, number(coverage.omitted_member_count))
      }
    : undefined;
  return {
    batch_id: optionalText(evidence.batch_id),
    phase: optionalText(evidence.phase) ?? undefined,
    member_count: Math.max(0, number(evidence.member_count)),
    member_activity_refs: list(evidence.member_activity_refs).flatMap((item) => {
      const ref = record(item);
      const activityId = optionalText(ref.activity_id);
      return activityId
        ? [{ activity_id: activityId, room_seq: Math.max(0, number(ref.room_seq)) }]
        : [];
    }),
    attempt_count: Math.max(0, number(evidence.attempt_count)),
    context_only_tail: bool(evidence.context_only_tail),
    coverage: normalizedCoverage
  };
}

function normalizeActor(value: unknown): RoomActor {
  const actor = record(value);
  const kind = text(actor.kind, "agent");
  return {
    kind,
    identity: optionalText(actor.identity),
    participant_id: optionalText(actor.participant_id),
    role: text(actor.role, kind === "human" ? "human" : "agent"),
    display_name: text(
      actor.display_name,
      kind === "human" ? "你" : text(actor.role, text(actor.identity, "Agent"))
    )
  };
}

function normalizeFrontier(value: unknown): RoomObservationFrontier | null {
  if (!value) return null;
  const frontier = record(value);
  return {
    ...normalizeBatchEvidence(frontier),
    observation_id: optionalText(frontier.observation_id),
    activity_id: optionalText(frontier.activity_id),
    correlation_id: optionalText(frontier.correlation_id),
    status: optionalText(frontier.status),
    expired: bool(frontier.expired),
    expires_at: optionalText(frontier.expires_at),
    claimed_until: optionalText(frontier.claimed_until ?? frontier.expires_at),
    attempt_count: number(frontier.attempt_count),
    control_state: (optionalText(frontier.control_state) ?? "active") as RoomObservationFrontier["control_state"],
    control_seq: number(frontier.control_seq),
    manual_retry_budget: number(frontier.manual_retry_budget),
    current_attempt: normalizeAttempt(frontier.current_attempt),
    actions: {
      cancel: normalizeControlAction(record(frontier.actions).cancel),
      retry: normalizeControlAction(record(frontier.actions).retry)
    },
    updated_at: optionalText(frontier.updated_at ?? frontier.created_at)
  };
}

function normalizeOutcome(value: unknown): RoomOutcomeSummary | null {
  if (!value) return null;
  const outcome = record(value);
  return {
    ...normalizeBatchEvidence(outcome),
    type: optionalText(outcome.type ?? outcome.outcome_type),
    outcome_type: optionalText(outcome.outcome_type ?? outcome.type),
    observation_id: optionalText(outcome.observation_id),
    activity_id: optionalText(outcome.produced_activity_id ?? outcome.activity_id),
    completed_at: optionalText(outcome.completed_at),
    skill_decision: normalizeSkillDecision(outcome.skill_decision)
  };
}

function mentionHandle(value: unknown, participantId: string, role: string): string {
  const configured = text(value);
  if (configured) return configured.startsWith("@") ? configured : `@${configured}`;
  return role ? `@${role}` : `@participant:${participantId}`;
}

function normalizeParticipant(value: unknown): RoomParticipant {
  const participant = record(value);
  const participantId = text(participant.participant_id ?? participant.id, "unknown-participant");
  const role = text(participant.role, "agent");
  const participantStatus = text(participant.participant_status ?? participant.status, "active");
  const status = participantState(participant.state ?? participant.status);
  return {
    participant_id: participantId,
    role,
    display_name: text(participant.display_name, role),
    mention_handle: mentionHandle(participant.mention_handle, participantId, role),
    status,
    participant_status: participantStatus,
    active: participant.active !== false && participantStatus !== "stopped",
    frontier: normalizeFrontier(participant.frontier),
    last_completed_outcome: normalizeOutcome(participant.last_completed_outcome),
    unresolved_count: number(participant.unresolved_count)
  };
}

function normalizeTurnParticipant(value: unknown): RoomTurnParticipant {
  const participant = record(value);
  const participantId = text(participant.participant_id ?? participant.id, "unknown-participant");
  const role = text(participant.role, "agent");
  const state = participantState(participant.state ?? participant.status);
  return {
    participant_id: participantId,
    role,
    display_name: text(participant.display_name, role),
    mention_handle: mentionHandle(participant.mention_handle, participantId, role),
    status: state,
    state,
    observation_count: number(participant.observation_count),
    response_count: number(participant.response_count),
    unresolved_count: number(participant.unresolved_count),
    frontier: normalizeFrontier(participant.frontier),
    latest_outcome: normalizeOutcome(participant.latest_outcome),
    root_skill_decision: normalizeSkillDecision(participant.root_skill_decision)
  };
}

export function normalizeTimelineItem(value: unknown, fallbackIndex = 0): RoomTimelineItem {
  const item = record(value);
  const actor = normalizeActor(item.actor);
  const roomSeq = number(item.room_seq, fallbackIndex);
  const kind = text(item.kind, "message");
  const message = record(item.message);
  const proposal = Object.keys(record(item.proposal)).length ? record(item.proposal) : null;
  const content = text(item.content ?? message.content ?? proposal?.summary ?? proposal?.title);
  const messageId = optionalText(item.message_id ?? message.id);
  const proposalId = optionalText(item.proposal_id ?? proposal?.proposal_id ?? proposal?.id);
  const activityId = optionalText(item.activity_id);
  return {
    id: messageId ?? proposalId ?? activityId ?? `${kind}:${roomSeq}:${fallbackIndex}`,
    room_seq: roomSeq,
    kind,
    activity_id: activityId,
    activity_type: optionalText(item.activity_type),
    message_id: messageId,
    proposal_id: proposalId,
    reply_to_activity_id: optionalText(item.reply_to_activity_id),
    reply_to_message_id: optionalText(item.reply_to_message_id),
    reply_target_display_name: optionalText(item.reply_target_display_name),
    correlation_id: optionalText(item.correlation_id),
    causation_id: optionalText(item.causation_id),
    causal_depth: number(item.causal_depth),
    actor,
    content,
    created_at: optionalText(item.created_at ?? message.created_at),
    handoff_targets: strings(item.handoff_targets ?? item.target_participant_ids),
    target_participant_ids: strings(item.target_participant_ids),
    mentions: strings(item.mentions),
    proposal,
    proof_boundary: optionalText(item.proof_boundary),
    source_refs: strings(item.source_refs),
    context_only_tail: bool(item.context_only_tail)
  };
}

function normalizeTurn(value: unknown): RoomTurn {
  const turn = record(value);
  const state = roomState(turn.status ?? turn.state);
  return {
    correlation_id: text(turn.correlation_id, "unknown-correlation"),
    root_activity_id: optionalText(turn.root_activity_id),
    root_room_seq: typeof turn.root_room_seq === "number" ? turn.root_room_seq : null,
    state,
    status: state,
    created_at: optionalText(turn.created_at),
    updated_at: optionalText(turn.updated_at),
    excluded_stopped_count: number(turn.excluded_stopped_count),
    observation_count: Math.max(0, number(turn.observation_count)),
    attempt_count: Math.max(0, number(turn.attempt_count)),
    skill_decision_count: Math.max(0, number(turn.skill_decision_count)),
    participants: list(turn.participants).map(normalizeTurnParticipant)
  };
}

function normalizeSummary(value: unknown): RoomSummary {
  const room = record(value);
  const conversationId = text(room.conversation_id ?? room.id, "unknown-room");
  const latestItem = room.latest_visible_item
    ? normalizeTimelineItem(room.latest_visible_item)
    : null;
  const participants = list(room.participants ?? room.members).map(normalizeParticipant);
  const state = roomState(room.status ?? room.state);
  return {
    conversation_id: conversationId,
    title: text(room.title, "未命名房间"),
    created_at: optionalText(room.created_at),
    updated_at: optionalText(room.updated_at),
    latest_visible_room_seq: number(room.latest_visible_room_seq),
    latest_visible_item: latestItem,
    latest_message: latestItem
      ? { content: latestItem.content, actor: latestItem.actor, created_at: latestItem.created_at }
      : null,
    members: participants,
    participants,
    state,
    status: state,
    participant_count: number(room.participant_count, participants.length),
    active_participant_count: number(
      room.active_participant_count,
      participants.filter((participant) => participant.active).length
    ),
    active_turn_count: number(room.active_turn_count),
    attention_turn_count: number(room.attention_turn_count)
  };
}

export function normalizeRoomList(payload: unknown): RoomListProjection {
  const source = record(payload);
  if (source.schema_version !== "room_list_projection/v1") {
    throw new Error("room_list_projection_schema_invalid");
  }
  return {
    schema_version: "room_list_projection/v1",
    generated_at: optionalText(source.generated_at) ?? undefined,
    rooms: list(source.rooms).map(normalizeSummary)
  };
}

export function normalizeRoomProjection(
  payload: unknown,
  conversationId: string
): RoomChatProjection {
  const source = record(payload);
  if (source.schema_version !== "room_chat_projection/v3") {
    throw new Error("room_chat_projection_schema_invalid");
  }
  const page = record(source.page);
  const conversation = record(source.conversation);
  const projectedConversationId = text(
    source.conversation_id ?? conversation.id,
    conversationId
  );
  if (projectedConversationId !== conversationId) {
    throw new Error("room_chat_projection_conversation_mismatch");
  }
  const items = list(source.timeline_items).map(normalizeTimelineItem);
  const status = roomState(source.status ?? source.room_state);
  return {
    schema_version: "room_chat_projection/v3",
    conversation_id: projectedConversationId,
    generated_at: optionalText(source.generated_at) ?? undefined,
    event_cursor: number(source.event_cursor),
    room_state: status,
    status,
    latest_visible_room_seq: number(
      source.latest_visible_room_seq,
      items.length ? Math.max(...items.map((item) => item.room_seq)) : 0
    ),
    conversation: {
      ...conversation,
      id: text(conversation.id, conversationId),
      title: text(conversation.title, "未命名房间")
    },
    participants: list(source.participants).map(normalizeParticipant),
    turns: list(source.turns).map(normalizeTurn),
    hidden_active_turn_count: number(
      source.additional_active_turn_count ?? source.hidden_active_turn_count
    ),
    active_turn_count: number(source.active_turn_count),
    attention_turn_count: number(source.attention_turn_count),
    additional_active_turn_count: number(source.additional_active_turn_count),
    excluded_stopped_count: number(source.excluded_stopped_count),
    timeline_items: items,
    has_older: bool(page.has_older ?? source.has_older),
    has_newer: bool(page.has_newer ?? source.has_newer),
    next_before_room_seq:
      typeof (page.next_before_room_seq ?? source.next_before_room_seq) === "number"
        ? (page.next_before_room_seq ?? source.next_before_room_seq) as number
        : null,
    next_after_room_seq:
      typeof (page.next_after_room_seq ?? source.next_after_room_seq) === "number"
        ? (page.next_after_room_seq ?? source.next_after_room_seq) as number
        : null,
    page: {
      mode: text(page.mode),
      limit: number(page.limit, 60),
      before_room_seq:
        typeof page.before_room_seq === "number" ? page.before_room_seq : null,
      after_room_seq:
        typeof page.after_room_seq === "number" ? page.after_room_seq : null,
      has_older: bool(page.has_older ?? source.has_older),
      has_newer: bool(page.has_newer ?? source.has_newer),
      next_before_room_seq:
        typeof (page.next_before_room_seq ?? source.next_before_room_seq) === "number"
          ? (page.next_before_room_seq ?? source.next_before_room_seq) as number
          : null,
      next_after_room_seq:
        typeof (page.next_after_room_seq ?? source.next_after_room_seq) === "number"
          ? (page.next_after_room_seq ?? source.next_after_room_seq) as number
          : null
    }
  };
}

export function mergeRoomTimeline(
  current: RoomTimelineItem[],
  incoming: RoomTimelineItem[]
): RoomTimelineItem[] {
  const byId = new Map<string, RoomTimelineItem>();
  for (const item of current) byId.set(item.id, item);
  for (const item of incoming) byId.set(item.id, item);
  return [...byId.values()].sort((left, right) => {
    if (left.room_seq !== right.room_seq) return left.room_seq - right.room_seq;
    return left.id.localeCompare(right.id);
  });
}

export function roomParticipantStateLabel(state: RoomParticipantState): string {
  const labels: Record<string, string> = {
    pending: "待观察",
    thinking: "判断中",
    claimed: "判断中",
    runtime_recovery: "等待运行时恢复",
    claimed_expired: "等待运行时恢复",
    responded: "已回应",
    respond: "已回应",
    handoff: "已建议转交",
    proposed: "已提案",
    propose: "已提案",
    noop: "已观察 · 未回应",
    deferred: "暂缓，不承诺自动唤醒",
    defer: "暂缓，不承诺自动唤醒",
    cancel_pending: "正在取消",
    cancelled: "已取消",
    exhausted: "尝试已耗尽",
    stopped: "已停止"
  };
  return labels[state] ?? state;
}

export function roomStateLabel(state: RoomState): string {
  if (state === "attention") return "需要关注";
  if (state === "active") return "Agent 正在独立判断";
  return "本轮已收束";
}
