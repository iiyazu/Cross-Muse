import type { AgentText } from "@/lib/board-types";

import { cx } from "./cx";

/**
 * Renders agent-authored text (`AgentText`, always untrusted) as plain text, visibly marked
 * as the agent's own words. Never pass its text to a title, aria-label, toast, status line or
 * document.title: callers label the surrounding element with trusted values instead.
 */
export function AgentQuote({
  value,
  inline = false,
  className,
  clamp
}: {
  value: AgentText | null | undefined;
  inline?: boolean;
  className?: string;
  /** Visual line clamp for list rows; the full text stays in the DOM. */
  clamp?: 1 | 2 | 3;
}) {
  if (!value || !value.text) return null;
  const clampClass = clamp === 1 ? "line-clamp-1" : clamp === 2 ? "line-clamp-2" : clamp === 3 ? "line-clamp-3" : null;
  if (inline) {
    return (
      <span className={cx("text-fg-2", className)} data-agent-text="">
        <span className="sr-only">Agent 自述：</span>
        <span className={cx("break-words whitespace-pre-wrap", clampClass)}>{value.text}</span>
        {value.truncated ? <span className="text-fg-3">…（已截断）</span> : null}
      </span>
    );
  }
  return (
    <figure className={cx("m-0 border-l-2 border-line-strong pl-3", className)} data-agent-text="">
      <figcaption className="mb-0.5 text-xs text-fg-3">Agent 自述 · 未经宿主核实</figcaption>
      <blockquote className={cx("m-0 text-fg-2 break-words whitespace-pre-wrap", clampClass)}>
        {value.text}
      </blockquote>
      {value.truncated ? <p className="m-0 text-xs text-fg-3">内容过长，已截断</p> : null}
    </figure>
  );
}
