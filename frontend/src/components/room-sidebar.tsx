"use client";

import type { FormEvent } from "react";

import { roomStateLabel } from "@/lib/room-view";
import type { RoomSummary } from "@/lib/types";
import { formatRoomTime, RoomMemberStack } from "./room-header";

function roomPreview(room: RoomSummary): string {
  return room.latest_visible_item?.content || room.latest_message?.content || "还没有消息";
}

export function RoomSidebar({
  rooms,
  selectedRoomId,
  readCursors,
  drafts,
  loading,
  loaded,
  error,
  createPending,
  createError,
  query,
  creating,
  title,
  createRequestId,
  onNavigate,
  onCreate,
  onClose,
  onQueryChange,
  onCreatingChange,
  onTitleChange
}: {
  rooms: RoomSummary[];
  selectedRoomId: string | null;
  readCursors: Record<string, number>;
  drafts: Record<string, string>;
  loading: boolean;
  loaded: boolean;
  error: { message: string } | null;
  createPending: boolean;
  createError: { message: string } | null;
  query: string;
  creating: boolean;
  title: string;
  createRequestId: string | null;
  onNavigate: (roomId: string) => void;
  onCreate: (title: string, clientRequestId: string) => Promise<boolean>;
  onClose: () => void;
  onQueryChange: (query: string) => void;
  onCreatingChange: (creating: boolean) => void;
  onTitleChange: (title: string) => void;
}) {
  const filtered = rooms.filter((room) => room.title.toLocaleLowerCase().includes(query.toLocaleLowerCase()));

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    const requestId = createRequestId ?? `ui_room_create_${crypto.randomUUID()}`;
    await onCreate(title, requestId);
  }

  return (
    <aside className="room-sidebar" aria-label="房间导航">
      <div className="room-sidebar__brand">
        <div><strong>xmuse</strong><span>Agent Room</span></div>
        <button className="room-icon-button room-mobile-only" onClick={onClose} type="button" aria-label="关闭房间栏">×</button>
      </div>
      <div className="room-sidebar__actions">
        <button aria-controls="room-create-form" aria-expanded={creating} className="room-primary-button" onClick={() => onCreatingChange(!creating)} type="button">新建房间</button>
        {creating ? (
          <form className="room-create-form" id="room-create-form" onSubmit={submit}>
            <label htmlFor="room-title">房间名称</label>
            <input autoFocus id="room-title" maxLength={120} disabled={createPending} onChange={(event) => onTitleChange(event.target.value)} placeholder="例如：完成群聊闭环" value={title} />
            <div>
              <button className="room-quiet-button" disabled={createPending} onClick={() => onCreatingChange(false)} type="button">取消</button>
              <button className="room-primary-button" disabled={createPending || !title.trim()} type="submit">{createPending ? "正在创建…" : "创建"}</button>
            </div>
            {createError && createRequestId ? <p className="room-create-error" role="alert">{createError.message}</p> : null}
          </form>
        ) : null}
        <input aria-label="搜索房间" className="room-search" onChange={(event) => onQueryChange(event.target.value)} placeholder="搜索房间" type="search" value={query} />
      </div>
      <nav className="room-list" aria-label="最近房间">
        {error && rooms.length ? <div className="room-list-warning" role="status">房间列表可能已过期：{error.message}</div> : null}
        {filtered.map((room) => {
          const unread = Math.max(0, room.latest_visible_room_seq - (readCursors[room.conversation_id] ?? 0));
          const draft = drafts[room.conversation_id]?.trim();
          return (
            <button aria-current={room.conversation_id === selectedRoomId ? "page" : undefined} className={`room-list-item ${room.conversation_id === selectedRoomId ? "is-active" : ""}`} key={room.conversation_id} onClick={() => onNavigate(room.conversation_id)} type="button">
              <span className="room-list-item__top"><strong>{room.title}</strong><i className={`room-state-dot state-${room.state}`} aria-label={roomStateLabel(room.state)} /></span>
              <span className="room-list-item__members"><RoomMemberStack participants={room.members} label={`${room.title} 成员`} /><small>{room.active_turn_count ? `${room.active_turn_count} 轮进行中` : formatRoomTime(room.updated_at)}</small></span>
              <span className="room-list-item__preview">{draft ? `草稿：${draft}` : roomPreview(room)}</span>
              {unread > 0 ? <span className="room-unread" aria-label="有未读更新">新</span> : null}
            </button>
          );
        })}
        {!filtered.length ? <div className="room-list-empty">{loading && !loaded ? "正在读取房间…" : query ? "没有匹配的房间" : "还没有房间"}</div> : null}
      </nav>
    </aside>
  );
}
