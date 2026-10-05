import type { AgentText } from "./board-types";

/** Module-level integration status (§3.11). Unknown server values degrade to "unknown". */
export type BoardModuleIntegrationStatus =
  | "none"
  | "waiting"
  | "pending"
  | "running"
  | "integrated"
  | "conflicted"
  | "gate_failed"
  | "error"
  | "unknown";

export type BoardModuleIntegration = {
  status: BoardModuleIntegrationStatus;
  /** Raw status string when the server sends an unknown value. */
  statusRaw: string | null;
  integration_id: string | null;
  verification_id: string | null;
  integrated_verification_id: string | null;
  reason_code: string | null;
  conflict_path_count: number;
  gate_ids: string[];
  updated_at: string | null;
};

/** Job-level status for the room integration and the detail route (§3.11, §5.3). */
export type BoardIntegrationJobStatus =
  | "pending"
  | "running"
  | "integrated"
  | "conflicted"
  | "gate_failed"
  | "error"
  | "unknown";

export type RoomIntegrationLatest = {
  integration_id: string;
  status: BoardIntegrationJobStatus;
  /** Raw status string when the server sends an unknown value. */
  statusRaw: string | null;
  reason_code: string | null;
  module_count: number;
  finished_at: string | null;
};

export type RoomIntegration = {
  green_head_commit: string | null;
  latest: RoomIntegrationLatest | null;
};

export type RoomBoardSummaryIntegration = {
  status: BoardIntegrationJobStatus | null;
  /** Raw status string when the server sends an unknown value. */
  statusRaw: string | null;
  green_head_commit: string | null;
};

export type BoardIntegrationItemRole = "incumbent" | "newcomer" | "unknown";

export type BoardIntegrationItemStatus =
  | "applied"
  | "fell_back"
  | "conflicted"
  | "waiting"
  | "not_applied"
  | "unknown";

export type BoardIntegrationConflict = {
  path: string;
  attributed_module_ids: string[];
};

export type BoardIntegrationItem = {
  module_id: string;
  verification_id: string;
  order: number;
  role: BoardIntegrationItemRole;
  /** Raw role string when the server sends an unknown value. */
  roleRaw: string | null;
  status: BoardIntegrationItemStatus;
  /** Raw status string when the server sends an unknown value. */
  statusRaw: string | null;
  applied_verification_id: string | null;
  conflicts: BoardIntegrationConflict[];
  conflicts_total: number;
};

export type BoardIntegrationGateStatus =
  | "passed"
  | "failed"
  | "error"
  | "pending"
  | "running"
  | "skipped"
  | "waiting"
  | "unknown";

export type BoardIntegrationGate = {
  gate_id: string;
  status: BoardIntegrationGateStatus;
  /** Raw status string when the server sends an unknown value. */
  statusRaw: string | null;
  exit_code: number | null;
  reason_code: string | null;
  output_tail: AgentText | null;
};

export type BoardIntegrationDetail = {
  schema_version: "room_board_integration/v1";
  conversation_id: string;
  integration_id: string;
  status: BoardIntegrationJobStatus;
  /** Raw status string when the server sends an unknown value. */
  statusRaw: string | null;
  reason_code: string | null;
  green_head_commit: string | null;
  result_commit: string | null;
  items: BoardIntegrationItem[];
  gates: BoardIntegrationGate[];
  attempt_count: number;
  created_at: string;
  finished_at: string | null;
};

/** The `none` values for a module with no integration candidate (§3.11). */
export function noneModuleIntegration(): BoardModuleIntegration {
  return {
    status: "none",
    statusRaw: null,
    integration_id: null,
    verification_id: null,
    integrated_verification_id: null,
    reason_code: null,
    conflict_path_count: 0,
    gate_ids: [],
    updated_at: null
  };
}

/** Empty room-level integration: no green head, no job yet. */
export function emptyRoomIntegration(): RoomIntegration {
  return { green_head_commit: null, latest: null };
}

/** Empty summary integration: no latest status, no green head. */
export function emptySummaryIntegration(): RoomBoardSummaryIntegration {
  return { status: null, statusRaw: null, green_head_commit: null };
}
