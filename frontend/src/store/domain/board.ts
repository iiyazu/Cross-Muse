import type { BoardReviewDetail } from "@/lib/board-review-types";
import type { XmuseApiErrorShape } from "@/lib/types";
import type {
  BoardContractDetail,
  BoardSplit,
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
  reviewDetails: Record<string, BoardReviewDetail>;
  reviewDetailErrors: Record<string, XmuseApiErrorShape>;
};

export type BoardDomainState = {
  boardByRoom: Record<string, RoomBoardCache>;
  boardActionPending: { kind: "approve" | "reject"; splitId: string } | null;
  boardActionError: XmuseApiErrorShape | null;
};

export type BoardDomainActions = {
  refreshBoard: (roomId?: string) => Promise<void>;
  loadBoardContract: (contractId: string, version?: number, roomId?: string) => Promise<void>;
  loadBoardReview: (reviewId: string, roomId?: string) => Promise<void>;
  decideBoardSplit: (split: BoardSplit, decision: "approve" | "reject", roomId?: string) => Promise<boolean>;
  submitBoardReviewDecision: (
    args: { reviewId: string; verdict: "endorse" | "object"; summary: string; findings: Array<{ severity: string; path: string | null; text: string }>; expectedDigest: string },
    roomId?: string
  ) => Promise<boolean>;
  startBoardSync: () => void;
};

export type BoardDomain = BoardDomainState & BoardDomainActions;
export type BoardReadCapability = DomainCapability<
  BoardDomain,
  "boardByRoom" | "boardActionPending" | "boardActionError"
>;
export type BoardWriteCapability = DomainCapability<
  BoardDomain,
  "refreshBoard" | "loadBoardContract" | "loadBoardReview" | "decideBoardSplit" | "submitBoardReviewDecision"
>;

export function createBoardCacheSelector(
  roomId: string
): DomainSelector<BoardDomainState, RoomBoardCache | null> {
  return (state) => state.boardByRoom[roomId] ?? null;
}
