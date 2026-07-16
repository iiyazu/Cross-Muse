"use client";

import { roomParticipantStateLabel, roomStateLabel } from "@/lib/room-view";
import type { RoomControlActionDescriptor, RoomTurn, RoomTurnParticipant } from "@/lib/types";
import { identityStyle, initials } from "./room-header";

export type RoomCancelTarget = {
  observationId: string;
  participant: RoomTurnParticipant;
  descriptor: RoomControlActionDescriptor;
};

export function RoomTurnStatus({
  turn,
  hiddenCount,
  controlPending,
  onSelectAgent = () => undefined,
  onCancel,
  onRetry
}: {
  turn: RoomTurn | null;
  hiddenCount: number;
  controlPending: { observationId: string; action: "cancel" | "retry" } | null;
  onSelectAgent?: (participantId: string) => void;
  onCancel: (target: RoomCancelTarget) => void;
  onRetry: (observationId: string, descriptor: RoomControlActionDescriptor) => void;
}) {
  if (!turn) return <div className="room-turn-empty">发送消息后，所有活跃 Agent 会独立观察并决定是否回应。</div>;
  return (
    <section className={`room-turn-status state-${turn.state}`} aria-label="当前 Agent 状态">
      <div className="room-turn-status__summary"><span className="room-state-dot" /><strong>{roomStateLabel(turn.state)}</strong>{hiddenCount > 0 ? <small>另有 {hiddenCount} 轮进行中</small> : null}</div>
      <div className="room-turn-status__agents">
        {turn.participants.map((participant) => {
          const observationId = participant.frontier?.observation_id ?? "";
          const cancel = participant.frontier?.actions?.cancel;
          const retry = participant.frontier?.actions?.retry;
          const pending = controlPending?.observationId === observationId;
          const stateLabel = (participant.state ?? participant.status) === "noop" && (participant.response_count ?? 0) > 0
            ? "已回应 · 后续未跟答"
            : roomParticipantStateLabel(participant.state ?? participant.status);
          return (
            <div className={`room-agent-state state-${participant.state ?? participant.status}`} key={participant.participant_id}>
              <button className="room-agent-state__identity" onClick={() => onSelectAgent(participant.participant_id)} type="button">
                <i className="room-avatar" style={identityStyle(participant.participant_id)}>{initials(participant.display_name)}</i>
                <span><strong>{participant.display_name}</strong><small>{stateLabel}</small></span>
              </button>
              {(cancel?.available || retry?.available) ? <details className="room-agent-state__controls"><summary>控制</summary><div>
              <button aria-label={`取消 ${participant.display_name} 当前处理`} className="room-control-button is-cancel" disabled={pending || !cancel?.available || !observationId} onClick={() => cancel?.available && observationId && onCancel({ observationId, participant, descriptor: cancel })} title={cancel?.available ? "只取消该 Agent 当前 delivery" : "当前没有可取消的 delivery"} type="button">{pending ? "处理中" : "取消"}</button>
              <button aria-label={`重试 ${participant.display_name} 当前 observation`} className="room-control-button is-retry" disabled={pending || !retry?.available || !observationId} onClick={() => retry?.available && observationId && onRetry(observationId, retry)} title={retry?.available ? "重新开放同一 observation" : "仅已取消或尝试耗尽的 observation 可重试"} type="button">{pending ? "处理中" : "重试"}</button>
              </div></details> : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}
