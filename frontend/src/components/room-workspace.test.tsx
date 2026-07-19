import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { normalizeRoomOperationsProjection, normalizeRoomProjection } from "@/lib/room-view";
import {
  useRoomStore,
  type RoomCache,
  type RoomExecutionCache,
  type RoomMemoryCache
} from "@/store/room-store";
import {
  captureTimelineAnchor,
  restoreTimelineAnchor,
  roomAgentStreamAnnouncement,
  RoomWorkspace,
  shouldInitializeTimeline,
  snapTimelineToBottom
} from "./room-workspace";

it("aggregates concurrent Agent stream announcements without dropping peers", () => {
  const names = new Map([
    ["part-a", "Architect"],
    ["part-b", "Reviewer"]
  ]);
  const started = roomAgentStreamAnnouncement(
    new Map(),
    [
      { stream_id: "stream-a", participant_id: "part-a", state: "streaming" },
      { stream_id: "stream-b", participant_id: "part-b", state: "streaming" }
    ],
    names
  );
  expect(started.announcement).toBe("Architect 开始生成；Reviewer 开始生成");

  const finished = roomAgentStreamAnnouncement(started.current, [], names);
  expect(finished.announcement).toBe("Architect 结束生成；Reviewer 结束生成");
});

const originalControl = useRoomStore.getState().controlObservation;
const originalRecover = useRoomStore.getState().recoverRuntime;
const originalLoadRooms = useRoomStore.getState().loadRooms;
const originalRefreshOperations = useRoomStore.getState().refreshOperations;
const originalStartOperationsSync = useRoomStore.getState().startOperationsSync;
const originalRefreshExecutions = useRoomStore.getState().refreshExecutions;
const originalStartExecutionSync = useRoomStore.getState().startExecutionSync;
const originalRefreshMemory = useRoomStore.getState().refreshMemory;
const originalStartMemorySync = useRoomStore.getState().startMemorySync;
const originalResolveMemoryCandidate = useRoomStore.getState().resolveMemoryCandidate;
const originalRebuildMemoryIndex = useRoomStore.getState().rebuildMemoryIndex;
const originalSelectExecutionCandidate = useRoomStore.getState().selectExecutionCandidate;
const originalUpdateExecutionPolicy = useRoomStore.getState().updateExecutionPolicy;
const originalDecideExecutionCandidate = useRoomStore.getState().decideExecutionCandidate;
const originalCancelExecutionRun = useRoomStore.getState().cancelExecutionRun;
const originalCreateRoom = useRoomStore.getState().createRoom;

function operationsMemory(state: "ready" | "degraded" | "rebuilding" = "ready") {
  return {
    enabled: true,
    state,
    code: state === "ready" ? "ready" : `memoryos_${state}`,
    consecutive_restart_count: state === "ready" ? 0 : 2,
    next_retry_at: null,
    last_healthy_at: "2026-07-12T09:59:00Z"
  };
}

function rebuildAction(overrides: Record<string, unknown> = {}) {
  return {
    available: false,
    pending: false,
    status: null,
    phase: null,
    method: "POST",
    href: "/api/chat/operator/memory-runtime/rebuild",
    expected_incident_id: null,
    confirmation_required: true,
    ...overrides
  };
}

function cache(): RoomCache {
  const projection = normalizeRoomProjection(
    {
      schema_version: "room_chat_projection/v3",
      event_cursor: 5,
      conversation: { id: "conv-1", title: "控制审计" },
      status: "attention",
      active_turn_count: 1,
      participants: [
        {
          participant_id: "part-builder",
          role: "builder",
          display_name: "Builder",
          participant_status: "active",
          mention_handle: "@builder"
        }
      ],
      turns: [
        {
          correlation_id: "corr-1",
          status: "attention",
          excluded_stopped_count: 0,
          participants: [
            {
              participant_id: "part-builder",
              role: "builder",
              display_name: "Builder",
              state: "thinking",
              unresolved_count: 1,
              frontier: {
                observation_id: "obs-1",
                status: "claimed",
                control_state: "active",
                attempt_count: 1,
                batch_id: "observation-batch-1",
                phase: "root",
                member_count: 1,
                member_activity_refs: [{ activity_id: "act-1", room_seq: 1 }],
                context_only_tail: false,
                coverage: {
                  mode: "batch",
                  cutoff_room_seq: 1,
                  included_member_count: 1,
                  omitted_member_count: 0
                },
                control_seq: 0,
                actions: {
                  cancel: {
                    available: true,
                    href: "/api/chat/operator/room-observations/obs-1/cancel",
                    expected_state: "active",
                    expected_attempt_count: 1,
                    expected_control_seq: 0
                  },
                  retry: {
                    available: false,
                    href: "/api/chat/operator/room-observations/obs-1/retry",
                    expected_state: "active",
                    expected_attempt_count: 1,
                    expected_control_seq: 0
                  }
                }
              }
            },
            {
              participant_id: "part-reviewer",
              role: "reviewer",
              display_name: "Reviewer",
              state: "settled",
              unresolved_count: 0
            }
          ]
        }
      ],
      timeline_items: [],
      page: { has_older: false, has_newer: false }
    },
    "conv-1"
  );
  return {
    projection,
    timelineItems: [],
    pendingMessages: [],
    requestGeneration: 1,
    loading: false,
    loadingOlder: false,
    eventCursor: 5,
    syncState: "synced",
    consecutiveFailures: 0,
    lastSyncedAt: Date.now(),
    lastAccessedAt: Date.now(),
    error: null,
    controlPending: null,
    controlError: null,
    agentStreams: [],
    agentStreamAvailable: true,
    agentStreamEpoch: null,
    agentStreamSeq: 0,
    agentStreamGeneration: 0
  };
}

