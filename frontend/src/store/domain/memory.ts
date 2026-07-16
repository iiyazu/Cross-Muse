import type {
  RoomMemoryProjection,
  RoomMemoryRebuildDescriptor,
  RoomMemoryResolveDescriptor,
  XmuseApiErrorShape
} from "@/lib/types";

import type { DomainCapability, DomainSelector } from "./shared";

export type RoomMemoryCache = {
  projection: RoomMemoryProjection | null;
  loading: boolean;
  requestGeneration: number;
  consecutiveFailures: number;
  lastSyncedAt: number;
  error: XmuseApiErrorShape | null;
};

export type MemoryDomainState = {
  memoryByRoom: Record<string, RoomMemoryCache>;
  memoryActionPending: { candidateId: string; decision: "approve" | "reject" } | null;
  memoryActionError: XmuseApiErrorShape | null;
  memoryRebuildPending: boolean;
  memoryRebuildIncidentId: string | null;
  memoryRebuildError: XmuseApiErrorShape | null;
};

export type MemoryDomainActions = {
  refreshMemory: (roomId?: string) => Promise<void>;
  resolveMemoryCandidate: (
    candidateId: string,
    decision: "approve" | "reject",
    descriptor: RoomMemoryResolveDescriptor
  ) => Promise<boolean>;
  rebuildMemoryIndex: (descriptor: RoomMemoryRebuildDescriptor) => Promise<boolean>;
  startMemorySync: () => void;
};

export type MemoryDomain = MemoryDomainState & MemoryDomainActions;
export type MemoryReadCapability = DomainCapability<
  MemoryDomain,
  | "memoryByRoom"
  | "memoryActionPending"
  | "memoryActionError"
  | "memoryRebuildPending"
  | "memoryRebuildError"
>;
export type MemoryWriteCapability = DomainCapability<
  MemoryDomain,
  "resolveMemoryCandidate" | "rebuildMemoryIndex"
>;

export function createMemoryCacheSelector(
  roomId: string
): DomainSelector<MemoryDomainState, RoomMemoryCache | null> {
  return (state) => state.memoryByRoom[roomId] ?? null;
}
