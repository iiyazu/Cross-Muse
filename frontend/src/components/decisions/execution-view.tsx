"use client";

import { useEffect, useState } from "react";
import { useShallow } from "zustand/react/shallow";

import { formatClock } from "@/components/room/format";
import { TrustGlyph } from "@/components/board/trust";
import { AgentQuote } from "@/components/ui/agent-quote";
import { Button } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { DiffView } from "@/components/ui/diff-view";
import { ConfirmDialog } from "@/components/ui/overlay";
import { boardReasonLabel } from "@/lib/board-labels";
import type { RoomExecutionCancelDescriptor, RoomExecutionDecisionDescriptor } from "@/lib/types";
import { useRoomStore } from "@/store/room-store";

const RUN_STATE: Record<string, string> = {
  requested: "已请求",
  preparing: "准备中",
  staging: "在隔离区应用",
  gating: "跑门禁",
  promoting: "提升到工作区",
  succeeded: "已完成",
  failed: "失败",
  blocked: "被拦下",
  cancelled: "已取消"
};

const ASSESSMENT: Record<string, string> = { endorse: "赞成", object: "反对", abstain: "弃权", pending: "未表态" };

type Confirm =
  | { kind: "execute" | "reject"; descriptor: RoomExecutionDecisionDescriptor }
  | { kind: "cancel"; runId: string; descriptor: RoomExecutionCancelDescriptor };

/**
 * An exact-patch execution candidate. Executing applies exactly this diff in an isolated
 * worktree; it is promoted only after every fixed gate passes and the workspace guard holds.
 */
