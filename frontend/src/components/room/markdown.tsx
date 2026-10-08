"use client";

import { Children, isValidElement, memo, type ReactNode, useState } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { Check, Copy } from "lucide-react";

function textContent(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textContent).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return textContent(node.props.children);
  return "";
}

/** Only absolute http(s) URLs survive; everything else renders as plain text. */
export function safeUrl(value: string): string {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.toString() : "";
  } catch {
    return "";
  }
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const code = textContent(children).replace(/\n$/, "");

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setState("copied");
    } catch {
      setState("failed");
    }
    window.setTimeout(() => setState("idle"), 1600);
  }

  return (
    <div className="group/code relative my-2">
      <button
        aria-label={state === "copied" ? "代码已复制" : state === "failed" ? "复制代码失败" : "复制代码"}
        className="absolute top-1.5 right-1.5 inline-flex size-6 items-center justify-center rounded-sm text-fg-3 opacity-0 transition-opacity group-hover/code:opacity-100 hover:bg-hover hover:text-fg focus-visible:opacity-100"
        onClick={copy}
        type="button"
      >
        {state === "copied" ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
      <pre className="scrollbar-quiet m-0 overflow-x-auto rounded-md border border-line bg-sunken px-3 py-2.5 font-mono text-[12.5px] leading-5 text-fg-2 [&_code]:bg-transparent [&_code]:p-0 [&_code]:text-[length:inherit] [&_code]:text-fg-2">
        {children}
      </pre>
    </div>
  );
}

const components: Components = {
  h1: ({ children }) => <p className="mt-3 mb-1 font-semibold text-fg">{children}</p>,
  h2: ({ children }) => <p className="mt-3 mb-1 font-semibold text-fg">{children}</p>,
  h3: ({ children }) => <p className="mt-2 mb-1 font-semibold text-fg">{children}</p>,
  h4: ({ children }) => <p className="mt-2 mb-1 font-medium text-fg">{children}</p>,
  h5: ({ children }) => <p className="mt-2 mb-1 font-medium text-fg">{children}</p>,
  h6: ({ children }) => <p className="mt-2 mb-1 font-medium text-fg">{children}</p>,
  p: ({ children }) => <p className="my-1.5 first:mt-0 last:mb-0">{children}</p>,
  ul: ({ children }) => <ul className="my-1.5 list-disc pl-5 marker:text-fg-4">{children}</ul>,
  ol: ({ children }) => <ol className="my-1.5 list-decimal pl-5 marker:text-fg-3">{children}</ol>,
  li: ({ children }) => <li className="my-0.5">{children}</li>,
  blockquote: ({ children }) => <blockquote className="my-2 border-l-2 border-line-strong pl-3 text-fg-2">{children}</blockquote>,
  code: ({ children }) => (
    <code className="rounded-sm bg-raised px-1 py-px font-mono text-[0.86em] text-fg">{children}</code>
  ),
  table: ({ children }) => (
    <div className="scrollbar-quiet my-2 overflow-x-auto">
      <table className="w-full border-collapse text-ui">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border-b border-line-strong px-2 py-1 text-left font-medium text-fg-2">{children}</th>,
  td: ({ children }) => <td className="border-b border-line px-2 py-1 align-top">{children}</td>,
  hr: () => <hr className="my-3 border-line" />,
  a: ({ href, children }) => {
    const safeHref = href ? safeUrl(href) : "";
    return safeHref ? (
      <a className="text-live underline decoration-live-line underline-offset-2 hover:decoration-live" href={safeHref} rel="noopener noreferrer" target="_blank">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    );
  },
  pre: ({ children }) => <CodeBlock>{Children.toArray(children)}</CodeBlock>
};

const MARKDOWN_CODE_SEGMENT = /(```[\s\S]*?```|`[^`\n]*`)/g;
const ESCAPED_LINE_BREAK = /\\r\\n|\\n/g;

/** Agents sometimes send literal "\n" sequences; unescape them outside code when it is clearly that. */
export function normalizeRoomMarkdownContent(content: string): string {
  const segments = content.split(MARKDOWN_CODE_SEGMENT);
  const prose = segments.filter((_, index) => index % 2 === 0).join("");
  const escapedBreakCount = prose.match(ESCAPED_LINE_BREAK)?.length ?? 0;
  if (escapedBreakCount < 2) return content;
  return segments
    .map((segment, index) => (index % 2 === 0 ? segment.replace(ESCAPED_LINE_BREAK, "\n") : segment))
    .join("");
}

/** Room speech renderer: no raw HTML, no media, links limited to http(s). */
export const RoomMarkdown = memo(function RoomMarkdown({ content }: { content: string }) {
  return (
    <div className="min-w-0 break-words text-fg [overflow-wrap:anywhere]">
      <ReactMarkdown
        components={components}
        disallowedElements={["img", "iframe", "svg", "script", "style", "object", "embed", "video", "audio"]}
        remarkPlugins={[remarkGfm]}
        skipHtml
        unwrapDisallowed
        urlTransform={safeUrl}
      >
        {normalizeRoomMarkdownContent(content)}
      </ReactMarkdown>
    </div>
  );
});
