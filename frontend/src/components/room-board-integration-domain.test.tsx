import fs from "node:fs";
import path from "node:path";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  normalizeBoardSummary,
  normalizeRoomBoardProjection
} from "@/lib/board-api";
import * as integrationApi from "@/lib/board-integration-api";
import { normalizeBoardIntegrationDetail } from "@/lib/board-integration-api";
import { noneModuleIntegration } from "@/lib/board-integration-types";
import type { RoomBoardProjection } from "@/lib/board-types";
import type { RoomBoardCache } from "@/store/domain/board";
import { RoomBoardDomain } from "./room-board-domain";

const FIXTURE_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");

const NON_INTEGRATION_SCENARIOS = [
  "contract_revised_stale_dependent.json",
  "empty.json",
  "injection_text.json",
  "lifecycle_mix.json",
  "split_approved_via_plugin.json",
  "split_pending.json",
  "superseded_done.json",
  "verification_error.json",
  "verification_escalated.json",
  "verification_failed_rework.json",
  "verified.json",
  "verifying_and_waiting.json"
];

function cacheFor(name: string): RoomBoardCache {
  const payload = JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8")) as {
    projection: unknown;
    summary: unknown;
  };
  return {
    projection: normalizeRoomBoardProjection(payload.projection),
    summary: normalizeBoardSummary(payload.summary),
    loading: false,
    requestGeneration: 1,
    consecutiveFailures: 0,
    lastSyncedAt: Date.now(),
    error: null,
    contractDetails: {},
    reviewDetails: {},
    reviewDetailErrors: {}
  };
}

