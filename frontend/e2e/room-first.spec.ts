import { expect, test, type Page, type Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const corsHeaders = {
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
  "Access-Control-Allow-Origin": "http://127.0.0.1:3210",
  "Cache-Control": "no-store",
  "Content-Type": "application/json"
};
const longCorrelationId = `corr-older-${"a".repeat(72)}`;

type FixtureTimelineItem = {
  kind: string;
  room_seq: number;
  activity_id: string;
  message_id: string;
  correlation_id: string;
  actor: { kind: string; identity?: string; participant_id?: string; role: string; display_name: string };
  content: string;
  created_at: string;
  reply_to_activity_id?: string;
  reply_to_message_id?: string;
  reply_target_display_name?: string;
  target_participant_ids?: string[];
  handoff_targets?: string[];
  context_only_tail?: boolean;
};

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, headers: corsHeaders, body: JSON.stringify(body) });
}

async function installRoomFixture(
  page: Page,
  options: { memoryRebuildable?: boolean } = {}
) {
  let cancelled = false;
  let executionPolicy: "manual" | "consensus" = "manual";
  let executionPolicyRevision = 2;
  let executionRunState: string | null = null;
  let executionRunRevision = 0;
  let memoryCandidatePending = true;
  let memoryRebuildPending = false;
  let codexGoalStatus: string | null = null;
  let codexActionCount = 0;
  let streamCommitted = false;
  let roomSeq = 2;
  const codexGuard = `sha256:${"a".repeat(64)}`;
  const configuredGateProfile = {
    schema_version: "room_execution_gate_profile/v1",
    profile_id: "xmuse-monorepo/v2",
    revision: 2,
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
    readiness: { state: "ready", ready: true, code: "ready" }
  };
  const messages: FixtureTimelineItem[] = [
    {
      kind: "message",
      room_seq: 1,
      activity_id: "act-1",
      message_id: "msg-1",
      correlation_id: "corr-1",
      actor: { kind: "human", identity: "human", role: "human", display_name: "你" },
      content: "请审视当前方案",
      created_at: "2026-07-10T10:00:00Z"
    },
    {
      kind: "handoff",
      room_seq: 2,
      activity_id: "act-2",
      message_id: "msg-2",
      correlation_id: "corr-1",
      actor: { kind: "agent", identity: "participant:part-builder", participant_id: "part-builder", role: "builder", display_name: "Builder" },
      content: "请 Reviewer 继续核验。",
      created_at: "2026-07-10T10:00:01Z",
      reply_to_activity_id: "act-1",
      reply_to_message_id: "msg-1",
      reply_target_display_name: "你",
      target_participant_ids: ["part-reviewer"],
      handoff_targets: ["Reviewer"],
      context_only_tail: true
    }
  ];

  const frontier = () => ({
    observation_id: "obs-1",
    activity_id: "act-1",
    correlation_id: "corr-1",
    status: "claimed",
    expired: false,
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
    control_state: cancelled ? "cancelled" : "active",
    control_seq: cancelled ? 1 : 0,
    current_attempt_id: cancelled ? null : "attempt-1",
    current_attempt: cancelled ? null : {
      attempt_number: 1,
      effective_attempt_limit: 3,
      state: "delivering",
      skill_decision: {
        skill_id: "evidence-review",
        version: "1.0.0",
        content_sha256: "sha256:1234567890abcdef1234567890abcdef",
        selection_reason: "trigger",
        matched_terms: ["审计", "风险"],
        context_status: "selected"
      }
    },
    actions: {
      cancel: {
        available: !cancelled,
        href: "/api/chat/operator/room-observations/obs-1/cancel",
        expected_state: cancelled ? "cancelled" : "active",
        expected_attempt_count: 1,
        expected_control_seq: cancelled ? 1 : 0
      },
      retry: {
        available: cancelled,
        href: "/api/chat/operator/room-observations/obs-1/retry",
        expected_state: cancelled ? "cancelled" : "active",
        expected_attempt_count: 1,
        expected_control_seq: cancelled ? 1 : 0
      }
    }
  });

  await page.route("http://127.0.0.1:8201/api/chat/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders });
      return;
    }
    if (url.pathname === "/api/chat/room-setup-options") {
      await json(route, {
        schema_version: "room_setup_options/v1",
        default_roster_template_id: "builtin.development",
        roster_templates: [{
          template_id: "builtin.development",
          display_name: "开发协作组",
          description: "架构、实现、审查与风险视角",
          participants: [
            { role_id: "architect", role: "architect", display_name: "Architect", description: "负责边界与方案", collaboration_focus: "系统结构" },
            { role_id: "builder", role: "builder", display_name: "Builder", description: "负责实现", collaboration_focus: "交付" },
            { role_id: "reviewer", role: "reviewer", display_name: "Reviewer", description: "负责核验", collaboration_focus: "质量" },
            { role_id: "critic", role: "critic", display_name: "Critic", description: "负责反例", collaboration_focus: "风险" }
          ]
        }]
      });
      return;
    }
    if (url.pathname === "/api/chat/conversations/conv-1/fixture-stream-commit") {
      if (!streamCommitted) {
        streamCommitted = true;
        roomSeq += 1;
        messages.push({
          kind: "message",
          room_seq: roomSeq,
          activity_id: "act-stream-durable",
          message_id: "msg-stream-durable",
          correlation_id: "corr-1",
          actor: {
            kind: "agent",
            identity: "participant:part-builder",
            participant_id: "part-builder",
            role: "builder",
            display_name: "Builder"
          },
          content: "流式提交后的正式回复",
          created_at: "2026-07-10T10:00:02Z"
        });
      }
      await json(route, { committed: true });
      return;
    }
    if (url.pathname === "/api/chat/conversations/conv-1/codex-agents") {
      const participant = (id: string, name: string) => ({
        participant: { participant_id: id, role: id === "part-builder" ? "builder" : "reviewer", display_name: name, status: "active" },
        native_snapshot: {
          source: "codex_app_server_projection_cache",
          observed_at: "2026-07-10T10:00:00Z",
          available: true,
          value: {
            schema_version: "room_codex_native_snapshot/v1",
            source: "codex_app_server",
            goal: codexGoalStatus ? { objective: "完成原生控制验收", status: codexGoalStatus, token_budget: 100000, tokens_used: 2400, time_used_seconds: 18 } : null,
            settings: { model: "gpt-5.6-terra", effort: "medium" },
            active_turn: false,
            guards: { session: codexGuard, goal: codexGuard, settings: codexGuard, turn: null }
          }
        },
        capabilities: {
          source: "codex_app_server_projection_cache",
          observed_at: "2026-07-10T10:00:00Z",
          available: true,
          value: {
            schema_version: "room_codex_native_capabilities/v1",
            source: "codex_app_server",
            capabilities: ["goal_set", "goal_pause", "goal_resume", "goal_get", "goal_clear", "settings_update", "models_list", "console_turn_start", "turn_steer", "turn_interrupt", "compact_start", "review_start"].map((capability_id) => ({
              capability_id,
              native_source: "fixture/native",
              availability: "available",
              disabled_reason: null,
              session_guard: codexGuard
            })),
            models: [{ id: "gpt-5.6-terra", model: "gpt-5.6-terra", is_default: true, default_effort: "medium", efforts: ["medium", "high", "max"] }]
          },
          actions: ["goal_set", "goal_pause", "goal_resume", "goal_get", "goal_clear", "settings_update", "models_list", "console_turn_start", "turn_steer", "turn_interrupt", "compact_start", "review_start"].map((capability_id) => ({
            capability_id,
            available: capability_id === "goal_set" ? !codexGoalStatus : capability_id === "goal_pause" ? codexGoalStatus === "active" : capability_id === "goal_resume" ? codexGoalStatus === "paused" : true,
            disabled_reason: null,
            method: "POST",
            href: `/api/chat/operator/room-participants/${id}/codex-actions`,
            expected_session_guard: codexGuard,
            expected_goal_guard: codexGuard,
            expected_settings_guard: codexGuard,
            expected_turn_guard: null,
            confirmation_required: capability_id === "goal_set"
          }))
        },
        room_bridge: {
          source: "chat.db:room_codex_bridge",
          observed_at: "2026-07-10T10:00:00Z",
          hold: { state: codexGoalStatus ? "goal_active" : "accepting", hold_revision: codexActionCount, session_guard: codexGuard, goal_guard: codexGuard, settings_guard: codexGuard, active_turn_guard: null, reason_code: null, observed_at: "2026-07-10T10:00:00Z", updated_at: "2026-07-10T10:00:00Z" },
          queue: { unresolved_count: id === "part-builder" ? 1 : 0, active_attempt_count: 0, root_blocking: Boolean(codexGoalStatus && id === "part-builder") },
          actions: codexActionCount ? [{ action_id: "codex-action-1", control_seq: 1, client_action_id: "fixture", capability_id: "goal_set", status: "applied", reason_code: null, requested_at: "2026-07-10T10:00:00Z", completed_at: "2026-07-10T10:00:01Z", updated_at: "2026-07-10T10:00:01Z" }] : []
        },
        history_partial: true,
        omitted_event_count: 2
      });
      await json(route, {
        schema_version: "room_codex_projection/v1",
        conversation_id: "conv-1",
        generated_at: "2026-07-10T10:00:00Z",
        projection_only: true,
        proof_boundary: "projection_not_codex_app_server_or_room_authority",
        participants: [participant("part-builder", "Builder"), participant("part-reviewer", "Reviewer")],
        native_events: { source: "codex_app_server_projection_cache", projection_available: true, reason_code: null, event_seq_domain: "room_codex_projection_cache", items: [{ event_seq: 1, participant_seq: 1, participant_id: "part-builder", observed_at: "2026-07-10T10:00:00Z", kind: "plan_updated", step_count: 2, steps: [{ step: "核验契约", status: "completed" }, { step: "完成验收", status: "in_progress" }] }], latest_event_seq: 1, has_older: false, has_newer: false, next_before_event_seq: null, next_after_event_seq: null }
      });
      return;
    }
    if (url.pathname === "/api/chat/runtime/operations") {
      await json(route, {
        schema_version: "room_operations_projection/v2",
        generated_at: "2026-07-10T10:00:00Z",
        overall: options.memoryRebuildable ? "attention" : "healthy",
        runtime: {
          runner: { state: "healthy", code: null },
          mcp: { state: "healthy", code: null },
          host: {
            state: "healthy",
            code: null,
            active_delivery_count: 2,
            retained_cleanup_count: 0
          },
          memory: {
            enabled: true,
            state: memoryRebuildPending
              ? "rebuilding"
              : options.memoryRebuildable ? "degraded" : "ready",
            code: memoryRebuildPending
              ? "memoryos_rebuild_replaying"
              : options.memoryRebuildable ? "memoryos_cache_schema_blocked" : "ready",
            consecutive_restart_count: options.memoryRebuildable ? 3 : 0,
            next_retry_at: null,
            last_healthy_at: "2026-07-10T09:59:00Z"
          }
        },
        counts: {
          active_delivery: 2,
          retained_cleanup: 0,
          recovery_pending: 0,
          cancel_pending: 0,
          provider_cleanup_pending: 0,
          exhausted: 0
        },
        incident_total: options.memoryRebuildable ? 1 : 0,
        incidents: options.memoryRebuildable ? [{
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
          next_action: memoryRebuildPending ? "wait" : "rebuild_memory_index"
        }] : [],
        actions: {
          recover_runtime: {
            available: false,
            method: "POST",
            href: "/api/chat/operator/room-runtime/recover",
            expected_incident_id: null,
            mode: "restart",
            confirmation_required: true
          },
          rebuild_memory_index: {
            available: Boolean(options.memoryRebuildable && !memoryRebuildPending),
            pending: memoryRebuildPending,
            status: memoryRebuildPending ? "requested" : null,
            phase: memoryRebuildPending ? "replaying" : null,
            method: "POST",
            href: "/api/chat/operator/memory-runtime/rebuild",
            expected_incident_id: options.memoryRebuildable ? "memory-rebuildable" : null,
            confirmation_required: true
          }
        }
      });
      return;
    }
    if (url.pathname === "/api/chat/rooms") {
      await json(route, {
        schema_version: "room_list_projection/v1",
        rooms: [
          {
            conversation_id: "conv-1",
            title: "闭环审计室",
            status: "attention",
            latest_visible_room_seq: roomSeq,
            latest_visible_item: messages.at(-1),
            participants: [
              {
                participant_id: "part-builder",
                role: "builder",
                display_name: "Builder",
                status: "active",
                mention_handle: "@builder"
              }
            ],
            active_turn_count: 2,
            attention_turn_count: 2
          }
        ]
      });
      return;
    }
    if (url.pathname === "/api/chat/conversations/conv-1/executions") {
      await json(route, {
        schema_version: "room_execution_list_projection/v1",
        projection_only: true,
        proof_boundary: "execution_projection_not_room_or_workspace_authority",
        generated_at: "2026-07-10T10:00:00Z",
        conversation_id: "conv-1",
        gate_profile: configuredGateProfile,
        policy: {
          mode: executionPolicy,
          revision: executionPolicyRevision,
          risk_policy_revision: "room_execution_low_risk/v1",
          kill_switch_enabled: false,
          automatic_execution_available: false,
          automatic_execution_code: executionPolicy === "manual"
            ? "execution_policy_manual"
            : "execution_consensus_kill_switch_disabled",
          updated_at: "2026-07-10T10:00:00Z",
          actions: {
            update: {
              available: true,
              method: "PUT",
              href: "/api/chat/operator/conversations/conv-1/execution-policy",
              expected_revision: executionPolicyRevision,
              allowed_modes: ["manual", "consensus"]
            }
          }
        },
        candidate_total: 1,
        candidates: [{
          candidate_id: "candidate-1",
          proposal_id: "proposal-1",
          digest: "sha256:candidate",
          revision: executionRunState ? 5 : 4,
          state: executionRunState ? "authorized" : "open",
          consensus_state: "manual_required",
          reason_code: null,
          summary: "修复批处理边界",
          author: { participant_id: "part-builder", display_name: "Builder" },
          allowed_files: ["src/xmuse_core/chat/room_kernel.py"],
          file_count: 1,
          byte_count: 128,
          votes: { required: 1, endorse: 1, object: 0, abstain: 0, pending: 0 },
          run: executionRunState ? {
            run_id: "run-1",
            state: executionRunState,
            revision: executionRunRevision,
            attempt_number: 1,
            gate_summary: { total: 1, pending: 0, running: 1, passed: 0, failed: 0 }
          } : null,
          gate_summary: executionRunState
            ? { total: 1, pending: 0, running: 1, passed: 0, failed: 0 }
            : { total: 0, pending: 0, running: 0, passed: 0, failed: 0 },
          created_at: "2026-07-10T10:00:00Z",
          updated_at: "2026-07-10T10:00:00Z"
        }],
        page: { limit: 20, cursor: null, has_more: false, next_cursor: null }
      });
      return;
    }
    if (url.pathname === "/api/chat/conversations/conv-1/memory") {
      await json(route, {
        schema_version: "room_memory_projection/v1",
        projection_only: true,
        proof_boundary: "memory_projection_not_room_or_memory_index_authority",
        generated_at: "2026-07-10T10:00:00Z",
        conversation_id: "conv-1",
        enabled: true,
        degraded: Boolean(options.memoryRebuildable),
        runtime: {
          enabled: true,
          degraded: Boolean(options.memoryRebuildable),
          state: memoryRebuildPending ? "rebuilding" : options.memoryRebuildable ? "degraded" : "ready",
          code: memoryRebuildPending ? "memoryos_rebuild_replaying" : options.memoryRebuildable ? "memoryos_cache_schema_blocked" : "ready",
          consecutive_restart_count: options.memoryRebuildable ? 3 : 0,
          next_retry_at: null,
          last_healthy_at: "2026-07-10T09:59:00Z",
          started_at: "2026-07-10T09:00:00Z",
          updated_at: "2026-07-10T10:00:00Z"
        },
        binding: {
          present: true,
          session_state: "bound",
          attachment_state: "attached",
          revision: 1,
          updated_at: "2026-07-10T10:00:00Z"
        },
        sync: {
          backlog: 2,
          pending: 1,
          processing: 1,
          failed: 0,
          conflict: 0,
          delivered: 5
        },
        recent_recalls: [{
          receipt_id: "receipt-1",
          participant_id: "part-builder",
          status: "ok",
          schema_version: "metadata.v3_context",
          latency_ms: 14,
          item_count: 1,
          source_refs: [{
            activity_id: "act-1",
            content_sha256: "sha256:source",
            archive_scope: "room"
          }],
          evidence_sha256: "sha256:evidence",
          created_at: "2026-07-10T10:00:00Z"
        }],
        pending_candidate_total: memoryCandidatePending ? 1 : 0,
        pending_candidates: memoryCandidatePending ? [{
          candidate_id: "memory-candidate-1",
          conversation_id: "conv-1",
          author_participant_id: "part-builder",
          kind: "project_rule",
          content: "所有修复必须先补回归测试。",
          digest: "sha256:memory-candidate",
          source_activity_ids: ["act-1"],
          approval_state: "pending",
          publish_state: "not_queued",
          target_scope: "project",
          revision: 2,
          reason_code: null,
          created_at: "2026-07-10T10:00:00Z",
          resolved_at: null,
          updated_at: "2026-07-10T10:00:00Z",
          actions: {
            resolve: {
              available: true,
              method: "POST",
              href: "/api/chat/operator/memory-candidates/memory-candidate-1/resolve",
              expected_digest: "sha256:memory-candidate",
              expected_revision: 2,
              allowed_decisions: ["approve", "reject"]
            }
          }
        }] : []
      });
      return;
    }
    if (url.pathname === "/api/chat/execution-candidates/candidate-1") {
      const run = executionRunState ? {
        run_id: "run-1",
        state: executionRunState,
        revision: executionRunRevision,
        attempt_number: 1,
        created_at: "2026-07-10T10:01:00Z",
        updated_at: "2026-07-10T10:02:00Z",
        finished_at: null,
        reason_code: null,
        gate_summary: { total: 1, pending: 0, running: 1, passed: 0, failed: 0 },
        gates: [{
          gate_id: "backend-tests",
          label: "Backend tests",
          state: "running",
          evidence_digest: null,
          started_at: "2026-07-10T10:02:00Z",
          finished_at: null,
          reason_code: null
        }],
        actions: {
          cancel: {
            available: executionRunState === "verifying",
            method: "POST",
            href: "/api/chat/operator/execution-runs/run-1/cancel",
            expected_run_state: executionRunState,
            expected_run_revision: executionRunRevision
          }
        }
      } : null;
      const policy = {
        mode: executionPolicy,
        revision: executionPolicyRevision,
        risk_policy_revision: "room_execution_low_risk/v1",
        kill_switch_enabled: false,
        automatic_execution_available: false,
        automatic_execution_code: executionPolicy === "manual"
          ? "execution_policy_manual"
          : "execution_consensus_kill_switch_disabled",
        updated_at: "2026-07-10T10:00:00Z",
        actions: {
          update: {
            available: true,
            method: "PUT",
            href: "/api/chat/operator/conversations/conv-1/execution-policy",
            expected_revision: executionPolicyRevision,
            allowed_modes: ["manual", "consensus"]
          }
        }
      };
      const decision = {
        available: executionRunState === null,
        method: "POST",
        href: "/api/chat/operator/execution-candidates/candidate-1/decision",
        expected_candidate_digest: "sha256:candidate",
        expected_candidate_revision: 4,
        expected_policy_revision: executionPolicyRevision
      };
      await json(route, {
        schema_version: "room_execution_candidate_projection/v1",
        projection_only: true,
        proof_boundary: "execution_projection_not_room_or_workspace_authority",
        generated_at: "2026-07-10T10:00:00Z",
        conversation_id: "conv-1",
        gate_profile: configuredGateProfile,
        candidate: {
          candidate_id: "candidate-1",
          proposal_id: "proposal-1",
          digest: "sha256:candidate",
          revision: executionRunState ? 5 : 4,
          state: executionRunState ? "authorized" : "open",
          consensus_state: "manual_required",
          reason_code: null,
          summary: "修复批处理边界",
          author: { participant_id: "part-builder", display_name: "Builder" },
          allowed_files: ["src/xmuse_core/chat/room_kernel.py"],
          file_count: 1,
          byte_count: 128,
          votes: { required: 1, endorse: 1, object: 0, abstain: 0, pending: 0 },
          run,
          gate_summary: run?.gate_summary ?? { total: 0, pending: 0, running: 0, passed: 0, failed: 0 },
          created_at: "2026-07-10T10:00:00Z",
          updated_at: "2026-07-10T10:00:00Z",
          base_head: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
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
          created_at: "2026-07-10T10:00:00Z"
        }],
        vote_counts: { required: 1, endorse: 1, object: 0, abstain: 0, pending: 0 },
        run,
        actions: { execute: decision, reject: decision }
      });
      return;
    }
    if (url.pathname.includes("/conversations/missing/room-projection")) {
      await json(route, { detail: { code: "room_not_found", message: "room not found" } }, 404);
      return;
    }
    if (url.pathname.includes("/conversations/conv-1/room-projection")) {
      const itemAfter = Number(url.searchParams.get("after_room_seq") ?? 0);
      await json(route, {
        schema_version: "room_chat_projection/v3",
        event_cursor: 10,
        conversation: { id: "conv-1", title: "闭环审计室", created_at: "2026-07-10T09:00:00Z" },
        status: "attention",
        latest_visible_room_seq: roomSeq,
        active_turn_count: 2,
        attention_turn_count: 2,
        additional_active_turn_count: 0,
        participants: [
          {
            participant_id: "part-builder",
            role: "builder",
            display_name: "Builder",
            participant_status: "active",
            status: cancelled ? "cancelled" : "thinking",
            mention_handle: "@builder",
            frontier: frontier()
          }
        ],
        turns: [
          {
            correlation_id: longCorrelationId,
            root_activity_id: "act-older",
            root_room_seq: 0,
            status: "active",
            excluded_stopped_count: 0,
            observation_count: 1,
            attempt_count: 2,
            skill_decision_count: 2,
            participants: [
              {
                participant_id: "part-reviewer",
                role: "reviewer",
                display_name: "Reviewer",
                state: "thinking",
                observation_count: 1,
                unresolved_count: 1,
                frontier: {
                  observation_id: "obs-older",
                  activity_id: "act-older",
                  correlation_id: longCorrelationId,
                  status: "claimed",
                  expired: false,
                  attempt_count: 2,
                  batch_id: "observation-batch-older",
                  phase: "peer",
                  member_count: 2,
                  member_activity_refs: [
                    { activity_id: "act-peer-1", room_seq: 7 },
                    { activity_id: "act-peer-2", room_seq: 8 }
                  ],
                  context_only_tail: false,
                  coverage: {
                    mode: "batch",
                    cutoff_room_seq: 8,
                    included_member_count: 2,
                    omitted_member_count: 0
                  },
                  control_state: "active",
                  control_seq: 5,
                  manual_retry_budget: 1,
                  current_attempt: {
                    attempt_number: 2,
                    effective_attempt_limit: 4,
                    state: "delivering",
                    reason_code: "operator_retry",
                    claimed_at: "2026-07-10T09:55:00Z",
                    transport_started_at: "2026-07-10T09:55:01Z",
                    skill_decision: {
                      skill_id: "evidence-review",
                      version: "1.0.0",
                      content_sha256: "sha256:1234567890abcdef1234567890abcdef",
                      selection_reason: "trigger",
                      matched_terms: ["审计", "风险"],
                      context_status: "submitted",
                      context_submitted_at: "2026-07-10T09:55:02Z"
                    }
                  },
                  actions: {
                    cancel: {
                      available: true,
                      href: "/api/chat/operator/room-observations/obs-older/cancel",
                      expected_state: "active",
                      expected_attempt_count: 2,
                      expected_control_seq: 5
                    },
                    retry: {
                      available: false,
                      href: null,
                      expected_state: "active",
                      expected_attempt_count: 2,
                      expected_control_seq: 5
                    }
                  }
                },
                root_skill_decision: {
                  skill_id: "implementation-planning",
                  version: "1.0.0",
                  content_sha256: "sha256:abcdef1234567890",
                  selection_reason: "explicit",
                  matched_terms: [],
                  context_status: "selected"
                },
                latest_outcome: {
                  outcome_type: "noop",
                  skill_decision: {
                    skill_id: "evidence-review",
                    version: "1.0.0",
                    content_sha256: "sha256:1234567890abcdef1234567890abcdef",
                    selection_reason: "trigger",
                    matched_terms: ["审计", "风险"],
                    context_status: "submitted",
                    context_submitted_at: "2026-07-10T09:55:03Z"
                  }
                }
              }
            ]
          },
          {
            correlation_id: "corr-1",
            root_activity_id: "act-1",
            root_room_seq: 1,
            status: "attention",
            excluded_stopped_count: 0,
            observation_count: 1,
            attempt_count: 1,
            skill_decision_count: 1,
            participants: [
              {
                participant_id: "part-builder",
                role: "builder",
                display_name: "Builder",
                state: cancelled ? "cancelled" : "thinking",
                observation_count: 1,
                unresolved_count: 1,
                frontier: frontier(),
                root_skill_decision: {
                  skill_id: "evidence-review",
                  version: "1.0.0",
                  content_sha256: "sha256:1234567890abcdef1234567890abcdef",
                  selection_reason: "trigger",
                  matched_terms: ["审计", "风险"],
                  context_status: "selected"
                }
              }
            ]
          }
        ],
        timeline_items: messages.filter((message) => message.room_seq > itemAfter),
        page: {
          has_older: false,
          has_newer: false,
          next_before_room_seq: 1,
          next_after_room_seq: roomSeq
        }
      });
      return;
    }
    if (url.pathname.endsWith("/events")) {
      const afterSeq = Number(url.searchParams.get("after_seq") ?? 0);
      const streamEvents = streamCommitted && afterSeq < 11
        ? [{
            sequence: 11,
            event_type: "projection.changed",
            payload: {
              kind: "room_projection_changed",
              change: "outcome.completed",
              activity_id: "act-stream-durable",
              room_seq: 3,
              message_id: "msg-stream-durable"
            }
          }]
        : [];
      await json(route, {
        schema_version: "chat_frontend_events/v1",
        conversation_id: "conv-1",
        after_seq: afterSeq,
        latest_seq: streamCommitted ? 11 : 10,
        has_more: false,
        events: streamEvents
      });
      return;
    }
    await json(route, { detail: { code: "fixture_route_missing", message: url.pathname } }, 404);
  });

  await page.route("**/api/rooms/conv-1/messages", async (route) => {
    const payload = route.request().postDataJSON() as { message: string; client_request_id: string };
    roomSeq += 1;
    const message = {
      kind: "message",
      room_seq: roomSeq,
      activity_id: `act-${roomSeq}`,
      message_id: `msg-${roomSeq}`,
      correlation_id: `corr-${roomSeq}`,
      actor: { kind: "human", identity: "human", role: "human", display_name: "你" },
      content: payload.message,
      created_at: "2026-07-10T10:01:00Z"
    };
    messages.push(message);
    await json(route, {
      client_request_id: payload.client_request_id,
      activity_id: message.activity_id,
      room_activity_seq: roomSeq,
      message: {
        id: message.message_id,
        content: message.content,
        created_at: message.created_at,
        conversation_id: "conv-1"
      }
    });
  });

  await page.route("**/api/room-observations/obs-1/cancel", async (route) => {
    cancelled = true;
    await json(route, { action_id: "cancel-1", status: "succeeded", event_cursor: 11 });
  });
  await page.route("**/api/room-participants/*/codex-actions", async (route) => {
    const payload = route.request().postDataJSON() as { capability_id: string; confirmed_pending_observations: boolean };
    if (payload.capability_id === "goal_set") {
      expect(payload.confirmed_pending_observations).toBe(true);
      codexGoalStatus = "active";
    } else if (payload.capability_id === "goal_pause") codexGoalStatus = "paused";
    else if (payload.capability_id === "goal_resume") codexGoalStatus = "active";
    else if (payload.capability_id === "goal_clear") codexGoalStatus = null;
    codexActionCount += 1;
    await json(route, { action_id: `codex-action-${codexActionCount}`, client_action_id: "fixture", status: "requested", participant_id: "part-builder", conversation_id: "conv-1", control_seq: codexActionCount, capability_id: payload.capability_id, reason_code: null, updated_at: "2026-07-10T10:00:01Z", proof_boundary: "operator_action_receipt_not_codex_or_room_authority" });
  });
  await page.route("**/api/room-observations/obs-1/retry", async (route) => {
    cancelled = false;
    await json(route, { action_id: "retry-1", status: "succeeded", event_cursor: 12 });
  });
  await page.route("**/api/room-execution-policy/conv-1", async (route) => {
    const payload = route.request().postDataJSON() as { mode: "manual" | "consensus" };
    executionPolicy = payload.mode;
    executionPolicyRevision += 1;
    await json(route, { action_id: "policy-1", status: "applied" });
  });
  await page.route("**/api/room-execution-candidates/candidate-1/decision", async (route) => {
    const payload = route.request().postDataJSON() as { decision: "execute" | "reject" };
    if (payload.decision === "execute") {
      executionRunState = "verifying";
      executionRunRevision = 1;
    }
    await json(route, {
      action_id: "decision-1",
      status: "applied",
      candidate_id: "candidate-1",
      run_id: payload.decision === "execute" ? "run-1" : null
    });
  });
  await page.route("**/api/room-execution-runs/run-1/cancel", async (route) => {
    executionRunState = "cancel_requested";
    executionRunRevision += 1;
    await json(route, { action_id: "cancel-run-1", status: "applied", run_id: "run-1" });
  });
  await page.route("**/api/room-memory-candidates/memory-candidate-1/resolve", async (route) => {
    const payload = route.request().postDataJSON() as {
      decision: "approve" | "reject";
      expected_digest: string;
      expected_revision: number;
    };
    expect(payload).toMatchObject({
      decision: "approve",
      expected_digest: "sha256:memory-candidate",
      expected_revision: 2
    });
    memoryCandidatePending = false;
    await json(route, {
      action_id: "memory-action-1",
      status: "applied",
      candidate_id: "memory-candidate-1",
      approval_state: "approved",
      revision: 3
    });
  });
  await page.route("**/api/room-memory/rebuild", async (route) => {
    const payload = route.request().postDataJSON() as Record<string, unknown>;
    expect(Object.keys(payload).sort()).toEqual(["client_action_id", "expected_incident_id"]);
    expect(payload.expected_incident_id).toBe("memory-rebuildable");
    memoryRebuildPending = true;
    await json(route, {
      schema_version: "room_memory_rebuild_action/v1",
      action_id: "memory-rebuild-action-1",
      client_action_id: payload.client_action_id,
      status: "requested",
      phase: "replaying",
      reason_code: null,
      before: { state: "degraded", code: "memoryos_cache_schema_blocked" },
      after: { state: null, code: null },
      result: null,
      requested_at: "2026-07-10T10:00:00Z",
      applied_at: null,
      proof_boundary: "operator_action_receipt_not_room_or_memory_index_authority"
    });
  });
}

