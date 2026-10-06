import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PluginGrant } from "@/lib/grant-types";
import { useRoomStore } from "@/store/room-store";

import { PluginGrants } from "./plugin-grants";

const issuePluginGrant = vi.fn();
vi.mock("@/lib/grant-api", () => ({ issuePluginGrant: (...args: unknown[]) => issuePluginGrant(...args) }));

const ISSUED_AT = Date.parse("2026-10-06T12:00:00Z");

function grant(status: PluginGrant["status"]): PluginGrant {
  return {
    grantId: "grant_1",
    conversationId: "room-1",
    host: "claude-code",
    scope: "board.split.decide",
    status,
    createdAt: "2026-10-06T12:00:00Z",
    activatedAt: status === "active" ? "2026-10-06T12:00:30Z" : null,
    expiresAt: status === "active" ? "2026-10-06T12:10:30Z" : "2026-10-06T12:02:00Z",
    revokedAt: null,
    lastUsedAt: null,
    useCount: 0
  };
}

function setGrants(grants: PluginGrant[]) {
  useRoomStore.setState((state) => ({
    grantsByRoom: {
      ...state.grantsByRoom,
      "room-1": { grants, loading: false, requestGeneration: 1, consecutiveFailures: 0, lastSyncedAt: 0, error: null }
    }
  }));
}

describe("PluginGrants", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(ISSUED_AT);
    issuePluginGrant.mockResolvedValue({
      grant: grant("pending"),
      pairingCode: "ABCD-EFGH",
      pairingExpiresAt: "2026-10-06T12:02:00Z"
    });
    useRoomStore.setState({
      startGrantsSync: vi.fn(),
      stopGrantsSync: vi.fn(),
      refreshGrants: vi.fn().mockResolvedValue(undefined),
      revokeGrant: vi.fn().mockResolvedValue(true)
    });
    setGrants([]);
  });

  afterEach(() => {
    vi.useRealTimers();
    issuePluginGrant.mockReset();
  });

  async function issue() {
    render(<PluginGrants roomId="room-1" />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "生成配对码" }));
    });
  }

  it("shows the pairing code once, outside any live region and any attribute", async () => {
    await issue();
    expect(screen.getByText("ABCD-EFGH")).toBeInTheDocument();
    for (const region of document.querySelectorAll("[aria-live], [role=status], [role=alert]")) {
      expect(region.textContent).not.toContain("ABCD-EFGH");
    }
    const attributes = [...document.querySelectorAll("*")].flatMap((element) => [...element.attributes].map((attribute) => attribute.value));
    expect(attributes.some((value) => value.includes("ABCD-EFGH"))).toBe(false);
  });

  it("drops the code when the pairing window ends", async () => {
    await issue();
    expect(screen.getByText("ABCD-EFGH")).toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(121_000);
    });
    expect(screen.queryByText("ABCD-EFGH")).toBeNull();
  });

  it("drops the code as soon as the grant becomes active", async () => {
    await issue();
    act(() => setGrants([grant("active")]));
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });
    expect(screen.queryByText("ABCD-EFGH")).toBeNull();
    expect(screen.getByText("已授权")).toBeInTheDocument();
  });
});
