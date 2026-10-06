"use client";

import { useEffect, useState } from "react";

import { formatClock } from "@/components/room/format";
import { Button } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { fetchBoardIntegrationDetail, escapeInvalidIntegrationPath, isValidIntegrationPath } from "@/lib/board-integration-api";
import {
  boardIntegrationGateText,
  boardIntegrationItemStatusLabel,
  boardIntegrationJobStatusLabel,
  boardIntegrationRoleLabel
} from "@/lib/board-integration-labels";
import type { BoardIntegrationDetail as Detail, BoardIntegrationItem } from "@/lib/board-integration-types";
import { boardReasonLabel } from "@/lib/board-labels";

import type { PanelView } from "./board-context";
import type { StepTone } from "./model";
import { TrustGlyph } from "./trust";

const ITEM_TONE: Record<string, StepTone> = {
  applied: "pass",
  fell_back: "fail",
  conflicted: "fail",
  waiting: "wait",
  not_applied: "empty"
};

function ItemRow({ item, onOpenModule }: { item: BoardIntegrationItem; onOpenModule: (moduleId: string) => void }) {
  const tone = ITEM_TONE[item.status] ?? "empty";
  return (
    <li className="flex gap-3 px-4 py-2">
      <span className="w-4 shrink-0 pt-0.5 text-right font-mono text-[11px] text-fg-4">{item.order}</span>
      <TrustGlyph className="mt-0.5" tone={tone} />
      <div className="min-w-0 flex-1">
        <p className="m-0 flex flex-wrap items-baseline gap-x-2 text-ui">
          <button className="font-mono font-medium text-fg underline decoration-line-strong underline-offset-2 hover:decoration-fg-3" onClick={() => onOpenModule(item.module_id)} type="button">
            {item.module_id}
          </button>
          <span className="text-xs text-fg-3">{boardIntegrationRoleLabel(item.role, item.roleRaw)}</span>
          <span className={cx("text-xs", tone === "pass" ? "text-proof" : tone === "fail" ? "text-fail" : "text-fg-2")}>
            {boardIntegrationItemStatusLabel(item.status, item.statusRaw)}
          </span>
        </p>
        {item.status === "fell_back" ? (
          <p className="m-0 mt-0.5 text-xs text-fg-3">新版本冲突，集成分支里保留了上一个已验收版本。</p>
        ) : null}
        {item.conflicts.length ? (
          <ul className="m-0 mt-1 list-none space-y-0.5 p-0">
            {item.conflicts.map((conflict) => {
              const valid = isValidIntegrationPath(conflict.path);
              return (
                <li className="text-xs" key={conflict.path}>
                  <code className={cx("font-mono", valid ? "text-fg-2" : "text-fail")}>
                    {valid ? conflict.path : escapeInvalidIntegrationPath(conflict.path)}
                  </code>
                  {conflict.attributed_module_ids.length ? (
                    <span className="text-fg-3"> · 章程覆盖它的模块：{conflict.attributed_module_ids.join("、")}</span>
                  ) : null}
                </li>
              );
            })}
            {item.conflicts_total > item.conflicts.length ? (
              <li className="text-xs text-fg-3">另有 {item.conflicts_total - item.conflicts.length} 个冲突路径未列出</li>
            ) : null}
          </ul>
        ) : null}
      </div>
    </li>
  );
}

