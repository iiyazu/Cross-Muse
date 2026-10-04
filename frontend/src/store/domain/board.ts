import type { XmuseApiErrorShape } from "@/lib/types";
import type {
  BoardContractDetail,
  RoomBoardProjection,
  RoomBoardSummary
} from "@/lib/board-types";

import type { DomainCapability, DomainSelector } from "./shared";

export type RoomBoardCache = {
  projection: RoomBoardProjection | null;
  summary: RoomBoardSummary | null;
  loading: boolean;
  requestGeneration: number;
  consecutiveFailures: number;
  lastSyncedAt: number;
  error: XmuseApiErrorShape | null;
  contractDetails: Record<string, BoardContractDetail>;
};

export type BoardDomainState = {
  boardByRoom: Record<string, RoomBoardCache>;
};

export type BoardDomainActions = {
  refreshBoard: (roomId?: string) => Promise<void>;
  loadBoardContract: (contractId: string, version?: number, roomId?: string) => Promise<void>;
  startBoardSync: () => void;
};

export type BoardDomain = BoardDomainState & BoardDomainActions;
export type BoardReadCapability = DomainCapability<BoardDomain, "boardByRoom">;
export type BoardWriteCapability = DomainCapability<
  BoardDomain,
  "refreshBoard" | "loadBoardContract"
>;

export function createBoardCacheSelector(
  roomId: string
): DomainSelector<BoardDomainState, RoomBoardCache | null> {
  return (state) => state.boardByRoom[roomId] ?? null;
}
