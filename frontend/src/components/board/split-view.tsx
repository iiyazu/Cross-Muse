"use client";

import { useState } from "react";

import { formatClock } from "@/components/room/format";
import { AgentQuote } from "@/components/ui/agent-quote";
import { FamilyDot } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/overlay";
import { boardContractKindLabel, boardDecidedViaLabel, boardReasonLabel, boardSplitStatusLabel } from "@/lib/board-labels";
import type { BoardSplit } from "@/lib/board-types";
import { useRoomStore } from "@/store/room-store";

import type { BoardPeople } from "./board-context";

/**
 * A lead's split proposal. Approval is the operator's decision: it goes through the fixed
 * route with the split's digest, so the human approves exactly the plan shown here.
 */
export function SplitView({ roomId, split, people }: { roomId: string; split: BoardSplit; people: BoardPeople }) {
  const decide = useRoomStore((state) => state.decideBoardSplit);
  const pending = useRoomStore((state) => state.boardActionPending);
  const error = useRoomStore((state) => state.boardActionError);
  const [confirmReject, setConfirmReject] = useState(false);
  const action = split.actions?.decide;
  const decidable = split.status === "proposed" && Boolean(action?.available) && Boolean(action?.expected_digest);
  const busy = pending?.splitId === split.split_id;
  const via = boardDecidedViaLabel(split.decided_via);

  return (
    <div className="pb-6">
      <div className="px-4 pt-3 pb-3">
        <h3 className="m-0 text-base font-semibold text-fg">拆分提案 · {split.modules.length} 个模块</h3>
        <p className="m-0 mt-1 text-xs text-fg-3">
          {people.name(split.proposed_by_participant_id)} 提出 · {formatClock(split.created_at)} · {boardSplitStatusLabel(split.status)}
          {split.decided_at ? ` · ${formatClock(split.decided_at)}${via ? ` 经由${via}` : ""}决定` : ""}
        </p>
        {decidable ? (
          <p className="m-0 mt-2 text-ui text-fg-2">
            批准后，每个模块的负责人会拿到章程并开始工作；契约先于代码。驳回后 lead 需要重新提议。
          </p>
        ) : null}
      </div>

      <ol className="m-0 list-none border-t border-line p-0">
        {split.modules.map((module) => (
          <li className="border-b border-line px-4 py-2.5" key={module.module_id}>
            <p className="m-0 flex items-center gap-2">
              <code className="font-mono text-ui font-medium text-fg">{module.module_id}</code>
              <span className="flex-1" />
              <FamilyDot family={people.family(module.owner_participant_id)} />
              <span className="text-xs text-fg-2">{people.name(module.owner_participant_id)}</span>
            </p>
            {module.title.text.trim() && module.title.text.trim() !== module.module_id ? (
              <AgentQuote className="mt-1 text-xs" clamp={2} inline value={module.title} />
            ) : null}
            <dl className="m-0 mt-1.5 grid grid-cols-[3.5rem_1fr] gap-x-2 gap-y-0.5 text-xs">
              <dt className="text-fg-3">路径</dt>
              <dd className="m-0 flex flex-wrap gap-1">
                {module.paths.length ? module.paths.map((path) => <code className="rounded-sm bg-raised px-1 font-mono text-fg-2" key={path}>{path}</code>) : <span className="text-fg-3">无</span>}
              </dd>
              {module.provides.length ? (
                <>
                  <dt className="text-fg-3">提供</dt>
                  <dd className="m-0 font-mono text-fg-2">{module.provides.join("、")}</dd>
                </>
              ) : null}
              {module.depends.length ? (
                <>
                  <dt className="text-fg-3">依赖</dt>
                  <dd className="m-0 font-mono text-fg-2">{module.depends.join("、")}</dd>
                </>
              ) : null}
            </dl>
          </li>
        ))}
      </ol>

      {split.contracts.length ? (
        <section className="px-4 pt-3">
          <h4 className="m-0 mb-1.5 text-xs font-medium text-fg-3">先行契约</h4>
          <ul className="m-0 list-none space-y-0.5 p-0 text-xs">
            {split.contracts.map((contract) => (
              <li key={contract.contract_id}>
                <code className="font-mono text-fg-2">{contract.contract_id}</code>
                <span className="text-fg-3"> · {boardContractKindLabel(contract.kind)} · 由 {contract.provider_module_id} 提供</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {decidable ? (
        <div className="sticky bottom-0 mt-4 flex items-center gap-2 border-t border-line bg-canvas px-4 py-3">
          {error && pending === null ? (
            <span className="min-w-0 flex-1 truncate text-xs text-fail" role="alert">
              {error.status === 409 ? "提案已经变化，已刷新。" : boardReasonLabel(error.code)}
            </span>
          ) : <span className="flex-1" />}
          <Button disabled={busy} onClick={() => setConfirmReject(true)} size="sm" variant="ghost">驳回</Button>
          <Button disabled={busy} onClick={() => void decide(split, "approve", roomId)} size="sm" variant="primary">
            {busy && pending?.kind === "approve" ? "正在批准…" : "批准拆分"}
          </Button>
        </div>
      ) : null}

      <ConfirmDialog
        confirmLabel="驳回拆分"
        description="Lead 会收到驳回，需要重新提议。这个决定会记录在房间里。"
        onConfirm={async () => {
          await decide(split, "reject", roomId);
          setConfirmReject(false);
        }}
        onOpenChange={setConfirmReject}
        open={confirmReject}
        pending={busy}
        title="驳回这个拆分？"
      />
    </div>
  );
}
