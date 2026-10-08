import type { CSSProperties } from "react";

import { providerBadge } from "@/lib/room-view";

import { cx } from "./cx";

export type Family = "claude" | "opencode" | "antigravity" | "codex" | "human" | "system" | "other";

/** Maps a server provider/family label onto a display family. Unknown labels stay neutral. */
export function familyOf(kind: string | null | undefined, actorKind?: string | null): Family {
  if (actorKind === "human") return "human";
  if (actorKind === "system") return "system";
  const badge = providerBadge(kind);
  if (badge) return badge.id;
  return "other";
}

const FAMILY_LABEL: Record<Family, string | null> = {
  claude: "Claude",
  opencode: "OpenCode",
  antigravity: "Antigravity",
  codex: "Codex",
  human: null,
  system: null,
  other: null
};

export function familyLabel(family: Family): string | null {
  return FAMILY_LABEL[family];
}

const FAMILY_VAR: Record<Family, string> = {
  claude: "var(--fam-claude)",
  opencode: "var(--fam-opencode)",
  antigravity: "var(--fam-antigravity)",
  codex: "var(--fam-codex)",
  human: "var(--fam-human)",
  system: "var(--fg-4)",
  other: "var(--fg-3)"
};

export function FamilyDot({ family, className }: { family: Family; className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cx("inline-block size-1.5 shrink-0 rounded-full", className)}
      style={{ background: FAMILY_VAR[family] }}
    />
  );
}

function monogram(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) return "?";
  const first = [...trimmed][0] ?? "?";
  // CJK names read best as one glyph; latin names take up to two initials.
  if (/[㐀-鿿]/.test(first)) return first;
  const words = trimmed.split(/[\s_-]+/).filter(Boolean);
  const initials = words.length > 1 ? `${words[0][0]}${words[1][0]}` : trimmed.slice(0, 2);
  return initials.toUpperCase();
}

export type PresenceTone = "live" | "attn" | "fail" | "idle" | null;

const PRESENCE: Record<Exclude<PresenceTone, null>, string> = {
  live: "bg-live-solid animate-pulse-soft",
  attn: "bg-attn-solid",
  fail: "bg-fail-solid",
  idle: "bg-fg-4"
};

/**
 * The vendor family tints the avatar itself, so identity needs no extra dot. Decorative:
 * always pair it with a visible or sr-only name.
 */
export function Avatar({
  name,
  family,
  size = "md",
  presence = null,
  className
}: {
  name: string;
  family: Family;
  size?: "sm" | "md" | "lg";
  presence?: PresenceTone;
  className?: string;
}) {
  const dimension = size === "sm" ? "size-5 text-[9.5px]" : size === "lg" ? "size-8 text-xs" : "size-6 text-[10.5px]";
  const human = family === "human";
  const tint: CSSProperties | undefined = human
    ? undefined
    : {
        background: `color-mix(in oklch, ${FAMILY_VAR[family]} 22%, var(--canvas))`,
        color: `color-mix(in oklch, ${FAMILY_VAR[family]} 62%, var(--fg))`
      };
  return (
    <span aria-hidden="true" className={cx("relative inline-flex shrink-0", className)}>
      <span
        className={cx(
          "inline-flex items-center justify-center rounded-full font-semibold leading-none tracking-tight",
          dimension,
          human && "bg-inverse text-on-inverse"
        )}
        style={tint}
      >
        {human ? "你" : monogram(name)}
      </span>
      {presence ? (
        <span className={cx("absolute -right-0.5 -bottom-0.5 size-2 rounded-full ring-2 ring-canvas", PRESENCE[presence])} />
      ) : null}
    </span>
  );
}
