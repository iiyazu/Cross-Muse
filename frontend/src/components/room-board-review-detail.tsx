"use client";

import { useState, type SyntheticEvent } from "react";

import { fetchBoardReviewDetail } from "@/lib/board-review-api";
import { boardReviewSeverityLabel, shortHeadCommit } from "@/lib/board-review-labels";
import type { BoardReviewDetail } from "@/lib/board-review-types";
import { describeError } from "@/lib/api";
import { AgentTextView } from "./room-board-domain";

function WhyReviewer({ detail }: { detail: BoardReviewDetail }) {
  const inputs = detail.rule_inputs;
  const picked = inputs.picked_participant_id;
  return (
    <div className="room-board-review-why">
      <p>作者模型族 {inputs.author_family}</p>
      {inputs.eligible.length ? (
        <ul>
          {inputs.eligible.map((item) => (
            <li key={item.participant_id}>
              <code>{item.participant_id.slice(0, 8)}…</code>
              <span>
                {item.family} · 待复核 {item.pending}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p>暂无其他模型族候选</p>
      )}
      <p>
        {inputs.last_reviewer_participant_id
          ? `上次复核人 ${inputs.last_reviewer_participant_id.slice(0, 8)}…`
          : "无上次复核人"}
      </p>
      <p>{picked ? `已选 ${picked.slice(0, 8)}…` : "无其他模型族，由你复核"}</p>
    </div>
  );
}

export function ReviewDetailDisclosure({
  conversationId,
  reviewId
}: {
  conversationId: string;
  reviewId: string;
}) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<BoardReviewDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  async function handleToggle(event: SyntheticEvent<HTMLDetailsElement>) {
    const nextOpen = event.currentTarget.open;
    setOpen(nextOpen);
    if (!nextOpen || detail || loading) return;
    setLoading(true);
    setErrorCode(null);
    try {
      const loaded = await fetchBoardReviewDetail(conversationId, reviewId);
      setDetail(loaded);
    } catch (error) {
      const failure = describeError(error);
      setErrorCode(failure.code);
    } finally {
      setLoading(false);
    }
  }

  return (
    <details className="room-board-review-detail" onToggle={(event) => void handleToggle(event)}>
      <summary>复核详情</summary>
      {!open ? null : loading ? (
        <p>正在加载复核详情…</p>
      ) : errorCode ? (
        <p role="alert">
          {errorCode === "room_board_review_unknown" ? (
            <span>复核记录不存在</span>
          ) : (
            <>
              <span>操作失败，请重试</span> <code>{errorCode}</code>
            </>
          )}
        </p>
      ) : detail ? (
        <div>
          <p>
            复核人 {detail.review.reviewer_kind === "operator" ? "你" : (detail.review.reviewer_family ?? "未知")}
            {detail.review.reviewer_kind === "participant" ? `（${detail.review.reviewer_family ?? "未知模型族"}）` : null}
          </p>
          <WhyReviewer detail={detail} />
          {detail.summary ? <AgentTextView value={detail.summary} /> : <p>暂无复核结论。</p>}
          {detail.findings.length ? (
            <ul className="room-board-review-findings-list">
              {detail.findings.map((finding, index) => (
                <li key={index}>
                  <span>
                    {boardReviewSeverityLabel(finding.severity)} ·{" "}
                    {finding.path ? <code>{finding.path}</code> : <span>通用</span>}
                  </span>
                  <AgentTextView value={finding.text} />
                </li>
              ))}
            </ul>
          ) : null}
          {detail.head_commit ? (
            <p>
              提交 <code title={detail.head_commit}>{shortHeadCommit(detail.head_commit)}</code>
            </p>
          ) : null}
        </div>
      ) : null}
    </details>
  );
}
