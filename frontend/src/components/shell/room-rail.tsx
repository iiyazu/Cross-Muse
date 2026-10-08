"use client";

import { memo, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { Monitor, Moon, Plus, Search, Sun } from "lucide-react";

import { formatAge } from "@/components/room/format";
import { IconButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import type { RoomSummary } from "@/lib/types";
import type { ThemePreference } from "@/store/room-persistence";
import { useRoomStore } from "@/store/room-store";

function preview(room: RoomSummary): string {
  const content = room.latest_visible_item?.content || room.latest_message?.content || "";
  return content.replace(/\s+/g, " ").trim() || "还没有消息";
}

const RoomRow = memo(function RoomRow({
  room,
  selected,
  unread,
  onSelect
}: {
  room: RoomSummary;
  selected: boolean;
  unread: boolean;
  onSelect: (roomId: string) => void;
}) {
  const attention = room.attention_turn_count > 0;
  const active = !attention && room.active_turn_count > 0;
  return (
    <li>
      <a
        aria-current={selected ? "page" : undefined}
        className={cx(
          "group flex flex-col gap-0.5 rounded-md px-2.5 py-2 outline-none",
          selected ? "bg-selected" : "hover:bg-hover"
        )}
        href={`/rooms/${encodeURIComponent(room.conversation_id)}`}
        onClick={(event) => {
          if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
          event.preventDefault();
          onSelect(room.conversation_id);
        }}
      >
        <span className="flex items-center gap-2">
          <span className={cx("min-w-0 flex-1 truncate text-sm", unread || selected ? "font-semibold text-fg" : "font-medium text-fg-2")}>
            {room.title || "未命名房间"}
          </span>
          <span className="shrink-0 text-[11px] text-fg-3">{formatAge(room.updated_at ?? room.latest_message?.created_at)}</span>
        </span>
        <span className="flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-xs text-fg-3">{preview(room)}</span>
          {attention ? (
            <span className="flex shrink-0 items-center gap-1 text-[11px] font-medium text-attn">
              <span aria-hidden="true" className="size-1.5 rounded-full bg-attn-solid" />
              需要关注
            </span>
          ) : active ? (
            <span className="flex shrink-0 items-center gap-1 text-[11px] text-live">
              <span aria-hidden="true" className="size-1.5 animate-pulse-soft rounded-full bg-live-solid" />
              进行中
            </span>
          ) : unread ? (
            <span className="size-1.5 shrink-0 rounded-full bg-inverse"><span className="sr-only">有未读消息</span></span>
          ) : null}
        </span>
      </a>
    </li>
  );
});

const THEME_OPTIONS: Array<{ value: ThemePreference; label: string; icon: typeof Sun }> = [
  { value: "system", label: "跟随系统", icon: Monitor },
  { value: "light", label: "浅色", icon: Sun },
  { value: "dark", label: "深色", icon: Moon }
];

function ThemeSwitch() {
  const theme = useRoomStore((state) => state.theme);
  const setTheme = useRoomStore((state) => state.setTheme);
  return (
    <div aria-label="主题" className="inline-flex rounded-md border border-line p-0.5" role="radiogroup">
      {THEME_OPTIONS.map((option) => {
        const Icon = option.icon;
        const checked = theme === option.value;
        return (
          <button
            aria-checked={checked}
            aria-label={option.label}
            className={cx(
              "inline-flex size-6 items-center justify-center rounded-sm transition-colors",
              checked ? "bg-selected text-fg" : "text-fg-3 hover:text-fg"
            )}
            key={option.value}
            onClick={() => setTheme(option.value)}
            role="radio"
            title={option.label}
            type="button"
          >
            <Icon aria-hidden="true" className="size-3.5" />
          </button>
        );
      })}
    </div>
  );
}

export function RoomRail({
  onNavigate,
  onCreate
}: {
  onNavigate: (roomId: string) => void;
  onCreate: () => void;
}) {
  const { rooms, selectedRoomId, readCursors, roomsLoaded, roomsError } = useRoomStore(useShallow((state) => ({
    rooms: state.rooms,
    selectedRoomId: state.selectedRoomId,
    readCursors: state.readCursors,
    roomsLoaded: state.roomsLoaded,
    roomsError: state.roomsError
  })));
  const [query, setQuery] = useState("");
  const filtered = query
    ? rooms.filter((room) => room.title.toLocaleLowerCase().includes(query.toLocaleLowerCase()))
    : rooms;

  return (
    <nav aria-label="房间" className="flex h-full min-h-0 flex-col bg-sunken">
      <div className="flex h-12 shrink-0 items-center gap-2 px-3">
        <span className="flex items-center gap-2 pl-1">
          <svg aria-hidden="true" className="size-4 text-fg" viewBox="0 0 16 16">
            <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeLinecap="round" strokeWidth="2.2" />
            <circle cx="13" cy="13" fill="var(--proof-solid)" r="2.4" />
          </svg>
          <span className="text-sm font-semibold tracking-tight text-fg">xmuse</span>
        </span>
        <span className="flex-1" />
        <IconButton label="新建房间" onClick={onCreate} size="sm">
          <Plus aria-hidden="true" className="size-4" />
        </IconButton>
      </div>
      {rooms.length > 6 ? (
        <div className="px-3 pb-2">
          <label className="flex h-7 items-center gap-2 rounded-md border border-line bg-canvas px-2 text-ui focus-within:border-line-strong">
            <Search aria-hidden="true" className="size-3.5 text-fg-3" />
            <input
              aria-label="搜索房间"
              className="min-w-0 flex-1 bg-transparent text-fg outline-none placeholder:text-fg-3"
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索房间"
              value={query}
            />
          </label>
        </div>
      ) : null}
      <div className="scrollbar-quiet min-h-0 flex-1 overflow-y-auto px-1.5 pb-2">
        {roomsError && !rooms.length ? (
          <p className="m-0 px-2.5 py-2 text-ui text-fail" role="alert">房间列表暂时读不到，正在重试。</p>
        ) : null}
        {roomsLoaded && !rooms.length && !roomsError ? (
          <p className="m-0 px-2.5 py-2 text-ui text-fg-3">还没有房间。</p>
        ) : null}
        <ul className="m-0 flex list-none flex-col gap-px p-0">
          {filtered.map((room) => (
            <RoomRow
              key={room.conversation_id}
              onSelect={onNavigate}
              room={room}
              selected={room.conversation_id === selectedRoomId}
              unread={(readCursors[room.conversation_id] ?? 0) < room.latest_visible_room_seq && room.conversation_id !== selectedRoomId}
            />
          ))}
        </ul>
      </div>
      <div className="flex h-11 shrink-0 items-center justify-between border-t border-line px-3">
        <span className="text-[11px] text-fg-3">仅本机 · 单用户</span>
        <ThemeSwitch />
      </div>
    </nav>
  );
}
