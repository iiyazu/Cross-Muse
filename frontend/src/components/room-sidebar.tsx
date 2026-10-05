"use client";

import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Pin, PinOff, Plus, Search, X } from "lucide-react";

import { fetchRoomSetupOptions } from "@/lib/api";
import { roomStateLabel } from "@/lib/room-view";
import type {
  RoomCollaborationInit,
  RoomCollaborationMode,
  RoomSetupOptions,
  RoomSummary
} from "@/lib/types";
import { formatRoomTime, ProviderBadge, RoomMemberStack } from "./room-header";

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
  onCreate: (
    title: string,
    clientRequestId: string,
    rosterTemplateId: string,
    collaboration: RoomCollaborationInit
  ) => Promise<boolean>;
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
  const [collaborationMode, setCollaborationMode] = useState<RoomCollaborationMode>("broadcast");
  const [leadRole, setLeadRole] = useState<string | null>(null);
  const [reviewEnabled, setReviewEnabled] = useState(false);
  const reviewAvailable = (setupOptions?.review_policies ?? []).includes("cross_family");
  const createTriggerRef = useRef<HTMLButtonElement>(null);
  const wasCreatingRef = useRef(false);
  const filtered = rooms.filter((room) => room.title.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const ordered = [...filtered].sort((left, right) =>
    Number(pinnedRoomIds.includes(right.conversation_id)) - Number(pinnedRoomIds.includes(left.conversation_id))
  );
  const selectedTemplate = setupOptions?.roster_templates.find(
    (template) => template.template_id === selectedTemplateId
  ) ?? null;
  const leadCandidates = useMemo(() => {
    const seen = new Set<string>();
    return (selectedTemplate?.participants ?? []).flatMap((participant) => {
      if (!participant.role || seen.has(participant.role)) return [];
      seen.add(participant.role);
      return [{ role: participant.role, display_name: participant.display_name }];
    });
  }, [selectedTemplate]);
  const effectiveLeadRole = leadRole && leadCandidates.some((candidate) => candidate.role === leadRole)
    ? leadRole
    : leadCandidates[0]?.role ?? "";

  function applyTemplatePreset(template: RoomSetupOptions["roster_templates"][number] | null) {
    const preset = template?.collaboration ?? null;
    setCollaborationMode(preset?.mode === "addressed" ? "addressed" : "broadcast");
    setLeadRole(preset?.lead_role ?? null);
  }

  useEffect(() => {
    if (!creating || setupOptions) return;
    const controller = new AbortController();
    void fetchRoomSetupOptions({ signal: controller.signal })
      .then((payload) => {
        setSetupOptions(payload);
        setSelectedTemplateId(payload.default_roster_template_id);
        applyTemplatePreset(
          payload.roster_templates.find(
            (template) => template.template_id === payload.default_roster_template_id
          ) ?? null
        );
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
    const controls = [...event.currentTarget.querySelectorAll<HTMLElement>("input:not(:disabled), select:not(:disabled), button:not(:disabled)")];
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
    const collaboration: RoomCollaborationInit = collaborationMode === "addressed"
      ? {
          mode: "addressed",
          lead_role: effectiveLeadRole || null,
          ...(reviewAvailable && reviewEnabled ? { review_policy: "cross_family" as const } : {})
        }
      : {
          mode: "broadcast",
          ...(reviewAvailable && reviewEnabled ? { review_policy: "cross_family" as const } : {})
        };
    await onCreate(title, requestId, selectedTemplateId, collaboration);
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
                {(setupOptions?.roster_templates ?? []).map((template) => {
                  const unavailable = template.available === false;
                  const missingProviders = template.unavailable_providers ?? [];
                  return (
                    <label className={[selectedTemplateId === template.template_id ? "is-selected" : "", unavailable ? "is-unavailable" : ""].join(" ").trim()} key={template.template_id}>
                      <input checked={selectedTemplateId === template.template_id} disabled={createPending || unavailable} name="roster" onChange={() => { setSelectedTemplateId(template.template_id); applyTemplatePreset(template); }} type="radio" value={template.template_id} />
                      <span>
                        <strong>{template.display_name}</strong>
                        <small>{template.description}</small>
                        {unavailable ? (
                          <small className="room-roster-unavailable">不可用：缺少 {missingProviders.join("、") || "所需 provider"}</small>
                        ) : null}
                        <em className="room-roster-participants">
                          {template.participants.map((participant) => (
                            <span className="room-roster-participant" key={`${participant.role_id}:${participant.role}`}>
                              {participant.display_name}
                              <ProviderBadge cliKind={participant.cli_kind} />
                            </span>
                          ))}
                        </em>
                      </span>
                    </label>
                  );
                })}
                {!setupOptions ? <div className="room-roster-loading">{setupError ?? "正在读取 roster…"}</div> : null}
              </fieldset>
              <fieldset className="room-collaboration-options">
                <legend>协作模式</legend>
                <label className={collaborationMode === "broadcast" ? "is-selected" : ""}>
                  <input checked={collaborationMode === "broadcast"} disabled={createPending} name="collaboration-mode" onChange={() => setCollaborationMode("broadcast")} type="radio" value="broadcast" />
                  <span><strong>Broadcast</strong><small>所有活跃 Agent 都会观察 Room 事件</small></span>
                </label>
                <label className={collaborationMode === "addressed" ? "is-selected" : ""}>
                  <input checked={collaborationMode === "addressed"} disabled={createPending} name="collaboration-mode" onChange={() => setCollaborationMode("addressed")} type="radio" value="addressed" />
                  <span><strong>Addressed</strong><small>仅 @ 提及的 Agent 观察；未提及时发给 lead</small></span>
                </label>
                {collaborationMode === "addressed" ? (
                  <label className="room-lead-select">
                    <span>Lead（未提及时的默认接收者）</span>
                    <select
                      aria-label="Room lead"
                      disabled={createPending || !leadCandidates.length}
                      onChange={(event) => setLeadRole(event.target.value)}
                      value={effectiveLeadRole}
                    >
                      {leadCandidates.map((candidate) => (
                        <option key={candidate.role} value={candidate.role}>{candidate.display_name}（{candidate.role}）</option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </fieldset>
              {reviewAvailable ? (
                <label className="room-review-toggle">
                  <input
                    checked={reviewEnabled}
                    disabled={createPending}
                    onChange={(event) => setReviewEnabled(event.target.checked)}
                    type="checkbox"
                  />
                  <span>
                    <strong>跨模型族复核</strong>
                    <small>验证通过后，由不同模型族复核补丁；关闭则与今日行为一致</small>
                  </span>
                </label>
              ) : null}
              <p className="room-create-note">
                {collaborationMode === "addressed"
                  ? "仅被 @ 提及的 Agent（或未提及时的 lead）会观察本次消息；该策略在 Room 内持久生效。"
                  : "所有 Agent 会独立观察 Room；角色只定义协作侧重点，不授予额外权限。"}
              </p>
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
