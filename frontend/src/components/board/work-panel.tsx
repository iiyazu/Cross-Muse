"use client";

import { useMemo, useState } from "react";
import { useShallow } from "zustand/react/shallow";
import { ArrowLeft, ChevronRight, GitCommitHorizontal, X } from "lucide-react";

import { IconButton } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { boardIntegrationJobStatusLabel } from "@/lib/board-integration-labels";
import { boardContractKindLabel } from "@/lib/board-labels";
import { boardReviewPolicyLabel } from "@/lib/board-review-labels";
import { useRoomStore } from "@/store/room-store";

import { attentionKey, DecisionCard, WaitingOnAgents } from "./attention";
import { useBoardPeople, type PanelView } from "./board-context";
import { ContractView } from "./contract-view";
import { EventList } from "./event-list";
import { IntegrationDetail } from "./integration-detail";
import { boardOverview, boardVisible, splitAttention, TRUST_LABELS, TRUST_ORDER } from "./model";
import { ModuleFile } from "./module-file";
import { ModuleList } from "./module-list";
import { SplitView } from "./split-view";
import { LevelSwatch, SegmentBar } from "./trust";

function SectionHeading({ children, count }: { children: React.ReactNode; count?: number }) {
  return (
    <h3 className="m-0 flex items-baseline gap-1.5 px-4 pt-4 pb-2 text-xs font-medium tracking-wide text-fg-3">
      {children}
      {typeof count === "number" ? <span className="font-normal text-fg-4">{count}</span> : null}
    </h3>
  );
}

const VIEW_TITLES: Record<PanelView["kind"], string> = {
  board: "工作",
  module: "模块",
  integration: "集成详情",
  contract: "契约",
  split: "拆分提案"
};

/**
 * The progressive work dock: decisions first, then the board, then history. Detail views
 * stack inside the panel with a back step, so the timeline never loses its place. Callers key
 * the panel by room, so the stack starts over in every room.
 */
