import { describe, expect, it } from "vitest";

import type { RoomChatProjection, RoomTimelineItem } from "@/lib/types";
import {
  isCurrentRequestGeneration,
  mergeRoomProjectionPage,
  nextRequestGeneration,
  projectionCursorRegressed,
  roomProjectionCursors,
  trimRoomCaches
} from "./room-cache";

function item(roomSeq: number, content = `message-${roomSeq}`): RoomTimelineItem {
  return {
    id: `message-${roomSeq}`,
    message_id: `message-${roomSeq}`,
    room_seq: roomSeq,
    kind: "message",
    actor: { kind: "human", role: "human", display_name: "Human" },
    content
  };
}

function projection(
  items: RoomTimelineItem[],
  overrides: Partial<RoomChatProjection> = {}
): RoomChatProjection {
  return {
    schema_version: "room_chat_projection/v3",
    conversation_id: "conv-1",
    conversation: { id: "conv-1", title: "Room" },
    room_state: "active",
    latest_visible_room_seq: items.at(-1)?.room_seq ?? 0,
    event_cursor: 10,
    has_older: true,
    has_newer: false,
    next_before_room_seq: items[0]?.room_seq,
    next_after_room_seq: items.at(-1)?.room_seq,
    timeline_items: items,
    compatibility_items: [],
    participants: [],
    turns: [],
    active_turn_count: 0,
    excluded_stopped_count: 0,
    ...overrides
  } as RoomChatProjection;
}

describe("room cache reducers", () => {
  it("retains exactly eight rooms while protecting selected and pending rooms", () => {
    const caches = Object.fromEntries(Array.from({ length: 10 }, (_, index) => [
      `room-${index}`,
      {
        lastAccessedAt: index,
        pendingMessages: index === 0 ? [{ id: "pending" }] : []
      }
    ]));

    const trimmed = trimRoomCaches(caches, "room-1");

    expect(Object.keys(trimmed)).toHaveLength(8);
    expect(trimmed).toHaveProperty("room-0");
    expect(trimmed).toHaveProperty("room-1");
    expect(trimmed).not.toHaveProperty("room-2");
    expect(trimmed).not.toHaveProperty("room-3");
  });

  it("preserves pending rooms even when protected entries exceed the nominal limit", () => {
    const caches = Object.fromEntries(Array.from({ length: 9 }, (_, index) => [
      `room-${index}`,
      { lastAccessedAt: index, pendingMessages: [{ id: index }] }
    ]));

    expect(Object.keys(trimRoomCaches(caches, null))).toHaveLength(9);
  });

  it("derives mutually exclusive initial, older, and incremental cursors", () => {
    const current = projection([item(4), item(5)], {
      next_before_room_seq: 4,
      next_after_room_seq: 5
    });
    expect(roomProjectionCursors("initial", current, current.timeline_items)).toEqual({});
    expect(roomProjectionCursors("older", current, current.timeline_items)).toEqual({ beforeRoomSeq: 4 });
    expect(roomProjectionCursors("incremental", current, current.timeline_items)).toEqual({ afterRoomSeq: 5 });
    expect(roomProjectionCursors("incremental", null, [])).toEqual({ afterRoomSeq: 0 });
  });

  it("prepends older pages and preserves the current forward cursor", () => {
    const current = projection([item(3), item(4)], {
      next_before_room_seq: 3,
      next_after_room_seq: 4
    });
    const older = projection([item(1), item(2)], {
      next_before_room_seq: 1,
      next_after_room_seq: 2
    });

    const merged = mergeRoomProjectionPage(current, current.timeline_items, older, "older");

    expect(merged.timelineItems.map((entry) => entry.room_seq)).toEqual([1, 2, 3, 4]);
    expect(merged.projection.next_before_room_seq).toBe(1);
    expect(merged.projection.next_after_room_seq).toBe(4);
  });

  it("appends incremental pages without losing the historical pagination cursor", () => {
    const current = projection([item(1), item(2)], {
      next_before_room_seq: 1,
      next_after_room_seq: 2,
      has_older: true
    });
    const incremental = projection([item(2, "deduplicated"), item(3)], {
      next_before_room_seq: 2,
      next_after_room_seq: 3,
      has_older: false
    });

    const merged = mergeRoomProjectionPage(current, current.timeline_items, incremental, "incremental");

    expect(merged.timelineItems.map((entry) => entry.room_seq)).toEqual([1, 2, 3]);
    expect(merged.projection.next_before_room_seq).toBe(1);
    expect(merged.projection.next_after_room_seq).toBe(3);
    expect(merged.projection.has_older).toBe(true);
  });

  it("detects event or durable Room cursor regression", () => {
    const current = projection([item(8)], { event_cursor: 20, latest_visible_room_seq: 8 });
    expect(projectionCursorRegressed(20, current, current.timeline_items, projection([item(9)], { event_cursor: 19 }))).toBe(true);
    expect(projectionCursorRegressed(20, current, current.timeline_items, projection([item(7)], { event_cursor: 21 }))).toBe(true);
    expect(projectionCursorRegressed(20, current, current.timeline_items, projection([item(9)], { event_cursor: 21 }))).toBe(false);
  });

  it("provides an explicit request-generation fence", () => {
    const generation = nextRequestGeneration(7);
    expect(generation).toBe(8);
    expect(isCurrentRequestGeneration(8, generation)).toBe(true);
    expect(isCurrentRequestGeneration(9, generation)).toBe(false);
  });
});
