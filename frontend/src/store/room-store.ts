"use client";

import { create } from "zustand";

import {
  cancelRoomExecutionRun,
  createConversation,
  decideRoomExecutionCandidate,
  describeError,
  fetchEvents,
  fetchRoomMemory,
  fetchRoomCodexAgents,
  fetchRoomOperations,
  fetchRoomExecutionCandidate,
  fetchRoomExecutions,
  fetchRoomProjection,
  fetchRooms,
  isCallerAbort,
  recoverRoomRuntime,
  rebuildRoomMemoryIndex,
  resolveRoomMemoryCandidate,
  sendThreadMessage,
  submitRoomObservationControl,
  submitRoomCodexAction,
  updateRoomExecutionPolicy
} from "@/lib/api";
import {
  normalizeRoomList,
  normalizeRoomMemoryProjection,
  normalizeRoomOperationsProjection,
  normalizeRoomProjection
} from "@/lib/room-view";
import type {
  RoomChatProjection,
  RoomCodexActionDescriptor,
  RoomCodexActionResult,
  RoomCodexCapabilityId,
  RoomCodexProjection,
  RoomCodexSafeRequestByCapability,
  RoomControlActionDescriptor,
  RoomExecutionCancelDescriptor,
  RoomExecutionCandidateProjection,
  RoomExecutionDecisionDescriptor,
  RoomExecutionListProjection,
  RoomExecutionPolicyMode,
  RoomExecutionPolicyUpdateDescriptor,
  RoomMessageReceipt,
  RoomMemoryRebuildDescriptor,
  RoomMemoryProjection,
  RoomMemoryResolveDescriptor,
  RoomOperationsProjection,
  RoomRuntimeRecoverDescriptor,
  RoomSummary,
  RoomTimelineItem,
  XmuseApiErrorShape
} from "@/lib/types";
import {
  clearExecutionAction,
  clearMemoryAction,
  clearMemoryRebuildAction,
  clearRuntimeRecoverAction,
  executionActionId,
  memoryActionId,
  memoryRebuildActionId,
  retainActionIdAfterFailure,
  runtimeRecoverActionId
} from "@/store/action-id-registry";
import {
  mergeRoomProjectionPage,
  mergeRoomTimelineItems,
  projectionCursorRegressed as didProjectionCursorRegress,
  roomProjectionCursors,
  trimRoomCaches
} from "@/store/room-cache";
import {
  persistRoomDraft,
  persistRoomUiState,
  readRoomDraft,
  readRoomUiState
} from "@/store/room-persistence";
import type { ScrollAnchor } from "@/store/room-persistence";
import { createRoomSyncCoordinator } from "@/store/room-sync-coordinator";
import {
  persistCodexConsolePreference,
  readCodexConsolePreference
} from "@/store/codex-console-preferences";
import type { CodexConsoleTurnMode } from "@/store/codex-console-preferences";

export type { ScrollAnchor } from "@/store/room-persistence";

export type RoomSyncState = "idle" | "syncing" | "synced" | "catching-up" | "stale" | "offline";

export type PendingRoomMessage = {
  clientRequestId: string;
  content: string;
  createdAt: string;
  status: "sending" | "failed";
  error?: XmuseApiErrorShape | null;
};

export type RoomCache = {
  projection: RoomChatProjection | null;
  timelineItems: RoomTimelineItem[];
  pendingMessages: PendingRoomMessage[];
  requestGeneration: number;
  loading: boolean;
  loadingOlder: boolean;
  eventCursor: number;
  syncState: RoomSyncState;
  consecutiveFailures: number;
  lastSyncedAt: number;
  lastAccessedAt: number;
  error: XmuseApiErrorShape | null;
  controlPending: { observationId: string; action: "cancel" | "retry" } | null;
  controlError: XmuseApiErrorShape | null;
};

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

export type RoomMemoryCache = {
  projection: RoomMemoryProjection | null;
  loading: boolean;
  requestGeneration: number;
  consecutiveFailures: number;
  lastSyncedAt: number;
  error: XmuseApiErrorShape | null;
};

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

type RoomState = {
  rooms: RoomSummary[];
  roomsById: Record<string, RoomCache>;
  selectedRoomId: string | null;
  roomsLoading: boolean;
  roomsLoaded: boolean;
  roomsError: XmuseApiErrorShape | null;
  roomCreatePending: boolean;
  roomCreateError: XmuseApiErrorShape | null;
  drafts: Record<string, string>;
  readCursors: Record<string, number>;
  scrollAnchors: Record<string, ScrollAnchor>;
  theme: "dark" | "light";
  sidebarOpen: boolean;
  inspectorOpen: boolean;
  operations: RoomOperationsProjection | null;
  operationsLoading: boolean;
  operationsError: XmuseApiErrorShape | null;
  operationsGeneration: number;
  operationsConsecutiveFailures: number;
  executionsByRoom: Record<string, RoomExecutionCache>;
  memoryByRoom: Record<string, RoomMemoryCache>;
  codexByRoom: Record<string, RoomCodexCache>;
  codexPreferenceRevision: number;
  executionActionPending: {
    kind: "policy" | "execute" | "reject" | "cancel";
    targetId: string;
  } | null;
  executionActionError: XmuseApiErrorShape | null;
  memoryActionPending: {
    candidateId: string;
    decision: "approve" | "reject";
  } | null;
  memoryActionError: XmuseApiErrorShape | null;
  memoryRebuildPending: boolean;
  memoryRebuildIncidentId: string | null;
  memoryRebuildError: XmuseApiErrorShape | null;
  runtimeRecoverPending: boolean;
  runtimeRecoverError: XmuseApiErrorShape | null;
  inspectorTarget: {
    roomId: string;
    observationId: string | null;
    incidentId: string;
  } | null;
  bootstrap: (requestedRoomId?: string | null) => Promise<string | null>;
  loadRooms: () => Promise<RoomSummary[]>;
  createRoom: (title: string, clientRequestId?: string) => Promise<string | null>;
  selectRoom: (roomId: string) => Promise<void>;
  refreshRoom: (roomId?: string, mode?: "initial" | "incremental" | "older") => Promise<void>;
  catchUpRoom: (roomId?: string) => Promise<void>;
  loadOlder: (roomId?: string) => Promise<void>;
  sendMessage: (content: string, clientRequestId?: string) => Promise<string | null>;
  retryMessage: (clientRequestId: string) => Promise<void>;
  controlObservation: (
    observationId: string,
    action: "cancel" | "retry",
    descriptor: RoomControlActionDescriptor
  ) => Promise<boolean>;
  refreshOperations: () => Promise<void>;
  refreshExecutions: (roomId?: string, candidateId?: string | null) => Promise<void>;
  refreshMemory: (roomId?: string) => Promise<void>;
  refreshCodexAgents: (roomId?: string) => Promise<void>;
  selectCodexParticipant: (participantId: string | null, roomId?: string) => void;
  submitCodexAction: (
    participantId: string,
    capabilityId: RoomCodexCapabilityId,
    request: RoomCodexSafeRequestByCapability[RoomCodexCapabilityId],
    descriptor: RoomCodexActionDescriptor,
    confirmedPendingObservations?: boolean
  ) => Promise<RoomCodexActionResult | null>;
  getCodexConsolePreference: (participantId: string) => CodexConsoleTurnMode;
  setCodexConsolePreference: (participantId: string, mode: CodexConsoleTurnMode) => void;
  resolveMemoryCandidate: (
    candidateId: string,
    decision: "approve" | "reject",
    descriptor: RoomMemoryResolveDescriptor
  ) => Promise<boolean>;
  rebuildMemoryIndex: (descriptor: RoomMemoryRebuildDescriptor) => Promise<boolean>;
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
  recoverRuntime: (descriptor: RoomRuntimeRecoverDescriptor) => Promise<boolean>;
  setDraft: (roomId: string, draft: string) => void;
  markRead: (roomId: string, roomSeq: number) => void;
  saveScrollAnchor: (roomId: string, anchor: ScrollAnchor | null) => void;
  setTheme: (theme: "dark" | "light") => void;
  setSidebarOpen: (open: boolean) => void;
  setInspectorOpen: (open: boolean) => void;
  setInspectorTarget: (target: RoomState["inspectorTarget"]) => void;
  clearRoomError: (roomId?: string) => void;
  clearControlError: (roomId?: string) => void;
  startSync: () => void;
  startOperationsSync: () => void;
  startExecutionSync: () => void;
  startMemorySync: () => void;
  startCodexSync: () => void;
  stopSync: () => void;
};

