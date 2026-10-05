import type { AgentText } from "./board-types";

export type BoardReviewStatus =
  | "none"
  | "pending"
  | "endorsed"
  | "objected"
  | "superseded"
  | "unknown";

export type BoardReviewDetailStatus =
  | "pending"
  | "endorsed"
  | "objected"
  | "superseded"
  | "unknown";

export type BoardReviewerKind = "participant" | "operator" | "unknown";

export type BoardReviewDecidedVia = "board_tool" | "web" | "unknown";

export type BoardReviewSeverity = "blocker" | "major" | "minor" | "unknown";

export type BoardReviewVerdict = "endorse" | "object";

export type BoardReviewPolicy = "off" | "cross_family" | "unknown";

export type BoardFindingsCount = {
  blocker: number;
  major: number;
  minor: number;
};

export type BoardReviewEscalation = {
  participant_id: string;
  family: string;
  reason_code: string;
  at: string;
};

export type BoardReviewDecideAction = {
  available: boolean;
  method: string;
  href: string;
  expected_digest: string | null;
  allowed_verdicts: string[];
};

export type BoardReviewActions = {
  decide?: BoardReviewDecideAction | null;
  material?: { available: boolean } | null;
};

export type BoardReview = {
  status: BoardReviewStatus;
  /** Raw status string when the server sends an unknown value. */
  statusRaw: string | null;
  review_id: string | null;
  verification_id: string | null;
  digest: string | null;
  rule_id: string | null;
  author_family: string | null;
  reviewer_kind: BoardReviewerKind | null;
  reviewerKindRaw: string | null;
  reviewer_participant_id: string | null;
  reviewer_family: string | null;
  escalated_from: BoardReviewEscalation | null;
  findings_count: BoardFindingsCount;
  decided_via: BoardReviewDecidedVia | null;
  decidedViaRaw: string | null;
  updated_at: string | null;
  actions: BoardReviewActions;
};

export type BoardReviewFinding = {
  severity: BoardReviewSeverity;
  severityRaw: string | null;
  path: string | null;
  text: AgentText;
};

export type BoardReviewEligible = {
  participant_id: string;
  family: string;
  pending: number;
};

export type BoardReviewRuleInputs = {
  rule_id: string;
  author_participant_id: string;
  author_family: string;
  eligible: BoardReviewEligible[];
  last_reviewer_participant_id: string | null;
  picked_participant_id: string | null;
};

export type BoardReviewDetail = {
  schema_version: "room_board_review/v1";
  conversation_id: string;
  module_id: string;
  review: BoardReview;
  head_commit: string;
  summary: AgentText | null;
  findings: BoardReviewFinding[];
  rule_inputs: BoardReviewRuleInputs;
  created_at: string;
  decided_at: string | null;
};

export type BoardReviewMaterialPatch = {
  text: string;
  bytes_total: number;
  truncated: boolean;
  hidden_char_count: number;
};

export type BoardReviewMaterial = {
  schema_version: "room_board_review_material/v1";
  review_id: string;
  verification_id: string;
  head_commit: string;
  digest: string;
  patch: BoardReviewMaterialPatch;
};

export type BoardReviewDecisionInput = {
  conversation_id: string;
  verdict: BoardReviewVerdict;
  expected_digest: string;
  summary: string;
  findings: Array<{ severity: string; path: string | null; text: string }>;
};
