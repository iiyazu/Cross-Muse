"use client";

import { memo, useState } from "react";
import { ArrowRightLeft, Check, Copy, CornerDownRight, FileDiff, RotateCw } from "lucide-react";

import { Avatar, familyOf, type Family } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { addressingChip, handoffNoteSections } from "@/lib/room-view";
import type { RoomHandoffNote, RoomTimelineItem } from "@/lib/types";
import type { PendingRoomMessage } from "@/store/domain";

import { formatClock, isHumanActor, isSystemActor } from "./format";
import { RoomMarkdown } from "./markdown";

export type ParticipantLookup = (participantId: string | null | undefined) => { family: Family; role: string | null } | null;

const HANDOFF_LABELS: Record<string, string> = {
  what: "要做什么",
  why: "为什么",
  tradeoffs: "取舍",
  open_questions: "未决问题",
  next_action: "下一步"
};

function HandoffNote({ note }: { note: RoomHandoffNote }) {
  const sections = handoffNoteSections(note);
  if (!sections.length) return null;
  return (
    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 rounded-md border border-line bg-sunken px-3 py-2 text-ui">
      {sections.map((section) => (
        <div className="contents" key={section.key}>
          <dt className="text-fg-3">{HANDOFF_LABELS[section.key] ?? section.label}</dt>
          <dd className="m-0 min-w-0 break-words text-fg-2">
            {section.questions ? (
              <ul className="m-0 list-disc pl-4">
                {section.questions.map((question) => <li key={question}>{question}</li>)}
              </ul>
            ) : section.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      aria-label={copied ? "已复制消息" : "复制消息"}
      className="inline-flex size-6 items-center justify-center rounded-sm text-fg-3 opacity-0 transition-opacity group-hover/item:opacity-100 hover:bg-hover hover:text-fg focus-visible:opacity-100"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1400);
        } catch {
          setCopied(false);
        }
      }}
      type="button"
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
    </button>
  );
}

