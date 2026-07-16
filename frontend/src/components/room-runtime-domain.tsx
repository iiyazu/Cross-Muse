"use client";

import { useEffect, useMemo, useRef, type KeyboardEvent } from "react";

import type {
  RoomOperationsIncident,
  RoomOperationsProjection,
  RoomRuntimeRecoverDescriptor
} from "@/lib/types";

export function runtimeStateLabel(state: string): string {
  return {
    ready: "就绪", healthy: "正常", attention: "需关注", blocked: "已阻塞",
    unknown: "未知", starting: "启动中", recovering: "自动恢复中",
    rebuilding: "正在重建索引", stopping: "停止中", stopped: "已停止",
    failed: "失败", stale: "心跳过期", invalid: "状态无效"
  }[state] ?? state;
}

export function RoomOperationIncident({
  incident,
  onAction
}: {
  incident: RoomOperationsIncident;
  onAction: (incident: RoomOperationsIncident) => void;
}) {
  const actionLabel = incident.next_action === "wait" && incident.code === "room_memory_degraded"
    ? "等待 MemoryOS 恢复"
    : {
        wait: "等待系统清理",
        open_room: "打开房间",
        retry_observation: "定位并重试",
        recover_runtime: "恢复运行时",
        rebuild_memory_index: "重建记忆索引",
        repair_then_recover: "修复后恢复"
      }[incident.next_action];
  return (
    <article className={`room-operation-incident is-${incident.severity}`} data-incident-id={incident.incident_id} tabIndex={-1}>
      <div>
        <strong>{incident.title}</strong>
        <span>{incident.detail}</span>
        <small>{incident.participant_display_name ?? incident.conversation_title ?? incident.code}</small>
      </div>
      {incident.next_action === "wait" ? (
        <small className="room-operation-next-action">{actionLabel}</small>
      ) : (
        <button className="room-quiet-button" onClick={() => onAction(incident)} type="button">{actionLabel}</button>
      )}
    </article>
  );
}

export function RoomRuntimeDomain({
  operations,
  operationsError,
  operationsLoading,
  recoverPending,
  recoverError,
  selectedRoomId,
  onIncidentAction,
  onRecover
}: {
  operations: RoomOperationsProjection | null;
  operationsError: { message: string; status: number } | null;
  operationsLoading: boolean;
  recoverPending: boolean;
  recoverError: { message: string; status: number } | null;
  selectedRoomId: string | null;
  onIncidentAction: (incident: RoomOperationsIncident) => void;
  onRecover: (descriptor: RoomRuntimeRecoverDescriptor) => void;
}) {
  const incidents = useMemo(() => {
    if (!operations) return [];
    return [...operations.incidents]
      .sort((left, right) => Number(right.conversation_id === selectedRoomId) - Number(left.conversation_id === selectedRoomId))
      .slice(0, 5);
  }, [operations, selectedRoomId]);

  return (
    <section className={`room-operations state-${operations?.overall ?? "unknown"}`} aria-label="运行与恢复" tabIndex={-1}>
      <div className="room-operations-heading">
        <h3>运行与恢复</h3>
        {operationsLoading ? <small>正在核验…</small> : null}
      </div>
      {operations ? <>
        <dl className="room-operations-components">
          <dt>Runner</dt><dd>{runtimeStateLabel(operations.runtime.runner.state)}{operations.runtime.runner.code ? ` · ${operations.runtime.runner.code}` : ""}</dd>
          <dt>Room MCP</dt><dd>{runtimeStateLabel(operations.runtime.mcp.state)}{operations.runtime.mcp.code ? ` · ${operations.runtime.mcp.code}` : ""}</dd>
          <dt>Host</dt><dd>{runtimeStateLabel(operations.runtime.host.state)}{operations.runtime.host.code ? ` · ${operations.runtime.host.code}` : ""}</dd>
          <dt>MemoryOS</dt><dd>{runtimeStateLabel(operations.runtime.memory.state)}{operations.runtime.memory.code ? ` · ${operations.runtime.memory.code}` : ""}</dd>
        </dl>
        <div className="room-operations-counts" aria-label="运行计数">
          <span><strong>{operations.counts.active_delivery}</strong>处理中</span>
          <span><strong>{operations.counts.retained_cleanup}</strong>遗留清理</span>
          <span><strong>{operations.counts.recovery_pending}</strong>恢复中</span>
          <span><strong>{operations.counts.cancel_pending}</strong>取消中</span>
          <span><strong>{operations.counts.provider_cleanup_pending}</strong>Provider 清理</span>
          <span><strong>{operations.counts.exhausted}</strong>已耗尽</span>
        </div>
        {incidents.length ? <div className="room-operations-incidents" aria-label="运行事件">
          {incidents.map((incident) => <RoomOperationIncident incident={incident} key={incident.incident_id} onAction={onIncidentAction} />)}
          {operations.incident_total > incidents.length ? <small>另有 {operations.incident_total - incidents.length} 项</small> : null}
        </div> : <p className="room-operations-empty">当前没有需要处理的运行事件。</p>}
        {operations.actions.recover_runtime.available ? <button
          className="room-danger-button room-runtime-recover-button"
          disabled={recoverPending}
          onClick={() => onRecover(operations.actions.recover_runtime)}
          type="button"
        >{recoverPending ? "正在恢复运行时…" : operations.actions.recover_runtime.mode === "start" ? "启动 Room Runtime" : "恢复 Room Runtime"}</button> : null}
      </> : <p className="room-operations-empty">尚未取得可信的运行状态。</p>}
      {operationsError ? <p className="room-operations-warning" role="status">运行状态暂不可刷新，保留上次核验结果：{operationsError.message}</p> : null}
      {recoverError ? <p className="room-operations-warning" role="alert">{recoverError.status === 409 ? "运行状态已经变化，已刷新最新状态。" : `运行时恢复未完成：${recoverError.message}`}</p> : null}
    </section>
  );
}

