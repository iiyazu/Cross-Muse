"use client";

import { useEffect } from "react";

import { formatClock } from "@/components/room/format";
import { AgentQuote } from "@/components/ui/agent-quote";
import { cx } from "@/components/ui/cx";
import { boardContractKindLabel } from "@/lib/board-labels";
import type { RoomBoardProjection } from "@/lib/board-types";
import { useRoomStore } from "@/store/room-store";

import type { BoardPeople, PanelView } from "./board-context";

/** §5 contract content: agent-authored, rendered as a plain-text code block only. */
export function ContractView({
  roomId,
  contractId,
  version,
  projection,
  people,
  onNavigate
}: {
  roomId: string;
  contractId: string;
  version?: number;
  projection: RoomBoardProjection;
  people: BoardPeople;
  onNavigate: (view: PanelView) => void;
}) {
  const detail = useRoomStore((state) => state.boardByRoom[roomId]?.contractDetails[contractId] ?? null);
  const load = useRoomStore((state) => state.loadBoardContract);
  const summary = projection.contracts.find((contract) => contract.contract_id === contractId) ?? null;

  useEffect(() => {
    void load(contractId, version, roomId);
  }, [contractId, load, roomId, version, summary?.latest_version]);

  const shownVersion = detail?.contract_id === contractId ? detail.version : null;
  const dependents = projection.modules.filter((module) => module.depends.includes(contractId));
  const stale = projection.stale_dependents.filter((item) => item.contract_id === contractId);

  return (
    <div className="pb-6">
      <div className="px-4 pt-3 pb-3">
        <h3 className="m-0 font-mono text-base font-semibold break-all text-fg">{contractId}</h3>
        {summary ? (
          <p className="m-0 mt-1 text-xs text-fg-3">
            {boardContractKindLabel(summary.kind)} · 提供方
            <button className="mx-1 font-mono text-fg-2 underline decoration-line-strong underline-offset-2" onClick={() => onNavigate({ kind: "module", moduleId: summary.provider_module_id })} type="button">
              {summary.provider_module_id}
            </button>
            · 共 {summary.versions_count} 版
          </p>
        ) : null}
        {dependents.length ? (
          <p className="m-0 mt-1 text-xs text-fg-3">
            依赖它的模块：
            {dependents.map((module) => {
              const isStale = stale.some((item) => item.module_id === module.module_id);
              return (
                <button
                  className={cx("mx-0.5 font-mono underline underline-offset-2", isStale ? "text-attn decoration-attn-line" : "text-fg-2 decoration-line-strong")}
                  key={module.module_id}
                  onClick={() => onNavigate({ kind: "module", moduleId: module.module_id })}
                  title={isStale ? "契约修订后还没有跟进" : undefined}
                  type="button"
                >
                  {module.module_id}{isStale ? "（待跟进）" : ""}
                </button>
              );
            })}
          </p>
        ) : null}
      </div>
      {detail && detail.contract_id === contractId ? (
        <>
          {detail.versions.length > 1 ? (
            <div className="flex flex-wrap gap-1 border-t border-line px-4 py-2">
              {detail.versions.map((entry) => (
                <button
                  aria-pressed={entry.version === shownVersion}
                  className={cx(
                    "rounded-sm px-1.5 font-mono text-xs leading-5",
                    entry.version === shownVersion ? "bg-selected text-fg" : "text-fg-3 hover:bg-hover hover:text-fg"
                  )}
                  key={entry.version}
                  onClick={() => onNavigate({ kind: "contract", contractId, version: entry.version })}
                  type="button"
                >
                  v{entry.version}
                </button>
              ))}
            </div>
          ) : null}
          {detail.versions.filter((entry) => entry.version === shownVersion).map((entry) => (
            <div className="border-t border-line px-4 py-2 text-xs text-fg-3" key={entry.version}>
              v{entry.version} · {people.name(entry.author_participant_id)} · {formatClock(entry.created_at)}
              {entry.rationale ? <AgentQuote className="mt-1.5 text-ui" value={entry.rationale} /> : null}
            </div>
          ))}
          <div className="border-t border-line px-4 pt-3">
            <p className="m-0 mb-1.5 text-[11px] text-fg-3">契约内容由 Agent 撰写，按纯文本显示</p>
            <pre className="scrollbar-quiet m-0 max-h-[60vh] overflow-auto rounded-md border border-line bg-sunken px-3 py-2.5 font-mono text-[12px] leading-5 whitespace-pre-wrap text-fg-2">
              {detail.content.text}
            </pre>
            {detail.content.truncated ? <p className="m-0 mt-1 text-[11px] text-fg-3">内容过长，已截断。</p> : null}
          </div>
        </>
      ) : (
        <p className="m-0 border-t border-line px-4 py-6 text-center text-ui text-fg-3" role="status">正在读取契约…</p>
      )}
    </div>
  );
}
