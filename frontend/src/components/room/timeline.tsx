"use client";

import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { ArrowDown } from "lucide-react";

import { familyOf } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import type { RoomAgentStream, RoomTimelineItem } from "@/lib/types";
import type { PendingRoomMessage } from "@/store/domain";
import { useRoomStore } from "@/store/room-store";

import { AgentPreview } from "./agent-preview";
import { dayKey, formatDay, isHumanActor } from "./format";
import { PendingItem, TimelineItem, type ParticipantLookup } from "./timeline-item";

const EMPTY_STREAMS: RoomAgentStream[] = [];
const EMPTY_ITEMS: RoomTimelineItem[] = [];
const EMPTY_PENDING: PendingRoomMessage[] = [];
const BOTTOM_SLACK_PX = 120;
const GROUP_WINDOW_MS = 5 * 60_000;

function atBottom(container: HTMLElement): boolean {
  return container.scrollHeight - container.scrollTop - container.clientHeight <= BOTTOM_SLACK_PX;
}

function snapToBottom(container: HTMLElement) {
  container.scrollTop = container.scrollHeight;
}

function messageNodes(container: HTMLElement): HTMLElement[] {
  return [...container.querySelectorAll<HTMLElement>("[data-message-id]")];
}

function captureAnchor(container: HTMLElement): { messageId: string; offset: number } | null {
  const top = container.getBoundingClientRect().top;
  const node = messageNodes(container).find((candidate) => candidate.getBoundingClientRect().bottom >= top);
  if (!node?.dataset.messageId) return null;
  return { messageId: node.dataset.messageId, offset: node.getBoundingClientRect().top - top };
}

function restoreAnchor(container: HTMLElement, anchor: { messageId: string; offset: number } | null) {
  if (!anchor) return;
  const node = messageNodes(container).find((candidate) => candidate.dataset.messageId === anchor.messageId);
  if (node) container.scrollTop = node.offsetTop - anchor.offset;
}

/** Whether a row continues the previous author's run (header hidden). */
export function continuesRun(previous: RoomTimelineItem | undefined, item: RoomTimelineItem): boolean {
  if (!previous || previous.kind !== "message" || item.kind !== "message") return false;
  const sameAuthor = isHumanActor(previous.actor) && isHumanActor(item.actor)
    ? true
    : Boolean(item.actor.participant_id) && previous.actor.participant_id === item.actor.participant_id;
  if (!sameAuthor) return false;
  const gap = new Date(item.created_at ?? 0).getTime() - new Date(previous.created_at ?? 0).getTime();
  return Number.isFinite(gap) && gap >= 0 && gap <= GROUP_WINDOW_MS;
}

function streamAnnouncement(
  previous: ReadonlyMap<string, RoomAgentStream["state"]>,
  streams: readonly RoomAgentStream[],
  names: ReadonlyMap<string, string>
): { next: Map<string, RoomAgentStream["state"]>; text: string } {
  const next = new Map<string, RoomAgentStream["state"]>();
  const parts: string[] = [];
  for (const stream of streams) {
    const name = names.get(stream.participant_id) ?? "Agent";
    next.set(stream.stream_id, stream.state);
    const prior = previous.get(stream.stream_id);
    if (prior === undefined && stream.state === "streaming") parts.push(`${name} 开始生成`);
    else if (prior !== "committing" && stream.state === "committing") parts.push(`${name} 正在写入房间`);
  }
  return { next, text: parts.join("；") };
}

