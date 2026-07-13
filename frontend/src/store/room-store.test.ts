import { beforeEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  cancelRoomExecutionRun: vi.fn(),
  createConversation: vi.fn(),
  decideRoomExecutionCandidate: vi.fn(),
  describeError: vi.fn((error: unknown) => ({
    code: "request_failed",
    message: error instanceof Error ? error.message : "请求失败",
    retryable: true,
    status: typeof error === "object" && error && "status" in error ? Number(error.status) : 0
  })),
  fetchEvents: vi.fn(),
  fetchRoomOperations: vi.fn(),
  fetchRoomExecutionCandidate: vi.fn(),
  fetchRoomExecutions: vi.fn(),
  fetchRoomMemory: vi.fn(),
  fetchRoomProjection: vi.fn(),
  fetchRooms: vi.fn(),
  isCallerAbort: vi.fn((error: unknown) => error instanceof Error && error.name === "AbortError"),
  sendThreadMessage: vi.fn(),
  rebuildRoomMemoryIndex: vi.fn(),
  recoverRoomRuntime: vi.fn(),
  resolveRoomMemoryCandidate: vi.fn(),
  submitRoomObservationControl: vi.fn(),
  updateRoomExecutionPolicy: vi.fn()
}));

vi.mock("@/lib/api", () => apiMocks);

const { useRoomStore } = await import("./room-store");
const originalStartSync = useRoomStore.getState().startSync;

function operations(
  overall: "healthy" | "attention" | "blocked" = "healthy",
  rebuildOverrides: Record<string, unknown> = {}
) {
  return {
    schema_version: "room_operations_projection/v2" as const,
    generated_at: "2026-07-11T10:00:00Z",
    overall,
    runtime: {
      runner: { state: overall === "blocked" ? "blocked" as const : "healthy" as const, code: null },
      mcp: { state: "healthy" as const, code: null },
      host: { state: "healthy" as const, code: null, active_delivery_count: 0, retained_cleanup_count: 0 },
      memory: {
        enabled: true,
        state: "ready" as const,
        code: "ready",
        consecutive_restart_count: 0,
        next_retry_at: null,
        last_healthy_at: "2026-07-11T10:00:00Z"
      }
    },
    counts: {
      active_delivery: 0,
      retained_cleanup: 0,
      recovery_pending: 0,
      cancel_pending: 0,
      provider_cleanup_pending: 0,
      exhausted: 0
    },
    incident_total: 0,
    incidents: [],
    actions: {
      recover_runtime: {
        available: false,
        method: "POST" as const,
        href: "/api/chat/operator/room-runtime/recover" as const,
        expected_incident_id: null,
        mode: "restart" as const,
        confirmation_required: true
      },
      rebuild_memory_index: {
        available: false,
        pending: false,
        status: null,
        phase: null,
        method: "POST" as const,
        href: "/api/chat/operator/memory-runtime/rebuild" as const,
        expected_incident_id: null,
        confirmation_required: true,
        ...rebuildOverrides
      }
    }
  };
}

function roomList() {
  return {
    schema_version: "room_list_projection/v1",
    rooms: [
      {
        conversation_id: "conv-1",
        title: "Room one",
        status: "settled",
        latest_visible_room_seq: 0,
        latest_visible_item: null,
        participants: [],
        active_turn_count: 0,
        attention_turn_count: 0
      }
    ]
  };
}

function executionList() {
  return {
    schema_version: "room_execution_list_projection/v1" as const,
    projection_only: true as const,
    proof_boundary: "execution_projection_not_room_or_workspace_authority",
    generated_at: "2026-07-12T10:00:00Z",
    conversation_id: "conv-1",
    policy: {
      mode: "manual" as const,
      revision: 2,
      risk_policy_revision: "room_execution_low_risk/v1",
      kill_switch_enabled: false,
      automatic_execution_available: false,
      automatic_execution_code: "execution_policy_manual",
      updated_at: null,
      actions: {
        update: {
          available: true,
          method: "PUT" as const,
          href: "/api/chat/operator/conversations/conv-1/execution-policy",
          expected_revision: 2,
          allowed_modes: ["manual" as const, "consensus" as const]
        }
      }
    },
    candidate_total: 1,
    candidates: [{
      candidate_id: "candidate-1",
      proposal_id: "proposal-1",
      digest: "sha256:candidate",
      revision: 4,
      state: "open",
      consensus_state: "manual_required",
      reason_code: null,
      summary: "Bounded exact patch",
      author: { participant_id: "participant-1", display_name: "Builder" },
      allowed_files: ["a.py"],
      file_count: 1,
      byte_count: 42,
      votes: { required: 1, endorse: 1, object: 0, abstain: 0, pending: 0 },
      run: null,
      gate_summary: { total: 0, pending: 0, running: 0, passed: 0, failed: 0 },
      created_at: "2026-07-12T10:00:00Z",
      updated_at: "2026-07-12T10:00:00Z"
    }],
    page: { limit: 20, cursor: null, has_more: false, next_cursor: null }
  };
}

