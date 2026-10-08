import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { normalizeRoomMarkdownContent, RoomMarkdown, safeUrl } from "./markdown";

describe("RoomMarkdown", () => {
  it("keeps only http(s) links and drops raw HTML and media", () => {
    const { container } = render(
      <RoomMarkdown content={"[ok](https://example.com) [bad](javascript:alert(1)) <b>raw</b> ![x](https://example.com/x.png)"} />
    );
    const links = [...container.querySelectorAll("a")];
    expect(links.map((link) => link.getAttribute("href"))).toEqual(["https://example.com/"]);
    expect(links[0]).toHaveAttribute("rel", "noopener noreferrer");
    expect(container.querySelector("b, img, script")).toBeNull();
    expect(screen.getByText("bad")).toBeInTheDocument();
  });

  it("unescapes literal \\n sequences only when the text is clearly escaped", () => {
    expect(normalizeRoomMarkdownContent("a\\nb")).toBe("a\\nb");
    expect(normalizeRoomMarkdownContent("a\\nb\\nc")).toBe("a\nb\nc");
    expect(normalizeRoomMarkdownContent("x\\ny\\n`code\\n`")).toBe("x\ny\n`code\\n`");
  });

  it("rejects non-absolute and non-web URLs", () => {
    expect(safeUrl("/relative")).toBe("");
    expect(safeUrl("data:text/html,hi")).toBe("");
    expect(safeUrl("http://127.0.0.1:3000/x")).toBe("http://127.0.0.1:3000/x");
  });
});
