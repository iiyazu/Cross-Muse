"use client";

import { PanelLeft, PanelRight } from "lucide-react";

import { participantPresence } from "@/components/room/format";
import { Avatar, familyLabel, familyOf } from "@/components/ui/avatar";
import { IconButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import type { RoomCollaboration, RoomParticipant } from "@/lib/types";
import type { RoomSyncState } from "@/store/domain";

const SYNC_LABEL: Record<RoomSyncState, string | null> = {
  idle: null,
  syncing: "同步中",
  synced: null,
  "catching-up": "正在追上最新状态",
  stale: "连接不稳定，显示的可能不是最新状态",
  offline: "已离线，正在重连"
};

export type HealthTone = "ok" | "attn" | "blocked";

export function RoomHeader({
  title,
  participants,
  collaboration,
  syncState,
  health,
  railDocked,
  panelOpen,
  panelBadge,
  onOpenRail,
  onTogglePanel,
  onOpenSystem
}: {
  title: string;
  participants: RoomParticipant[];
  collaboration: RoomCollaboration | null;
  syncState: RoomSyncState;
  health: HealthTone;
  railDocked: boolean;
  panelOpen: boolean;
  /** Count of items that need the human, shown on the work-panel toggle. */
  panelBadge: number;
  onOpenRail: () => void;
  onTogglePanel: () => void;
  onOpenSystem: () => void;
}) {
  const agents = participants.filter((participant) => participant.role !== "init");
  const shown = agents.slice(0, 5);
  const lead = collaboration?.mode === "addressed" && collaboration.lead_participant_id
    ? agents.find((participant) => participant.participant_id === collaboration.lead_participant_id) ?? null
    : null;
  const syncLabel = SYNC_LABEL[syncState];
  const mode = collaboration?.mode === "addressed"
    ? `点名协作${lead ? ` · lead ${lead.display_name}` : ""}`
    : "广播协作";

  return (
    <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line px-2 sm:px-3">
      {!railDocked ? (
        <IconButton label="打开房间列表" onClick={onOpenRail} size="sm">
          <PanelLeft aria-hidden="true" className="size-4" />
        </IconButton>
      ) : null}
      <div className="flex min-w-0 flex-1 items-baseline gap-2.5 pl-1">
        <h1 className="m-0 min-w-0 truncate text-sm font-semibold text-fg">{title}</h1>
        <span className="hidden shrink-0 text-xs text-fg-3 md:inline">{mode}</span>
        {syncLabel ? (
          <span className={cx("shrink-0 truncate text-xs", syncState === "offline" || syncState === "stale" ? "text-attn" : "text-fg-3")} role="status">
            {syncLabel}
          </span>
        ) : null}
      </div>
      <ul aria-label="房间成员" className="m-0 hidden list-none items-center p-0 sm:flex">
        {shown.map((participant, index) => {
          const family = familyOf(participant.cli_kind);
          const vendor = familyLabel(family);
          return (
            <li className={cx("relative", index > 0 && "-ml-1.5")} key={participant.participant_id} title={`${participant.display_name}${vendor ? ` · ${vendor}` : ""}`}>
              <span className="block rounded-full ring-2 ring-canvas">
                <Avatar
                  family={family}
                  name={participant.display_name}
                  presence={participantPresence(participant.status, participant.active)}
                  size="sm"
                />
              </span>
              <span className="sr-only">{participant.display_name}{vendor ? `（${vendor}）` : ""}</span>
            </li>
          );
        })}
        {agents.length > shown.length ? (
          <li className="-ml-1.5 inline-flex size-5 items-center justify-center rounded-full bg-raised text-[10px] text-fg-2 ring-2 ring-canvas">
            +{agents.length - shown.length}
          </li>
        ) : null}
      </ul>
      <button
        aria-label={health === "ok" ? "系统正常" : health === "attn" ? "系统需要关注" : "系统已阻塞"}
        className="inline-flex size-7 items-center justify-center rounded-md hover:bg-hover"
        onClick={onOpenSystem}
        title={health === "ok" ? "系统正常" : "系统需要关注"}
        type="button"
      >
        <span
          aria-hidden="true"
          className={cx(
            "size-2 rounded-full",
            health === "ok" ? "bg-proof-solid" : health === "attn" ? "bg-attn-solid" : "bg-fail-solid"
          )}
        />
      </button>
      <button
        aria-expanded={panelOpen}
        aria-label={panelBadge ? `工作面板，${panelBadge} 项待你处理` : "工作面板"}
        className={cx(
          "inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-ui font-medium transition-colors",
          panelOpen ? "bg-selected text-fg" : "text-fg-2 hover:bg-hover hover:text-fg"
        )}
        onClick={onTogglePanel}
        type="button"
      >
        <PanelRight aria-hidden="true" className="size-4" />
        <span className="hidden sm:inline">工作</span>
        {panelBadge ? (
          <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-attn-solid px-1 text-[10px] font-semibold text-[oklch(0.25_0.05_70)]">
            {panelBadge}
          </span>
        ) : null}
      </button>
    </header>
  );
}