export const TimelineItem = memo(function TimelineItem({
  item,
  compact,
  leadName,
  lookup,
  onJumpToReference
}: {
  item: RoomTimelineItem;
  /** Same author as the previous row within a few minutes: hide the header. */
  compact: boolean;
  leadName: string | null;
  lookup: ParticipantLookup;
  onJumpToReference: (messageId?: string | null, activityId?: string | null) => void;
}) {
  const human = isHumanActor(item.actor);
  const system = isSystemActor(item.actor);
  const participant = lookup(item.actor.participant_id);
  const family = human ? "human" : system ? "system" : participant?.family ?? familyOf(null, item.actor.kind);
  const name = human ? "你" : item.actor.display_name;
  const chip = human ? addressingChip(item, leadName) : null;
  const replyTarget = item.reply_to_message_id || item.reply_to_activity_id;
  const showHeader = !compact || Boolean(replyTarget) || item.kind !== "message";

  if (system && item.kind !== "handoff" && item.kind !== "proposal") {
    return (
      <div
        className="flex items-center gap-2 px-4 py-1 text-xs text-fg-3 sm:px-6"
        data-activity-id={item.activity_id ?? undefined}
        data-message-id={item.id}
        tabIndex={-1}
      >
        <span className="h-px flex-1 bg-line" aria-hidden="true" />
        <span className="max-w-[70%] truncate">{item.content}</span>
        <time dateTime={item.created_at ?? undefined}>{formatClock(item.created_at)}</time>
        <span className="h-px flex-1 bg-line" aria-hidden="true" />
      </div>
    );
  }

  return (
    <article
      aria-label={`${name} ${formatClock(item.created_at)}`}
      className={cx(
        "group/item relative flex gap-3 px-4 outline-none sm:px-6",
        "focus-visible:bg-hover hover:bg-[color-mix(in_oklch,var(--hover)_60%,transparent)]",
        showHeader ? "pt-2.5 pb-1" : "py-0.5"
      )}
      data-activity-id={item.activity_id ?? undefined}
      data-message-id={item.id}
      tabIndex={-1}
    >
      <div className="w-6 shrink-0 pt-0.5">
        {showHeader ? (
          <Avatar family={family} name={item.actor.display_name} />
        ) : (
          <time
            className="block pt-0.5 text-right font-mono text-[10px] leading-5 text-fg-4 opacity-0 group-hover/item:opacity-100"
            dateTime={item.created_at ?? undefined}
          >
            {formatClock(item.created_at).slice(-5)}
          </time>
        )}
      </div>
      <div className="min-w-0 flex-1">
        {showHeader ? (
          <header className="flex min-h-6 flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="text-sm font-semibold text-fg">{name}</span>
            {!human && participant?.role ? <span className="text-xs text-fg-3">{participant.role}</span> : null}
            {item.kind === "handoff" ? (
              <span className="inline-flex items-center gap-1 rounded-sm bg-raised px-1.5 text-xs text-fg-2">
                <ArrowRightLeft aria-hidden="true" className="size-3" /> 转交
              </span>
            ) : null}
            {item.kind === "proposal" ? (
              <span className="inline-flex items-center gap-1 rounded-sm bg-raised px-1.5 text-xs text-fg-2">
                <FileDiff aria-hidden="true" className="size-3" /> 提案
              </span>
            ) : null}
            <time className="text-xs text-fg-3" dateTime={item.created_at ?? undefined}>{formatClock(item.created_at)}</time>
            <span className="ml-auto">
              <CopyButton text={item.content} />
            </span>
          </header>
        ) : null}
        {chip || replyTarget ? (
          <div className="mb-0.5 flex flex-wrap items-center gap-x-3 text-xs text-fg-3">
            {chip ? <span className="font-mono">{chip}</span> : null}
            {replyTarget ? (
              <button
                className="inline-flex items-center gap-1 rounded-sm hover:text-fg"
                onClick={() => onJumpToReference(item.reply_to_message_id, item.reply_to_activity_id)}
                type="button"
              >
                <CornerDownRight aria-hidden="true" className="size-3" />
                回复 {item.reply_target_display_name ?? "上一条消息"}
              </button>
            ) : null}
          </div>
        ) : null}
        <RoomMarkdown content={item.content} />
        {item.kind === "handoff" && item.handoff_targets?.length ? (
          <p className="m-0 mt-1.5 text-ui text-fg-2">
            转交给 <span className="font-medium text-fg">{item.handoff_targets.join("、")}</span>
          </p>
        ) : null}
        {item.handoff_note ? <HandoffNote note={item.handoff_note} /> : null}
      </div>
    </article>
  );
});

export function PendingItem({ pending, onRetry }: { pending: PendingRoomMessage; onRetry: () => void }) {
  const failed = pending.status === "failed";
  return (
    <article
      aria-label={failed ? "你 · 发送失败" : "你 · 发送中"}
      className="flex gap-3 px-4 pt-2.5 pb-1 sm:px-6"
      data-message-id={`pending:${pending.clientRequestId}`}
    >
      <div className="w-6 shrink-0 pt-0.5">
        <Avatar family="human" name="你" />
      </div>
      <div className={cx("min-w-0 flex-1", !failed && "opacity-60")}>
        <header className="flex min-h-6 items-center gap-2">
          <span className="text-sm font-semibold text-fg">你</span>
          <span className={cx("text-xs", failed ? "text-fail" : "text-fg-3")}>{failed ? "发送失败" : "发送中…"}</span>
        </header>
        <RoomMarkdown content={pending.content} />
        {failed ? (
          <div className="mt-2 flex flex-wrap items-center gap-3 rounded-md border border-fail-line bg-fail-soft px-3 py-2 text-ui" role="alert">
            <span className="text-fail">消息没有发出去，原文还在这里。</span>
            <Button onClick={onRetry} size="sm" variant="secondary">
              <RotateCw aria-hidden="true" className="size-3.5" /> 重试
            </Button>
          </div>
        ) : null}
      </div>
    </article>
  );
}
