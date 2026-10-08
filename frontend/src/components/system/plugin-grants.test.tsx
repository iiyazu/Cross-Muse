import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PluginGrant } from "@/lib/grant-types";
import { useRoomStore } from "@/store/room-store";

import { PluginGrants } from "./plugin-grants";

const ROOM = "conv_00000000000000000000000000000001";

function grant(overrides: Partial<PluginGrant> = {}): PluginGrant {
  return {
    grantId: "grant_1",
    conversationIds: [ROOM],
    host: "claude-code",
    scopes: ["room.message", "board.split.decide", "board.review.decide"],
    status: "active",
    createdAt: "2026-10-06T12:00:00Z",
    activatedAt: "2026-10-06T12:00:30Z",
    expiresAt: "2099-10-06T12:10:30Z",
    revokedAt: null,
    lastUsedAt: null,
    useCount: 0,
    ...overrides
  };
}

function setGrants(grants: PluginGrant[], elsewhere: PluginGrant[] = []) {
  useRoomStore.setState((state) => ({
    grantsByRoom: {
      ...state.grantsByRoom,
      [ROOM]: { grants, elsewhere, loading: false, requestGeneration: 1, consecutiveFailures: 0, lastSyncedAt: 0, error: null }
    }
  }));
}

describe("PluginGrants", () => {
  const revokeGrant = vi.fn().mockResolvedValue(true);

  beforeEach(() => {
    revokeGrant.mockClear();
    useRoomStore.setState({
      startGrantsSync: vi.fn(),
      stopGrantsSync: vi.fn(),
      refreshGrants: vi.fn().mockResolvedValue(undefined),
      revokeGrant
    });
    setGrants([]);
  });

  it("offers no pairing code, only the terminal command with the full Room id", () => {
    render(<PluginGrants roomId={ROOM} />);
    expect(screen.queryByRole("button", { name: /配对码/ })).toBeNull();
    expect(screen.getByText(`xmuse-workroom pair --host claude-code --room ${ROOM}`)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("combobox", { name: "插件所在的工具" }), { target: { value: "opencode" } });
    expect(screen.getByText(`xmuse-workroom pair --host opencode --room ${ROOM}`)).toBeInTheDocument();
  });

  it("lists this Room's grants with what each may do, and revokes a live one", async () => {
    setGrants([grant(), grant({ grantId: "grant_0", status: "revoked", revokedAt: "2026-10-06T12:05:00Z" })]);
    render(<PluginGrants roomId={ROOM} />);
    const rows = within(screen.getByRole("list", { name: "本房间的授权" })).getAllByRole("listitem").filter((item) => item.parentElement?.getAttribute("aria-label") === "本房间的授权");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("已授权")).toBeInTheDocument();
    expect(within(rows[0]).getByText("定复核")).toBeInTheDocument();
    expect(within(rows[1]).queryByRole("button", { name: "撤销" })).toBeNull();
    await act(async () => {
      fireEvent.click(within(rows[0]).getByRole("button", { name: "撤销" }));
    });
    expect(revokeGrant).toHaveBeenCalledWith("grant_1", ROOM);
  });

  it("says a live grant leaves this Room out, once per host", () => {
    const outside = grant({ grantId: "grant_9", conversationIds: ["conv_other"] });
    setGrants([], [outside, { ...outside, grantId: "grant_8" }]);
    render(<PluginGrants roomId={ROOM} />);
    expect(screen.getAllByText("Claude Code 已授权（不含当前房间）")).toHaveLength(1);
  });

  it("drops that notice once the host also covers this Room", () => {
    setGrants([grant()], [grant({ grantId: "grant_9", conversationIds: ["conv_other"] })]);
    render(<PluginGrants roomId={ROOM} />);
    expect(screen.queryByText(/不含当前房间/)).toBeNull();
  });
});
