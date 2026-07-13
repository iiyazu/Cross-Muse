export type JsonRecord = Record<string, unknown>;

export type XmuseApiErrorShape = {
  code: string;
  message: string;
  retryable: boolean;
  status: number;
};

export type ConversationSummary = {
  id: string;
  client_request_id?: string;
  title?: string;
  created_at?: string;
  updated_at?: string;
  [key: string]: unknown;
};

export type FrontendEvent = {
  sequence?: number;
  type?: string;
  event_type?: string;
  payload?: unknown;
  [key: string]: unknown;
};

export type FrontendEventsResponse = {
  schema_version: string;
  conversation_id: string;
  after_seq: number;
  latest_seq: number;
  has_more: boolean;
  events: FrontendEvent[];
  projection_only?: boolean;
  proof_boundary?: string;
};

export type RoomState = "active" | "attention" | "settled";

export type RoomParticipantState =
  | "pending"
  | "thinking"
  | "runtime_recovery"
  | "responded"
  | "handoff"
  | "proposed"
  | "noop"
  | "deferred"
  | "stopped"
  | "cancel_pending"
  | "cancelled"
  | "exhausted"
  | "settled"
  | string;

export type RoomControlState =
  | "active"
  | "cancel_requested"
  | "cancel_pending"
  | "cancelled"
  | "exhausted";

export type RoomControlActionDescriptor = {
  available: boolean;
  href: string;
  expected_state: RoomControlState;
  expected_attempt_count: number;
  expected_control_seq: number;
};

export type RoomSkillDecision = {
  skill_id: string;
  version: string;
  content_sha256: string;
  selection_reason: string;
  matched_terms: string[];
  context_status: "selected" | "submitted";
  context_submitted_at?: string | null;
};

export type RoomAttemptRecovery = {
  state: "none" | "fenced" | "cleanup_pending" | "recovered";
  reason_code?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  next_action: "cleanup_pending" | "will_retry" | "will_exhaust" | "none";
};

export type RoomAttemptView = {
  attempt_number: number;
  effective_attempt_limit: number;
  state: string;
  reason_code?: string | null;
  claimed_at?: string | null;
  expires_at?: string | null;
  transport_started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
  recovery?: RoomAttemptRecovery;
  skill_decision?: RoomSkillDecision;
};

export type RoomActor = {
  participant_id?: string | null;
  identity?: string | null;
  role: string;
  display_name: string;
  kind?: "human" | "agent" | "system" | string;
};

export type RoomTimelineItem = {
  id: string;
  room_seq: number;
  kind: "message" | "handoff" | "proposal" | string;
  activity_id?: string | null;
  activity_type?: string | null;
  message_id?: string | null;
  proposal_id?: string | null;
  reply_to_activity_id?: string | null;
  reply_to_message_id?: string | null;
  reply_target_display_name?: string | null;
  correlation_id?: string | null;
  causation_id?: string | null;
  causal_depth?: number;
  actor: RoomActor;
  content: string;
  created_at?: string | null;
  handoff_targets?: string[];
  target_participant_ids?: string[];
  mentions?: string[];
  proposal?: JsonRecord | null;
  proof_boundary?: string | null;
  source_refs?: string[];
  context_only_tail?: boolean;
};

export type RoomBatchActivityRef = {
  activity_id: string;
  room_seq: number;
};

export type RoomBatchCoverage = {
  mode: "batch" | "singleton_fallback" | string;
  cutoff_room_seq: number;
  included_member_count: number;
  omitted_member_count: number;
};

export type RoomObservationBatchEvidence = {
  batch_id?: string | null;
  phase?: "root" | "peer" | string;
  member_count?: number;
  member_activity_refs?: RoomBatchActivityRef[];
  attempt_count?: number;
  context_only_tail?: boolean;
  coverage?: RoomBatchCoverage;
};

