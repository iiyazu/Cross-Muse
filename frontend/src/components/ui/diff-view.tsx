"use client";

import { useMemo } from "react";

import { cx } from "./cx";

function lineTone(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) return "text-fg-2 font-medium";
  if (line.startsWith("@@")) return "text-live";
  if (line.startsWith("+")) return "bg-proof-soft text-fg";
  if (line.startsWith("-")) return "bg-fail-soft text-fg";
  if (line.startsWith("diff ") || line.startsWith("index ")) return "text-fg-3";
  return "text-fg-2";
}

/** A unified diff as plain text: one span per line, coloured only by its diff marker. */
export function DiffView({ text, label, className }: { text: string; label: string; className?: string }) {
  const lines = useMemo(() => text.split("\n"), [text]);
  return (
    <pre aria-label={label} className={cx("scrollbar-quiet m-0 overflow-auto bg-sunken py-2 font-mono text-[12px] leading-5", className)} tabIndex={0}>
      {lines.map((line, index) => (
        <span className={cx("block min-w-max px-3 whitespace-pre", lineTone(line))} key={index}>
          {line || " "}
        </span>
      ))}
    </pre>
  );
}
