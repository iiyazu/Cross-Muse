import { beforeEach, describe, expect, it, vi } from "vitest";

const grantApiMocks = vi.hoisted(() => ({
  issuePluginGrant: vi.fn(),
  listPluginGrants: vi.fn(),
  revokePluginGrant: vi.fn()
}));

vi.mock("@/lib/grant-api", () => grantApiMocks);

const boardApiMocks = vi.hoisted(() => ({
  fetchRoomBoardSummary: vi.fn(async () => ({
    schema_version: "room_board_summary/v1",
    revision: "1:aaa"
  })),
  fetchRoomBoard: vi.fn(async () => ({
    schema_version: "room_board_projection/v2",
    revision: "1:aaa"
  })),
  fetchBoardContract: vi.fn(),
  decideBoardSplit: vi.fn()
}));

vi.mock("@/lib/board-api", () => boardApiMocks);

const apiMocks = vi.hoisted(() => ({
  fetchRooms: vi.fn(async () => ({ schema_version: "room_list_projection/v1", rooms: [] })),
  fetchRoomProjection: vi.fn(async () => ({
    schema_version: "room_chat_projection/v3",
    event_cursor: 0,
    conversation: { id: "room-a", title: "Room A" },
    status: "settled",
    participants: [],
    turns: [],
    timeline_items: [],
    page: { has_older: false, has_newer: false }
  })),
  fetchEvents: vi.fn(async () => ({ events: [], has_more: false })),
  fetchRoomOperations: vi.fn(async () => {
    throw new Error("not needed");
  }),
  fetchRoomExecutions: vi.fn(async () => {
    throw new Error("not needed");
  }),
  fetchRoomExecutionCandidate: vi.fn(async () => {
    throw new Error("not needed");
  }),
  fetchRoomMemory: vi.fn(async () => {
    throw new Error("not needed");
  }),
  fetchRoomCodexAgents: vi.fn(async () => {
    throw new Error("not needed");
  }),
  describeError: vi.fn((error: unknown) => ({
    code: "request_failed",
    message: error instanceof Error ? error.message : "请求失败",
    retryable: true,
    status: 0
  })),
  isCallerAbort: vi.fn(() => false)
}));

vi.mock("@/lib/api", () => apiMocks);

const { useRoomStore } = await import("./room-store");

function grant(id: string, status = "pending") {
  return {
    grantId: id,
    conversationId: "room-a",
    host: "claude-code",
    scope: "board.split.decide",
    status,
    createdAt: "2026-10-05T12:00:00Z",
    activatedAt: null,
    expiresAt: "2026-10-05T12:10:00Z",
    revokedAt: null,
    lastUsedAt: null,
    useCount: 0
  };
}

function listResult(grants: ReturnType<typeof grant>[]) {
  return { conversationId: "room-a", grants };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useRealTimers();
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
    inspectorOpen: true,
    dockTab: "room"
  });
});

