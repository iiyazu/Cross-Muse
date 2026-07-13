"use client";

import { Children, isValidElement, type ReactNode, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

function textContent(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textContent).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textContent(node.props.children);
  return "";
}

function safeUrl(value: string): string {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : "";
  } catch {
    return "";
  }
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const [copyState, setCopyState] = useState<"idle" | "copied" | "failed">("idle");
  const code = textContent(children).replace(/\n$/, "");

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 1600);
    } catch {
      setCopyState("failed");
      window.setTimeout(() => setCopyState("idle"), 2400);
    }
  }

  const feedback = copyState === "copied" ? "代码已复制" : copyState === "failed" ? "复制代码失败" : "";

  return (
    <div className="room-code-block">
      <button aria-label={feedback || "复制代码"} className="room-code-copy" onClick={copy} type="button">
        {copyState === "copied" ? "已复制" : copyState === "failed" ? "复制失败" : "复制"}
      </button>
      <pre>{children}</pre>
      <span aria-live="polite" className="sr-only">{feedback}</span>
    </div>
  );
}

const components: Components = {
  h1: ({ children }) => <h3>{children}</h3>,
  h2: ({ children }) => <h3>{children}</h3>,
  h3: ({ children }) => <h4>{children}</h4>,
  h4: ({ children }) => <h5>{children}</h5>,
  h5: ({ children }) => <h6>{children}</h6>,
  h6: ({ children }) => <h6>{children}</h6>,
  a: ({ href, children }) => {
    const safeHref = href ? safeUrl(href) : "";
    return safeHref ? (
      <a href={safeHref} rel="noopener noreferrer" target="_blank">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    );
  },
  pre: ({ children }) => <CodeBlock>{Children.toArray(children)}</CodeBlock>
};

export function RoomMarkdown({ content }: { content: string }) {
  return (
    <div className="room-markdown">
      <ReactMarkdown
        components={components}
        disallowedElements={["img", "iframe", "svg", "script", "style", "object", "embed", "video", "audio"]}
        remarkPlugins={[remarkGfm]}
        skipHtml
        unwrapDisallowed
        urlTransform={safeUrl}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
