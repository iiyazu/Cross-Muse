"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Pin, PinOff, Plus, Search, X } from "lucide-react";

import { fetchRoomSetupOptions } from "@/lib/api";
import { roomStateLabel } from "@/lib/room-view";
import type { RoomSetupOptions, RoomSummary } from "@/lib/types";
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
  onTitleChange,
  pinnedRoomIds = [],
  onTogglePinned = () => undefined
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
  onCreate: (title: string, clientRequestId: string, rosterTemplateId: string) => Promise<boolean>;
  onClose: () => void;
  onQueryChange: (query: string) => void;
  onCreatingChange: (creating: boolean) => void;
  onTitleChange: (title: string) => void;
  pinnedRoomIds?: string[];
  onTogglePinned?: (roomId: string) => void;
}) {
  const [setupOptions, setSetupOptions] = useState<RoomSetupOptions | null>(null);
  const [setupError, setSetupError] = useState<string | null>(null);
  const [selectedTemplateId, setSelectedTemplateId] = useState("builtin.development");
  const createTriggerRef = useRef<HTMLButtonElement>(null);
  const wasCreatingRef = useRef(false);
  const filtered = rooms.filter((room) => room.title.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const ordered = [...filtered].sort((left, right) =>
    Number(pinnedRoomIds.includes(right.conversation_id)) - Number(pinnedRoomIds.includes(left.conversation_id))
  );

  useEffect(() => {
    if (!creating || setupOptions) return;
    const controller = new AbortController();
    void fetchRoomSetupOptions({ signal: controller.signal })
      .then((payload) => {
        setSetupOptions(payload);
        setSelectedTemplateId(payload.default_roster_template_id);
        setSetupError(null);
      })
      .catch(() => setSetupError("暂时无法读取 Room roster，仍可使用默认开发团队。"));
    return () => controller.abort();
  }, [creating, setupOptions]);

  useEffect(() => {
    if (creating) wasCreatingRef.current = true;
    else if (wasCreatingRef.current) requestAnimationFrame(() => createTriggerRef.current?.focus());
  }, [creating]);

  function handleDialogKeyDown(event: KeyboardEvent<HTMLFormElement>) {
    if (event.key === "Escape" && !createPending) {
      event.preventDefault();
      onCreatingChange(false);
      return;
    }
    if (event.key !== "Tab") return;
    const controls = [...event.currentTarget.querySelectorAll<HTMLElement>("input:not(:disabled), button:not(:disabled)")];
    const first = controls[0];
    const last = controls.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first?.focus();
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!title.trim()) return;
    const requestId = createRequestId ?? `ui_room_create_${crypto.randomUUID()}`;
    await onCreate(title, requestId, selectedTemplateId);
  }

  return (
    <aside className="room-sidebar" aria-label="房间导航">
      <div className="room-sidebar__brand">
        <div><strong>xmuse</strong><span>Agent Room</span></div>
        <button className="room-icon-button room-mobile-only" onClick={onClose} type="button" aria-label="关闭房间栏"><X size={17} /></button>
      </div>
      <div className="room-sidebar__actions">
        <button aria-controls="room-create-dialog" aria-expanded={creating} className="room-primary-button" onClick={() => onCreatingChange(!creating)} ref={createTriggerRef} type="button"><Plus size={16} />新建 Room</button>
        {creating ? (
          <div className="room-dialog-layer" id="room-create-dialog">
            <button aria-label="关闭新建 Room" className="room-dialog-scrim" disabled={createPending} onClick={() => onCreatingChange(false)} type="button" />
            <form aria-labelledby="room-create-title" aria-modal="true" className="room-create-dialog" onKeyDown={handleDialogKeyDown} onSubmit={submit} role="dialog">
              <header><div><span>New room</span><h2 id="room-create-title">创建协作 Room</h2></div><button aria-label="关闭" className="room-icon-button" disabled={createPending} onClick={() => onCreatingChange(false)} type="button"><X size={18} /></button></header>
              <label htmlFor="room-title">Room 名称</label>
              <input autoFocus id="room-title" maxLength={200} disabled={createPending} onChange={(event) => onTitleChange(event.target.value)} placeholder="例如：审视并完成发布方案" value={title} />
              <fieldset className="room-roster-options">
                <legend>参与团队</legend>
                {(setupOptions?.roster_templates ?? []).map((template) => (
                  <label className={selectedTemplateId === template.template_id ? "is-selected" : ""} key={template.template_id}>
                    <input checked={selectedTemplateId === template.template_id} name="roster" onChange={() => setSelectedTemplateId(template.template_id)} type="radio" value={template.template_id} />
                    <span><strong>{template.display_name}</strong><small>{template.description}</small><em>{template.participants.map((participant) => participant.display_name).join(" · ")}</em></span>
                  </label>
                ))}
                {!setupOptions ? <div className="room-roster-loading">{setupError ?? "正在读取 roster…"}</div> : null}
              </fieldset>
              <p className="room-create-note">所有 Agent 会独立观察 Room；角色只定义协作侧重点，不授予额外权限。</p>
              <div className="room-dialog-actions">
                <button className="room-quiet-button" disabled={createPending} onClick={() => onCreatingChange(false)} type="button">取消</button>
                <button className="room-primary-button" disabled={createPending || !title.trim()} type="submit">{createPending ? "正在创建…" : "创建 Room"}</button>
              </div>
              {createError && createRequestId ? <p className="room-create-error" role="alert">{createError.message}</p> : null}
            </form>
          </div>
        ) : null}
        <div className="room-search-wrap"><Search aria-hidden="true" size={15} /><input aria-label="搜索房间" className="room-search" onChange={(event) => onQueryChange(event.target.value)} placeholder="搜索 Room" type="search" value={query} /></div>
      </div>
      <nav className="room-list" aria-label="最近房间">
        {error && rooms.length ? <div className="room-list-warning" role="status">房间列表可能已过期：{error.message}</div> : null}
        {ordered.map((room, index) => {
          const unread = Math.max(0, room.latest_visible_room_seq - (readCursors[room.conversation_id] ?? 0));
          const draft = drafts[room.conversation_id]?.trim();
          const pinned = pinnedRoomIds.includes(room.conversation_id);
          return (
            <div className="room-list-row" key={room.conversation_id}>
            {(index === 0 || pinned !== pinnedRoomIds.includes(ordered[index - 1]?.conversation_id ?? "")) ? <span className="room-list-section">{pinned ? "Pinned" : "Recent"}</span> : null}
            <button aria-current={room.conversation_id === selectedRoomId ? "page" : undefined} className={`room-list-item ${room.conversation_id === selectedRoomId ? "is-active" : ""}`} onClick={() => onNavigate(room.conversation_id)} type="button">
              <span className="room-list-item__top"><strong>{room.title}</strong><i className={`room-state-dot state-${room.state}`} aria-label={roomStateLabel(room.state)} /></span>
              <span className="room-list-item__members"><RoomMemberStack participants={room.members} label={`${room.title} 成员`} /><small>{room.active_turn_count ? `${room.active_turn_count} 轮进行中` : formatRoomTime(room.updated_at)}</small></span>
              <span className="room-list-item__preview">{draft ? `草稿：${draft}` : roomPreview(room)}</span>
              {unread > 0 ? <span className="room-unread" aria-label={`${unread} 条未读更新`}>{unread > 99 ? "99+" : unread}</span> : null}
            </button>
            <button aria-label={pinned ? `取消置顶 ${room.title}` : `置顶 ${room.title}`} className="room-pin-button" onClick={() => onTogglePinned(room.conversation_id)} type="button">{pinned ? <PinOff size={14} /> : <Pin size={14} />}</button>
            </div>
          );
        })}
        {!filtered.length ? <div className="room-list-empty">{loading && !loaded ? "正在读取房间…" : query ? "没有匹配的房间" : "还没有房间"}</div> : null}
      </nav>
    </aside>
  );
}
