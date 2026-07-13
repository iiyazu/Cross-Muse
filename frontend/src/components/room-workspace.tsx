"use client";

import {
  Fragment,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode
} from "react";

import {
  roomParticipantStateLabel,
  roomStateLabel
} from "@/lib/room-view";
import type {
  RoomParticipant,
  RoomControlActionDescriptor,
  RoomExecutionCancelDescriptor,
  RoomExecutionDecisionDescriptor,
  RoomExecutionPolicyMode,
  RoomExecutionPolicyUpdateDescriptor,
  RoomMemoryCandidate,
  RoomMemoryRebuildDescriptor,
  RoomMemoryResolveDescriptor,
  RoomObservationFrontier,
  RoomObservationBatchEvidence,
  RoomOperationsIncident,
  RoomOperationsProjection,
  RoomRuntimeRecoverDescriptor,
  RoomSkillDecision,
  RoomSummary,
  RoomTimelineItem,
  RoomTurn,
  RoomTurnParticipant
} from "@/lib/types";
import {
  useRoomStore,
  type RoomCache,
  type RoomExecutionCache,
  type RoomMemoryCache
} from "@/store/room-store";
import { RoomComposer } from "./room-composer";
import {
  formatRoomTime as formatTime,
  identityStyle,
  initials,
  RoomHeader
} from "./room-header";
import { RoomMessage, RoomPendingBubble } from "./room-message";
import { RoomInspector as RoomInspectorShell } from "./room-inspector";
import { RoomSidebar } from "./room-sidebar";
import { RoomTurnStatus, type RoomCancelTarget } from "./room-turn-status";
import { AgentConsole } from "./agent-console";

type RoomWorkspaceProps = {
  onNavigateRoom: (roomId: string) => void;
  onCreatedRoom: (roomId: string) => void;
};

type CancelTarget = RoomCancelTarget;

