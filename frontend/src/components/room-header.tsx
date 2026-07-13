"use client";

import type { CSSProperties } from "react";

import type { RoomParticipant } from "@/lib/types";

const AGENT_COLORS = ["#d49a62", "#8e9ef5", "#69ad83", "#c784a4", "#77a9c9", "#b49a68"];

function hash(value: string): number {
  let result = 0;
  for (let index = 0; index < value.length; index += 1) {
    result = (result * 31 + value.charCodeAt(index)) >>> 0;
  }
  return result;
}

export function identityStyle(id: string): CSSProperties {
  return { "--agent-color": AGENT_COLORS[hash(id) % AGENT_COLORS.length] } as CSSProperties;
}

export function initials(name: string): string {
  return name.trim().slice(0, 2).toUpperCase() || "A";
}

export function formatRoomTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

export function RoomMemberStack({
  participants,
  label
}: {
  participants: RoomParticipant[];
  label: string;
}) {
  return (
    <div className="room-member-stack" aria-label={label}>
      {participants.slice(0, 4).map((participant) => (
        <span
          className="room-avatar"
          key={participant.participant_id}
          style={identityStyle(participant.participant_id)}
          title={participant.display_name}
        >
          {initials(participant.display_name)}
        </span>
      ))}
      {participants.length > 4 ? <span className="room-avatar room-avatar--count">+{participants.length - 4}</span> : null}
    </div>
  );
}

export type RoomHeaderAlert = {
  className: string;
  label: string;
  glyph: string;
} | null;

export function RoomHeader({
  title,
  syncState,
  syncLabel,
  participants,
  navigationOpen,
  inspectorOpen,
  operationsAlert,
  theme,
  onToggleNavigation,
  onToggleInspector,
  onToggleTheme
}: {
  title: string;
  syncState: string;
  syncLabel: string;
  participants: RoomParticipant[];
  navigationOpen: boolean;
  inspectorOpen: boolean;
  operationsAlert: RoomHeaderAlert;
  theme: "dark" | "light";
  onToggleNavigation: () => void;
  onToggleInspector: () => void;
  onToggleTheme: () => void;
}) {
  return (
    <header className="room-header">
      <div className="room-header__leading">
        <button className="room-icon-button" onClick={onToggleNavigation} type="button" aria-label={navigationOpen ? "关闭房间栏" : "打开房间栏"}>☰</button>
        <div>
          <h1>{title}</h1>
          <span className={`room-sync state-${syncState}`}><i />{syncLabel}</span>
        </div>
      </div>
      <div className="room-header__actions">
        <RoomMemberStack participants={participants} label="当前房间成员" />
        <button
          aria-controls="room-inspector"
          aria-expanded={inspectorOpen}
          className={`room-quiet-button room-inspector-toggle ${operationsAlert?.className ?? ""}`}
          onClick={onToggleInspector}
          type="button"
        >
          {inspectorOpen ? "收起检查器" : "成员与状态"}
          {operationsAlert ? <span aria-label={operationsAlert.label}>{operationsAlert.glyph}</span> : null}
        </button>
        <button className="room-icon-button" onClick={onToggleTheme} type="button" aria-label="切换主题">
          {theme === "dark" ? "☼" : "◐"}
        </button>
      </div>
    </header>
  );
}