describe("grants store", () => {
  it("stores the refreshed grant list and clears the previous error", async () => {
    grantApiMocks.listPluginGrants.mockResolvedValueOnce(listResult([grant("g1")]));
    await useRoomStore.getState().refreshGrants("room-a");
    const cache = useRoomStore.getState().grantsByRoom["room-a"];
    expect(grantApiMocks.listPluginGrants).toHaveBeenCalledWith(
      "room-a",
      expect.objectContaining({})
    );
    expect(cache?.grants.map((item) => item.grantId)).toEqual(["g1"]);
    expect(cache?.error).toBeNull();
    expect(cache?.loading).toBe(false);
  });

  it("keeps the last list and records the failure on error", async () => {
    grantApiMocks.listPluginGrants.mockResolvedValueOnce(listResult([grant("g1")]));
    await useRoomStore.getState().refreshGrants("room-a");
    grantApiMocks.listPluginGrants.mockRejectedValueOnce(new Error("grants offline"));
    await useRoomStore.getState().refreshGrants("room-a");
    const cache = useRoomStore.getState().grantsByRoom["room-a"];
    expect(cache?.grants.map((item) => item.grantId)).toEqual(["g1"]);
    expect(cache?.consecutiveFailures).toBe(1);
    expect(cache?.error?.code).toBe("request_failed");
  });

  it("polls every five seconds only while the grants sync runs", async () => {
    vi.useFakeTimers();
    grantApiMocks.listPluginGrants.mockResolvedValue(listResult([grant("g1")]));
    useRoomStore.getState().startGrantsSync("room-a");
    expect(grantApiMocks.listPluginGrants).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(5_000);
    expect(grantApiMocks.listPluginGrants).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5_000);
    expect(grantApiMocks.listPluginGrants).toHaveBeenCalledTimes(2);
    useRoomStore.getState().stopGrantsSync();
    await vi.advanceTimersByTimeAsync(15_000);
    expect(grantApiMocks.listPluginGrants).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });

  it("restarts the poll instead of stacking two loops", async () => {
    vi.useFakeTimers();
    grantApiMocks.listPluginGrants.mockResolvedValue(listResult([]));
    useRoomStore.getState().startGrantsSync("room-a");
    useRoomStore.getState().startGrantsSync("room-a");
    await vi.advanceTimersByTimeAsync(5_000);
    expect(grantApiMocks.listPluginGrants).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("revokes through the fixed route and refreshes the list", async () => {
    grantApiMocks.revokePluginGrant.mockResolvedValueOnce(grant("g1", "revoked"));
    grantApiMocks.listPluginGrants.mockResolvedValueOnce(listResult([grant("g1", "revoked")]));
    const applied = await useRoomStore.getState().revokeGrant("g1", "room-a");
    expect(applied).toBe(true);
    expect(grantApiMocks.revokePluginGrant).toHaveBeenCalledWith(
      "g1",
      "room-a",
      expect.objectContaining({})
    );
    expect(useRoomStore.getState().grantsByRoom["room-a"]?.grants[0]?.status).toBe("revoked");
  });

  it("reports a failed revoke without clearing the cached list", async () => {
    grantApiMocks.listPluginGrants.mockResolvedValueOnce(listResult([grant("g1")]));
    await useRoomStore.getState().refreshGrants("room-a");
    grantApiMocks.revokePluginGrant.mockRejectedValueOnce(new Error("revoke denied"));
    const applied = await useRoomStore.getState().revokeGrant("g1", "room-a");
    expect(applied).toBe(false);
    const cache = useRoomStore.getState().grantsByRoom["room-a"];
    expect(cache?.grants.map((item) => item.grantId)).toEqual(["g1"]);
    expect(cache?.error?.code).toBe("request_failed");
  });

  it("drops a stale grants response after switching rooms", async () => {
    let resolveList!: (value: ReturnType<typeof listResult>) => void;
    grantApiMocks.listPluginGrants.mockImplementationOnce(
      () => new Promise((resolve) => { resolveList = resolve; })
    );
    useRoomStore.setState({ selectedRoomId: "room-a", inspectorOpen: false });
    const pending = useRoomStore.getState().refreshGrants("room-a");
    await Promise.resolve();
    await useRoomStore.getState().selectRoom("room-b");
    useRoomStore.getState().stopSync();
    resolveList(listResult([grant("g1")]));
    await pending;
    expect(useRoomStore.getState().grantsByRoom["room-a"]?.grants ?? []).toEqual([]);
    expect(useRoomStore.getState().selectedRoomId).toBe("room-b");
  });

  it("does not start the grants poll when the inspector opens or the Room tab is selected", async () => {
    useRoomStore.setState({ inspectorOpen: false });
    useRoomStore.getState().setInspectorOpen(true);
    await vi.waitFor(() => {
      expect(useRoomStore.getState().boardByRoom["room-a"]?.summary).toBeTruthy();
    });
    const boardCalls = boardApiMocks.fetchRoomBoardSummary.mock.calls.length;
    expect(boardCalls).toBeGreaterThan(0);
    expect(grantApiMocks.listPluginGrants).not.toHaveBeenCalled();

    useRoomStore.setState({ inspectorOpen: false, dockTab: "runtime" });
    useRoomStore.getState().setDockTab("room");
    await vi.waitFor(() => {
      expect(boardApiMocks.fetchRoomBoardSummary.mock.calls.length).toBeGreaterThan(boardCalls);
    });
    expect(grantApiMocks.listPluginGrants).not.toHaveBeenCalled();
    useRoomStore.getState().stopSync();
  });
});