function CancelObservationDialog({
  target,
  pending,
  onClose,
  onConfirm
}: {
  target: CancelTarget;
  pending: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

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

  return (
    <div className="room-dialog-layer" onKeyDown={handleKeyDown}>
      <button className="room-dialog-scrim" disabled={pending} onClick={onClose} type="button" aria-label="关闭取消确认" />
      <div
        aria-describedby="cancel-observation-description"
        aria-labelledby="cancel-observation-title"
        aria-modal="true"
        className="room-confirm-dialog"
        role="alertdialog"
      >
        <span className="room-dialog-kicker">单 Agent 控制</span>
        <h2 id="cancel-observation-title">取消 {target.participant.display_name} 的当前处理？</h2>
        <p id="cancel-observation-description">
          这只会终止该 Agent 当前 observation 的 delivery。其他 Agent 和后续房间活动不受影响；取消完成后需显式重试才能重新开放。
        </p>
        <div className="room-dialog-actions">
          <button className="room-quiet-button" disabled={pending} onClick={onClose} ref={closeRef} type="button">返回</button>
          <button className="room-danger-button" disabled={pending} onClick={() => void onConfirm()} ref={confirmRef} type="button">
            {pending ? "正在请求取消…" : "确认取消当前处理"}
          </button>
        </div>
      </div>
    </div>
  );
}

type TimelineAnchorSnapshot = { messageId: string; offset: number };

export function captureTimelineAnchor(container: HTMLElement): TimelineAnchorSnapshot | null {
  const top = container.getBoundingClientRect().top;
  const node = [...container.querySelectorAll<HTMLElement>("[data-message-id]")].find(
    (candidate) => candidate.getBoundingClientRect().bottom >= top
  );
  if (!node?.dataset.messageId) return null;
  return {
    messageId: node.dataset.messageId,
    offset: node.getBoundingClientRect().top - top
  };
}

export function restoreTimelineAnchor(
  container: HTMLElement,
  anchor: TimelineAnchorSnapshot | null
) {
  if (!anchor) return;
  const node = [...container.querySelectorAll<HTMLElement>("[data-message-id]")].find(
    (candidate) => candidate.dataset.messageId === anchor.messageId
  );
  if (node) container.scrollTop = node.offsetTop - anchor.offset;
}

export function snapTimelineToBottom(container: HTMLElement) {
  const scrollBehavior = container.style.scrollBehavior;
  container.style.scrollBehavior = "auto";
  container.scrollTop = container.scrollHeight;
  container.style.scrollBehavior = scrollBehavior;
}

export function shouldInitializeTimeline(
  initializedRoomId: string | null,
  roomId: string,
  loading: boolean
) {
  return !loading && initializedRoomId !== roomId;
}

function RoomTimeline({ roomId, cache }: { roomId: string; cache: RoomCache }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const initializedRoomRef = useRef<string | null>(null);
  const wasAtBottomRef = useRef(true);
  const previousCountRef = useRef(0);
  const historyLoadRef = useRef(false);
  const [newCount, setNewCount] = useState(0);
  const markRead = useRoomStore((state) => state.markRead);
  const saveScrollAnchor = useRoomStore((state) => state.saveScrollAnchor);
  const anchor = useRoomStore((state) => state.scrollAnchors[roomId]);
  const loadOlder = useRoomStore((state) => state.loadOlder);
  const retryMessage = useRoomStore((state) => state.retryMessage);

  const visibleSeq = cache.projection?.latest_visible_room_seq ?? cache.timelineItems.at(-1)?.room_seq ?? 0;

  useEffect(() => {
    const container = containerRef.current;
    if (
      !container ||
      !shouldInitializeTimeline(initializedRoomRef.current, roomId, cache.loading)
    ) return;
    initializedRoomRef.current = roomId;
    const saved = anchor
      ? [...container.querySelectorAll<HTMLElement>("[data-message-id]")].find(
          (node) => node.dataset.messageId === anchor.messageId
        ) ?? null
      : null;
    if (saved) container.scrollTop = saved.offsetTop - anchor!.offset;
    else container.scrollTop = container.scrollHeight;
    wasAtBottomRef.current = container.scrollHeight - container.scrollTop - container.clientHeight <= 120;
    previousCountRef.current = cache.timelineItems.length + cache.pendingMessages.length;
    if (wasAtBottomRef.current && visibleSeq) markRead(roomId, visibleSeq);
    // Restore only when entering a room, not on every incremental page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, cache.loading]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const count = cache.timelineItems.length + cache.pendingMessages.length;
    const added = Math.max(0, count - previousCountRef.current);
    if (added && historyLoadRef.current) {
      // Prepending history is not a new-message event and must not move the reader.
    } else if (added && wasAtBottomRef.current) {
      requestAnimationFrame(() => {
        snapTimelineToBottom(container);
        if (typeof document === "undefined" || document.visibilityState === "visible") {
          markRead(roomId, visibleSeq);
        }
      });
    } else if (added) {
      setNewCount((current) => current + added);
    }
    previousCountRef.current = count;
  }, [cache.pendingMessages.length, cache.timelineItems.length, markRead, roomId, visibleSeq]);

  function handleScroll() {
    const container = containerRef.current;
    if (!container) return;
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight <= 120;
    wasAtBottomRef.current = atBottom;
    if (atBottom) {
      setNewCount(0);
      if ((typeof document === "undefined" || document.visibilityState === "visible") && visibleSeq) {
        markRead(roomId, visibleSeq);
      }
    }
    const nodes = [...container.querySelectorAll<HTMLElement>("[data-message-id]")];
    const containerTop = container.getBoundingClientRect().top;
    const firstVisible = nodes.find((node) => node.getBoundingClientRect().bottom >= containerTop);
    if (firstVisible) {
      saveScrollAnchor(roomId, {
        messageId: firstVisible.dataset.messageId ?? "",
        offset: firstVisible.getBoundingClientRect().top - containerTop
      });
    }
  }

  async function handleLoadOlder() {
    const container = containerRef.current;
    if (!container || cache.loadingOlder) return;
    const snapshot = captureTimelineAnchor(container);
    historyLoadRef.current = true;
    try {
      await loadOlder(roomId);
      requestAnimationFrame(() => {
        const current = containerRef.current;
        if (current) restoreTimelineAnchor(current, snapshot);
        historyLoadRef.current = false;
      });
    } catch {
      historyLoadRef.current = false;
    }
  }

  async function handleJumpToReference(
    messageId?: string | null,
    activityId?: string | null
  ) {
    const locate = () => {
      const container = containerRef.current;
      if (!container) return null;
      return [...container.querySelectorAll<HTMLElement>("[data-message-id]")].find(
        (candidate) =>
          (messageId && candidate.dataset.messageId === messageId) ||
          (activityId && candidate.dataset.activityId === activityId)
      ) ?? null;
    };
    for (let page = 0; page < 5; page += 1) {
      const target = locate();
      if (target) {
        target.scrollIntoView?.({ block: "center", behavior: "smooth" });
        target.focus({ preventScroll: true });
        return;
      }
      const latest = useRoomStore.getState().roomsById[roomId];
      if (!latest?.projection?.has_older || latest.loadingOlder) return;
      await loadOlder(roomId);
      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
    }
  }

  return (
    <div className="room-timeline-wrap">
      <div
        aria-label="房间消息"
        aria-live="polite"
        className="room-timeline"
        onScroll={handleScroll}
        ref={containerRef}
        role="log"
      >
        {cache.projection?.has_older ? (
          <button className="room-load-older" disabled={cache.loadingOlder} onClick={() => void handleLoadOlder()} type="button">
            {cache.loadingOlder ? "正在加载…" : "加载更早消息"}
          </button>
        ) : null}
        {cache.timelineItems.map((item) => (
          <RoomMessage
            item={item}
            key={item.id}
            onJumpToReference={(messageId, activityId) => {
              void handleJumpToReference(messageId, activityId);
            }}
          />
        ))}
        {cache.pendingMessages.map((pending) => (
          <RoomPendingBubble
            key={pending.clientRequestId}
            onRetry={() => void retryMessage(pending.clientRequestId)}
            pending={pending}
          />
        ))}
        {!cache.loading && !cache.timelineItems.length && !cache.pendingMessages.length ? (
          <div className="room-empty-timeline">
            <strong>开始自然群聊</strong>
            <span>每位活跃 Agent 都会观察共享房间，并独立决定是否回应。</span>
          </div>
        ) : null}
      </div>
      {newCount > 0 ? (
        <button
          className="room-new-messages"
          onClick={() => {
            const container = containerRef.current;
            if (container) snapTimelineToBottom(container);
            setNewCount(0);
          }}
          type="button"
        >
          有 {newCount} 条新消息
        </button>
      ) : null}
    </div>
  );
}

function shortDigest(value: string): string {
  const digest = value.startsWith("sha256:") ? value : `sha256:${value}`;
  return digest.length > 19 ? `${digest.slice(0, 19)}…` : digest;
}

function SkillDecisionEvidence({
  decision,
  label
}: {
  decision?: RoomSkillDecision;
  label: string;
}) {
  if (!decision) return null;
  return (
    <section className="room-skill-evidence" aria-label={label}>
      <span className={`room-skill-status is-${decision.context_status}`}>
        {decision.context_status === "submitted" ? "上下文已提交" : "Skill 已选择"}
      </span>
      <strong>{decision.skill_id} · v{decision.version} · {decision.selection_reason}</strong>
      {decision.matched_terms.length ? <small>命中：{decision.matched_terms.join("、")}</small> : null}
      <code title={decision.content_sha256}>{shortDigest(decision.content_sha256)}</code>
      {decision.context_submitted_at ? (
        <small title={decision.context_submitted_at}>提交于 {formatTime(decision.context_submitted_at)}</small>
      ) : null}
    </section>
  );
}

function ObservationBatchDetails({
  evidence,
  label
}: {
  evidence?: RoomObservationBatchEvidence | null;
  label: string;
}) {
  if (!evidence?.phase) return null;
  const refs = evidence.member_activity_refs ?? [];
  const coverage = evidence.coverage;
  return (
    <section className="room-batch-evidence" aria-label={label}>
      <strong>{evidence.phase === "root" ? "Human root batch" : "Peer batch"}</strong>
      <dl>
        <dt>Batch 成员</dt><dd>{evidence.member_count ?? refs.length}</dd>
        <dt>真实 attempts</dt><dd>{evidence.attempt_count ?? 0}</dd>
        <dt>Context-only tail</dt><dd>{evidence.context_only_tail ? "是" : "否"}</dd>
        {coverage ? (
          <>
            <dt>覆盖</dt>
            <dd>
              {coverage.included_member_count}/{evidence.member_count ?? refs.length}
              {coverage.omitted_member_count ? ` · 省略 ${coverage.omitted_member_count}` : " · 无省略"}
            </dd>
            <dt>截止 seq</dt><dd>{coverage.cutoff_room_seq}</dd>
          </>
        ) : null}
      </dl>
      {refs.length ? (
        <details>
          <summary>Batch activity refs · {refs.length}</summary>
          {refs.map((ref) => (
            <code key={`${ref.activity_id}:${ref.room_seq}`}>{ref.activity_id} · #{ref.room_seq}</code>
          ))}
        </details>
      ) : null}
    </section>
  );
}

function AttemptDetails({ frontier }: { frontier?: RoomObservationFrontier | null }) {
  if (!frontier) return <small>当前没有未完成 observation</small>;
  const attempt = frontier.current_attempt;
  const recovery = attempt?.recovery;
  const times = [
    ["Claim", attempt?.claimed_at],
    ["Transport", attempt?.transport_started_at],
    ["Expires", attempt?.expires_at],
    ["Finished", attempt?.finished_at],
    ["Updated", attempt?.updated_at]
  ].filter((entry): entry is [string, string] => Boolean(entry[1]));
  return (
    <>
      <dl className="room-attempt-details">
        <dt>控制状态</dt><dd>{frontier.control_state ?? "active"}</dd>
        <dt>控制序号</dt><dd>{frontier.control_seq ?? 0}</dd>
        <dt>人工预算</dt><dd>{frontier.manual_retry_budget ?? 0}</dd>
        {attempt ? (
          <>
            <dt>Attempt</dt><dd>{attempt.attempt_number} / {attempt.effective_attempt_limit}</dd>
            <dt>Attempt 状态</dt><dd>{attempt.state}</dd>
            <dt>原因</dt><dd>{attempt.reason_code ?? "—"}</dd>
            {recovery && recovery.state !== "none" ? (
              <>
                <dt>恢复状态</dt><dd>{attemptRecoveryStateLabel(recovery.state)}</dd>
                <dt>恢复原因</dt><dd>{recovery.reason_code ?? "—"}</dd>
                <dt>恢复后续</dt><dd>{attemptRecoveryNextActionLabel(recovery.next_action)}</dd>
                {recovery.started_at ? (
                  <><dt>恢复开始</dt><dd title={recovery.started_at}>{formatTime(recovery.started_at)}</dd></>
                ) : null}
                {recovery.completed_at ? (
                  <><dt>恢复完成</dt><dd title={recovery.completed_at}>{formatTime(recovery.completed_at)}</dd></>
                ) : null}
              </>
            ) : null}
            {times.map(([label, value]) => (
              <Fragment key={label}>
                <dt>{label}</dt><dd title={value}>{formatTime(value)}</dd>
              </Fragment>
            ))}
          </>
        ) : (
          <><dt>Attempt</dt><dd>尚无当前 attempt</dd></>
        )}
      </dl>
      <ObservationBatchDetails evidence={frontier} label="当前 frontier batch" />
      <SkillDecisionEvidence decision={attempt?.skill_decision} label="当前 frontier Skill" />
    </>
  );
}

function attemptRecoveryStateLabel(state: "fenced" | "cleanup_pending" | "recovered"): string {
  return {
    fenced: "已隔离失效运行",
    cleanup_pending: "正在清理旧运行",
    recovered: "运行恢复已完成"
  }[state];
}

function attemptRecoveryNextActionLabel(
  action: "cleanup_pending" | "will_retry" | "will_exhaust" | "none"
): string {
  return {
    cleanup_pending: "等待清理完成",
    will_retry: "将重新进入处理",
    will_exhaust: "将标记尝试耗尽",
    none: "无需后续恢复动作"
  }[action];
}

type ExecutionConfirmation =
  | {
      kind: "policy";
      mode: RoomExecutionPolicyMode;
      descriptor: RoomExecutionPolicyUpdateDescriptor;
    }
  | {
      kind: "execute" | "reject";
      candidateId: string;
      descriptor: RoomExecutionDecisionDescriptor;
    }
  | {
      kind: "cancel";
      runId: string;
      descriptor: RoomExecutionCancelDescriptor;
    };

function ExecutionConfirmationDialog({
  target,
  pending,
  onClose,
  onConfirm
}: {
  target: ExecutionConfirmation;
  pending: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => closeRef.current?.focus(), []);
  const title = target.kind === "policy"
    ? target.mode === "consensus" ? "开启全体 Agent 共识执行？" : "切回人工执行？"
    : target.kind === "execute" ? "执行这个 exact patch？"
      : target.kind === "reject" ? "拒绝这个候选？" : "取消当前执行？";
  const detail = target.kind === "policy"
    ? "共识模式仍受启动级 kill-switch、完整 peer 快照和低风险策略约束；不满足时会降级为人工确认。"
    : target.kind === "execute"
      ? "Harness 只会在隔离 worktree 中应用这个已展示的 exact diff。全部固定门禁通过且目标 HEAD/工作树守卫未变化后，才会提升到当前工作区。"
      : target.kind === "reject"
        ? "拒绝会耐久终结当前候选，不会修改工作区。"
        : "取消只在 promotion 前生效；已进入提升阶段时后端会拒绝，避免猜测性回滚。";
  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && !pending) {
      event.preventDefault();
      event.stopPropagation();
      onClose();
    } else if (event.key === "Tab") {
      event.stopPropagation();
      if (event.shiftKey && document.activeElement === closeRef.current) {
        event.preventDefault();
        confirmRef.current?.focus();
      } else if (!event.shiftKey && document.activeElement === confirmRef.current) {
        event.preventDefault();
        closeRef.current?.focus();
      }
    }
  }
  return (
    <div className="room-dialog-layer" onKeyDown={handleKeyDown}>
      <button className="room-dialog-scrim" disabled={pending} onClick={onClose} type="button" aria-label="关闭执行确认" />
      <div aria-modal="true" className="room-confirm-dialog" role="alertdialog" aria-labelledby="execution-confirm-title">
        <span className="room-dialog-kicker">Exact-patch execution</span>
        <h2 id="execution-confirm-title">{title}</h2>
        <p>{detail}</p>
        <div className="room-dialog-actions">
          <button className="room-quiet-button" disabled={pending} onClick={onClose} ref={closeRef} type="button">返回</button>
          <button className={target.kind === "reject" || target.kind === "cancel" ? "room-danger-button" : "room-primary-button"} disabled={pending} onClick={() => void onConfirm()} ref={confirmRef} type="button">
            {pending ? "正在提交…" : "确认"}
          </button>
        </div>
      </div>
    </div>
  );
}

