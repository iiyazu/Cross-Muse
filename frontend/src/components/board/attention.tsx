"use client";

import { ChevronRight, Hourglass } from "lucide-react";

import { Button } from "@/components/ui/button";
import { boardAttentionReasonLabel } from "@/lib/board-labels";
import type { BoardAttentionItem, RoomBoardProjection } from "@/lib/board-types";

import type { BoardPeople, PanelView } from "./board-context";
import { TrustGlyph } from "./trust";

type Copy = { title: string; detail: string | null; action: string; view: PanelView | null };

function operatorCopy(item: BoardAttentionItem, projection: RoomBoardProjection | null, people: BoardPeople): Copy {
  switch (item.reason_code) {
    case "board_attention_split_pending": {
      const split = projection?.splits.find((candidate) => candidate.split_id === item.split_id) ?? null;
      return {
        title: "审批模块拆分",
        detail: split ? `${people.name(split.proposed_by_participant_id)} 提议拆成 ${split.modules.length} 个模块` : null,
        action: "查看拆分",
        view: item.split_id ? { kind: "split", splitId: item.split_id } : null
      };
    }
    case "board_attention_review_operator_pending": {
      const target = projection?.modules.find((candidate) => candidate.module_id === item.module_id) ?? null;
      const escalated = target?.review.escalated_from ? "原复核人没有给出结论，转给你" : "房间里没有其他家族的 Agent，由你复核";
      return {
        title: `复核模块 ${item.module_id ?? ""}`.trim(),
        detail: escalated,
        action: "开始复核",
        view: item.module_id ? { kind: "module", moduleId: item.module_id } : null
      };
    }
    case "board_attention_verification_error":
      return {
        title: `模块 ${item.module_id ?? ""} 验证异常`.trim(),
        detail: "宿主没能完成验证，需要你看一下环境",
        action: "查看",
        view: item.module_id ? { kind: "module", moduleId: item.module_id } : null
      };
    case "board_attention_integration_error":
      return {
        title: "集成异常",
        detail: "宿主会按 10 分钟、30 分钟和重启后各重试一次",
        action: "查看详情",
        view: item.integration_id ? { kind: "integration", integrationId: item.integration_id } : null
      };
    default:
      return {
        title: boardAttentionReasonLabel(item.reason_code),
        detail: null,
        action: "查看",
        view: item.module_id ? { kind: "module", moduleId: item.module_id } : item.integration_id ? { kind: "integration", integrationId: item.integration_id } : null
      };
  }
}

export function attentionKey(item: BoardAttentionItem): string {
  return [item.kind, item.reason_code, item.module_id, item.split_id, item.integration_id].join(":");
}

/** One decision the human owns. */
export function DecisionCard({
  item,
  projection,
  people,
  onNavigate,
  onStartReview
}: {
  item: BoardAttentionItem;
  projection: RoomBoardProjection | null;
  people: BoardPeople;
  onNavigate: (view: PanelView) => void;
  /** Operator reviews open the review dialog directly instead of the module file. */
  onStartReview?: (moduleId: string) => void;
}) {
  const copy = operatorCopy(item, projection, people);
  const review = item.reason_code === "board_attention_review_operator_pending" && item.module_id && onStartReview;
  return (
    <li className="flex items-start gap-3 rounded-md border border-attn-line bg-attn-soft px-3 py-2.5">
      <TrustGlyph className="mt-0.5" tone="attn" />
      <div className="min-w-0 flex-1">
        <p className="m-0 text-ui font-medium text-fg">{copy.title}</p>
        {copy.detail ? <p className="m-0 mt-0.5 text-xs text-fg-2">{copy.detail}</p> : null}
      </div>
      {review ? (
        <Button onClick={() => onStartReview(item.module_id!)} size="sm" variant="secondary">
          {copy.action}
        </Button>
      ) : copy.view ? (
        <Button onClick={() => copy.view && onNavigate(copy.view)} size="sm" variant="secondary">
          {copy.action}
        </Button>
      ) : null}
    </li>
  );
}

const WHO: Record<string, string> = { lead: "Lead", owner: "Owner" };

/** Items an agent has to act on: informational, collapsed by default. */
export function WaitingOnAgents({
  items,
  projection,
  people,
  onNavigate
}: {
  items: BoardAttentionItem[];
  projection: RoomBoardProjection | null;
  people: BoardPeople;
  onNavigate: (view: PanelView) => void;
}) {
  if (!items.length) return null;
  const lead = projection?.participants.find((participant) => participant.is_lead) ?? null;
  return (
    <details className="group rounded-md border border-line">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-ui text-fg-2 select-none [&::-webkit-details-marker]:hidden">
        <Hourglass aria-hidden="true" className="size-3.5 text-fg-3" />
        <span className="flex-1">{items.length} 项在等 Agent 处理</span>
        <ChevronRight aria-hidden="true" className="size-3.5 text-fg-4 transition-transform group-open:rotate-90" />
      </summary>
      <ul className="m-0 list-none border-t border-line p-0">
        {items.map((item) => {
          const target = item.module_id ? projection?.modules.find((candidate) => candidate.module_id === item.module_id) : null;
          const who = item.kind === "owner" && target
            ? people.name(target.owner_participant_id)
            : item.kind === "lead"
              ? (target?.report_to ? people.name(target.report_to) : lead?.display_name ?? "Lead")
              : WHO[item.kind] ?? "Agent";
          const view: PanelView | null = item.module_id
            ? { kind: "module", moduleId: item.module_id }
            : item.integration_id ? { kind: "integration", integrationId: item.integration_id } : null;
          return (
            <li key={attentionKey(item)}>
              <button
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-hover disabled:cursor-default disabled:hover:bg-transparent"
                disabled={!view}
                onClick={() => view && onNavigate(view)}
                type="button"
              >
                <span className="w-12 shrink-0 text-fg-3">{WHO[item.kind] ?? item.kind}</span>
                <span className="shrink-0 text-fg-2">{who}</span>
                <span className="min-w-0 flex-1 truncate text-fg-3">
                  {boardAttentionReasonLabel(item.reason_code)}
                  {item.module_id ? <code className="ml-1.5 font-mono text-fg-2">{item.module_id}</code> : null}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </details>
  );
}
