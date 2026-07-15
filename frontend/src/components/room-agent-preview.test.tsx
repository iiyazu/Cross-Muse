import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RoomAgentPreview, splitIncrementalMarkdown } from "./room-agent-preview";

describe("RoomAgentPreview", () => {
  it("renders stable Markdown while keeping the incomplete tail as plain text", () => {
    const { container, rerender } = render(
      <RoomAgentPreview
        displayName="Reviewer"
        stream={{
          stream_id: "stream-1",
          participant_id: "participant-1",
          observation_id: "observation-1",
          state: "streaming",
          content: "# 已完成标题\n\n**尚未闭合",
          truncated: false,
          started_at: "2026-07-14T10:00:00Z",
          updated_at: "2026-07-14T10:00:01Z"
        }}
      />
    );

    expect(screen.getByText("生成中 · 非耐久预览")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "已完成标题", level: 3 })).toBeInTheDocument();
    expect(screen.getByText("**尚未闭合")).toBeInTheDocument();
    expect(container.querySelector(".room-stream-tail strong")).toBeNull();

    rerender(
      <RoomAgentPreview
        displayName="Reviewer"
        stream={{
          stream_id: "stream-1",
          participant_id: "participant-1",
          observation_id: "observation-1",
          state: "committing",
          content: "# 已完成标题\n\n**已经闭合**",
          truncated: false,
          started_at: "2026-07-14T10:00:00Z",
          updated_at: "2026-07-14T10:00:02Z"
        }}
      />
    );
    expect(container.querySelector(".room-stream-body strong")).toHaveTextContent("已经闭合");
  });

  it("does not parse an open fenced block until the fence closes", () => {
    expect(splitIncrementalMarkdown("正文\n\n```ts\nconst value = 1\n")).toEqual({
      stable: "正文\n\n",
      tail: "```ts\nconst value = 1\n"
    });
    expect(splitIncrementalMarkdown("正文\n\n```ts\nconst value = 1\n```\n尾部")).toEqual({
      stable: "正文\n\n```ts\nconst value = 1\n```\n",
      tail: "尾部"
    });
  });

  it("freezes the caret while committing", () => {
    const { container } = render(
      <RoomAgentPreview
        displayName="Architect"
        stream={{
          stream_id: "stream-2",
          participant_id: "participant-2",
          observation_id: "observation-2",
          state: "committing",
          content: "Ready",
          truncated: true,
          started_at: "2026-07-14T10:00:00Z",
          updated_at: "2026-07-14T10:00:01Z"
        }}
      />
    );

    expect(screen.getByText("正在提交")).toBeInTheDocument();
    expect(screen.getByText("预览已截断，正式回复不受影响。")).toBeInTheDocument();
    expect(container.querySelector(".room-stream-caret")).toBeNull();
  });
});
