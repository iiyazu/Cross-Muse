import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { RoomTimelineItem } from "@/lib/types";
import { RoomMessage, RoomPendingBubble } from "./room-message";

const item: RoomTimelineItem = {
  id: "message-2",
  room_seq: 2,
  kind: "handoff",
  activity_id: "activity-2",
  message_id: "message-2",
  reply_to_message_id: "message-1",
  reply_to_activity_id: "activity-1",
  reply_target_display_name: "Architect",
  correlation_id: "correlation-1",
  causation_id: "activity-1",
  causal_depth: 1,
  actor: { kind: "agent", role: "builder", participant_id: "participant-1", display_name: "Builder" },
  content: "**handoff**",
  handoff_targets: ["Reviewer"]
};

describe("RoomMessage", () => {
  it("preserves identity, causal proof, handoff, Markdown, and reply navigation", async () => {
    const user = userEvent.setup();
    const onJump = vi.fn();
    const { container } = render(<RoomMessage item={item} onJumpToReference={onJump} />);
    const article = container.querySelector("article");
    expect(article).toHaveClass("from-agent", "kind-handoff");
    expect(article).toHaveAttribute("data-message-id", "message-2");
    expect(screen.getByText("建议转交")).toBeInTheDocument();
    expect(screen.getByText("转交给 Reviewer")).toBeInTheDocument();
    expect(screen.getByText("handoff").tagName).toBe("STRONG");
    await user.click(screen.getByRole("button", { name: "回复 Architect" }));
    expect(onJump).toHaveBeenCalledWith("message-1", "activity-1");
    await user.click(screen.getByText("核验因果"));
    expect(screen.getByText("correlation-1")).toBeInTheDocument();
  });

  it("keeps a failed optimistic message and exposes same-request retry", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    const { container } = render(<RoomPendingBubble pending={{ clientRequestId: "request-1", content: "body", createdAt: "now", status: "failed", error: { code: "timeout", message: "timed out", retryable: true, status: 504 } }} onRetry={onRetry} />);
    expect(container.querySelector("article")).toHaveAttribute("data-message-id", "pending:request-1");
    expect(screen.getByRole("alert")).toHaveTextContent("timed out");
    await user.click(screen.getByRole("button", { name: "使用同一请求重试" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
