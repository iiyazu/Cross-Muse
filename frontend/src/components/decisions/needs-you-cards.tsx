"use client";

import { useState } from "react";

import { TrustGlyph } from "@/components/board/trust";
import { incidentNextStep, incidentTitle } from "@/components/system/incident-labels";
import { AgentQuote } from "@/components/ui/agent-quote";
import { Button } from "@/components/ui/button";
import type { RoomExecutionCandidateSummary, RoomMemoryCandidate, RoomOperationsIncident } from "@/lib/types";
import { useRoomStore } from "@/store/room-store";

function Card({ title, detail, children, action }: { title: string; detail?: React.ReactNode; children?: React.ReactNode; action?: React.ReactNode }) {
  return (
    <li className="flex items-start gap-3 rounded-md border border-attn-line bg-attn-soft px-3 py-2.5">
      <TrustGlyph className="mt-0.5" tone="attn" />
      <div className="min-w-0 flex-1">
        <p className="m-0 text-ui font-medium text-fg">{title}</p>
        {detail ? <p className="m-0 mt-0.5 text-xs text-fg-2">{detail}</p> : null}
        {children}
      </div>
      {action}
    </li>
  );
}

export function ExecutionCard({ candidate, onOpen }: { candidate: RoomExecutionCandidateSummary; onOpen: () => void }) {
  return (
    <Card
      action={<Button onClick={onOpen} size="sm">查看补丁</Button>}
      detail={`${candidate.author.display_name ?? "Agent"} 提出 · ${candidate.file_count} 个文件 · 赞成 ${candidate.votes.endorse} / 反对 ${candidate.votes.object}`}
      title="决定是否执行补丁"
    />
  );
}

const MEMORY_KIND: Record<string, string> = {
  user_preference: "你的偏好",
  project_rule: "项目规则",
  room_fact: "房间事实",
  room_decision: "房间决定"
};

/**
 * A memory candidate that becomes durable for you or the project once approved. Its text is
 * agent-authored, so it is quoted; the decision is bound to the candidate's digest and revision.
 */
export function MemoryCard({ candidate, proposer }: { candidate: RoomMemoryCandidate; proposer: string }) {
  const resolve = useRoomStore((state) => state.resolveMemoryCandidate);
  const pending = useRoomStore((state) => state.memoryActionPending);
  const busy = pending?.candidateId === candidate.candidate_id;
  const [failed, setFailed] = useState(false);
  async function decide(decision: "approve" | "reject") {
    const ok = await resolve(candidate.candidate_id, decision, candidate.actions.resolve);
    setFailed(!ok);
  }
  const allowed = candidate.actions.resolve.allowed_decisions;
  return (
    <Card
      detail={`${proposer} 提议 · 引用了 ${candidate.source_activity_ids.length} 条房间记录`}
      title={`记住一条${MEMORY_KIND[candidate.kind] ?? "记忆"}`}
    >
      <AgentQuote className="mt-2 text-ui" value={{ text: candidate.content, untrusted: true, truncated: false }} />
      <div className="mt-2 flex items-center gap-2">
        {allowed.includes("approve") ? (
          <Button disabled={busy} onClick={() => void decide("approve")} size="sm" variant="primary">
            {busy && pending?.decision === "approve" ? "正在记住…" : "记住"}
          </Button>
        ) : null}
        {allowed.includes("reject") ? (
          <Button disabled={busy} onClick={() => void decide("reject")} size="sm" variant="ghost">不记</Button>
        ) : null}
        {failed ? <span className="text-xs text-fail" role="alert">没有成功，已刷新为最新状态。</span> : null}
      </div>
    </Card>
  );
}

export function IncidentCard({ incident, onOpenSystem }: { incident: RoomOperationsIncident; onOpenSystem: () => void }) {
  return (
    <Card
      action={<Button onClick={onOpenSystem} size="sm">去处理</Button>}
      detail={`${incident.participant_display_name ? `影响 ${incident.participant_display_name}` : "影响本机所有房间"} · ${incidentNextStep(incident)}`}
      title={incidentTitle(incident)}
    />
  );
}
