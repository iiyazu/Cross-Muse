"use client";

import { useMemo } from "react";

import { familyOf, type Family } from "@/components/ui/avatar";
import type { BoardParticipant, RoomBoardProjection } from "@/lib/board-types";

export type BoardPeople = {
  name: (participantId: string | null | undefined) => string;
  family: (participantId: string | null | undefined) => Family;
  get: (participantId: string | null | undefined) => BoardParticipant | null;
};

/** Participant lookups for board rows: ids never show; unknown ids read as "未知成员". */
export function useBoardPeople(projection: RoomBoardProjection | null): BoardPeople {
  const participants = projection?.participants;
  return useMemo(() => {
    const byId = new Map((participants ?? []).map((participant) => [participant.participant_id, participant]));
    return {
      name: (participantId) => (participantId ? byId.get(participantId)?.display_name : null) ?? "未知成员",
      family: (participantId) => familyOf(participantId ? byId.get(participantId)?.provider_kind : null),
      get: (participantId) => (participantId ? byId.get(participantId) ?? null : null)
    };
  }, [participants]);
}

export type PanelView =
  | { kind: "board" }
  | { kind: "module"; moduleId: string }
  | { kind: "integration"; integrationId: string }
  | { kind: "contract"; contractId: string; version?: number }
  | { kind: "split"; splitId: string }
  | { kind: "execution"; candidateId: string };
