"use client";

import {
  boardIntegrationChipGlyph,
  boardIntegrationChipText,
  boardIntegrationChipTone,
  boardIntegrationSecondaryText
} from "@/lib/board-integration-labels";
import type { BoardModuleIntegration } from "@/lib/board-integration-types";

export function IntegrationChip({
  integration,
  integrationsEnabled
}: {
  integration: BoardModuleIntegration;
  integrationsEnabled: boolean;
}) {
  if (!integrationsEnabled) return null;
  if (integration.status === "none") return null;
  const text = boardIntegrationChipText(integration);
  if (!text) return null;
  const glyph = boardIntegrationChipGlyph(integration.status);
  const secondary = boardIntegrationSecondaryText(integration);
  const tone = boardIntegrationChipTone(integration.status);
  const ariaLabel = `集成状态：${text}${secondary ? `，${secondary}` : ""}`;
  return (
    <span className="room-board-integration-wrap">
      <span aria-label={ariaLabel} className={`room-board-integration-chip ${tone}`} role="status">
        <span aria-hidden="true" className="room-board-integration-glyph">
          {glyph}
        </span>
        <span>{text}</span>
      </span>
      {integration.status === "gate_failed" && integration.gate_ids.length ? (
        <small className="room-board-integration-gates">
          {integration.gate_ids.map((gateId) => (
            <code key={gateId}>{gateId}</code>
          ))}
        </small>
      ) : null}
      {secondary ? <small className="room-board-integration-sub">{secondary}</small> : null}
    </span>
  );
}