function stripIntegration(projection: RoomBoardProjection): RoomBoardProjection {
  return {
    ...projection,
    capabilities: { ...projection.capabilities, integrations: 0 },
    integration: { green_head_commit: null, latest: null },
    modules: projection.modules.map((item) => ({
      ...item,
      integration: noneModuleIntegration()
    })),
    attention: projection.attention.map((item) => ({ ...item, integration_id: null }))
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("integration room summary", () => {
  it("writes 已验证 when reviews are off, 已验收 when reviews are on", () => {
    const off = cacheFor("integration_fallback_to_incumbent.json");
    const first = render(<RoomBoardDomain cache={off} onLoadContract={vi.fn()} />);
    const line = first.container.querySelector(
      ".room-board-accepted-total"
    ) as HTMLElement | null;
    expect(line).not.toBeNull();
    expect(line?.textContent).toContain("已验证 3");
    expect(line?.textContent).toContain("已集成 2");
    expect(line?.textContent).not.toContain("已验收");
    // Green head short with the full commit in title.
    const green = within(line as HTMLElement).getByText("8d191a5e");
    expect(green.tagName).toBe("CODE");
    expect(green.getAttribute("title")).toBe(
      "8d191a5e343aa15363492f7a1570b59100c54300"
    );
    first.unmount();

    const on = cacheFor("review_endorsed_integrated.json");
    const second = render(<RoomBoardDomain cache={on} onLoadContract={vi.fn()} />);
    const reviewed = second.container.querySelector(
      ".room-board-accepted-total"
    ) as HTMLElement | null;
    expect(reviewed?.textContent).toContain("已验收 1");
    expect(reviewed?.textContent).toContain("已集成 1");
  });

  function summaryLineText(container: HTMLElement): string | null {
    const line = container.querySelector(".room-board-accepted-total");
    return line?.textContent ?? null;
  }

  it("names the latest job word when it is not integrated", () => {
    const gateFailed = cacheFor("integration_gate_failed.json");
    const first = render(<RoomBoardDomain cache={gateFailed} onLoadContract={vi.fn()} />);
    expect(summaryLineText(first.container)).toContain("门禁失败");
    expect(first.getByText("最近一次集成详情")).toBeInTheDocument();
    first.unmount();

    const errored = cacheFor("integration_error.json");
    const second = render(<RoomBoardDomain cache={errored} onLoadContract={vi.fn()} />);
    expect(summaryLineText(second.container)).toContain("异常");
    expect(second.getByText("最近一次集成详情")).toBeInTheDocument();
    second.unmount();

    const pending = cacheFor("integration_pending_running.json");
    const third = render(<RoomBoardDomain cache={pending} onLoadContract={vi.fn()} />);
    expect(summaryLineText(third.container)).toContain("排队");
    // No finished troubled job: no room-level detail.
    expect(third.queryByText("最近一次集成详情")).toBeNull();
  });

  it("counts integrated_total from modules when the summary lacks it", () => {
    const cache = cacheFor("integration_fallback_to_incumbent.json");
    const { summary, ...rest } = cache;
    void summary;
    const withoutSummary: RoomBoardCache = { ...rest, summary: null };
    const { container } = render(
      <RoomBoardDomain cache={withoutSummary} onLoadContract={vi.fn()} />
    );
    expect(summaryLineText(container)).toContain("已集成 2");
  });
});

describe("integration capability gating", () => {
  it("renders no integration UI when capabilities.integrations is 0", () => {
    const cache = cacheFor("integration_fallback_to_incumbent.json");
    cache.projection = {
      ...cache.projection!,
      capabilities: { ...cache.projection!.capabilities, integrations: 0 }
    };
    const { container } = render(<RoomBoardDomain cache={cache} onLoadContract={vi.fn()} />);
    // Module chips, the summary line, green head and detail disclosures are all gated.
    // (The generic attention strip still shows the server-provided reason label.)
    expect(container.querySelector(".room-board-integration-chip")).toBeNull();
    expect(container.querySelector(".room-board-accepted-total")).toBeNull();
    expect(container.textContent).not.toContain("集成分支");
    expect(container.textContent).not.toContain("集成详情");
    expect(container.textContent).not.toContain("分支中是旧版本");
  });

  it("leaves the DOM identical for scenarios without integration data", () => {
    expect(NON_INTEGRATION_SCENARIOS).toHaveLength(12);
    for (const name of NON_INTEGRATION_SCENARIOS) {
      const cache = cacheFor(name);
      const full = render(<RoomBoardDomain cache={cache} onLoadContract={vi.fn()} />);
      const fullHtml = full.container.innerHTML;
      full.unmount();
      const stripped: RoomBoardCache = {
        ...cache,
        projection: stripIntegration(cache.projection!),
        summary: {
          ...cache.summary!,
          integrated_total: 0,
          integration: { status: null, statusRaw: null, green_head_commit: null }
        }
      };
      const second = render(<RoomBoardDomain cache={stripped} onLoadContract={vi.fn()} />);
      expect(second.container.innerHTML, name).toBe(fullHtml);
      second.unmount();
    }
  });
});

describe("integration module cards and events", () => {
  it("mounts 集成详情 only for conflicted/gate_failed/error/waiting modules with an id", () => {
    const cache = cacheFor("integration_fallback_to_incumbent.json");
    const { container } = render(<RoomBoardDomain cache={cache} onLoadContract={vi.fn()} />);
    const cards = [...container.querySelectorAll(".room-board-module")];
    const byId = new Map(
      cards.map((card) => [card.querySelector("code")?.textContent, card] as const)
    );
    expect(byId.get("m1")?.textContent).toContain("集成详情");
    expect(byId.get("m1")?.textContent).toContain("集成冲突 · 1 个路径");
    expect(byId.get("m2")?.textContent).toContain("已集成");
    expect(byId.get("m2")?.textContent).not.toContain("集成详情");
    expect(byId.get("m3")?.textContent).not.toContain("集成详情");

    const waiting = cacheFor("integration_conflicted.json");
    const second = render(<RoomBoardDomain cache={waiting} onLoadContract={vi.fn()} />);
    const waitingCards = [...second.container.querySelectorAll(".room-board-module")];
    const waitingById = new Map(
      waitingCards.map((card) => [card.querySelector("code")?.textContent, card] as const)
    );
    expect(waitingById.get("mc")?.textContent).toContain("集成详情");
    expect(waitingById.get("ma")?.textContent).not.toContain("集成详情");
  });

  it("renders integration events from structured fields in the room list only", () => {
    const cache = cacheFor("integration_fallback_to_incumbent.json");
    const { container } = render(<RoomBoardDomain cache={cache} onLoadContract={vi.fn()} />);
    const events = container.querySelector(".room-board-events");
    expect(events?.textContent).toContain("集成结果");
    expect(events?.textContent).toContain("已集成 3 个模块");
    expect(events?.textContent).toContain("m1 冲突 1 个路径（已回退）");
    for (const card of container.querySelectorAll(".room-board-module")) {
      expect(card.textContent).not.toContain("已回退");
    }
  });

  it("renders suspects for a gate_failed event and never crashes on null module_id", () => {
    const cache = cacheFor("integration_gate_failed.json");
    const { container } = render(<RoomBoardDomain cache={cache} onLoadContract={vi.fn()} />);
    const events = container.querySelector(".room-board-events");
    expect(events?.textContent).toContain("门禁失败");
    expect(events?.textContent).toContain("嫌疑 m2");
  });

  it("keeps state, accepted and review rendering untouched next to integration", () => {
    const cache = cacheFor("review_endorsed_integrated.json");
    const { container } = render(<RoomBoardDomain cache={cache} onLoadContract={vi.fn()} />);
    expect(container.querySelector('[data-state="verified"]')).toBeInTheDocument();
    expect(container.querySelector(".room-board-accepted")).toBeInTheDocument();
    expect(container.textContent).toContain("已背书");
    expect(container.textContent).toContain("已集成");
  });

  it("opens the module 集成详情 and highlights that module", async () => {
    const user = userEvent.setup();
    const detailPayload = JSON.parse(
      fs.readFileSync(
        path.join(FIXTURE_DIR, "integration_fallback_to_incumbent.integration.json"),
        "utf8"
      )
    );
    const detail = normalizeBoardIntegrationDetail(detailPayload);
    vi.spyOn(integrationApi, "fetchBoardIntegrationDetail").mockResolvedValue(detail);
    const cache = cacheFor("integration_fallback_to_incumbent.json");
    const { container } = render(<RoomBoardDomain cache={cache} onLoadContract={vi.fn()} />);
    const cards = [...container.querySelectorAll(".room-board-module")];
    const m1 = cards.find((card) => card.querySelector("code")?.textContent === "m1")!;
    await user.click(within(m1 as HTMLElement).getByText("集成详情"));
    const matches = await within(m1 as HTMLElement).findAllByText("docs/b.txt");
    // One is the charter path (<dd>), the other the conflict path (<code>).
    expect(matches.some((node) => node.tagName === "CODE")).toBe(true);
    const highlighted = container.querySelector(
      '.room-board-integration-item.is-self[data-module-id="m1"]'
    );
    expect(highlighted).not.toBeNull();
    expect(highlighted?.textContent).toContain("本模块");
  });
});