function RoomExecutionInspector({
  cache,
  actionPending,
  actionError,
  onSelectCandidate,
  onUpdatePolicy,
  onDecideCandidate,
  onCancelRun
}: {
  cache: RoomExecutionCache | null;
  actionPending: boolean;
  actionError: { message: string; status: number } | null;
  onSelectCandidate: (candidateId: string | null) => Promise<void>;
  onUpdatePolicy: (
    mode: RoomExecutionPolicyMode,
    descriptor: RoomExecutionPolicyUpdateDescriptor
  ) => Promise<boolean>;
  onDecideCandidate: (
    candidateId: string,
    decision: "execute" | "reject",
    descriptor: RoomExecutionDecisionDescriptor
  ) => Promise<boolean>;
  onCancelRun: (runId: string, descriptor: RoomExecutionCancelDescriptor) => Promise<boolean>;
}) {
  const [confirmation, setConfirmation] = useState<ExecutionConfirmation | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const list = cache?.list ?? null;
  const selectedId = cache?.selectedCandidateId ?? null;
  const detail = selectedId ? cache?.details[selectedId] ?? null : null;
  const policy = list?.policy ?? detail?.policy ?? null;
  const gateProfile = list?.gate_profile ?? detail?.gate_profile ?? null;
  const profileBlocked = gateProfile?.readiness.ready !== true;
  const boundProfile = detail?.run?.gate_profile ?? detail?.candidate.gate_profile ?? null;

  function requestConfirmation(target: ExecutionConfirmation) {
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setConfirmation(target);
  }
  function closeConfirmation() {
    setConfirmation(null);
    requestAnimationFrame(() => returnFocusRef.current?.focus());
  }
  async function confirm() {
    if (!confirmation) return;
    if (confirmation.kind === "policy") {
      await onUpdatePolicy(confirmation.mode, confirmation.descriptor);
    } else if (confirmation.kind === "execute" || confirmation.kind === "reject") {
      await onDecideCandidate(
        confirmation.candidateId,
        confirmation.kind,
        confirmation.descriptor
      );
    } else if ("runId" in confirmation) {
      await onCancelRun(confirmation.runId, confirmation.descriptor);
    }
    closeConfirmation();
  }

  return (
    <section className="room-executions" aria-label="执行候选">
      <div className="room-executions-heading">
        <h3>执行候选</h3>
        {cache?.loading ? <small>正在核验…</small> : <small>只执行 exact patch</small>}
      </div>
      {gateProfile ? (
        <div
          className={`room-execution-policy ${profileBlocked ? "state-blocked" : ""}`}
          aria-label="执行门禁 Profile"
        >
          <div>
            <strong>{gateProfile.profile_id}</strong>
            <small>
              profile revision {gateProfile.revision} · {gateProfile.gate_ids.length} 个固定门禁
            </small>
          </div>
          <small>{profileBlocked ? `不可用 · ${gateProfile.readiness.code}` : "已就绪"}</small>
          {profileBlocked ? (
            <p className="room-execution-notice" role="status">
              当前 workspace 或本地工具链未满足固定门禁；人工与共识执行均保持阻断。
            </p>
          ) : null}
        </div>
      ) : (
        <div className="room-execution-policy state-blocked" aria-label="执行门禁 Profile">
          <div>
            <strong>门禁状态不可用</strong>
            <small>未取得可信的固定 gate profile</small>
          </div>
          <p className="room-execution-notice" role="status">
            当前无法证明执行门禁，人工与共识执行均保持阻断。
          </p>
        </div>
      )}
      {policy ? (
        <div className="room-execution-policy" aria-label="Room 执行策略">
          <div>
            <strong>{policy.mode === "manual" ? "人工确认" : "全体共识"}</strong>
            <small>策略 revision {policy.revision} · 风险策略 {policy.risk_policy_revision}</small>
          </div>
          <div role="group" aria-label="切换 Room 执行策略">
            {(["manual", "consensus"] as const).map((mode) => (
              <button
                aria-pressed={policy.mode === mode}
                className="room-quiet-button"
                disabled={actionPending || policy.mode === mode || !policy.actions.update.available}
                key={mode}
                onClick={() => requestConfirmation({ kind: "policy", mode, descriptor: policy.actions.update })}
                type="button"
              >{mode === "manual" ? "人工" : "共识"}</button>
            ))}
          </div>
          {!policy.kill_switch_enabled ? (
            <p className="room-execution-notice">启动级共识自动执行未开启；即使 Room 选择共识，候选仍会降级到人工确认。</p>
          ) : null}
        </div>
      ) : null}
      {list?.candidates.length ? (
        <div className="room-execution-layout">
          <div className="room-execution-candidates" role="list" aria-label="最近执行候选">
            {list.candidates.map((candidate) => (
              <button
                aria-current={candidate.candidate_id === selectedId ? "true" : undefined}
                className="room-execution-candidate"
                key={candidate.candidate_id}
                onClick={() => void onSelectCandidate(candidate.candidate_id)}
                role="listitem"
                type="button"
              >
                <strong>{candidate.summary}</strong>
                <span>{candidate.allowed_files.join("、") || "无文件"}</span>
                <small>{candidate.state} · 赞成 {candidate.votes.endorse}/{candidate.votes.required} · 门禁 {candidate.gate_summary.passed}/{candidate.gate_summary.total}</small>
              </button>
            ))}
          </div>
          {detail ? (
            <article className="room-execution-detail" aria-label="Exact diff 详情">
              <header>
                <div><strong>{detail.candidate.summary}</strong><small>{detail.candidate.digest}</small></div>
                <span className={`room-execution-state is-${detail.candidate.state}`}>{detail.candidate.state}</span>
              </header>
              <dl className="room-execution-facts">
                <dt>Base HEAD</dt><dd><code>{detail.candidate.base_head ?? "—"}</code></dd>
                <dt>Allowed files</dt><dd>{detail.candidate.allowed_files.join("、") || "—"}</dd>
                <dt>Patch bytes</dt><dd>{detail.candidate.byte_count}</dd>
                <dt>Gate profile</dt><dd>{boundProfile ? `${boundProfile.profile_id} · ${boundProfile.gate_ids.length} gates` : "待授权冻结"}</dd>
              </dl>
              <pre className="room-execution-diff" aria-label="Exact unified diff"><code>{detail.candidate.unified_diff}</code></pre>
              <div className="room-execution-votes" aria-label="共识投票">
                <strong>投票 {detail.vote_counts.endorse}/{detail.vote_counts.required}</strong>
                {detail.votes.map((vote) => (
                  <article key={vote.participant_id}>
                    <span>{vote.display_name ?? vote.participant_id}</span>
                    <strong>{vote.assessment}</strong>
                    {vote.rationale ? <small>{vote.rationale}</small> : null}
                  </article>
                ))}
              </div>
              {detail.run ? (
                <div className="room-execution-run" aria-label="执行门禁" role="region">
                  <div><strong>Run · {detail.run.state}</strong><small>attempt {detail.run.attempt_number}</small></div>
                  {detail.run.gates.map((gate) => (
                    <div className={`room-execution-gate is-${gate.state}`} key={gate.gate_id}>
                      <span>{gate.label}</span><strong>{gate.state}</strong>
                    </div>
                  ))}
                  <button
                    className="room-danger-button"
                    disabled={actionPending || !detail.run.actions.cancel.available}
                    onClick={() => requestConfirmation({ kind: "cancel", runId: detail.run!.run_id, descriptor: detail.run!.actions.cancel })}
                    type="button"
                  >取消执行</button>
                </div>
              ) : null}
              <div className="room-execution-actions">
                <button
                  className="room-primary-button"
                  disabled={actionPending || profileBlocked || !detail.actions.execute.available}
                  onClick={() => requestConfirmation({ kind: "execute", candidateId: detail.candidate.candidate_id, descriptor: detail.actions.execute })}
                  type="button"
                >人工执行</button>
                <button
                  className="room-danger-button"
                  disabled={actionPending || !detail.actions.reject.available}
                  onClick={() => requestConfirmation({ kind: "reject", candidateId: detail.candidate.candidate_id, descriptor: detail.actions.reject })}
                  type="button"
                >拒绝</button>
              </div>
            </article>
          ) : cache?.detailLoading ? <p>正在加载 exact diff…</p> : null}
        </div>
      ) : <p className="room-operations-empty">当前房间没有执行候选。</p>}
      {cache?.error ? <p className="room-operations-warning" role="status">执行状态暂不可刷新，保留 Room 消息：{cache.error.message}</p> : null}
      {actionError ? <p className="room-operations-warning" role="alert">{actionError.status === 409 ? "执行状态已变化，已刷新最新证据。" : `执行操作未完成：${actionError.message}`}</p> : null}
      {confirmation ? (
        <ExecutionConfirmationDialog
          onClose={closeConfirmation}
          onConfirm={confirm}
          pending={actionPending}
          target={confirmation}
        />
      ) : null}
    </section>
  );
}

