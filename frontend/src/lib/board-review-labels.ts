import { boardReasonLabel } from "./board-labels";
import type {
  BoardReview,
  BoardReviewPolicy,
  BoardReviewSeverity,
  BoardReviewStatus
} from "./board-review-types";

export const BOARD_REVIEW_STATUS_LABELS: Record<string, string> = {
  none: "无复核",
  pending: "待复核",
  endorsed: "已背书",
  objected: "已驳回",
  superseded: "已取代"
};

export const BOARD_REVIEW_SEVERITY_LABELS: Record<string, string> = {
  blocker: "阻断",
  major: "严重",
  minor: "轻微"
};

const ESCALATION_REASON_LABELS: Record<string, string> = {
  board_review_reviewer_unavailable: "复核人不可用",
  board_review_reviewer_no_verdict: "复核人未给出结论",
  board_review_reviewer_unresponsive: "复核人无响应"
};

export function boardReviewStatusLabel(status: string, raw?: string | null): string {
  const known = BOARD_REVIEW_STATUS_LABELS[status];
  if (known) return known;
  const value = raw ?? (status && status !== "unknown" ? status : null);
  if (value && value !== "unknown") return `? ${value}`;
  if (status === "unknown") return "未知复核状态";
  return `? ${status}`;
}

export function boardReviewStatusText(status: BoardReviewStatus, statusRaw?: string | null): string {
  return boardReviewStatusLabel(status, statusRaw);
}

export function boardReviewSeverityLabel(severity: string): string {
  const known = BOARD_REVIEW_SEVERITY_LABELS[severity];
  if (known) return known;
  if (!severity || severity === "unknown") return "未知严重度";
  return `? ${severity}`;
}

export function boardReviewEscalationReasonLabel(reasonCode: string | null | undefined): string {
  if (!reasonCode) return "暂无原因";
  const known = ESCALATION_REASON_LABELS[reasonCode];
  if (known) return known;
  return boardReasonLabel(reasonCode);
}

export function boardReviewEscalationText(
  escalatedFrom: { reason_code: string } | null | undefined
): string | null {
  if (!escalatedFrom) return null;
  return boardReviewEscalationReasonLabel(escalatedFrom.reason_code);
}

export function boardReviewPolicyLabel(policy: string | null | undefined): string {
  if (policy === "cross_family") return "复核：跨模型族";
  if (policy === "off") return "复核：关";
  if (!policy || policy === "unknown") return "复核：未知";
  return `复核：? ${policy}`;
}

export function boardReviewPolicyValue(value: unknown): BoardReviewPolicy {
  if (value === "off" || value === "cross_family") return value;
  return "unknown";
}

/** Chip text for the module-card review axis. Glyph is rendered by the component. */
export function boardReviewChipText(review: Pick<BoardReview, "status">): string {
  switch (review.status) {
    case "pending":
      return "待复核";
    case "endorsed":
      return "已背书";
    case "objected":
      return "已驳回";
    case "none":
      return "无复核";
    default:
      return "未知复核";
  }
}

export function boardReviewChipGlyph(status: string): string {
  switch (status) {
    case "pending":
      return "◔";
    case "endorsed":
      return "✓";
    case "objected":
      return "✕";
    case "none":
      return "○";
    default:
      return "?";
  }
}

export function boardReviewFindingsText(counts: {
  blocker: number;
  major: number;
  minor: number;
}): string | null {
  const parts: string[] = [];
  if (counts.blocker > 0) parts.push(`阻断 ${counts.blocker}`);
  if (counts.major > 0) parts.push(`严重 ${counts.major}`);
  if (counts.minor > 0) parts.push(`轻微 ${counts.minor}`);
  if (!parts.length) return null;
  return parts.join(" · ");
}

export function boardReviewSeverityGlyph(severity: string): string {
  switch (severity) {
    case "blocker":
      return "■";
    case "major":
      return "▲";
    case "minor":
      return "●";
    default:
      return "?";
  }
}

const REVIEW_ERROR_LABELS: Record<string, string> = {
  room_board_review_digest_mismatch: "材料已变化，请重新加载",
  room_board_review_not_pending: "复核已不在待处理状态",
  room_board_review_material_incomplete: "材料被截断，无法背书",
  room_board_review_findings_invalid: "复核内容不合法",
  room_board_review_summary_invalid: "复核内容不合法",
  room_board_review_request_invalid: "复核内容不合法",
  room_board_review_request_too_large: "内容过大",
  room_board_review_unknown: "复核记录不存在",
  room_board_review_not_operator: "该复核不在待你处理状态",
  room_board_decided_via_invalid: "决策来源无效"
};

export function boardReviewErrorText(code: string | null | undefined): string {
  if (!code) return "操作失败，请重试";
  const known = REVIEW_ERROR_LABELS[code];
  if (known) return known;
  return "操作失败，请重试";
}

export function boardReviewErrorShowsCode(code: string | null | undefined): boolean {
  if (!code) return true;
  return !(code in REVIEW_ERROR_LABELS);
}

export function boardReviewVerdictLabel(verdict: string): string {
  if (verdict === "endorse") return "背书";
  if (verdict === "object") return "异议";
  return `? ${verdict}`;
}

export function shortHeadCommit(commit: string | null | undefined): string | null {
  if (!commit) return null;
  return commit.slice(0, 8);
}

export function isReviewSeverity(value: string): value is BoardReviewSeverity {
  return value === "blocker" || value === "major" || value === "minor";
}
