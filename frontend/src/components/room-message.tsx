"use client";

import { Fragment, useState } from "react";
import { Check, Copy } from "lucide-react";

import { addressingChip, handoffNoteSections } from "@/lib/room-view";
import type { RoomHandoffNote, RoomTimelineItem, XmuseApiErrorShape } from "@/lib/types";
import { formatRoomTime, identityStyle, initials } from "./room-header";
import { RoomMarkdown } from "./room-markdown";

const ADDRESSING_TITLES: Record<string, string> = {
  mentions: "@ 提及的 Agent 成为本次观察对象",
  lead: "未提及时发给 Room 的 lead",
  fallback_broadcast: "lead 不可用，本次回退为全员观察"
};

export function RoomHandoffNoteCard({ note }: { note: RoomHandoffNote }) {
  const sections = handoffNoteSections(note);
  if (!sections.length) return null;
  return (
    <details className="room-handoff-note">
      <summary>交办说明</summary>
      <dl>
        {sections.map((section) => (
          <Fragment key={section.key}>
            <dt>{section.label}</dt>
            <dd>
              {section.questions ? (
                <ul>{section.questions.map((question) => <li key={question}>{question}</li>)}</ul>
              ) : section.value}
            </dd>
          </Fragment>
        ))}
      </dl>
    </details>
  );
}

export type RoomPendingMessage = {
  clientRequestId: string;
  content: string;
  createdAt: string;
  status: "sending" | "failed";
  error?: XmuseApiErrorShape | null;
};

export function RoomMessageDetails({ item }: { item: RoomTimelineItem }) {
  const hasDetails = item.room_seq > 0 || item.activity_id || item.message_id || item.proposal_id || item.reply_to_activity_id || item.reply_to_message_id || item.proof_boundary || item.correlation_id || item.causation_id || item.source_refs?.length;
  if (!hasDetails) return null;
  return (
    <details className="room-message-details">
      <summary>核验因果</summary>
      <dl>
        {item.room_seq > 0 ? <><dt>Room seq</dt><dd>{item.room_seq}</dd></> : null}
        {item.activity_id ? <><dt>Activity</dt><dd>{item.activity_id}</dd></> : null}
        {item.message_id ? <><dt>Message</dt><dd>{item.message_id}</dd></> : null}
        {item.proposal_id ? <><dt>Proposal</dt><dd>{item.proposal_id}</dd></> : null}
        {item.reply_to_activity_id ? <><dt>Reply activity</dt><dd>{item.reply_to_activity_id}</dd></> : null}
        {item.reply_to_message_id ? <><dt>Reply message</dt><dd>{item.reply_to_message_id}</dd></> : null}
        {item.correlation_id ? <><dt>Correlation</dt><dd>{item.correlation_id}</dd></> : null}
        {item.causation_id ? <><dt>Causation</dt><dd>{item.causation_id}</dd></> : null}
        <dt>Causal depth</dt><dd>{item.causal_depth ?? 0}</dd>
        {item.proof_boundary ? <><dt>证据边界</dt><dd>{item.proof_boundary}</dd></> : null}
      </dl>
    </details>
  );
}

export function RoomMessage({ item, onJumpToReference, leadName = null }: { item: RoomTimelineItem; onJumpToReference: (messageId?: string | null, activityId?: string | null) => void; leadName?: string | null }) {
  const [copied, setCopied] = useState(false);
  const human = item.actor.kind === "human" || item.actor.role === "human" || item.actor.role === "user";
  const identity = item.actor.participant_id || item.actor.identity || item.actor.role;
  const chip = human ? addressingChip(item, leadName) : null;
  return (
    <article className={`room-message ${human ? "from-human" : "from-agent"} kind-${item.kind}`} data-activity-id={item.activity_id ?? undefined} data-message-id={item.id} style={identityStyle(identity)} tabIndex={-1}>
      {!human ? <span className="room-avatar room-message__avatar">{initials(item.actor.display_name)}</span> : null}
      <div className="room-message__content">
        <header><strong>{human ? "你" : item.actor.display_name}</strong>{item.kind === "handoff" ? <span className="room-kind-pill">建议转交</span> : null}{item.kind === "proposal" ? <span className="room-kind-pill">提案</span> : null}<time dateTime={item.created_at ?? undefined}>{formatRoomTime(item.created_at)}</time><button aria-label={copied ? "已复制消息" : "复制消息"} className="room-message-copy" onClick={async () => { try { await navigator.clipboard.writeText(item.content); setCopied(true); window.setTimeout(() => setCopied(false), 1400); } catch { setCopied(false); } }} type="button">{copied ? <Check size={13} /> : <Copy size={13} />}</button></header>
        {chip ? <span className="room-addressing-chip" title={item.addressing ? ADDRESSING_TITLES[item.addressing] : undefined}>{chip}</span> : null}
        {item.reply_to_message_id || item.reply_to_activity_id ? <button className="room-reply-link" onClick={() => onJumpToReference(item.reply_to_message_id, item.reply_to_activity_id)} title={`跳到上游 ${item.reply_to_message_id ?? item.reply_to_activity_id}`} type="button">回复 {item.reply_target_display_name ?? "上一条消息"}</button> : null}
        <RoomMarkdown content={item.content} />
        {item.kind === "handoff" && item.handoff_targets?.length ? <div className="room-causal-pill">转交给 {item.handoff_targets.join("、")}</div> : null}
        {item.handoff_note ? <RoomHandoffNoteCard note={item.handoff_note} /> : null}
        <RoomMessageDetails item={item} />
      </div>
    </article>
  );
}

export function RoomPendingBubble({ pending, onRetry }: { pending: RoomPendingMessage; onRetry: () => void }) {
  return (
    <article className={`room-message from-human is-${pending.status}`} data-message-id={`pending:${pending.clientRequestId}`}>
      <div className="room-message__content">
        <header><strong>你</strong><span>{pending.status === "sending" ? "发送中…" : "发送失败"}</span></header>
        <RoomMarkdown content={pending.content} />
        {pending.status === "failed" ? <div className="room-send-error" role="alert"><span>{pending.error?.message ?? "消息未发送，正文仍在这里。"}</span><button className="room-quiet-button" onClick={onRetry} type="button">使用同一请求重试</button></div> : null}
      </div>
    </article>
  );
}
