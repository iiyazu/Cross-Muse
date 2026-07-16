import type {
  RoomAgentStream,
  RoomChatProjection,
  RoomControlActionDescriptor,
  RoomMessageReceipt,
  RoomSummary,
  RoomTimelineItem,
  XmuseApiErrorShape
} from "@/lib/types";

import type { DomainCapability, DomainSelector } from "./shared";

export type RoomSyncState =
  | "idle"
  | "syncing"
  | "synced"
  | "catching-up"
  | "stale"
  | "offline";

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
  agentStreams: RoomAgentStream[];
  agentStreamAvailable: boolean;
  agentStreamEpoch: string | null;
  agentStreamSeq: number;
  agentStreamGeneration: number;
};

export type RoomDomainState = {
  rooms: RoomSummary[];
  roomsById: Record<string, RoomCache>;
  selectedRoomId: string | null;
  roomsLoading: boolean;
  roomsLoaded: boolean;
  roomsError: XmuseApiErrorShape | null;
  roomCreatePending: boolean;
  roomCreateError: XmuseApiErrorShape | null;
};

export type RoomDomainActions = {
  bootstrap: (requestedRoomId?: string | null) => Promise<string | null>;
  loadRooms: () => Promise<RoomSummary[]>;
  createRoom: (
    title: string,
    clientRequestId?: string,
    rosterTemplateId?: string
  ) => Promise<string | null>;
  selectRoom: (roomId: string) => Promise<void>;
  refreshRoom: (
    roomId?: string,
    mode?: "initial" | "incremental" | "older"
  ) => Promise<void>;
  catchUpRoom: (roomId?: string) => Promise<void>;
  loadOlder: (roomId?: string) => Promise<void>;
  sendMessage: (content: string, clientRequestId?: string) => Promise<string | null>;
  retryMessage: (clientRequestId: string) => Promise<void>;
  controlObservation: (
    observationId: string,
    action: "cancel" | "retry",
    descriptor: RoomControlActionDescriptor
  ) => Promise<boolean>;
  clearRoomError: (roomId?: string) => void;
  clearControlError: (roomId?: string) => void;
  startAgentStream: () => void;
};

export type RoomDomain = RoomDomainState & RoomDomainActions;
export type RoomReadCapability = DomainCapability<
  RoomDomain,
  | "rooms"
  | "roomsById"
  | "selectedRoomId"
  | "roomsLoading"
  | "roomsLoaded"
  | "roomsError"
  | "roomCreatePending"
  | "roomCreateError"
>;
export type RoomWriteCapability = DomainCapability<
  RoomDomain,
  | "createRoom"
  | "selectRoom"
  | "loadOlder"
  | "sendMessage"
  | "retryMessage"
  | "controlObservation"
  | "clearRoomError"
  | "clearControlError"
>;

export const selectRooms: DomainSelector<RoomDomainState, RoomSummary[]> = (state) => state.rooms;
export const selectSelectedRoomId: DomainSelector<RoomDomainState, string | null> =
  (state) => state.selectedRoomId;

export function createRoomCacheSelector(
  roomId: string
): DomainSelector<RoomDomainState, RoomCache | null> {
  return (state) => state.roomsById[roomId] ?? null;
}

// Keeps the receipt type close to the send boundary without making a domain own API calls.
export type RoomSendReceipt = RoomMessageReceipt;
