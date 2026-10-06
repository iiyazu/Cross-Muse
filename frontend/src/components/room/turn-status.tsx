"use client";

import { useState } from "react";
import { DropdownMenu } from "radix-ui";
import { Ellipsis } from "lucide-react";

import { Avatar, familyOf } from "@/components/ui/avatar";
import { cx } from "@/components/ui/cx";
import { ConfirmDialog } from "@/components/ui/overlay";
import { roomParticipantStateLabel, roomStateLabel } from "@/lib/room-view";
import type { RoomControlActionDescriptor, RoomTurn, RoomTurnParticipant } from "@/lib/types";

import { participantPresence } from "./format";

type CancelTarget = { observationId: string; participant: RoomTurnParticipant; descriptor: RoomControlActionDescriptor };

function participantStateLabel(participant: RoomTurnParticipant): string {
  const state = participant.state ?? participant.status;
  if (state === "noop" && (participant.response_count ?? 0) > 0) return "已回应 · 未再跟进";
  return roomParticipantStateLabel(state);
}

const TURN_DOT: Record<string, string> = {
  active: "bg-live-solid animate-pulse-soft",
  attention: "bg-attn-solid",
  settled: "bg-fg-4"
};

/**
 * The live status of the newest Human turn, docked above the composer where attention goes
 * after sending. Cancel/retry act on one participant's observation through the fixed routes.
 */
export function TurnStatus({
  turn,
  hiddenCount,
  controlPending,
  onControl
}: {
  turn: RoomTurn | null;
  hiddenCount: number;
  controlPending: { observationId: string; action: "cancel" | "retry" } | null;
  onControl: (observationId: string, action: "cancel" | "retry", descriptor: RoomControlActionDescriptor) => Promise<boolean>;
}) {
  const [cancelTarget, setCancelTarget] = useState<CancelTarget | null>(null);
  if (!turn) return null;

  return (
    <section aria-label="当前 Agent 状态" className="flex items-center gap-3 px-4 pt-2 pb-1 sm:px-6">
      <span className="flex shrink-0 items-center gap-1.5 text-xs font-medium text-fg-2">
        <span aria-hidden="true" className={cx("size-1.5 rounded-full", TURN_DOT[turn.state] ?? "bg-fg-4")} />
        {roomStateLabel(turn.state)}
        {hiddenCount > 0 ? <span className="font-normal text-fg-3">· 另有 {hiddenCount} 轮</span> : null}
      </span>
      <ul className="scrollbar-quiet m-0 flex min-w-0 flex-1 list-none items-center gap-1 overflow-x-auto p-0">
        {turn.participants.map((participant) => {
          const state = participant.state ?? participant.status;
          const observationId = participant.frontier?.observation_id ?? "";
          const cancel = participant.frontier?.actions?.cancel;
          const retry = participant.frontier?.actions?.retry;
          const pending = Boolean(observationId) && controlPending?.observationId === observationId;
          const controllable = Boolean(observationId) && (cancel?.available || retry?.available);
          return (
            <li
              className="flex shrink-0 items-center gap-1.5 rounded-full border border-line py-0.5 pr-1 pl-0.5 text-xs"
              key={participant.participant_id}
            >
              <Avatar
                family={familyOf(participant.cli_kind)}
                name={participant.display_name}
                presence={participantPresence(state, true)}
                size="sm"
              />
              <span className="text-fg-2">{participant.display_name}</span>
              <span className={cx("pr-1", state === "exhausted" ? "text-fail" : state === "runtime_recovery" ? "text-attn" : "text-fg-3")}>
                {pending ? "处理中…" : participantStateLabel(participant)}
              </span>
              {controllable ? (
                <DropdownMenu.Root>
                  <DropdownMenu.Trigger asChild>
                    <button
                      aria-label={`控制 ${participant.display_name}`}
                      className="inline-flex size-5 items-center justify-center rounded-full text-fg-3 hover:bg-hover hover:text-fg disabled:opacity-40"
                      disabled={pending}
                      type="button"
                    >
                      <Ellipsis aria-hidden="true" className="size-3.5" />
                    </button>
                  </DropdownMenu.Trigger>
                  <DropdownMenu.Portal>
                    <DropdownMenu.Content
                      align="end"
                      className="z-50 min-w-44 rounded-lg bg-overlay p-1 text-sm shadow-overlay"
                      sideOffset={6}
                    >
                      <DropdownMenu.Item
                        className="flex cursor-pointer items-center rounded-md px-2 py-1.5 text-fg outline-none data-[disabled]:cursor-default data-[disabled]:opacity-40 data-[highlighted]:bg-hover"
                        disabled={!cancel?.available}
                        onSelect={() => cancel && setCancelTarget({ observationId, participant, descriptor: cancel })}
                      >
                        取消当前处理
                      </DropdownMenu.Item>
                      <DropdownMenu.Item
                        className="flex cursor-pointer items-center rounded-md px-2 py-1.5 text-fg outline-none data-[disabled]:cursor-default data-[disabled]:opacity-40 data-[highlighted]:bg-hover"
                        disabled={!retry?.available}
                        onSelect={() => retry && void onControl(observationId, "retry", retry)}
                      >
                        重新开放并重试
                      </DropdownMenu.Item>
                    </DropdownMenu.Content>
                  </DropdownMenu.Portal>
                </DropdownMenu.Root>
              ) : null}
            </li>
          );
        })}
      </ul>
      <ConfirmDialog
        confirmLabel="取消当前处理"
        description="只结束这位 Agent 本次的处理，其他 Agent 和后续消息不受影响。取消后需要手动重试才会重新开始。"
        onConfirm={async () => {
          if (!cancelTarget) return;
          await onControl(cancelTarget.observationId, "cancel", cancelTarget.descriptor);
          setCancelTarget(null);
        }}
        onOpenChange={(open) => { if (!open) setCancelTarget(null); }}
        open={Boolean(cancelTarget)}
        pending={Boolean(cancelTarget && controlPending?.observationId === cancelTarget.observationId)}
        title={cancelTarget ? `取消 ${cancelTarget.participant.display_name} 的当前处理？` : "取消当前处理？"}
      />
    </section>
  );
}
