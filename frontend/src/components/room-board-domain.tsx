import { useEffect, useRef, useState, type KeyboardEvent } from "react";

import { sanitizeAgentTextValue } from "@/lib/board-api";
import {
  boardAttentionKindLabel,
  boardAttentionReasonLabel,
  boardContractKindLabel,
  boardDecidedViaLabel,
  boardEventKindLabel,
  boardLifecycleLabel,
  boardReasonLabel,
  boardSplitStatusLabel,
  boardStateLabel,
  boardVerificationStatusLabel
} from "@/lib/board-labels";
import type {
  AgentText,
  BoardAttentionItem,
  BoardEvent,
  BoardModule,
  BoardSplit,
  RoomBoardProjection
} from "@/lib/board-types";
import type { RoomBoardCache } from "@/store/domain/board";
import { Check, Hourglass, TriangleAlert } from "lucide-react";

import { boardReviewPolicyLabel } from "@/lib/board-review-labels";
import { AcceptedMark, ReviewChip } from "./room-board-review-chip";
import { ReviewDetailDisclosure } from "./room-board-review-detail";
import { OperatorReviewPanel } from "./room-board-review-panel";
import { RoomGrantsDomain } from "./room-grants-domain";

export function AgentTextView({
  value,
  monospace = false
}: {
  value: AgentText | null | undefined;
  monospace?: boolean;
}) {
  if (!value) return null;
  const clean = sanitizeAgentTextValue(value.text);
  const body = (
    <>
      <span className="room-board-agent-label">agent 自述 · 未验证</span>
      <span className="room-board-agent-text">{clean}</span>
      {value.truncated ? <span className="room-board-agent-truncated">…（已截断）</span> : null}
    </>
  );
  if (monospace) {
    return (
      <pre className="room-board-agent room-board-agent--pre" data-testid="agent-text-view">
        {body}
      </pre>
    );
  }
  return (
    <span className="room-board-agent" data-testid="agent-text-view">
      {body}
    </span>
  );
}

function participantName(projection: RoomBoardProjection | null, participantId: string | null): string {
  if (!participantId) return "—";
  const found = projection?.participants.find((item) => item.participant_id === participantId);
  return found?.display_name ?? participantId;
}

function providerKindOf(projection: RoomBoardProjection | null, participantId: string): string {
  const found = projection?.participants.find((item) => item.participant_id === participantId);
  return found?.provider_kind ?? "unknown";
}

function StateBadge({ state }: { state: BoardModule["state"] }) {
  const label = boardStateLabel(state);
  if (state === "verified") {
    return (
      <span
        aria-label={`已验证：宿主验证已通过，非自称完成`}
        className="room-board-badge is-verified"
        data-state="verified"
        role="status"
      >
        <Check aria-hidden="true" size={13} />
        <span>已验证</span>
      </span>
    );
  }
  if (state === "done_claimed") {
    return (
      <span
        aria-label={`自称完成 · 未验证：Owner 自称完成，宿主尚未验证`}
        className="room-board-badge is-claimed"
        data-state="done_claimed"
        role="status"
      >
        <Hourglass aria-hidden="true" size={13} />
        <span>自称完成 · 未验证</span>
      </span>
    );
  }
  if (state === "verification_failed") {
    return (
      <span
        aria-label={`验证失败：宿主验证未通过，需返工`}
        className="room-board-badge is-failed"
        data-state="verification_failed"
        role="status"
      >
        <TriangleAlert aria-hidden="true" size={13} />
        <span>{label}</span>
      </span>
    );
  }
  if (state === "verification_error") {
    return (
      <span
        aria-label={`验证异常：宿主验证异常，需要人工介入`}
        className="room-board-badge is-error"
        data-state="verification_error"
        role="status"
      >
        <TriangleAlert aria-hidden="true" size={13} />
        <span>{label} · 需要人工介入</span>
      </span>
    );
  }
  if (state === "verifying") {
    return (
      <span
        aria-label={`验证中：宿主正在验证 Owner 的完成报告`}
        className="room-board-badge is-verifying"
        data-state="verifying"
        role="status"
      >
        <span aria-hidden="true" className="room-board-spinner" />
        <span>{label}</span>
      </span>
    );
  }
  return (
    <span
      aria-label={`模块状态：${label}`}
      className="room-board-badge is-muted"
      data-state={state}
      role="status"
    >
      <span>{label}</span>
    </span>
  );
}

