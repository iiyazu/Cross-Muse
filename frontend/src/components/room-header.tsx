"use client";

import type { CSSProperties } from "react";
import { Menu, Moon, PanelRight, Sun } from "lucide-react";

import { collaborationModeLabel, providerBadge } from "@/lib/room-view";
import type { RoomCollaboration, RoomParticipant } from "@/lib/types";

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

export function ProviderBadge({
  cliKind,
  className = ""
}: {
  cliKind?: string | null;
  className?: string;
}) {
  const badge = providerBadge(cliKind);
  if (!badge) return null;
  return (
    <span
      aria-label={`${badge.label} · ${badge.confinement}`}
      className={`room-provider-badge provider-${badge.id} ${className}`.trim()}
      title={`${badge.label} · ${badge.confinement}`}
    >
      {badge.label}
    </span>
  );
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
      {participants.slice(0, 4).map((participant) => {
        const badge = providerBadge(participant.cli_kind);
        return (
          <span
            className="room-avatar"
            key={participant.participant_id}
            style={identityStyle(participant.participant_id)}
            title={badge
              ? `${participant.display_name} · ${badge.label} · ${badge.confinement}`
              : participant.display_name}
          >
            {initials(participant.display_name)}
            {badge ? <i aria-hidden="true" className={`room-avatar__provider provider-${badge.id}`} /> : null}
          </span>
        );
      })}
      {participants.length > 4 ? <span className="room-avatar room-avatar--count">+{participants.length - 4}</span> : null}
    </div>
  );
}

export function roomCollaborationChip(
  collaboration: RoomCollaboration | null | undefined,
  participants: RoomParticipant[]
): { label: string; title: string } | null {
  if (!collaboration) return null;
  if (collaboration.mode === "addressed") {
    const lead = collaboration.lead_participant_id
      ? participants.find((participant) => participant.participant_id === collaboration.lead_participant_id)
      : null;
    return {
      label: `${collaborationModeLabel(collaboration.mode)} · lead ${lead?.display_name ?? "未指定"}`,
      title: "Addressed：仅被 @ 提及的 Agent 会观察；未提及时发给 lead"
    };
  }
  return {
    label: `${collaborationModeLabel(collaboration.mode)} · 全员观察`,
    title: "Broadcast：所有活跃 Agent 都会观察 Room 事件"
  };
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
  collaboration = null,
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
  collaboration?: RoomCollaboration | null;
  navigationOpen: boolean;
  inspectorOpen: boolean;
  operationsAlert: RoomHeaderAlert;
  theme: "dark" | "light";
  onToggleNavigation: () => void;
  onToggleInspector: () => void;
  onToggleTheme: () => void;
}) {
  const collaborationChip = roomCollaborationChip(collaboration, participants);
  return (
    <header className="room-header">
      <div className="room-header__leading">
        <button className="room-icon-button" onClick={onToggleNavigation} type="button" aria-label={navigationOpen ? "关闭房间栏" : "打开房间栏"}><Menu size={18} /></button>
        <div>
          <h1>{title}</h1>
          <span className={`room-sync state-${syncState}`}><i />{syncLabel}</span>
          {collaborationChip ? (
            <span className="room-collaboration-chip" title={collaborationChip.title}>{collaborationChip.label}</span>
          ) : null}
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
          <PanelRight size={16} />{inspectorOpen ? "收起工作台" : "工作台"}
          {operationsAlert ? <span aria-label={operationsAlert.label}>{operationsAlert.glyph}</span> : null}
        </button>
        <button className="room-icon-button" onClick={onToggleTheme} type="button" aria-label="切换主题">
          {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
        </button>
      </div>
    </header>
  );
}
