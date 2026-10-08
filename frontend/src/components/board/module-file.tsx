"use client";

import { useEffect } from "react";
import { GitBranch, ShieldCheck } from "lucide-react";

import { AgentQuote } from "@/components/ui/agent-quote";
import { FamilyDot, familyLabel, familyOf } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { cx } from "@/components/ui/cx";
import { boardReviewFindingsText, boardReviewSeverityLabel, shortHeadCommit } from "@/lib/board-review-labels";
import { boardReasonLabel } from "@/lib/board-labels";
import type { BoardModule, RoomBoardProjection } from "@/lib/board-types";
import { useRoomStore } from "@/store/room-store";

import type { BoardPeople, PanelView } from "./board-context";
import { EventList } from "./event-list";
import { trustSteps } from "./model";
import { TrustLadder } from "./trust";
import { VerificationGates } from "./verification-gates";

function Section({ title, children, aside }: { title: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <section aria-label={title} className="border-t border-line px-4 py-3">
      <div className="mb-2 flex items-center gap-2">
        <h4 className="m-0 flex-1 text-xs font-medium tracking-wide text-fg-3">{title}</h4>
        {aside}
      </div>
      {children}
    </section>
  );
}

const COUNTERS: Array<[keyof BoardModule["counters"], string]> = [
  ["done_reports", "声明完成"],
  ["passed", "验证通过"],
  ["failed", "验证未通过"],
  ["errored", "验证异常"],
  ["superseded", "被新声明取代"],
  ["rework_rounds", "首次通过前返工"],
  ["reviews_endorsed", "复核背书"],
  ["reviews_objected", "复核驳回"],
  ["integrations_conflicted", "集成冲突"],
  ["integrations_gate_failed", "集成门禁失败"],
  ["conflict_fix_rounds", "首次集成前冲突"]
];