function GuardedConfirmationDialog({
  pending,
  onClose,
  onConfirm,
  closeLabel,
  kicker,
  title,
  description,
  pendingLabel,
  confirmLabel,
  id
}: {
  pending: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
  closeLabel: string;
  kicker: string;
  title: string;
  description: string;
  pendingLabel: string;
  confirmLabel: string;
  id: string;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => closeRef.current?.focus(), []);
  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && !pending) {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    if (event.shiftKey && document.activeElement === closeRef.current) {
      event.preventDefault();
      confirmRef.current?.focus();
    } else if (!event.shiftKey && document.activeElement === confirmRef.current) {
      event.preventDefault();
      closeRef.current?.focus();
    }
  }
  return <div className="room-dialog-layer" onKeyDown={handleKeyDown}>
    <button aria-label={closeLabel} className="room-dialog-scrim" disabled={pending} onClick={onClose} type="button" />
    <div aria-describedby={`${id}-description`} aria-labelledby={`${id}-title`} aria-modal="true" className="room-confirm-dialog" role="alertdialog">
      <span className="room-dialog-kicker">{kicker}</span>
      <h2 id={`${id}-title`}>{title}</h2>
      <p id={`${id}-description`}>{description}</p>
      <div className="room-dialog-actions">
        <button className="room-quiet-button" disabled={pending} onClick={onClose} ref={closeRef} type="button">返回</button>
        <button className="room-danger-button" disabled={pending} onClick={() => void onConfirm()} ref={confirmRef} type="button">{pending ? pendingLabel : confirmLabel}</button>
      </div>
    </div>
  </div>;
}

export function RoomRuntimeRecoverDialog({ pending, onClose, onConfirm }: {
  pending: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  return <GuardedConfirmationDialog
    closeLabel="关闭运行时恢复确认"
    confirmLabel="确认中断并恢复"
    description="这会中断当前正在进行的 Agent delivery。未完成工作将由耐久 observation attempt 在新运行时中安全恢复，不会伪造 Agent 回应。"
    id="runtime-recover"
    kicker="守卫运行时恢复"
    onClose={onClose}
    onConfirm={onConfirm}
    pending={pending}
    pendingLabel="正在恢复运行时…"
    title="确认恢复 Room Runtime？"
  />;
}

export function RoomMemoryRebuildDialog({ pending, onClose, onConfirm }: {
  pending: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  return <GuardedConfirmationDialog
    closeLabel="关闭记忆索引重建确认"
    confirmLabel="确认重建派生索引"
    description="只会删除可重建的 MemoryOS 派生缓存，并从 chat.db 重新绑定与回放。Room 消息、已审批记忆和其他耐久事实不会删除；重建期间群聊仍可继续工作。"
    id="memory-rebuild"
    kicker="MemoryOS 派生索引"
    onClose={onClose}
    onConfirm={onConfirm}
    pending={pending}
    pendingLabel="正在请求重建…"
    title="确认重建 MemoryOS 派生索引？"
  />;
}