/** §5.3 integration detail. Web only: plugins and the CLI never read this route. */
export function IntegrationDetail({
  roomId,
  integrationId,
  onNavigate
}: {
  roomId: string;
  integrationId: string;
  onNavigate: (view: PanelView) => void;
}) {
  const [attempt, setAttempt] = useState(0);
  const requestKey = `${roomId}:${integrationId}:${attempt}`;
  const [result, setResult] = useState<{ key: string; detail: Detail | null; failed: boolean } | null>(null);
  const current = result?.key === requestKey ? result : null;
  const detail = current?.detail ?? null;
  const failed = current?.failed ?? false;

  useEffect(() => {
    const controller = new AbortController();
    fetchBoardIntegrationDetail(roomId, integrationId, { signal: controller.signal })
      .then((value) => setResult({ key: requestKey, detail: value, failed: false }))
      .catch(() => {
        if (!controller.signal.aborted) setResult({ key: requestKey, detail: null, failed: true });
      });
    return () => controller.abort();
  }, [roomId, integrationId, requestKey]);

  if (failed && !detail) {
    return (
      <div className="px-4 py-6 text-center">
        <p className="m-0 text-ui text-fg-2">集成详情暂时读不到。</p>
        <Button className="mt-3" onClick={() => setAttempt((value) => value + 1)} size="sm">重试</Button>
      </div>
    );
  }
  if (!detail) return <p className="m-0 px-4 py-6 text-center text-ui text-fg-3" role="status">正在读取集成详情…</p>;

  const good = detail.status === "integrated";
  return (
    <div className="pb-6">
      <div className="px-4 pt-3 pb-3">
        <p className="m-0 flex items-center gap-2">
          <TrustGlyph tone={good ? "pass" : detail.status === "error" ? "attn" : detail.status === "pending" || detail.status === "running" ? "running" : "fail"} />
          <span className="text-base font-semibold text-fg">集成：{boardIntegrationJobStatusLabel(detail.status, detail.statusRaw)}</span>
        </p>
        <p className="m-0 mt-1 text-xs text-fg-3">
          {detail.finished_at ? `${formatClock(detail.finished_at)} 完成` : "尚未完成"} · 第 {detail.attempt_count} 次尝试
          {detail.reason_code && !good ? ` · ${boardReasonLabel(detail.reason_code)}` : ""}
        </p>
        <dl className="m-0 mt-3 grid grid-cols-[5.5rem_1fr] gap-x-3 gap-y-1 text-xs">
          <dt className="text-fg-3">集成分支现在</dt>
          <dd className="m-0">{detail.green_head_commit ? <code className="font-mono text-fg-2">{detail.green_head_commit.slice(0, 12)}</code> : <span className="text-fg-3">还没有绿色提交</span>}</dd>
          <dt className="text-fg-3">本次结果</dt>
          <dd className="m-0">
            {detail.result_commit ? <code className="font-mono text-fg-2">{detail.result_commit.slice(0, 12)}</code> : <span className="text-fg-3">没有跑到门禁</span>}
            {detail.result_commit && !good ? <span className="text-fg-3">（门禁未通过，分支没有移动）</span> : null}
          </dd>
        </dl>
      </div>

      <section className="border-t border-line pt-3">
        <h4 className="m-0 mb-1 px-4 text-xs font-medium tracking-wide text-fg-3">应用顺序（依赖优先，在先的先于新加入的）</h4>
        <ol className="m-0 list-none p-0">
          {detail.items.map((item) => (
            <ItemRow item={item} key={`${item.module_id}:${item.order}`} onOpenModule={(moduleId) => onNavigate({ kind: "module", moduleId })} />
          ))}
        </ol>
      </section>

      {detail.gates.length ? (
        <section className="border-t border-line pt-3">
          <h4 className="m-0 mb-1 px-4 text-xs font-medium tracking-wide text-fg-3">门禁</h4>
          <ul className="m-0 list-none p-0">
            {detail.gates.map((gate) => (
              <li className="px-4 py-2" key={gate.gate_id}>
                <p className="m-0 flex flex-wrap items-baseline gap-x-2 text-ui">
                  <code className="font-mono text-fg">{gate.gate_id}</code>
                  <span className={cx("text-xs", gate.status === "passed" ? "text-proof" : gate.status === "failed" || gate.status === "error" ? "text-fail" : "text-fg-3")}>
                    {boardIntegrationGateText(gate)}
                  </span>
                  {gate.exit_code !== null ? <span className="font-mono text-[11px] text-fg-3">exit {gate.exit_code}</span> : null}
                </p>
                {gate.output_tail ? (
                  <figure className="m-0 mt-1.5">
                    <figcaption className="mb-1 text-[11px] text-fg-3">门禁输出末尾（已清洗，按纯文本显示）</figcaption>
                    <pre className="scrollbar-quiet m-0 max-h-56 overflow-auto rounded-md border border-line bg-sunken px-3 py-2 font-mono text-[11.5px] leading-[1.15rem] whitespace-pre-wrap text-fg-2">
                      {gate.output_tail.text}
                    </pre>
                    {gate.output_tail.truncated ? <p className="m-0 mt-1 text-[11px] text-fg-3">输出过长，只保留了末尾。</p> : null}
                  </figure>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
