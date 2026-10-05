"use client";

import {
  boardReviewChipGlyph,
  boardReviewChipText,
  boardReviewEscalationReasonLabel,
  boardReviewFindingsText,
  boardReviewStatusLabel
} from "@/lib/board-review-labels";
import type { BoardReview } from "@/lib/board-review-types";

export function ReviewChip({
  review,
  reviewsEnabled
}: {
  review: BoardReview;
  reviewsEnabled: boolean;
}) {
  if (!reviewsEnabled) return null;
  if (review.status === "none") return null;
  const isPending = review.status === "pending";
  const isOperator = review.reviewer_kind === "operator";
  const escalated = review.escalated_from;
  const text =
    isPending && isOperator && !escalated ? "待你复核" : boardReviewChipText(review);
  const glyph = boardReviewChipGlyph(review.status);
  let detail: string | null = null;
  if (review.status === "unknown") {
    detail = boardReviewStatusLabel(review.status, review.statusRaw);
  } else if (escalated) {
    detail = `已从 ${escalated.family} 升级给你`;
  } else if (isPending && isOperator) {
    detail = null;
  } else if (isPending && review.reviewer_kind === "participant") {
    detail = review.reviewer_family ? `由 ${review.reviewer_family} 复核` : "由其他模型族复核";
  }
  const findings = boardReviewFindingsText(review.findings_count);
  const tone =
    review.status === "endorsed"
      ? "is-endorsed"
      : review.status === "objected"
        ? "is-objected"
        : review.status === "pending" && isOperator
          ? "is-operator-pending"
          : review.status === "pending"
            ? "is-pending"
            : "is-muted";
  const ariaLabel =
    escalated
      ? `复核状态：已升级，${detail ?? ""}，原因${boardReviewEscalationReasonLabel(escalated.reason_code)}`
      : isPending && isOperator
        ? "复核状态：待你复核"
        : `复核状态：${text}${detail ? `，${detail}` : ""}`;
  return (
    <span className="room-board-review-wrap">
      <span aria-label={ariaLabel} className={`room-board-review-chip ${tone}`} role="status">
        <span aria-hidden="true" className="room-board-review-glyph">
          {escalated ? "⇪" : glyph}
        </span>
        <span>{escalated ? "已升级" : text}</span>
      </span>
      {detail && !escalated ? <small className="room-board-review-by">{detail}</small> : null}
      {escalated ? (
        <small className="room-board-review-by">
          {detail} · {boardReviewEscalationReasonLabel(escalated.reason_code)}
          {boardReviewEscalationReasonLabel(escalated.reason_code).startsWith("未知原因") ? (
            <code>{escalated.reason_code}</code>
          ) : null}
        </small>
      ) : null}
      {escalated && review.reviewer_kind === "operator" && review.status === "pending" ? (
        <small className="room-board-review-by">待你复核</small>
      ) : null}
      {findings ? <small className="room-board-review-findings">{findings}</small> : null}
    </span>
  );
}

export function AcceptedMark({ accepted }: { accepted: boolean }) {
  if (!accepted) return null;
  return (
    <span aria-label="已验收：验证通过且复核已背书" className="room-board-accepted" role="status">
      <span aria-hidden="true">✔</span>
      <span>已验收</span>
    </span>
  );
}
