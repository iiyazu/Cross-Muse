import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as reviewApi from "@/lib/board-review-api";
import { normalizeBoardReview } from "@/lib/board-review-api";
import { OperatorReviewPanel } from "./room-board-review-panel";

const DIGEST = `sha256:${"a".repeat(64)}`;

function pendingReview() {
  return normalizeBoardReview({
    status: "pending",
    review_id: "r1",
    verification_id: "v1",
    digest: DIGEST,
    rule_id: "cross_family/v1",
    author_family: "codex",
    reviewer_kind: "operator",
    reviewer_participant_id: null,
    reviewer_family: null,
    escalated_from: null,
    findings_count: { blocker: 0, major: 0, minor: 0 },
    decided_via: null,
    updated_at: "2026-10-04T12:00:00Z",
    actions: {
      decide: {
        available: true,
        method: "POST",
        href: "/api/chat/operator/board-reviews/r1/decision",
        expected_digest: DIGEST,
        allowed_verdicts: ["endorse", "object"]
      },
      material: { available: true }
    }
  });
}

function material(overrides: Record<string, unknown> = {}) {
  return reviewApi.normalizeBoardReviewMaterial({
    schema_version: "room_board_review_material/v1",
    review_id: "r1",
    verification_id: "v1",
    head_commit: "abc",
    digest: DIGEST,
    patch: {
      text: "--- a/x\n+++ b/x\n",
      bytes_total: 12,
      truncated: false,
      hidden_char_count: 0,
      ...overrides
    }
  });
}

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(reviewApi, "fetchBoardReviewMaterial").mockResolvedValue(material());
  vi.spyOn(reviewApi, "submitBoardReviewDecision").mockResolvedValue({ ok: true });
});

describe("OperatorReviewPanel", () => {
  it("shows hidden-char notices and renders the patch as plain text", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.fetchBoardReviewMaterial).mockResolvedValueOnce(
      material({ text: "a <U+202E> b", hidden_char_count: 3 })
    );
    render(<OperatorReviewPanel conversationId="conv-1" review={pendingReview()} reviewId="r1" />);
    await user.click(screen.getByRole("button", { name: "复核此模块" }));
    await screen.findByText(/含 3 个不可见字符/);
    const pre = screen.getByLabelText("复核补丁");
    expect(pre.tagName).toBe("PRE");
    expect(pre.textContent).toContain("<U+202E>");
    expect(pre.getAttribute("tabindex")).toBe("0");
  });

  it("disables endorse while truncated but keeps object available", async () => {
    const user = userEvent.setup();
    vi.mocked(reviewApi.fetchBoardReviewMaterial).mockResolvedValueOnce(
      material({ truncated: true })
    );
    render(<OperatorReviewPanel conversationId="conv-1" review={pendingReview()} reviewId="r1" />);
    await user.click(screen.getByRole("button", { name: "复核此模块" }));
    await screen.findByText("材料被截断，无法背书；可以提出异议");
    expect(screen.getByRole("radio", { name: "背书" })).toBeDisabled();
    expect(screen.getByRole("radio", { name: "异议" })).toBeEnabled();
  });

  it("blocks submit on digest mismatch", async () => {
    const user = userEvent.setup();
    const changed = reviewApi.normalizeBoardReviewMaterial({
      schema_version: "room_board_review_material/v1",
      review_id: "r1",
      verification_id: "v1",
      head_commit: "abc",
      digest: `sha256:${"b".repeat(64)}`,
      patch: { text: "x", bytes_total: 1, truncated: false, hidden_char_count: 0 }
    });
    vi.mocked(reviewApi.fetchBoardReviewMaterial).mockResolvedValueOnce(changed);
    render(<OperatorReviewPanel conversationId="conv-1" review={pendingReview()} reviewId="r1" />);
    await user.click(screen.getByRole("button", { name: "复核此模块" }));
    await screen.findByText("材料已变化，请重新加载");
    await user.type(screen.getByLabelText(/复核结论/), "good");
    expect(screen.getByRole("button", { name: "提交复核" })).toBeDisabled();
    expect(reviewApi.submitBoardReviewDecision).not.toHaveBeenCalled();
  });

  it("requires a blocker/major finding for object", async () => {
    const user = userEvent.setup();
    render(<OperatorReviewPanel conversationId="conv-1" review={pendingReview()} reviewId="r1" />);
    await user.click(screen.getByRole("button", { name: "复核此模块" }));
    await screen.findByLabelText("复核补丁");
    await user.click(screen.getByRole("radio", { name: "异议" }));
    await user.type(screen.getByLabelText(/复核结论/), "bad");
    await screen.findByText("异议至少需要一条阻断或严重问题");
    expect(screen.getByRole("button", { name: "提交复核" })).toBeDisabled();
  });

  it("discards the draft on close and never leaks digests in aria labels", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <OperatorReviewPanel conversationId="conv-1" review={pendingReview()} reviewId="r1" />
    );
    await user.click(screen.getByRole("button", { name: "复核此模块" }));
    await screen.findByLabelText("复核补丁");
    await user.type(screen.getByLabelText(/复核结论/), "draft text");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByLabelText("复核补丁")).toBeNull());
    await user.click(screen.getByRole("button", { name: "复核此模块" }));
    await screen.findByLabelText("复核补丁");
    expect(screen.getByLabelText(/复核结论/)).toHaveValue("");
    for (const element of [...container.querySelectorAll("[aria-label]")]) {
      const label = element.getAttribute("aria-label") ?? "";
      expect(label).not.toContain("sha256:");
      expect(label).not.toContain("server-secret");
    }
  });

  it("maps submit errors from code only", async () => {
    const user = userEvent.setup();
    const { XmuseApiError } = await import("@/lib/api");
    vi.mocked(reviewApi.submitBoardReviewDecision).mockRejectedValueOnce(
      new XmuseApiError({
        code: "room_board_review_digest_mismatch",
        message: "developer message must not show",
        retryable: false,
        status: 409
      })
    );
    render(<OperatorReviewPanel conversationId="conv-1" review={pendingReview()} reviewId="r1" />);
    await user.click(screen.getByRole("button", { name: "复核此模块" }));
    await screen.findByLabelText("复核补丁");
    await user.type(screen.getByLabelText(/复核结论/), "good");
    await user.click(screen.getByRole("button", { name: "提交复核" }));
    await screen.findByText("材料已变化，请重新加载");
    expect(screen.queryByText("developer message must not show")).toBeNull();
  });
});