export type RoomObservationFrontier = RoomObservationBatchEvidence & {
  observation_id?: string | null;
  activity_id?: string | null;
  correlation_id?: string | null;
  status?: string | null;
  expired?: boolean;
  expires_at?: string | null;
  claimed_until?: string | null;
  attempt_count?: number;
  control_state?: RoomControlState;
  control_seq?: number;
  manual_retry_budget?: number;
  current_attempt?: RoomAttemptView | null;
  actions?: {
    cancel?: RoomControlActionDescriptor;
    retry?: RoomControlActionDescriptor;
  };
  updated_at?: string | null;
};

export type RoomOutcomeSummary = RoomObservationBatchEvidence & {
  type?: string | null;
  outcome_type?: string | null;
  observation_id?: string | null;
  activity_id?: string | null;
  completed_at?: string | null;
  skill_decision?: RoomSkillDecision;
};

export type RoomParticipant = {
  participant_id: string;
  role: string;
  display_name: string;
  mention_handle: string;
  status: RoomParticipantState;
  participant_status?: string;
  active: boolean;
  frontier?: RoomObservationFrontier | null;
  last_completed_outcome?: RoomOutcomeSummary | null;
  unresolved_count?: number;
};

export type RoomTurnParticipant = {
  participant_id: string;
  role: string;
  display_name: string;
  mention_handle?: string;
  status: RoomParticipantState;
  state?: RoomParticipantState;
  observation_count?: number;
  response_count?: number;
  unresolved_count: number;
  frontier?: RoomObservationFrontier | null;
  latest_outcome?: RoomOutcomeSummary | null;
  root_skill_decision?: RoomSkillDecision;
};

export type RoomTurn = {
  correlation_id: string;
  root_activity_id?: string | null;
  root_room_seq?: number | null;
  state: RoomState;
  status?: RoomState;
  created_at?: string | null;
  updated_at?: string | null;
  excluded_stopped_count: number;
  observation_count: number;
  attempt_count: number;
  skill_decision_count: number;
  participants: RoomTurnParticipant[];
};

export type RoomSummary = {
  conversation_id: string;
  title: string;
  created_at?: string | null;
  updated_at?: string | null;
  latest_visible_room_seq: number;
  latest_visible_item?: RoomTimelineItem | null;
  latest_message?: {
    content: string;
    actor?: RoomActor | null;
    created_at?: string | null;
  } | null;
  members: RoomParticipant[];
  participants?: RoomParticipant[];
  state: RoomState;
  status?: RoomState;
  participant_count?: number;
  active_participant_count?: number;
  active_turn_count: number;
  attention_turn_count: number;
};

export type RoomListProjection = {
  schema_version: "room_list_projection/v1";
  generated_at?: string;
  rooms: RoomSummary[];
};

export type RoomChatProjection = {
  schema_version: "room_chat_projection/v3";
  conversation_id: string;
  generated_at?: string;
  event_cursor: number;
  room_state: RoomState;
  status?: RoomState;
  latest_visible_room_seq?: number;
  conversation: ConversationSummary;
  participants: RoomParticipant[];
  turns: RoomTurn[];
  hidden_active_turn_count: number;
  active_turn_count?: number;
  attention_turn_count?: number;
  additional_active_turn_count?: number;
  excluded_stopped_count: number;
  timeline_items: RoomTimelineItem[];
  has_older: boolean;
  has_newer: boolean;
  next_before_room_seq?: number | null;
  next_after_room_seq?: number | null;
  page?: {
    mode?: string;
    limit?: number;
    before_room_seq?: number | null;
    after_room_seq?: number | null;
    has_older: boolean;
    has_newer: boolean;
    next_before_room_seq?: number | null;
    next_after_room_seq?: number | null;
  };
};

export type RoomMessageReceipt = {
  client_request_id: string;
  activity_id?: string | null;
  room_activity_seq?: number | null;
  message: {
    id: string;
    content: string;
    author?: string;
    role?: string;
    created_at?: string | null;
  };
};

