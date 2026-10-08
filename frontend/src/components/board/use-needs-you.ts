"use client";

import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import type { BoardAttentionItem } from "@/lib/board-types";
import type { RoomExecutionCandidateSummary, RoomMemoryCandidate, RoomOperationsIncident } from "@/lib/types";
import { useRoomStore } from "@/store/room-store";

/** Mirrors the backend's actionable rule (room_execution_projection: state "open", no live run). */
const TERMINAL_RUN_STATES = new Set(["succeeded", "failed", "blocked", "cancelled"]);

export function executionAwaitsDecision(candidate: RoomExecutionCandidateSummary): boolean {
  return candidate.state === "open" && (!candidate.run || TERMINAL_RUN_STATES.has(candidate.run.state));
}

export function memoryAwaitsDecision(candidate: RoomMemoryCandidate): boolean {
  return candidate.approval_state === "pending" && candidate.actions.resolve.available;
}

/** Runtime incidents the human can act on from here (recovery or index rebuild). */
export function incidentNeedsOperator(incident: RoomOperationsIncident): boolean {
  return incident.next_action === "recover_runtime"
    || incident.next_action === "rebuild_memory_index"
    || incident.next_action === "repair_then_recover";
}

export type NeedsYou = {
  /** Board items whose `kind` is `operator`: the only board items the human must act on. */
  board: BoardAttentionItem[];
  executions: RoomExecutionCandidateSummary[];
  memories: RoomMemoryCandidate[];
  incidents: RoomOperationsIncident[];
  total: number;
};

const NONE: never[] = [];

/** Everything in the selected room that waits for the human (design §2.4). */
export function useNeedsYou(roomId: string | null): NeedsYou {
  const { attention, candidates, memories, incidents } = useRoomStore(useShallow((state) => {
    const board = roomId ? state.boardByRoom[roomId] : undefined;
    return {
      attention: board?.projection?.attention ?? board?.summary?.attention ?? NONE,
      candidates: (roomId ? state.executionsByRoom[roomId]?.list?.candidates : undefined) ?? NONE,
      memories: (roomId ? state.memoryByRoom[roomId]?.projection?.pending_candidates : undefined) ?? NONE,
      incidents: state.operations?.incidents ?? NONE
    };
  }));
  return useMemo(() => {
    const board = attention.filter((item) => item.kind === "operator");
    const executions = candidates.filter(executionAwaitsDecision);
    const pendingMemories = memories.filter(memoryAwaitsDecision);
    const roomIncidents = incidents.filter((incident) =>
      incidentNeedsOperator(incident) && (!incident.conversation_id || incident.conversation_id === roomId)
    );
    return {
      board,
      executions,
      memories: pendingMemories,
      incidents: roomIncidents,
      total: board.length + executions.length + pendingMemories.length + roomIncidents.length
    };
  }, [attention, candidates, memories, incidents, roomId]);
}
