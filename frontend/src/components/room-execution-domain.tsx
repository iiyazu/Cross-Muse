"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import type {
  RoomExecutionCancelDescriptor,
  RoomExecutionDecisionDescriptor,
  RoomExecutionPolicyMode,
  RoomExecutionPolicyUpdateDescriptor
} from "@/lib/types";
import type { RoomExecutionCache } from "@/store/domain";

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
export function RoomExecutionDomain({
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
