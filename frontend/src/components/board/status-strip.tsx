"use client";

import { useMemo } from "react";
import { useShallow } from "zustand/react/shallow";
import { ChevronRight, GitCommitHorizontal } from "lucide-react";

import { cx } from "@/components/ui/cx";
import { boardIntegrationJobStatusLabel } from "@/lib/board-integration-labels";
import { useRoomStore } from "@/store/room-store";

import { boardOverview, boardVisible } from "./model";
import { SegmentBar } from "./trust";
import { useNeedsYou } from "./use-needs-you";

/** The glance layer: true completion, the integration branch and what waits for the human. */
export function StatusStrip({ roomId, onOpen }: { roomId: string; onOpen: () => void }) {
  const { projection, summary } = useRoomStore(useShallow((state) => ({
    projection: state.boardByRoom[roomId]?.projection ?? null,
    summary: state.boardByRoom[roomId]?.summary ?? null
  })));
  const needsYou = useNeedsYou(roomId);
  const overview = useMemo(() => boardOverview(projection, summary), [projection, summary]);
  if (!boardVisible(projection, summary)) return null;

  const integrations = (summary?.capabilities ?? projection?.capabilities)?.integrations === 1;
  const greenHead = summary?.integration.green_head_commit ?? projection?.integration.green_head_commit ?? null;
  const jobStatus = summary?.integration.status ?? projection?.integration.latest?.status ?? null;
  const jobRaw = summary?.integration.statusRaw ?? projection?.integration.latest?.statusRaw ?? null;
  const jobBad = jobStatus === "conflicted" || jobStatus === "gate_failed" || jobStatus === "error";
  const label = `看板：${overview.total} 个模块，${overview.accepted} 个已验收${integrations ? `，${overview.integrated} 个已集成` : ""}${needsYou.total ? `，${needsYou.total} 项待你处理` : ""}。打开工作面板`;

  return (
    <button
      aria-label={label}
      className="group flex h-9 w-full shrink-0 items-center gap-3 border-b border-line bg-sunken px-4 text-left text-ui transition-colors hover:bg-[color-mix(in_oklch,var(--sunken)_70%,var(--hover))] sm:px-6"
      onClick={onOpen}
      type="button"
    >
      {overview.segments.length ? <SegmentBar className="w-20 shrink-0 sm:w-28" segments={overview.segments} /> : null}
      <span className="shrink-0 tabular-nums">
        <span className="font-semibold text-fg">{overview.accepted}</span>
        <span className="text-fg-3">/{overview.total}</span>
        <span className="ml-1 text-fg-2">已验收</span>
      </span>
      {integrations ? (
        <span className="hidden shrink-0 tabular-nums text-fg-2 sm:inline">
          <span className="text-fg-4">·</span> <span className="font-medium text-fg">{overview.integrated}</span> 已集成
        </span>
      ) : null}
      {integrations && (greenHead || jobStatus) ? (
        <span className="hidden min-w-0 items-center gap-1.5 truncate text-fg-3 md:flex">
          <span className="text-fg-4">·</span>
          <GitCommitHorizontal aria-hidden="true" className="size-3.5 shrink-0" />
          {greenHead ? <code className="font-mono text-xs text-fg-2">{greenHead.slice(0, 7)}</code> : <span>尚无绿色提交</span>}
          {jobStatus ? (
            <span className={cx("truncate", jobBad ? "text-fail" : "text-fg-3")}>
              最近一次{boardIntegrationJobStatusLabel(jobStatus, jobRaw)}
            </span>
          ) : null}
        </span>
      ) : null}
      <span className="flex-1" />
      {needsYou.total ? (
        <span className="flex shrink-0 items-center gap-1.5 rounded-full bg-attn-soft px-2 py-0.5 text-xs font-medium text-attn">
          <span aria-hidden="true" className="size-1.5 rounded-full bg-attn-solid" />
          {needsYou.total} 项待你处理
        </span>
      ) : null}
      <ChevronRight aria-hidden="true" className="size-4 shrink-0 text-fg-4 transition-transform group-hover:translate-x-0.5 group-hover:text-fg-3" />
    </button>
  );
}
