import { mergeRoomTimeline } from "@/lib/room-view";
import type { RoomChatProjection, RoomTimelineItem } from "@/lib/types";

export const MAX_CACHED_ROOMS = 8;

export type RoomRequestMode = "initial" | "incremental" | "older";

export type CacheRetentionFacts = {
  pendingMessages: readonly unknown[];
  lastAccessedAt: number;
};

export function trimRoomCaches<T extends CacheRetentionFacts>(
  caches: Record<string, T>,
  selectedRoomId: string | null,
  maximum = MAX_CACHED_ROOMS
): Record<string, T> {
  const entries = Object.entries(caches);
  if (entries.length <= maximum) return caches;
  const protectedIds = new Set(
    entries
      .filter(([id, cache]) => id === selectedRoomId || cache.pendingMessages.length > 0)
      .map(([id]) => id)
  );
  const removable = entries
    .filter(([id]) => !protectedIds.has(id))
    .sort(([, left], [, right]) => left.lastAccessedAt - right.lastAccessedAt);
  const result = { ...caches };
  while (Object.keys(result).length > maximum && removable.length) {
    const [id] = removable.shift()!;
    delete result[id];
  }
  return result;
}

export function timelineRoomSeq(
  items: RoomTimelineItem[],
  edge: "first" | "last"
): number | undefined {
  if (!items.length) return undefined;
  return edge === "first" ? items[0].room_seq : items[items.length - 1].room_seq;
}

export function latestCachedRoomSeq(
  projection: RoomChatProjection | null,
  timelineItems: RoomTimelineItem[]
): number {
  return Math.max(
    projection?.latest_visible_room_seq ?? 0,
    ...timelineItems.map((item) => item.room_seq)
  );
}

export function projectionCursorRegressed(
  eventCursor: number,
  projection: RoomChatProjection | null,
  timelineItems: RoomTimelineItem[],
  incoming: RoomChatProjection
): boolean {
  return (
    incoming.event_cursor < eventCursor ||
    (incoming.latest_visible_room_seq ?? 0) < latestCachedRoomSeq(projection, timelineItems)
  );
}

export function roomProjectionCursors(
  mode: RoomRequestMode,
  projection: RoomChatProjection | null,
  timelineItems: RoomTimelineItem[]
): { beforeRoomSeq?: number; afterRoomSeq?: number } {
  if (mode === "older") {
    return {
      beforeRoomSeq: projection?.next_before_room_seq ?? timelineRoomSeq(timelineItems, "first")
    };
  }
  if (mode === "incremental") {
    return {
      afterRoomSeq: projection?.next_after_room_seq ?? timelineRoomSeq(timelineItems, "last") ?? 0
    };
  }
  return {};
}

export function mergeRoomProjectionPage(
  current: RoomChatProjection | null,
  timelineItems: RoomTimelineItem[],
  incoming: RoomChatProjection,
  mode: RoomRequestMode
): { projection: RoomChatProjection; timelineItems: RoomTimelineItem[] } {
  const mergedItems = mode === "initial"
    ? incoming.timeline_items
    : mergeRoomTimeline(timelineItems, incoming.timeline_items);
  return {
    projection: {
      ...incoming,
      timeline_items: mergedItems,
      has_older: mode === "incremental"
        ? current?.has_older ?? incoming.has_older
        : incoming.has_older,
      next_before_room_seq: mode === "incremental"
        ? current?.next_before_room_seq ?? incoming.next_before_room_seq
        : incoming.next_before_room_seq,
      next_after_room_seq: mode === "older"
        ? current?.next_after_room_seq ?? incoming.next_after_room_seq
        : incoming.next_after_room_seq
    },
    timelineItems: mergedItems
  };
}

export function mergeRoomTimelineItems(
  current: RoomTimelineItem[],
  incoming: RoomTimelineItem[]
): RoomTimelineItem[] {
  return mergeRoomTimeline(current, incoming);
}

export function nextRequestGeneration(current: number): number {
  return current + 1;
}

export function isCurrentRequestGeneration(current: number, expected: number): boolean {
  return current === expected;
}
