import type {
  BoardModuleIntegration,
  RoomBoardSummaryIntegration,
  RoomIntegration
} from "./board-integration-types";
import type { BoardReview } from "./board-review-types";

export type BoardState =
  | "assigned"
  | "claimed"
  | "working"
  | "blocked"
  | "ready_for_review"
  | "done_claimed"
  | "verifying"
  | "waiting_for_provider"
  | "verified"
  | "verification_failed"
  | "verification_error"
  | "unknown";

export type BoardLifecycle =
  | "assigned"
  | "claimed"
  | "working"
  | "blocked"
  | "ready_for_review"
  | "done_claimed"
  | "unknown";

export type BoardVerificationStatus =
  | "none"
  | "waiting_for_provider"
  | "pending"
  | "running"
  | "passed"
  | "failed"
  | "error"
  | "unknown";

export type BoardAttentionKind =
  | "none"
  | "operator"
  | "lead"
  | "owner"
  | "unknown";

export type BoardEventKind =
  | "split_proposed"
  | "split_rejected"
  | "charter_assigned"
  | "claimed"
  | "contract_published"
  | "contract_revised"
  | "progress"
  | "question"
  | "verification"
  | "review_requested"
  | "review"
  | "integration"
  | "unknown";

export type BoardSplitStatus =
  | "proposed"
  | "approved"
  | "rejected"
  | "superseded"
  | "unknown";

export type BoardContractKind =
  | "api_schema"
  | "types"
  | "protocol"
  | "text"
  | "unknown";

export type AgentText = {
  text: string;
  untrusted: true;
  truncated: boolean;
};

export type BoardCapabilities = {
  verification: number;
  reviews: number;
  integrations: number;
  lessons: number;
};

export type BoardParticipant = {
  participant_id: string;
  display_name: string;
  provider_kind: string;
  model_family: string;
  role_preset: string | null;
  is_lead: boolean;
};

export type BoardVerificationStacked = {
  module_id: string;
  verification_id: string;
};

export type BoardVerification = {
  status: BoardVerificationStatus;
  verification_id: string | null;
  reason_code: string | null;
  escalated: boolean;
  gate_ids: string[];
  stacked: BoardVerificationStacked[];
  head_commit: string | null;
  changed_path_count: number;
  updated_at: string | null;
};

export type BoardCounters = {
  done_reports: number;
  passed: number;
  failed: number;
  superseded: number;
  errored: number;
  rework_rounds: number;
  reviews_endorsed: number;
  reviews_objected: number;
  integrations_conflicted: number;
  integrations_gate_failed: number;
  conflict_fix_rounds: number;
};

export type BoardModuleAttention = {
  kind: BoardAttentionKind;
  reason_code: string | null;
};

export type BoardModule = {
  module_id: string;
  title: AgentText;
  owner_participant_id: string;
  report_to: string | null;
  charter_version: number;
  paths: string[];
  provides: string[];
  depends: string[];
  lifecycle: BoardLifecycle;
  verification: BoardVerification;
  counters: BoardCounters;
  state: BoardState;
  review: BoardReview;
  accepted: boolean;
  integration: BoardModuleIntegration;
  attention: BoardModuleAttention;
};

export type BoardContractSummary = {
  contract_id: string;
  latest_version: number;
  versions_count: number;
  digest: string;
  provider_module_id: string;
  kind: BoardContractKind;
  author_participant_id: string;
  updated_at: string;
};

export type BoardSplitDecideAction = {
  available: boolean;
  method: string;
  href: string;
  expected_digest: string | null;
  allowed_decisions: string[];
};

export type BoardSplitModule = {
  module_id: string;
  title: AgentText;
  owner_participant_id: string;
  paths: string[];
  provides: string[];
  depends: string[];
};

export type BoardSplitContract = {
  contract_id: string;
  provider_module_id: string;
  kind: BoardContractKind;
  digest: string;
};

export type BoardSplit = {
  split_id: string;
  status: BoardSplitStatus;
  proposed_by_participant_id: string;
  created_at: string;
  decided_at: string | null;
  digest: string;
  decided_via: string | null;
  modules: BoardSplitModule[];
  contracts: BoardSplitContract[];
  actions?: {
    decide?: BoardSplitDecideAction | null;
  };
};

export type BoardStaleDependent = {
  contract_id: string;
  revised_version: number;
  revised_seq: number;
  module_id: string;
  owner_participant_id: string;
};

export type BoardAttentionItem = {
  kind: Exclude<BoardAttentionKind, "none"> | "unknown";
  reason_code: string;
  module_id: string | null;
  split_id: string | null;
  integration_id: string | null;
};

export type BoardEventActor = {
  kind: string;
  participant_id: string | null;
};

export type BoardEvent = {
  seq: number;
  kind: string;
  typedKind: BoardEventKind;
  at: string;
  module_id: string | null;
  actor: BoardEventActor;
  data: Record<string, unknown>;
};

export type RoomBoardProjection = {
  schema_version: "room_board_projection/v2";
  metrics_version: string;
  conversation_id: string;
  server_time: string;
  board_seq: number;
  revision: string;
  capabilities: BoardCapabilities;
  review_policy: string;
  integration: RoomIntegration;
  participants: BoardParticipant[];
  modules: BoardModule[];
  contracts: BoardContractSummary[];
  splits: BoardSplit[];
  stale_dependents: BoardStaleDependent[];
  attention: BoardAttentionItem[];
  events: BoardEvent[];
};

export type RoomBoardCounts = Record<BoardState extends never ? never : string, number> & {
  assigned: number;
  claimed: number;
  working: number;
  blocked: number;
  ready_for_review: number;
  done_claimed: number;
  verifying: number;
  waiting_for_provider: number;
  verified: number;
  verification_failed: number;
  verification_error: number;
};

export type RoomBoardSummary = {
  schema_version: "room_board_summary/v1";
  conversation_id: string;
  server_time: string;
  board_seq: number;
  revision: string;
  capabilities: BoardCapabilities;
  modules_total: number;
  counts: RoomBoardCounts;
  accepted_total: number;
  integrated_total: number;
  integration: RoomBoardSummaryIntegration;
  attention_total: number;
  attention: BoardAttentionItem[];
};

export type BoardContractVersion = {
  version: number;
  digest: string;
  author_participant_id: string;
  created_at: string;
  rationale: AgentText | null;
};

export type BoardContractDetail = {
  schema_version: "room_board_contract/v2";
  conversation_id: string;
  contract_id: string;
  provider_module_id: string;
  kind: BoardContractKind;
  versions: BoardContractVersion[];
  version: number;
  content: AgentText;
};
