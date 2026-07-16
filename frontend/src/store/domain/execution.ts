import type {
  RoomExecutionCancelDescriptor,
  RoomExecutionCandidateProjection,
  RoomExecutionDecisionDescriptor,
  RoomExecutionListProjection,
  RoomExecutionPolicyMode,
  RoomExecutionPolicyUpdateDescriptor,
  XmuseApiErrorShape
} from "@/lib/types";

import type { DomainCapability, DomainSelector } from "./shared";

export type RoomExecutionCache = {
  list: RoomExecutionListProjection | null;
  details: Record<string, RoomExecutionCandidateProjection>;
  selectedCandidateId: string | null;
  loading: boolean;
  detailLoading: boolean;
  requestGeneration: number;
  consecutiveFailures: number;
  lastSyncedAt: number;
  error: XmuseApiErrorShape | null;
};

export type ExecutionDomainState = {
  executionsByRoom: Record<string, RoomExecutionCache>;
  executionActionPending: {
    kind: "policy" | "execute" | "reject" | "cancel";
    targetId: string;
  } | null;
  executionActionError: XmuseApiErrorShape | null;
};

export type ExecutionDomainActions = {
  refreshExecutions: (roomId?: string, candidateId?: string | null) => Promise<void>;
  selectExecutionCandidate: (candidateId: string | null) => Promise<void>;
  updateExecutionPolicy: (
    mode: RoomExecutionPolicyMode,
    descriptor: RoomExecutionPolicyUpdateDescriptor
  ) => Promise<boolean>;
  decideExecutionCandidate: (
    candidateId: string,
    decision: "execute" | "reject",
    descriptor: RoomExecutionDecisionDescriptor
  ) => Promise<boolean>;
  cancelExecutionRun: (
    runId: string,
    descriptor: RoomExecutionCancelDescriptor
  ) => Promise<boolean>;
  startExecutionSync: () => void;
};

export type ExecutionDomain = ExecutionDomainState & ExecutionDomainActions;
export type ExecutionReadCapability = DomainCapability<
  ExecutionDomain,
  "executionsByRoom" | "executionActionPending" | "executionActionError"
>;
export type ExecutionWriteCapability = DomainCapability<
  ExecutionDomain,
  | "selectExecutionCandidate"
  | "updateExecutionPolicy"
  | "decideExecutionCandidate"
  | "cancelExecutionRun"
>;

export function createExecutionCacheSelector(
  roomId: string
): DomainSelector<ExecutionDomainState, RoomExecutionCache | null> {
  return (state) => state.executionsByRoom[roomId] ?? null;
}
