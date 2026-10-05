import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { XmuseApiError } from "@/lib/api";
import type { PluginGrant } from "@/lib/grant-types";
import { useRoomStore } from "@/store/room-store";
import { RoomGrantsDomain } from "./room-grants-domain";

const grantApiMocks = vi.hoisted(() => ({
  issuePluginGrant: vi.fn(),
  listPluginGrants: vi.fn(),
  revokePluginGrant: vi.fn()
}));

vi.mock("@/lib/grant-api", () => grantApiMocks);

function grantPayload(id: string, overrides: Partial<PluginGrant> = {}): PluginGrant {
  return {
    grantId: id,
    conversationId: "room-a",
    host: "claude-code",
    scope: "board.split.decide",
    status: "pending",
    createdAt: "2026-10-05T12:00:00Z",
    activatedAt: null,
    expiresAt: "2026-10-05T12:10:00Z",
    revokedAt: null,
    lastUsedAt: null,
    useCount: 0,
    ...overrides
  };
}

function issueResult(code = "ABCD-EFGH", grantId = "g1") {
  return {
    grant: grantPayload(grantId),
    pairingCode: code,
    pairingExpiresAt: "2026-10-05T12:02:00Z"
  };
}

function openSection(container: HTMLElement) {
  const details = container.querySelector("details.room-grants") as HTMLDetailsElement;
  // jsdom toggles <details> natively but queues its toggle event asynchronously,
  // which races later actions. Deliver the toggle synchronously instead; a late
  // native toggle is a no-op because the open state is unchanged.
  fireEvent.click(details.querySelector("summary") as HTMLElement);
  if (!details.open) details.open = true;
  fireEvent(details, new Event("toggle", { bubbles: false }));
  return details;
}

async function settleRoomGrants(room = "room-a") {
  // Await the real store promise chain (mock fetch + cache write) inside act
  // so the component re-renders deterministically. Joins an in-flight refresh
  // when the open effect or an action already started one.
  await act(async () => {
    await useRoomStore.getState().refreshGrants(room);
  });
}

async function clickIssue() {
  fireEvent.click(screen.getByRole("button", { name: "生成配对码" }));
  await settleRoomGrants();
}

function grantError(code: string, status: number) {
  return new XmuseApiError({ code, message: "server detail text", retryable: false, status });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
  grantApiMocks.listPluginGrants.mockResolvedValue({ conversationId: "room-a", grants: [] });
  useRoomStore.getState().stopSync();
  useRoomStore.getState().stopGrantsSync();
  useRoomStore.setState({
    selectedRoomId: "room-a",
    roomsById: {},
    executionsByRoom: {},
    memoryByRoom: {},
    boardByRoom: {},
    boardActionPending: null,
    boardActionError: null,
    grantsByRoom: {},
    codexByRoom: {},
    inspectorOpen: false,
    dockTab: "room"
  });
  window.localStorage.clear();
  window.sessionStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
  useRoomStore.getState().stopSync();
  useRoomStore.getState().stopGrantsSync();
});