export function ExecutionView({ roomId, candidateId }: { roomId: string; candidateId: string }) {
  const { detail, list, pending, error } = useRoomStore(useShallow((state) => ({
    detail: state.executionsByRoom[roomId]?.details[candidateId] ?? null,
    list: state.executionsByRoom[roomId]?.list ?? null,
    pending: state.executionActionPending,
    error: state.executionActionError
  })));
  const select = useRoomStore((state) => state.selectExecutionCandidate);
  const decide = useRoomStore((state) => state.decideExecutionCandidate);
  const cancelRun = useRoomStore((state) => state.cancelExecutionRun);
  const [confirm, setConfirm] = useState<Confirm | null>(null);

  useEffect(() => {
    void select(candidateId);
    return () => { void select(null); };
  }, [candidateId, select]);

  if (!detail) return <p className="m-0 px-4 py-6 text-center text-ui text-fg-3" role="status">正在读取执行候选…</p>;

  const { candidate, run, actions, vote_counts: votes } = detail;
  const profile = detail.gate_profile ?? list?.gate_profile ?? null;
  const profileReady = profile?.readiness.ready === true;
  const busy = pending !== null && (pending.targetId === candidateId || pending.targetId === run?.run_id);
  const summary = candidate.summary ? { text: candidate.summary, untrusted: true as const, truncated: false } : null;

  return (
    <div className="pb-6">
      <div className="px-4 pt-3 pb-3">
        <h3 className="m-0 text-base font-semibold text-fg">执行候选</h3>
        <p className="m-0 mt-1 text-xs text-fg-3">
          {candidate.author.display_name ?? "Agent"} 提出 · {formatClock(candidate.created_at)} · {candidate.file_count} 个文件 · {candidate.byte_count} 字节
        </p>
        {summary ? <AgentQuote className="mt-2.5 text-ui" value={summary} /> : null}
      </div>

      <section className="border-t border-line px-4 py-3">
        <h4 className="m-0 mb-2 text-xs font-medium text-fg-3">执行前的保障</h4>
        <ul className="m-0 list-none space-y-1.5 p-0 text-xs">
          <li className="flex items-start gap-2">
            <TrustGlyph className="mt-px" tone={profileReady ? "pass" : "attn"} />
            <span className="text-fg-2">
              门禁配置 {profile ? <code className="font-mono">{profile.profile_id}</code> : "未知"}
              {profile ? `：${profile.gate_ids.join("、") || "无门禁"}` : ""}
              {!profileReady && profile ? <span className="text-attn">（未就绪：{boardReasonLabel(profile.readiness.code)}）</span> : null}
            </span>
          </li>
          <li className="flex items-start gap-2">
            <TrustGlyph className="mt-px" tone={votes.object > 0 ? "fail" : votes.pending > 0 ? "running" : votes.endorse >= votes.required ? "pass" : "empty"} />
            <span className="text-fg-2">
              同伴意见：赞成 {votes.endorse} · 反对 {votes.object} · 弃权 {votes.abstain} · 未表态 {votes.pending}
              {votes.required ? `（共识需要 ${votes.required}）` : ""}
            </span>
          </li>
          <li className="flex items-start gap-2">
            <TrustGlyph className="mt-px" tone="claim" />
            <span className="text-fg-2">只会应用下面这份精确的补丁，先在隔离区跑门禁，全部通过才会进入工作区。</span>
          </li>
        </ul>
        {detail.votes.length ? (
          <ul className="m-0 mt-2.5 list-none space-y-1 border-t border-line p-0 pt-2.5">
            {detail.votes.map((vote) => (
              <li className="text-xs" key={vote.participant_id}>
                <span className="text-fg-2">{vote.display_name ?? "Agent"}</span>
                <span className={cx("ml-1.5", vote.assessment === "object" ? "text-fail" : vote.assessment === "endorse" ? "text-proof" : "text-fg-3")}>
                  {ASSESSMENT[vote.assessment] ?? vote.assessment}
                </span>
                {vote.rationale ? (
                  <span className="mt-0.5 block pl-3"><AgentQuote clamp={3} inline value={{ text: vote.rationale, untrusted: true, truncated: false }} /></span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      {run ? (
        <section className="border-t border-line px-4 py-3">
          <div className="mb-2 flex items-center gap-2">
            <h4 className="m-0 flex-1 text-xs font-medium text-fg-3">执行：{RUN_STATE[run.state] ?? run.state}</h4>
            {run.actions.cancel.available ? (
              <Button disabled={busy} onClick={() => setConfirm({ kind: "cancel", runId: run.run_id, descriptor: run.actions.cancel })} size="sm" variant="ghost">
                取消执行
              </Button>
            ) : null}
          </div>
          {run.reason_code ? <p className="m-0 mb-1.5 text-xs text-fail">{boardReasonLabel(run.reason_code)}</p> : null}
          <ul className="m-0 list-none space-y-1 p-0">
            {run.gates.map((gate) => (
              <li className="flex items-center gap-2 text-xs" key={gate.gate_id}>
                <TrustGlyph tone={gate.state === "passed" ? "pass" : gate.state === "failed" ? "fail" : gate.state === "running" ? "running" : "empty"} />
                <code className="font-mono text-fg-2">{gate.gate_id}</code>
                <span className="text-fg-3">{gate.label}</span>
                {gate.reason_code ? <span className="text-fail">{boardReasonLabel(gate.reason_code)}</span> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="border-t border-line pt-3">
        <h4 className="m-0 mb-2 px-4 text-xs font-medium text-fg-3">补丁 · {candidate.files.length} 个文件</h4>
        <ul className="m-0 mb-2 list-none space-y-0.5 px-4 text-xs">
          {candidate.files.map((file) => (
            <li className="flex gap-2" key={file.path}>
              <span className="w-10 shrink-0 text-fg-3">{file.change_type}</span>
              <code className="min-w-0 truncate font-mono text-fg-2">{file.path}</code>
            </li>
          ))}
        </ul>
        <DiffView className="max-h-[50vh] border-y border-line" label="执行候选的补丁" text={candidate.unified_diff} />
      </section>

      {actions.execute.available || actions.reject.available ? (
        <div className="sticky bottom-0 flex items-center gap-2 border-t border-line bg-canvas px-4 py-3">
          {error && !busy ? (
            <span className="min-w-0 flex-1 truncate text-xs text-fail" role="alert">
              {error.status === 409 ? "候选已经变化，已刷新。" : "操作没有成功，请重试。"}
            </span>
          ) : <span className="flex-1" />}
          {actions.reject.available ? (
            <Button disabled={busy} onClick={() => setConfirm({ kind: "reject", descriptor: actions.reject })} size="sm" variant="ghost">拒绝</Button>
          ) : null}
          {actions.execute.available ? (
            <Button disabled={busy || !profileReady} onClick={() => setConfirm({ kind: "execute", descriptor: actions.execute })} size="sm" variant="primary">
              执行补丁
            </Button>
          ) : null}
        </div>
      ) : null}

      <ConfirmDialog
        confirmLabel={confirm?.kind === "execute" ? "执行" : confirm?.kind === "reject" ? "拒绝候选" : "取消执行"}
        description={confirm?.kind === "execute"
          ? "宿主会在隔离区应用这份补丁并跑全部固定门禁；全部通过、工作区也没有变化时才会写入。"
          : confirm?.kind === "reject"
            ? "拒绝会结束这个候选，不改动工作区。"
            : "只有在写入工作区之前才能取消；已经进入写入阶段时后端会拒绝。"}
        onConfirm={async () => {
          if (!confirm) return;
          if (confirm.kind === "cancel") await cancelRun(confirm.runId, confirm.descriptor);
          else await decide(candidateId, confirm.kind, confirm.descriptor);
          setConfirm(null);
        }}
        onOpenChange={(open) => { if (!open) setConfirm(null); }}
        open={Boolean(confirm)}
        pending={busy}
        title={confirm?.kind === "execute" ? "执行这份补丁？" : confirm?.kind === "reject" ? "拒绝这个候选？" : "取消这次执行？"}
        tone={confirm?.kind === "execute" ? "primary" : "danger"}
      />
    </div>
  );
}