const chatApiBaseUrl = process.env.NEXT_PUBLIC_XMUSE_CHAT_API_BASE_URL;
const MESSAGE_SEND_TIMEOUT_MS = 24_000;
const SAFE_REFRESH_MS = 15_000;
const ROOM_LIST_REFRESH_MS = 12_000;

const syncCoordinator = createRoomSyncCoordinator();
let lastSafeRefreshAt = 0;
let lastRoomListRefreshAt = 0;
const requestControllers = new Map<string, AbortController>();
const eventControllers = new Map<string, AbortController>();
let operationsController: AbortController | null = null;
let operationsRequest: Promise<void> | null = null;
let memoryRebuildWriteInFlight = false;
const executionControllers = new Map<string, AbortController>();
const executionRequests = new Map<string, Promise<void>>();
const memoryControllers = new Map<string, AbortController>();
const memoryRequests = new Map<string, Promise<void>>();
const codexControllers = new Map<string, AbortController>();
const codexRequests = new Map<string, Promise<void>>();
let codexFocusHandler: (() => void) | null = null;
const CODEX_ACTION_STORAGE_KEY = "xmuse.codex-action-ids.v1";

function apiOptions(signal?: AbortSignal) {
  return { chatApiBaseUrl, signal };
}

function emptyCache(now = Date.now()): RoomCache {
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
    controlError: null
  };
}

