"use client";

import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";

import { StatusStrip } from "@/components/board/status-strip";
import { Composer } from "@/components/room/composer";
import { Timeline } from "@/components/room/timeline";
import { TurnStatus } from "@/components/room/turn-status";
import { Button } from "@/components/ui/button";
import type { RoomParticipant } from "@/lib/types";
import { useRoomStore } from "@/store/room-store";

import { RoomHeader, type HealthTone } from "./room-header";

const NO_PARTICIPANTS: RoomParticipant[] = [];

export function RoomView({
  roomId,
  railDocked,
  panelOpen,
  attentionCount,
  onOpenRail,
  onTogglePanel,
  onOpenPanel,
  onOpenSystem
}: {
  roomId: string;
  railDocked: boolean;
  panelOpen: boolean;
  attentionCount: number;
  onOpenRail: () => void;
  onTogglePanel: () => void;
  onOpenPanel: () => void;
  onOpenSystem: () => void;
}) {
  const room = useRoomStore(useShallow((state) => {
    const cache = state.roomsById[roomId];
    return {
      projection: cache?.projection ?? null,
      syncState: cache?.syncState ?? "idle",
      error: cache?.error ?? null,
      loading: cache?.loading ?? true,
      controlPending: cache?.controlPending ?? null,
      controlError: cache?.controlError ?? null
    };
  }));
  const summary = useRoomStore((state) => state.rooms.find((candidate) => candidate.conversation_id === roomId) ?? null);
  const operationsState = useRoomStore((state) => state.operations?.overall ?? "healthy");
  const draft = useRoomStore((state) => state.drafts[roomId] ?? "");
  const setDraft = useRoomStore((state) => state.setDraft);
  const sendMessage = useRoomStore((state) => state.sendMessage);
  const controlObservation = useRoomStore((state) => state.controlObservation);
  const clearControlError = useRoomStore((state) => state.clearControlError);
  const refreshRoom = useRoomStore((state) => state.refreshRoom);

  const projection = room.projection;
  const participants = projection?.participants ?? summary?.members ?? NO_PARTICIPANTS;
  const collaboration = projection?.collaboration ?? summary?.collaboration ?? null;
  const title = projection?.conversation.title ?? summary?.title ?? "房间";
  const turns = projection?.turns;
  const currentTurn = useMemo(() => {
    if (!turns?.length) return null;
    return turns.filter((turn) => turn.state !== "settled").at(-1) ?? turns.at(-1) ?? null;
  }, [turns]);
  const hiddenTurns = Math.max(0, (projection?.active_turn_count ?? 0) - (currentTurn && currentTurn.state !== "settled" ? 1 : 0));
  const leadName = collaboration?.mode === "addressed" && collaboration.lead_participant_id
    ? participants.find((participant) => participant.participant_id === collaboration.lead_participant_id)?.display_name ?? null
    : null;
  const health: HealthTone = operationsState === "blocked"
    ? "blocked"
    : operationsState === "attention" || room.syncState === "offline" || room.syncState === "stale"
      ? "attn"
      : "ok";

  if (room.error && !projection && !room.loading) {
    const missing = room.error.status === 404;
    return (
      <div className="flex h-full flex-col">
        <RoomHeader
          collaboration={null}
          health={health}
          onOpenRail={onOpenRail}
          onOpenSystem={onOpenSystem}
          onTogglePanel={onTogglePanel}
          panelBadge={0}
          panelOpen={panelOpen}
          participants={NO_PARTICIPANTS}
          railDocked={railDocked}
          syncState={room.syncState}
          title={missing ? "找不到这个房间" : "房间暂时打不开"}
        />
        <div className="mx-auto mt-[20vh] max-w-sm px-6 text-center">
          <p className="m-0 text-base font-semibold text-fg">{missing ? "找不到这个房间" : "房间暂时打不开"}</p>
          <p className="m-0 mt-1.5 text-ui text-fg-3">
            {missing ? "链接里的房间不存在，或者已经不在这台机器上了。" : "后端没有响应。确认 xmuse 正在运行后重试。"}
          </p>
          {!missing ? (
            <Button className="mt-4" onClick={() => void refreshRoom(roomId, "initial")} size="sm">重试</Button>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <RoomHeader
        collaboration={collaboration}
        health={health}
        onOpenRail={onOpenRail}
        onOpenSystem={onOpenSystem}
        onTogglePanel={onTogglePanel}
        panelBadge={attentionCount}
        panelOpen={panelOpen}
        participants={participants}
        railDocked={railDocked}
        syncState={room.syncState}
        title={title}
      />
      <StatusStrip onOpen={onOpenPanel} roomId={roomId} />
      <Timeline roomId={roomId} />
      <div className="shrink-0">
        {room.controlError ? (
          <div className="mx-4 mb-1 flex items-center gap-3 rounded-md border border-fail-line bg-fail-soft px-3 py-1.5 text-ui sm:mx-6" role="alert">
            <span className="flex-1 text-fail">操作没有生效，已刷新为最新状态。</span>
            <button className="text-xs text-fg-2 hover:text-fg" onClick={() => clearControlError(roomId)} type="button">知道了</button>
          </div>
        ) : null}
        <TurnStatus
          controlPending={room.controlPending}
          hiddenCount={hiddenTurns}
          onControl={controlObservation}
          turn={currentTurn}
        />
        <Composer
          collaboration={collaboration}
          draft={draft}
          leadName={leadName}
          onDraftChange={(value) => setDraft(roomId, value)}
          onSend={(content) => sendMessage(content)}
          participants={participants}
          roomId={roomId}
        />
      </div>
    </div>
  );
}