function executionCache(): RoomExecutionCache {
  const gateProfile = {
    schema_version: "room_execution_gate_profile/v1" as const,
    profile_id: "xmuse-monorepo/v2" as const,
    revision: 2,
    gate_ids: ["patch_diff_check", "backend_pytest"]
  };
  const configuredGateProfile = {
    ...gateProfile,
    gate_ids: [
      "patch_diff_check",
      "backend_ruff",
      "backend_mypy",
      "backend_pytest",
      "frontend_typecheck",
      "frontend_lint",
      "frontend_vitest",
      "frontend_build"
    ],
    readiness: { state: "ready" as const, ready: true, code: "ready" }
  };
  const policy = {
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
  };
  const summary = {
    candidate_id: "candidate-1",
    proposal_id: "proposal-1",
    digest: "sha256:candidate",
    revision: 4,
    state: "open",
    consensus_state: "manual_required",
    reason_code: null,
    gate_profile: gateProfile,
    summary: "修复批处理边界",
    author: { participant_id: "part-builder", display_name: "Builder" },
    allowed_files: ["src/xmuse_core/chat/room_kernel.py"],
    file_count: 1,
    byte_count: 128,
    votes: { required: 1, endorse: 1, object: 0, abstain: 0, pending: 0 },
    run: null,
    gate_summary: { total: 1, pending: 0, running: 1, passed: 0, failed: 0 },
    created_at: "2026-07-12T10:00:00Z",
    updated_at: "2026-07-12T10:00:00Z"
  };
  const decision = {
    available: true,
    method: "POST" as const,
    href: "/api/chat/operator/execution-candidates/candidate-1/decision",
    expected_candidate_digest: "sha256:candidate",
    expected_candidate_revision: 4,
    expected_policy_revision: 2
  };
  const run = {
    run_id: "run-1",
    state: "verifying",
    revision: 5,
    attempt_number: 1,
    created_at: "2026-07-12T10:01:00Z",
    updated_at: "2026-07-12T10:02:00Z",
    finished_at: null,
    reason_code: null,
    gate_profile: gateProfile,
    gate_summary: summary.gate_summary,
    gates: [{
      gate_id: "backend-tests",
      label: "Backend tests",
      state: "running",
      evidence_digest: null,
      started_at: "2026-07-12T10:02:00Z",
      finished_at: null,
      reason_code: null
    }],
    actions: {
      cancel: {
        available: true,
        method: "POST" as const,
        href: "/api/chat/operator/execution-runs/run-1/cancel",
        expected_run_state: "verifying",
        expected_run_revision: 5
      }
    }
  };
  return {
    list: {
      schema_version: "room_execution_list_projection/v1",
      projection_only: true,
      proof_boundary: "execution_projection_not_room_or_workspace_authority",
      generated_at: "2026-07-12T10:00:00Z",
      conversation_id: "conv-1",
      gate_profile: configuredGateProfile,
      policy,
      candidate_total: 1,
      candidates: [summary],
      page: { limit: 20, cursor: null, has_more: false, next_cursor: null }
    },
    details: {
      "candidate-1": {
        schema_version: "room_execution_candidate_projection/v1",
        projection_only: true,
        proof_boundary: "execution_projection_not_room_or_workspace_authority",
        generated_at: "2026-07-12T10:00:00Z",
        conversation_id: "conv-1",
        gate_profile: configuredGateProfile,
        candidate: {
          ...summary,
          run,
          base_head: "a".repeat(40),
          unified_diff: "diff --git a/room_kernel.py b/room_kernel.py\n+bounded = True\n",
          files: [{ path: "src/xmuse_core/chat/room_kernel.py", change_type: "modify", hunk_count: 1 }],
          review_material_digest: "sha256:review",
          patch_sha256: "sha256:patch",
          snapshot_digest: "sha256:snapshot",
          policy_mode_snapshot: "manual",
          policy_revision_snapshot: 2,
          risk_policy_revision_snapshot: "room_execution_low_risk/v1"
        },
        policy,
        votes: [{
          participant_id: "part-reviewer",
          display_name: "Reviewer",
          status_snapshot: "active",
          assessment: "endorse",
          rationale: "补丁边界完整",
          created_at: "2026-07-12T10:00:00Z"
        }],
        vote_counts: summary.votes,
        run,
        actions: { execute: decision, reject: decision }
      }
    },
    selectedCandidateId: "candidate-1",
    loading: false,
    detailLoading: false,
    requestGeneration: 1,
    consecutiveFailures: 0,
    lastSyncedAt: Date.now(),
    error: null
  };
}

