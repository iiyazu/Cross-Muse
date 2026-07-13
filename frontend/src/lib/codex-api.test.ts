import { describe, expect, it, vi } from "vitest";

import { fetchRoomCodexAgents, submitRoomCodexAction } from "./api";
import type { RoomCodexActionDescriptor } from "./types";

const GUARD = `sha256:${"a".repeat(64)}`;

function descriptor(
  overrides: Partial<RoomCodexActionDescriptor> = {}
): RoomCodexActionDescriptor {
  return {
    capability_id: "goal_set",
    available: true,
    disabled_reason: null,
    method: "POST",
    href: "/api/chat/operator/room-participants/participant%2Fone/codex-actions",
    expected_session_guard: GUARD,
    expected_goal_guard: GUARD,
    expected_settings_guard: GUARD,
    expected_turn_guard: null,
    confirmation_required: false,
    ...overrides
  };
}

describe("Room Codex projection client", () => {
  it("reads the bounded no-store projection with exactly one cursor direction", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({
      schema_version: "room_codex_projection/v1",
      participants: [],
      native_events: { items: [] }
    }));

    await fetchRoomCodexAgents("room/one", {
      fetcher,
      chatApiBaseUrl: "http://127.0.0.1:8201/api/chat",
      limit: 999,
      afterEventSeq: 42
    });

    expect(fetcher).toHaveBeenCalledWith(
      "http://127.0.0.1:8201/api/chat/conversations/room%2Fone/codex-agents?limit=100&after_event_seq=42",
      expect.objectContaining({ method: "GET", cache: "no-store" })
    );
    await expect(fetchRoomCodexAgents("room", {
      beforeEventSeq: 3,
      afterEventSeq: 2
    })).rejects.toMatchObject({ code: "room_codex_projection_cursor_conflict" });
  });

  it("fails closed on a future projection schema", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({
      schema_version: "room_codex_projection/v99",
      participants: []
    }));
    await expect(fetchRoomCodexAgents("room", { fetcher })).rejects.toMatchObject({
      code: "room_codex_projection_schema_unsupported",
      status: 422
    });
  });
});

describe("Room Codex action client", () => {
  it("maps one exact descriptor to the fixed Next route with stable idempotency and guards", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({
      action_id: "action-1",
      client_action_id: "stable-action",
      status: "requested"
    }));
    await submitRoomCodexAction(
      "participant/one",
      "goal_set",
      { objective: "Complete the task", token_budget: 100_000 },
      descriptor(),
      { fetcher, clientActionId: "stable-action" }
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/room-participants/participant%2Fone/codex-actions",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        body: JSON.stringify({
          client_action_id: "stable-action",
          capability_id: "goal_set",
          request: { objective: "Complete the task", token_budget: 100_000 },
          expected_session_guard: GUARD,
          expected_goal_guard: GUARD,
          expected_settings_guard: GUARD,
          expected_turn_guard: null,
          confirmed_pending_observations: false
        })
      })
    );
    expect(JSON.stringify(fetcher.mock.calls)).not.toContain("Operator-Token");
  });

  it("requires the explicit pending-observation confirmation proved by the descriptor", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({ status: "requested" }));
    const guarded = descriptor({ confirmation_required: true });
    await expect(submitRoomCodexAction(
      "participant/one",
      "goal_set",
      { objective: "Goal", token_budget: 100_000 },
      guarded,
      { fetcher }
    )).rejects.toMatchObject({ code: "room_codex_action_descriptor_invalid" });
    await submitRoomCodexAction(
      "participant/one",
      "goal_set",
      { objective: "Goal", token_budget: 100_000 },
      guarded,
      {
        fetcher,
        clientActionId: "confirmed-action",
        confirmedPendingObservations: true
      }
    );
    expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toMatchObject({
      client_action_id: "confirmed-action",
      confirmed_pending_observations: true
    });
  });

  it.each([
    descriptor({ available: false }),
    descriptor({ href: "/api/chat/operator/room-participants/other/codex-actions" }),
    descriptor({ expected_session_guard: "not-a-guard" }),
    descriptor({ capability_id: "turn_interrupt" })
  ])("rejects unavailable, forged, stale, or mismatched descriptors before fetch", async (item) => {
    const fetcher = vi.fn();
    await expect(submitRoomCodexAction(
      "participant/one",
      "goal_set",
      { objective: "Goal", token_budget: 100_000 },
      item,
      { fetcher }
    )).rejects.toMatchObject({ code: "room_codex_action_descriptor_invalid" });
    expect(fetcher).not.toHaveBeenCalled();
  });
});
