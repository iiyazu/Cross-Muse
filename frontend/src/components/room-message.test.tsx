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

  it("renders the addressing chip and handoff note card on a Human message", () => {
    const human: RoomTimelineItem = {
      id: "message-9",
      room_seq: 9,
      kind: "message",
      actor: { kind: "human", role: "human", display_name: "你" },
      content: "请先评估发布风险",
      mentions: ["架构师", "@研究员"],
      addressing: "mentions",
      handoff_note: {
        what: "评估发布风险",
        why: "存在未验证路径",
        tradeoffs: "延迟一天",
        open_questions: ["是否回滚？"],
        next_action: "给出结论"
      }
    };
    render(<RoomMessage item={human} onJumpToReference={vi.fn()} leadName="架构师" />);
    expect(screen.getByText("→ @架构师 @研究员")).toHaveAttribute("title", "@ 提及的 Agent 成为本次观察对象");
    expect(screen.getByText("交办说明")).toBeInTheDocument();
    expect(screen.getByText("What")).toBeInTheDocument();
    expect(screen.getByText("评估发布风险")).toBeInTheDocument();
    expect(screen.getByText("Open questions")).toBeInTheDocument();
    expect(screen.getByText("是否回滚？")).toBeInTheDocument();
    expect(screen.getByText("Next action")).toBeInTheDocument();
  });

  it("labels lead and fallback addressing when no lead name is known", () => {
    const base: RoomTimelineItem = {
      id: "message-10",
      room_seq: 10,
      kind: "message",
      actor: { kind: "human", role: "human", display_name: "你" },
      content: "继续"
    };
    render(
      <>
        <RoomMessage item={{ ...base, id: "message-10", addressing: "lead" }} onJumpToReference={vi.fn()} leadName="架构师" />
        <RoomMessage item={{ ...base, id: "message-11", room_seq: 11, addressing: "fallback_broadcast" }} onJumpToReference={vi.fn()} />
      </>
    );
    expect(screen.getByText("→ 架构师（lead）")).toBeInTheDocument();
    expect(screen.getByText("fallback: everyone")).toBeInTheDocument();
  });
});
