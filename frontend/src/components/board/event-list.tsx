"use client";

import { useState } from "react";

import { AgentQuote } from "@/components/ui/agent-quote";
import { formatClock } from "@/components/room/format";
import type { BoardEvent } from "@/lib/board-types";

import type { BoardPeople } from "./board-context";
import { eventLine } from "./events";
import { TrustGlyph } from "./trust";
import { VerificationGates } from "./verification-gates";

/** A failed or errored verification event can show its gates (§5.2), read only once opened. */
function GatesDisclosure({ roomId, verificationId }: { roomId: string; verificationId: string }) {
  const [open, setOpen] = useState(false);
  return (
    <details className="mt-1.5 text-xs" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer select-none text-fg-3 hover:text-fg-2">看门禁和输出</summary>
      {open ? <div className="mt-1.5"><VerificationGates roomId={roomId} verificationId={verificationId} /></div> : null}
    </details>
  );
}

function failedVerificationId(event: BoardEvent): string | null {
  if (event.kind !== "verification") return null;
  const { status, verification_id: id } = event.data;
  return (status === "failed" || status === "error") && typeof id === "string" && id ? id : null;
}

/** Evidence timeline: who did what, newest first. Agent words are quoted, host facts are not. */
export function EventList({
  events,
  people,
  showModule = false,
  onOpenModule,
  roomId
}: {
  events: BoardEvent[];
  people: BoardPeople;
  showModule?: boolean;
  onOpenModule?: (moduleId: string) => void;
  /** Given, failed verifications can open their gate output (the module file passes it). */
  roomId?: string;
}) {
  if (!events.length) return <p className="m-0 px-4 py-2 text-xs text-fg-3">还没有事件。</p>;
  const ordered = [...events].sort((left, right) => right.seq - left.seq);
  return (
    <ol className="m-0 list-none p-0">
      {ordered.map((event, index) => {
        const line = eventLine(event, (id) => people.name(id));
        const verificationId = roomId ? failedVerificationId(event) : null;
        const actor = line.actor.kind === "infrastructure" ? "宿主" : line.actor.kind === "operator" ? "你" : people.name(line.actor.participantId);
        return (
          <li className="relative flex gap-3 px-4 pb-3" key={event.seq}>
            {index < ordered.length - 1 ? (
              <span aria-hidden="true" className="absolute top-4 bottom-0 left-[22.5px] w-px bg-line" />
            ) : null}
            <TrustGlyph className="relative mt-0.5" size={14} tone={line.tone} />
            <div className="min-w-0 flex-1">
              <p className="m-0 flex flex-wrap items-baseline gap-x-1.5 text-ui">
                <span className="font-medium text-fg">{line.title}</span>
                {showModule && event.module_id ? (
                  onOpenModule ? (
                    <button className="font-mono text-xs text-fg-2 underline decoration-line-strong underline-offset-2 hover:text-fg" onClick={() => onOpenModule(event.module_id!)} type="button">
                      {event.module_id}
                    </button>
                  ) : <code className="font-mono text-xs text-fg-2">{event.module_id}</code>
                ) : null}
              </p>
              <p className="m-0 text-xs text-fg-3">
                {actor} · <time dateTime={event.at}>{formatClock(event.at)}</time>
                {line.facts.length ? ` · ${line.facts.join(" · ")}` : ""}
              </p>
              {line.quote ? <AgentQuote className="mt-1.5 text-ui" value={line.quote} /> : null}
              {roomId && verificationId ? <GatesDisclosure roomId={roomId} verificationId={verificationId} /> : null}
              {line.extras.length ? (
                <ul className="m-0 mt-1 list-none space-y-0.5 p-0 pl-3">
                  {line.extras.map((claim, claimIndex) => (
                    <li className="text-xs" key={claimIndex}>
                      <AgentQuote clamp={2} inline value={claim} />
                    </li>
                  ))}
                  {line.extrasTotal > line.extras.length ? (
                    <li className="text-xs text-fg-3">另有 {line.extrasTotal - line.extras.length} 条声明未显示</li>
                  ) : null}
                </ul>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