function memoryCache(): RoomMemoryCache {
  return {
    projection: {
      schema_version: "room_memory_projection/v1",
      projection_only: true,
      proof_boundary: "memory_projection_not_room_or_memory_index_authority",
      generated_at: "2026-07-12T10:00:00Z",
      conversation_id: "conv-1",
      enabled: true,
      degraded: false,
      runtime: {
        enabled: true,
        degraded: false,
        state: "ready",
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
      sync: { backlog: 2, pending: 2, processing: 0, failed: 0, conflict: 0, delivered: 4 },
      recent_recalls: [{
        receipt_id: "receipt-1",
        participant_id: "part-builder",
        status: "ok",
        source_refs: [{
          activity_id: "activity-prior-1",
          content_sha256: "sha256:source",
          archive_scope: "room"
        }],
        created_at: "2026-07-12T10:00:00Z"
      }],
      pending_candidate_total: 1,
      pending_candidates: [{
        candidate_id: "memory-candidate-1",
        conversation_id: "conv-1",
        author_participant_id: "part-builder",
        kind: "project_rule",
        content: "所有修复必须先补回归测试。",
        digest: "sha256:candidate",
        source_activity_ids: ["activity-prior-1"],
        approval_state: "pending",
        publish_state: "not_queued",
        target_scope: "project",
        revision: 2,
        reason_code: null,
        created_at: "2026-07-12T10:00:00Z",
        resolved_at: null,
        updated_at: "2026-07-12T10:00:00Z",
        actions: {
          resolve: {
            available: true,
            method: "POST",
            href: "/api/chat/operator/memory-candidates/memory-candidate-1/resolve",
            expected_digest: "sha256:candidate",
            expected_revision: 2,
            allowed_decisions: ["approve", "reject"]
          }
        }
      }]
    },
    loading: false,
    requestGeneration: 1,
    consecutiveFailures: 0,
    lastSyncedAt: Date.now(),
    error: null
  };
}

afterEach(() => {
  act(() => useRoomStore.setState({
    controlObservation: originalControl,
    recoverRuntime: originalRecover,
    loadRooms: originalLoadRooms,
    refreshOperations: originalRefreshOperations,
    startOperationsSync: originalStartOperationsSync,
    refreshExecutions: originalRefreshExecutions,
    startExecutionSync: originalStartExecutionSync,
    refreshMemory: originalRefreshMemory,
    startMemorySync: originalStartMemorySync,
    resolveMemoryCandidate: originalResolveMemoryCandidate,
    rebuildMemoryIndex: originalRebuildMemoryIndex,
    selectExecutionCandidate: originalSelectExecutionCandidate,
    updateExecutionPolicy: originalUpdateExecutionPolicy,
    decideExecutionCandidate: originalDecideExecutionCandidate,
    cancelExecutionRun: originalCancelExecutionRun,
    createRoom: originalCreateRoom,
    operations: null,
    operationsError: null,
    operationsLoading: false,
    runtimeRecoverPending: false,
    runtimeRecoverError: null,
    executionsByRoom: {},
    executionActionPending: null,
    executionActionError: null,
    memoryByRoom: {},
    memoryActionPending: null,
    memoryActionError: null,
    memoryRebuildPending: false,
    memoryRebuildIncidentId: null,
    memoryRebuildError: null,
    dockTab: "room",
    onboardingVersion: 1,
    onboardingCompleted: false,
    onboardingDismissed: false,
    onboardingOpen: false
  }));
});

describe("RoomWorkspace observation controls", () => {
  it("refreshes only the visible dock model on focus and replans timers on visibility changes", () => {
    const loadRooms = vi.fn(async () => []);
    const refreshOperations = vi.fn(async () => undefined);
    const startOperationsSync = vi.fn();
    const refreshMemory = vi.fn(async () => undefined);
    const startMemorySync = vi.fn();
    useRoomStore.setState({
      loadRooms,
      refreshOperations,
      startOperationsSync,
      refreshMemory,
      startMemorySync,
      inspectorOpen: true,
      dockTab: "runtime"
    });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    window.dispatchEvent(new Event("focus"));
    expect(loadRooms).toHaveBeenCalledOnce();
    expect(refreshOperations).toHaveBeenCalledOnce();
    expect(refreshMemory).not.toHaveBeenCalled();
    document.dispatchEvent(new Event("visibilitychange"));
    expect(startOperationsSync).toHaveBeenCalledOnce();
    expect(startMemorySync).toHaveBeenCalledOnce();
  });

  it("shows safe Operations facts, prioritizes the selected Room, and navigates incidents", async () => {
    const user = userEvent.setup();
    const onNavigateRoom = vi.fn();
    const operations = normalizeRoomOperationsProjection({
      schema_version: "room_operations_projection/v2",
      overall: "blocked",
      runtime: {
        runner: { state: "blocked", code: "runner_heartbeat_stale" },
        mcp: { state: "healthy", code: null },
        host: { state: "attention", code: "cleanup_retained", active_delivery_count: 2, retained_cleanup_count: 1 },
        memory: operationsMemory()
      },
      counts: {
        active_delivery: 2,
        retained_cleanup: 1,
        recovery_pending: 1,
        cancel_pending: 0,
        provider_cleanup_pending: 1,
        exhausted: 3
      },
      incident_total: 7,
      incidents: [
        {
          incident_id: "other",
          kind: "observation",
          severity: "attention",
          code: "exhausted",
          title: "其他房间已耗尽",
          detail: "需要人工重试",
          started_at: null,
          conversation_id: "conv-2",
          conversation_title: "其他房间",
          participant_id: null,
          participant_display_name: null,
          observation_id: "obs-2",
          next_action: "open_room"
        },
        {
          incident_id: "current",
          kind: "runtime",
          severity: "blocked",
          code: "runner_heartbeat_stale",
          title: "当前房间运行受阻",
          detail: "Runner 心跳已过期",
          started_at: null,
          conversation_id: "conv-1",
          conversation_title: "控制审计",
          participant_id: null,
          participant_display_name: null,
          observation_id: null,
          next_action: "recover_runtime"
        }
      ],
      actions: {
        recover_runtime: {
          available: true,
          method: "POST",
          href: "/api/chat/operator/room-runtime/recover",
          expected_incident_id: "current",
          mode: "restart",
          confirmation_required: true
        },
        rebuild_memory_index: rebuildAction()
      }
    });
    useRoomStore.setState({
      rooms: [{
        conversation_id: "conv-1",
        title: "控制审计",
        latest_visible_room_seq: 0,
        members: [],
        state: "attention",
        active_turn_count: 1,
        attention_turn_count: 1
      }],
      roomsById: { "conv-1": cache() },
      selectedRoomId: "conv-1",
      sidebarOpen: false,
      inspectorOpen: true,
      dockTab: "runtime",
      operations,
      refreshOperations: vi.fn(async () => undefined),
      startOperationsSync: vi.fn()
    });

    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={onNavigateRoom} />);

    const inspector = screen.getByRole("complementary", { name: "房间检查器" });
    const operationsRegion = within(inspector).getByRole("region", { name: "运行与恢复" });
    expect(operationsRegion).toHaveTextContent("Runner已阻塞 · runner_heartbeat_stale");
    expect(operationsRegion).toHaveTextContent("Host需关注 · cleanup_retained");
    expect(operationsRegion).toHaveTextContent("另有 5 项");
    const incidentTitles = [...operationsRegion.querySelectorAll(".room-operation-incident strong")].map((node) => node.textContent);
    expect(incidentTitles.indexOf("当前房间运行受阻")).toBeLessThan(incidentTitles.indexOf("其他房间已耗尽"));
    await user.click(within(operationsRegion).getByRole("button", { name: "打开房间" }));
    expect(onNavigateRoom).toHaveBeenCalledWith("conv-2");
    expect(useRoomStore.getState().inspectorTarget).toMatchObject({
      roomId: "conv-2",
      observationId: "obs-2",
      incidentId: "other"
    });
    expect(screen.getByRole("button", { name: /收起工作台.*运行时阻塞/ })).toHaveClass("has-alert");
  });

  it("keeps a failed Room title and reuses its create request id until edited", async () => {
    const user = userEvent.setup();
    const ids: string[] = [];
    const createRoom = vi.fn(async (_title: string, requestId?: string) => {
      ids.push(requestId ?? "");
      useRoomStore.setState({
        roomCreatePending: false,
        roomCreateError: { code: "timeout", message: "创建请求超时", retryable: true, status: 0 }
      });
      return null;
    });
    useRoomStore.setState({
      createRoom,
      rooms: [],
      roomsLoaded: true,
      roomsError: null,
      roomCreatePending: false,
      roomCreateError: null,
      sidebarOpen: true,
      selectedRoomId: null
    });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "新建 Room" }));
    const title = screen.getByLabelText("Room 名称");
    await user.type(title, "夜间验收");
    await user.click(screen.getByRole("button", { name: "创建 Room" }));
    expect(title).toHaveValue("夜间验收");
    expect(screen.getByRole("alert")).toHaveTextContent("创建请求超时");
    await user.click(screen.getByRole("button", { name: "创建 Room" }));
    expect(ids[1]).toBe(ids[0]);

    await user.type(title, " v2");
    await user.click(screen.getByRole("button", { name: "创建 Room" }));
    expect(ids[2]).not.toBe(ids[0]);
  });

  it("renders a first-load connection failure instead of an empty Room state", () => {
    useRoomStore.setState({
      rooms: [],
      roomsLoaded: false,
      roomsLoading: false,
      roomsError: { code: "offline", message: "Chat API offline", retryable: true, status: 0 },
      selectedRoomId: null,
      sidebarOpen: false
    });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);
    expect(screen.getByRole("alert")).toHaveTextContent("无法连接 xmuse");
    expect(screen.queryByText("还没有房间")).not.toBeInTheDocument();
  });

  it("keeps Operations next actions scoped to navigation, projected guards, and confirmation", async () => {
    const user = userEvent.setup();
    // Keep this projection fixture authoritative; the runtime sync must not
    // replace it with the empty healthy response from an unavailable API.
    useRoomStore.setState({
      refreshOperations: vi.fn(async () => undefined),
      startOperationsSync: vi.fn()
    });
    const operations = normalizeRoomOperationsProjection({
      schema_version: "room_operations_projection/v2",
      overall: "attention",
      runtime: {
        runner: { state: "healthy", code: null },
        mcp: { state: "healthy", code: null },
        host: { state: "attention", code: "cleanup", active_delivery_count: 0, retained_cleanup_count: 1 },
        memory: operationsMemory()
      },
      counts: { active_delivery: 0, retained_cleanup: 1, recovery_pending: 0, cancel_pending: 0, provider_cleanup_pending: 1, exhausted: 1 },
      incident_total: 3,
      incidents: [
        {
          incident_id: "wait-only", kind: "observation", severity: "attention", code: "cleanup",
          title: "等待清理", detail: "不能执行动作", started_at: null,
          conversation_id: "conv-1", conversation_title: "控制审计", participant_id: "part-builder",
          participant_display_name: "Builder", observation_id: "obs-1", next_action: "wait"
        },
        {
          incident_id: "retry-target", kind: "observation", severity: "attention", code: "exhausted",
          title: "可以重试", detail: "先读取 Room descriptor", started_at: null,
          conversation_id: "conv-1", conversation_title: "控制审计", participant_id: "part-builder",
          participant_display_name: "Builder", observation_id: "obs-1", next_action: "retry_observation"
        },
        {
          incident_id: "repair-target", kind: "host", severity: "blocked", code: "skill_drift",
          title: "需要修复", detail: "修复后恢复", started_at: null,
          conversation_id: null, conversation_title: null, participant_id: null,
          participant_display_name: null, observation_id: null, next_action: "repair_then_recover"
        }
      ],
      actions: {
        recover_runtime: {
          available: true, method: "POST", href: "/api/chat/operator/room-runtime/recover",
          expected_incident_id: "runtime-guard-not-incident-id", mode: "restart", confirmation_required: true
        },
        rebuild_memory_index: rebuildAction()
      }
    });
    useRoomStore.setState({
      rooms: [{ conversation_id: "conv-1", title: "控制审计", latest_visible_room_seq: 0, members: [], state: "attention", active_turn_count: 1, attention_turn_count: 1 }],
      roomsById: { "conv-1": cache() },
      selectedRoomId: "conv-1",
      sidebarOpen: false,
      inspectorOpen: true,
      dockTab: "runtime",
      operations
    });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    expect(screen.getByText("等待系统清理")).toBeVisible();
    expect(screen.getByRole("button", { name: /收起工作台.*运行时需要关注/ })).toHaveClass("has-attention");
    await user.click(screen.getByRole("button", { name: "定位并重试" }));
    await waitFor(() => expect(document.activeElement).toHaveAttribute("data-observation-id", "obs-1"));
    await user.click(screen.getByRole("tab", { name: "Runtime" }));
    await user.click(screen.getByRole("button", { name: "修复后恢复" }));
    expect(screen.getByRole("alertdialog")).toBeVisible();
    expect(useRoomStore.getState().runtimeRecoverPending).toBe(false);
  });

  it("labels optional memory attention without implying host cleanup", () => {
    const operations = normalizeRoomOperationsProjection({
      schema_version: "room_operations_projection/v2",
      overall: "attention",
      runtime: {
        runner: { state: "healthy", code: "ready" },
        mcp: { state: "healthy", code: "ready" },
        host: { state: "attention", code: "room_memory_degraded", active_delivery_count: 0, retained_cleanup_count: 0 },
        memory: operationsMemory("degraded")
      },
      counts: { active_delivery: 0, retained_cleanup: 0, recovery_pending: 0, cancel_pending: 0, provider_cleanup_pending: 0, exhausted: 0 },
      incident_total: 1,
      incidents: [{
        incident_id: "memory-wait", kind: "host", severity: "attention", code: "room_memory_degraded",
        title: "Optional memory index is degraded", detail: "Room delivery remains available", started_at: null,
        conversation_id: null, conversation_title: null, participant_id: null,
        participant_display_name: null, observation_id: null, next_action: "wait"
      }],
      actions: {
        recover_runtime: {
          available: false, method: "POST", href: "/api/chat/operator/room-runtime/recover",
          expected_incident_id: "", mode: "restart", confirmation_required: true
        },
        rebuild_memory_index: rebuildAction()
      }
    });
    useRoomStore.setState({
      rooms: [{ conversation_id: "conv-1", title: "Memory audit", latest_visible_room_seq: 0, members: [], state: "settled", active_turn_count: 0, attention_turn_count: 0 }],
      roomsById: { "conv-1": cache() },
      selectedRoomId: "conv-1",
      sidebarOpen: false,
      inspectorOpen: true,
      dockTab: "runtime",
      operations
    });

    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    expect(screen.getByText("等待 MemoryOS 恢复")).toBeVisible();
    expect(screen.queryByText("等待系统清理")).not.toBeInTheDocument();
  });

  it("renders exact diff, votes, gates and confirms policy, decision, and cancel actions", async () => {
    const user = userEvent.setup();
    const updateExecutionPolicy = vi.fn(async () => true);
    const decideExecutionCandidate = vi.fn(async () => true);
    const cancelExecutionRun = vi.fn(async () => true);
    const selectExecutionCandidate = vi.fn(async () => undefined);
    useRoomStore.setState({
      rooms: [{
        conversation_id: "conv-1",
        title: "控制审计",
        latest_visible_room_seq: 0,
        members: [],
        state: "attention",
        active_turn_count: 1,
        attention_turn_count: 1
      }],
      roomsById: { "conv-1": cache() },
      selectedRoomId: "conv-1",
      sidebarOpen: false,
      inspectorOpen: true,
      executionsByRoom: { "conv-1": executionCache() },
      executionActionPending: null,
      executionActionError: null,
      updateExecutionPolicy,
      decideExecutionCandidate,
      cancelExecutionRun,
      selectExecutionCandidate
    });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    const region = screen.getByRole("region", { name: "执行候选" });
    expect(region).toHaveTextContent("人工确认");
    expect(region).toHaveTextContent("xmuse-monorepo/v2");
    expect(region).toHaveTextContent("已就绪");
    expect(region).toHaveTextContent("xmuse-monorepo/v2 · 2 gates");
    expect(region).toHaveTextContent("启动级共识自动执行未开启");
    expect(within(region).getByLabelText("Exact unified diff")).toHaveTextContent(
      "bounded = True"
    );
    expect(region).toHaveTextContent("Reviewerendorse补丁边界完整");
    expect(region).toHaveTextContent("Backend testsrunning");

    const consensus = within(region).getByRole("button", { name: "共识" });
    await user.click(consensus);
    const policyDialog = screen.getByRole("alertdialog", { name: "开启全体 Agent 共识执行？" });
    expect(policyDialog).toHaveTextContent("启动级 kill-switch");
    await waitFor(() => expect(within(policyDialog).getByRole("button", { name: "返回" })).toHaveFocus());
    await user.click(within(policyDialog).getByRole("button", { name: "确认" }));
    expect(updateExecutionPolicy).toHaveBeenCalledWith(
      "consensus",
      expect.objectContaining({ expected_revision: 2 })
    );
    await waitFor(() => expect(consensus).toHaveFocus());

    const execute = within(region).getByRole("button", { name: "人工执行" });
    await user.click(execute);
    expect(screen.getByRole("alertdialog", { name: "执行这个 exact patch？" })).toHaveTextContent(
      "已展示的 exact diff"
    );
    await user.click(screen.getByRole("button", { name: "确认" }));
    expect(decideExecutionCandidate).toHaveBeenCalledWith(
      "candidate-1",
      "execute",
      expect.objectContaining({ expected_candidate_digest: "sha256:candidate" })
    );

    const cancel = within(region).getByRole("button", { name: "取消执行" });
    await user.click(cancel);
    expect(screen.getByRole("alertdialog", { name: "取消当前执行？" })).toHaveTextContent(
      "promotion 前"
    );
    await user.click(screen.getByRole("button", { name: "确认" }));
    expect(cancelExecutionRun).toHaveBeenCalledWith(
      "run-1",
      expect.objectContaining({ expected_run_revision: 5 })
    );
  });

  it("shows fixed profile readiness and blocks execution when capabilities are unavailable", () => {
    const execution = executionCache();
    execution.list!.gate_profile!.readiness = {
      state: "blocked",
      ready: false,
      code: "execution_frontend_dependencies_unavailable"
    };
    execution.details["candidate-1"].gate_profile = execution.list!.gate_profile;
    useRoomStore.setState({
      roomsById: { "conv-1": cache() },
      selectedRoomId: "conv-1",
      sidebarOpen: false,
      inspectorOpen: true,
      executionsByRoom: { "conv-1": execution },
      executionActionPending: null,
      executionActionError: null
    });

    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    const region = screen.getByRole("region", { name: "执行候选" });
    expect(region).toHaveTextContent("execution_frontend_dependencies_unavailable");
    expect(region).toHaveTextContent("人工与共识执行均保持阻断");
    expect(within(region).getByRole("button", { name: "人工执行" })).toBeDisabled();
    expect(within(region).getByRole("button", { name: "拒绝" })).toBeEnabled();
  });

  it("fails closed when the execution profile projection is missing", () => {
    const execution = executionCache();
    execution.list!.gate_profile = null;
    execution.details["candidate-1"].gate_profile = null;
    useRoomStore.setState({
      roomsById: { "conv-1": cache() },
      selectedRoomId: "conv-1",
      sidebarOpen: false,
      inspectorOpen: true,
      executionsByRoom: { "conv-1": execution },
      executionActionPending: null,
      executionActionError: null
    });

    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    const region = screen.getByRole("region", { name: "执行候选" });
    expect(region).toHaveTextContent("门禁状态不可用");
    expect(region).toHaveTextContent("当前无法证明执行门禁");
    expect(within(region).getByRole("button", { name: "人工执行" })).toBeDisabled();
    expect(within(region).getByRole("button", { name: "拒绝" })).toBeEnabled();
  });

  it("keeps execution actions disabled while pending and reports 409 without corrupting Room", () => {
    const room = cache();
    useRoomStore.setState({
      roomsById: { "conv-1": room },
      selectedRoomId: "conv-1",
      sidebarOpen: false,
      inspectorOpen: true,
      executionsByRoom: { "conv-1": executionCache() },
      executionActionPending: { kind: "execute", targetId: "candidate-1" },
      executionActionError: {
        code: "room_execution_candidate_revision_conflict",
        message: "guard changed",
        retryable: false,
        status: 409
      }
    });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    const region = screen.getByRole("region", { name: "执行候选" });
    expect(within(region).getByRole("button", { name: "人工执行" })).toBeDisabled();
    expect(within(region).getByRole("button", { name: "拒绝" })).toBeDisabled();
    expect(within(region).getByRole("button", { name: "取消执行" })).toBeDisabled();
    expect(within(region).getByRole("alert")).toHaveTextContent("执行状态已变化");
    expect(useRoomStore.getState().roomsById["conv-1"]).toBe(room);
  });

  it("shows source-backed memory and confirms a guarded project rule approval", async () => {
    const user = userEvent.setup();
    const resolveMemoryCandidate = vi.fn(async () => true);
    useRoomStore.setState({
      roomsById: { "conv-1": cache() },
      selectedRoomId: "conv-1",
      sidebarOpen: false,
      inspectorOpen: true,
      memoryByRoom: { "conv-1": memoryCache() },
      memoryActionPending: null,
      memoryActionError: null,
      resolveMemoryCandidate
    });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    const region = screen.getByRole("region", { name: "长期记忆" });
    expect(region).toHaveTextContent("2待同步");
    expect(region).toHaveTextContent("activity-prior-1");
    expect(region).toHaveTextContent("所有修复必须先补回归测试");
    const approve = within(region).getByRole("button", { name: "批准" });
    await user.click(approve);
    const dialog = screen.getByRole("alertdialog", { name: "确认记忆审批" });
    expect(dialog).toHaveTextContent("按其作用域用于后续召回");
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "返回" })).toHaveFocus());
    await user.click(within(dialog).getByRole("button", { name: "确认" }));
    expect(resolveMemoryCandidate).toHaveBeenCalledWith(
      "memory-candidate-1",
      "approve",
      expect.objectContaining({
        expected_digest: "sha256:candidate",
        expected_revision: 2
      })
    );
    await waitFor(() => expect(approve).toHaveFocus());
  });

  it("surfaces full-local capability proof and safe recovery facts", () => {
    const memory = memoryCache();
    memory.projection = {
      ...memory.projection!,
      schema_version: "room_memory_projection/v2",
      profile: "full-local",
      capabilities: { hybrid: true, message_ingest: true, agentic_advisory: true },
      runtime: {
        ...memory.projection!.runtime,
        consecutive_restart_count: 1,
        last_healthy_at: "2026-07-14T18:48:08Z"
      },
      sync: {
        ...memory.projection!.sync,
        backlog: 3,
        messages: { backlog: 2, pending: 1, processing: 0, failed: 0, conflict: 0, delivered: 12 }
      }
    };
    useRoomStore.setState({
      roomsById: { "conv-1": cache() },
      selectedRoomId: "conv-1",
      sidebarOpen: false,
      inspectorOpen: true,
      dockTab: "room",
      memoryByRoom: { "conv-1": memory }
    });

    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    const region = screen.getByRole("region", { name: "长期记忆" });
    expect(region).toHaveTextContent("Full-local");
    expect(region).toHaveTextContent("Hybrid 就绪");
    expect(region).toHaveTextContent("3待同步（档案）");
    expect(region).toHaveTextContent("2消息待同步");
    expect(region).toHaveTextContent("1连续重启");
    expect(region).toHaveTextContent("最近健康");
    expect(region).not.toHaveTextContent("8301");
    expect(region).not.toHaveTextContent("api_key");
  });

  it("keeps memory actions disabled and Room intact after a 409 refresh", () => {
    const room = cache();
    useRoomStore.setState({
      roomsById: { "conv-1": room },
      selectedRoomId: "conv-1",
      sidebarOpen: false,
      inspectorOpen: true,
      memoryByRoom: { "conv-1": memoryCache() },
      memoryActionPending: {
        candidateId: "memory-candidate-1",
        decision: "approve"
      },
      memoryActionError: {
        code: "room_memory_candidate_guard_mismatch",
        message: "guard changed",
        retryable: false,
        status: 409
      }
    });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    const region = screen.getByRole("region", { name: "长期记忆" });
    expect(within(region).getByRole("button", { name: "批准" })).toBeDisabled();
    expect(within(region).getByRole("button", { name: "拒绝" })).toBeDisabled();
    expect(within(region).getByRole("alert")).toHaveTextContent("记忆候选已经变化");
    expect(useRoomStore.getState().roomsById["conv-1"]).toBe(room);
  });

  it("confirms disruptive runtime recovery accessibly and restores trigger focus", async () => {
    const user = userEvent.setup();
    const recoverRuntime = vi.fn(async () => true);
    const operations = normalizeRoomOperationsProjection({
      schema_version: "room_operations_projection/v2",
      overall: "blocked",
      runtime: {
        runner: { state: "blocked", code: "runner_heartbeat_stale" },
        mcp: { state: "healthy", code: null },
        host: { state: "healthy", code: null, active_delivery_count: 1, retained_cleanup_count: 0 },
        memory: operationsMemory()
      },
      counts: { active_delivery: 1, retained_cleanup: 0, recovery_pending: 0, cancel_pending: 0, provider_cleanup_pending: 0, exhausted: 0 },
      incident_total: 1,
      incidents: [{
        incident_id: "recoverable",
        kind: "runtime",
        severity: "blocked",
        code: "runner_heartbeat_stale",
        title: "Runner 无响应",
        detail: "运行时可以恢复",
        started_at: null,
        conversation_id: null,
        conversation_title: null,
        participant_id: null,
        participant_display_name: null,
        observation_id: null,
        next_action: "recover_runtime"
      }],
      actions: {
        recover_runtime: { available: true, method: "POST", href: "/api/chat/operator/room-runtime/recover", expected_incident_id: "recoverable", mode: "restart", confirmation_required: true },
        rebuild_memory_index: rebuildAction()
      }
    });
    useRoomStore.setState({
      roomsById: { "conv-1": cache() },
      selectedRoomId: "conv-1",
      sidebarOpen: false,
      inspectorOpen: true,
      dockTab: "runtime",
      operations,
      recoverRuntime
    });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);
    const trigger = screen.getByRole("button", { name: "恢复 Room Runtime" });

    await user.click(trigger);
    const dialog = screen.getByRole("alertdialog", { name: "确认恢复 Room Runtime？" });
    expect(dialog).toHaveTextContent("中断当前正在进行的 Agent delivery");
    expect(dialog).toHaveTextContent("耐久 observation attempt");
    await waitFor(() => expect(screen.getByRole("button", { name: "返回" })).toHaveFocus());
    await user.click(screen.getByRole("button", { name: "确认中断并恢复" }));
    expect(recoverRuntime).toHaveBeenCalledWith(expect.objectContaining({ expected_incident_id: "recoverable" }));
    await waitFor(() => expect(trigger).toHaveFocus());
  });

  it("confirms a guarded MemoryOS rebuild, traps focus, and shows durable progress", async () => {
    const user = userEvent.setup();
    const rebuildMemoryIndex = vi.fn(async () => true);
    const operations = normalizeRoomOperationsProjection({
      schema_version: "room_operations_projection/v2",
      overall: "attention",
      runtime: {
        runner: { state: "healthy", code: "ready" },
        mcp: { state: "healthy", code: "ready" },
        host: { state: "attention", code: "room_memory_degraded", active_delivery_count: 0, retained_cleanup_count: 0 },
        memory: operationsMemory("degraded")
      },
      counts: { active_delivery: 0, retained_cleanup: 0, recovery_pending: 0, cancel_pending: 0, provider_cleanup_pending: 0, exhausted: 0 },
      incident_total: 1,
      incidents: [{
        incident_id: "memory-rebuildable",
        kind: "memory",
        severity: "attention",
        code: "memoryos_cache_schema_blocked",
        title: "MemoryOS 派生索引需要重建",
        detail: "Room 群聊仍可继续工作",
        started_at: null,
        conversation_id: null,
        conversation_title: null,
        participant_id: null,
        participant_display_name: null,
        observation_id: null,
        next_action: "rebuild_memory_index"
      }],
      actions: {
        recover_runtime: {
          available: false, method: "POST", href: "/api/chat/operator/room-runtime/recover",
          expected_incident_id: null, mode: "restart", confirmation_required: true
        },
        rebuild_memory_index: rebuildAction({
          available: true,
          expected_incident_id: "memory-rebuildable"
        })
      }
    });
    useRoomStore.setState({
      roomsById: { "conv-1": cache() },
      selectedRoomId: "conv-1",
      sidebarOpen: false,
      inspectorOpen: true,
      operations,
      memoryByRoom: { "conv-1": memoryCache() },
      rebuildMemoryIndex
    });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);
    const memory = screen.getByRole("region", { name: "长期记忆" });
    const trigger = within(memory).getByRole("button", { name: "重建 MemoryOS 派生索引" });

    await user.click(trigger);
    const dialog = screen.getByRole("alertdialog", { name: "确认重建 MemoryOS 派生索引？" });
    expect(dialog).toHaveTextContent("只会删除可重建的 MemoryOS 派生缓存");
    expect(dialog).toHaveTextContent("Room 消息、已审批记忆");
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "返回" })).toHaveFocus());
    await user.tab({ shift: true });
    expect(within(dialog).getByRole("button", { name: "确认重建派生索引" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "确认重建派生索引" }));
    expect(rebuildMemoryIndex).toHaveBeenCalledWith(expect.objectContaining({
      expected_incident_id: "memory-rebuildable"
    }));
    await waitFor(() => expect(trigger).toHaveFocus());

    act(() => useRoomStore.setState({
      operations: normalizeRoomOperationsProjection({
        ...operations,
        actions: {
          ...operations.actions,
          rebuild_memory_index: rebuildAction({
            available: false,
            pending: true,
            status: "requested",
            phase: "replaying",
            expected_incident_id: "memory-rebuildable"
          })
        }
      }),
      memoryRebuildPending: true
    }));
    expect(within(memory).getByRole("status")).toHaveTextContent("replaying");
    expect(within(memory).queryByRole("button", { name: "重建 MemoryOS 派生索引" })).not.toBeInTheDocument();
  });

  it("keeps both actions visible, confirms cancel accessibly, and restores trigger focus", async () => {
    const user = userEvent.setup();
    const controlObservation = vi.fn(async () => true);
    useRoomStore.setState({
      rooms: [
        {
          conversation_id: "conv-1",
          title: "控制审计",
          latest_visible_room_seq: 0,
          members: [],
          state: "attention",
          active_turn_count: 1,
          attention_turn_count: 1
        }
      ],
      roomsById: { "conv-1": cache() },
      selectedRoomId: "conv-1",
      roomsLoading: false,
      drafts: {},
      readCursors: {},
      scrollAnchors: {},
      sidebarOpen: false,
      inspectorOpen: false,
      controlObservation
    });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    const cancel = screen.getByRole("button", { name: "取消 Builder 当前处理" });
    const retry = screen.getByRole("button", { name: "重试 Builder 当前 observation" });
    expect(cancel).toBeEnabled();
    expect(retry).toBeDisabled();
    expect(screen.queryByRole("button", { name: "取消 Reviewer 当前处理" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "重试 Reviewer 当前 observation" })).not.toBeInTheDocument();

    await user.click(cancel);
    const dialog = screen.getByRole("alertdialog");
    expect(dialog).toHaveAccessibleName("取消 Builder 的当前处理？");
    await waitFor(() => expect(screen.getByRole("button", { name: "返回" })).toHaveFocus());
    await user.tab();
    expect(screen.getByRole("button", { name: "确认取消当前处理" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "返回" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(screen.getByRole("button", { name: "确认取消当前处理" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await waitFor(() => expect(cancel).toHaveFocus());

    await user.click(cancel);
    await user.click(screen.getByRole("button", { name: "确认取消当前处理" }));
    expect(controlObservation).toHaveBeenCalledWith(
      "obs-1",
      "cancel",
      expect.objectContaining({ expected_control_seq: 0 })
    );
  });

  it("lists every active turn frontier and safe attempt/control details in the inspector", () => {
    const value = cache();
    const latest = value.projection!.turns[0];
    const older = structuredClone(latest);
    older.correlation_id = "corr-older";
    older.root_room_seq = 1;
    const frontier = older.participants[0].frontier!;
    frontier.observation_id = "obs-older";
    frontier.control_seq = 7;
    frontier.manual_retry_budget = 1;
    frontier.attempt_count = 2;
    frontier.phase = "peer";
    frontier.member_count = 2;
    frontier.member_activity_refs = [
      { activity_id: "act-peer-1", room_seq: 7 },
      { activity_id: "act-peer-2", room_seq: 8 }
    ];
    frontier.coverage = {
      mode: "batch",
      cutoff_room_seq: 8,
      included_member_count: 2,
      omitted_member_count: 0
    };
    frontier.current_attempt = {
      attempt_number: 2,
      effective_attempt_limit: 4,
      state: "delivering",
      reason_code: "operator_retry",
      claimed_at: "2026-07-10T10:00:00Z",
      transport_started_at: "2026-07-10T10:00:01Z",
      recovery: {
        state: "fenced",
        reason_code: "room_runner_boot_lost",
        started_at: "2026-07-10T10:00:02Z",
        completed_at: null,
        next_action: "cleanup_pending"
      }
    };
    frontier.actions!.cancel!.href = "/api/chat/operator/room-observations/obs-older/cancel";
    frontier.actions!.retry!.href = "/api/chat/operator/room-observations/obs-older/retry";
    value.projection!.turns = [older, latest];
    value.projection!.active_turn_count = 2;
    useRoomStore.setState({
      rooms: [
        {
          conversation_id: "conv-1",
          title: "控制审计",
          latest_visible_room_seq: 0,
          members: [],
          state: "attention",
          active_turn_count: 2,
          attention_turn_count: 2
        }
      ],
      roomsById: { "conv-1": value },
      selectedRoomId: "conv-1",
      drafts: {},
      readCursors: {},
      scrollAnchors: {},
      sidebarOpen: false,
      inspectorOpen: true,
      controlObservation: vi.fn(async () => true)
    });

    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);
    const inspector = screen.getByRole("complementary", { name: "房间检查器" });
    expect(within(inspector).getByText("进行中轮次 · 2")).toBeInTheDocument();
    expect(within(inspector).getByRole("button", { name: "取消 Builder 在轮次 corr-older 的处理" })).toBeEnabled();
    expect(within(inspector).getByText("2 / 4")).toBeInTheDocument();
    expect(within(inspector).getByText("operator_retry")).toBeInTheDocument();
    expect(within(inspector).getByText("7")).toBeInTheDocument();
    const olderCard = inspector.querySelector<HTMLElement>('[data-observation-id="obs-older"]');
    expect(olderCard).not.toBeNull();
    expect(within(olderCard!).getByText("1")).toBeInTheDocument();
    expect(within(inspector).getByText("已隔离失效运行")).toBeInTheDocument();
    expect(within(inspector).getByText("room_runner_boot_lost")).toBeInTheDocument();
    expect(within(inspector).getByText("等待清理完成")).toBeInTheDocument();
    const batch = within(inspector).getAllByRole("region", { name: "当前 frontier batch" })[0];
    expect(batch).toHaveTextContent("Peer batch");
    expect(batch).toHaveTextContent("Batch 成员2");
    expect(batch).toHaveTextContent("真实 attempts2");
    expect(batch).toHaveTextContent("2/2 · 无省略");
    expect(inspector.textContent).not.toContain("attempt-internal");
  });

  it("labels a retained settled turn as recent rather than actionable", () => {
    const value = cache();
    const turn = value.projection!.turns[0];
    turn.state = "settled";
    turn.participants.forEach((participant) => {
      participant.state = "noop";
      participant.unresolved_count = 0;
      participant.frontier = null;
    });
    value.projection!.active_turn_count = 0;
    useRoomStore.setState({
      rooms: [{
        conversation_id: "conv-1",
        title: "控制审计",
        latest_visible_room_seq: 0,
        members: [],
        state: "settled",
        active_turn_count: 0,
        attention_turn_count: 0
      }],
      roomsById: { "conv-1": value },
      selectedRoomId: "conv-1",
      drafts: {},
      readCursors: {},
      scrollAnchors: {},
      sidebarOpen: false,
      inspectorOpen: true
    });

    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);
    const inspector = screen.getByRole("complementary", { name: "房间检查器" });
    expect(within(inspector).getByText("最近轮次")).toBeInTheDocument();
    expect(within(inspector).queryByText(/可处理轮次|进行中轮次/)).not.toBeInTheDocument();
  });

  it("marks onboarding complete only after the first Room turn settles", async () => {
    const value = cache();
    value.projection!.turns[0].state = "settled";
    value.projection!.active_turn_count = 0;
    useRoomStore.setState({
      rooms: [{
        conversation_id: "conv-1",
        title: "控制审计",
        latest_visible_room_seq: 1,
        members: [],
        state: "settled",
        active_turn_count: 0,
        attention_turn_count: 0
      }],
      roomsById: { "conv-1": value },
      selectedRoomId: "conv-1",
      sidebarOpen: false,
      inspectorOpen: false,
      onboardingCompleted: false,
      onboardingDismissed: false,
      onboardingOpen: false
    });

    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    await waitFor(() => expect(useRoomStore.getState().onboardingCompleted).toBe(true));
    expect(screen.queryByLabelText("首次使用进度")).not.toBeInTheDocument();
  });

  it("retains an earlier response when a later peer observation settles as noop", () => {
    const value = cache();
    const participant = value.projection!.turns[0].participants[0];
    participant.state = "noop";
    participant.response_count = 1;
    participant.unresolved_count = 0;
    participant.frontier = null;
    value.projection!.turns[0].state = "settled";
    value.projection!.active_turn_count = 0;
    useRoomStore.setState({
      roomsById: { "conv-1": value },
      selectedRoomId: "conv-1",
      drafts: {},
      readCursors: {},
      scrollAnchors: {},
      sidebarOpen: false,
      inspectorOpen: false
    });

    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    expect(screen.getByText("已回应 · 后续未跟答")).toBeInTheDocument();
    expect(screen.queryByText("已观察 · 未回应")).not.toBeInTheDocument();
  });

  it("shows honest Skill decision evidence only in the inspector", () => {
    const value = cache();
    const participant = value.projection!.turns[0].participants[0];
    participant.root_skill_decision = {
      skill_id: "evidence-review",
      version: "1.0.0",
      content_sha256: "sha256:1234567890abcdef1234567890abcdef",
      selection_reason: "trigger",
      matched_terms: ["审计", "风险"],
      context_status: "selected"
    };
    participant.frontier!.current_attempt = {
      attempt_number: 1,
      effective_attempt_limit: 3,
      state: "delivering",
      skill_decision: {
        ...participant.root_skill_decision,
        context_status: "submitted",
        context_submitted_at: "2026-07-10T10:00:01Z"
      }
    };
    participant.latest_outcome = {
      outcome_type: "noop",
      skill_decision: {
        skill_id: "implementation-planning",
        version: "1.0.0",
        content_sha256: "sha256:abcdef1234567890",
        selection_reason: "explicit",
        matched_terms: [],
        context_status: "submitted",
        context_submitted_at: "2026-07-10T10:00:02Z"
      }
    };
    useRoomStore.setState({
      rooms: [{
        conversation_id: "conv-1",
        title: "控制审计",
        latest_visible_room_seq: 0,
        members: [],
        state: "attention",
        active_turn_count: 1,
        attention_turn_count: 1
      }],
      roomsById: { "conv-1": value },
      selectedRoomId: "conv-1",
      drafts: {},
      readCursors: {},
      scrollAnchors: {},
      sidebarOpen: false,
      inspectorOpen: true
    });

    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);
    const inspector = screen.getByRole("complementary", { name: "房间检查器" });
    expect(within(inspector).getByRole("region", { name: "Human-root Skill" })).toHaveTextContent("Skill 已选择");
    expect(within(inspector).getByRole("region", { name: "当前 frontier Skill" })).toHaveTextContent("上下文已提交");
    expect(within(inspector).getByRole("region", { name: "最新 outcome Skill" })).toHaveTextContent("implementation-planning");
    expect(within(inspector).getAllByText("命中：审计、风险")).toHaveLength(2);
    expect(screen.getByRole("log", { name: "房间消息" })).not.toHaveTextContent("Skill 已选择");
    expect(document.body.textContent).not.toContain("模型已加载");
  });

  it("exposes bounded durable identifiers in message causal proof", async () => {
    const user = userEvent.setup();
    const value = cache();
    value.timelineItems = [{
      id: "msg-12",
      room_seq: 12,
      kind: "message",
      activity_id: "activity-12",
      message_id: "msg-12",
      correlation_id: "correlation-12",
      causation_id: "activity-11",
      causal_depth: 2,
      actor: {
        participant_id: "part-builder",
        role: "builder",
        display_name: "Builder",
        kind: "agent"
      },
      content: "durable response",
      proof_boundary: "identity_bound_room_outcome"
    }];
    useRoomStore.setState({
      roomsById: { "conv-1": value },
      selectedRoomId: "conv-1",
      drafts: {},
      readCursors: {},
      scrollAnchors: {},
      sidebarOpen: false,
      inspectorOpen: false
    });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    await user.click(screen.getByText("核验因果"));

    const proof = screen.getByText("Room seq").closest("dl");
    expect(proof).toHaveTextContent("12");
    expect(proof).toHaveTextContent("activity-12");
    expect(proof).toHaveTextContent("msg-12");
    expect(proof).toHaveTextContent("correlation-12");
    expect(proof).toHaveTextContent("activity-11");
    expect(proof).toHaveTextContent("Causal depth2");
    expect(proof).toHaveTextContent("identity_bound_room_outcome");
  });

  it("renders resolved reply and handoff labels and jumps by stable message id", async () => {
    const user = userEvent.setup();
    const value = cache();
    value.timelineItems = [
      {
        id: "proposal-parent",
        room_seq: 1,
        kind: "proposal",
        activity_id: "act-parent",
        proposal_id: "proposal-parent",
        actor: {
          kind: "agent",
          participant_id: "part-reviewer",
          role: "reviewer",
          display_name: "Reviewer"
        },
        content: "父提案"
      },
      {
        id: "msg-child",
        room_seq: 2,
        kind: "handoff",
        activity_id: "act-child",
        message_id: "msg-child",
        reply_to_activity_id: "act-parent",
        reply_to_message_id: null,
        reply_target_display_name: "Reviewer",
        handoff_targets: ["Reviewer"],
        target_participant_ids: ["part-reviewer"],
        context_only_tail: true,
        actor: {
          kind: "agent",
          participant_id: "part-builder",
          role: "builder",
          display_name: "Builder"
        },
        content: "请继续核验"
      }
    ];
    useRoomStore.setState({
      roomsById: { "conv-1": value },
      selectedRoomId: "conv-1",
      drafts: {},
      readCursors: {},
      scrollAnchors: {},
      sidebarOpen: false,
      inspectorOpen: false
    });
    render(<RoomWorkspace onCreatedRoom={vi.fn()} onNavigateRoom={vi.fn()} />);

    expect(screen.getByText("转交给 Reviewer")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "回复 Reviewer" }));
    expect(document.querySelector('[data-activity-id="act-parent"]')).toHaveFocus();
  });

  it("restores a stable message anchor after history is prepended", () => {
    const container = document.createElement("div");
    const message = document.createElement("article");
    message.dataset.messageId = "msg-anchor";
    container.append(message);
    Object.defineProperty(container, "getBoundingClientRect", {
      value: () => ({ top: 100 })
    });
    Object.defineProperty(message, "getBoundingClientRect", {
      value: () => ({ top: 120, bottom: 160 })
    });
    Object.defineProperty(message, "offsetTop", { value: 340 });

    const anchor = captureTimelineAnchor(container);
    expect(anchor).toEqual({ messageId: "msg-anchor", offset: 20 });
    restoreTimelineAnchor(container, anchor);
    expect(container.scrollTop).toBe(320);
  });

  it("snaps auto-follow to the actual bottom without inheriting smooth scrolling", () => {
    const container = document.createElement("div");
    container.style.scrollBehavior = "smooth";
    Object.defineProperty(container, "scrollHeight", { value: 960 });

    snapTimelineToBottom(container);

    expect(container.scrollTop).toBe(960);
    expect(container.style.scrollBehavior).toBe("smooth");
  });

  it("restores a timeline anchor only once per room, not after incremental loading", () => {
    expect(shouldInitializeTimeline(null, "conv-1", true)).toBe(false);
    expect(shouldInitializeTimeline(null, "conv-1", false)).toBe(true);
    expect(shouldInitializeTimeline("conv-1", "conv-1", true)).toBe(false);
    expect(shouldInitializeTimeline("conv-1", "conv-1", false)).toBe(false);
    expect(shouldInitializeTimeline("conv-1", "conv-2", false)).toBe(true);
  });
});