describe("RoomGrantsDomain", () => {
  it("stays collapsed until opened, then shows the form and refreshes the list", async () => {
    const { container } = render(<RoomGrantsDomain conversationId="room-a" />);
    const details = container.querySelector("details.room-grants") as HTMLDetailsElement;
    expect(details.open).toBe(false);
    expect(grantApiMocks.listPluginGrants).not.toHaveBeenCalled();

    openSection(container);
    expect(details.open).toBe(true);
    expect(screen.getByText("授权后，插件只能批准或拒绝待审批拆分，到期自动失效。")).toBeInTheDocument();
    expect(screen.getByLabelText("宿主")).toBeInTheDocument();
    expect(screen.getByLabelText("有效期")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "生成配对码" })).toBeInTheDocument();
    await settleRoomGrants();
    expect(grantApiMocks.listPluginGrants).toHaveBeenCalledWith(
      "room-a",
      expect.objectContaining({})
    );
  });

  it("shows the pairing code without leaking it into shared state or attributes", async () => {
    grantApiMocks.issuePluginGrant.mockResolvedValueOnce(issueResult());
    grantApiMocks.listPluginGrants.mockResolvedValue({
      conversationId: "room-a",
      grants: [grantPayload("g1")]
    });
    const { container } = render(<RoomGrantsDomain conversationId="room-a" />);
    openSection(container);
    await clickIssue();

    const code = screen.getByText("ABCD-EFGH");
    expect(code.tagName).toBe("CODE");
    const instruction = screen.getByText("在插件窗格里输入此码，120 秒内有效，只能使用一次");
    expect(instruction.getAttribute("aria-live")).toBe("polite");
    // The live announcement covers the instruction, never the code.
    expect(instruction.textContent ?? "").not.toContain("ABCD-EFGH");
    expect(code.closest("[aria-live]")).toBeNull();
    expect(screen.getByText(/配对码剩余/)).toBeInTheDocument();

    // The code lives only in component state.
    const serialized = JSON.stringify(useRoomStore.getState());
    expect(serialized).not.toContain("ABCD-EFGH");
    expect(document.title).not.toContain("ABCD-EFGH");
    for (const element of [...container.querySelectorAll("[aria-label],[title]")]) {
      expect(element.getAttribute("aria-label") ?? "").not.toContain("ABCD-EFGH");
      expect(element.getAttribute("title") ?? "").not.toContain("ABCD-EFGH");
    }
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("clears the code when the countdown ends", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-05T12:00:00Z"));
    grantApiMocks.issuePluginGrant.mockResolvedValueOnce(issueResult());
    grantApiMocks.listPluginGrants.mockResolvedValue({
      conversationId: "room-a",
      grants: [grantPayload("g1")]
    });
    const { container } = render(<RoomGrantsDomain conversationId="room-a" />);
    openSection(container);
    await clickIssue();
    expect(screen.getByText("ABCD-EFGH")).toBeInTheDocument();

    vi.setSystemTime(new Date("2026-10-05T12:02:01Z"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(screen.queryByText("ABCD-EFGH")).toBeNull();
  });

  it("clears the code when the grant becomes active and shows the authorized chip", async () => {
    grantApiMocks.issuePluginGrant.mockResolvedValueOnce(issueResult());
    grantApiMocks.listPluginGrants.mockResolvedValue({
      conversationId: "room-a",
      grants: [grantPayload("g1")]
    });
    const { container } = render(<RoomGrantsDomain conversationId="room-a" />);
    openSection(container);
    await clickIssue();
    expect(screen.getByText("ABCD-EFGH")).toBeInTheDocument();

    grantApiMocks.listPluginGrants.mockResolvedValue({
      conversationId: "room-a",
      grants: [grantPayload("g1", { status: "active", activatedAt: "2026-10-05T12:01:00Z" })]
    });
    await act(async () => {
      await useRoomStore.getState().refreshGrants("room-a");
    });
    expect(screen.queryByText("ABCD-EFGH")).toBeNull();
    const chip = screen.getByRole("status", { name: /已授权/ });
    expect(chip.textContent ?? "").toContain("●");
    expect(chip.textContent ?? "").toContain("已授权");
  });

  it("renders glyph-plus-text chips and a revoke button only for live grants", async () => {
    grantApiMocks.listPluginGrants.mockResolvedValue({
      conversationId: "room-a",
      grants: [
        grantPayload("g-pending", { host: "claude-code" }),
        grantPayload("g-active", { host: "opencode", status: "active" }),
        grantPayload("g-expired", { status: "expired" }),
        grantPayload("g-revoked", { status: "revoked" }),
        grantPayload("g-unknown", { status: "unknown" })
      ]
    });
    const { container } = render(<RoomGrantsDomain conversationId="room-a" />);
    openSection(container);
    await settleRoomGrants();
    expect(screen.getByRole("status", { name: /待配对/ })).toBeInTheDocument();
    expect(screen.getByRole("status", { name: /待配对/ }).textContent).toContain("◌");
    expect(screen.getByRole("status", { name: /已授权/ }).textContent).toContain("●");
    expect(screen.getByRole("status", { name: /已过期/ }).textContent).toContain("○");
    expect(screen.getByRole("status", { name: /已撤销/ }).textContent).toContain("✕");
    expect(screen.getByRole("status", { name: /未知状态/ })).toBeInTheDocument();
    expect(container.textContent).toContain("Claude Code");
    expect(container.textContent).toContain("OpenCode");

    const revokeButtons = screen.getAllByRole("button", { name: /撤销/ });
    expect(revokeButtons).toHaveLength(2);
  });

  it("shows relative last-used time, use counts and remaining time", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-05T12:10:00Z"));
    grantApiMocks.listPluginGrants.mockResolvedValue({
      conversationId: "room-a",
      grants: [
        grantPayload("g1", { lastUsedAt: "2026-10-05T12:07:30Z", useCount: 2 }),
        grantPayload("g2", { status: "expired", lastUsedAt: null })
      ]
    });
    const { container } = render(<RoomGrantsDomain conversationId="room-a" />);
    openSection(container);
    await settleRoomGrants();
    expect(screen.getByText(/2 分钟前/)).toBeInTheDocument();
    expect(container.textContent).toContain("使用 2 次");
    expect(container.textContent).toContain("从未使用");
  });

  it("revokes a grant, clears its code and shows the revoked chip", async () => {
    grantApiMocks.issuePluginGrant.mockResolvedValueOnce(issueResult());
    grantApiMocks.listPluginGrants.mockResolvedValue({
      conversationId: "room-a",
      grants: [grantPayload("g1")]
    });
    const { container } = render(<RoomGrantsDomain conversationId="room-a" />);
    openSection(container);
    await clickIssue();
    expect(screen.getByText("ABCD-EFGH")).toBeInTheDocument();

    grantApiMocks.revokePluginGrant.mockResolvedValueOnce(
      grantPayload("g1", { status: "revoked", revokedAt: "2026-10-05T12:03:00Z" })
    );
    grantApiMocks.listPluginGrants.mockResolvedValue({
      conversationId: "room-a",
      grants: [grantPayload("g1", { status: "revoked", revokedAt: "2026-10-05T12:03:00Z" })]
    });
    fireEvent.click(screen.getByRole("button", { name: /撤销/ }));
    await settleRoomGrants();
    expect(grantApiMocks.revokePluginGrant).toHaveBeenCalledWith(
      "g1",
      "room-a",
      expect.objectContaining({})
    );
    expect(screen.queryByText("ABCD-EFGH")).toBeNull();
    expect(screen.getByRole("status", { name: /已撤销/ })).toBeInTheDocument();
  });

  it("clears the code when the room changes", async () => {
    grantApiMocks.issuePluginGrant.mockResolvedValueOnce(issueResult());
    const { container, rerender } = render(<RoomGrantsDomain conversationId="room-a" />);
    openSection(container);
    await clickIssue();
    expect(screen.getByText("ABCD-EFGH")).toBeInTheDocument();

    rerender(<RoomGrantsDomain conversationId="room-b" />);
    expect(screen.queryByText("ABCD-EFGH")).toBeNull();
  });

  it("polls the list only while the section is open", async () => {
    vi.useFakeTimers();
    grantApiMocks.listPluginGrants.mockResolvedValue({ conversationId: "room-a", grants: [] });
    const { container } = render(<RoomGrantsDomain conversationId="room-a" />);
    const details = openSection(container);
    await settleRoomGrants();
    expect(grantApiMocks.listPluginGrants).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(grantApiMocks.listPluginGrants).toHaveBeenCalledTimes(2);

    fireEvent.click(details.querySelector("summary") as HTMLElement);
    details.open = false;
    fireEvent(details, new Event("toggle", { bubbles: false }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_000);
    });
    expect(grantApiMocks.listPluginGrants).toHaveBeenCalledTimes(2);
  });

  it("renders error text from the code and never the server message", async () => {
    const { container } = render(<RoomGrantsDomain conversationId="room-a" />);
    openSection(container);

    grantApiMocks.issuePluginGrant.mockRejectedValueOnce(grantError("plugin_grant_host_invalid", 422));
    await clickIssue();
    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain("宿主无效");
    expect(alert.textContent).not.toContain("server detail text");

    grantApiMocks.issuePluginGrant.mockRejectedValueOnce(grantError("room_conversation_unknown", 404));
    await clickIssue();
    expect(screen.getByRole("alert").textContent).toContain("房间不存在");

    grantApiMocks.issuePluginGrant.mockRejectedValueOnce(grantError("plugin_grant_scope_invalid", 422));
    await clickIssue();
    expect(screen.getByRole("alert").textContent).toContain("范围无效");

    grantApiMocks.issuePluginGrant.mockRejectedValueOnce(grantError("plugin_grant_request_invalid", 400));
    await clickIssue();
    expect(screen.getByRole("alert").textContent).toContain("请求无效");

    grantApiMocks.issuePluginGrant.mockRejectedValueOnce(grantError("plugin_grant_unknown", 404));
    await clickIssue();
    expect(screen.getByRole("alert").textContent).toContain("授权不存在或不属于此房间");

    grantApiMocks.issuePluginGrant.mockRejectedValueOnce(grantError("operator_auth_not_configured", 503));
    await clickIssue();
    expect(screen.getByRole("alert").textContent).toContain(
      "服务端未配置 operator 令牌，无法签发授权"
    );

    grantApiMocks.issuePluginGrant.mockRejectedValueOnce(grantError("something_new", 500));
    await clickIssue();
    const generic = screen.getByRole("alert");
    expect(generic.textContent).toContain("操作失败，请重试");
    expect(generic.querySelector("code")?.textContent).toBe("something_new");
    expect(container.textContent).not.toContain("server detail text");
  });
});