function executionDetail() {
  const list = executionList();
  return {
    schema_version: "room_execution_candidate_projection/v1" as const,
    projection_only: true as const,
    proof_boundary: "execution_projection_not_room_or_workspace_authority",
    generated_at: list.generated_at,
    conversation_id: "conv-1",
    candidate: {
      ...list.candidates[0],
      base_head: "a".repeat(40),
      unified_diff: "diff --git a/a.py b/a.py\n+x = 1\n",
      files: [{ path: "a.py", change_type: "modify", hunk_count: 1 }],
      review_material_digest: "sha256:review",
      patch_sha256: "sha256:patch",
      snapshot_digest: "sha256:snapshot",
      policy_mode_snapshot: "manual",
      policy_revision_snapshot: 2,
      risk_policy_revision_snapshot: "room_execution_low_risk/v1"
    },
    policy: list.policy,
    votes: [],
    vote_counts: list.candidates[0].votes,
    run: null,
    actions: {
      execute: {
        available: true,
        method: "POST" as const,
        href: "/api/chat/operator/execution-candidates/candidate-1/decision",
        expected_candidate_digest: "sha256:candidate",
        expected_candidate_revision: 4,
        expected_policy_revision: 2
      },
      reject: {
        available: true,
        method: "POST" as const,
        href: "/api/chat/operator/execution-candidates/candidate-1/decision",
        expected_candidate_digest: "sha256:candidate",
        expected_candidate_revision: 4,
        expected_policy_revision: 2
      }
    }
  };
}

function memoryProjection(conversationId = "conv-1") {
  return {
    schema_version: "room_memory_projection/v1" as const,
    projection_only: true as const,
    proof_boundary: "memory_projection_not_room_or_memory_index_authority",
    generated_at: "2026-07-12T10:00:00Z",
    conversation_id: conversationId,
    enabled: true,
    degraded: false,
    runtime: {
      enabled: true,
      degraded: false,
      state: "ready" as const,
      code: "ready",
      consecutive_restart_count: 0,
      next_retry_at: null,
      last_healthy_at: "2026-07-12T10:00:00Z",
      started_at: null,
      updated_at: "2026-07-12T10:00:00Z"
    },
    binding: {
      present: true,
      session_state: "bound",
      attachment_state: "attached",
      revision: 1,
      updated_at: null
    },
    sync: { backlog: 1, pending: 1, processing: 0, failed: 0, conflict: 0, delivered: 4 },
    recent_recalls: [{
      receipt_id: "receipt-1",
      participant_id: "participant-1",
      status: "ok",
      source_refs: [{
        activity_id: "activity-1",
        content_sha256: `sha256:${"b".repeat(64)}`,
        archive_scope: "room"
      }],
      created_at: "2026-07-12T10:00:00Z"
    }],
    pending_candidate_total: 1,
    pending_candidates: [{
      candidate_id: "memory-candidate-1",
      conversation_id: conversationId,
      author_participant_id: "participant-1",
      kind: "user_preference" as const,
      content: "Use concise replies.",
      digest: `sha256:${"a".repeat(64)}`,
      source_activity_ids: ["activity-1"],
      approval_state: "pending" as const,
      publish_state: "not_queued",
      target_scope: "local_user" as const,
      revision: 2,
      reason_code: null,
      created_at: "2026-07-12T10:00:00Z",
      resolved_at: null,
      updated_at: "2026-07-12T10:00:00Z",
      actions: {
        resolve: {
          available: true,
          method: "POST" as const,
          href: "/api/chat/operator/memory-candidates/memory-candidate-1/resolve",
          expected_digest: `sha256:${"a".repeat(64)}`,
          expected_revision: 2,
          allowed_decisions: ["approve" as const, "reject" as const]
        }
      }
    }]
  };
}

function projection(sequence = 0, content = "") {
  return {
    schema_version: "room_chat_projection/v3",
    event_cursor: 17,
    conversation: { id: "conv-1", title: "Room one" },
    status: "settled",
    latest_visible_room_seq: sequence,
    participants: [],
    turns: [],
    timeline_items: sequence
      ? [
          {
            kind: "message",
            room_seq: sequence,
            activity_id: `act-${sequence}`,
            message_id: `msg-${sequence}`,
            actor: { kind: "human", role: "human", display_name: "你" },
            content
          }
        ]
      : [],
    page: {
      has_older: false,
      has_newer: false,
      next_before_room_seq: sequence || null,
      next_after_room_seq: sequence
    }
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useRoomStore.getState().stopSync();
  localStorage.clear();
  sessionStorage.clear();
  useRoomStore.setState({
    rooms: [],
    roomsById: {},
    selectedRoomId: null,
    roomsLoading: false,
    roomsLoaded: false,
    roomsError: null,
    roomCreatePending: false,
    roomCreateError: null,
    drafts: {},
    readCursors: {},
    scrollAnchors: {},
    theme: "dark",
    sidebarOpen: true,
    inspectorOpen: false,
    operations: null,
    operationsLoading: false,
    operationsError: null,
    operationsGeneration: 0,
    operationsConsecutiveFailures: 0,
    executionsByRoom: {},
    memoryByRoom: {},
    executionActionPending: null,
    executionActionError: null,
    memoryActionPending: null,
    memoryActionError: null,
    memoryRebuildPending: false,
    memoryRebuildIncidentId: null,
    memoryRebuildError: null,
    runtimeRecoverPending: false,
    runtimeRecoverError: null,
    inspectorTarget: null,
    startSync: originalStartSync
  });
  apiMocks.fetchRooms.mockResolvedValue(roomList());
  apiMocks.fetchRoomProjection.mockResolvedValue(projection());
  apiMocks.fetchEvents.mockResolvedValue({ events: [], has_more: false });
  apiMocks.fetchRoomOperations.mockResolvedValue(operations());
  apiMocks.fetchRoomExecutions.mockResolvedValue(executionList());
  apiMocks.fetchRoomExecutionCandidate.mockResolvedValue(executionDetail());
  apiMocks.fetchRoomMemory.mockResolvedValue(memoryProjection());
});

