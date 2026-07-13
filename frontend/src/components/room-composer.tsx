"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";

import type { RoomParticipant } from "@/lib/types";

type MentionMatch = {
  start: number;
  query: string;
};

type RoomComposerProps = {
  roomId: string;
  participants: RoomParticipant[];
  draft: string;
  disabled?: boolean;
  onDraftChange: (draft: string) => void;
  onSend: (content: string) => Promise<unknown>;
};

function mentionAt(value: string, caret: number): MentionMatch | null {
  const before = value.slice(0, caret);
  const match = before.match(/(^|\s)(@[\p{L}\p{N}_:.-]*)$/u);
  if (!match || match.index === undefined) return null;
  const token = match[2];
  return {
    start: match.index + match[1].length,
    query: token.slice(1).toLocaleLowerCase()
  };
}

export function RoomComposer({
  roomId,
  participants,
  draft,
  disabled = false,
  onDraftChange,
  onSend
}: RoomComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composingRef = useRef(false);
  const [mention, setMention] = useState<MentionMatch | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  const candidates = useMemo(() => {
    const query = mention?.query ?? "";
    return participants
      .filter((participant) => participant.active && participant.role !== "init")
      .filter((participant) => {
        if (!query) return true;
        return [participant.display_name, participant.role, participant.mention_handle]
          .join(" ")
          .toLocaleLowerCase()
          .includes(query);
      })
      .slice(0, 8);
  }, [mention?.query, participants]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(160, Math.max(48, textarea.scrollHeight))}px`;
  }, [draft]);

  function updateMention(value: string, caret: number) {
    setMention(mentionAt(value, caret));
    setActiveIndex(0);
  }

  function chooseMention(index: number) {
    const selected = candidates[index];
    const textarea = textareaRef.current;
    if (!selected || !mention || !textarea) return;
    const caret = textarea.selectionStart;
    const handle = selected.mention_handle.startsWith("@")
      ? selected.mention_handle
      : `@${selected.mention_handle}`;
    const next = `${draft.slice(0, mention.start)}${handle} ${draft.slice(caret)}`;
    const nextCaret = mention.start + handle.length + 1;
    onDraftChange(next);
    setMention(null);
    requestAnimationFrame(() => {
      textarea.focus();
      textarea.setSelectionRange(nextCaret, nextCaret);
    });
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    const snapshot = draft.trim();
    if (!snapshot || disabled) return;
    setMention(null);
    onDraftChange("");
    await onSend(snapshot);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (
      event.key === "Enter" &&
      (event.nativeEvent.isComposing || composingRef.current)
    ) {
      return;
    }
    if (mention && candidates.length) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setActiveIndex((index) => (index + 1) % candidates.length);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setActiveIndex((index) => (index - 1 + candidates.length) % candidates.length);
        return;
      }
      if (event.key === "Tab" || event.key === "Enter") {
        event.preventDefault();
        chooseMention(activeIndex);
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setMention(null);
        return;
      }
    }
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void submit();
    }
  }

  const menuOpen = Boolean(mention && candidates.length);
  return (
    <form className="room-composer" onSubmit={submit}>
      <div className="room-composer__field">
        {menuOpen ? (
          <ul className="mention-menu" id="room-mention-options" role="listbox" aria-label="可提及的 Agent">
            {candidates.map((participant, index) => (
              <li
                aria-selected={index === activeIndex}
                className={index === activeIndex ? "is-active" : ""}
                id={`mention-${participant.participant_id}`}
                key={participant.participant_id}
                onMouseDown={(event) => {
                  event.preventDefault();
                  chooseMention(index);
                }}
                role="option"
              >
                <span className="room-avatar" data-agent={participant.participant_id} aria-hidden="true">
                  {participant.display_name.slice(0, 1).toUpperCase()}
                </span>
                <span>
                  <strong>{participant.display_name}</strong>
                  <small>{participant.mention_handle} · 仅提高关注优先级</small>
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        <textarea
          aria-activedescendant={menuOpen ? `mention-${candidates[activeIndex]?.participant_id}` : undefined}
          aria-autocomplete="list"
          aria-controls={menuOpen ? "room-mention-options" : undefined}
          aria-expanded={menuOpen}
          aria-label="发送消息"
          data-room-id={roomId}
          disabled={disabled}
          onChange={(event) => {
            onDraftChange(event.target.value);
            updateMention(event.target.value, event.target.selectionStart);
          }}
          onClick={(event) => updateMention(event.currentTarget.value, event.currentTarget.selectionStart)}
          onCompositionEnd={(event) => {
            composingRef.current = false;
            updateMention(event.currentTarget.value, event.currentTarget.selectionStart);
          }}
          onCompositionStart={() => {
            composingRef.current = true;
          }}
          onKeyDown={handleKeyDown}
          placeholder="在房间里说点什么，输入 @ 提高某位 Agent 的关注优先级…"
          ref={textareaRef}
          role="combobox"
          rows={1}
          value={draft}
        />
      </div>
      <div className="room-composer__footer">
        <span>房间内当前活跃 Agent 都会观察，@ 只提高关注优先级</span>
        <button className="room-primary-button" disabled={disabled || !draft.trim()} type="submit">
          发送
        </button>
      </div>
    </form>
  );
}