test("deep link, message send, and single-Agent control remain usable", async ({ page }) => {
  await installRoomFixture(page);
  await page.goto("/rooms/conv-1");
  await expect(page.getByRole("heading", { name: "闭环审计室" })).toBeVisible();
  const messageLog = page.getByRole("log", { name: "房间消息" });
  await expect(messageLog.getByText("请审视当前方案")).toBeVisible();
  await expect(messageLog.getByRole("button", { name: "回复 你" })).toBeVisible();
  await expect(messageLog.getByText("转交给 Reviewer")).toBeVisible();
  await messageLog.getByRole("button", { name: "回复 你" }).click();
  await expect(messageLog.locator('[data-message-id="msg-1"]')).toBeFocused();
  await expect(messageLog).toBeVisible();

  await page.getByRole("button", { name: "切换主题" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await page.locator(".room-sidebar-slot").evaluate((node) => getComputedStyle(node).transitionDuration)).toBe("0s");

  await page.getByLabel("发送消息").fill("新增消息");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByText("新增消息")).toBeVisible();

  await page.locator(".room-turn-status details").first().getByText("控制").click();
  await page.getByRole("button", { name: "取消 Builder 当前处理" }).click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("其他 Agent 和后续房间活动不受影响");
  await expect(dialog.getByRole("button", { name: "返回" })).toBeFocused();
  await dialog.getByRole("button", { name: "确认取消当前处理" }).click();
  const retry = page.getByRole("button", { name: "重试 Builder 当前 observation" });
  await expect(retry).toBeEnabled();
  await retry.click();
  await expect(page.getByRole("button", { name: "取消 Builder 当前处理" })).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("Room Agent preview streams snapshots and yields to one durable message", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Streaming transition is exercised once");
  await installRoomFixture(page);
  await page.addInitScript(() => {
    type Listener = (event: MessageEvent<string>) => void;
    class FixtureEventSource {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      readonly url: string;
      readonly withCredentials = false;
      readyState = FixtureEventSource.OPEN;
      onerror: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent<string>) => void) | null = null;
      onopen: ((event: Event) => void) | null = null;
      private listeners = new Map<string, Listener[]>();
      private timers: number[] = [];

      constructor(url: string | URL) {
        this.url = String(url);
        const snapshot = (streamSeq: number, state: string, content: string) => ({
          schema_version: "room_agent_stream_projection/v1",
          proof_boundary: "provider_preview_not_room_or_codex_authority",
          projection_available: true,
          conversation_id: "conv-1",
          epoch: "fixture-epoch",
          stream_seq: streamSeq,
          streams: [{
            stream_id: "stream-fixture",
            participant_id: "part-builder",
            observation_id: "obs-1",
            state,
            content,
            truncated: false,
            started_at: "2026-07-10T10:00:01Z",
            updated_at: `2026-07-10T10:00:0${streamSeq}Z`,
            resolution: state === "resolved" ? {
              outcome_type: "respond",
              produced_activity_id: "act-stream-durable"
            } : null
          }]
        });
        const schedule = (delay: number, callback: () => void) => {
          this.timers.push(window.setTimeout(callback, delay));
        };
        schedule(700, () => this.emit("projection", snapshot(1, "streaming", "第一段 ")));
        schedule(1400, () => this.emit("projection", snapshot(2, "streaming", "第一段 第二段 ")));
        schedule(2100, () => this.emit("projection", snapshot(3, "streaming", "第一段 第二段 第三段 ")));
        schedule(2800, () => this.emit("projection", snapshot(4, "committing", "第一段 第二段 第三段 ")));
        schedule(3500, () => {
          void fetch("http://127.0.0.1:8201/api/chat/conversations/conv-1/fixture-stream-commit")
            .then(() => this.emit("projection", snapshot(5, "resolved", "第一段 第二段 第三段 ")));
        });
      }

      addEventListener(type: string, listener: EventListenerOrEventListenerObject | null) {
        if (typeof listener !== "function") return;
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener as Listener]);
      }

      removeEventListener() {}

      dispatchEvent() { return true; }

      close() {
        this.readyState = FixtureEventSource.CLOSED;
        this.timers.forEach((timer) => window.clearTimeout(timer));
      }

      private emit(type: string, payload: object) {
        if (this.readyState === FixtureEventSource.CLOSED) return;
        const event = new MessageEvent<string>(type, { data: JSON.stringify(payload) });
        this.listeners.get(type)?.forEach((listener) => listener(event));
      }
    }
    (window as unknown as { EventSource: typeof EventSource }).EventSource = (
      FixtureEventSource as unknown as typeof EventSource
    );
  });

  await page.goto("/rooms/conv-1");
  const preview = page.getByLabel("Agent 正在生成");
  const previewBody = preview.locator(".room-stream-body");
  await expect(previewBody).toHaveText("第一段");
  await expect(previewBody).toHaveText("第一段 第二段");
  await expect(previewBody).toHaveText("第一段 第二段 第三段");
  await expect(preview).toContainText("正在提交");
  await expect(preview).toHaveCount(0);
  const durable = page.getByRole("log", { name: "房间消息" }).getByText(
    "流式提交后的正式回复"
  );
  await expect(durable).toHaveCount(1);
});