describe("Room store", () => {
  it("distinguishes a failed first Room list load and preserves cached rooms on refresh failure", async () => {
    apiMocks.fetchRooms.mockRejectedValueOnce(new Error("Chat API offline"));
    expect(await useRoomStore.getState().loadRooms()).toEqual([]);
    expect(useRoomStore.getState()).toMatchObject({
      roomsLoaded: false,
      rooms: [],
      roomsError: { message: "Chat API offline" }
    });

    apiMocks.fetchRooms.mockResolvedValueOnce(roomList());
    await useRoomStore.getState().loadRooms();
    apiMocks.fetchRooms.mockRejectedValueOnce(new Error("refresh failed"));
    await useRoomStore.getState().loadRooms();
    expect(useRoomStore.getState().rooms).toHaveLength(1);
    expect(useRoomStore.getState().roomsLoaded).toBe(true);
    expect(useRoomStore.getState().roomsError?.message).toBe("refresh failed");
  });

  it("keeps the trusted Room cache when a retired v1 projection is returned", async () => {
    apiMocks.fetchRoomProjection.mockResolvedValueOnce(projection(1, "trusted v2"));
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    apiMocks.fetchRoomProjection.mockResolvedValueOnce({
      ...projection(2, "retired v1"),
      schema_version: "room_chat_projection/v1"
    });

    await useRoomStore.getState().refreshRoom("conv-1", "initial");

    const cache = useRoomStore.getState().roomsById["conv-1"];
    expect(cache.timelineItems.map((item) => item.content)).toEqual(["trusted v2"]);
    expect(cache.syncState).toBe("stale");
    expect(cache.error?.message).toBe("room_chat_projection_schema_invalid");
  });

  it("forwards a stable create request id and retains a retryable create error", async () => {
    apiMocks.createConversation.mockRejectedValueOnce(new Error("ambiguous timeout"));
    expect(await useRoomStore.getState().createRoom("New Room", "create-stable")).toBeNull();
    expect(apiMocks.createConversation).toHaveBeenCalledWith(
      "New Room",
      expect.objectContaining({ clientRequestId: "create-stable" })
    );
    expect(useRoomStore.getState()).toMatchObject({
      roomCreatePending: false,
      roomCreateError: { message: "ambiguous timeout" }
    });
  });

  it("starts the Room sync loop when selecting a room and fetches Operations immediately", async () => {
    const startSync = vi.fn();
    useRoomStore.setState({ startSync });

    await useRoomStore.getState().selectRoom("conv-1");

    expect(startSync).toHaveBeenCalledOnce();
    useRoomStore.setState({ startSync: originalStartSync });
    useRoomStore.getState().startOperationsSync();
    await vi.waitFor(() => expect(apiMocks.fetchRoomOperations).toHaveBeenCalled());
    useRoomStore.getState().stopSync();
  });

  it("starts Operations polling even when bootstrap has no Room", async () => {
    apiMocks.fetchRooms.mockResolvedValueOnce({ schema_version: "room_list_projection/v1", rooms: [] });

    expect(await useRoomStore.getState().bootstrap()).toBeNull();
    await vi.waitFor(() => expect(apiMocks.fetchRoomOperations).toHaveBeenCalled());

    useRoomStore.getState().stopSync();
  });

  it("keeps the last trusted Operations projection when a refresh fails", async () => {
    apiMocks.fetchRoomOperations.mockResolvedValueOnce(operations("attention"));
    await useRoomStore.getState().refreshOperations();
    apiMocks.fetchRoomOperations.mockRejectedValueOnce(new Error("browser offline"));

    await useRoomStore.getState().refreshOperations();

    expect(useRoomStore.getState().operations?.overall).toBe("attention");
    expect(useRoomStore.getState().operationsError?.message).toBe("browser offline");
  });

  it("polls Operations at five seconds only while the visible Inspector is open", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0);
    try {
      useRoomStore.setState({
        operations: operations(),
        inspectorOpen: true,
        operationsConsecutiveFailures: 0
      });
      useRoomStore.getState().startOperationsSync();
      await vi.advanceTimersByTimeAsync(4_999);
      expect(apiMocks.fetchRoomOperations).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      expect(apiMocks.fetchRoomOperations).toHaveBeenCalledTimes(1);

      useRoomStore.setState({ inspectorOpen: false });
      useRoomStore.getState().startOperationsSync();
      await vi.advanceTimersByTimeAsync(14_999);
      expect(apiMocks.fetchRoomOperations).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(1);
      expect(apiMocks.fetchRoomOperations).toHaveBeenCalledTimes(2);
    } finally {
      useRoomStore.getState().stopSync();
      vi.useRealTimers();
    }
  });

  it("loads execution list/detail independently and preserves Room state on execution failure", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    await useRoomStore.getState().refreshExecutions("conv-1");

    expect(useRoomStore.getState().executionsByRoom["conv-1"]).toMatchObject({
      selectedCandidateId: "candidate-1",
      list: { candidate_total: 1 },
      details: { "candidate-1": { candidate: { unified_diff: expect.stringContaining("diff --git") } } },
      error: null
    });
    const roomProjection = useRoomStore.getState().roomsById["conv-1"].projection;
    apiMocks.fetchRoomExecutions.mockRejectedValueOnce(new Error("execution endpoint offline"));

    await useRoomStore.getState().refreshExecutions("conv-1");

    expect(useRoomStore.getState().executionsByRoom["conv-1"].list?.candidate_total).toBe(1);
    expect(useRoomStore.getState().executionsByRoom["conv-1"].error?.message).toBe(
      "execution endpoint offline"
    );
    expect(useRoomStore.getState().roomsById["conv-1"].projection).toBe(roomProjection);
  });

  it("polls execution evidence at five seconds only while the visible Inspector is open", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0);
    try {
      useRoomStore.setState({
        selectedRoomId: "conv-1",
        inspectorOpen: true,
        executionsByRoom: {
          "conv-1": { ...useRoomStore.getState().executionsByRoom["conv-1"],
            list: executionList(),
            details: {},
            selectedCandidateId: null,
            loading: false,
            detailLoading: false,
            requestGeneration: 0,
            consecutiveFailures: 0,
            lastSyncedAt: 0,
            error: null }
        }
      });
      useRoomStore.getState().startExecutionSync();
      await vi.advanceTimersByTimeAsync(4_999);
      expect(apiMocks.fetchRoomExecutions).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      expect(apiMocks.fetchRoomExecutions).toHaveBeenCalledTimes(1);

      useRoomStore.setState({ inspectorOpen: false });
      useRoomStore.getState().startExecutionSync();
      await vi.advanceTimersByTimeAsync(14_999);
      expect(apiMocks.fetchRoomExecutions).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(1);
      expect(apiMocks.fetchRoomExecutions).toHaveBeenCalledTimes(2);
    } finally {
      useRoomStore.getState().stopSync();
      vi.useRealTimers();
    }
  });

  it("reuses execution action id after timeout and refreshes stale guards on 409", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    await useRoomStore.getState().refreshExecutions("conv-1");
    const descriptor = executionDetail().actions.execute;
    apiMocks.decideRoomExecutionCandidate
      .mockRejectedValueOnce({ status: 504, message: "ambiguous timeout" })
      .mockRejectedValueOnce({ status: 409, message: "guard changed" });

    expect(await useRoomStore.getState().decideExecutionCandidate(
      "candidate-1", "execute", descriptor
    )).toBe(false);
    expect(await useRoomStore.getState().decideExecutionCandidate(
      "candidate-1", "execute", descriptor
    )).toBe(false);

    const first = apiMocks.decideRoomExecutionCandidate.mock.calls[0][3].clientActionId;
    const second = apiMocks.decideRoomExecutionCandidate.mock.calls[1][3].clientActionId;
    expect(first).toMatch(/^ui_execution_/);
    expect(second).toBe(first);
    expect(useRoomStore.getState().executionActionPending).toBeNull();
    expect(useRoomStore.getState().executionActionError?.status).toBe(409);
    expect(apiMocks.fetchRoomExecutions.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("keeps Room state while memory refresh fails and scopes evidence by room", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    await useRoomStore.getState().refreshMemory("conv-1");
    const roomProjection = useRoomStore.getState().roomsById["conv-1"].projection;
    expect(useRoomStore.getState().memoryByRoom["conv-1"].projection).toMatchObject({
      conversation_id: "conv-1",
      pending_candidate_total: 1
    });
    apiMocks.fetchRoomMemory.mockRejectedValueOnce(new Error("memory endpoint offline"));

    await useRoomStore.getState().refreshMemory("conv-1");

    expect(useRoomStore.getState().memoryByRoom["conv-1"].projection?.conversation_id)
      .toBe("conv-1");
    expect(useRoomStore.getState().memoryByRoom["conv-1"].error?.message)
      .toBe("memory endpoint offline");
    expect(useRoomStore.getState().roomsById["conv-1"].projection).toBe(roomProjection);

    apiMocks.fetchRoomMemory.mockResolvedValueOnce(memoryProjection("conv-2"));
    await useRoomStore.getState().refreshMemory("conv-2");
    expect(useRoomStore.getState().memoryByRoom["conv-2"].projection?.conversation_id)
      .toBe("conv-2");
    expect(useRoomStore.getState().memoryByRoom["conv-1"].projection?.conversation_id)
      .toBe("conv-1");
  });

  it("polls memory at five seconds only for a visible open Inspector", async () => {
    vi.useFakeTimers();
    vi.spyOn(Math, "random").mockReturnValue(0);
    try {
      useRoomStore.setState({
        selectedRoomId: "conv-1",
        inspectorOpen: true,
        memoryByRoom: {
          "conv-1": {
            projection: memoryProjection(),
            loading: false,
            requestGeneration: 0,
            consecutiveFailures: 0,
            lastSyncedAt: 0,
            error: null
          }
        }
      });
      useRoomStore.getState().startMemorySync();
      await vi.advanceTimersByTimeAsync(4_999);
      expect(apiMocks.fetchRoomMemory).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      expect(apiMocks.fetchRoomMemory).toHaveBeenCalledTimes(1);

      useRoomStore.setState({ inspectorOpen: false });
      useRoomStore.getState().startMemorySync();
      await vi.advanceTimersByTimeAsync(14_999);
      expect(apiMocks.fetchRoomMemory).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(1);
      expect(apiMocks.fetchRoomMemory).toHaveBeenCalledTimes(2);
    } finally {
      useRoomStore.getState().stopSync();
      vi.useRealTimers();
    }
  });

  it("reuses memory action id after timeout and refreshes candidate guards on 409", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    await useRoomStore.getState().refreshMemory("conv-1");
    const descriptor = memoryProjection().pending_candidates[0].actions.resolve;
    apiMocks.resolveRoomMemoryCandidate
      .mockRejectedValueOnce({ status: 504, message: "ambiguous timeout" })
      .mockRejectedValueOnce({ status: 409, message: "guard changed" });

    expect(await useRoomStore.getState().resolveMemoryCandidate(
      "memory-candidate-1", "approve", descriptor
    )).toBe(false);
    expect(await useRoomStore.getState().resolveMemoryCandidate(
      "memory-candidate-1", "approve", descriptor
    )).toBe(false);

    const first = apiMocks.resolveRoomMemoryCandidate.mock.calls[0][3].clientActionId;
    const second = apiMocks.resolveRoomMemoryCandidate.mock.calls[1][3].clientActionId;
    expect(first).toMatch(/^ui_memory_/);
    expect(second).toBe(first);
    expect(useRoomStore.getState().memoryActionPending).toBeNull();
    expect(useRoomStore.getState().memoryActionError?.status).toBe(409);
    expect(apiMocks.fetchRoomMemory.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("reuses a rebuild action id after an ambiguous timeout and refreshes both read models on 409", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    await useRoomStore.getState().refreshMemory("conv-1");
    const roomProjection = useRoomStore.getState().roomsById["conv-1"].projection;
    const descriptor = {
      available: true,
      pending: false,
      status: null,
      phase: null,
      method: "POST" as const,
      href: "/api/chat/operator/memory-runtime/rebuild" as const,
      expected_incident_id: "memory-incident-1",
      confirmation_required: true
    };
    apiMocks.rebuildRoomMemoryIndex
      .mockRejectedValueOnce({ status: 504, message: "ambiguous timeout" })
      .mockRejectedValueOnce({ status: 409, message: "guard changed" });
    const operationsBefore = apiMocks.fetchRoomOperations.mock.calls.length;
    const memoryBefore = apiMocks.fetchRoomMemory.mock.calls.length;

    expect(await useRoomStore.getState().rebuildMemoryIndex(descriptor)).toBe(false);
    expect(await useRoomStore.getState().rebuildMemoryIndex(descriptor)).toBe(false);

    const first = apiMocks.rebuildRoomMemoryIndex.mock.calls[0][1].clientActionId;
    const second = apiMocks.rebuildRoomMemoryIndex.mock.calls[1][1].clientActionId;
    expect(first).toMatch(/^ui_memory_rebuild_/);
    expect(second).toBe(first);
    expect(apiMocks.fetchRoomOperations.mock.calls.length).toBe(operationsBefore + 1);
    expect(apiMocks.fetchRoomMemory.mock.calls.length).toBe(memoryBefore + 1);
    expect(useRoomStore.getState().memoryRebuildError?.status).toBe(409);
    expect(useRoomStore.getState().roomsById["conv-1"].projection).toBe(roomProjection);
    expect(sessionStorage.getItem("xmuse.memory-runtime-rebuild-action/v1")).toBeNull();
  });

  it("uses durable Operations progress to hold and clear rebuild pending state", async () => {
    sessionStorage.setItem("xmuse.memory-runtime-rebuild-action/v1", JSON.stringify({
      incidentId: "memory-incident-1",
      clientActionId: "stable-memory-rebuild"
    }));
    useRoomStore.setState({
      memoryRebuildPending: true,
      memoryRebuildIncidentId: "memory-incident-1"
    });
    apiMocks.fetchRoomOperations.mockResolvedValueOnce(operations("attention", {
      available: false,
      pending: true,
      status: "requested",
      phase: "replaying",
      expected_incident_id: "memory-incident-1"
    }));

    await useRoomStore.getState().refreshOperations();

    expect(useRoomStore.getState()).toMatchObject({
      memoryRebuildPending: true,
      memoryRebuildIncidentId: "memory-incident-1",
      operations: { actions: { rebuild_memory_index: { phase: "replaying" } } }
    });

    apiMocks.fetchRoomOperations.mockResolvedValueOnce(operations("healthy", {
      available: false,
      pending: false,
      status: "applied",
      phase: "complete",
      expected_incident_id: null
    }));
    await useRoomStore.getState().refreshOperations();

    expect(useRoomStore.getState()).toMatchObject({
      memoryRebuildPending: false,
      memoryRebuildIncidentId: null,
      memoryRebuildError: null
    });
    expect(sessionStorage.getItem("xmuse.memory-runtime-rebuild-action/v1")).toBeNull();
  });

  it("does not let a stale Operations read clear an in-flight rebuild write", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    const descriptor = {
      available: true,
      pending: false,
      status: null,
      phase: null,
      method: "POST" as const,
      href: "/api/chat/operator/memory-runtime/rebuild" as const,
      expected_incident_id: "memory-race-guard",
      confirmation_required: true
    };
    let finish!: (value: unknown) => void;
    apiMocks.rebuildRoomMemoryIndex.mockReturnValueOnce(new Promise((resolve) => {
      finish = resolve;
    }));

    const write = useRoomStore.getState().rebuildMemoryIndex(descriptor);
    apiMocks.fetchRoomOperations.mockResolvedValueOnce(operations("attention", {
      available: true,
      pending: false,
      expected_incident_id: "memory-race-guard"
    }));
    await useRoomStore.getState().refreshOperations();
    expect(useRoomStore.getState().memoryRebuildPending).toBe(true);

    apiMocks.fetchRoomOperations.mockResolvedValueOnce(operations("attention", {
      available: false,
      pending: true,
      status: "requested",
      phase: "replaying",
      expected_incident_id: "memory-race-guard"
    }));
    finish({ status: "requested", reason_code: null });
    expect(await write).toBe(true);
    expect(useRoomStore.getState()).toMatchObject({
      memoryRebuildPending: true,
      memoryRebuildIncidentId: "memory-race-guard"
    });
  });

  it("guards runtime recovery and refreshes global and selected Room state", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    const descriptor = {
      available: true,
      method: "POST" as const,
      href: "/api/chat/operator/room-runtime/recover" as const,
      expected_incident_id: "incident-1",
      mode: "restart" as const,
      confirmation_required: true
    };
    apiMocks.recoverRoomRuntime.mockResolvedValueOnce({ action_id: "recover-1", status: "applied" });
    const roomsBefore = apiMocks.fetchRooms.mock.calls.length;
    const roomBefore = apiMocks.fetchRoomProjection.mock.calls.length;

    expect(await useRoomStore.getState().recoverRuntime(descriptor)).toBe(true);

    expect(apiMocks.recoverRoomRuntime).toHaveBeenCalledWith(descriptor, expect.any(Object));
    expect(apiMocks.fetchRooms.mock.calls.length).toBe(roomsBefore + 1);
    expect(apiMocks.fetchRoomProjection.mock.calls.length).toBe(roomBefore + 1);
    expect(useRoomStore.getState().runtimeRecoverPending).toBe(false);
  });

  it("refreshes trusted Operations and Room state after a recover guard conflict", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    const descriptor = {
      available: true,
      method: "POST" as const,
      href: "/api/chat/operator/room-runtime/recover" as const,
      expected_incident_id: "stale-incident",
      mode: "restart" as const,
      confirmation_required: true
    };
    apiMocks.recoverRoomRuntime.mockRejectedValueOnce({ status: 409, message: "guard changed" });
    const operationsBefore = apiMocks.fetchRoomOperations.mock.calls.length;
    const roomBefore = apiMocks.fetchRoomProjection.mock.calls.length;

    expect(await useRoomStore.getState().recoverRuntime(descriptor)).toBe(false);

    expect(apiMocks.fetchRoomOperations.mock.calls.length).toBe(operationsBefore + 1);
    expect(apiMocks.fetchRoomProjection.mock.calls.length).toBe(roomBefore + 1);
    expect(useRoomStore.getState().runtimeRecoverError?.status).toBe(409);
  });

  it("reuses the durable client action after an ambiguous proxy timeout", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    const descriptor = {
      available: true,
      method: "POST" as const,
      href: "/api/chat/operator/room-runtime/recover" as const,
      expected_incident_id: "incident-timeout",
      mode: "restart" as const,
      confirmation_required: true
    };
    apiMocks.recoverRoomRuntime
      .mockRejectedValueOnce({ status: 504, message: "upstream timed out" })
      .mockResolvedValueOnce({ action_id: "recover-after-timeout", status: "applied" });

    expect(await useRoomStore.getState().recoverRuntime(descriptor)).toBe(false);
    expect(await useRoomStore.getState().recoverRuntime(descriptor)).toBe(true);

    const firstOptions = apiMocks.recoverRoomRuntime.mock.calls[0][1];
    const secondOptions = apiMocks.recoverRoomRuntime.mock.calls[1][1];
    expect(firstOptions.clientActionId).toMatch(/^ui_runtime_recover_/);
    expect(secondOptions.clientActionId).toBe(firstOptions.clientActionId);
    expect(sessionStorage.getItem("xmuse.room-runtime-recover-action/v1")).toBeNull();
  });

  it("keeps a failed optimistic bubble and retries with the same client request id", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    apiMocks.sendThreadMessage.mockRejectedValueOnce(new Error("暂时离线"));

    await useRoomStore.getState().sendMessage("不要重复发送", "request-stable");

    expect(useRoomStore.getState().roomsById["conv-1"].pendingMessages[0]).toMatchObject({
      clientRequestId: "request-stable",
      content: "不要重复发送",
      status: "failed"
    });

    apiMocks.sendThreadMessage.mockResolvedValueOnce({
      client_request_id: "request-stable",
      activity_id: "act-8",
      room_activity_seq: 8,
      message: {
        id: "msg-8",
        content: "不要重复发送",
        created_at: "2026-07-10T12:00:00Z"
      }
    });
    apiMocks.fetchRoomProjection.mockResolvedValueOnce(projection(8, "不要重复发送"));

    await useRoomStore.getState().retryMessage("request-stable");

    expect(apiMocks.sendThreadMessage).toHaveBeenNthCalledWith(
      2,
      "conv-1",
      "不要重复发送",
      expect.objectContaining({ clientRequestId: "request-stable" })
    );
    expect(useRoomStore.getState().roomsById["conv-1"].pendingMessages).toEqual([]);
    expect(useRoomStore.getState().roomsById["conv-1"].timelineItems).toHaveLength(1);
    expect(useRoomStore.getState().roomsById["conv-1"].timelineItems[0].id).toBe("msg-8");
  });

  it("turns a stalled send into a retryable failed bubble after the send deadline", async () => {
    vi.useFakeTimers();
    try {
      await useRoomStore.getState().bootstrap("conv-1");
      useRoomStore.getState().stopSync();
      apiMocks.sendThreadMessage.mockImplementationOnce(
        (_roomId: string, _content: string, options: { signal?: AbortSignal }) =>
          new Promise((_resolve, reject) => {
            options.signal?.addEventListener("abort", () => reject(options.signal?.reason), {
              once: true
            });
          })
      );

      const sending = useRoomStore.getState().sendMessage("超时也要能够重试", "request-timeout");
      await vi.advanceTimersByTimeAsync(24_000);
      await sending;

      expect(useRoomStore.getState().roomsById["conv-1"].pendingMessages[0]).toMatchObject({
        clientRequestId: "request-timeout",
        content: "超时也要能够重试",
        status: "failed",
        error: expect.objectContaining({ message: "发送请求超时，请使用同一请求重试。" })
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("does not let an older request generation overwrite a newer Room page", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();

    let resolveOld!: (value: ReturnType<typeof projection>) => void;
    let resolveNew!: (value: ReturnType<typeof projection>) => void;
    apiMocks.fetchRoomProjection
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveNew = resolve; }));

    const oldRequest = useRoomStore.getState().refreshRoom("conv-1", "initial");
    const newRequest = useRoomStore.getState().refreshRoom("conv-1", "incremental");
    resolveNew(projection(2, "new"));
    await newRequest;
    resolveOld(projection(1, "old"));
    await oldRequest;

    expect(useRoomStore.getState().roomsById["conv-1"].timelineItems.map((item) => item.content)).toEqual(["new"]);
  });

  it("persists drafts per room in session storage and read cursors separately in local storage", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    useRoomStore.getState().setDraft("conv-1", "未发送草稿");
    useRoomStore.getState().markRead("conv-1", 18);

    expect(sessionStorage.getItem("xmuse.room-draft/v1:conv-1")).toBe("未发送草稿");
    const local = JSON.parse(localStorage.getItem("xmuse.room-ui/v1") ?? "{}");
    expect(local.readCursors["conv-1"]).toBe(18);
    expect(local).not.toHaveProperty("drafts");
  });

  it("aligns the initial frontend event cursor to the projection cursor", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    expect(useRoomStore.getState().roomsById["conv-1"].eventCursor).toBe(17);
  });

  it("resets a restored event cursor and replaces post-backup timeline items", async () => {
    apiMocks.fetchRoomProjection.mockResolvedValueOnce(projection(9, "post-backup ghost"));
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    apiMocks.fetchEvents.mockResolvedValueOnce({
      schema_version: "chat_frontend_events/v1",
      conversation_id: "conv-1",
      after_seq: 17,
      latest_seq: 4,
      has_more: false,
      events: []
    });
    apiMocks.fetchRoomProjection.mockResolvedValueOnce({
      ...projection(3, "restored snapshot"),
      event_cursor: 4
    });

    await useRoomStore.getState().catchUpRoom("conv-1");

    expect(apiMocks.fetchEvents).toHaveBeenCalledWith("conv-1", 17, expect.any(Object));
    expect(apiMocks.fetchRoomProjection).toHaveBeenLastCalledWith(
      "conv-1",
      expect.not.objectContaining({ afterRoomSeq: expect.anything() })
    );
    const restored = useRoomStore.getState().roomsById["conv-1"];
    expect(restored.eventCursor).toBe(4);
    expect(restored.timelineItems.map((item) => item.content)).toEqual(["restored snapshot"]);
    expect(restored.timelineItems.map((item) => item.content)).not.toContain("post-backup ghost");
  });

  it("reloads an initial projection when the durable Room sequence moves backward", async () => {
    apiMocks.fetchRoomProjection.mockResolvedValueOnce(projection(12, "newer ghost"));
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    apiMocks.fetchRoomProjection
      .mockResolvedValueOnce({ ...projection(), event_cursor: 17, latest_visible_room_seq: 5 })
      .mockResolvedValueOnce({ ...projection(5, "restored room"), event_cursor: 17 });

    await useRoomStore.getState().refreshRoom("conv-1", "incremental");

    expect(apiMocks.fetchRoomProjection).toHaveBeenNthCalledWith(
      2,
      "conv-1",
      expect.objectContaining({ afterRoomSeq: 12 })
    );
    expect(apiMocks.fetchRoomProjection).toHaveBeenNthCalledWith(
      3,
      "conv-1",
      expect.not.objectContaining({ afterRoomSeq: expect.anything() })
    );
    const restored = useRoomStore.getState().roomsById["conv-1"];
    expect(restored.timelineItems.map((item) => item.content)).toEqual(["restored room"]);
    expect(restored.timelineItems.map((item) => item.content)).not.toContain("newer ghost");
  });

  it("submits a projected single-Agent control and refreshes Room state", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    const descriptor = {
      available: true,
      href: "/api/chat/operator/room-observations/obs-1/retry",
      expected_state: "exhausted" as const,
      expected_attempt_count: 3,
      expected_control_seq: 4
    };
    apiMocks.submitRoomObservationControl.mockResolvedValue({
      action_id: "retry-1",
      status: "succeeded",
      event_cursor: 22
    });
    apiMocks.fetchRoomProjection.mockResolvedValueOnce({ ...projection(), event_cursor: 22 });

    const succeeded = await useRoomStore.getState().controlObservation("obs-1", "retry", descriptor);

    expect(succeeded).toBe(true);
    expect(apiMocks.submitRoomObservationControl).toHaveBeenCalledWith(
      "obs-1",
      "retry",
      descriptor,
      expect.any(Object)
    );
    expect(useRoomStore.getState().roomsById["conv-1"].controlPending).toBeNull();
    expect(useRoomStore.getState().roomsById["conv-1"].eventCursor).toBe(22);
  });

  it("refreshes projection after a 409 guard conflict", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    const descriptor = {
      available: true,
      href: "/api/chat/operator/room-observations/obs-1/cancel",
      expected_state: "active" as const,
      expected_attempt_count: 1,
      expected_control_seq: 0
    };
    apiMocks.submitRoomObservationControl.mockRejectedValue({ status: 409, message: "conflict" });
    apiMocks.fetchRoomProjection.mockResolvedValueOnce(projection());
    const before = apiMocks.fetchRoomProjection.mock.calls.length;

    const succeeded = await useRoomStore.getState().controlObservation("obs-1", "cancel", descriptor);

    expect(succeeded).toBe(false);
    expect(apiMocks.fetchRoomProjection.mock.calls.length).toBe(before + 1);
    expect(useRoomStore.getState().roomsById["conv-1"].controlError?.status).toBe(409);
  });

  it("never evicts a room with a pending send from the eight-room LRU", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    const base = useRoomStore.getState().roomsById["conv-1"];
    const roomsById = Object.fromEntries(
      Array.from({ length: 9 }, (_, index) => {
        const id = `room-${index}`;
        return [
          id,
          {
            ...base,
            projection: base.projection
              ? { ...base.projection, conversation_id: id, conversation: { id, title: id } }
              : null,
            lastAccessedAt: index,
            lastSyncedAt: Date.now(),
            pendingMessages: index === 0
              ? [{ clientRequestId: "pending-0", content: "未完成", createdAt: "now", status: "sending" as const }]
              : []
          }
        ];
      })
    );
    useRoomStore.setState({ roomsById, selectedRoomId: null });

    await useRoomStore.getState().selectRoom("room-8");
    useRoomStore.getState().stopSync();

    expect(useRoomStore.getState().roomsById).toHaveProperty("room-0");
    expect(useRoomStore.getState().roomsById).toHaveProperty("room-8");
    expect(useRoomStore.getState().roomsById).not.toHaveProperty("room-1");
    expect(Object.keys(useRoomStore.getState().roomsById)).toHaveLength(8);
  });

  it("keeps the latest selected room authoritative during rapid cross-room loads", async () => {
    let resolveA!: (value: ReturnType<typeof projection>) => void;
    apiMocks.fetchRoomProjection
      .mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve; }))
      .mockResolvedValueOnce({
        ...projection(2, "Room B"),
        conversation: { id: "room-b", title: "Room B" }
      });

    const selectingA = useRoomStore.getState().selectRoom("room-a");
    await Promise.resolve();
    await useRoomStore.getState().selectRoom("room-b");
    resolveA({ ...projection(1, "Room A"), conversation: { id: "room-a", title: "Room A" } });
    await selectingA;
    useRoomStore.getState().stopSync();

    expect(useRoomStore.getState().selectedRoomId).toBe("room-b");
    expect(useRoomStore.getState().roomsById["room-b"].timelineItems[0].content).toBe("Room B");
  });

  it("prepends older pages without replacing the current timeline", async () => {
    await useRoomStore.getState().bootstrap("conv-1");
    useRoomStore.getState().stopSync();
    const current = useRoomStore.getState().roomsById["conv-1"];
    const newest = {
      id: "msg-3",
      room_seq: 3,
      kind: "message",
      actor: { kind: "human", role: "human", display_name: "你" },
      content: "newest"
    };
    useRoomStore.setState({
      roomsById: {
        "conv-1": {
          ...current,
          timelineItems: [newest],
          projection: current.projection
            ? {
                ...current.projection,
                timeline_items: [newest],
                has_older: true,
                next_before_room_seq: 3,
                next_after_room_seq: 3
              }
            : null
        }
      }
    });
    apiMocks.fetchRoomProjection.mockResolvedValueOnce(projection(1, "older"));

    await useRoomStore.getState().loadOlder("conv-1");

    expect(useRoomStore.getState().roomsById["conv-1"].timelineItems.map((item) => item.content)).toEqual([
      "older",
      "newest"
    ]);
  });
});