export type RoomControlResult = {
  action_id: string;
  status: "succeeded" | string;
  result_ref?: string;
  changed_refs?: string[];
  event_cursor?: number | null;
  projection_revision?: number | null;
  room_observation_control?: JsonRecord;
  error?: unknown;
};

export type RoomOperationsState = "healthy" | "attention" | "blocked";

export type RoomOperationsComponent = {
  state: "healthy" | "blocked" | "stopped";
  code: string | null;
};

export type RoomOperationsHost = {
  state: "healthy" | "attention" | "blocked" | "unknown";
  code: string | null;
  active_delivery_count: number;
  retained_cleanup_count: number;
};

export type RoomMemoryRuntimeState =
  | "disabled"
  | "starting"
  | "ready"
  | "recovering"
  | "rebuilding"
  | "degraded"
  | "stopping"
  | "stopped"
  | "failed"
  | "unknown";

export type RoomOperationsMemory = {
  enabled: boolean;
  state: RoomMemoryRuntimeState;
  code: string | null;
  consecutive_restart_count: number;
  next_retry_at: string | null;
  last_healthy_at: string | null;
};

export type RoomOperationsCounts = {
  active_delivery: number;
  retained_cleanup: number;
  recovery_pending: number;
  cancel_pending: number;
  provider_cleanup_pending: number;
  exhausted: number;
};

export type RoomOperationsNextAction =
  | "wait"
  | "open_room"
  | "retry_observation"
  | "recover_runtime"
  | "rebuild_memory_index"
  | "repair_then_recover";

export type RoomOperationsIncident = {
  incident_id: string;
  kind: "runtime" | "host" | "memory" | "observation";
  severity: "attention" | "blocked";
  code: string;
  title: string;
  detail: string;
  started_at: string | null;
  conversation_id: string | null;
  conversation_title: string | null;
  participant_id: string | null;
  participant_display_name: string | null;
  observation_id: string | null;
  next_action: RoomOperationsNextAction;
};

export type RoomRuntimeRecoverDescriptor = {
  available: boolean;
  method: "POST";
  href: "/api/chat/operator/room-runtime/recover";
  expected_incident_id: string | null;
  mode: "start" | "restart";
  confirmation_required: boolean;
};

export type RoomMemoryRebuildDescriptor = {
  available: boolean;
  pending: boolean;
  status: string | null;
  phase: string | null;
  method: "POST";
  href: "/api/chat/operator/memory-runtime/rebuild";
  expected_incident_id: string | null;
  confirmation_required: boolean;
};

export type RoomOperationsProjection = {
  schema_version: "room_operations_projection/v2";
  generated_at: string | null;
  overall: RoomOperationsState;
  runtime: {
    runner: RoomOperationsComponent;
    mcp: RoomOperationsComponent;
    host: RoomOperationsHost;
    memory: RoomOperationsMemory;
  };
  counts: RoomOperationsCounts;
  incident_total: number;
  incidents: RoomOperationsIncident[];
  actions: {
    recover_runtime: RoomRuntimeRecoverDescriptor;
    rebuild_memory_index: RoomMemoryRebuildDescriptor;
  };
};

export type RoomRuntimeRecoverResult = {
  action_id: string;
  status: "requested" | "applied" | "rejected" | "failed" | string;
};

export type RoomMemoryRebuildActionResult = {
  schema_version: "room_memory_rebuild_action/v1";
  action_id: string;
  client_action_id: string;
  status: "requested" | "applied" | "rejected" | "failed";
  phase: string | null;
  reason_code: string | null;
  before: { state: string | null; code: string | null };
  after: { state: string | null; code: string | null };
  result: null | {
    cache_cleared: boolean;
    bindings_reset: number;
    deliveries_reopened: number;
    claimed_attempts_fenced: number;
    candidates_requeued: number;
  };
  requested_at: string | null;
  applied_at: string | null;
  proof_boundary: "operator_action_receipt_not_room_or_memory_index_authority";
};

