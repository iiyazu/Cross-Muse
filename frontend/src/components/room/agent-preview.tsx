"use client";

import { memo } from "react";

import { Avatar, type Family } from "@/components/ui/avatar";
import type { RoomAgentStream } from "@/lib/types";

/**
 * A provider's in-flight answer. It is a disposable preview, not Room speech: it never gets
 * the message styling, carries an explicit label, and disappears once the durable message
 * lands or the attempt is invalidated.
 */
export const AgentPreview = memo(function AgentPreview({
  stream,
  name,
  family
}: {
  stream: RoomAgentStream;
  name: string;
  family: Family;
}) {
  const committing = stream.state === "committing";
  return (
    <article aria-label={`${name} 正在生成（预览）`} className="flex gap-3 px-4 pt-2.5 pb-1 sm:px-6">
      <div className="w-6 shrink-0 pt-0.5">
        <Avatar family={family} name={name} presence="live" />
      </div>
      <div className="min-w-0 flex-1">
        <header className="flex min-h-6 flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-fg">{name}</span>
          <span className="text-xs text-live">{committing ? "正在写入房间…" : "正在生成…"}</span>
          <span className="rounded-sm border border-dashed border-line-strong px-1.5 text-[11px] leading-4 text-fg-3">
            预览 · 尚未进入房间记录
          </span>
        </header>
        <div className="mt-0.5 border-l-2 border-dashed border-live-line pl-3 text-fg-2">
          <p className="m-0 break-words whitespace-pre-wrap [overflow-wrap:anywhere]">
            {stream.content}
            <span aria-hidden="true" className="ml-0.5 inline-block h-3.5 w-1.5 translate-y-0.5 animate-pulse-soft bg-live-solid" />
          </p>
          {stream.truncated ? <p className="m-0 text-xs text-fg-3">预览已截断，完整内容以房间消息为准。</p> : null}
        </div>
      </div>
    </article>
  );
});