export function WorkPanel({ roomId, docked, onClose }: { roomId: string; docked: boolean; onClose: () => void }) {
  const { projection, summary, error, loading } = useRoomStore(useShallow((state) => ({
    projection: state.boardByRoom[roomId]?.projection ?? null,
    summary: state.boardByRoom[roomId]?.summary ?? null,
    error: state.boardByRoom[roomId]?.error ?? null,
    loading: state.boardByRoom[roomId]?.loading ?? false
  })));
  const people = useBoardPeople(projection);
  const [stack, setStack] = useState<PanelView[]>([{ kind: "board" }]);
  const view = stack[stack.length - 1];

  const navigate = (next: PanelView) => setStack((current) => [...current, next]);
  const back = () => setStack((current) => (current.length > 1 ? current.slice(0, -1) : current));

  const overview = useMemo(() => boardOverview(projection, summary), [projection, summary]);
  const attention = useMemo(() => splitAttention(projection?.attention ?? summary?.attention ?? []), [projection, summary]);
  const visible = boardVisible(projection, summary);

  let body: React.ReactNode;
  if (view.kind === "module") {
    const target = projection?.modules.find((candidate) => candidate.module_id === view.moduleId) ?? null;
    body = target && projection
      ? <ModuleFile module={target} onNavigate={navigate} people={people} projection={projection} roomId={roomId} />
      : <p className="m-0 px-4 py-6 text-center text-ui text-fg-3">这个模块已不在当前章程里。</p>;
  } else if (view.kind === "integration") {
    body = <IntegrationDetail integrationId={view.integrationId} onNavigate={navigate} roomId={roomId} />;
  } else if (view.kind === "contract") {
    body = projection
      ? <ContractView contractId={view.contractId} onNavigate={navigate} people={people} projection={projection} roomId={roomId} version={view.version} />
      : null;
  } else if (view.kind === "split") {
    const split = projection?.splits.find((candidate) => candidate.split_id === view.splitId) ?? null;
    body = split
      ? <SplitView people={people} roomId={roomId} split={split} />
      : <p className="m-0 px-4 py-6 text-center text-ui text-fg-3">找不到这个拆分提案。</p>;
  } else if (!visible) {
    body = (
      <div className="px-6 py-10 text-center">
        <p className="m-0 text-ui font-medium text-fg">这个房间没有模块看板</p>
        <p className="m-0 mt-1.5 text-xs text-fg-3">
          {loading && !projection && !summary
            ? "正在读取看板…"
            : error && !projection
              ? "看板暂时读不到，稍后会自动重试。"
              : "当 lead 提出拆分、宿主开始验证模块时，进度会出现在这里。"}
        </p>
      </div>
    );
  } else {
    const capabilities = projection?.capabilities ?? summary!.capabilities;
    const integrations = capabilities.integrations === 1;
    const latest = projection?.integration.latest ?? null;
    const greenHead = projection?.integration.green_head_commit ?? summary?.integration.green_head_commit ?? null;
    const legend = TRUST_ORDER.filter((level) => overview.levels[level] > 0);
    const decidedSplits = projection?.splits.filter((split) => split.status !== "proposed") ?? [];
    body = (
      <>
        <section aria-label="完成度" className="px-4 pt-4 pb-4">
          <div className="flex items-end gap-3">
            <p className="m-0 tabular-nums">
              <span className="text-stat font-semibold tracking-tight text-fg">{overview.accepted}</span>
              <span className="text-lg text-fg-3">/{overview.total}</span>
            </p>
            <p className="m-0 pb-1 text-ui text-fg-2">已验收</p>
            <span className="flex-1" />
            {integrations ? (
              <p className="m-0 pb-1 text-ui tabular-nums text-fg-2">
                <span className="font-semibold text-fg">{overview.integrated}</span> 已集成
              </p>
            ) : null}
          </div>
          <SegmentBar className="mt-2.5 h-2" segments={overview.segments} />
          {legend.length ? (
            <ul className="m-0 mt-2 flex list-none flex-wrap gap-x-3 gap-y-1 p-0 text-[11px] text-fg-3">
              {legend.map((level) => (
                <li className="flex items-center gap-1.5" key={level}>
                  <LevelSwatch level={level} />
                  {TRUST_LABELS[level]} <span className="tabular-nums text-fg-2">{overview.levels[level]}</span>
                </li>
              ))}
            </ul>
          ) : null}
          <p className="m-0 mt-2 text-[11px] text-fg-3">
            只有宿主验证通过{capabilities.reviews === 1 ? "并经跨家族复核背书" : ""}的模块才算验收；Agent 自称完成不计入。
          </p>
          {integrations ? (
            <button
              className="mt-3 flex w-full items-center gap-2 rounded-md border border-line px-3 py-2 text-left text-xs transition-colors hover:bg-hover disabled:hover:bg-transparent"
              disabled={!latest}
              onClick={() => latest && navigate({ kind: "integration", integrationId: latest.integration_id })}
              type="button"
            >
              <GitCommitHorizontal aria-hidden="true" className="size-3.5 shrink-0 text-fg-3" />
              <span className="text-fg-3">集成分支</span>
              {greenHead ? <code className="font-mono text-fg-2">{greenHead.slice(0, 7)}</code> : <span className="text-fg-3">尚无绿色提交</span>}
              <span className="flex-1" />
              {latest ? (
                <span className={cx(latest.status === "integrated" ? "text-proof" : latest.status === "pending" || latest.status === "running" ? "text-live" : "text-fail")}>
                  最近一次{boardIntegrationJobStatusLabel(latest.status, latest.statusRaw)}
                </span>
              ) : null}
              {latest ? <ChevronRight aria-hidden="true" className="size-3.5 text-fg-4" /> : null}
            </button>
          ) : null}
        </section>

        {attention.mine.length || attention.agents.length ? (
          <section aria-label="待处理" className="border-t border-line">
            {attention.mine.length ? (
              <>
                <SectionHeading count={attention.mine.length}>待你处理</SectionHeading>
                <ul className="m-0 flex list-none flex-col gap-2 px-4 p-0">
                  {attention.mine.map((item) => (
                    <DecisionCard item={item} key={attentionKey(item)} onNavigate={navigate} people={people} projection={projection} />
                  ))}
                </ul>
              </>
            ) : null}
            <div className={cx("px-4 pb-3", attention.mine.length ? "pt-2" : "pt-3")}>
              <WaitingOnAgents items={attention.agents} onNavigate={navigate} people={people} projection={projection} />
            </div>
          </section>
        ) : null}

        {projection?.modules.length ? (
          <section aria-label="模块" className="border-t border-line">
            <SectionHeading count={projection.modules.length}>模块</SectionHeading>
            <ModuleList capabilities={capabilities} modules={projection.modules} onOpen={(moduleId) => navigate({ kind: "module", moduleId })} people={people} />
          </section>
        ) : null}

        {projection?.contracts.length ? (
          <details className="group border-t border-line">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 px-4 py-3 text-xs font-medium tracking-wide text-fg-3 select-none hover:text-fg-2 [&::-webkit-details-marker]:hidden">
              契约 <span className="font-normal text-fg-4">{projection.contracts.length}</span>
              <span className="flex-1" />
              <ChevronRight aria-hidden="true" className="size-3.5 text-fg-4 transition-transform group-open:rotate-90" />
            </summary>
            <ul className="m-0 list-none p-0 pb-2">
              {projection.contracts.map((contract) => (
                <li key={contract.contract_id}>
                  <button className="flex w-full items-center gap-2 px-4 py-1.5 text-left text-xs hover:bg-hover" onClick={() => navigate({ kind: "contract", contractId: contract.contract_id })} type="button">
                    <code className="min-w-0 truncate font-mono text-fg">{contract.contract_id}</code>
                    <span className="text-fg-3">v{contract.latest_version}</span>
                    <span className="flex-1" />
                    <span className="text-fg-3">{boardContractKindLabel(contract.kind)} · {contract.provider_module_id}</span>
                  </button>
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        {projection?.events.length ? (
          <details className="group border-t border-line">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 px-4 py-3 text-xs font-medium tracking-wide text-fg-3 select-none hover:text-fg-2 [&::-webkit-details-marker]:hidden">
              最近动态 <span className="font-normal text-fg-4">{projection.events.length}</span>
              <span className="flex-1" />
              <ChevronRight aria-hidden="true" className="size-3.5 text-fg-4 transition-transform group-open:rotate-90" />
            </summary>
            <EventList events={projection.events} onOpenModule={(moduleId) => navigate({ kind: "module", moduleId })} people={people} showModule />
          </details>
        ) : null}

        {decidedSplits.length ? (
          <details className="group border-t border-line">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 px-4 py-3 text-xs font-medium tracking-wide text-fg-3 select-none hover:text-fg-2 [&::-webkit-details-marker]:hidden">
              拆分记录 <span className="font-normal text-fg-4">{decidedSplits.length}</span>
              <span className="flex-1" />
              <ChevronRight aria-hidden="true" className="size-3.5 text-fg-4 transition-transform group-open:rotate-90" />
            </summary>
            <ul className="m-0 list-none p-0 pb-2">
              {decidedSplits.map((split) => (
                <li key={split.split_id}>
                  <button className="flex w-full items-center gap-2 px-4 py-1.5 text-left text-xs hover:bg-hover" onClick={() => navigate({ kind: "split", splitId: split.split_id })} type="button">
                    <span className="text-fg-2">{people.name(split.proposed_by_participant_id)} 提议 {split.modules.length} 个模块</span>
                    <span className="flex-1" />
                    <span className={cx(split.status === "approved" ? "text-proof" : split.status === "rejected" ? "text-fail" : "text-fg-3")}>
                      {split.status === "approved" ? "已批准" : split.status === "rejected" ? "已驳回" : "已取代"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        {projection ? (
          <p className="m-0 border-t border-line px-4 py-3 text-[11px] text-fg-4">{boardReviewPolicyLabel(projection.review_policy)}</p>
        ) : null}
      </>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-canvas">
      <div className="flex h-12 shrink-0 items-center gap-1 border-b border-line px-2">
        {stack.length > 1 ? (
          <IconButton label="返回" onClick={back} size="sm">
            <ArrowLeft aria-hidden="true" className="size-4" />
          </IconButton>
        ) : null}
        <h2 className={cx("m-0 flex-1 text-sm font-semibold text-fg", stack.length > 1 ? "pl-0.5" : "pl-2")}>{VIEW_TITLES[view.kind]}</h2>
        <IconButton label={docked ? "收起工作面板" : "关闭工作面板"} onClick={onClose} size="sm">
          <X aria-hidden="true" className="size-4" />
        </IconButton>
      </div>
      <div className="scrollbar-quiet min-h-0 flex-1 overflow-y-auto" key={stack.length}>
        {body}
      </div>
    </div>
  );
}
