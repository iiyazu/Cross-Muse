import { describe, expect, it } from "vitest";

import {
  boardReviewChipGlyph,
  boardReviewChipText,
  boardReviewErrorShowsCode,
  boardReviewErrorText,
  boardReviewEscalationReasonLabel,
  boardReviewFindingsText,
  boardReviewPolicyLabel,
  boardReviewSeverityLabel,
  boardReviewStatusLabel
} from "./board-review-labels";

describe("review labels", () => {
  it("labels known statuses with glyph+text", () => {
    expect(boardReviewChipText({ status: "pending" })).toBe("待复核");
    expect(boardReviewChipText({ status: "endorsed" })).toBe("已背书");
    expect(boardReviewChipText({ status: "objected" })).toBe("已驳回");
    expect(boardReviewChipGlyph("pending")).toBeTruthy();
    expect(boardReviewChipGlyph("endorsed")).toBe("✓");
    expect(boardReviewChipGlyph("objected")).toBe("✕");
    expect(boardReviewStatusLabel("pending")).toBe("待复核");
  });

  it("shows unknown statuses as ? + value, never hidden", () => {
    expect(boardReviewStatusLabel("unknown", "future_status")).toBe("? future_status");
    expect(boardReviewStatusLabel("future_status")).toBe("? future_status");
    expect(boardReviewSeverityLabel("future")).toBe("? future");
  });

  it("labels escalation reasons and falls back with the code", () => {
    expect(boardReviewEscalationReasonLabel("board_review_reviewer_unavailable")).toBe(
      "复核人不可用"
    );
    expect(boardReviewEscalationReasonLabel("board_review_reviewer_no_verdict")).toBe(
      "复核人未给出结论"
    );
    expect(boardReviewEscalationReasonLabel("board_review_reviewer_unresponsive")).toBe(
      "复核人无响应"
    );
    const unknown = boardReviewEscalationReasonLabel("board_review_future_code");
    expect(unknown).toContain("board_review_future_code");
  });

  it("formats findings counts as small numbers", () => {
    expect(boardReviewFindingsText({ blocker: 1, major: 1, minor: 1 })).toContain("阻断 1");
    expect(boardReviewFindingsText({ blocker: 0, major: 0, minor: 0 })).toBeNull();
  });

  it("labels the review policy display-only", () => {
    expect(boardReviewPolicyLabel("cross_family")).toBe("复核：跨模型族");
    expect(boardReviewPolicyLabel("off")).toBe("复核：关");
    expect(boardReviewPolicyLabel("future")).toContain("?");
  });

  it("maps operator error codes from code only", () => {
    expect(boardReviewErrorText("room_board_review_digest_mismatch")).toBe("材料已变化，请重新加载");
    expect(boardReviewErrorText("room_board_review_not_pending")).toBe("复核已不在待处理状态");
    expect(boardReviewErrorText("room_board_review_material_incomplete")).toBe("材料被截断，无法背书");
    expect(boardReviewErrorText("room_board_review_unknown")).toBe("复核记录不存在");
    expect(boardReviewErrorText("room_board_decided_via_invalid")).toBe("决策来源无效");
    expect(boardReviewErrorText("some_future_code")).toBe("操作失败，请重试");
    expect(boardReviewErrorShowsCode("room_board_review_unknown")).toBe(false);
    expect(boardReviewErrorShowsCode("some_future_code")).toBe(true);
  });
});
