import type {
  RoomCache,
  RoomCodexCache,
  RoomExecutionCache,
  RoomMemoryCache
} from "@/store/domain";

/**
 * Creates cache records at the store boundary.  Domain components deliberately
 * consume nullable cache selectors instead of allocating fallbacks while they
 * render, so allocations stay on state-transition paths only.
 */
export function createEmptyRoomCache(now = Date.now()): RoomCache {
  return {
    projection: null,
    timelineItems: [],
    pendingMessages: [],
    requestGeneration: 0,
    loading: false,
    loadingOlder: false,
    eventCursor: 0,
    syncState: "idle",
    consecutiveFailures: 0,
    lastSyncedAt: 0,
    lastAccessedAt: now,
    error: null,
    controlPending: null,
    controlError: null,
    agentStreams: [],
    agentStreamAvailable: true,
    agentStreamEpoch: null,
    agentStreamSeq: 0,
    agentStreamGeneration: 0
  };
}

export function createEmptyExecutionCache(): RoomExecutionCache {
  return {
    list: null,
    details: {},
    selectedCandidateId: null,
    loading: false,
    detailLoading: false,
    requestGeneration: 0,
    consecutiveFailures: 0,
    lastSyncedAt: 0,
    error: null
  };
}

export function createEmptyMemoryCache(): RoomMemoryCache {
  return {
    projection: null,
    loading: false,
    requestGeneration: 0,
    consecutiveFailures: 0,
    lastSyncedAt: 0,
    error: null
  };
}

export function createEmptyCodexCache(): RoomCodexCache {
  return {
    projection: null,
    selectedParticipantId: null,
    loading: false,
    requestGeneration: 0,
    consecutiveFailures: 0,
    lastSyncedAt: 0,
    error: null,
    actionPending: {},
    actionErrors: {}
  };
}