type MemoryConfirmation = {
  candidate: RoomMemoryCandidate;
  decision: "approve" | "reject";
};

function RoomMemoryInspector({
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
            <span><strong>{projection.sync.backlog}</strong>待同步</span>
            <span><strong>{projection.recent_recalls.length}</strong>最近召回</span>
            <span><strong>{projection.pending_candidate_total}</strong>待审批</span>
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

function RoomInspector({
  agentConsoleSection,
  executionCache,
  executionActionPending,
  executionActionError,
  memoryCache,
  memoryActionPending,
  memoryActionError,
  memoryRebuildPending,
  memoryRebuildError,
  operations,
  operationsError,
  operationsLoading,
  recoverPending,
  recoverError,
  selectedRoomId,
  participants,
  turns,
  controlPending,
  onCancel,
  onRetry,
  onClose,
  onIncidentAction,
  onRecover,
  modal,
  inspectorTarget,
  targetReady,
  onTargetResolved,
  onTargetMissing,
  onSelectExecutionCandidate,
  onUpdateExecutionPolicy,
  onDecideExecutionCandidate,
  onCancelExecutionRun,
  onResolveMemoryCandidate,
  onRebuildMemoryIndex
}: {
  agentConsoleSection: ReactNode;
  executionCache: RoomExecutionCache | null;
  executionActionPending: boolean;
  executionActionError: { message: string; status: number } | null;
  memoryCache: RoomMemoryCache | null;
  memoryActionPending: boolean;
  memoryActionError: { message: string; status: number } | null;
  memoryRebuildPending: boolean;
  memoryRebuildError: { message: string; status: number } | null;
  operations: RoomOperationsProjection | null;
  operationsError: { message: string; status: number } | null;
  operationsLoading: boolean;
  recoverPending: boolean;
  recoverError: { message: string; status: number } | null;
  selectedRoomId: string | null;
  participants: RoomParticipant[];
  turns: RoomTurn[];
  controlPending: RoomCache["controlPending"];
  onCancel: (target: CancelTarget) => void;
  onRetry: (observationId: string, descriptor: RoomControlActionDescriptor) => void;
  onClose: () => void;
  onIncidentAction: (incident: RoomOperationsIncident) => void;
  onRecover: (descriptor: RoomRuntimeRecoverDescriptor) => void;
  modal: boolean;
  inspectorTarget: { roomId: string; observationId: string | null; incidentId: string } | null;
  targetReady: boolean;
  onTargetResolved: (target: null) => void;
  onTargetMissing: () => void;
  onSelectExecutionCandidate: (candidateId: string | null) => Promise<void>;
  onUpdateExecutionPolicy: (
    mode: RoomExecutionPolicyMode,
    descriptor: RoomExecutionPolicyUpdateDescriptor
  ) => Promise<boolean>;
  onDecideExecutionCandidate: (
    candidateId: string,
    decision: "execute" | "reject",
    descriptor: RoomExecutionDecisionDescriptor
  ) => Promise<boolean>;
  onCancelExecutionRun: (
    runId: string,
    descriptor: RoomExecutionCancelDescriptor
  ) => Promise<boolean>;
  onResolveMemoryCandidate: (
    candidateId: string,
    decision: "approve" | "reject",
    descriptor: RoomMemoryResolveDescriptor
  ) => Promise<boolean>;
  onRebuildMemoryIndex: (descriptor: RoomMemoryRebuildDescriptor) => void;
}) {
  const activeTurnCount = turns.filter((turn) => turn.state !== "settled").length;
  const incidents = useMemo(() => {
    if (!operations) return [];
    return [...operations.incidents]
      .sort((left, right) =>
        Number(right.conversation_id === selectedRoomId) - Number(left.conversation_id === selectedRoomId)
      )
      .slice(0, 5);
  }, [operations, selectedRoomId]);

  return (
    <RoomInspectorShell
      agentConsoleSection={agentConsoleSection}
      executionSection={<RoomExecutionInspector
        actionError={executionActionError}
        actionPending={executionActionPending}
        cache={executionCache}
        onCancelRun={onCancelExecutionRun}
        onDecideCandidate={onDecideExecutionCandidate}
        onSelectCandidate={onSelectExecutionCandidate}
        onUpdatePolicy={onUpdateExecutionPolicy}
      />}
      memorySection={<RoomMemoryInspector
        actionError={memoryActionError}
        actionPending={memoryActionPending}
        cache={memoryCache}
        rebuildDescriptor={operations?.actions.rebuild_memory_index ?? null}
        rebuildError={memoryRebuildError}
        rebuildPending={memoryRebuildPending}
        onResolve={onResolveMemoryCandidate}
        onRebuild={onRebuildMemoryIndex}
      />}
      modal={modal}
      onClose={onClose}
      onTargetMissing={onTargetMissing}
      onTargetResolved={() => onTargetResolved(null)}
      operationsSection={<>
      <section className={`room-operations state-${operations?.overall ?? "unknown"}`} aria-label="运行与恢复" tabIndex={-1}>
        <div className="room-operations-heading">
          <h3>运行与恢复</h3>
          {operationsLoading ? <small>正在核验…</small> : null}
        </div>
        {operations ? (
          <>
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
            {incidents.length ? (
              <div className="room-operations-incidents" aria-label="运行事件">
                {incidents.map((incident) => (
                  <OperationIncident incident={incident} key={incident.incident_id} onAction={onIncidentAction} />
                ))}
                {operations.incident_total > incidents.length ? (
                  <small>另有 {operations.incident_total - incidents.length} 项</small>
                ) : null}
              </div>
            ) : <p className="room-operations-empty">当前没有需要处理的运行事件。</p>}
            {operations.actions.recover_runtime.available ? (
              <button
                className="room-danger-button room-runtime-recover-button"
                disabled={recoverPending}
                onClick={() => onRecover(operations.actions.recover_runtime)}
                type="button"
              >
                {recoverPending ? "正在恢复运行时…" : operations.actions.recover_runtime.mode === "start" ? "启动 Room Runtime" : "恢复 Room Runtime"}
              </button>
            ) : null}
          </>
        ) : <p className="room-operations-empty">尚未取得可信的运行状态。</p>}
        {operationsError ? (
          <p className="room-operations-warning" role="status">运行状态暂不可刷新，保留上次核验结果：{operationsError.message}</p>
        ) : null}
        {recoverError ? (
          <p className="room-operations-warning" role="alert">
            {recoverError.status === 409 ? "运行状态已经变化，已刷新最新状态。" : `运行时恢复未完成：${recoverError.message}`}
          </p>
        ) : null}
      </section>
      </>}
      roomEvidenceSection={<>
      <section>
        <h3>活跃成员</h3>
        <div className="room-inspector-members">
          {participants.map((participant) => (
            <article key={participant.participant_id}>
              <span className="room-avatar" style={identityStyle(participant.participant_id)}>{initials(participant.display_name)}</span>
              <div>
                <strong>{participant.display_name}</strong>
                <span>{participant.mention_handle} · {participant.role}</span>
              </div>
              <small>{participant.active ? "会观察新活动" : "已停止"}</small>
            </article>
          ))}
        </div>
      </section>
      {turns.length ? (
        <section>
          <h3>{activeTurnCount ? `进行中轮次 · ${activeTurnCount}` : "最近轮次"}</h3>
          <div className="room-inspector-active-turns">
            {turns.map((turn) => (
              <article className="room-inspector-turn" key={turn.correlation_id}>
                <header>
                  <strong>{roomStateLabel(turn.state)}</strong>
                  <code title={turn.correlation_id}>{turn.correlation_id}</code>
                </header>
                <small>
                  Observations {turn.observation_count} · Attempts {turn.attempt_count} · Skill decisions {turn.skill_decision_count}
                  {turn.excluded_stopped_count ? ` · 停止成员遗留 ${turn.excluded_stopped_count}` : ""}
                </small>
                <div className="room-inspector-turns">
                  {turn.participants.map((participant: RoomTurnParticipant) => {
                    const frontier = participant.frontier;
                    const observationId = frontier?.observation_id ?? "";
                    const cancel = frontier?.actions?.cancel;
                    const retry = frontier?.actions?.retry;
                    const pending = controlPending?.observationId === observationId;
                    return (
                      <article
                        data-observation-id={observationId || undefined}
                        key={`${turn.correlation_id}:${participant.participant_id}`}
                        tabIndex={-1}
                      >
                        <div className="room-inspector-agent-heading">
                          <span>
                            <strong>{participant.display_name}</strong>
                            <small>{roomParticipantStateLabel(participant.state ?? participant.status)} · {participant.unresolved_count} 个未完成</small>
                          </span>
                          <span className="room-inspector-controls">
                            <button
                              aria-label={`取消 ${participant.display_name} 在轮次 ${turn.correlation_id} 的处理`}
                              className="room-control-button is-cancel"
                              disabled={pending || !cancel?.available || !observationId}
                              onClick={() => cancel?.available && observationId && onCancel({ observationId, participant, descriptor: cancel })}
                              title={cancel?.available ? "只取消该 Agent 当前 delivery" : "当前没有可取消的 delivery"}
                              type="button"
                            >取消</button>
                            <button
                              aria-label={`重试 ${participant.display_name} 在轮次 ${turn.correlation_id} 的 observation`}
                              className="room-control-button is-retry"
                              disabled={pending || !retry?.available || !observationId}
                              onClick={() => retry?.available && observationId && onRetry(observationId, retry)}
                              title={retry?.available ? "重新开放同一 observation" : "仅已取消或尝试耗尽的 observation 可重试"}
                              type="button"
                            >重试</button>
                          </span>
                        </div>
                        <SkillDecisionEvidence
                          decision={participant.root_skill_decision}
                          label="Human-root Skill"
                        />
                        <AttemptDetails frontier={frontier} />
                        <SkillDecisionEvidence
                          decision={participant.latest_outcome?.skill_decision}
                          label="最新 outcome Skill"
                        />
                        <ObservationBatchDetails
                          evidence={participant.latest_outcome}
                          label="最新 outcome batch"
                        />
                      </article>
                    );
                  })}
                </div>
              </article>
            ))}
          </div>
        </section>
      ) : null}
      <details className="room-advanced-proof">
        <summary>高级核验</summary>
        <p>界面状态只来自 chat.db 的 Room projection。Provider 文本和浏览器遥测不是群聊事实。</p>
      </details>
      </>}
      selectedRoomId={selectedRoomId}
      target={inspectorTarget}
      targetReady={targetReady}
      targetVersion={`${turns.length}:${operations?.incident_total ?? 0}`}
    />
  );
}

function runtimeStateLabel(state: string): string {
  return {
    ready: "就绪",
    healthy: "正常",
    attention: "需关注",
    blocked: "已阻塞",
    unknown: "未知",
    starting: "启动中",
    recovering: "自动恢复中",
    rebuilding: "正在重建索引",
    stopping: "停止中",
    stopped: "已停止",
    failed: "失败",
    stale: "心跳过期",
    invalid: "状态无效"
  }[state] ?? state;
}

function OperationIncident({
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
        <button className="room-quiet-button" onClick={() => onAction(incident)} type="button">
          {actionLabel}
        </button>
      )}
    </article>
  );
}