export type RoomExecutionPolicyMode = "manual" | "consensus";

export type RoomExecutionPolicyUpdateDescriptor = {
  available: boolean;
  method: "PUT";
  href: string;
  expected_revision: number;
  allowed_modes: RoomExecutionPolicyMode[];
};

export type RoomExecutionPolicy = {
  mode: RoomExecutionPolicyMode;
  revision: number;
  risk_policy_revision: string;
  kill_switch_enabled: boolean;
  automatic_execution_available: boolean;
  automatic_execution_code: string | null;
  updated_at: string | null;
  actions: { update: RoomExecutionPolicyUpdateDescriptor };
};

export type RoomExecutionVoteCounts = {
  required: number;
  endorse: number;
  object: number;
  abstain: number;
  pending: number;
};

export type RoomExecutionGateSummary = {
  total: number;
  pending: number;
  running: number;
  passed: number;
  failed: number;
};

export type RoomExecutionGateProfileReference = {
  schema_version: "room_execution_gate_profile/v1";
  profile_id: "docs/v1" | "python-uv/v1" | "xmuse-monorepo/v2";
  revision: number;
  gate_ids: string[];
};

export type RoomExecutionGateProfileStatus = RoomExecutionGateProfileReference & {
  readiness: {
    state: "ready" | "blocked";
    ready: boolean;
    code: string;
  };
};

export type RoomExecutionRunSummary = {
  run_id: string;
  state: string;
  revision: number;
  attempt_number: number;
  created_at: string | null;
  updated_at: string | null;
  finished_at: string | null;
  reason_code: string | null;
  gate_profile?: RoomExecutionGateProfileReference | null;
  gate_summary: RoomExecutionGateSummary;
};

export type RoomExecutionCandidateSummary = {
  candidate_id: string;
  proposal_id: string | null;
  digest: string;
  revision: number;
  state: string;
  consensus_state: string | null;
  reason_code: string | null;
  gate_profile?: RoomExecutionGateProfileReference | null;
  summary: string;
  author: { participant_id: string | null; display_name: string | null };
  allowed_files: string[];
  file_count: number;
  byte_count: number;
  votes: RoomExecutionVoteCounts;
  run: RoomExecutionRunSummary | null;
  gate_summary: RoomExecutionGateSummary;
  created_at: string | null;
  updated_at: string | null;
};

export type RoomExecutionListProjection = {
  schema_version: "room_execution_list_projection/v1";
  projection_only: true;
  proof_boundary: string;
  generated_at: string;
  conversation_id: string;
  gate_profile?: RoomExecutionGateProfileStatus | null;
  policy: RoomExecutionPolicy;
  candidate_total: number;
  candidates: RoomExecutionCandidateSummary[];
  page: {
    limit: number;
    cursor: string | null;
    has_more: boolean;
    next_cursor: string | null;
  };
};

export type RoomExecutionDecisionDescriptor = {
  available: boolean;
  method: "POST";
  href: string;
  expected_candidate_digest: string;
  expected_candidate_revision: number;
  expected_policy_revision: number;
};

export type RoomExecutionCancelDescriptor = {
  available: boolean;
  method: "POST";
  href: string;
  expected_run_state: string;
  expected_run_revision: number;
};

export type RoomExecutionVote = {
  participant_id: string;
  display_name: string | null;
  status_snapshot: string | null;
  assessment: "endorse" | "object" | "abstain" | "pending";
  rationale: string | null;
  created_at: string | null;
};

export type RoomExecutionGate = {
  gate_id: string;
  label: string;
  state: string;
  evidence_digest: string | null;
  started_at: string | null;
  finished_at: string | null;
  reason_code: string | null;
};

