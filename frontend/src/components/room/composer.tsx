"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { ArrowUp } from "lucide-react";

import { Avatar, familyLabel, familyOf } from "@/components/ui/avatar";
import { cx } from "@/components/ui/cx";
import type { RoomCollaboration, RoomParticipant } from "@/lib/types";

type MentionMatch = { start: number; query: string };

export function mentionAt(value: string, caret: number): MentionMatch | null {
  const before = value.slice(0, caret);
  const match = before.match(/(^|\s)(@[\p{L}\p{N}_:.-]*)$/u);
  if (!match || match.index === undefined) return null;
  return { start: match.index + match[1].length, query: match[2].slice(1).toLocaleLowerCase() };
}

export function Composer({
  roomId,
  participants,
  collaboration,
  leadName,
  draft,
  disabled = false,
  onDraftChange,
  onSend
}: {
  roomId: string;
  participants: RoomParticipant[];
  collaboration: RoomCollaboration | null;
  leadName: string | null;
  draft: string;
  disabled?: boolean;
  onDraftChange: (draft: string) => void;
  onSend: (content: string) => Promise<unknown>;
}) {
  const addressed = collaboration?.mode === "addressed";
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composingRef = useRef(false);
  const [mention, setMention] = useState<MentionMatch | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  const candidates = useMemo(() => {
    const query = mention?.query ?? "";
    return participants
      .filter((participant) => participant.active && participant.role !== "init")
      .filter((participant) => !query || [participant.display_name, participant.role, participant.mention_handle]
        .join(" ")
        .toLocaleLowerCase()
        .includes(query))
      .slice(0, 8);
  }, [mention?.query, participants]);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(200, Math.max(24, textarea.scrollHeight))}px`;
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
    const handle = selected.mention_handle.startsWith("@") ? selected.mention_handle : `@${selected.mention_handle}`;
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
    if (event.key === "Enter" && (event.nativeEvent.isComposing || composingRef.current)) return;
    if (mention && candidates.length) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        setActiveIndex((index) => (index + step + candidates.length) % candidates.length);
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
  const hint = addressed
    ? `只有被 @ 的 Agent 会处理；不 @ 时交给 ${leadName ?? "lead"}`
    : "所有在线 Agent 都会看到；@ 只提高优先级";

  return (
    <form className="px-3 pt-1 pb-3 sm:px-5" onSubmit={submit}>
      <div
        className={cx(
          "relative rounded-lg border border-line-strong bg-canvas shadow-[0_1px_0_var(--line)]",
          "transition-[border-color,box-shadow] duration-150 focus-within:border-[color-mix(in_oklch,var(--focus)_60%,var(--line-strong))]",
          "focus-within:shadow-[0_0_0_3px_color-mix(in_oklch,var(--focus)_18%,transparent)]"
        )}
      >
        {menuOpen ? (
          <ul
            aria-label="可以 @ 的 Agent"
            className="absolute inset-x-2 bottom-full z-20 mb-2 max-h-72 overflow-y-auto rounded-lg bg-overlay p-1 shadow-overlay"
            id={`mention-options-${roomId}`}
            role="listbox"
          >
            {candidates.map((participant, index) => {
              const family = familyOf(participant.cli_kind);
              return (
                <li
                  aria-selected={index === activeIndex}
                  className={cx(
                    "flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5",
                    index === activeIndex ? "bg-selected" : "hover:bg-hover"
                  )}
                  id={`mention-${roomId}-${participant.participant_id}`}
                  key={participant.participant_id}
                  onMouseDown={(event) => {
                    event.preventDefault();
                    chooseMention(index);
                  }}
                  role="option"
                >
                  <Avatar family={family} name={participant.display_name} size="sm" />
                  <span className="min-w-0 flex-1 truncate text-sm text-fg">{participant.display_name}</span>
                  <span className="font-mono text-xs text-fg-3">{participant.mention_handle}</span>
                  {familyLabel(family) ? <span className="text-xs text-fg-3">{familyLabel(family)}</span> : null}
                </li>
              );
            })}
          </ul>
        ) : null}
        <textarea
          aria-activedescendant={menuOpen ? `mention-${roomId}-${candidates[activeIndex]?.participant_id}` : undefined}
          aria-autocomplete="list"
          aria-controls={menuOpen ? `mention-options-${roomId}` : undefined}
          aria-expanded={menuOpen}
          aria-label="发送消息"
          className="block max-h-[200px] min-h-6 w-full resize-none bg-transparent px-3.5 pt-3 text-sm leading-6 text-fg outline-none placeholder:text-fg-3 disabled:opacity-60"
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
          placeholder="给房间发消息，输入 @ 点名"
          ref={textareaRef}
          role="combobox"
          rows={1}
          value={draft}
        />
        <div className="flex items-center gap-3 px-2 pt-1 pb-2 pl-3.5">
          <span className="min-w-0 flex-1 truncate text-xs text-fg-3">{hint}</span>
          <kbd className="hidden font-sans text-[11px] text-fg-4 sm:inline">Enter 发送 · Shift+Enter 换行</kbd>
          <button
            className="inline-flex h-7 items-center gap-1 rounded-md bg-inverse px-2.5 text-ui font-medium text-on-inverse transition-opacity hover:opacity-90 disabled:opacity-30"
            disabled={disabled || !draft.trim()}
            type="submit"
          >
            <ArrowUp aria-hidden="true" className="size-3.5" />
            发送
          </button>
        </div>
      </div>
    </form>
  );
}