function ReviewBlock({
  roomId,
  module,
  people,
  onStartReview
}: {
  roomId: string;
  module: BoardModule;
  people: BoardPeople;
  onStartReview?: (moduleId: string) => void;
}) {
  const { review } = module;
  const detail = useRoomStore((state) => (review.review_id ? state.boardByRoom[roomId]?.reviewDetails[review.review_id] ?? null : null));
  const loadReview = useRoomStore((state) => state.loadBoardReview);
  useEffect(() => {
    if (review.review_id && review.status !== "none") void loadReview(review.review_id, roomId);
  }, [loadReview, review.review_id, review.status, review.updated_at, roomId]);

  if (review.status === "none") {
    return <p className="m-0 text-xs text-fg-3">当前验证还没有进入复核。</p>;
  }
  const operator = review.reviewer_kind === "operator";
  const reviewer = operator ? "你" : people.name(review.reviewer_participant_id);
  const findings = boardReviewFindingsText(review.findings_count);
  const picked = detail?.rule_inputs;
  return (
    <div className="flex flex-col gap-2 text-ui">
      <p className="m-0 flex flex-wrap items-center gap-x-1.5 text-fg-2">
        <span>作者</span>
        <FamilyDot family={familyOf(review.author_family)} />
        <span className="text-fg">{people.name(module.owner_participant_id)}</span>
        <span aria-hidden="true" className="text-fg-3">→</span>
        <span>复核人</span>
        {!operator ? <FamilyDot family={familyOf(review.reviewer_family)} /> : null}
        <span className="text-fg">{reviewer}</span>
        {review.rule_id ? <code className="ml-1 font-mono text-[11px] text-fg-3">{review.rule_id}</code> : null}
      </p>
      {review.escalated_from ? (
        <p className="m-0 text-xs text-attn">原复核人 {people.name(review.escalated_from.participant_id)}：{boardReasonLabel(review.escalated_from.reason_code)}，已转给你</p>
      ) : null}
      {findings ? <p className="m-0 text-xs text-fg-2">意见：{findings}</p> : null}
      {detail?.summary ? <AgentQuote value={detail.summary} /> : null}
      {detail?.findings.length ? (
        <ul className="m-0 list-none space-y-1.5 p-0">
          {detail.findings.map((finding, index) => (
            <li className="flex gap-2 text-xs" key={index}>
              <span className={cx("shrink-0 font-medium", finding.severity === "blocker" ? "text-fail" : finding.severity === "major" ? "text-attn" : "text-fg-3")}>
                {boardReviewSeverityLabel(finding.severity)}
              </span>
              <span className="min-w-0 flex-1">
                {finding.path ? <code className="mr-1.5 font-mono text-fg-2">{finding.path}</code> : null}
                <AgentQuote inline value={finding.text} />
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      {picked ? (
        <details className="text-xs text-fg-3">
          <summary className="cursor-pointer select-none hover:text-fg-2">为什么由{operator ? "你" : ` ${reviewer} `}复核</summary>
          <div className="mt-1.5 rounded-md bg-sunken px-3 py-2">
            <p className="m-0">规则 <code className="font-mono">{picked.rule_id}</code>：作者家族 {familyLabel(familyOf(picked.author_family)) ?? picked.author_family} 不能复核自己。</p>
            {picked.eligible.length ? (
              <p className="m-0 mt-1">
                可选复核人：{picked.eligible.map((candidate) => `${people.name(candidate.participant_id)}（${familyLabel(familyOf(candidate.family)) ?? candidate.family}，待办 ${candidate.pending}）`).join("、")}
              </p>
            ) : <p className="m-0 mt-1">房间里没有其他家族的 Agent，所以由你复核。</p>}
            {picked.last_reviewer_participant_id ? <p className="m-0 mt-1">优先上次的复核人：{people.name(picked.last_reviewer_participant_id)}</p> : null}
          </div>
        </details>
      ) : null}
      {operator && review.status === "pending" && onStartReview ? (
        <Button className="self-start" onClick={() => onStartReview(module.module_id)} size="sm" variant="attn">
          <ShieldCheck aria-hidden="true" className="size-3.5" /> 开始复核
        </Button>
      ) : null}
    </div>
  );
}

export function ModuleFile({
  roomId,
  module,
  projection,
  people,
  onNavigate,
  onStartReview
}: {
  roomId: string;
  module: BoardModule;
  projection: RoomBoardProjection;
  people: BoardPeople;
  onNavigate: (view: PanelView) => void;
  onStartReview?: (moduleId: string) => void;
}) {
  const steps = trustSteps(module, projection.capabilities, (id) => (id ? people.name(id) : null));
  const events = projection.events.filter((event) => event.module_id === module.module_id);
  const titleDiffers = module.title.text.trim() && module.title.text.trim() !== module.module_id;
  const verification = module.verification;
  return (
    <div className="pb-6">
      <div className="px-4 pt-3 pb-3">
        <div className="flex items-center gap-2">
          <h3 className="m-0 font-mono text-base font-semibold text-fg">{module.module_id}</h3>
          {module.accepted ? <span className="rounded-sm bg-proof-soft px-1.5 text-xs leading-5 font-medium text-proof">已验收</span> : null}
          <span className="flex-1" />
          <span className="text-xs text-fg-3">章程 v{module.charter_version}</span>
        </div>
        <p className="m-0 mt-1 flex items-center gap-1.5 text-xs text-fg-3">
          <FamilyDot family={people.family(module.owner_participant_id)} />
          负责人 <span className="text-fg-2">{people.name(module.owner_participant_id)}</span>
          {module.report_to ? <>· 汇报给 <span className="text-fg-2">{people.name(module.report_to)}</span></> : null}
        </p>
        {titleDiffers ? <AgentQuote className="mt-2.5 text-ui" value={module.title} /> : null}
      </div>

      <Section title="信任链">
        <TrustLadder steps={steps} />
        {verification.head_commit || verification.changed_path_count ? (
          <p className="m-0 mt-2.5 text-xs text-fg-3">
            {verification.head_commit ? <>验证的提交 <code className="font-mono text-fg-2">{shortHeadCommit(verification.head_commit)}</code></> : null}
            {verification.changed_path_count ? ` · 改动 ${verification.changed_path_count} 个文件` : ""}
            {verification.stacked.length ? ` · 叠加了上游 ${verification.stacked.map((item) => item.module_id).join("、")}` : ""}
          </p>
        ) : null}
        {module.verification.reason_code && module.verification.status !== "passed" ? (
          <p className="m-0 mt-1 text-xs text-fail">{boardReasonLabel(module.verification.reason_code)}</p>
        ) : null}
      </Section>

      {(verification.status === "failed" || verification.status === "error") && verification.verification_id ? (
        <Section title={verification.status === "failed" ? "返工：为什么没通过" : "验证出错"}>
          <VerificationGates roomId={roomId} verificationId={verification.verification_id} />
        </Section>
      ) : null}

      {projection.capabilities.reviews === 1 ? (
        <Section title="复核">
          <ReviewBlock module={module} onStartReview={onStartReview} people={people} roomId={roomId} />
        </Section>
      ) : null}

      {projection.capabilities.integrations === 1 && module.integration.integration_id ? (
        <Section
          aside={
            <Button onClick={() => onNavigate({ kind: "integration", integrationId: module.integration.integration_id! })} size="sm" variant="ghost">
              <GitBranch aria-hidden="true" className="size-3.5" /> 集成详情
            </Button>
          }
          title="集成"
        >
          <p className="m-0 text-xs text-fg-2">
            {module.integration.reason_code ? boardReasonLabel(module.integration.reason_code) : "最近一次集成作业包含这个模块。"}
          </p>
        </Section>
      ) : null}

      <Section title="章程">
        <dl className="m-0 grid grid-cols-[4.5rem_1fr] gap-x-3 gap-y-1.5 text-xs">
          <dt className="text-fg-3">路径</dt>
          <dd className="m-0 flex flex-wrap gap-1">
            {module.paths.length ? module.paths.map((path) => (
              <code className="rounded-sm bg-raised px-1 font-mono text-fg-2" key={path}>{path}</code>
            )) : <span className="text-fg-3">无</span>}
          </dd>
          <dt className="text-fg-3">提供契约</dt>
          <dd className="m-0 flex flex-wrap gap-1">
            {module.provides.length ? module.provides.map((contract) => (
              <button className="rounded-sm border border-line px-1 font-mono text-fg-2 hover:border-line-strong hover:text-fg" key={contract} onClick={() => onNavigate({ kind: "contract", contractId: contract })} type="button">
                {contract}
              </button>
            )) : <span className="text-fg-3">无</span>}
          </dd>
          <dt className="text-fg-3">依赖契约</dt>
          <dd className="m-0 flex flex-wrap gap-1">
            {module.depends.length ? module.depends.map((contract) => (
              <button className="rounded-sm border border-line px-1 font-mono text-fg-2 hover:border-line-strong hover:text-fg" key={contract} onClick={() => onNavigate({ kind: "contract", contractId: contract })} type="button">
                {contract}
              </button>
            )) : <span className="text-fg-3">无</span>}
          </dd>
        </dl>
      </Section>

      <Section title="计数（board_metrics/v1）">
        <dl className="m-0 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          {COUNTERS.map(([key, label]) => (
            <div className="flex items-baseline justify-between gap-2" key={key}>
              <dt className="text-fg-3">{label}</dt>
              <dd className={cx("m-0 font-mono tabular-nums", module.counters[key] ? "text-fg" : "text-fg-3")}>{module.counters[key]}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <section className="border-t border-line pt-3">
        <h4 className="m-0 mb-2 px-4 text-xs font-medium tracking-wide text-fg-3">证据</h4>
        <EventList events={events} people={people} />
      </section>
    </div>
  );
}