function RuntimeRecoverDialog({
  pending,
  onClose,
  onConfirm
}: {
  pending: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

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

  return (
    <div className="room-dialog-layer" onKeyDown={handleKeyDown}>
      <button className="room-dialog-scrim" disabled={pending} onClick={onClose} type="button" aria-label="关闭运行时恢复确认" />
      <div
        aria-describedby="runtime-recover-description"
        aria-labelledby="runtime-recover-title"
        aria-modal="true"
        className="room-confirm-dialog"
        role="alertdialog"
      >
        <span className="room-dialog-kicker">守卫运行时恢复</span>
        <h2 id="runtime-recover-title">确认恢复 Room Runtime？</h2>
        <p id="runtime-recover-description">
          这会中断当前正在进行的 Agent delivery。未完成工作将由耐久 observation attempt 在新运行时中安全恢复，不会伪造 Agent 回应。
        </p>
        <div className="room-dialog-actions">
          <button className="room-quiet-button" disabled={pending} onClick={onClose} ref={closeRef} type="button">返回</button>
          <button className="room-danger-button" disabled={pending} onClick={() => void onConfirm()} ref={confirmRef} type="button">
            {pending ? "正在恢复运行时…" : "确认中断并恢复"}
          </button>
        </div>
      </div>
    </div>
  );
}

function MemoryRebuildDialog({
  pending,
  onClose,
  onConfirm
}: {
  pending: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

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

  return (
    <div className="room-dialog-layer" onKeyDown={handleKeyDown}>
      <button
        aria-label="关闭记忆索引重建确认"
        className="room-dialog-scrim"
        disabled={pending}
        onClick={onClose}
        type="button"
      />
      <div
        aria-describedby="memory-rebuild-description"
        aria-labelledby="memory-rebuild-title"
        aria-modal="true"
        className="room-confirm-dialog"
        role="alertdialog"
      >
        <span className="room-dialog-kicker">MemoryOS 派生索引</span>
        <h2 id="memory-rebuild-title">确认重建 MemoryOS 派生索引？</h2>
        <p id="memory-rebuild-description">
          只会删除可重建的 MemoryOS 派生缓存，并从 chat.db 重新绑定与回放。Room 消息、已审批记忆和其他耐久事实不会删除；重建期间群聊仍可继续工作。
        </p>
        <div className="room-dialog-actions">
          <button className="room-quiet-button" disabled={pending} onClick={onClose} ref={closeRef} type="button">返回</button>
          <button className="room-danger-button" disabled={pending} onClick={() => void onConfirm()} ref={confirmRef} type="button">
            {pending ? "正在请求重建…" : "确认重建派生索引"}
          </button>
        </div>
      </div>
    </div>
  );
}

function syncLabel(cache: RoomCache | null): string {
  if (!cache) return "未选择房间";
  const labels = {
    idle: "等待同步",
    syncing: "正在同步",
    synced: "已同步",
    "catching-up": "正在补拉",
    stale: "数据可能过期",
    offline: "离线"
  };
  return labels[cache.syncState];
}

function useCompactLayout() {
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia("(max-width: 1099px)");
    const update = () => setCompact(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return compact;
}

export function RoomWorkspace({ onNavigateRoom, onCreatedRoom }: RoomWorkspaceProps) {
  const store = useRoomStore();
  const compactLayout = useCompactLayout();
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [sidebarQuery, setSidebarQuery] = useState("");
  const [creatingRoom, setCreatingRoom] = useState(false);
  const [roomTitle, setRoomTitle] = useState("");
  const [roomCreateRequestId, setRoomCreateRequestId] = useState<string | null>(null);
  const [cancelTarget, setCancelTarget] = useState<CancelTarget | null>(null);
  const [recoverTarget, setRecoverTarget] = useState<RoomRuntimeRecoverDescriptor | null>(null);
  const [memoryRebuildTarget, setMemoryRebuildTarget] = useState<RoomMemoryRebuildDescriptor | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const selectedRoom = store.rooms.find((room) => room.conversation_id === store.selectedRoomId) ?? null;
  const cache = store.selectedRoomId ? store.roomsById[store.selectedRoomId] ?? null : null;
  const executionCache = store.selectedRoomId
    ? store.executionsByRoom[store.selectedRoomId] ?? null
    : null;
  const memoryCache = store.selectedRoomId
    ? store.memoryByRoom[store.selectedRoomId] ?? null
    : null;
  const codexCache = store.selectedRoomId
    ? store.codexByRoom[store.selectedRoomId] ?? null
    : null;
  const codexParticipants = codexCache?.projection?.participants ?? [];
  const selectedCodexParticipant = codexParticipants.find(
    (item) => item.participant.participant_id === codexCache?.selectedParticipantId
  ) ?? codexParticipants[0] ?? null;
  const projection = cache?.projection ?? null;
  const participants = projection?.participants ?? selectedRoom?.members ?? [];
  const activeTurns = projection?.turns.filter((turn) => turn.state !== "settled") ?? [];
  const currentTurn = activeTurns.at(-1) ?? projection?.turns.at(-1) ?? null;
  const title = projection?.conversation.title ?? selectedRoom?.title ?? "选择一个房间";
  const draft = store.selectedRoomId ? store.drafts[store.selectedRoomId] ?? "" : "";
  const operationsAlert = store.operations?.overall === "blocked"
    ? { className: "has-alert", label: "运行时阻塞", glyph: "!" }
    : store.operations?.overall === "attention"
      ? { className: "has-attention", label: "运行时需要关注", glyph: "·" }
      : memoryCache?.projection?.degraded || memoryCache?.projection?.pending_candidate_total
        ? { className: "has-attention", label: "长期记忆需要关注", glyph: "·" }
        : null;

  useEffect(() => {
    document.documentElement.dataset.theme = store.theme;
  }, [store.theme]);

  useEffect(() => {
    const refresh = () => {
      void store.loadRooms();
      void store.refreshOperations();
      void store.refreshExecutions();
      void store.refreshMemory();
    };
    const visibility = () => {
      store.startOperationsSync();
      store.startExecutionSync();
      store.startMemorySync();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", visibility);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const invalidRoom = Boolean(
    store.selectedRoomId &&
    !selectedRoom &&
    cache?.error?.status === 404 &&
    !cache.projection &&
    !store.roomsLoading
  );
  const unavailableRoom = Boolean(
    store.selectedRoomId && cache?.error && cache.error.status !== 404 && !cache.projection
  );

  function closeCancelDialog() {
    setCancelTarget(null);
    requestAnimationFrame(() => {
      if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus();
      else document.querySelector<HTMLElement>(".room-inspector button")?.focus();
    });
  }

  async function confirmCancel() {
    if (!cancelTarget) return;
    await store.controlObservation(
      cancelTarget.observationId,
      "cancel",
      cancelTarget.descriptor
    );
    closeCancelDialog();
  }

  function closeRecoverDialog() {
    setRecoverTarget(null);
    requestAnimationFrame(() => {
      if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus();
      else document.querySelector<HTMLElement>(".room-inspector button")?.focus();
    });
  }

  async function confirmRecover() {
    if (!recoverTarget) return;
    await store.recoverRuntime(recoverTarget);
    closeRecoverDialog();
  }

  function closeMemoryRebuildDialog() {
    setMemoryRebuildTarget(null);
    requestAnimationFrame(() => {
      if (returnFocusRef.current?.isConnected) returnFocusRef.current.focus();
      else document.querySelector<HTMLElement>(".room-inspector button")?.focus();
    });
  }

  async function confirmMemoryRebuild() {
    if (!memoryRebuildTarget) return;
    await store.rebuildMemoryIndex(memoryRebuildTarget);
    closeMemoryRebuildDialog();
  }

  function handleOperationIncident(incident: RoomOperationsIncident) {
    if (incident.next_action === "rebuild_memory_index") {
      const descriptor = store.operations?.actions.rebuild_memory_index;
      if (descriptor?.available && !descriptor.pending) {
        returnFocusRef.current = document.activeElement as HTMLElement | null;
        setMemoryRebuildTarget(descriptor);
      } else {
        void store.refreshOperations();
      }
      return;
    }
    if (incident.next_action === "recover_runtime" || incident.next_action === "repair_then_recover") {
      const descriptor = store.operations?.actions.recover_runtime;
      if (descriptor?.available) {
        returnFocusRef.current = document.activeElement as HTMLElement | null;
        setRecoverTarget(descriptor);
      } else {
        void store.refreshOperations();
      }
      return;
    }
    if (!incident.conversation_id) return;
    store.setInspectorTarget({
      roomId: incident.conversation_id,
      observationId: incident.observation_id,
      incidentId: incident.incident_id
    });
    if (incident.conversation_id !== store.selectedRoomId) {
      onNavigateRoom(incident.conversation_id);
    }
  }

  function handleInspectorTargetMissing() {
    void store.refreshOperations();
    if (store.selectedRoomId) {
      void store.refreshRoom(store.selectedRoomId, "incremental");
    }
  }

  return (
    <div className={`room-app ${store.sidebarOpen ? "has-sidebar" : ""} ${store.inspectorOpen ? "has-inspector" : ""}`}>
      {store.sidebarOpen || mobileSidebarOpen ? (
        <div className={`room-sidebar-slot ${mobileSidebarOpen ? "is-mobile-open" : ""}`}>
          {mobileSidebarOpen ? (
            <button className="room-mobile-scrim" onClick={() => setMobileSidebarOpen(false)} type="button" aria-label="关闭房间栏遮罩" />
          ) : null}
          <RoomSidebar
            createRequestId={roomCreateRequestId}
            createError={store.roomCreateError}
            createPending={store.roomCreatePending}
            creating={creatingRoom}
            drafts={store.drafts}
            error={store.roomsError}
            loading={store.roomsLoading}
            loaded={store.roomsLoaded}
            onClose={() => setMobileSidebarOpen(false)}
            onCreate={async (name, clientRequestId) => {
              setRoomCreateRequestId(clientRequestId);
              const id = await store.createRoom(name, clientRequestId);
              if (id) {
                setRoomTitle("");
                setRoomCreateRequestId(null);
                setCreatingRoom(false);
                onCreatedRoom(id);
              }
              return Boolean(id);
            }}
            onCreatingChange={setCreatingRoom}
            onNavigate={(id) => {
              setMobileSidebarOpen(false);
              onNavigateRoom(id);
            }}
            onQueryChange={setSidebarQuery}
            onTitleChange={(value) => {
              setRoomTitle(value);
              setRoomCreateRequestId(null);
            }}
            query={sidebarQuery}
            readCursors={store.readCursors}
            rooms={store.rooms}
            selectedRoomId={store.selectedRoomId}
            title={roomTitle}
          />
        </div>
      ) : null}

      <main className="room-main">
        <RoomHeader
          inspectorOpen={store.inspectorOpen}
          navigationOpen={compactLayout ? mobileSidebarOpen : store.sidebarOpen}
          onToggleInspector={() => store.setInspectorOpen(!store.inspectorOpen)}
          onToggleNavigation={() => {
              if (compactLayout) setMobileSidebarOpen((open) => !open);
              else store.setSidebarOpen(!store.sidebarOpen);
          }}
          onToggleTheme={() => store.setTheme(store.theme === "dark" ? "light" : "dark")}
          operationsAlert={operationsAlert}
          participants={participants}
          syncLabel={syncLabel(cache)}
          syncState={cache?.syncState ?? "idle"}
          theme={store.theme}
          title={title}
        />

        {invalidRoom ? (
          <section className="room-fatal-empty" role="alert">
            <strong>找不到这个房间</strong>
            <span>{cache?.error?.message ?? "房间不存在或当前无法读取。"}</span>
            <button className="room-primary-button" onClick={() => store.rooms[0] && onNavigateRoom(store.rooms[0].conversation_id)} type="button">返回最近房间</button>
          </section>
        ) : unavailableRoom ? (
          <section className="room-fatal-empty" role="alert">
            <strong>房间暂时无法读取</strong>
            <span>{cache?.error?.message ?? "Chat API 当前不可用。"}</span>
            <button className="room-primary-button" onClick={() => void store.refreshRoom(store.selectedRoomId ?? undefined, "initial")} type="button">重试读取</button>
          </section>
        ) : store.selectedRoomId && cache ? (
          <>
            <RoomTurnStatus
              controlPending={cache.controlPending}
              hiddenCount={Math.max(0, (projection?.active_turn_count ?? activeTurns.length) - 1)}
              onCancel={(target) => {
                returnFocusRef.current = document.activeElement as HTMLElement | null;
                setCancelTarget(target);
              }}
              onRetry={(observationId, descriptor) => {
                void store.controlObservation(observationId, "retry", descriptor);
              }}
              turn={currentTurn}
            />
            {cache.controlError ? (
              <div className="room-error-banner room-control-error" role="alert">
                <span>
                  <strong>{cache.controlError.status === 409 ? "状态已经变化" : "Agent 控制未完成"}</strong>
                  {cache.controlError.status === 409
                    ? "已刷新最新 Room 状态，请根据当前可用动作重试。"
                    : cache.controlError.message}
                </span>
                <button className="room-icon-button" onClick={() => store.clearControlError()} type="button" aria-label="关闭控制错误">×</button>
              </div>
            ) : null}
            {cache.error ? (
              <div className="room-error-banner" role="alert">
                <span><strong>{cache.syncState === "stale" ? "同步暂时中断" : "房间读取失败"}</strong>{cache.error.message}</span>
                <button className="room-quiet-button" onClick={() => void store.refreshRoom(store.selectedRoomId ?? undefined, cache.projection ? "incremental" : "initial")} type="button">重试</button>
                <button className="room-icon-button" onClick={() => store.clearRoomError()} type="button" aria-label="关闭错误">×</button>
              </div>
            ) : null}
            <RoomTimeline cache={cache} roomId={store.selectedRoomId} />
            <RoomComposer
              disabled={!projection && cache.loading}
              draft={draft}
              key={store.selectedRoomId}
              onDraftChange={(value) => store.setDraft(store.selectedRoomId!, value)}
              onSend={(content) => store.sendMessage(content)}
              participants={participants}
              roomId={store.selectedRoomId}
            />
          </>
        ) : store.roomsError && !store.rooms.length ? (
          <section className="room-fatal-empty" role="alert">
            <strong>无法连接 xmuse</strong>
            <span>{store.roomsError.message}</span>
            <button className="room-primary-button" onClick={() => void store.loadRooms()} type="button">重新连接</button>
          </section>
        ) : (
          <section className="room-fatal-empty">
            <strong>{store.roomsLoading && !store.roomsLoaded ? "正在连接 xmuse…" : "还没有房间"}</strong>
            <span>创建房间后，活跃 Agent 会共同观察其中的活动。</span>
          </section>
        )}
      </main>

      {store.inspectorOpen ? (
        <>
          {compactLayout ? (
            <button
              aria-label="关闭检查器遮罩"
              className="room-inspector-scrim"
              onClick={() => store.setInspectorOpen(false)}
              tabIndex={-1}
              type="button"
            />
          ) : null}
          <RoomInspector
            agentConsoleSection={(
              <section className="room-agent-console-section" aria-label="Codex Agent Console">
                <div className="room-agent-console-tabs" role="tablist" aria-label="选择 Codex Agent">
                  {codexParticipants.map((item) => (
                    <button
                      aria-selected={item.participant.participant_id === selectedCodexParticipant?.participant.participant_id}
                      key={item.participant.participant_id}
                      onClick={() => store.selectCodexParticipant(item.participant.participant_id)}
                      role="tab"
                      type="button"
                    >{item.participant.display_name}</button>
                  ))}
                </div>
                {selectedCodexParticipant && codexCache?.projection ? (
                  <AgentConsole
                    error={codexCache.actionErrors[selectedCodexParticipant.participant.participant_id]?.message
                      ?? codexCache.error?.message
                      ?? null}
                    key={selectedCodexParticipant.participant.participant_id}
                    localMode={store.getCodexConsolePreference(selectedCodexParticipant.participant.participant_id)}
                    nativeEvents={codexCache.projection.native_events.items}
                    onAction={(capabilityId, safeRequest, descriptor, confirmed) =>
                      store.submitCodexAction(
                        selectedCodexParticipant.participant.participant_id,
                        capabilityId,
                        safeRequest,
                        descriptor,
                        confirmed
                      )}
                    onPreferenceChange={(mode) => {
                      store.setCodexConsolePreference(
                        selectedCodexParticipant.participant.participant_id,
                        mode
                      );
                    }}
                    onRefresh={() => void store.refreshCodexAgents()}
                    participant={selectedCodexParticipant}
                    pending={Boolean(codexCache.actionPending[selectedCodexParticipant.participant.participant_id])}
                  />
                ) : (
                  <div className="agent-console agent-console--empty" role="status">
                    <h3>Agent Console</h3>
                    <p>{codexCache?.loading ? "正在读取 Codex 原生状态…" : "当前房间没有可用的 Codex Agent 投影。"}</p>
                    {codexCache?.error ? <button onClick={() => void store.refreshCodexAgents()} type="button">重试</button> : null}
                  </div>
                )}
              </section>
            )}
            controlPending={cache?.controlPending ?? null}
            executionActionError={store.executionActionError}
            executionActionPending={Boolean(store.executionActionPending)}
            executionCache={executionCache}
            memoryActionError={store.memoryActionError}
            memoryActionPending={Boolean(store.memoryActionPending)}
            memoryCache={memoryCache}
            memoryRebuildError={store.memoryRebuildError}
            memoryRebuildPending={store.memoryRebuildPending}
            inspectorTarget={store.inspectorTarget}
            modal={compactLayout}
            operations={store.operations}
            operationsError={store.operationsError}
            operationsLoading={store.operationsLoading}
            onCancel={(target) => {
              returnFocusRef.current = document.activeElement as HTMLElement | null;
              setCancelTarget(target);
            }}
            onClose={() => store.setInspectorOpen(false)}
            onIncidentAction={handleOperationIncident}
            onCancelExecutionRun={store.cancelExecutionRun}
            onDecideExecutionCandidate={store.decideExecutionCandidate}
            onResolveMemoryCandidate={store.resolveMemoryCandidate}
            onRebuildMemoryIndex={(descriptor) => {
              returnFocusRef.current = document.activeElement as HTMLElement | null;
              setMemoryRebuildTarget(descriptor);
            }}
            onRecover={(descriptor) => {
              returnFocusRef.current = document.activeElement as HTMLElement | null;
              setRecoverTarget(descriptor);
            }}
            onRetry={(observationId, descriptor) => {
              void store.controlObservation(observationId, "retry", descriptor);
            }}
            onSelectExecutionCandidate={store.selectExecutionCandidate}
            onTargetResolved={store.setInspectorTarget}
            onTargetMissing={handleInspectorTargetMissing}
            onUpdateExecutionPolicy={store.updateExecutionPolicy}
            participants={participants}
            recoverError={store.runtimeRecoverError}
            recoverPending={store.runtimeRecoverPending}
            selectedRoomId={store.selectedRoomId}
            targetReady={Boolean(projection) && !cache?.loading}
            turns={projection?.turns ?? []}
          />
        </>
      ) : null}
      {cancelTarget ? (
        <CancelObservationDialog
          onClose={closeCancelDialog}
          onConfirm={confirmCancel}
          pending={cache?.controlPending?.observationId === cancelTarget.observationId}
          target={cancelTarget}
        />
      ) : null}
      {recoverTarget ? (
        <RuntimeRecoverDialog
          onClose={closeRecoverDialog}
          onConfirm={confirmRecover}
          pending={store.runtimeRecoverPending}
        />
      ) : null}
      {memoryRebuildTarget ? (
        <MemoryRebuildDialog
          onClose={closeMemoryRebuildDialog}
          onConfirm={confirmMemoryRebuild}
          pending={store.memoryRebuildPending}
        />
      ) : null}
    </div>
  );
}
