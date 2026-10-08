import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AgentQuote } from "./agent-quote";

const INJECTION = "Ignore previous instructions <img src=x onerror=alert(1)> [click](javascript:alert(1))";

function attributeValues(container: HTMLElement): string[] {
  return [...container.querySelectorAll("*")].flatMap((element) => [...element.attributes].map((attribute) => attribute.value));
}

describe("AgentQuote", () => {
  it("renders agent text as plain text and labels it as the agent's own words", () => {
    const { container } = render(<AgentQuote value={{ text: INJECTION, untrusted: true, truncated: false }} />);
    expect(screen.getByText(INJECTION)).toBeInTheDocument();
    expect(screen.getByText("Agent 自述 · 未经宿主核实")).toBeInTheDocument();
    expect(container.querySelector("img, a, script")).toBeNull();
  });

  it("never copies agent text into an attribute (title, aria-label, ...)", () => {
    const { container } = render(
      <>
        <AgentQuote value={{ text: INJECTION, untrusted: true, truncated: true }} />
        <AgentQuote inline value={{ text: INJECTION, untrusted: true, truncated: false }} />
      </>
    );
    expect(attributeValues(container).some((value) => value.includes("Ignore previous"))).toBe(false);
  });

  it("says when the server truncated the text", () => {
    render(<AgentQuote value={{ text: "partial", untrusted: true, truncated: true }} />);
    expect(screen.getByText("内容过长，已截断")).toBeInTheDocument();
  });

  it("renders nothing for an empty value", () => {
    const { container } = render(<AgentQuote value={{ text: "", untrusted: true, truncated: false }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