export const Timeline = memo(function Timeline({ roomId }: { roomId: string }) {
  const room = useRoomStore(useShallow((state) => {
    const cache = state.roomsById[roomId];
    return {
      projection: cache?.projection ?? null,
      items: cache?.timelineItems ?? EMPTY_ITEMS,
      pending: cache?.pendingMessages ?? EMPTY_PENDING,
      loading: cache?.loading ?? true,
      loadingOlder: cache?.loadingOlder ?? false
    };
  }));
  const streams = useRoomStore((state) => state.roomsById[roomId]?.agentStreams ?? EMPTY_STREAMS);
  const anchor = useRoomStore((state) => state.scrollAnchors[roomId]);
  const markRead = useRoomStore((state) => state.markRead);
  const saveScrollAnchor = useRoomStore((state) => state.saveScrollAnchor);
  const loadOlder = useRoomStore((state) => state.loadOlder);
  const retryMessage = useRoomStore((state) => state.retryMessage);

  const containerRef = useRef<HTMLDivElement>(null);
  const initializedRoomRef = useRef<string | null>(null);
  const followRef = useRef(true);
  const previousCountRef = useRef(0);
  const loadingHistoryRef = useRef(false);
  const streamStatesRef = useRef<Map<string, RoomAgentStream["state"]>>(new Map());
  const [unseen, setUnseen] = useState(0);
  const [announcement, setAnnouncement] = useState("");

  const participants = room.projection?.participants;
  const lookup = useMemo<ParticipantLookup>(() => {
    const byId = new Map((participants ?? []).map((participant) => [participant.participant_id, participant]));
    return (participantId) => {
      const participant = participantId ? byId.get(participantId) : undefined;
      if (!participant) return null;
      return { family: familyOf(participant.cli_kind), role: participant.role || null };
    };
  }, [participants]);
  const names = useMemo(
    () => new Map((participants ?? []).map((participant) => [participant.participant_id, participant.display_name])),
    [participants]
  );
  const leadName = useMemo(() => {
    const collaboration = room.projection?.collaboration;
    if (collaboration?.mode !== "addressed" || !collaboration.lead_participant_id) return null;
    return names.get(collaboration.lead_participant_id) ?? null;
  }, [room.projection?.collaboration, names]);

  const durableActivityIds = useMemo(
    () => new Set(room.items.map((item) => item.activity_id).filter(Boolean)),
    [room.items]
  );
  const visibleStreams = useMemo(() => streams.filter((stream) => {
    if (stream.state === "invalidated") return false;
    if (stream.state !== "resolved") return true;
    const produced = stream.resolution?.produced_activity_id;
    return Boolean(produced && !durableActivityIds.has(produced));
  }), [streams, durableActivityIds]);
  const streamContentKey = visibleStreams.map((stream) => `${stream.stream_id}:${stream.content.length}`).join("|");
  const visibleSeq = room.projection?.latest_visible_room_seq ?? room.items.at(-1)?.room_seq ?? 0;

  // Enter a room: restore the saved reading position, or start at the newest message.
  useEffect(() => {
    const container = containerRef.current;
    if (!container || room.loading || initializedRoomRef.current === roomId) return;
    initializedRoomRef.current = roomId;
    const saved = anchor ? messageNodes(container).find((node) => node.dataset.messageId === anchor.messageId) : null;
    if (saved && anchor) container.scrollTop = saved.offsetTop - anchor.offset;
    else snapToBottom(container);
    followRef.current = atBottom(container);
    previousCountRef.current = room.items.length + room.pending.length;
    setUnseen(0);
    if (followRef.current && visibleSeq) markRead(roomId, visibleSeq);
    // Only on entering a room, not on every incremental page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, room.loading]);

  // New rows: follow when the reader is at the bottom, otherwise count them.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const count = room.items.length + room.pending.length;
    const added = Math.max(0, count - previousCountRef.current);
    previousCountRef.current = count;
    if (!added || loadingHistoryRef.current) return;
    if (followRef.current) {
      requestAnimationFrame(() => {
        snapToBottom(container);
        if (document.visibilityState === "visible" && visibleSeq) markRead(roomId, visibleSeq);
      });
    } else {
      setUnseen((current) => current + added);
    }
  }, [room.items.length, room.pending.length, markRead, roomId, visibleSeq]);

  // Streaming previews grow in place; keep them in view while following.
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !streamContentKey || !followRef.current) return;
    const frame = requestAnimationFrame(() => snapToBottom(container));
    return () => cancelAnimationFrame(frame);
  }, [streamContentKey]);

  useEffect(() => {
    const { next, text } = streamAnnouncement(streamStatesRef.current, streams, names);
    streamStatesRef.current = next;
    if (!text) return;
    const timer = window.setTimeout(() => setAnnouncement(text), 0);
    return () => window.clearTimeout(timer);
  }, [streams, names]);

  function handleScroll() {
    const container = containerRef.current;
    if (!container) return;
    followRef.current = atBottom(container);
    if (followRef.current) {
      setUnseen(0);
      if (document.visibilityState === "visible" && visibleSeq) markRead(roomId, visibleSeq);
    }
    const captured = captureAnchor(container);
    if (captured) saveScrollAnchor(roomId, captured);
  }

  async function handleLoadOlder() {
    const container = containerRef.current;
    if (!container || room.loadingOlder) return;
    const snapshot = captureAnchor(container);
    loadingHistoryRef.current = true;
    try {
      await loadOlder(roomId);
    } finally {
      requestAnimationFrame(() => {
        if (containerRef.current) restoreAnchor(containerRef.current, snapshot);
        loadingHistoryRef.current = false;
      });
    }
  }

  const jumpToReference = useCallback(async (messageId?: string | null, activityId?: string | null) => {
    const locate = () => {
      const container = containerRef.current;
      if (!container) return null;
      return messageNodes(container).find((node) =>
        (messageId && node.dataset.messageId === messageId) || (activityId && node.dataset.activityId === activityId)
      ) ?? null;
    };
    for (let page = 0; page < 5; page += 1) {
      const target = locate();
      if (target) {
        target.scrollIntoView?.({ block: "center", behavior: "smooth" });
        target.focus({ preventScroll: true });
        return;
      }
      const latest = useRoomStore.getState().roomsById[roomId];
      if (!latest?.projection?.has_older || latest.loadingOlder) return;
      await loadOlder(roomId);
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    }
  }, [loadOlder, roomId]);

  const empty = !room.loading && !room.items.length && !room.pending.length && !visibleStreams.length;

  return (
    <div className="relative min-h-0 flex-1">
      <div
        aria-label="房间消息"
        className="scrollbar-quiet h-full overflow-y-auto overscroll-contain pb-4"
        onScroll={handleScroll}
        ref={containerRef}
        role="log"
      >
        {room.projection?.has_older ? (
          <div className="flex justify-center pt-4 pb-2">
            <Button disabled={room.loadingOlder} onClick={() => void handleLoadOlder()} size="sm" variant="ghost">
              {room.loadingOlder ? "正在加载…" : "加载更早的消息"}
            </Button>
          </div>
        ) : <div className="h-4" />}
        {room.items.map((item, index) => {
          const previous = room.items[index - 1];
          const newDay = dayKey(item.created_at) !== dayKey(previous?.created_at);
          return (
            <Fragment key={item.id}>
              {newDay && item.created_at ? (
                <div className="flex items-center gap-3 px-4 pt-4 pb-1 sm:px-6" role="separator">
                  <span className="text-xs font-medium text-fg-3">{formatDay(item.created_at)}</span>
                  <span aria-hidden="true" className="h-px flex-1 bg-line" />
                </div>
              ) : null}
              <TimelineItem
                compact={!newDay && continuesRun(previous, item)}
                item={item}
                leadName={leadName}
                lookup={lookup}
                onJumpToReference={jumpToReference}
              />
            </Fragment>
          );
        })}
        {room.pending.map((pending) => (
          <PendingItem key={pending.clientRequestId} onRetry={() => void retryMessage(pending.clientRequestId)} pending={pending} />
        ))}
        {visibleStreams.map((stream) => {
          const participant = lookup(stream.participant_id);
          return (
            <AgentPreview
              family={participant?.family ?? "other"}
              key={stream.stream_id}
              name={names.get(stream.participant_id) ?? "Agent"}
              stream={stream}
            />
          );
        })}
        {empty ? (
          <div className="mx-auto mt-[18vh] max-w-sm px-6 text-center">
            <p className="m-0 text-base font-semibold text-fg">房间还没有消息</p>
            <p className="m-0 mt-1.5 text-ui text-fg-3">
              说出目标，房间里的 Agent 会各自判断是否接手。用 @ 点名某位 Agent，它会优先处理。
            </p>
          </div>
        ) : null}
      </div>
      <div aria-live="polite" className="sr-only" role="status">{announcement}</div>
      {unseen > 0 ? (
        <div className="pointer-events-none absolute inset-x-0 bottom-3 flex justify-center">
          <button
            className="pointer-events-auto inline-flex h-7 items-center gap-1.5 rounded-full bg-inverse px-3 text-ui font-medium text-on-inverse shadow-overlay"
            onClick={() => {
              const container = containerRef.current;
              if (container) snapToBottom(container);
              setUnseen(0);
            }}
            type="button"
          >
            <ArrowDown aria-hidden="true" className="size-3.5" /> {unseen} 条新消息
          </button>
        </div>
      ) : null}
    </div>
  );
});
