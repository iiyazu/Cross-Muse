import fs from "node:fs";
import path from "node:path";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { XmuseApiError } from "@/lib/api";
import * as integrationApi from "@/lib/board-integration-api";
import { IntegrationDetailDisclosure } from "./room-board-integration-detail";

const FIXTURE_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");

function loadGolden(name: string) {
  const payload = JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8"));
  return integrationApi.normalizeBoardIntegrationDetail(payload);
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("IntegrationDetailDisclosure", () => {
  it("fetches on first open and renders items, conflicts and versions", async () => {
    const user = userEvent.setup();
    const detail = loadGolden("integration_fallback_to_incumbent.integration.json");
    const fetchSpy = vi
      .spyOn(integrationApi, "fetchBoardIntegrationDetail")
      .mockResolvedValue(detail);
    const { container } = render(
      <IntegrationDetailDisclosure conversationId="conv-1" integrationId="job-1" />
    );
    expect(fetchSpy).not.toHaveBeenCalled();
    await user.click(screen.getByText("集成详情"));
    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    expect(fetchSpy).toHaveBeenCalledWith("conv-1", "job-1");
    await screen.findByText("已集成");
    // The conflicted path renders as plain text in <code>.
    const pathNode = await screen.findByText("docs/b.txt");
    expect(pathNode.tagName).toBe("CODE");
    expect(container.querySelector("script")).toBeNull();
    expect(container.textContent).toContain("新加入");
    expect(container.textContent).toContain("已回退到旧版本");
    expect(container.textContent).toContain("涉及 m2");
    expect(container.textContent).toContain("应用的版本");
    expect(container.textContent).toContain("尝试 1 次");
  });

  it("renders gate output tails through AgentTextView in a scrollable box", async () => {
    const user = userEvent.setup();
    const detail = loadGolden("integration_gate_failed.integration.json");
    vi.spyOn(integrationApi, "fetchBoardIntegrationDetail").mockResolvedValue(detail);
    const { container } = render(
      <IntegrationDetailDisclosure conversationId="conv-1" integrationId="job-1" />
    );
    await user.click(screen.getByText("集成详情"));
    await screen.findByText("门禁失败");
    expect(container.textContent).toContain("未通过");
    expect(container.textContent).toContain("退出码 1");
    const agentNodes = [...container.querySelectorAll('[data-testid="agent-text-view"]')];
    expect(agentNodes.length).toBeGreaterThan(0);
    const tailBox = container.querySelector(".room-board-integration-tail");
    expect(tailBox).not.toBeNull();
    expect(tailBox?.getAttribute("tabindex")).toBe("0");
    expect(container.querySelector("script")).toBeNull();
  });

  it("shows 404 integration detail as missing, other errors with a code", async () => {
    const user = userEvent.setup();
    vi.spyOn(integrationApi, "fetchBoardIntegrationDetail").mockRejectedValue(
      new XmuseApiError({
        code: "room_board_integration_unknown",
        message: "missing",
        retryable: false,
        status: 404
      })
    );
    const first = render(
      <IntegrationDetailDisclosure conversationId="conv-1" integrationId="job-1" />
    );
    await user.click(screen.getByText("集成详情"));
    await screen.findByText("集成记录不存在");
    first.unmount();

    vi.spyOn(integrationApi, "fetchBoardIntegrationDetail").mockRejectedValue(
      new XmuseApiError({ code: "frontend_error", message: "boom", retryable: true, status: 0 })
    );
    const second = render(
      <IntegrationDetailDisclosure conversationId="conv-1" integrationId="job-2" />
    );
    await user.click(screen.getByText("集成详情"));
    await screen.findByText("操作失败，请重试");
    expect(second.container.querySelector("code")?.textContent).toBe("frontend_error");
  });

  it("notes unlisted conflict paths without reconciling counts", async () => {
    const user = userEvent.setup();
    const raw = JSON.parse(
      fs.readFileSync(
        path.join(FIXTURE_DIR, "integration_fallback_to_incumbent.integration.json"),
        "utf8"
      )
    ) as Record<string, unknown>;
    const items = raw.items as Array<Record<string, unknown>>;
    (items[1] as Record<string, unknown>).conflicts_total = 5;
    const detail = integrationApi.normalizeBoardIntegrationDetail(raw);
    vi.spyOn(integrationApi, "fetchBoardIntegrationDetail").mockResolvedValue(detail);
    render(<IntegrationDetailDisclosure conversationId="conv-1" integrationId="job-1" />);
    await user.click(screen.getByText("集成详情"));
    // conflicts_total (5) minus listed (1) = 4 unlisted; the projection count is untouched.
    await screen.findByText("另有 4 个路径未列出");
  });

  it("escapes an invalid conflict path and flags it", async () => {
    const user = userEvent.setup();
    const raw = JSON.parse(
      fs.readFileSync(
        path.join(FIXTURE_DIR, "integration_fallback_to_incumbent.integration.json"),
        "utf8"
      )
    ) as Record<string, unknown>;
    const items = raw.items as Array<Record<string, unknown>>;
    const conflicts = (items[1] as Record<string, unknown>).conflicts as Array<
      Record<string, unknown>
    >;
    conflicts[0].path = "src/‪b.py";
    const detail = integrationApi.normalizeBoardIntegrationDetail(raw);
    vi.spyOn(integrationApi, "fetchBoardIntegrationDetail").mockResolvedValue(detail);
    const { container } = render(
      <IntegrationDetailDisclosure conversationId="conv-1" integrationId="job-1" />
    );
    await user.click(screen.getByText("集成详情"));
    await screen.findByText("路径含不可见字符");
    expect(container.textContent).toContain("src/<U+202A>b.py");
    expect(container.querySelector("script")).toBeNull();
  });
});
