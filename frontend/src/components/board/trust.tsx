import { Fragment } from "react";

import { cx } from "@/components/ui/cx";

import { AXIS_LABELS, TRUST_LABELS, type StepTone, type TrustLevel, type TrustStep } from "./model";

/**
 * Shape is the primary channel: hollow = an agent's claim, solid = host proof, × = failed,
 * ! = needs a human, dashed = not started. Colour only repeats what the shape says.
 */
export function TrustGlyph({ tone, size = 14, className }: { tone: StepTone; size?: number; className?: string }) {
  const common = { width: size, height: size, viewBox: "0 0 14 14", "aria-hidden": true, className: cx("shrink-0", className) } as const;
  switch (tone) {
    case "pass":
      return (
        <svg {...common}>
          <circle cx="7" cy="7" fill="var(--proof-solid)" r="6.5" />
          <path d="M4.2 7.2l1.9 1.9 3.7-4" fill="none" stroke="var(--canvas)" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.6" />
        </svg>
      );
    case "fail":
      return (
        <svg {...common}>
          <circle cx="7" cy="7" fill="var(--fail-solid)" r="6.5" />
          <path d="M4.8 4.8l4.4 4.4M9.2 4.8l-4.4 4.4" stroke="var(--canvas)" strokeLinecap="round" strokeWidth="1.6" />
        </svg>
      );
    case "attn":
      return (
        <svg {...common}>
          <circle cx="7" cy="7" fill="var(--attn-solid)" r="6.5" />
          <path d="M7 3.8v4" stroke="oklch(0.25 0.05 70)" strokeLinecap="round" strokeWidth="1.7" />
          <circle cx="7" cy="10.1" fill="oklch(0.25 0.05 70)" r="0.95" />
        </svg>
      );
    case "claim":
      return (
        <svg {...common}>
          <circle cx="7" cy="7" fill="none" r="5.6" stroke="var(--fg-2)" strokeWidth="1.5" />
        </svg>
      );
    case "running":
      return (
        <svg {...common}>
          <circle cx="7" cy="7" fill="none" r="5.6" stroke="var(--live-line)" strokeWidth="1.5" />
          <path className="origin-center animate-spin [animation-duration:1.4s]" d="M7 1.4a5.6 5.6 0 0 1 5.6 5.6" fill="none" stroke="var(--live-solid)" strokeLinecap="round" strokeWidth="1.5" />
        </svg>
      );
    case "wait":
      return (
        <svg {...common}>
          <circle cx="7" cy="7" fill="none" r="5.6" stroke="var(--fg-3)" strokeDasharray="2.2 1.6" strokeWidth="1.3" />
          <path d="M7 4.3V7l1.8 1.2" fill="none" stroke="var(--fg-3)" strokeLinecap="round" strokeWidth="1.3" />
        </svg>
      );
    case "progress":
      return (
        <svg {...common}>
          <circle cx="7" cy="7" fill="none" r="5.6" stroke="var(--fg-3)" strokeWidth="1.3" />
          <circle cx="7" cy="7" fill="var(--fg-3)" r="2" />
        </svg>
      );
    default:
      return (
        <svg {...common}>
          <circle cx="7" cy="7" fill="none" r="5.6" stroke="var(--fg-4)" strokeDasharray="1.6 2" strokeWidth="1.3" />
        </svg>
      );
  }
}

/** Compact horizontal track for list rows. Labels are in the accessible tree and the tooltip. */
export function TrustTrack({ steps, className }: { steps: TrustStep[]; className?: string }) {
  return (
    <ol aria-label="信任链" className={cx("m-0 flex list-none items-center p-0", className)}>
      {steps.map((step, index) => {
        const linked = index > 0 && steps[index - 1].tone === "pass" && step.tone === "pass";
        return (
          <Fragment key={step.axis}>
            {index > 0 ? (
              <li aria-hidden="true" className={cx("h-px w-2.5", linked ? "bg-proof-line" : "bg-line-strong")} />
            ) : null}
            <li className="flex" title={`${AXIS_LABELS[step.axis]}：${step.label}${step.detail ? `（${step.detail}）` : ""}`}>
              <TrustGlyph tone={step.tone} />
              <span className="sr-only">{AXIS_LABELS[step.axis]}：{step.label}；</span>
            </li>
          </Fragment>
        );
      })}
    </ol>
  );
}

const TONE_TEXT: Record<StepTone, string> = {
  pass: "text-proof",
  fail: "text-fail",
  attn: "text-attn",
  running: "text-live",
  claim: "text-fg",
  progress: "text-fg-2",
  wait: "text-fg-2",
  empty: "text-fg-3"
};

/** Expanded vertical track for the module case file: each axis with its words. */
export function TrustLadder({ steps }: { steps: TrustStep[] }) {
  return (
    <ol aria-label="信任链" className="m-0 list-none p-0">
      {steps.map((step, index) => (
        <li className="relative flex gap-3 pb-3 last:pb-0" key={step.axis}>
          {index < steps.length - 1 ? (
            <span
              aria-hidden="true"
              className={cx(
                "absolute top-4 bottom-0 left-[6.5px] w-px",
                step.tone === "pass" && steps[index + 1].tone === "pass" ? "bg-proof-line" : "bg-line-strong"
              )}
            />
          ) : null}
          <TrustGlyph className="relative mt-0.5" tone={step.tone} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span className="w-16 shrink-0 text-xs text-fg-3">{AXIS_LABELS[step.axis]}</span>
              <span className={cx("text-ui font-medium", TONE_TEXT[step.tone])}>{step.label}</span>
            </div>
            {step.detail ? <p className="m-0 mt-0.5 pl-[4.5rem] text-xs text-fg-3">{step.detail}</p> : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

const SEGMENT: Record<TrustLevel, string> = {
  integrated: "bg-proof-solid",
  accepted: "bg-proof-soft ring-1 ring-inset ring-proof-line",
  verified: "bg-transparent ring-1 ring-inset ring-proof-line [background-image:repeating-linear-gradient(135deg,var(--proof-soft)_0_3px,transparent_3px_6px)]",
  claimed: "bg-transparent ring-1 ring-inset ring-line-strong",
  working: "bg-hover ring-1 ring-inset ring-line",
  failed: "bg-fail-solid",
  idle: "bg-transparent ring-1 ring-inset ring-line [background-image:repeating-linear-gradient(90deg,var(--line)_0_2px,transparent_2px_5px)]"
};

/** One segment per module, ordered from integrated to not started. */
export function SegmentBar({
  segments,
  className
}: {
  segments: Array<{ moduleId: string; level: TrustLevel }>;
  className?: string;
}) {
  if (!segments.length) return null;
  return (
    <div aria-hidden="true" className={cx("flex h-1.5 gap-0.5", className)}>
      {segments.map((segment) => (
        <span className={cx("min-w-1 flex-1 rounded-[2px]", SEGMENT[segment.level])} key={segment.moduleId} title={`${segment.moduleId}：${TRUST_LABELS[segment.level]}`} />
      ))}
    </div>
  );
}

export function LevelSwatch({ level }: { level: TrustLevel }) {
  return <span aria-hidden="true" className={cx("inline-block h-2 w-3 rounded-[2px]", SEGMENT[level])} />;
}
