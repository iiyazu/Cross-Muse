import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { normalizeRoomMarkdownContent, RoomMarkdown } from "./room-markdown";

describe("RoomMarkdown", () => {
  it("repairs repeated escaped line breaks in prose without rewriting code", () => {
    const content = [
      "结论如下：\\n\\n1. 第一项\\n2. 第二项 `\\n\\n`",
      "```text",
      "literal \\n and \\r\\n",
      "```"
    ].join("\n\n");
    expect(normalizeRoomMarkdownContent(content)).toBe(
      [
        "结论如下：\n\n1. 第一项\n2. 第二项 `\\n\\n`",
        "```text",
        "literal \\n and \\r\\n",
        "```"
      ].join("\n\n")
    );
    const { container } = render(<RoomMarkdown content={content} />);
    expect(container.querySelectorAll("p, ol, pre")).toHaveLength(3);
    expect(screen.getByText("\\n\\n")).toBeInTheDocument();
    expect(screen.getByText("literal \\n and \\r\\n")).toBeInTheDocument();
  });

  it("preserves a single escaped newline because it may be intentional text", () => {
    expect(normalizeRoomMarkdownContent("使用 \\n 表示换行")).toBe("使用 \\n 表示换行");
  });

  it("renders GFM while removing executable and media content", () => {
    const { container } = render(
      <RoomMarkdown
        content={'# 标题\n\n[安全链接](https://example.com/path) [危险链接](javascript:alert(1))\n\n<img src="https://example.com/a.png" onerror="alert(1)">\n\n<script>alert(1)</script>\n\n| A | B |\n| - | - |\n| 1 | 2 |'}
      />
    );
    expect(screen.getByRole("heading", { name: "标题", level: 3 })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "安全链接" })).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByRole("link", { name: "危险链接" })).not.toBeInTheDocument();
    expect(container.querySelector("img, script, iframe, svg")).toBeNull();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("announces clipboard failure instead of silently ignoring it", async () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) }
    });
    render(<RoomMarkdown content={'```text\ncopy me\n```'} />);

    await user.click(screen.getByRole("button", { name: "复制代码" }));

    expect(screen.getByRole("button", { name: "复制代码失败" })).toHaveTextContent("复制失败");
    expect(screen.getByText("复制代码失败")).toHaveAttribute("aria-live", "polite");
  });
});
