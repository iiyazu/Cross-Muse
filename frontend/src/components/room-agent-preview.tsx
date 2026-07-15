import { memo, useMemo } from "react";

import type { RoomAgentStream } from "@/lib/types";
import { identityStyle, initials } from "./room-header";
import { RoomMarkdown } from "./room-markdown";

export type IncrementalMarkdownParts = {
  stable: string;
  tail: string;
};

export function splitIncrementalMarkdown(
  content: string,
  complete = false
): IncrementalMarkdownParts {
  if (!content || complete) return { stable: content, tail: "" };
  let offset = 0;
  let stableEnd = 0;
  let fence: "`" | "~" | null = null;
  for (const match of content.matchAll(/.*(?:\n|$)/g)) {
    const line = match[0];
    if (!line) continue;
    offset += line.length;
    const trimmed = line.trimStart();
    const marker = trimmed.match(/^(`{3,}|~{3,})/)?.[1] ?? null;
    if (marker) {
      const kind = marker[0] as "`" | "~";
      if (fence === null) fence = kind;
      else if (fence === kind) {
        fence = null;
        stableEnd = offset;
      }
    } else if (fence === null && line.trim() === "") {
      stableEnd = offset;
    }
  }
  return {
    stable: content.slice(0, stableEnd),
    tail: content.slice(stableEnd)
  };
}

export const RoomAgentPreview = memo(function RoomAgentPreview({
  stream,
  displayName
}: {
  stream: RoomAgentStream;
  displayName: string;
}) {
  const committing = stream.state === "committing" || stream.state === "resolved";
  const markdown = useMemo(
    () => splitIncrementalMarkdown(stream.content, committing),
    [committing, stream.content]
  );
  return (
    <article
      aria-live="off"
      className={`room-message from-agent room-agent-preview ${committing ? "is-committing" : "is-streaming"}`}
      data-stream-id={stream.stream_id}
      style={identityStyle(stream.participant_id)}
    >
      <span className="room-avatar room-message__avatar">{initials(displayName)}</span>
      <div className="room-message__content">
        <header>
          <strong>{displayName}</strong>
          <span className="room-stream-label">
            {committing ? "正在提交" : "生成中 · 非耐久预览"}
          </span>
        </header>
        {stream.content ? (
          <div className="room-stream-body">
            {markdown.stable ? <RoomMarkdown content={markdown.stable} /> : null}
            {markdown.tail || !committing ? (
              <div className="room-stream-tail">
                {markdown.tail}
                {!committing ? <span aria-hidden="true" className="room-stream-caret" /> : null}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="room-stream-placeholder" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
        )}
        {stream.truncated ? <small>预览已截断，正式回复不受影响。</small> : null}
      </div>
    </article>
  );
});