export type RoomExecutionCandidateDetail = RoomExecutionCandidateSummary & {
  base_head: string | null;
  unified_diff: string;
  files: Array<{ path: string; change_type: string; hunk_count: number }>;
  review_material_digest: string | null;
  patch_sha256: string | null;
  snapshot_digest: string | null;
  policy_mode_snapshot: string | null;
  policy_revision_snapshot: number;
  risk_policy_revision_snapshot: string;
};

export type RoomExecutionRunDetail = RoomExecutionRunSummary & {
  gates: RoomExecutionGate[];
  actions: { cancel: RoomExecutionCancelDescriptor };
};

export type RoomExecutionCandidateProjection = {
  schema_version: "room_execution_candidate_projection/v1";
  projection_only: true;
  proof_boundary: string;
  generated_at: string;
  conversation_id: string;
  gate_profile?: RoomExecutionGateProfileStatus | null;
  candidate: RoomExecutionCandidateDetail;
  policy: RoomExecutionPolicy;
  votes: RoomExecutionVote[];
  vote_counts: RoomExecutionVoteCounts;
  run: RoomExecutionRunDetail | null;
  actions: {
    execute: RoomExecutionDecisionDescriptor;
    reject: RoomExecutionDecisionDescriptor;
  };
};

export type RoomExecutionActionResult = {
  action_id: string;
  status: string;
  conversation_id: string | null;
  candidate_id: string | null;
  run_id: string | null;
  state: string | null;
  revision: number | null;
  policy_mode: RoomExecutionPolicyMode | null;
  policy_revision: number | null;
  proof_boundary: string;
};

export type RoomMemoryResolveDescriptor = {
  available: boolean;
  method: "POST";
  href: string;
  expected_digest: string;
  expected_revision: number;
  allowed_decisions: Array<"approve" | "reject">;
};

export type RoomMemoryCandidate = {
  candidate_id: string;
  conversation_id: string;
  author_participant_id: string | null;
  kind: "room_fact" | "room_decision" | "user_preference" | "project_rule";
  content: string;
  digest: string;
  source_activity_ids: string[];
  approval_state: "pending" | "approved" | "rejected";
  publish_state: string;
  target_scope: "room" | "local_user" | "project";
  revision: number;
  reason_code: string | null;
  created_at: string | null;
  resolved_at: string | null;
  updated_at: string | null;
  actions: { resolve: RoomMemoryResolveDescriptor };
};

export type RoomMemoryRecallSource = {
  activity_id: string;
  content_sha256: string | null;
  archive_scope: string | null;
};

export type RoomMemoryRecall = {
  receipt_id: string | null;
  participant_id: string | null;
  status: string;
  schema_version?: string | null;
  latency_ms?: number;
  item_count?: number;
  source_refs?: RoomMemoryRecallSource[];
  evidence_sha256?: string | null;
  created_at: string | null;
};

export type RoomMemoryProjection = {
  schema_version: "room_memory_projection/v1";
  projection_only: true;
  proof_boundary: string;
  generated_at: string;
  conversation_id: string;
  enabled: boolean;
  degraded: boolean;
  runtime: {
    enabled: boolean;
    degraded: boolean;
    state: RoomMemoryRuntimeState;
    code: string | null;
    consecutive_restart_count: number;
    next_retry_at: string | null;
    last_healthy_at: string | null;
    started_at: string | null;
    updated_at: string | null;
  };
  binding: {
    present: boolean;
    session_state: string | null;
    attachment_state: string | null;
    revision: number;
    updated_at: string | null;
  };
  sync: {
    backlog: number;
    pending: number;
    processing: number;
    failed: number;
    conflict: number;
    delivered: number;
  };
  recent_recalls: RoomMemoryRecall[];
  pending_candidate_total: number;
  pending_candidates: RoomMemoryCandidate[];
};

export type RoomMemoryResolveResult = {
  action_id: string;
  status: string;
  candidate_id: string;
  conversation_id: string | null;
  approval_state: string | null;
  publish_state: string | null;
  revision: number | null;
  reason_code: string | null;
  proof_boundary: string;
};
