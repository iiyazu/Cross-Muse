import { cx } from "@/components/ui/cx";
import { boardIntegrationGateText } from "@/lib/board-integration-labels";
import type { BoardIntegrationGate } from "@/lib/board-integration-types";

/**
 * Gate results with their scrubbed output tails, as plain text. Used by the integration
 * detail (§5.3) and the verification detail (§5.2); both are Web-only reads.
 */
export function GateList({ gates }: { gates: BoardIntegrationGate[] }) {
  return (
    <ul className="m-0 list-none p-0">
      {gates.map((gate) => (
        <li className="px-4 py-2" key={gate.gate_id}>
          <p className="m-0 flex flex-wrap items-baseline gap-x-2 text-ui">
            <code className="font-mono text-fg">{gate.gate_id}</code>
            <span className={cx("text-xs", gate.status === "passed" ? "text-proof" : gate.status === "failed" || gate.status === "error" ? "text-fail" : "text-fg-3")}>
              {boardIntegrationGateText(gate)}
            </span>
            {gate.exit_code !== null ? <span className="font-mono text-[11px] text-fg-3">exit {gate.exit_code}</span> : null}
          </p>
          {gate.output_tail ? (
            <figure className="m-0 mt-1.5">
              <figcaption className="mb-1 text-[11px] text-fg-3">门禁输出末尾（已清洗，按纯文本显示）</figcaption>
              <pre className="scrollbar-quiet m-0 max-h-56 overflow-auto rounded-md border border-line bg-sunken px-3 py-2 font-mono text-[11.5px] leading-[1.15rem] whitespace-pre-wrap text-fg-2">
                {gate.output_tail.text}
              </pre>
              {gate.output_tail.truncated ? <p className="m-0 mt-1 text-[11px] text-fg-3">输出过长，只保留了末尾。</p> : null}
            </figure>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