const COUNT_ORDER: Array<BoardModule["state"]> = [
  "verified",
  "verifying",
  "waiting_for_provider",
  "verification_failed",
  "verification_error",
  "done_claimed",
  "ready_for_review",
  "working",
  "claimed",
  "assigned",
  "blocked"
];

function CountsRow({ projection }: { projection: RoomBoardProjection }) {
  const counts = new Map<string, number>();
  for (const boardModule of projection.modules) {
    counts.set(boardModule.state, (counts.get(boardModule.state) ?? 0) + 1);
  }
  const chips = COUNT_ORDER.flatMap((state) => {
    const count = counts.get(state) ?? 0;
    if (!count) return [];
    return [{ state, count }];
  });
  if (!chips.length) return null;
  return (
    <div aria-label="模块状态统计" className="room-board-counts">
      {chips.map((chip) => (
        <span className="room-board-chip" data-state={chip.state} key={chip.state}>
          {boardStateLabel(chip.state)} {chip.count}
        </span>
      ))}
    </div>
  );
}

function AttentionStrip({
  items,
  onViewSplit
}: {
  items: BoardAttentionItem[];
  onViewSplit?: (splitId: string) => void;
}) {
  if (!items.length) return null;
  const rank = (kind: string) => (kind === "operator" ? 0 : kind === "lead" ? 1 : 2);
  const sorted = [...items].sort((left, right) => {
    const byKind = rank(left.kind) - rank(right.kind);
    if (byKind !== 0) return byKind;
    return (left.module_id ?? left.split_id ?? "").localeCompare(right.module_id ?? right.split_id ?? "");
  });
  return (
    <ul aria-label="待处理事项" className="room-board-attention">
      {sorted.map((item, index) => (
        <li
          className={`room-board-attention-item is-${item.kind}`}
          data-kind={item.kind}
          key={`${item.kind}:${item.reason_code}:${item.module_id ?? ""}:${item.split_id ?? ""}:${index}`}
        >
          <strong>{boardAttentionKindLabel(item.kind)}</strong>
          <span>{boardAttentionReasonLabel(item.reason_code)}</span>
          {item.module_id ? <code>{item.module_id}</code> : null}
          {item.split_id ? <code>{item.split_id}</code> : null}
          {item.kind === "operator" &&
          item.reason_code === "board_attention_split_pending" &&
          item.split_id &&
          onViewSplit ? (
            <button
              className="room-quiet-button room-board-attention-jump"
              onClick={() => onViewSplit(item.split_id as string)}
              type="button"
            >
              查看拆分
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

function CountersLine({ boardModule }: { boardModule: BoardModule }) {
  const parts: string[] = [];
  if (boardModule.counters.done_reports > 0) parts.push(`完成报告 ${boardModule.counters.done_reports}`);
  if (boardModule.counters.passed > 0) parts.push(`通过 ${boardModule.counters.passed}`);
  if (boardModule.counters.failed > 0) parts.push(`失败 ${boardModule.counters.failed}`);
  if (boardModule.counters.rework_rounds > 0) parts.push(`返工 ${boardModule.counters.rework_rounds}轮`);
  if (!parts.length) return null;
  return <p className="room-board-counters">{parts.join(" · ")}</p>;
}

function ModuleCard({
  boardModule,
  projection,
  reviewsEnabled,
  conversationId
}: {
  boardModule: BoardModule;
  projection: RoomBoardProjection;
  reviewsEnabled: boolean;
  conversationId: string;
}) {
  const ownerName = participantName(projection, boardModule.owner_participant_id);
  const providerKind = providerKindOf(projection, boardModule.owner_participant_id);
  const reportToName = participantName(projection, boardModule.report_to);
  const stale = projection.stale_dependents.filter((item) => item.module_id === boardModule.module_id);
  const moduleEvents = projection.events.filter((event) => event.module_id === boardModule.module_id).slice(-5);
  const verified = boardModule.state === "verified";
  const reviewId = boardModule.review?.review_id ?? null;
  return (
    <article aria-label={`模块 ${boardModule.module_id}`} className="room-board-module">
      <header className="room-board-module-head">
        <div>
          <code>{boardModule.module_id}</code>
          <span className="room-board-provider">{providerKind}</span>
        </div>
        <span className="room-board-badges">
          <StateBadge state={boardModule.state} />
          <ReviewChip review={boardModule.review} reviewsEnabled={reviewsEnabled} />
          <AcceptedMark accepted={reviewsEnabled && boardModule.accepted === true} />
        </span>
      </header>
      {verified && !boardModule.accepted && reviewsEnabled ? (
        <p className="room-board-pending-review">已验证 · 待复核</p>
      ) : null}
      <div className="room-board-module-title">
        <AgentTextView value={boardModule.title} />
      </div>
      <p className="room-board-owner">Owner {ownerName}</p>
      <div className="room-board-axes">
        <p>
          <span>Owner 自述</span>
          <strong>{boardLifecycleLabel(boardModule.lifecycle)}</strong>
        </p>
        <div>
          <span>宿主验证</span>
          <strong>{boardVerificationStatusLabel(boardModule.verification.status)}</strong>
          {boardModule.verification.reason_code ? (
            <small>{boardReasonLabel(boardModule.verification.reason_code)}</small>
          ) : null}
          {boardModule.verification.gate_ids.length ? (
            <span className="room-board-gates">
              {boardModule.verification.gate_ids.map((gateId) => (
                <code key={gateId}>{gateId}</code>
              ))}
            </span>
          ) : null}
          {verified && boardModule.verification.head_commit ? (
            <code title={boardModule.verification.head_commit}>{boardModule.verification.head_commit.slice(0, 8)}</code>
          ) : null}
          {boardModule.verification.stacked.length ? (
            <small>上游 {boardModule.verification.stacked.map((item) => item.module_id).join("、")} 已叠加</small>
          ) : null}
        </div>
      </div>
      <CountersLine boardModule={boardModule} />
      {stale.map((item) => (
        <p className="room-board-stale" key={`${item.contract_id}:${item.revised_version}`}>
          契约 {item.contract_id} 已修订为 v{item.revised_version}，尚未跟进
        </p>
      ))}
      {reviewsEnabled && reviewId ? (
        <ReviewDetailDisclosure
          conversationId={conversationId}
          key={`detail:${conversationId}:${reviewId}`}
          reviewId={reviewId}
        />
      ) : null}
      {reviewsEnabled && boardModule.review?.actions?.decide?.available === true && reviewId ? (
        <OperatorReviewPanel
          conversationId={conversationId}
          key={`${conversationId}:${reviewId}`}
          review={boardModule.review}
          reviewId={reviewId}
        />
      ) : null}
      <details className="room-board-details">
        <summary>章程与近期事件</summary>
        <dl>
          <dt>paths</dt>
          <dd>{boardModule.paths.length ? boardModule.paths.join("、") : "—"}</dd>
          <dt>provides</dt>
          <dd>{boardModule.provides.length ? boardModule.provides.join("、") : "—"}</dd>
          <dt>depends</dt>
          <dd>{boardModule.depends.length ? boardModule.depends.join("、") : "—"}</dd>
          <dt>report_to</dt>
          <dd>{boardModule.report_to ? reportToName : "—"}</dd>
        </dl>
        {moduleEvents.length ? (
          <ul>
            {moduleEvents.map((event) => (
              <li key={event.seq}>
                <EventLine event={event} projection={projection} />
              </li>
            ))}
          </ul>
        ) : (
          <p>暂无该模块事件。</p>
        )}
      </details>
    </article>
  );
}

export type BoardSplitDecision = "approve" | "reject";

function shortSplitDigest(digest: string): string {
  const hex = digest.startsWith("sha256:") ? digest.slice("sha256:".length) : digest;
  return hex.slice(0, 12);
}

function SplitDecisionDialog({
  split,
  decision,
  ownerNameOf,
  pending,
  onClose,
  onConfirm
}: {
  split: BoardSplit;
  decision: BoardSplitDecision;
  ownerNameOf: (participantId: string) => string;
  pending: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
  }, []);
  const title = decision === "approve" ? "批准这个拆分？" : "拒绝这个拆分？";
  const consequence =
    decision === "approve"
      ? "批准后将创建章程、通知各 Owner 开工。"
      : "拒绝后将丢弃该拆分，不创建章程。";
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
      <button
        aria-label="关闭拆分确认"
        className="room-dialog-scrim"
        disabled={pending}
        onClick={onClose}
        type="button"
      />
      <div
        aria-modal="true"
        aria-labelledby="board-split-confirm-title"
        className="room-confirm-dialog"
        role="alertdialog"
      >
        <span className="room-dialog-kicker">Board split decision</span>
        <h2 id="board-split-confirm-title">{title}</h2>
        <p>{consequence}</p>
        <dl className="room-board-confirm-facts">
          <dt>模块</dt>
          <dd>
            <ul>
              {split.modules.map((item) => (
                <li key={item.module_id}>
                  <code>{item.module_id}</code>
                  <span>Owner {ownerNameOf(item.owner_participant_id)}</span>
                  <AgentTextView value={item.title} />
                </li>
              ))}
            </ul>
          </dd>
          {split.contracts.length ? (
            <>
              <dt>契约</dt>
              <dd>{split.contracts.map((item) => item.contract_id).join("、")}</dd>
            </>
          ) : null}
          <dt>摘要绑定</dt>
          <dd>
            <code title={split.digest}>{shortSplitDigest(split.digest)}</code>
          </dd>
        </dl>
        <div className="room-dialog-actions">
          <button
            className="room-quiet-button"
            disabled={pending}
            onClick={onClose}
            ref={closeRef}
            type="button"
          >
            返回
          </button>
          <button
            className={decision === "reject" ? "room-danger-button" : "room-primary-button"}
            disabled={pending}
            onClick={() => void onConfirm()}
            ref={confirmRef}
            type="button"
          >
            {pending ? "正在提交…" : "确认"}
          </button>
        </div>
      </div>
    </div>
  );
}

function SplitCard({
  split,
  projection,
  actionPending,
  cardRef,
  onRequestDecision
}: {
  split: BoardSplit;
  projection: RoomBoardProjection;
  actionPending: boolean;
  cardRef: (element: HTMLDetailsElement | null) => void;
  onRequestDecision: (split: BoardSplit, decision: BoardSplitDecision) => void;
}) {
  const proposer = participantName(projection, split.proposed_by_participant_id);
  const decideAvailable = split.status === "proposed" && split.actions?.decide?.available === true;
  const via = boardDecidedViaLabel(split.decided_via);
  return (
    <details
      className="room-board-split"
      data-split-id={split.split_id}
      id={`board-split-${split.split_id}`}
      ref={cardRef}
    >
      <summary>
        <code>{split.split_id.slice(0, 12)}…</code>
        <span>{boardSplitStatusLabel(split.status)}</span>
      </summary>
      <p>提议人 {proposer}</p>
      <ul>
        {split.modules.map((item) => (
          <li key={item.module_id}>
            <code>{item.module_id}</code>
            <span>{participantName(projection, item.owner_participant_id)}</span>
          </li>
        ))}
      </ul>
      {split.contracts.length ? <p>契约 {split.contracts.map((item) => item.contract_id).join("、")}</p> : null}
      {via ? <p className="room-board-provenance">经由 {via}</p> : null}
      {split.status === "proposed" ? (
        <div className="room-board-split-actions">
          <button
            className="room-primary-button"
            disabled={!decideAvailable || actionPending}
            onClick={() => onRequestDecision(split, "approve")}
            type="button"
          >
            批准拆分
          </button>
          <button
            className="room-danger-button"
            disabled={!decideAvailable || actionPending}
            onClick={() => onRequestDecision(split, "reject")}
            type="button"
          >
            拒绝
          </button>
        </div>
      ) : null}
    </details>
  );
}

function boardActionErrorText(error: { code: string; message: string; status: number }): string {
  if (error.status === 409) return "看板状态已变化，已刷新";
  return `拆分决策未完成：${boardReasonLabel(error.code)}`;
}

function EventSummary({ event }: { event: BoardEvent }) {
  const data = event.data;
  if (event.typedKind === "progress") {
    const summary = isRecord(data.summary) ? (data.summary as AgentText) : null;
    const claims = Array.isArray(data.claims)
      ? data.claims.filter((item): item is AgentText => isRecord(item))
      : [];
    return (
      <span>
        <AgentTextView value={summary} />
        {claims.slice(0, 3).map((claim, index) => (
          <AgentTextView key={index} value={claim} />
        ))}
      </span>
    );
  }
  if (event.typedKind === "question") {
    const question = isRecord(data.question) ? (data.question as AgentText) : null;
    return <AgentTextView value={question} />;
  }
  if (event.typedKind === "contract_published" || event.typedKind === "contract_revised") {
    const contractId = typeof data.contract_id === "string" ? data.contract_id : "";
    const version = typeof data.version === "number" ? data.version : null;
    const rationale = isRecord(data.rationale) ? (data.rationale as AgentText) : null;
    return (
      <span>
        <span>
          {contractId}
          {version !== null ? ` v${version}` : ""}
        </span>
        <AgentTextView value={rationale} />
      </span>
    );
  }
  if (event.typedKind === "verification") {
    const status = typeof data.status === "string" ? data.status : "";
    const reasonCode = typeof data.reason_code === "string" ? data.reason_code : null;
    const gateIds = Array.isArray(data.gate_ids)
      ? data.gate_ids.filter((item): item is string => typeof item === "string")
      : [];
    return (
      <span>
        <span>{boardVerificationStatusLabel(status)}</span>
        {reasonCode ? <span>{boardReasonLabel(reasonCode)}</span> : null}
        {gateIds.length ? <span>{gateIds.join("、")}</span> : null}
      </span>
    );
  }
  if (event.typedKind === "split_proposed") {
    const splitId = typeof data.split_id === "string" ? data.split_id : "";
    const moduleIds = Array.isArray(data.module_ids)
      ? data.module_ids.filter((item): item is string => typeof item === "string")
      : [];
    return (
      <span>
        {splitId ? <code>{splitId}</code> : null}
        {moduleIds.length ? <span>{moduleIds.join("、")}</span> : null}
      </span>
    );
  }
  if (event.typedKind === "split_rejected" || event.typedKind === "charter_assigned") {
    const splitId = typeof data.split_id === "string" ? data.split_id : "";
    return splitId ? (
      <span>
        <code>{splitId}</code>
      </span>
    ) : null;
  }
  if (event.kind === "review_requested") {
    const reviewId = typeof data.review_id === "string" ? data.review_id : "";
    const reviewerKind = typeof data.reviewer_kind === "string" ? data.reviewer_kind : "";
    return (
      <span>
        {reviewId ? <code>{reviewId.slice(0, 12)}…</code> : null}
        {reviewerKind === "operator" ? <span>待你复核</span> : null}
      </span>
    );
  }
  if (event.kind === "review") {
    const verdict = typeof data.verdict === "string" ? data.verdict : "";
    const summary = isRecord(data.summary) ? (data.summary as AgentText) : null;
    return (
      <span>
        <span>{verdict === "endorse" ? "已背书" : verdict === "object" ? "已驳回" : verdict}</span>
        <AgentTextView value={summary} />
      </span>
    );
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function EventLine({
  event,
  projection: _projection
}: {
  event: BoardEvent;
  projection: RoomBoardProjection;
}) {
  void _projection;
  return (
    <div className="room-board-event">
      <span>{boardEventKindLabel(event.kind)}</span>
      {event.module_id ? <code>{event.module_id}</code> : null}
      <EventSummary event={event} />
    </div>
  );
}

export function RoomBoardDomain({
  cache,
  roomId,
  onLoadContract,
  actionPending = null,
  actionError = null,
  onDecide
}: {
  cache: RoomBoardCache | null;
  roomId?: string;
  onLoadContract: (contractId: string) => void;
  actionPending?: { kind: "approve" | "reject"; splitId: string } | null;
  actionError?: { code: string; message: string; status: number } | null;
  onDecide?: (split: BoardSplit, decision: BoardSplitDecision) => Promise<boolean>;
}) {
  const projection = cache?.projection ?? null;
  const summary = cache?.summary ?? null;
  const lastSynced = cache?.lastSyncedAt ? new Date(cache.lastSyncedAt).toLocaleString() : "未同步";
  const attention = projection?.attention ?? summary?.attention ?? [];
  const reviewsEnabled = projection?.capabilities.reviews === 1;
  const reviewPolicy = (projection as { review_policy?: string } | null)?.review_policy ?? null;
  const acceptedTotal =
    typeof summary?.accepted_total === "number"
      ? summary.accepted_total
      : (projection?.modules.filter((item) => item.accepted === true).length ?? 0);
  const conversationId = roomId ?? projection?.conversation_id ?? "";
  const isEmpty =
    projection !== null &&
    projection.modules.length === 0 &&
    projection.splits.length === 0 &&
    projection.events.length === 0;
  const eventsNewest = projection ? [...projection.events].sort((a, b) => b.seq - a.seq) : [];
  const [confirmation, setConfirmation] = useState<{
    split: BoardSplit;
    decision: BoardSplitDecision;
  } | null>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const splitRefs = useRef(new Map<string, HTMLDetailsElement>());

  function requestDecision(split: BoardSplit, decision: BoardSplitDecision) {
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    setConfirmation({ split, decision });
  }

  function closeConfirmation() {
    setConfirmation(null);
    requestAnimationFrame(() => returnFocusRef.current?.focus());
  }

  async function confirmDecision() {
    if (!confirmation || !onDecide) return;
    await onDecide(confirmation.split, confirmation.decision);
    closeConfirmation();
  }

  function viewSplit(splitId: string) {
    const card = splitRefs.current.get(splitId);
    if (!card) return;
    card.open = true;
    card.scrollIntoView?.({ block: "nearest" });
    card.querySelector("summary")?.focus({ preventScroll: true });
  }

  return (
    <section aria-label="协作看板" className="room-board">
      <div className="room-board-heading">
        <h3>协作看板</h3>
        <span className="room-board-heading-meta">
          {reviewPolicy ? <small>{boardReviewPolicyLabel(reviewPolicy)}</small> : null}
          {cache?.loading ? (
            <small>正在同步…</small>
          ) : (
            <small>上次同步 {lastSynced}</small>
          )}
        </span>
      </div>
      {projection && reviewsEnabled ? (
        <p className="room-board-accepted-total" role="status">
          已验收 {acceptedTotal}
        </p>
      ) : null}
      {cache?.error ? <p className="room-operations-warning" role="status">看板暂不可刷新</p> : null}
      {projection === null ? (
        <p className="room-operations-empty">尚未建立协作看板</p>
      ) : (
        <>
          <AttentionStrip items={attention} onViewSplit={viewSplit} />
          {projection ? <CountsRow projection={projection} /> : null}
          {isEmpty ? (
            <p className="room-operations-empty">尚未建立协作看板</p>
          ) : (
            <>
              <div aria-label="模块列表" className="room-board-modules">
                {projection.modules.map((boardModule) => (
                  <ModuleCard
                    boardModule={boardModule}
                    conversationId={conversationId}
                    key={boardModule.module_id}
                    projection={projection}
                    reviewsEnabled={reviewsEnabled}
                  />
                ))}
              </div>
              {projection.splits.length ? (
                <div aria-label="拆分提议" className="room-board-splits">
                  {projection.splits.map((split) => (
                    <SplitCard
                      actionPending={actionPending !== null}
                      cardRef={(element) => {
                        if (element) splitRefs.current.set(split.split_id, element);
                        else splitRefs.current.delete(split.split_id);
                      }}
                      key={split.split_id}
                      onRequestDecision={requestDecision}
                      projection={projection}
                      split={split}
                    />
                  ))}
                  {actionError ? (
                    <p className="room-operations-warning" role="alert">
                      {boardActionErrorText(actionError)}
                    </p>
                  ) : null}
                </div>
              ) : null}
              <RoomGrantsDomain
                conversationId={roomId ?? projection.conversation_id}
                key={roomId ?? projection.conversation_id}
              />
              {projection.contracts.length ? (
                <div aria-label="契约列表" className="room-board-contracts">
                  {projection.contracts.map((contract) => {
                    const detail = cache?.contractDetails[contract.contract_id] ?? null;
                    return (
                      <article className="room-board-contract" key={contract.contract_id}>
                        <button
                          aria-label={`查看契约 ${contract.contract_id}`}
                          onClick={() => onLoadContract(contract.contract_id)}
                          type="button"
                        >
                          <code>{contract.contract_id}</code>
                          <span>
                            v{contract.latest_version} · {boardContractKindLabel(contract.kind)}
                          </span>
                          <small>提供方 {contract.provider_module_id}</small>
                        </button>
                        {detail ? (
                          <div>
                            <ul>
                              {detail.versions.map((version) => (
                                <li key={version.version}>
                                  <span>v{version.version}</span>
                                  <AgentTextView value={version.rationale} />
                                </li>
                              ))}
                            </ul>
                            <AgentTextView monospace value={detail.content} />
                          </div>
                        ) : null}
                      </article>
                    );
                  })}
                </div>
              ) : null}
              {eventsNewest.length ? (
                <details className="room-board-events">
                  <summary>最近事件</summary>
                  <ul>
                    {eventsNewest.map((event) => (
                      <li key={event.seq}>
                        <EventLine event={event} projection={projection} />
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </>
          )}
        </>
      )}
      {confirmation && projection ? (
        <SplitDecisionDialog
          decision={confirmation.decision}
          onClose={closeConfirmation}
          onConfirm={confirmDecision}
          ownerNameOf={(participantId) => participantName(projection, participantId)}
          pending={actionPending !== null}
          split={confirmation.split}
        />
      ) : null}
    </section>
  );
}
