import { describe, expect, it } from "vitest";

import {
  mergeRoomTimeline,
  normalizeRoomList,
  normalizeRoomMemoryProjection,
  normalizeRoomOperationsProjection,
  normalizeRoomProjection,
  roomAgentWorkStateLabel,
  roomParticipantStateLabel
} from "./room-view";

describe("Room projection view", () => {
  it("labels Agent work only from native turns and durable Room evidence", () => {
    const participant = {
      participant: {
        participant_id: "part-builder",
        role: "execute",
        display_name: "Builder",
        status: "active" as const
      },
      native_snapshot: {
        source: "codex_app_server_projection_cache" as const,
        observed_at: null,
        available: true,
        value: null
      },
      capabilities: {
        source: "codex_app_server_projection_cache" as const,
        observed_at: null,
        available: false,
        value: null,
        actions: []
      },
      room_bridge: {
        source: "chat.db:room_codex_bridge" as const,
        observed_at: null,
        hold: null,
        queue: { unresolved_count: 0, active_attempt_count: 0, root_blocking: false },
        actions: []
      },
      history_partial: false,
      omitted_event_count: 0
    };

    expect(roomAgentWorkStateLabel(participant)).toBe("无进行中任务");
    expect(roomAgentWorkStateLabel({
      ...participant,
      room_bridge: {
        ...participant.room_bridge,
        queue: { unresolved_count: 1, active_attempt_count: 0, root_blocking: true }
      }
    })).toBe("Room 待处理");
    expect(roomAgentWorkStateLabel({
      ...participant,
      room_bridge: {
        ...participant.room_bridge,
        queue: { unresolved_count: 1, active_attempt_count: 1, root_blocking: true }
      }
    })).toBe("Room 正在处理");
  });

  it("normalizes only the safe bounded Operations projection", () => {
    const result = normalizeRoomOperationsProjection({
      schema_version: "room_operations_projection/v2",
      generated_at: "2026-07-11T10:00:00Z",
      overall: "blocked",
      runtime: {
        runner: { state: "blocked", code: "runner_heartbeat_stale", pid: 42, boot_id: "secret" },
        mcp: { state: "healthy", code: null, token: "secret" },
        host: {
          state: "blocked",
          code: "skill_catalog_drift",
          active_delivery_count: 2,
          retained_cleanup_count: 1,
          provider_binding: "secret"
        },
        memory: {
          enabled: true,
          state: "rebuilding",
          code: "memoryos_cache_rebuild",
          consecutive_restart_count: 3,
          next_retry_at: null,
          last_healthy_at: "2026-07-11T09:00:00Z",
          pid: 44,
          data_dir: "/secret/memory"
        }
      },
      counts: {
        active_delivery: 2,
        retained_cleanup: 1,
        recovery_pending: 1,
        cancel_pending: 0,
        provider_cleanup_pending: 1,
        exhausted: 3
      },
      incident_total: 1,
      incidents: [{
        incident_id: "opaque-1",
        kind: "observation",
        severity: "blocked",
        code: "provider_cleanup_pending",
        title: "等待 Provider 清理",
        detail: "Builder 的旧 delivery 尚未退出",
        started_at: "2026-07-11T09:59:00Z",
        conversation_id: "conv-1",
        conversation_title: "自然群聊",
        participant_id: "part-builder",
        participant_display_name: "Builder",
        observation_id: "obs-1",
        next_action: "open_room",
        lease_token: "secret"
      }],
      actions: {
        recover_runtime: {
          available: true,
          method: "POST",
          href: "/api/chat/operator/room-runtime/recover",
          expected_incident_id: "opaque-1",
          mode: "restart",
          confirmation_required: true,
          arbitrary_href: "https://evil.invalid"
        },
        rebuild_memory_index: {
          available: true,
          pending: false,
          status: null,
          phase: null,
          method: "POST",
          href: "/api/chat/operator/memory-runtime/rebuild",
          expected_incident_id: "memory-opaque-1",
          confirmation_required: true,
          api_key: "secret"
        }
      }
    });

    expect(result).toMatchObject({
      overall: "blocked",
      incident_total: 1,
      runtime: { host: { state: "blocked", active_delivery_count: 2 } },
      actions: {
        recover_runtime: { expected_incident_id: "opaque-1" },
        rebuild_memory_index: { expected_incident_id: "memory-opaque-1" }
      }
    });
    expect(result.incidents[0]).toMatchObject({ conversation_id: "conv-1", next_action: "open_room" });
    const serialized = JSON.stringify(result);
    expect(serialized).not.toContain("secret");
    expect(serialized).not.toContain("pid");
    expect(serialized).not.toContain("arbitrary_href");
    expect(serialized).not.toContain("/secret/memory");
  });

  it("rejects invalid Operations schemas instead of inventing a blocked runtime", () => {
    expect(() => normalizeRoomOperationsProjection({ schema_version: "future/v9" })).toThrow(
      "room_operations_projection_invalid"
    );
    expect(() => normalizeRoomOperationsProjection({
      schema_version: "room_operations_projection/v2",
      overall: "blocked",
      runtime: { runner: {}, mcp: {}, host: { state: "blocked" } },
      actions: {}
    })).toThrow("room_operations_projection_invalid");
    expect(() => normalizeRoomOperationsProjection({
      schema_version: "room_operations_projection/v2",
      overall: "healthy",
      runtime: {
        runner: { state: "provider_owned", code: null },
        mcp: { state: "healthy", code: null },
        host: { state: "healthy" },
        memory: {
          enabled: true,
          state: "ready",
          consecutive_restart_count: 0,
          next_retry_at: null,
          last_healthy_at: null
        }
      },
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
          available: false,
          pending: false,
          status: null,
          phase: null,
          method: "POST",
          href: "/api/chat/operator/memory-runtime/rebuild",
          expected_incident_id: null,
          confirmation_required: true
        }
      }
    })).toThrow("room_operations_projection_invalid");
  });

  it("normalizes Memory evidence while stripping process and index internals", () => {
    const result = normalizeRoomMemoryProjection({
      schema_version: "room_memory_projection/v1",
      projection_only: true,
      proof_boundary: "memory_projection_not_room_or_memory_index_authority",
      generated_at: "2026-07-12T10:00:00Z",
      conversation_id: "conv-1",
      enabled: true,
      degraded: true,
      runtime: {
        enabled: true,
        degraded: true,
        state: "recovering",
        code: "memoryos_process_restarting",
        consecutive_restart_count: 2,
        next_retry_at: "2026-07-12T10:00:02Z",
        last_healthy_at: "2026-07-12T09:59:00Z",
        started_at: null,
        updated_at: "2026-07-12T10:00:00Z",
        pid: 42,
        generation: "secret-generation",
        api_key: "secret-key",
        data_dir: "/secret/path"
      },
      binding: { present: false, revision: 0, session_id: "secret-session" },
      sync: { backlog: 1, pending: 1, processing: 0, failed: 0, conflict: 0, delivered: 3 },
      recent_recalls: [],
      pending_candidate_total: 0,
      pending_candidates: [],
      trace: "secret-trace"
    });

    expect(result.runtime).toMatchObject({
      state: "recovering",
      consecutive_restart_count: 2,
      next_retry_at: "2026-07-12T10:00:02Z"
    });
    const serialized = JSON.stringify(result);
    for (const secret of ["secret-generation", "secret-key", "/secret/path", "secret-session", "secret-trace", "pid"]) {
      expect(serialized).not.toContain(secret);
    }
    expect(() => normalizeRoomMemoryProjection({ schema_version: "future/v9" }))
      .toThrow("room_memory_projection_invalid");
  });

  it("accepts the v2 full-local capability projection without exposing sidecar internals", () => {
    const result = normalizeRoomMemoryProjection({
      schema_version: "room_memory_projection/v2",
      projection_only: true,
      proof_boundary: "memory_projection_not_room_or_memory_index_authority",
      generated_at: "2026-07-14T18:48:09Z",
      conversation_id: "conv-1",
      enabled: true,
      degraded: false,
      profile: "full-local",
      capabilities: { hybrid: true, message_ingest: true, agentic_advisory: true },
      runtime: {
        enabled: true,
        degraded: false,
        state: "ready",
        code: "ready",
        consecutive_restart_count: 1,
        next_retry_at: null,
        last_healthy_at: "2026-07-14T18:48:08Z",
        started_at: "2026-07-14T18:42:20Z",
        updated_at: "2026-07-14T18:48:08Z",
        pid: 42,
        api_key: "secret-key"
      },
      binding: { present: true, session_state: "bound", attachment_state: "attached", revision: 4, session_id: "secret-session" },
      sync: {
        backlog: 3,
        pending: 1,
        processing: 0,
        failed: 0,
        conflict: 0,
        delivered: 23,
        messages: { backlog: 2, pending: 1, processing: 0, failed: 0, conflict: 0, delivered: 12 }
      },
      recent_recalls: [],
      pending_candidate_total: 0,
      pending_candidates: [],
      data_dir: "/secret/path"
    });

    expect(result.schema_version).toBe("room_memory_projection/v2");
    expect(result.profile).toBe("full-local");
    expect(result.capabilities).toEqual({ hybrid: true, message_ingest: true, agentic_advisory: true });
    expect(result.sync.messages).toEqual({ backlog: 2, pending: 1, processing: 0, failed: 0, conflict: 0, delivered: 12 });
    const serialized = JSON.stringify(result);
    for (const secret of ["secret-key", "secret-session", "/secret/path", "pid"]) {
      expect(serialized).not.toContain(secret);
    }
  });

  it("normalizes the durable Room contract without legacy worklist state", () => {
    const projection = normalizeRoomProjection(
      {
        schema_version: "room_chat_projection/v3",
        conversation: { id: "conv-1", title: "自然群聊" },
        status: "active",
        latest_visible_room_seq: 9,
        participants: [
          {
            participant_id: "part-builder",
            role: "builder",
            display_name: "Builder",
            status: "active",
            mention_handle: "@builder",
            frontier: {
              observation_id: "obs-1",
              status: "claimed",
              expired: false,
              attempt_count: 1,
              control_state: "active",
              control_seq: 3,
              manual_retry_budget: 1,
              current_attempt: {
                attempt_id: "attempt-internal",
                attempt_number: 2,
                effective_attempt_limit: 4,
                state: "delivering",
                reason_code: "operator_retry",
                claimed_at: "2026-07-10T10:00:00Z",
                transport_started_at: "2026-07-10T10:00:01Z",
                delivery_task_id: "must-not-leak",
                recovery: {
                  state: "fenced",
                  reason_code: "room_runner_boot_lost",
                  started_at: "2026-07-10T10:00:02Z",
                  completed_at: null,
                  next_action: "cleanup_pending",
                  runner_generation: "must-not-leak-generation",
                  runner_boot_id: "must-not-leak-boot",
                  provider_session_id: "must-not-leak-provider"
                }
              }
            }
          }
        ],
        turns: [
          {
            correlation_id: "corr-1",
            status: "active",
            excluded_stopped_count: 0,
            participants: [
              {
                participant_id: "part-builder",
                role: "builder",
                display_name: "Builder",
                state: "thinking",
                unresolved_count: 1
              }
            ]
          }
        ],
        timeline_items: [
          {
            kind: "message",
            room_seq: 9,
            activity_id: "act-9",
            message_id: "msg-9",
            correlation_id: "corr-1",
            actor: {
              kind: "agent",
              participant_id: "part-builder",
              role: "builder",
              display_name: "Builder"
            },
            content: "我会独立处理。"
          }
        ],
        page: {
          has_older: true,
          has_newer: false,
          next_before_room_seq: 9,
          next_after_room_seq: 9
        },
        groupchat_worklist: { status: "claimed" }
      },
      "conv-1"
    );

    expect(projection.room_state).toBe("active");
    expect(projection.participants[0].frontier?.observation_id).toBe("obs-1");
    expect(projection.participants[0].frontier?.current_attempt).toEqual({
      attempt_number: 2,
      effective_attempt_limit: 4,
      state: "delivering",
      reason_code: "operator_retry",
      claimed_at: "2026-07-10T10:00:00Z",
      expires_at: null,
      transport_started_at: "2026-07-10T10:00:01Z",
      finished_at: null,
      updated_at: null,
      recovery: {
        state: "fenced",
        reason_code: "room_runner_boot_lost",
        started_at: "2026-07-10T10:00:02Z",
        completed_at: null,
        next_action: "cleanup_pending"
      },
      skill_decision: undefined
    });
    expect(projection.participants[0].frontier?.current_attempt).not.toHaveProperty("attempt_id");
    expect(projection.participants[0].frontier?.current_attempt).not.toHaveProperty("delivery_task_id");
    expect(JSON.stringify(projection)).not.toContain("must-not-leak");
    expect(projection.turns[0].participants[0].status).toBe("thinking");
    expect(projection.timeline_items[0]).toMatchObject({
      id: "msg-9",
      room_seq: 9,
      content: "我会独立处理。"
    });
    expect(projection).not.toHaveProperty("groupchat_worklist");
  });

  it("keeps room list state, member handles, and latest durable preview", () => {
    const result = normalizeRoomList({
      schema_version: "room_list_projection/v1",
      rooms: [
        {
          conversation_id: "conv-2",
          title: "审视方案",
          status: "attention",
          latest_visible_room_seq: 12,
          latest_visible_item: {
            kind: "message",
            room_seq: 12,
            message_id: "msg-12",
            actor: { kind: "human", role: "human", display_name: "你" },
            content: "继续审计"
          },
          participants: [
            {
              participant_id: "part-review",
              role: "reviewer",
              display_name: "Reviewer",
              status: "active",
              mention_handle: "reviewer"
            }
          ],
          active_turn_count: 1,
          attention_turn_count: 1
        }
      ]
    });

    expect(result.rooms[0]).toMatchObject({
      state: "attention",
      latest_visible_room_seq: 12,
      active_turn_count: 1
    });
    expect(result.rooms[0].members[0].mention_handle).toBe("@reviewer");
    expect(result.rooms[0].latest_visible_item?.content).toBe("继续审计");
  });

  it("normalizes only public selected/submitted Skill evidence", () => {
    const projection = normalizeRoomProjection({
      schema_version: "room_chat_projection/v3",
      conversation: { id: "conv-skill", title: "Skill evidence" },
      participants: [{
        participant_id: "part-review",
        role: "review",
        display_name: "Reviewer",
        participant_status: "active",
        frontier: {
          status: "claimed",
          current_attempt: {
            attempt_number: 1,
            effective_attempt_limit: 3,
            state: "delivering",
            skill_decision: {
              skill_id: "evidence-review",
              version: "1.0.0",
              content_sha256: "sha256:public-content",
              selection_reason: "trigger",
              matched_terms: ["审计", "风险"],
              context_status: "selected",
              body: "must-not-leak",
              path: "/private/SKILL.md",
              context_payload_sha256: "sha256:private-payload"
            }
          }
        },
        last_completed_outcome: {
          outcome_type: "noop",
          skill_decision: { decision: "none", context_status: "selected" }
        }
      }],
      turns: [{
        correlation_id: "corr-skill",
        status: "active",
        excluded_stopped_count: 0,
        participants: [{
          participant_id: "part-review",
          role: "review",
          display_name: "Reviewer",
          state: "thinking",
          unresolved_count: 1,
          root_skill_decision: {
            skill_id: "evidence-review",
            version: "1.0.0",
            content_sha256: "sha256:public-content",
            selection_reason: "explicit",
            matched_terms: [],
            context_status: "submitted",
            context_submitted_at: "2026-07-10T10:00:00Z",
            session_id: "private-session",
            lease_token: "private-lease"
          }
        }]
      }],
      timeline_items: [],
      page: { has_older: false, has_newer: false }
    }, "conv-skill");

    expect(projection.participants[0].frontier?.current_attempt?.skill_decision).toEqual({
      skill_id: "evidence-review",
      version: "1.0.0",
      content_sha256: "sha256:public-content",
      selection_reason: "trigger",
      matched_terms: ["审计", "风险"],
      context_status: "selected",
      context_submitted_at: null
    });
    expect(projection.participants[0].last_completed_outcome?.skill_decision).toBeUndefined();
    expect(projection.turns[0].participants[0].root_skill_decision?.context_status).toBe("submitted");
    expect(projection.turns[0].participants[0].root_skill_decision).not.toHaveProperty("session_id");
    expect(JSON.stringify(projection)).not.toContain("private");
  });

  it("normalizes batch evidence, durable totals, and resolved causal labels", () => {
    const projection = normalizeRoomProjection({
      schema_version: "room_chat_projection/v3",
      conversation: { id: "conv-batch", title: "Batch evidence" },
      participants: [{
        participant_id: "part-builder",
        role: "builder",
        display_name: "Builder",
        participant_status: "active",
        frontier: {
          observation_id: "obs-peer-1",
          batch_id: "batch-peer-1",
          phase: "peer",
          member_count: 2,
          member_activity_refs: [
            { activity_id: "act-peer-1", room_seq: 2 },
            { activity_id: "act-peer-2", room_seq: 3 }
          ],
          attempt_count: 2,
          context_only_tail: false,
          coverage: {
            mode: "batch",
            cutoff_room_seq: 3,
            included_member_count: 2,
            omitted_member_count: 0
          }
        }
      }],
      turns: [{
        correlation_id: "corr-batch",
        status: "active",
        observation_count: 4,
        attempt_count: 3,
        skill_decision_count: 3,
        excluded_stopped_count: 0,
        participants: []
      }],
      timeline_items: [{
        kind: "handoff",
        room_seq: 4,
        activity_id: "act-handoff",
        message_id: "msg-handoff",
        reply_to_activity_id: "act-human",
        reply_to_message_id: "msg-human",
        reply_target_display_name: "你",
        target_participant_ids: ["part-reviewer"],
        handoff_targets: ["Reviewer"],
        context_only_tail: true,
        actor: { kind: "agent", role: "builder", display_name: "Builder" },
        content: "请继续核验"
      }],
      page: { has_older: false, has_newer: false }
    }, "conv-batch");

    expect(projection.participants[0].frontier).toMatchObject({
      batch_id: "batch-peer-1",
      phase: "peer",
      member_count: 2,
      attempt_count: 2,
      coverage: { included_member_count: 2, omitted_member_count: 0 }
    });
    expect(projection.turns[0]).toMatchObject({
      observation_count: 4,
      attempt_count: 3,
      skill_decision_count: 3
    });
    expect(projection.timeline_items[0]).toMatchObject({
      reply_to_activity_id: "act-human",
      reply_to_message_id: "msg-human",
      reply_target_display_name: "你",
      handoff_targets: ["Reviewer"],
      target_participant_ids: ["part-reviewer"],
      context_only_tail: true
    });
  });

  it("merges overlapping pages by durable item id and Room sequence", () => {
    const actor = { kind: "human", role: "human", display_name: "你" };
    const merged = mergeRoomTimeline(
      [
        { id: "msg-2", room_seq: 2, kind: "message", actor, content: "旧正文" },
        { id: "msg-3", room_seq: 3, kind: "message", actor, content: "三" }
      ],
      [
        { id: "msg-1", room_seq: 1, kind: "message", actor, content: "一" },
        { id: "msg-2", room_seq: 2, kind: "message", actor, content: "新正文" }
      ]
    );

    expect(merged.map((item) => item.id)).toEqual(["msg-1", "msg-2", "msg-3"]);
    expect(merged[1].content).toBe("新正文");
    expect(roomParticipantStateLabel("runtime_recovery")).toBe("等待运行时恢复");
    expect(roomParticipantStateLabel("deferred")).toBe("暂缓，不承诺自动唤醒");
  });

  it("fails closed on the wrong Room schema or conversation identity", () => {
    expect(() => normalizeRoomList({ schema_version: "legacy_rooms/v1", rooms: [] }))
      .toThrow("room_list_projection_schema_invalid");
    expect(() => normalizeRoomProjection({
      schema_version: "room_chat_projection/v1",
      conversation: { id: "conv-requested", title: "Old contract" },
      timeline_items: [],
      participants: [],
      turns: [],
      page: { has_older: false, has_newer: false }
    }, "conv-requested")).toThrow("room_chat_projection_schema_invalid");
    expect(() => normalizeRoomProjection({
      schema_version: "room_chat_projection/v3",
      conversation: { id: "conv-other", title: "Wrong Room" },
      timeline_items: [],
      participants: [],
      turns: [],
      page: { has_older: false, has_newer: false }
    }, "conv-requested")).toThrow("room_chat_projection_conversation_mismatch");
  });
});