test("the root route enters the most recent Room", async ({ page }) => {
  await installRoomFixture(page);
  await page.goto("/");
  await expect(page).toHaveURL(/\/rooms\/conv-1$/);
  await expect(page.getByRole("heading", { name: "闭环审计室" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("an invalid Room deep link is explicit and never falls back silently", async ({ page }) => {
  await installRoomFixture(page);
  await page.goto("/rooms/missing");
  await expect(page.locator("section.room-fatal-empty[role=alert]")).toContainText("找不到这个房间");
  await expect(page).toHaveURL(/\/rooms\/missing$/);
});

test("all active turn frontiers remain discoverable in the inspector", async ({ page }, testInfo) => {
  test.skip(
    !["desktop", "desktop-min"].includes(testInfo.project.name),
    "Desktop Inspector detail is covered at both release widths"
  );
  await installRoomFixture(page);
  await page.goto("/rooms/conv-1");
  await page.getByRole("button", { name: /工作台/ }).click();
  const inspector = page.getByRole("complementary", { name: "房间检查器" });
  await inspector.getByRole("tab", { name: "Runtime" }).click();
  await expect(inspector.getByRole("region", { name: "运行与恢复" })).toContainText("Runner正常");
  await inspector.getByRole("tab", { name: "Room" }).click();
  await expect(inspector).toContainText("进行中轮次 · 2");
  await expect(inspector.getByRole("button", { name: `取消 Reviewer 在轮次 ${longCorrelationId} 的处理` })).toBeEnabled();
  await expect(inspector).toContainText("2 / 4");
  await expect(inspector).toContainText("operator_retry");
  await expect(inspector).toContainText("控制序号5");
  await expect(inspector.getByRole("region", { name: "当前 frontier batch" }).first()).toContainText("Batch 成员2");
  await expect(inspector.getByRole("region", { name: "当前 frontier batch" }).first()).toContainText("真实 attempts2");
  await expect(inspector).toContainText("Observations 1 · Attempts 2 · Skill decisions 2");
  await expect(inspector.getByRole("region", { name: "Human-root Skill" }).first()).toContainText("Skill 已选择");
  await expect(inspector.getByRole("region", { name: "当前 frontier Skill" }).first()).toContainText("上下文已提交");
  await expect(inspector.getByRole("region", { name: "最新 outcome Skill" })).toContainText("evidence-review");
  await expect(page.getByRole("log", { name: "房间消息" })).not.toContainText("Skill 已选择");
  expect(await inspector.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
});

test("Agent Console renders discovered native capabilities and guarded Goal state", async ({ page }) => {
  await installRoomFixture(page);
  await page.goto("/rooms/conv-1");
  await page.getByRole("button", { name: /工作台/ }).click();
  const inspector = page.locator(".room-inspector");
  await inspector.getByRole("tab", { name: "Agent" }).click();
  const console = inspector.getByRole("region", { name: "Codex Agent Console" });
  await expect(console.getByRole("tab", { name: "Builder" })).toHaveAttribute("aria-selected", "true");
  await expect(console).toContainText("Codex 原生状态");
  await expect(console).toContainText("xmuse Room Bridge");
  await console.getByRole("button", { name: /计划更新/ }).click();
  const detail = page.getByRole("dialog", { name: "Codex 原生事件详情" });
  await expect(detail).toContainText("核验契约");
  await detail.getByRole("button", { name: "关闭" }).click();

  const input = console.getByLabel("给 Builder 的 Console 输入");
  await input.fill("/goal 完成原生控制验收");
  await input.press("Enter");
  const confirmation = page.getByRole("alertdialog", { name: "启动新的 Codex Goal？" });
  await expect(confirmation).toContainText("待处理的 Room observation");
  await confirmation.getByRole("button", { name: "确认启动 Goal" }).click();
  await expect(console).toContainText("active");
  await expect(console).toContainText("其他 Agent 可完成根回应；后续同轮跟进正在等待此 Agent");

  await console.getByRole("tab", { name: "Reviewer" }).click();
  await expect(console.getByRole("heading", { name: "Reviewer" })).toBeVisible();
  await expect(console.getByLabel("Codex 模型")).toHaveValue("gpt-5.6-terra");
  await console.getByLabel("Console 默认模式").selectOption("plan");
  await expect(console).toContainText("Plan（仅本机偏好）");
  expect(await inspector.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
});

test("exact-patch Inspector stays guarded and usable across release viewports", async ({ page }) => {
  await installRoomFixture(page);
  await page.goto("/rooms/conv-1");
  await page.getByRole("button", { name: /工作台/ }).click();
  const inspector = page.locator(".room-inspector");
  await inspector.getByRole("tab", { name: "Room" }).click();
  const execution = inspector.getByRole("region", { name: "执行候选" });
  await expect(execution).toContainText("人工确认");
  await expect(execution).toContainText("xmuse-monorepo/v2");
  await expect(execution).toContainText("已就绪");
  await expect(execution).toContainText("启动级共识自动执行未开启");
  await expect(execution.getByLabel("Exact unified diff")).toContainText("bounded = True");
  await expect(execution).toContainText("Reviewer");
  await expect(execution).toContainText("endorse");
  expect(await inspector.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);

  const consensus = execution.getByRole("button", { name: "共识" });
  await consensus.click();
  let dialog = page.getByRole("alertdialog", { name: "开启全体 Agent 共识执行？" });
  await expect(dialog.getByRole("button", { name: "返回" })).toBeFocused();
  await dialog.getByRole("button", { name: "确认" }).click();
  await expect(execution).toContainText("全体共识");

  const reject = execution.getByRole("button", { name: "拒绝" });
  await reject.click();
  dialog = page.getByRole("alertdialog", { name: "拒绝这个候选？" });
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(reject).toBeFocused();

  await execution.getByRole("button", { name: "人工执行" }).click();
  dialog = page.getByRole("alertdialog", { name: "执行这个 exact patch？" });
  await expect(dialog).toContainText("已展示的 exact diff");
  await dialog.getByRole("button", { name: "确认" }).click();
  await expect(execution.getByRole("region", { name: "执行门禁" })).toContainText(
    "Backend tests"
  );

  await execution.getByRole("button", { name: "取消执行" }).click();
  dialog = page.getByRole("alertdialog", { name: "取消当前执行？" });
  await dialog.getByRole("button", { name: "确认" }).click();
  await expect(execution).toContainText("cancel_requested");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("source-backed Memory Inspector remains guarded across release viewports", async ({ page }) => {
  await installRoomFixture(page);
  await page.goto("/rooms/conv-1");
  await page.getByRole("button", { name: /工作台/ }).click();
  const inspector = page.locator(".room-inspector");
  await inspector.getByRole("tab", { name: "Room" }).click();
  const memory = inspector.getByRole("region", { name: "长期记忆" });
  await memory.scrollIntoViewIfNeeded();
  await expect(memory).toContainText("2待同步");
  await expect(memory).toContainText("act-1");
  await expect(memory).toContainText("所有修复必须先补回归测试");
  expect(await inspector.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);

  const approve = memory.getByRole("button", { name: "批准" });
  await approve.click();
  const dialog = page.getByRole("alertdialog", { name: "确认记忆审批" });
  await expect(dialog).toContainText("按其作用域用于后续召回");
  await expect(dialog.getByRole("button", { name: "返回" })).toBeFocused();
  await dialog.getByRole("button", { name: "确认" }).click();
  await expect(memory).toContainText("没有待审批的跨房间记忆");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("MemoryOS derived-index rebuild stays guarded and usable across release viewports", async ({ page }) => {
  await installRoomFixture(page, { memoryRebuildable: true });
  await page.goto("/rooms/conv-1");
  await page.getByRole("button", { name: /工作台/ }).click();
  const inspector = page.locator(".room-inspector");
  await inspector.getByRole("tab", { name: "Room" }).click();
  const memory = inspector.getByRole("region", { name: "长期记忆" });
  await memory.scrollIntoViewIfNeeded();
  const trigger = memory.getByRole("button", { name: "重建 MemoryOS 派生索引" });
  await trigger.click();

  const dialog = page.getByRole("alertdialog", { name: "确认重建 MemoryOS 派生索引？" });
  await expect(dialog).toContainText("只会删除可重建的 MemoryOS 派生缓存");
  await expect(dialog).toContainText("重建期间群聊仍可继续工作");
  await expect(dialog.getByRole("button", { name: "返回" })).toBeFocused();
  const box = await dialog.boundingBox();
  const viewport = page.viewportSize();
  expect(box).not.toBeNull();
  expect(viewport).not.toBeNull();
  expect(box!.y).toBeGreaterThanOrEqual(0);
  expect(box!.y + box!.height).toBeLessThanOrEqual(viewport!.height);
  expect(await dialog.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);

  await dialog.getByRole("button", { name: "确认重建派生索引" }).click();
  await expect(memory.locator(".room-memory-progress")).toContainText("replaying");
  await expect(memory.getByRole("button", { name: "重建 MemoryOS 派生索引" })).toHaveCount(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("compact drawer state, label, and full-viewport scrim stay aligned", async ({ page }, testInfo) => {
  test.skip(!["compact-640", "zoom-200"].includes(testInfo.project.name), "Compact-only behavior");
  await installRoomFixture(page);
  await page.goto("/rooms/conv-1");
  const toggle = page.locator(".room-header").getByRole("button", { name: "打开房间栏" });
  await expect(toggle).toBeVisible();
  await toggle.click();
  const scrim = page.getByRole("button", { name: "关闭房间栏遮罩" });
  await expect(scrim).toBeVisible();
  const box = await scrim.boundingBox();
  expect(box).toMatchObject({ x: 0, y: 0, width: 640, height: testInfo.project.name === "zoom-200" ? 360 : 900 });
  await scrim.click({ position: { x: 620, y: 20 } });
  await expect(page.locator(".room-header").getByRole("button", { name: "打开房间栏" })).toBeVisible();
});

test("compact inspector is a keyboard-modal sheet", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "compact-640", "Compact inspector behavior is covered at 640 CSS px");
  await installRoomFixture(page);
  await page.goto("/rooms/conv-1");
  const trigger = page.getByRole("button", { name: /工作台/ });
  await expect(trigger).toBeVisible();
  await trigger.click();
  const inspector = page.getByRole("dialog", { name: "房间检查器" });
  await expect(inspector).toBeVisible();
  await expect(inspector.getByRole("button", { name: "关闭检查器" })).toBeFocused();
  await inspector.getByRole("tab", { name: "Room" }).click();
  await expect(inspector.getByRole("region", { name: "Human-root Skill" }).first()).toBeVisible();
  await expect(inspector.getByRole("tab", { name: "Runtime" })).toBeVisible();
  expect(await inspector.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.keyboard.press("Escape");
  await expect(inspector).toBeHidden();
  await expect(trigger).toBeFocused();
});

test("the 200% zoom-equivalent viewport preserves the complete chat path", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "zoom-200", "200% zoom-equivalent project only");
  await installRoomFixture(page);
  await page.goto("/rooms/conv-1");
  await expect(page.getByRole("log", { name: "房间消息" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "发送消息" })).toBeVisible();
  await page.locator(".room-turn-status details").first().getByText("控制").click();
  await expect(page.getByRole("button", { name: "取消 Builder 当前处理" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("workroom landmarks and interactive controls pass automated accessibility checks", async ({ page }, testInfo) => {
  await installRoomFixture(page);
  await page.goto("/rooms/conv-1");
  await expect(page.getByRole("heading", { name: "闭环审计室" })).toBeVisible();
  await page.getByRole("button", { name: /工作台/ }).click();
  await page.getByRole("tab", { name: "Agent" }).click();

  const darkResults = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(darkResults.violations).toEqual([]);
  if (process.env.XMUSE_UI_VISUAL_EVIDENCE === "1") {
    await page.screenshot({ fullPage: true, path: `/tmp/xmuse-ui-${testInfo.project.name}-dark.png` });
  }

  if ((page.viewportSize()?.width ?? 1440) < 1180) {
    await page.getByRole("button", { name: "关闭检查器", exact: true }).click();
  }
  await page.getByRole("button", { name: "切换主题" }).click();
  if (!(await page.locator(".room-inspector").count())) {
    await page.getByRole("button", { name: /工作台/ }).click();
    await page.getByRole("tab", { name: "Agent" }).click();
  }
  const lightResults = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(lightResults.violations).toEqual([]);
  if (process.env.XMUSE_UI_VISUAL_EVIDENCE === "1") {
    await page.screenshot({ fullPage: true, path: `/tmp/xmuse-ui-${testInfo.project.name}-light.png` });
  }
});
