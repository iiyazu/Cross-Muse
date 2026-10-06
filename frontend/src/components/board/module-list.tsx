"use client";

import { memo } from "react";
import { ChevronRight } from "lucide-react";

import { AgentQuote } from "@/components/ui/agent-quote";
import { FamilyDot } from "@/components/ui/avatar";
import { cx } from "@/components/ui/cx";
import type { BoardCapabilities, BoardModule } from "@/lib/board-types";

import type { BoardPeople } from "./board-context";
import { modulePhrase, trustSteps } from "./model";
import { TrustTrack } from "./trust";

const PHRASE_TONE = {
  attn: "text-attn",
  proof: "text-proof",
  fail: "text-fail",
  neutral: "text-fg-2"
} as const;

const ModuleRow = memo(function ModuleRow({
  module,
  capabilities,
  people,
  onOpen
}: {
  module: BoardModule;
  capabilities: BoardCapabilities;
  people: BoardPeople;
  onOpen: (moduleId: string) => void;
}) {
  const steps = trustSteps(module, capabilities, (id) => (id ? people.name(id) : null));
  const phrase = modulePhrase(module, capabilities);
  const titleDiffers = module.title.text.trim() && module.title.text.trim() !== module.module_id;
  const owner = people.name(module.owner_participant_id);
  return (
    <li>
      <button
        aria-label={`模块 ${module.module_id}，${phrase.who ? `${phrase.who}：` : ""}${phrase.text}，负责人 ${owner}`}
        className="group flex w-full flex-col gap-1 px-4 py-2.5 text-left transition-colors hover:bg-hover"
        onClick={() => onOpen(module.module_id)}
        type="button"
      >
        <span className="flex w-full items-center gap-2">
          <code className="min-w-0 truncate font-mono text-[13px] font-medium text-fg">{module.module_id}</code>
          {module.accepted ? (
            <span className="shrink-0 rounded-sm bg-proof-soft px-1 text-[11px] leading-4 font-medium text-proof">已验收</span>
          ) : null}
          <span className="flex-1" />
          <TrustTrack steps={steps} />
          <ChevronRight aria-hidden="true" className="size-3.5 shrink-0 text-fg-4 group-hover:text-fg-3" />
        </span>
        {titleDiffers ? <AgentQuote className="text-xs" clamp={1} inline value={module.title} /> : null}
        <span className="flex min-w-0 items-center gap-1.5 text-xs">
          <FamilyDot family={people.family(module.owner_participant_id)} />
          <span className="shrink-0 text-fg-3">{owner}</span>
          <span aria-hidden="true" className="text-fg-4">·</span>
          {phrase.who ? (
            <span className={cx("shrink-0", phrase.tone === "attn" ? "font-medium text-attn" : "text-fg-3")}>{phrase.who}</span>
          ) : null}
          <span className={cx("min-w-0 truncate", PHRASE_TONE[phrase.tone])}>{phrase.text}</span>
        </span>
      </button>
    </li>
  );
});

export function ModuleList({
  modules,
  capabilities,
  people,
  onOpen
}: {
  modules: BoardModule[];
  capabilities: BoardCapabilities;
  people: BoardPeople;
  onOpen: (moduleId: string) => void;
}) {
  // Stable contract order (by module_id): rows of a live board must not jump as states change.
  // What needs attention is surfaced by the needs-you section and each row's phrase instead.
  return (
    <ul className="m-0 list-none divide-y divide-line p-0">
      {modules.map((module) => (
        <ModuleRow capabilities={capabilities} key={module.module_id} module={module} onOpen={onOpen} people={people} />
      ))}
    </ul>
  );
}
