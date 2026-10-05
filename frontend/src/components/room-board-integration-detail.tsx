"use client";

import { useState, type SyntheticEvent } from "react";

import { describeError } from "@/lib/api";
import {
  escapeInvalidIntegrationPath,
  fetchBoardIntegrationDetail
} from "@/lib/board-integration-api";
import {
  boardIntegrationErrorShowsCode,
  boardIntegrationErrorText,
  boardIntegrationGateStatusLabel,
  boardIntegrationItemStatusLabel,
  boardIntegrationJobStatusLabel,
  boardIntegrationRoleLabel
} from "@/lib/board-integration-labels";
import type {
  BoardIntegrationDetail,
  BoardIntegrationGate,
  BoardIntegrationItem
} from "@/lib/board-integration-types";
import { boardReasonLabel } from "@/lib/board-labels";
import { isValidReviewPath } from "@/lib/board-review-api";
import { shortHeadCommit } from "@/lib/board-review-labels";
import { AgentTextView } from "./room-board-domain";

function shortCommit(commit: string | null | undefined): string | null {
  return shortHeadCommit(commit);
}

// Verification ids share a prefix (`boardverify_`), so the distinguishing part is the tail.
function shortVerificationId(id: string): string {
  return id.length > 8 ? `…${id.slice(-8)}` : id;
}

function ConflictPath({ path }: { path: string }) {
  if (isValidReviewPath(path)) {
    return <code>{path}</code>;
  }
  return (
    <span>
      <code>{escapeInvalidIntegrationPath(path)}</code>
      <span className="room-board-integration-flag">路径含不可见字符</span>
    </span>
  );
}

function IntegrationItemRow({
  item,
  highlighted
}: {
  item: BoardIntegrationItem;
  highlighted: boolean;
}) {
  const unlisted = Math.max(0, item.conflicts_total - item.conflicts.length);
  return (
    <li
      className={`room-board-integration-item${highlighted ? " is-self" : ""}`}
      data-module-id={item.module_id}
    >
      <p className="room-board-integration-item-head">
        <code>{item.module_id}</code>
        <span>
          {boardIntegrationRoleLabel(item.role, item.roleRaw)} ·{" "}
          {boardIntegrationItemStatusLabel(item.status, item.statusRaw)}
        </span>
        {highlighted ? <small className="room-board-integration-self">本模块</small> : null}
      </p>
      <p className="room-board-integration-applied">
        应用的版本{" "}
        {item.applied_verification_id ? (
          <code title={item.applied_verification_id}>{shortVerificationId(item.applied_verification_id)}</code>
        ) : (
          "无"
        )}
      </p>
      {item.conflicts.length ? (
        <ul className="room-board-integration-conflicts">
          {item.conflicts.map((conflict, index) => (
            <li key={`${conflict.path}:${index}`}>
              <ConflictPath path={conflict.path} />
              {conflict.attributed_module_ids.length ? (
                <span>涉及 {conflict.attributed_module_ids.join("、")}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {unlisted > 0 ? <p>另有 {unlisted} 个路径未列出</p> : null}
    </li>
  );
}

function IntegrationGateRow({ gate, showTail }: { gate: BoardIntegrationGate; showTail: boolean }) {
  return (
    <li className="room-board-integration-gate">
      <p className="room-board-integration-gate-line">
        <code>{gate.gate_id}</code>
        <span>{boardIntegrationGateStatusLabel(gate.status, gate.statusRaw)}</span>
        {gate.exit_code !== null ? <span>退出码 {gate.exit_code}</span> : null}
        {gate.reason_code ? <span>{boardReasonLabel(gate.reason_code)}</span> : null}
      </p>
      {showTail && gate.output_tail ? (
        <div className="room-board-integration-tail" tabIndex={0}>
          <AgentTextView monospace value={gate.output_tail} />
        </div>
      ) : null}
    </li>
  );
}

function tailIndexes(detail: BoardIntegrationDetail): Set<number> {
  const withTail = detail.gates
    .map((gate, index) => (gate.output_tail ? index : -1))
    .filter((index) => index >= 0)
    .slice(0, 3);
  return new Set(withTail);
}

function IntegrationDetailBody({
  detail,
  highlightModuleId
}: {
  detail: BoardIntegrationDetail;
  highlightModuleId?: string | null;
}) {
  const items = [...detail.items].sort((left, right) => left.order - right.order);
  const tails = tailIndexes(detail);
  return (
    <div>
      <p className="room-board-integration-job">
        <span>{boardIntegrationJobStatusLabel(detail.status, detail.statusRaw)}</span>
        {detail.reason_code ? <span>{boardReasonLabel(detail.reason_code)}</span> : null}
      </p>
      {detail.green_head_commit ? (
        <p>
          集成分支 <code title={detail.green_head_commit}>{shortCommit(detail.green_head_commit)}</code>
        </p>
      ) : null}
      {detail.result_commit ? (
        <p>
          构建结果 <code title={detail.result_commit}>{shortCommit(detail.result_commit)}</code>
        </p>
      ) : null}
      <p>尝试 {detail.attempt_count} 次</p>
      {items.length ? (
        <ul className="room-board-integration-items">
          {items.map((item) => (
            <IntegrationItemRow
              highlighted={highlightModuleId === item.module_id}
              item={item}
              key={`${item.order}:${item.module_id}`}
            />
          ))}
        </ul>
      ) : (
        <p>暂无集成模块。</p>
      )}
      {detail.gates.length ? (
        <ul className="room-board-integration-gates-list">
          {detail.gates.map((gate, index) => (
            <IntegrationGateRow gate={gate} key={`${gate.gate_id}:${index}`} showTail={tails.has(index)} />
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function IntegrationDetailDisclosure({
  conversationId,
  integrationId,
  highlightModuleId = null,
  summaryLabel = "集成详情"
}: {
  conversationId: string;
  integrationId: string;
  highlightModuleId?: string | null;
  summaryLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<BoardIntegrationDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  async function handleToggle(event: SyntheticEvent<HTMLDetailsElement>) {
    const nextOpen = event.currentTarget.open;
    setOpen(nextOpen);
    if (!nextOpen || detail || loading) return;
    setLoading(true);
    setErrorCode(null);
    try {
      const loaded = await fetchBoardIntegrationDetail(conversationId, integrationId);
      setDetail(loaded);
    } catch (error) {
      const failure = describeError(error);
      setErrorCode(failure.code);
    } finally {
      setLoading(false);
    }
  }

  return (
    <details className="room-board-integration-detail" onToggle={(event) => void handleToggle(event)}>
      <summary>{summaryLabel}</summary>
      {!open ? null : loading ? (
        <p>正在加载集成详情…</p>
      ) : errorCode ? (
        <p role="alert">
          {errorCode === "room_board_integration_unknown" ? (
            <span>{boardIntegrationErrorText(errorCode)}</span>
          ) : (
            <>
              <span>{boardIntegrationErrorText(errorCode)}</span>{" "}
              {boardIntegrationErrorShowsCode(errorCode) ? <code>{errorCode}</code> : null}
            </>
          )}
        </p>
      ) : detail ? (
        <IntegrationDetailBody detail={detail} highlightModuleId={highlightModuleId} />
      ) : null}
    </details>
  );
}