function emptyExecutionCache(): RoomExecutionCache {
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

function emptyMemoryCache(): RoomMemoryCache {
  return {
    projection: null,
    loading: false,
    requestGeneration: 0,
    consecutiveFailures: 0,
    lastSyncedAt: 0,
    error: null
  };
}

function emptyCodexCache(): RoomCodexCache {
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

function browserStorage(kind: "local" | "session"): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

function readLocalState(): Pick<
  RoomState,
  "readCursors" | "scrollAnchors" | "theme" | "sidebarOpen" | "inspectorOpen"
> {
  return readRoomUiState(browserStorage("local"));
}

function persistLocalState(state: RoomState) {
  persistRoomUiState(browserStorage("local"), state);
}

function trimCaches(caches: Record<string, RoomCache>, selectedRoomId: string | null) {
  return trimRoomCaches(caches, selectedRoomId);
}

function projectionCursorRegressed(
  cache: RoomCache,
  projection: RoomChatProjection
): boolean {
  return (
    didProjectionCursorRegress(
      cache.eventCursor,
      cache.projection,
      cache.timelineItems,
      projection
    )
  );
}

function receiptTimelineItem(receipt: RoomMessageReceipt, content: string): RoomTimelineItem | null {
  if (!receipt.message?.id || typeof receipt.room_activity_seq !== "number") return null;
  return {
    id: receipt.message.id,
    message_id: receipt.message.id,
    activity_id: receipt.activity_id ?? null,
    room_seq: receipt.room_activity_seq,
    kind: "message",
    actor: { kind: "human", role: "human", display_name: "你" },
    content: receipt.message.content || content,
    created_at: receipt.message.created_at ?? new Date().toISOString()
  };
}

function abortRoomRequest(roomId: string) {
  requestControllers.get(roomId)?.abort();
  requestControllers.delete(roomId);
}

function abortEventRequest(roomId: string) {
  eventControllers.get(roomId)?.abort();
  eventControllers.delete(roomId);
}

function abortOperationsRequest() {
  operationsController?.abort();
  operationsController = null;
  operationsRequest = null;
}

function runtimeRecoverClientActionId(incidentId: string): string {
  return runtimeRecoverActionId(browserStorage("session"), incidentId);
}

function clearRuntimeRecoverClientAction(incidentId: string) {
  clearRuntimeRecoverAction(browserStorage("session"), incidentId);
}

function executionClientActionId(fingerprint: string): string {
  return executionActionId(browserStorage("session"), fingerprint);
}

function clearExecutionClientAction(fingerprint: string) {
  clearExecutionAction(browserStorage("session"), fingerprint);
}

function retainExecutionActionId(error: XmuseApiErrorShape): boolean {
  return retainActionIdAfterFailure(error.status);
}

function abortExecutionRequest(roomId: string) {
  executionControllers.get(roomId)?.abort();
  executionControllers.delete(roomId);
  executionRequests.delete(roomId);
}

function memoryClientActionId(fingerprint: string): string {
  return memoryActionId(browserStorage("session"), fingerprint);
}

function clearMemoryClientAction(fingerprint: string) {
  clearMemoryAction(browserStorage("session"), fingerprint);
}

function memoryRebuildClientActionId(incidentId: string): string {
  return memoryRebuildActionId(browserStorage("session"), incidentId);
}

function clearMemoryRebuildClientAction(incidentId: string) {
  clearMemoryRebuildAction(browserStorage("session"), incidentId);
}

function abortMemoryRequest(roomId: string) {
  memoryControllers.get(roomId)?.abort();
  memoryControllers.delete(roomId);
  memoryRequests.delete(roomId);
}

function abortCodexRequest(roomId: string) {
  codexControllers.get(roomId)?.abort();
  codexControllers.delete(roomId);
  codexRequests.delete(roomId);
}

function codexActionClientId(fingerprint: string): string {
  const storage = browserStorage("session");
  if (!storage) return `ui_codex_${crypto.randomUUID()}`;
  try {
    const parsed = JSON.parse(storage.getItem(CODEX_ACTION_STORAGE_KEY) ?? "{}") as unknown;
    const retained = Object.fromEntries(
      parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? Object.entries(parsed)
            .filter((entry): entry is [string, string] => typeof entry[1] === "string")
            .slice(-49)
        : []
    );
    const existing = retained[fingerprint];
    if (existing) return existing;
    const created = `ui_codex_${crypto.randomUUID()}`;
    retained[fingerprint] = created;
    storage.setItem(CODEX_ACTION_STORAGE_KEY, JSON.stringify(retained));
    return created;
  } catch {
    return `ui_codex_${crypto.randomUUID()}`;
  }
}

function clearCodexActionClientId(fingerprint: string) {
  const storage = browserStorage("session");
  if (!storage) return;
  try {
    const parsed = JSON.parse(storage.getItem(CODEX_ACTION_STORAGE_KEY) ?? "{}") as unknown;
    if (!parsed || typeof parsed !== "object") return;
    const values = parsed as Record<string, string>;
    delete values[fingerprint];
    storage.setItem(CODEX_ACTION_STORAGE_KEY, JSON.stringify(values));
  } catch {
    // Action IDs are best-effort browser replay protection; the server is authoritative.
  }
}

export const useRoomStore = create<RoomState>((set, get) => ({
  rooms: [],
  roomsById: {},
  selectedRoomId: null,
  roomsLoading: false,
  roomsLoaded: false,
  roomsError: null,
  roomCreatePending: false,
  roomCreateError: null,
  drafts: {},
  readCursors: {},
  scrollAnchors: {},
  theme: "dark",
  sidebarOpen: true,
  inspectorOpen: false,
  operations: null,
  operationsLoading: false,
  operationsError: null,
  operationsGeneration: 0,
  operationsConsecutiveFailures: 0,
  executionsByRoom: {},
  memoryByRoom: {},
  codexByRoom: {},
  codexPreferenceRevision: 0,
  executionActionPending: null,
  executionActionError: null,
  memoryActionPending: null,
  memoryActionError: null,
  memoryRebuildPending: false,
  memoryRebuildIncidentId: null,
  memoryRebuildError: null,
  runtimeRecoverPending: false,
  runtimeRecoverError: null,
  inspectorTarget: null,

  async bootstrap(requestedRoomId = null) {
    const local = readLocalState();
    set(local);
    const rooms = await get().loadRooms();
    const selected = requestedRoomId ?? rooms[0]?.conversation_id ?? null;
    if (selected) await get().selectRoom(selected);
    else get().startOperationsSync();
    return selected;
  },

  async loadRooms() {
    set({ roomsLoading: true });
    try {
      const payload = normalizeRoomList(await fetchRooms(apiOptions()));
      const rooms = [...payload.rooms].sort((left, right) => {
        const leftTime = Date.parse(left.updated_at ?? left.created_at ?? "") || 0;
        const rightTime = Date.parse(right.updated_at ?? right.created_at ?? "") || 0;
        return rightTime - leftTime;
      });
      lastRoomListRefreshAt = Date.now();
      set({ rooms, roomsLoading: false, roomsLoaded: true, roomsError: null });
      return rooms;
    } catch (error) {
      set({ roomsLoading: false, roomsError: describeError(error) });
      return get().rooms;
    }
  },

  async createRoom(title, clientRequestId = `ui_room_create_${crypto.randomUUID()}`) {
    const cleanTitle = title.trim();
    if (!cleanTitle) return null;
    set({ roomCreatePending: true, roomCreateError: null });
    try {
      const conversation = await createConversation(cleanTitle, {
        ...apiOptions(),
        clientRequestId
      });
      const id = String(conversation.id);
      await get().loadRooms();
      await get().selectRoom(id);
      set({ roomCreatePending: false, roomCreateError: null });
      return id;
    } catch (error) {
      if (isCallerAbort(error)) {
        set({ roomCreatePending: false });
        return null;
      }
      set({ roomCreatePending: false, roomCreateError: describeError(error) });
      return null;
    }
  },

  async selectRoom(roomId) {
    const previous = get().selectedRoomId;
    if (previous && previous !== roomId) {
      abortRoomRequest(previous);
      abortEventRequest(previous);
      abortExecutionRequest(previous);
      abortMemoryRequest(previous);
      abortCodexRequest(previous);
    }
    const savedDraft = readRoomDraft(browserStorage("session"), roomId);
    set((state) => {
      const cache = state.roomsById[roomId] ?? emptyCache();
      const roomsById = trimCaches(
        {
          ...state.roomsById,
          [roomId]: { ...cache, lastAccessedAt: Date.now() }
        },
        roomId
      );
      return {
        selectedRoomId: roomId,
        roomsById,
        drafts: state.drafts[roomId] === undefined
          ? { ...state.drafts, [roomId]: savedDraft }
          : state.drafts
      };
    });
    const cache = get().roomsById[roomId];
    if (!cache?.projection) await get().refreshRoom(roomId, "initial");
    else if (Date.now() - cache.lastSyncedAt > 5_000) await get().refreshRoom(roomId, "incremental");
    if (get().inspectorOpen) {
      void get().refreshExecutions(roomId);
      void get().refreshMemory(roomId);
      void get().refreshCodexAgents(roomId);
    }
    get().startSync();
  },

  async refreshRoom(roomId = get().selectedRoomId ?? "", mode = "incremental") {
    if (!roomId) return;
    const current = get().roomsById[roomId] ?? emptyCache();
    const { beforeRoomSeq, afterRoomSeq } = roomProjectionCursors(
      mode,
      current.projection,
      current.timelineItems
    );
    if (mode === "older" && (beforeRoomSeq === undefined || !current.projection?.has_older)) return;

    abortRoomRequest(roomId);
    const controller = new AbortController();
    requestControllers.set(roomId, controller);
    const generation = current.requestGeneration + 1;
    set((state) => ({
      roomsById: {
        ...state.roomsById,
        [roomId]: {
          ...(state.roomsById[roomId] ?? emptyCache()),
          requestGeneration: generation,
          loading: mode !== "older",
          loadingOlder: mode === "older",
          syncState: mode === "incremental" ? "catching-up" : "syncing"
        }
      }
    }));

    try {
      const raw = await fetchRoomProjection(roomId, {
        ...apiOptions(controller.signal),
        limit: mode === "older" ? 60 : 60,
        ...(mode === "older" && beforeRoomSeq !== undefined ? { beforeRoomSeq } : {}),
        ...(mode === "incremental" && afterRoomSeq !== undefined ? { afterRoomSeq } : {})
      });
      const projection = normalizeRoomProjection(raw, roomId);
      if (get().roomsById[roomId]?.requestGeneration !== generation) return;
      const latestCache = get().roomsById[roomId] ?? emptyCache();
      if (mode === "incremental" && projectionCursorRegressed(latestCache, projection)) {
        set((state) => {
          const cache = state.roomsById[roomId] ?? emptyCache();
          if (cache.requestGeneration !== generation) return {};
          return {
            roomsById: {
              ...state.roomsById,
              [roomId]: { ...cache, eventCursor: 0, syncState: "catching-up" }
            }
          };
        });
        await get().refreshRoom(roomId, "initial");
        return;
      }
      set((state) => {
        const cache = state.roomsById[roomId] ?? emptyCache();
        const merged = mergeRoomProjectionPage(
          cache.projection,
          cache.timelineItems,
          projection,
          mode
        );
        return {
          roomsById: {
            ...state.roomsById,
            [roomId]: {
              ...cache,
              projection: merged.projection,
              timelineItems: merged.timelineItems,
              loading: false,
              loadingOlder: false,
              syncState: "synced",
              consecutiveFailures: 0,
              lastSyncedAt: Date.now(),
              lastAccessedAt: Date.now(),
              eventCursor: mode === "initial"
                ? projection.event_cursor
                : cache.eventCursor,
              error: null
            }
          }
        };
      });
    } catch (error) {
      if (controller.signal.aborted) return;
      const failure = describeError(error);
      set((state) => {
        const cache = state.roomsById[roomId] ?? emptyCache();
        return {
          roomsById: {
            ...state.roomsById,
            [roomId]: {
              ...cache,
              loading: false,
              loadingOlder: false,
              syncState: cache.projection ? "stale" : "offline",
              consecutiveFailures: cache.consecutiveFailures + 1,
              error: failure
            }
          }
        };
      });
    } finally {
      if (requestControllers.get(roomId) === controller) requestControllers.delete(roomId);
    }
  },

  async catchUpRoom(roomId = get().selectedRoomId ?? "") {
    if (!roomId) return;
    abortEventRequest(roomId);
    const controller = new AbortController();
    eventControllers.set(roomId, controller);
    let cursor = get().roomsById[roomId]?.eventCursor ?? 0;
    let changed = false;
    try {
      let hasMore = true;
      while (hasMore) {
        const response = await fetchEvents(roomId, cursor, apiOptions(controller.signal));
        if (response.latest_seq < cursor) {
          if ((get().roomsById[roomId]?.eventCursor ?? 0) !== cursor) return;
          set((state) => {
            const cache = state.roomsById[roomId] ?? emptyCache();
            if (cache.eventCursor !== cursor) return {};
            return {
              roomsById: {
                ...state.roomsById,
                [roomId]: { ...cache, eventCursor: 0, syncState: "catching-up" }
              }
            };
          });
          await get().refreshRoom(roomId, "initial");
          return;
        }
        const events = response.events ?? [];
        const delivered = events[events.length - 1]?.sequence;
        hasMore = response.has_more;
        if (typeof delivered !== "number" || delivered <= cursor) break;
        cursor = delivered;
        changed = true;
        set((state) => {
          const cache = state.roomsById[roomId] ?? emptyCache();
          return {
            roomsById: {
              ...state.roomsById,
              [roomId]: { ...cache, eventCursor: cursor, syncState: "catching-up" }
            }
          };
        });
      }
      if (changed) await get().refreshRoom(roomId, "incremental");
    } catch (error) {
      if (controller.signal.aborted || isCallerAbort(error)) return;
      const failure = describeError(error);
      set((state) => {
        const cache = state.roomsById[roomId] ?? emptyCache();
        return {
          roomsById: {
            ...state.roomsById,
            [roomId]: {
              ...cache,
              syncState: cache.projection ? "stale" : "offline",
              consecutiveFailures: cache.consecutiveFailures + 1,
              error: failure
            }
          }
        };
      });
    } finally {
      if (eventControllers.get(roomId) === controller) eventControllers.delete(roomId);
    }
  },

  async loadOlder(roomId = get().selectedRoomId ?? "") {
    await get().refreshRoom(roomId, "older");
  },

  async sendMessage(content, clientRequestId = `ui_${crypto.randomUUID()}`) {
    const roomId = get().selectedRoomId;
    const cleanContent = content.trim();
    if (!roomId || !cleanContent) return null;
    const pending: PendingRoomMessage = {
      clientRequestId,
      content: cleanContent,
      createdAt: new Date().toISOString(),
      status: "sending",
      error: null
    };
    set((state) => {
      const cache = state.roomsById[roomId] ?? emptyCache();
      return {
        roomsById: {
          ...state.roomsById,
          [roomId]: {
            ...cache,
            pendingMessages: [
              ...cache.pendingMessages.filter((item) => item.clientRequestId !== clientRequestId),
              pending
            ]
          }
        }
      };
    });
    const sendController = new AbortController();
    const sendTimeout = setTimeout(() => {
      sendController.abort(new Error("发送请求超时，请使用同一请求重试。"));
    }, MESSAGE_SEND_TIMEOUT_MS);
    try {
      const receipt = await sendThreadMessage(roomId, cleanContent, {
        ...apiOptions(sendController.signal),
        clientRequestId
      });
      const durableItem = receiptTimelineItem(receipt, cleanContent);
      set((state) => {
        const cache = state.roomsById[roomId] ?? emptyCache();
        const timelineItems = durableItem
          ? mergeRoomTimelineItems(cache.timelineItems, [durableItem])
          : cache.timelineItems;
        return {
          roomsById: {
            ...state.roomsById,
            [roomId]: {
              ...cache,
              timelineItems,
              projection: cache.projection
                ? { ...cache.projection, timeline_items: timelineItems }
                : cache.projection,
              pendingMessages: cache.pendingMessages.filter(
                (item) => item.clientRequestId !== clientRequestId
              )
            }
          }
        };
      });
      await get().refreshRoom(roomId, "incremental");
      return clientRequestId;
    } catch (error) {
      const failure = describeError(error);
      set((state) => {
        const cache = state.roomsById[roomId] ?? emptyCache();
        return {
          roomsById: {
            ...state.roomsById,
            [roomId]: {
              ...cache,
              pendingMessages: cache.pendingMessages.map((item) =>
                item.clientRequestId === clientRequestId
                  ? { ...item, status: "failed", error: failure }
                  : item
              )
            }
          }
        };
      });
      return null;
    } finally {
      clearTimeout(sendTimeout);
    }
  },

  async retryMessage(clientRequestId) {
    const roomId = get().selectedRoomId;
    if (!roomId) return;
    const pending = get().roomsById[roomId]?.pendingMessages.find(
      (item) => item.clientRequestId === clientRequestId
    );
    if (!pending || pending.status !== "failed") return;
    await get().sendMessage(pending.content, clientRequestId);
  },

  async controlObservation(observationId, action, descriptor) {
    const roomId = get().selectedRoomId;
    if (!roomId || !observationId || !descriptor.available) return false;
    set((state) => {
      const cache = state.roomsById[roomId] ?? emptyCache();
      return {
        roomsById: {
          ...state.roomsById,
          [roomId]: {
            ...cache,
            controlPending: { observationId, action },
            controlError: null
          }
        }
      };
    });
    try {
      const result = await submitRoomObservationControl(observationId, action, descriptor, apiOptions());
      set((state) => {
        const cache = state.roomsById[roomId] ?? emptyCache();
        return {
          roomsById: {
            ...state.roomsById,
            [roomId]: {
              ...cache,
              eventCursor: typeof result.event_cursor === "number"
                ? Math.max(cache.eventCursor, result.event_cursor)
                : cache.eventCursor,
              controlPending: null,
              controlError: null
            }
          }
        };
      });
      await get().refreshRoom(roomId, "incremental");
      return true;
    } catch (error) {
      const failure = describeError(error);
      set((state) => {
        const cache = state.roomsById[roomId] ?? emptyCache();
        return {
          roomsById: {
            ...state.roomsById,
            [roomId]: {
              ...cache,
              controlPending: null,
              controlError: failure
            }
          }
        };
      });
      if (failure.status === 409) await get().refreshRoom(roomId, "incremental");
      return false;
    }
  },

  async refreshOperations() {
    if (operationsRequest) return operationsRequest;
    const controller = new AbortController();
    operationsController = controller;
    const generation = get().operationsGeneration + 1;
    set({ operationsGeneration: generation, operationsLoading: true });
    let request!: Promise<void>;
    request = (async () => {
      try {
        const projection = normalizeRoomOperationsProjection(
          await fetchRoomOperations(apiOptions(controller.signal))
        );
        if (get().operationsGeneration !== generation) return;
        const rebuild = projection.actions.rebuild_memory_index;
        const localIncidentId = get().memoryRebuildIncidentId;
        const effectiveRebuildPending = memoryRebuildWriteInFlight || rebuild.pending;
        if (localIncidentId && !effectiveRebuildPending) {
          clearMemoryRebuildClientAction(localIncidentId);
        }
        set({
          operations: projection,
          operationsLoading: false,
          operationsError: null,
          operationsConsecutiveFailures: 0,
          memoryRebuildPending: effectiveRebuildPending,
          memoryRebuildIncidentId: effectiveRebuildPending
            ? rebuild.expected_incident_id ?? localIncidentId
            : null,
          ...(rebuild.status === "applied" ? { memoryRebuildError: null } : {})
        });
      } catch (error) {
        if (controller.signal.aborted || get().operationsGeneration !== generation) return;
        set((state) => ({
          operationsLoading: false,
          operationsError: describeError(error),
          operationsConsecutiveFailures: state.operationsConsecutiveFailures + 1
        }));
      } finally {
        if (operationsController === controller) operationsController = null;
        if (operationsRequest === request) operationsRequest = null;
      }
    })();
    operationsRequest = request;
    return request;
  },

  async refreshExecutions(roomId = get().selectedRoomId ?? "", candidateId) {
    if (!roomId) return;
    const inFlight = executionRequests.get(roomId);
    if (inFlight) return inFlight;
    const current = get().executionsByRoom[roomId] ?? emptyExecutionCache();
    const generation = current.requestGeneration + 1;
    const controller = new AbortController();
    executionControllers.set(roomId, controller);
    set((state) => ({
      executionsByRoom: {
        ...state.executionsByRoom,
        [roomId]: {
          ...(state.executionsByRoom[roomId] ?? emptyExecutionCache()),
          loading: true,
          detailLoading: Boolean(candidateId ?? current.selectedCandidateId),
          requestGeneration: generation
        }
      }
    }));
    let request!: Promise<void>;
    request = (async () => {
      try {
        const list = await fetchRoomExecutions(roomId, apiOptions(controller.signal));
        const selectedCandidateId = candidateId
          ?? get().executionsByRoom[roomId]?.selectedCandidateId
          ?? list.candidates[0]?.candidate_id
          ?? null;
        const detail = selectedCandidateId
          ? await fetchRoomExecutionCandidate(
              selectedCandidateId,
              apiOptions(controller.signal)
            )
          : null;
        if (
          controller.signal.aborted ||
          get().executionsByRoom[roomId]?.requestGeneration !== generation
        ) return;
        set((state) => {
          const cache = state.executionsByRoom[roomId] ?? emptyExecutionCache();
          return {
            executionsByRoom: {
              ...state.executionsByRoom,
              [roomId]: {
                ...cache,
                list,
                details: detail
                  ? { ...cache.details, [detail.candidate.candidate_id]: detail }
                  : cache.details,
                selectedCandidateId,
                loading: false,
                detailLoading: false,
                consecutiveFailures: 0,
                lastSyncedAt: Date.now(),
                error: null
              }
            }
          };
        });
      } catch (error) {
        if (controller.signal.aborted) return;
        set((state) => {
          const cache = state.executionsByRoom[roomId] ?? emptyExecutionCache();
          if (cache.requestGeneration !== generation) return {};
          return {
            executionsByRoom: {
              ...state.executionsByRoom,
              [roomId]: {
                ...cache,
                loading: false,
                detailLoading: false,
                consecutiveFailures: cache.consecutiveFailures + 1,
                error: describeError(error)
              }
            }
          };
        });
      } finally {
        if (executionControllers.get(roomId) === controller) {
          executionControllers.delete(roomId);
        }
        if (executionRequests.get(roomId) === request) executionRequests.delete(roomId);
      }
    })();
    executionRequests.set(roomId, request);
    return request;
  },

  async refreshMemory(roomId = get().selectedRoomId ?? "") {
    if (!roomId) return;
    const inFlight = memoryRequests.get(roomId);
    if (inFlight) return inFlight;
    const current = get().memoryByRoom[roomId] ?? emptyMemoryCache();
    const generation = current.requestGeneration + 1;
    const controller = new AbortController();
    memoryControllers.set(roomId, controller);
    set((state) => ({
      memoryByRoom: {
        ...state.memoryByRoom,
        [roomId]: {
          ...(state.memoryByRoom[roomId] ?? emptyMemoryCache()),
          loading: true,
          requestGeneration: generation
        }
      }
    }));
    let request!: Promise<void>;
    request = (async () => {
      try {
        const projection = normalizeRoomMemoryProjection(
          await fetchRoomMemory(roomId, apiOptions(controller.signal))
        );
        if (
          controller.signal.aborted ||
          get().memoryByRoom[roomId]?.requestGeneration !== generation
        ) return;
        set((state) => {
          const cache = state.memoryByRoom[roomId] ?? emptyMemoryCache();
          if (cache.requestGeneration !== generation) return {};
          return {
            memoryByRoom: {
              ...state.memoryByRoom,
              [roomId]: {
                ...cache,
                projection,
                loading: false,
                consecutiveFailures: 0,
                lastSyncedAt: Date.now(),
                error: null
              }
            }
          };
        });
      } catch (error) {
        if (controller.signal.aborted) return;
        set((state) => {
          const cache = state.memoryByRoom[roomId] ?? emptyMemoryCache();
          if (cache.requestGeneration !== generation) return {};
          return {
            memoryByRoom: {
              ...state.memoryByRoom,
              [roomId]: {
                ...cache,
                loading: false,
                consecutiveFailures: cache.consecutiveFailures + 1,
                error: describeError(error)
              }
            }
          };
        });
      } finally {
        if (memoryControllers.get(roomId) === controller) memoryControllers.delete(roomId);
        if (memoryRequests.get(roomId) === request) memoryRequests.delete(roomId);
      }
    })();
    memoryRequests.set(roomId, request);
    return request;
  },

  async refreshCodexAgents(roomId = get().selectedRoomId ?? "") {
    if (!roomId) return;
    const inFlight = codexRequests.get(roomId);
    if (inFlight) return inFlight;
    const current = get().codexByRoom[roomId] ?? emptyCodexCache();
    const generation = current.requestGeneration + 1;
    const controller = new AbortController();
    codexControllers.set(roomId, controller);
    set((state) => ({
      codexByRoom: {
        ...state.codexByRoom,
        [roomId]: {
          ...(state.codexByRoom[roomId] ?? emptyCodexCache()),
          loading: true,
          requestGeneration: generation
        }
      }
    }));
    let request!: Promise<void>;
    request = (async () => {
      try {
        const projection = await fetchRoomCodexAgents(
          roomId,
          apiOptions(controller.signal)
        );
        if (controller.signal.aborted || get().codexByRoom[roomId]?.requestGeneration !== generation) {
          return;
        }
        set((state) => {
          const cache = state.codexByRoom[roomId] ?? emptyCodexCache();
          if (cache.requestGeneration !== generation) return {};
          const participantIds = projection.participants.map(
            (item) => item.participant.participant_id
          );
          const selectedParticipantId = cache.selectedParticipantId
            && participantIds.includes(cache.selectedParticipantId)
            ? cache.selectedParticipantId
            : participantIds[0] ?? null;
          return {
            codexByRoom: {
              ...state.codexByRoom,
              [roomId]: {
                ...cache,
                projection,
                selectedParticipantId,
                loading: false,
                consecutiveFailures: 0,
                lastSyncedAt: Date.now(),
                error: null
              }
            }
          };
        });
      } catch (error) {
        if (controller.signal.aborted || isCallerAbort(error)) return;
        set((state) => {
          const cache = state.codexByRoom[roomId] ?? emptyCodexCache();
          if (cache.requestGeneration !== generation) return {};
          return {
            codexByRoom: {
              ...state.codexByRoom,
              [roomId]: {
                ...cache,
                loading: false,
                consecutiveFailures: cache.consecutiveFailures + 1,
                error: describeError(error)
              }
            }
          };
        });
      } finally {
        if (codexControllers.get(roomId) === controller) codexControllers.delete(roomId);
        if (codexRequests.get(roomId) === request) codexRequests.delete(roomId);
      }
    })();
    codexRequests.set(roomId, request);
    return request;
  },

  selectCodexParticipant(participantId, roomId = get().selectedRoomId ?? "") {
    if (!roomId) return;
    set((state) => {
      const cache = state.codexByRoom[roomId] ?? emptyCodexCache();
      return {
        codexByRoom: {
          ...state.codexByRoom,
          [roomId]: { ...cache, selectedParticipantId: participantId }
        }
      };
    });
  },

  async submitCodexAction(
    participantId,
    capabilityId,
    requestBody,
    descriptor,
    confirmedPendingObservations = false
  ) {
    const roomId = get().selectedRoomId;
    if (!roomId || !descriptor.available) return null;
    const cache = get().codexByRoom[roomId] ?? emptyCodexCache();
    if (cache.actionPending[participantId]) return null;
    const fingerprint = [
      participantId,
      capabilityId,
      descriptor.expected_session_guard,
      descriptor.expected_goal_guard ?? "",
      descriptor.expected_settings_guard ?? "",
      descriptor.expected_turn_guard ?? "",
      JSON.stringify(requestBody)
    ].join(":");
    const clientActionId = codexActionClientId(fingerprint);
    set((state) => {
      const latest = state.codexByRoom[roomId] ?? emptyCodexCache();
      return {
        codexByRoom: {
          ...state.codexByRoom,
          [roomId]: {
            ...latest,
            actionPending: {
              ...latest.actionPending,
              [participantId]: { capabilityId, clientActionId }
            },
            actionErrors: { ...latest.actionErrors, [participantId]: null }
          }
        }
      };
    });
    try {
      const result = await submitRoomCodexAction(
        participantId,
        capabilityId,
        requestBody,
        descriptor,
        {
          ...apiOptions(),
          clientActionId,
          confirmedPendingObservations
        }
      );
      clearCodexActionClientId(fingerprint);
      set((state) => {
        const latest = state.codexByRoom[roomId] ?? emptyCodexCache();
        const actionPending = { ...latest.actionPending };
        delete actionPending[participantId];
        return {
          codexByRoom: {
            ...state.codexByRoom,
            [roomId]: { ...latest, actionPending, actionErrors: { ...latest.actionErrors, [participantId]: null } }
          }
        };
      });
      abortCodexRequest(roomId);
      await get().refreshCodexAgents(roomId);
      return result;
    } catch (error) {
      const failure = describeError(error);
      if (![0, 502, 503, 504].includes(failure.status)) clearCodexActionClientId(fingerprint);
      set((state) => {
        const latest = state.codexByRoom[roomId] ?? emptyCodexCache();
        const actionPending = { ...latest.actionPending };
        delete actionPending[participantId];
        return {
          codexByRoom: {
            ...state.codexByRoom,
            [roomId]: {
              ...latest,
              actionPending,
              actionErrors: { ...latest.actionErrors, [participantId]: failure }
            }
          }
        };
      });
      if (failure.status === 409 || failure.status === 503) {
        abortCodexRequest(roomId);
        await get().refreshCodexAgents(roomId);
      }
      return null;
    }
  },

  getCodexConsolePreference(participantId) {
    return readCodexConsolePreference(browserStorage("session"), participantId);
  },

  setCodexConsolePreference(participantId, mode) {
    persistCodexConsolePreference(browserStorage("session"), participantId, mode);
    set((state) => ({ codexPreferenceRevision: state.codexPreferenceRevision + 1 }));
  },

  async resolveMemoryCandidate(candidateId, decision, descriptor) {
    const roomId = get().selectedRoomId;
    if (!roomId || get().memoryActionPending || !descriptor.available) return false;
    const fingerprint = [
      "resolve",
      candidateId,
      decision,
      descriptor.expected_digest,
      descriptor.expected_revision
    ].join(":");
    const clientActionId = memoryClientActionId(fingerprint);
    set({
      memoryActionPending: { candidateId, decision },
      memoryActionError: null
    });
    try {
      await resolveRoomMemoryCandidate(candidateId, decision, descriptor, {
        ...apiOptions(),
        clientActionId
      });
      clearMemoryClientAction(fingerprint);
      set({ memoryActionPending: null, memoryActionError: null });
      abortMemoryRequest(roomId);
      await get().refreshMemory(roomId);
      return true;
    } catch (error) {
      const failure = describeError(error);
      if (![0, 502, 504].includes(failure.status)) clearMemoryClientAction(fingerprint);
      set({ memoryActionPending: null, memoryActionError: failure });
      if (failure.status === 409 || failure.status === 404) {
        abortMemoryRequest(roomId);
        await get().refreshMemory(roomId);
      }
      return false;
    }
  },

  async rebuildMemoryIndex(descriptor) {
    const incidentId = descriptor.expected_incident_id;
    if (
      get().memoryRebuildPending ||
      descriptor.pending ||
      !descriptor.available ||
      !incidentId
    ) return false;
    const clientActionId = memoryRebuildClientActionId(incidentId);
    memoryRebuildWriteInFlight = true;
    abortOperationsRequest();
    set({
      memoryRebuildPending: true,
      memoryRebuildIncidentId: incidentId,
      memoryRebuildError: null
    });
    try {
      const result = await rebuildRoomMemoryIndex(descriptor, {
        ...apiOptions(),
        clientActionId
      });
      memoryRebuildWriteInFlight = false;
      abortOperationsRequest();
      const terminal = result.status !== "requested";
      if (terminal) clearMemoryRebuildClientAction(incidentId);
      set({
        memoryRebuildPending: !terminal,
        memoryRebuildIncidentId: terminal ? null : incidentId,
        memoryRebuildError: result.status === "rejected" || result.status === "failed"
          ? {
              code: result.reason_code ?? `room_memory_rebuild_${result.status}`,
              message: "MemoryOS derived-index rebuild did not complete",
              retryable: false,
              status: result.status === "rejected" ? 409 : 500
            }
          : null
      });
      const roomId = get().selectedRoomId;
      if (roomId) abortMemoryRequest(roomId);
      await Promise.all([
        get().refreshOperations(),
        roomId ? get().refreshMemory(roomId) : Promise.resolve()
      ]);
      return result.status === "requested" || result.status === "applied";
    } catch (error) {
      memoryRebuildWriteInFlight = false;
      abortOperationsRequest();
      const failure = describeError(error);
      if (![0, 502, 504].includes(failure.status)) {
        clearMemoryRebuildClientAction(incidentId);
      }
      set({
        memoryRebuildPending: false,
        memoryRebuildIncidentId: null,
        memoryRebuildError: failure
      });
      if (failure.status === 409) {
        const roomId = get().selectedRoomId;
        if (roomId) abortMemoryRequest(roomId);
        await Promise.all([
          get().refreshOperations(),
          roomId ? get().refreshMemory(roomId) : Promise.resolve()
        ]);
      }
      return false;
    }
  },

  async selectExecutionCandidate(candidateId) {
    const roomId = get().selectedRoomId;
    if (!roomId) return;
    set((state) => {
      const cache = state.executionsByRoom[roomId] ?? emptyExecutionCache();
      return {
        executionsByRoom: {
          ...state.executionsByRoom,
          [roomId]: { ...cache, selectedCandidateId: candidateId }
        }
      };
    });
    if (candidateId) await get().refreshExecutions(roomId, candidateId);
  },

  async updateExecutionPolicy(mode, descriptor) {
    const roomId = get().selectedRoomId;
    if (!roomId || get().executionActionPending || !descriptor.available) return false;
    const fingerprint = `policy:${roomId}:${mode}:${descriptor.expected_revision}`;
    const clientActionId = executionClientActionId(fingerprint);
    set({
      executionActionPending: { kind: "policy", targetId: roomId },
      executionActionError: null
    });
    try {
      await updateRoomExecutionPolicy(roomId, mode, descriptor, {
        ...apiOptions(),
        clientActionId
      });
      clearExecutionClientAction(fingerprint);
      set({ executionActionPending: null, executionActionError: null });
      await get().refreshExecutions(roomId);
      return true;
    } catch (error) {
      const failure = describeError(error);
      if (!retainExecutionActionId(failure)) clearExecutionClientAction(fingerprint);
      set({ executionActionPending: null, executionActionError: failure });
      if (failure.status === 409) await get().refreshExecutions(roomId);
      return false;
    }
  },

  async decideExecutionCandidate(candidateId, decision, descriptor) {
    const roomId = get().selectedRoomId;
    if (!roomId || get().executionActionPending || !descriptor.available) return false;
    const fingerprint = [
      "decision",
      candidateId,
      decision,
      descriptor.expected_candidate_digest,
      descriptor.expected_candidate_revision,
      descriptor.expected_policy_revision
    ].join(":");
    const clientActionId = executionClientActionId(fingerprint);
    set({
      executionActionPending: { kind: decision, targetId: candidateId },
      executionActionError: null
    });
    try {
      await decideRoomExecutionCandidate(candidateId, decision, descriptor, {
        ...apiOptions(),
        clientActionId
      });
      clearExecutionClientAction(fingerprint);
      set({ executionActionPending: null, executionActionError: null });
      await get().refreshExecutions(roomId, candidateId);
      return true;
    } catch (error) {
      const failure = describeError(error);
      if (!retainExecutionActionId(failure)) clearExecutionClientAction(fingerprint);
      set({ executionActionPending: null, executionActionError: failure });
      if (failure.status === 409) await get().refreshExecutions(roomId, candidateId);
      return false;
    }
  },

  async cancelExecutionRun(runId, descriptor) {
    const roomId = get().selectedRoomId;
    if (!roomId || get().executionActionPending || !descriptor.available) return false;
    const fingerprint = `cancel:${runId}:${descriptor.expected_run_state}:${descriptor.expected_run_revision}`;
    const clientActionId = executionClientActionId(fingerprint);
    set({
      executionActionPending: { kind: "cancel", targetId: runId },
      executionActionError: null
    });
    try {
      await cancelRoomExecutionRun(runId, descriptor, {
        ...apiOptions(),
        clientActionId
      });
      clearExecutionClientAction(fingerprint);
      set({ executionActionPending: null, executionActionError: null });
      const candidateId = get().executionsByRoom[roomId]?.selectedCandidateId;
      await get().refreshExecutions(roomId, candidateId);
      return true;
    } catch (error) {
      const failure = describeError(error);
      if (!retainExecutionActionId(failure)) clearExecutionClientAction(fingerprint);
      set({ executionActionPending: null, executionActionError: failure });
      if (failure.status === 409) {
        const candidateId = get().executionsByRoom[roomId]?.selectedCandidateId;
        await get().refreshExecutions(roomId, candidateId);
      }
      return false;
    }
  },

  async recoverRuntime(descriptor) {
    const incidentId = descriptor.expected_incident_id;
    if (get().runtimeRecoverPending || !incidentId) return false;
    const clientActionId = runtimeRecoverClientActionId(incidentId);
    set({ runtimeRecoverPending: true, runtimeRecoverError: null });
    try {
      await recoverRoomRuntime(descriptor, { ...apiOptions(), clientActionId });
      clearRuntimeRecoverClientAction(incidentId);
      set({ runtimeRecoverPending: false, runtimeRecoverError: null });
      const roomId = get().selectedRoomId;
      await Promise.all([
        get().refreshOperations(),
        get().loadRooms(),
        roomId ? get().refreshRoom(roomId, "incremental") : Promise.resolve()
      ]);
      return true;
    } catch (error) {
      const failure = describeError(error);
      if (![0, 502, 504].includes(failure.status)) {
        clearRuntimeRecoverClientAction(incidentId);
      }
      set({ runtimeRecoverPending: false, runtimeRecoverError: failure });
      if (failure.status === 409) {
        const roomId = get().selectedRoomId;
        await Promise.all([
          get().refreshOperations(),
          roomId ? get().refreshRoom(roomId, "incremental") : Promise.resolve()
        ]);
      }
      return false;
    }
  },

  setDraft(roomId, draft) {
    set((state) => ({ drafts: { ...state.drafts, [roomId]: draft } }));
    persistRoomDraft(browserStorage("session"), roomId, draft);
  },

  markRead(roomId, nextSeq) {
    if (nextSeq <= (get().readCursors[roomId] ?? 0)) return;
    set((state) => ({
      readCursors: {
        ...state.readCursors,
        [roomId]: Math.max(state.readCursors[roomId] ?? 0, nextSeq)
      }
    }));
    persistLocalState(get());
  },

  saveScrollAnchor(roomId, anchor) {
    set((state) => {
      const scrollAnchors = { ...state.scrollAnchors };
      if (anchor) scrollAnchors[roomId] = anchor;
      else delete scrollAnchors[roomId];
      return { scrollAnchors };
    });
    persistLocalState(get());
  },

  setTheme(theme) {
    set({ theme });
    persistLocalState(get());
  },

  setSidebarOpen(open) {
    set({ sidebarOpen: open });
    persistLocalState(get());
  },

  setInspectorOpen(open) {
    set({ inspectorOpen: open });
    persistLocalState(get());
    if (open) {
      void get().refreshOperations();
      void get().refreshExecutions();
      void get().refreshMemory();
      void get().refreshCodexAgents();
    }
    get().startOperationsSync();
    get().startExecutionSync();
    get().startMemorySync();
    get().startCodexSync();
  },

  setInspectorTarget(target) {
    set({ inspectorTarget: target, inspectorOpen: target ? true : get().inspectorOpen });
    if (target) {
      persistLocalState(get());
      void get().refreshOperations();
      void get().refreshExecutions();
      void get().refreshMemory();
      void get().refreshCodexAgents();
    }
  },

  clearRoomError(roomId = get().selectedRoomId ?? "") {
    if (!roomId) return;
    set((state) => {
      const cache = state.roomsById[roomId] ?? emptyCache();
      return {
        roomsById: {
          ...state.roomsById,
          [roomId]: { ...cache, error: null }
        }
      };
    });
  },

  clearControlError(roomId = get().selectedRoomId ?? "") {
    if (!roomId) return;
    set((state) => {
      const cache = state.roomsById[roomId] ?? emptyCache();
      return {
        roomsById: {
          ...state.roomsById,
          [roomId]: { ...cache, controlError: null }
        }
      };
    });
  },

  startSync() {
    get().stopSync();
    const epoch = syncCoordinator.restart("room");
    const schedule = () => {
      if (!syncCoordinator.isCurrent("room", epoch)) return;
      const roomId = get().selectedRoomId;
      const cache = roomId ? get().roomsById[roomId] : null;
      const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
      const base = hidden ? 15_000 : cache?.projection?.room_state !== "settled" ? 1_000 : 5_000;
      const failureDelay = Math.min(30_000, base * 2 ** Math.min(cache?.consecutiveFailures ?? 0, 4));
      const jitter = Math.round(failureDelay * 0.12 * Math.random());
      syncCoordinator.schedule("room", epoch, failureDelay + jitter, async () => {
        const currentRoomId = get().selectedRoomId;
        if (currentRoomId) {
          await get().catchUpRoom(currentRoomId);
          if (Date.now() - lastSafeRefreshAt >= SAFE_REFRESH_MS) {
            lastSafeRefreshAt = Date.now();
            await get().refreshRoom(currentRoomId, "incremental");
          }
        }
        if (Date.now() - lastRoomListRefreshAt >= ROOM_LIST_REFRESH_MS) {
          await get().loadRooms();
        }
        schedule();
      });
    };
    schedule();
    get().startOperationsSync();
    get().startExecutionSync();
    get().startMemorySync();
    get().startCodexSync();
  },

  startOperationsSync() {
    const currentOperationsEpoch = syncCoordinator.restart("operations");
    const scheduleOperations = () => {
      if (!syncCoordinator.isCurrent("operations", currentOperationsEpoch)) return;
      const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
      const base = !hidden && get().inspectorOpen ? 5_000 : 15_000;
      const delay = Math.min(
        30_000,
        base * 2 ** Math.min(get().operationsConsecutiveFailures, 2)
      );
      const jitter = Math.round(delay * 0.12 * Math.random());
      syncCoordinator.schedule("operations", currentOperationsEpoch, delay + jitter, async () => {
        await get().refreshOperations();
        scheduleOperations();
      });
    };
    if (!get().operations && !operationsRequest) void get().refreshOperations();
    scheduleOperations();
  },

  startExecutionSync() {
    const currentExecutionEpoch = syncCoordinator.restart("execution");
    const scheduleExecutions = () => {
      if (!syncCoordinator.isCurrent("execution", currentExecutionEpoch)) return;
      const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
      const roomId = get().selectedRoomId;
      const cache = roomId ? get().executionsByRoom[roomId] : null;
      const base = !hidden && get().inspectorOpen ? 5_000 : 15_000;
      const delay = Math.min(
        30_000,
        base * 2 ** Math.min(cache?.consecutiveFailures ?? 0, 2)
      );
      const jitter = Math.round(delay * 0.12 * Math.random());
      syncCoordinator.schedule("execution", currentExecutionEpoch, delay + jitter, async () => {
        const currentRoomId = get().selectedRoomId;
        if (currentRoomId) await get().refreshExecutions(currentRoomId);
        scheduleExecutions();
      });
    };
    const roomId = get().selectedRoomId;
    if (roomId && !get().executionsByRoom[roomId]?.list) {
      void get().refreshExecutions(roomId);
    }
    scheduleExecutions();
  },

  startMemorySync() {
    const currentMemoryEpoch = syncCoordinator.restart("memory");
    const scheduleMemory = () => {
      if (!syncCoordinator.isCurrent("memory", currentMemoryEpoch)) return;
      const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
      const roomId = get().selectedRoomId;
      const cache = roomId ? get().memoryByRoom[roomId] : null;
      const base = !hidden && get().inspectorOpen ? 5_000 : 15_000;
      const delay = Math.min(
        30_000,
        base * 2 ** Math.min(cache?.consecutiveFailures ?? 0, 2)
      );
      const jitter = Math.round(delay * 0.12 * Math.random());
      syncCoordinator.schedule("memory", currentMemoryEpoch, delay + jitter, async () => {
        const currentRoomId = get().selectedRoomId;
        if (currentRoomId) await get().refreshMemory(currentRoomId);
        scheduleMemory();
      });
    };
    const roomId = get().selectedRoomId;
    if (roomId && get().inspectorOpen && !get().memoryByRoom[roomId]?.projection) {
      void get().refreshMemory(roomId);
    }
    scheduleMemory();
  },

  startCodexSync() {
    const currentCodexEpoch = syncCoordinator.restart("codex");
    const scheduleCodex = () => {
      if (!syncCoordinator.isCurrent("codex", currentCodexEpoch)) return;
      const hidden = typeof document !== "undefined" && document.visibilityState === "hidden";
      const roomId = get().selectedRoomId;
      const cache = roomId ? get().codexByRoom[roomId] : null;
      const base = hidden ? 15_000 : 2_000;
      const delay = Math.min(
        30_000,
        base * 2 ** Math.min(cache?.consecutiveFailures ?? 0, 3)
      );
      const jitter = Math.round(delay * 0.12 * Math.random());
      syncCoordinator.schedule("codex", currentCodexEpoch, delay + jitter, async () => {
        const currentRoomId = get().selectedRoomId;
        if (currentRoomId) {
          await get().refreshCodexAgents(currentRoomId);
        }
        scheduleCodex();
      });
    };
    const roomId = get().selectedRoomId;
    if (roomId && !get().codexByRoom[roomId]?.projection) {
      void get().refreshCodexAgents(roomId);
    }
    if (typeof window !== "undefined") {
      if (codexFocusHandler) window.removeEventListener("focus", codexFocusHandler);
      codexFocusHandler = () => {
        const currentRoomId = get().selectedRoomId;
        if (currentRoomId) void get().refreshCodexAgents(currentRoomId);
      };
      window.addEventListener("focus", codexFocusHandler);
    }
    scheduleCodex();
  },

  stopSync() {
    syncCoordinator.teardown();
    operationsController?.abort();
    operationsController = null;
    operationsRequest = null;
    for (const controller of executionControllers.values()) controller.abort();
    executionControllers.clear();
    executionRequests.clear();
    for (const controller of memoryControllers.values()) controller.abort();
    memoryControllers.clear();
    memoryRequests.clear();
    for (const controller of codexControllers.values()) controller.abort();
    codexControllers.clear();
    codexRequests.clear();
    if (typeof window !== "undefined" && codexFocusHandler) {
      window.removeEventListener("focus", codexFocusHandler);
      codexFocusHandler = null;
    }
    set((state) => ({
      operationsLoading: false,
      operationsGeneration: state.operationsGeneration + 1,
      executionsByRoom: Object.fromEntries(
        Object.entries(state.executionsByRoom).map(([roomId, cache]) => [
          roomId,
          {
            ...cache,
            loading: false,
            detailLoading: false,
            requestGeneration: cache.requestGeneration + 1
          }
        ])
      ),
      memoryByRoom: Object.fromEntries(
        Object.entries(state.memoryByRoom).map(([roomId, cache]) => [
          roomId,
          {
            ...cache,
            loading: false,
            requestGeneration: cache.requestGeneration + 1
          }
        ])
      ),
      codexByRoom: Object.fromEntries(
        Object.entries(state.codexByRoom).map(([roomId, cache]) => [
          roomId,
          {
            ...cache,
            loading: false,
            requestGeneration: cache.requestGeneration + 1
          }
        ])
      )
    }));
    for (const controller of requestControllers.values()) controller.abort();
    requestControllers.clear();
    for (const controller of eventControllers.values()) controller.abort();
    eventControllers.clear();
  }
}));
