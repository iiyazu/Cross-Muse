import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BoardSplit } from "@/lib/board-types";

const boardApiMocks = vi.hoisted(() => ({
  fetchRoomBoardSummary: vi.fn(),
  fetchRoomBoard: vi.fn(),
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

function summary(revision: string) {
  return {
    schema_version: "room_board_summary/v1" as const,
    conversation_id: "room-a",
    server_time: "2026-10-04T12:00:00Z",
    board_seq: 1,
    revision,
    capabilities: { verification: 1, reviews: 0, integrations: 0, lessons: 0 },
    modules_total: 0,
    counts: {
      assigned: 0,
      claimed: 0,
      working: 0,
      blocked: 0,
      ready_for_review: 0,
      done_claimed: 0,
      verifying: 0,
      waiting_for_provider: 0,
      verified: 0,
      verification_failed: 0,
      verification_error: 0
    },
    attention_total: 0,
    attention: []
  };
}

function projection(revision: string) {
  return {
    schema_version: "room_board_projection/v2" as const,
    metrics_version: "board_metrics/v1",
    conversation_id: "room-a",
    server_time: "2026-10-04T12:00:00Z",
    board_seq: 1,
    revision,
    capabilities: { verification: 1, reviews: 0, integrations: 0, lessons: 0 },
    participants: [],
    modules: [],
    contracts: [],
    splits: [],
    stale_dependents: [],
    attention: [],
    events: []
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useRoomStore.getState().stopSync();
  useRoomStore.setState({
    selectedRoomId: "room-a",
    roomsById: {},
    executionsByRoom: {},
    memoryByRoom: {},
    boardByRoom: {},
    boardActionPending: null,
    boardActionError: null,
    codexByRoom: {},
    inspectorOpen: true,
    dockTab: "room"
  });
});

describe("board store sync", () => {
  it("fetches the full projection only when the summary revision changed", async () => {
    boardApiMocks.fetchRoomBoardSummary.mockResolvedValue(summary("1:aaa"));
    boardApiMocks.fetchRoomBoard.mockResolvedValue(projection("1:aaa"));
    await useRoomStore.getState().refreshBoard("room-a");
    expect(boardApiMocks.fetchRoomBoardSummary).toHaveBeenCalledTimes(1);
    expect(boardApiMocks.fetchRoomBoard).toHaveBeenCalledTimes(1);

    boardApiMocks.fetchRoomBoardSummary.mockResolvedValue(summary("1:aaa"));
    await useRoomStore.getState().refreshBoard("room-a");
    expect(boardApiMocks.fetchRoomBoardSummary).toHaveBeenCalledTimes(2);
    expect(boardApiMocks.fetchRoomBoard).toHaveBeenCalledTimes(1);

    boardApiMocks.fetchRoomBoardSummary.mockResolvedValue(summary("2:bbb"));
    boardApiMocks.fetchRoomBoard.mockResolvedValue(projection("2:bbb"));
    await useRoomStore.getState().refreshBoard("room-a");
    expect(boardApiMocks.fetchRoomBoard).toHaveBeenCalledTimes(2);
    expect(useRoomStore.getState().boardByRoom["room-a"]?.projection?.revision).toBe("2:bbb");
  });

  it("drops a stale response from an older generation", async () => {
    boardApiMocks.fetchRoomBoardSummary.mockResolvedValue(summary("9:keep"));
    boardApiMocks.fetchRoomBoard.mockResolvedValue(projection("9:keep"));
    await useRoomStore.getState().refreshBoard("room-a");
    expect(useRoomStore.getState().boardByRoom["room-a"]?.summary?.revision).toBe("9:keep");

    let resolveStale!: (value: ReturnType<typeof summary>) => void;
    boardApiMocks.fetchRoomBoardSummary.mockImplementationOnce(
      () => new Promise((resolve) => { resolveStale = resolve; })
    );
    const stale = useRoomStore.getState().refreshBoard("room-a");
    await Promise.resolve();
    const generation = useRoomStore.getState().boardByRoom["room-a"]?.requestGeneration ?? 0;
    useRoomStore.setState((state) => ({
      boardByRoom: {
        ...state.boardByRoom,
        "room-a": {
          ...(state.boardByRoom["room-a"] ?? {
            projection: projection("9:keep"),
            summary: summary("9:keep"),
            loading: true,
            requestGeneration: generation,
            consecutiveFailures: 0,
            lastSyncedAt: 0,
            error: null,
            contractDetails: {}
          }),
          requestGeneration: generation + 1
        }
      }
    }));
    resolveStale(summary("1:old"));
    await stale;
    // The stale summary must not clear the newer projection.
    expect(useRoomStore.getState().boardByRoom["room-a"]?.summary?.revision).toBe("9:keep");
  });

  it("keeps the last projection and increments failures on error", async () => {
    boardApiMocks.fetchRoomBoardSummary.mockResolvedValue(summary("1:aaa"));
    boardApiMocks.fetchRoomBoard.mockResolvedValue(projection("1:aaa"));
    await useRoomStore.getState().refreshBoard("room-a");
    boardApiMocks.fetchRoomBoardSummary.mockRejectedValueOnce(new Error("board offline"));
    await useRoomStore.getState().refreshBoard("room-a");
    const cache = useRoomStore.getState().boardByRoom["room-a"];
    expect(cache?.projection?.revision).toBe("1:aaa");
    expect(cache?.consecutiveFailures).toBe(1);
    expect(cache?.error?.message).toBe("board offline");
  });

  it("aborts the in-flight board request when switching rooms", async () => {
    let resolveSummary!: (value: ReturnType<typeof summary>) => void;
    boardApiMocks.fetchRoomBoardSummary.mockImplementationOnce(
      () => new Promise((resolve) => { resolveSummary = resolve; })
    );
    useRoomStore.setState({ selectedRoomId: "room-a", inspectorOpen: false });
    const pending = useRoomStore.getState().refreshBoard("room-a");
    await Promise.resolve();
    await useRoomStore.getState().selectRoom("room-b");
    useRoomStore.getState().stopSync();
    resolveSummary(summary("1:aaa"));
    await pending;
    expect(useRoomStore.getState().boardByRoom["room-a"]?.projection).toBeNull();
    expect(useRoomStore.getState().selectedRoomId).toBe("room-b");
  });

  it("loads the board as soon as the inspector opens instead of waiting for the poll", async () => {
    boardApiMocks.fetchRoomBoardSummary.mockResolvedValue(summary("1:aaa"));
    boardApiMocks.fetchRoomBoard.mockResolvedValue(projection("1:aaa"));
    useRoomStore.setState({ inspectorOpen: false });
    useRoomStore.getState().setInspectorOpen(true);
    await vi.waitFor(() => {
      expect(useRoomStore.getState().boardByRoom["room-a"]?.projection?.revision).toBe("1:aaa");
    });
    useRoomStore.getState().stopSync();
  });

  it("loads the board when the Room dock tab is selected", async () => {
    boardApiMocks.fetchRoomBoardSummary.mockResolvedValue(summary("1:aaa"));
    boardApiMocks.fetchRoomBoard.mockResolvedValue(projection("1:aaa"));
    useRoomStore.setState({ inspectorOpen: false, dockTab: "runtime" });
    useRoomStore.getState().setDockTab("room");
    await vi.waitFor(() => {
      expect(useRoomStore.getState().boardByRoom["room-a"]?.projection?.revision).toBe("1:aaa");
    });
    useRoomStore.getState().stopSync();
  });
});

describe("board split decisions", () => {
  const digest = `sha256:${"c".repeat(64)}`;

  function split(): BoardSplit {
    return {
      split_id: "split-1",
      status: "proposed",
      proposed_by_participant_id: "lead",
      created_at: "2026-10-04T12:00:00Z",
      decided_at: null,
      digest,
      decided_via: null,
      modules: [],
      contracts: [],
      actions: {
        decide: {
          available: true,
          method: "POST",
          href: "/api/chat/operator/board-splits/split-1/decision",
          expected_digest: digest,
          allowed_decisions: ["approve", "reject"]
        }
      }
    };
  }

  function refreshedBoard() {
    boardApiMocks.fetchRoomBoardSummary.mockResolvedValue(summary("2:bbb"));
    boardApiMocks.fetchRoomBoard.mockResolvedValue(projection("2:bbb"));
  }

  it("refreshes the board cache on a successful decision", async () => {
    refreshedBoard();
    boardApiMocks.decideBoardSplit.mockResolvedValue({ status: "decided" });
    const applied = await useRoomStore.getState().decideBoardSplit(
      { ...split() },
      "approve",
      "room-a"
    );
    expect(applied).toBe(true);
    expect(boardApiMocks.decideBoardSplit).toHaveBeenCalledTimes(1);
    const request = boardApiMocks.decideBoardSplit.mock.calls[0];
    expect(request[1]).toBe("approve");
    expect(useRoomStore.getState().boardByRoom["room-a"]?.summary?.revision).toBe("2:bbb");
    expect(useRoomStore.getState().boardActionPending).toBeNull();
    expect(useRoomStore.getState().boardActionError).toBeNull();
  });

  it("refreshes and keeps the 409 notice without retrying on a stale decision", async () => {
    refreshedBoard();
    boardApiMocks.decideBoardSplit.mockRejectedValueOnce(new Error("digest mismatch"));
    apiMocks.describeError.mockReturnValueOnce({
      code: "room_board_split_digest_mismatch",
      message: "stale digest",
      retryable: false,
      status: 409
    });
    const applied = await useRoomStore.getState().decideBoardSplit(
      { ...split() },
      "reject",
      "room-a"
    );
    expect(applied).toBe(false);
    expect(boardApiMocks.decideBoardSplit).toHaveBeenCalledTimes(1);
    expect(useRoomStore.getState().boardByRoom["room-a"]?.summary?.revision).toBe("2:bbb");
    expect(useRoomStore.getState().boardActionPending).toBeNull();
    expect(useRoomStore.getState().boardActionError?.status).toBe(409);
  });

  it("blocks a second decision while one is in flight", async () => {
    refreshedBoard();
    let resolveDecision!: (value: unknown) => void;
    boardApiMocks.decideBoardSplit.mockImplementationOnce(
      () => new Promise((resolve) => { resolveDecision = resolve; })
    );
    const first = useRoomStore.getState().decideBoardSplit({ ...split() }, "approve", "room-a");
    const second = await useRoomStore.getState().decideBoardSplit(
      { ...split() },
      "reject",
      "room-a"
    );
    expect(second).toBe(false);
    expect(boardApiMocks.decideBoardSplit).toHaveBeenCalledTimes(1);
    resolveDecision({ status: "decided" });
    expect(await first).toBe(true);
  });

  it("does not corrupt the other room cache when switching rooms mid-request", async () => {
    refreshedBoard();
    let resolveDecision!: (value: unknown) => void;
    boardApiMocks.decideBoardSplit.mockImplementationOnce(
      () => new Promise((resolve) => { resolveDecision = resolve; })
    );
    const pending = useRoomStore.getState().decideBoardSplit({ ...split() }, "approve", "room-a");
    useRoomStore.setState({ selectedRoomId: "room-b" });
    resolveDecision({ status: "decided" });
    expect(await pending).toBe(true);
    expect(useRoomStore.getState().boardByRoom["room-a"]?.summary?.revision).toBe("2:bbb");
    expect(useRoomStore.getState().boardByRoom["room-b"]).toBeUndefined();
    expect(useRoomStore.getState().boardActionPending).toBeNull();
  });
});
