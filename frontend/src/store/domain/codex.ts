import type {
  RoomCodexActionDescriptor,
  RoomCodexActionResult,
  RoomCodexCapabilityId,
  RoomCodexProjection,
  RoomCodexSafeRequestByCapability,
  XmuseApiErrorShape
} from "@/lib/types";
import type { CodexConsoleTurnMode } from "@/store/codex-console-preferences";

import type { DomainCapability, DomainSelector } from "./shared";

export type RoomCodexCache = {
  projection: RoomCodexProjection | null;
  selectedParticipantId: string | null;
  loading: boolean;
  requestGeneration: number;
  consecutiveFailures: number;
  lastSyncedAt: number;
  error: XmuseApiErrorShape | null;
  actionPending: Record<string, { capabilityId: string; clientActionId: string }>;
  actionErrors: Record<string, XmuseApiErrorShape | null>;
};

export type CodexDomainState = {
  codexByRoom: Record<string, RoomCodexCache>;
  codexPreferenceRevision: number;
};

export type CodexDomainActions = {
  refreshCodexAgents: (roomId?: string) => Promise<void>;
  selectCodexParticipant: (participantId: string | null, roomId?: string) => void;
  submitCodexAction: <TCapability extends RoomCodexCapabilityId>(
    participantId: string,
    capabilityId: TCapability,
    request: RoomCodexSafeRequestByCapability[TCapability],
    descriptor: RoomCodexActionDescriptor,
    confirmedPendingObservations?: boolean
  ) => Promise<RoomCodexActionResult | null>;
  getCodexConsolePreference: (participantId: string) => CodexConsoleTurnMode;
  setCodexConsolePreference: (participantId: string, mode: CodexConsoleTurnMode) => void;
  startCodexSync: () => void;
};

export type CodexDomain = CodexDomainState & CodexDomainActions;
export type CodexReadCapability = DomainCapability<CodexDomain, "codexByRoom">;
export type CodexWriteCapability = DomainCapability<
  CodexDomain,
  | "selectCodexParticipant"
  | "submitCodexAction"
  | "getCodexConsolePreference"
  | "setCodexConsolePreference"
>;

export function createCodexCacheSelector(
  roomId: string
): DomainSelector<CodexDomainState, RoomCodexCache | null> {
  return (state) => state.codexByRoom[roomId] ?? null;
}
