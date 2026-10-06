"use client";

import { useMemo } from "react";

import type { BoardAttentionItem } from "@/lib/board-types";
import { useRoomStore } from "@/store/room-store";

const NO_ITEMS: BoardAttentionItem[] = [];

export type NeedsYou = {
  /** Board items whose `kind` is `operator`: the only ones the human must act on. */
  board: BoardAttentionItem[];
  total: number;
};

/** Everything in the selected room that waits for the human (design §2.4). */
export function useNeedsYou(roomId: string | null): NeedsYou {
  const attention = useRoomStore((state) => {
    if (!roomId) return NO_ITEMS;
    const cache = state.boardByRoom[roomId];
    return cache?.projection?.attention ?? cache?.summary?.attention ?? NO_ITEMS;
  });
  return useMemo(() => {
    const board = attention.filter((item) => item.kind === "operator");
    return { board, total: board.length };
  }, [attention]);
}
