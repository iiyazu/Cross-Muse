import fs from "node:fs";
import path from "node:path";
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { normalizeRoomBoardProjection } from "@/lib/board-api";
import type { BoardModuleIntegration } from "@/lib/board-integration-types";
import type { RoomBoardProjection } from "@/lib/board-types";
import { IntegrationChip } from "./room-board-integration-chip";

const FIXTURE_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");

function projectionOf(name: string): RoomBoardProjection {
  const payload = JSON.parse(
    fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8")
  ) as { projection: unknown };
  return normalizeRoomBoardProjection(payload.projection);
}

function moduleIntegration(scenario: string, moduleId: string): BoardModuleIntegration {
  const projection = projectionOf(scenario);
  return projection.modules.find((item) => item.module_id === moduleId)!.integration;
}

describe("IntegrationChip", () => {
  it("renders glyph+text for conflicted, waiting, pending and integrated", () => {
    const conflicted = moduleIntegration("integration_conflicted.json", "mb");
    const first = render(<IntegrationChip integration={conflicted} integrationsEnabled />);
    expect(first.getByRole("status").textContent).toContain("集成冲突 · 1 个路径");
    expect(first.container.textContent).toContain("未进入集成分支");
    expect(first.container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
    first.unmount();

    const waiting = moduleIntegration("integration_conflicted.json", "mc");
    const second = render(<IntegrationChip integration={waiting} integrationsEnabled />);
    expect(second.getByRole("status").textContent).toContain("等待依赖集成");
    expect(second.container.textContent).toContain("未进入集成分支");
    second.unmount();

    const pending = moduleIntegration("integration_pending_running.json", "m2");
    const third = render(<IntegrationChip integration={pending} integrationsEnabled />);
    expect(third.getByRole("status").textContent).toContain("排队集成");
    third.unmount();

    const integrated = moduleIntegration("integration_conflicted.json", "ma");
    const fourth = render(<IntegrationChip integration={integrated} integrationsEnabled />);
    expect(fourth.getByRole("status").textContent).toContain("已集成");
    expect(fourth.container.textContent).not.toContain("分支中是旧版本");
    fourth.unmount();
  });

  it("says 分支中是旧版本 for a module that fell back, never 已集成", () => {
    const fellBack = moduleIntegration("integration_fallback_to_incumbent.json", "m1");
    const { container, getByRole } = render(
      <IntegrationChip integration={fellBack} integrationsEnabled />
    );
    expect(getByRole("status").textContent).toContain("集成冲突 · 1 个路径");
    expect(getByRole("status").textContent).not.toContain("已集成");
    expect(container.textContent).toContain("分支中是旧版本");
  });

  it("names suspect gates for gate_failed and auto-retry for error", () => {
    const suspect = moduleIntegration("integration_gate_failed.json", "m2");
    const first = render(<IntegrationChip integration={suspect} integrationsEnabled />);
    expect(first.getByRole("status").textContent).toContain("门禁失败 · 嫌疑");
    expect(first.container.textContent).not.toContain("导致失败");
    expect(first.container.querySelector("code")?.textContent).toBe("patch_diff_check");
    expect(first.container.textContent).toContain("未进入集成分支");
    first.unmount();

    const errored = moduleIntegration("integration_error.json", "m1");
    const second = render(<IntegrationChip integration={errored} integrationsEnabled />);
    expect(second.getByRole("status").textContent).toContain("集成异常");
    expect(second.container.textContent).toContain("宿主会自动重试");
    second.unmount();
  });

  it("renders unknown statuses as ? <raw>", () => {
    const integration: BoardModuleIntegration = {
      status: "unknown",
      statusRaw: "future_status",
      integration_id: "job-1",
      verification_id: "v1",
      integrated_verification_id: null,
      reason_code: null,
      conflict_path_count: 0,
      gate_ids: [],
      updated_at: null
    };
    const { getByRole } = render(<IntegrationChip integration={integration} integrationsEnabled />);
    expect(getByRole("status").textContent).toContain("? future_status");
  });

  it("shows nothing for none or when integrations are disabled", () => {
    const none = moduleIntegration("verified.json", "alpha");
    expect(none.status).toBe("none");
    const first = render(<IntegrationChip integration={none} integrationsEnabled />);
    expect(first.container.textContent).toBe("");
    first.unmount();

    const conflicted = moduleIntegration("integration_conflicted.json", "mb");
    const second = render(<IntegrationChip integration={conflicted} integrationsEnabled={false} />);
    expect(second.container.textContent).toBe("");
  });

  it("never puts ids or paths in aria labels", () => {
    const suspect = moduleIntegration("integration_gate_failed.json", "m2");
    const { getByRole } = render(<IntegrationChip integration={suspect} integrationsEnabled />);
    const label = getByRole("status").getAttribute("aria-label") ?? "";
    expect(label).not.toContain("patch_diff_check");
    expect(label).not.toContain("boardintegration_");
    expect(label).not.toContain("boardverify_");
  });
});
