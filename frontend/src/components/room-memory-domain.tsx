"use client";

import { useEffect, useRef, useState } from "react";

import type {
  RoomMemoryCandidate,
  RoomMemoryRebuildDescriptor,
  RoomMemoryResolveDescriptor
} from "@/lib/types";
import type { RoomMemoryCache } from "@/store/domain";
import { formatRoomTime as formatTime } from "./room-header";
import { runtimeStateLabel } from "./room-runtime-domain";

type MemoryConfirmation = {
  candidate: RoomMemoryCandidate;
  decision: "approve" | "reject";
};

export function RoomMemoryDomain({
  cache,
  actionPending,
  actionError,
  rebuildDescriptor,
  rebuildPending,
  rebuildError,
  onResolve,
  onRebuild
}: {
  cache: RoomMemoryCache | null;
  actionPending: boolean;
  actionError: { message: string; status: number } | null;
  rebuildDescriptor: RoomMemoryRebuildDescriptor | null;
  rebuildPending: boolean;
  rebuildError: { message: string; status: number } | null;
  onResolve: (
    candidateId: string,
    decision: "approve" | "reject",
    descriptor: RoomMemoryResolveDescriptor
  ) => Promise<boolean>;
  onRebuild: (descriptor: RoomMemoryRebuildDescriptor) => void;
}) {
  const [confirmation, setConfirmation] = useState<MemoryConfirmation | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const projection = cache?.projection ?? null;

  useEffect(() => {
    if (confirmation) closeRef.current?.focus();
  }, [confirmation]);

  function requestConfirmation(
    candidate: RoomMemoryCandidate,
    decision: "approve" | "reject"
  ) {
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setConfirmation({ candidate, decision });
  }

  function closeConfirmation() {
    setConfirmation(null);
    requestAnimationFrame(() => returnFocusRef.current?.focus());
  }

  async function confirm() {
    if (!confirmation) return;
    await onResolve(
      confirmation.candidate.candidate_id,
      confirmation.decision,
      confirmation.candidate.actions.resolve
    );
    closeConfirmation();
  }

  return (
    <section
      className={`room-memory ${projection?.degraded ? "state-degraded" : ""}`}
      aria-label="长期记忆"
    >
      <div className="room-memory-heading">
        <h3>长期记忆</h3>
        {cache?.loading ? <small>正在核验…</small> : (
          <small>{projection?.enabled ? runtimeStateLabel(projection.runtime.state) : "未启用"}</small>
        )}
      </div>
      {projection ? (
        <>
          <div className="room-memory-summary" aria-label="记忆同步状态">
            <span><strong>{projection.sync.backlog}</strong>待同步（档案）</span>
            {projection.sync.messages ? (
              <span><strong>{projection.sync.messages.backlog}</strong>消息待同步</span>
            ) : null}
            <span><strong>{projection.recent_recalls.length}</strong>最近召回</span>
            <span><strong>{projection.pending_candidate_total}</strong>待审批</span>
          </div>
          {projection.profile || projection.capabilities ? (
            <div className="room-memory-summary" aria-label="MemoryOS 能力证明">
              {projection.profile ? (
                <span>
                  <strong>{projection.profile === "full-local" ? "Full-local" : "Archive-only"}</strong>
                  运行模式
                </span>
              ) : null}
              {projection.capabilities ? (
                <span>
                  <strong>{projection.capabilities.hybrid ? "Hybrid 就绪" : "Hybrid 不可用"}</strong>
                  检索能力
                </span>
              ) : null}
              {projection.capabilities?.message_ingest ? (
                <span><strong>消息接入就绪</strong>消息链路</span>
              ) : null}
            </div>
          ) : null}
          <div className="room-memory-summary" aria-label="MemoryOS 运行健康">
            <span><strong>{projection.runtime.consecutive_restart_count}</strong>连续重启</span>
            <span>
              <strong>{projection.runtime.last_healthy_at ? formatTime(projection.runtime.last_healthy_at) : "未记录"}</strong>
              最近健康
            </span>
          </div>
          {projection.degraded ? (
            <p className="room-operations-warning" role="status">
              MemoryOS 当前降级（{projection.runtime.code ?? projection.runtime.state}）；Room 因果上下文仍可正常工作。
            </p>
          ) : null}
          {rebuildDescriptor?.pending ? (
            <p className="room-memory-progress" role="status">
              派生索引操作进行中 · {rebuildDescriptor.phase ?? rebuildDescriptor.status ?? "requested"}
            </p>
          ) : null}
          {rebuildDescriptor?.available ? (
            <button
              className="room-danger-button room-memory-rebuild-button"
              disabled={rebuildPending || rebuildDescriptor.pending}
              onClick={() => onRebuild(rebuildDescriptor)}
              type="button"
            >
              {rebuildPending ? "正在请求重建…" : "重建 MemoryOS 派生索引"}
            </button>
          ) : null}
          {projection.recent_recalls.length ? (
            <div className="room-memory-recalls" aria-label="最近记忆召回来源">
              <strong>最近召回证据</strong>
              {projection.recent_recalls.map((recall, index) => (
                <article key={recall.receipt_id ?? `${recall.created_at ?? "recall"}:${index}`}>
                  <div>
                    <span>{recall.participant_id ?? "Room Agent"}</span>
                    <small>{recall.status}{recall.created_at ? ` · ${formatTime(recall.created_at)}` : ""}</small>
                  </div>
                  {recall.source_refs?.length ? (
                    <div className="room-memory-source-refs">
                      {recall.source_refs.map((source) => (
                        <code key={`${recall.receipt_id}:${source.activity_id}`} title={source.content_sha256 ?? undefined}>
                          {source.activity_id}
                        </code>
                      ))}
                    </div>
                  ) : <small>本次没有可回查的历史来源。</small>}
                </article>
              ))}
            </div>
          ) : <p className="room-operations-empty">当前房间还没有长期记忆召回证据。</p>}
          {projection.pending_candidates.length ? (
            <div className="room-memory-candidates" aria-label="待审批核心记忆">
              <strong>待审批核心记忆</strong>
              {projection.pending_candidates.map((candidate) => {
                const pending = actionPending;
                return (
                  <article key={candidate.candidate_id}>
                    <header>
                      <span>{memoryKindLabel(candidate.kind)}</span>
                      <small>{candidate.target_scope} · revision {candidate.revision}</small>
                    </header>
                    <p>{candidate.content}</p>
                    {candidate.source_activity_ids.length ? (
                      <small>来源 {candidate.source_activity_ids.join("、")}</small>
                    ) : null}
                    <div className="room-memory-actions">
                      <button
                        className="room-primary-button"
                        disabled={pending || !candidate.actions.resolve.available}
                        onClick={() => requestConfirmation(candidate, "approve")}
                        type="button"
                      >批准</button>
                      <button
                        className="room-danger-button"
                        disabled={pending || !candidate.actions.resolve.available}
                        onClick={() => requestConfirmation(candidate, "reject")}
                        type="button"
                      >拒绝</button>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : <p className="room-operations-empty">没有待审批的跨房间记忆。</p>}
        </>
      ) : <p className="room-operations-empty">尚未取得当前房间的记忆状态。</p>}
      {cache?.error ? (
        <p className="room-operations-warning" role="status">
          记忆状态暂不可刷新，保留 Room 消息与上次证据：{cache.error.message}
        </p>
      ) : null}
      {actionError ? (
        <p className="room-operations-warning" role="alert">
          {actionError.status === 409 || actionError.status === 404
            ? "记忆候选已经变化，已刷新最新证据。"
            : `记忆审批未完成：${actionError.message}`}
        </p>
      ) : null}
      {rebuildError ? (
        <p className="room-operations-warning" role="alert">
          {rebuildError.status === 409
            ? "MemoryOS 状态已经变化，已刷新最新状态。"
            : `派生索引重建未完成：${rebuildError.message}`}
        </p>
      ) : null}
      {confirmation ? (
        <div className="room-memory-confirm" role="alertdialog" aria-modal="true" aria-label="确认记忆审批">
          <p>
            {confirmation.decision === "approve"
              ? "批准后，这条带来源的记忆可按其作用域用于后续召回。"
              : "拒绝后，这条候选不会进入长期记忆索引。"}
          </p>
          <div className="room-dialog-actions">
            <button className="room-quiet-button" disabled={actionPending} onClick={closeConfirmation} ref={closeRef} type="button">返回</button>
            <button
              className={confirmation.decision === "reject" ? "room-danger-button" : "room-primary-button"}
              disabled={actionPending}
              onClick={() => void confirm()}
              type="button"
            >{actionPending ? "正在提交…" : "确认"}</button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
function memoryKindLabel(kind: RoomMemoryCandidate["kind"]): string {
  return {
    room_fact: "房间事实",
    room_decision: "房间决策",
    user_preference: "用户偏好",
    project_rule: "项目规则"
  }[kind];
}
