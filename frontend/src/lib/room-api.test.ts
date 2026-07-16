import { describe, expect, it, vi } from "vitest";

import {
  createConversation,
  fetchRoomOperations,
  fetchRoomProjection,
  fetchRoomSetupOptions,
  fetchRooms,
  recoverRoomRuntime,
  sendThreadMessage,
  submitRoomObservationControl
} from "./api";

describe("Room API client", () => {
  it("uses fixed same-origin routes and stable request ids for browser writes", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json({ id: "conv-1" }, { status: 201 })
    );
    await createConversation("Room", { fetcher, clientRequestId: "create-1" });
    await sendThreadMessage("conv/one", "hello", { fetcher, clientRequestId: "message-1" });

    expect(fetcher.mock.calls[0][0]).toBe("/api/rooms");
    expect(fetcher.mock.calls[0][1]).toEqual(expect.objectContaining({
      credentials: "same-origin",
      body: JSON.stringify({
        title: "Room",
        client_request_id: "create-1",
        roster_template_id: "builtin.development"
      })
    }));
    expect(fetcher.mock.calls[1][0]).toBe("/api/rooms/conv%2Fone/messages");
    expect(fetcher.mock.calls[1][1]).toEqual(expect.objectContaining({
      credentials: "same-origin",
      body: JSON.stringify({ message: "hello", client_request_id: "message-1" })
    }));
    expect(JSON.stringify(fetcher.mock.calls)).not.toContain("Operator-Token");
  });

  it("maps a read deadline to frontend_request_timeout", async () => {
    vi.useFakeTimers();
    try {
      const fetcher = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
        })
      );
      const pending = fetchRooms({ fetcher, timeoutMs: 10_000 });
      const rejected = expect(pending).rejects.toMatchObject({ code: "frontend_request_timeout" });
      await vi.advanceTimersByTimeAsync(10_000);
      await rejected;
    } finally {
      vi.useRealTimers();
    }
  });

  it("uses the bounded lightweight room list endpoint", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ schema_version: "room_list_projection/v1", rooms: [] }))
    );
    await fetchRooms({ fetcher, chatApiBaseUrl: "http://localhost:8201/api/chat" });
    expect(fetcher).toHaveBeenCalledWith(
      "http://localhost:8201/api/chat/rooms",
      expect.objectContaining({ method: "GET", cache: "no-store" })
    );
  });

  it("reads roster setup options and rejects a future schema", async () => {
    const payload = {
      schema_version: "room_setup_options/v1",
      default_roster_template_id: "builtin.development",
      roster_templates: []
    };
    const fetcher = vi.fn(async () => Response.json(payload));
    await expect(fetchRoomSetupOptions({ fetcher, chatApiBaseUrl: "http://localhost:8201/api/chat" }))
      .resolves.toEqual(payload);
    expect(fetcher).toHaveBeenCalledWith(
      "http://localhost:8201/api/chat/room-setup-options",
      expect.objectContaining({ method: "GET", cache: "no-store" })
    );

    fetcher.mockResolvedValueOnce(Response.json({ ...payload, schema_version: "room_setup_options/v2" }));
    await expect(fetchRoomSetupOptions({ fetcher })).rejects.toMatchObject({
      code: "room_setup_options_schema_unsupported"
    });
  });

  it("encodes exactly one Room pagination direction and caps the limit", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(
        JSON.stringify({
          schema_version: "room_chat_projection/v3",
          conversation: { id: "conv/one", title: "Room" },
          status: "settled",
          participants: [],
          turns: [],
          timeline_items: [],
          page: { has_older: false, has_newer: false }
        })
      )
    );
    await fetchRoomProjection("conv/one", {
      fetcher,
      chatApiBaseUrl: "http://localhost:8201/api/chat",
      limit: 500,
      afterRoomSeq: 42
    });
    expect(fetcher.mock.calls[0][0]).toBe(
      "http://localhost:8201/api/chat/conversations/conv%2Fone/room-projection?limit=100&after_room_seq=42"
    );
    await expect(
      fetchRoomProjection("conv-1", { beforeRoomSeq: 2, afterRoomSeq: 3 })
    ).rejects.toMatchObject({ code: "room_projection_cursor_conflict" });
  });
});

describe("Room control client", () => {
  const descriptor = {
    available: true,
    href: "/api/chat/operator/room-observations/obs-1/cancel",
    expected_state: "active" as const,
    expected_attempt_count: 1,
    expected_control_seq: 3
  };

  it("posts guards to the fixed same-origin route without an operator token", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json({ action_id: "action-1", status: "succeeded" })
    );
    await submitRoomObservationControl("obs-1", "cancel", descriptor, {
      fetcher,
      clientActionId: "action-1"
    });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/room-observations/obs-1/cancel",
      expect.objectContaining({
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify({
          client_action_id: "action-1",
          expected_state: "active",
          expected_attempt_count: 1,
          expected_control_seq: 3
        })
      })
    );
    const serialized = JSON.stringify(fetcher.mock.calls);
    expect(serialized).not.toContain("operator_token");
    expect(serialized).not.toContain("X-XMuse-Operator-Token");
  });

  it("rejects a stale or mismatched descriptor without calling the proxy", async () => {
    const fetcher = vi.fn();
    await expect(
      submitRoomObservationControl("obs-1", "retry", descriptor, { fetcher })
    ).rejects.toMatchObject({ code: "room_control_descriptor_invalid" });
    expect(fetcher).not.toHaveBeenCalled();
  });
});

describe("Room runtime Operations client", () => {
  const descriptor = {
    available: true,
    method: "POST" as const,
    href: "/api/chat/operator/room-runtime/recover" as const,
    expected_incident_id: "opaque-incident",
    mode: "restart" as const,
    confirmation_required: true
  };

  it("reads Operations from the lightweight no-store endpoint", async () => {
    const fetcher = vi.fn(async () => Response.json({ schema_version: "room_operations_projection/v2" }));
    await fetchRoomOperations({ fetcher, chatApiBaseUrl: "http://localhost:8201/api/chat" });
    expect(fetcher).toHaveBeenCalledWith(
      "http://localhost:8201/api/chat/runtime/operations",
      expect.objectContaining({ method: "GET", cache: "no-store" })
    );
  });

  it("posts only the opaque guard to the fixed same-origin recover route", async () => {
    const fetcher = vi.fn(async () => Response.json({ action_id: "recover-1", status: "applied" }));
    await recoverRoomRuntime(descriptor, { fetcher, clientActionId: "recover-1" });
    expect(fetcher).toHaveBeenCalledWith(
      "/api/room-runtime/recover",
      expect.objectContaining({
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify({
          client_action_id: "recover-1",
          expected_incident_id: "opaque-incident"
        })
      })
    );
    expect(JSON.stringify(fetcher.mock.calls)).not.toContain("operator_token");
  });

  it("rejects unavailable and non-fixed descriptors before fetch", async () => {
    const fetcher = vi.fn();
    await expect(recoverRoomRuntime({ ...descriptor, available: false }, { fetcher })).rejects.toMatchObject({
      code: "room_runtime_recover_descriptor_invalid"
    });
    expect(fetcher).not.toHaveBeenCalled();
  });
});
