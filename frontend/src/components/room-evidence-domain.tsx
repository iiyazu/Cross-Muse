"use client";

import { Fragment } from "react";

import { roomParticipantStateLabel, roomStateLabel } from "@/lib/room-view";
import type {
  RoomControlActionDescriptor,
  RoomObservationBatchEvidence,
  RoomObservationFrontier,
  RoomParticipant,
  RoomSkillDecision,
  RoomTurn,
  RoomTurnParticipant
} from "@/lib/types";
import type { RoomCache } from "@/store/domain";
import { formatRoomTime as formatTime, identityStyle, initials } from "./room-header";
import type { RoomCancelTarget } from "./room-turn-status";

function shortDigest(value: string): string {
  const digest = value.startsWith("sha256:") ? value : `sha256:${value}`;
  return digest.length > 19 ? `${digest.slice(0, 19)}…` : digest;
}

export function RoomSkillDecisionEvidence({
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

export function RoomObservationBatchDetails({
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
        {coverage ? <>
          <dt>覆盖</dt><dd>{coverage.included_member_count}/{evidence.member_count ?? refs.length}{coverage.omitted_member_count ? ` · 省略 ${coverage.omitted_member_count}` : " · 无省略"}</dd>
          <dt>截止 seq</dt><dd>{coverage.cutoff_room_seq}</dd>
        </> : null}
      </dl>
      {refs.length ? <details>
        <summary>Batch activity refs · {refs.length}</summary>
        {refs.map((ref) => <code key={`${ref.activity_id}:${ref.room_seq}`}>{ref.activity_id} · #{ref.room_seq}</code>)}
      </details> : null}
    </section>
  );
}

function recoveryStateLabel(state: "fenced" | "cleanup_pending" | "recovered"): string {
  return { fenced: "已隔离失效运行", cleanup_pending: "正在清理旧运行", recovered: "运行恢复已完成" }[state];
}

function recoveryNextActionLabel(action: "cleanup_pending" | "will_retry" | "will_exhaust" | "none"): string {
  return { cleanup_pending: "等待清理完成", will_retry: "将重新进入处理", will_exhaust: "将标记尝试耗尽", none: "无需后续恢复动作" }[action];
}

export function RoomAttemptDetails({ frontier }: { frontier?: RoomObservationFrontier | null }) {
  if (!frontier) return <small>当前没有未完成 observation</small>;
  const attempt = frontier.current_attempt;
  const recovery = attempt?.recovery;
  const times = [
    ["Claim", attempt?.claimed_at], ["Transport", attempt?.transport_started_at],
    ["Expires", attempt?.expires_at], ["Finished", attempt?.finished_at], ["Updated", attempt?.updated_at]
  ].filter((entry): entry is [string, string] => Boolean(entry[1]));
  return <>
    <dl className="room-attempt-details">
      <dt>控制状态</dt><dd>{frontier.control_state ?? "active"}</dd>
      <dt>控制序号</dt><dd>{frontier.control_seq ?? 0}</dd>
      <dt>人工预算</dt><dd>{frontier.manual_retry_budget ?? 0}</dd>
      {attempt ? <>
        <dt>Attempt</dt><dd>{attempt.attempt_number} / {attempt.effective_attempt_limit}</dd>
        <dt>Attempt 状态</dt><dd>{attempt.state}</dd>
        <dt>原因</dt><dd>{attempt.reason_code ?? "—"}</dd>
        {recovery && recovery.state !== "none" ? <>
          <dt>恢复状态</dt><dd>{recoveryStateLabel(recovery.state)}</dd>
          <dt>恢复原因</dt><dd>{recovery.reason_code ?? "—"}</dd>
          <dt>恢复后续</dt><dd>{recoveryNextActionLabel(recovery.next_action)}</dd>
          {recovery.started_at ? <><dt>恢复开始</dt><dd title={recovery.started_at}>{formatTime(recovery.started_at)}</dd></> : null}
          {recovery.completed_at ? <><dt>恢复完成</dt><dd title={recovery.completed_at}>{formatTime(recovery.completed_at)}</dd></> : null}
        </> : null}
        {times.map(([label, value]) => <Fragment key={label}><dt>{label}</dt><dd title={value}>{formatTime(value)}</dd></Fragment>)}
      </> : <><dt>Attempt</dt><dd>尚无当前 attempt</dd></>}
    </dl>
    <RoomObservationBatchDetails evidence={frontier} label="当前 frontier batch" />
    <RoomSkillDecisionEvidence decision={attempt?.skill_decision} label="当前 frontier Skill" />
  </>;
}

export function RoomEvidenceDomain({
  participants,
  turns,
  controlPending,
  onCancel,
  onRetry
}: {
  participants: RoomParticipant[];
  turns: RoomTurn[];
  controlPending: RoomCache["controlPending"];
  onCancel: (target: RoomCancelTarget) => void;
  onRetry: (observationId: string, descriptor: RoomControlActionDescriptor) => void;
}) {
  const activeTurnCount = turns.filter((turn) => turn.state !== "settled").length;
  return <>
    <section>
      <h3>活跃成员</h3>
      <div className="room-inspector-members">
        {participants.map((participant) => <article key={participant.participant_id}>
          <span className="room-avatar" style={identityStyle(participant.participant_id)}>{initials(participant.display_name)}</span>
          <div><strong>{participant.display_name}</strong><span>{participant.mention_handle} · {participant.role}</span></div>
          <small>{participant.active ? "会观察新活动" : "已停止"}</small>
        </article>)}
      </div>
    </section>
    {turns.length ? <section>
      <h3>{activeTurnCount ? `进行中轮次 · ${activeTurnCount}` : "最近轮次"}</h3>
      <div className="room-inspector-active-turns">
        {turns.map((turn) => <article className="room-inspector-turn" key={turn.correlation_id}>
          <header><strong>{roomStateLabel(turn.state)}</strong><code title={turn.correlation_id}>{turn.correlation_id}</code></header>
          <small>Observations {turn.observation_count} · Attempts {turn.attempt_count} · Skill decisions {turn.skill_decision_count}{turn.excluded_stopped_count ? ` · 停止成员遗留 ${turn.excluded_stopped_count}` : ""}</small>
          <div className="room-inspector-turns">
            {turn.participants.map((participant: RoomTurnParticipant) => {
              const frontier = participant.frontier;
              const observationId = frontier?.observation_id ?? "";
              const cancel = frontier?.actions?.cancel;
              const retry = frontier?.actions?.retry;
              const pending = controlPending?.observationId === observationId;
              return <article data-observation-id={observationId || undefined} key={`${turn.correlation_id}:${participant.participant_id}`} tabIndex={-1}>
                <div className="room-inspector-agent-heading">
                  <span><strong>{participant.display_name}</strong><small>{roomParticipantStateLabel(participant.state ?? participant.status)} · {participant.unresolved_count} 个未完成</small></span>
                  <span className="room-inspector-controls">
                    <button aria-label={`取消 ${participant.display_name} 在轮次 ${turn.correlation_id} 的处理`} className="room-control-button is-cancel" disabled={pending || !cancel?.available || !observationId} onClick={() => cancel?.available && observationId && onCancel({ observationId, participant, descriptor: cancel })} title={cancel?.available ? "只取消该 Agent 当前 delivery" : "当前没有可取消的 delivery"} type="button">取消</button>
                    <button aria-label={`重试 ${participant.display_name} 在轮次 ${turn.correlation_id} 的 observation`} className="room-control-button is-retry" disabled={pending || !retry?.available || !observationId} onClick={() => retry?.available && observationId && onRetry(observationId, retry)} title={retry?.available ? "重新开放同一 observation" : "仅已取消或尝试耗尽的 observation 可重试"} type="button">重试</button>
                  </span>
                </div>
                <RoomSkillDecisionEvidence decision={participant.root_skill_decision} label="Human-root Skill" />
                <RoomAttemptDetails frontier={frontier} />
                <RoomSkillDecisionEvidence decision={participant.latest_outcome?.skill_decision} label="最新 outcome Skill" />
                <RoomObservationBatchDetails evidence={participant.latest_outcome} label="最新 outcome batch" />
              </article>;
            })}
          </div>
        </article>)}
      </div>
    </section> : null}
    <details className="room-advanced-proof"><summary>高级核验</summary><p>界面状态只来自 chat.db 的 Room projection。Provider 文本和浏览器遥测不是群聊事实。</p></details>
  </>;
}
