import { describe, expect, it, vi } from "vitest";

import {
  fetchRoomMemory,
  rebuildRoomMemoryIndex,
  resolveRoomMemoryCandidate,
  XmuseApiError
} from "./api";

const descriptor = {
  available: true,
  method: "POST" as const,
  href: "/api/chat/operator/memory-candidates/candidate-1/resolve",
  expected_digest: `sha256:${"a".repeat(64)}`,
  expected_revision: 2,
  allowed_decisions: ["approve" as const, "reject" as const]
};

const rebuildDescriptor = {
  available: true,
  pending: false,
  status: null,
  phase: null,
  method: "POST" as const,
  href: "/api/chat/operator/memory-runtime/rebuild" as const,
  expected_incident_id: "incident-memory-1",
  confirmation_required: true
};

describe("Room memory API", () => {
  it("reads the selected Room memory projection with no-store", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      Response.json({ schema_version: "room_memory_projection/v1" })
    );

    await fetchRoomMemory("conv/one", {
      fetcher,
      chatApiBaseUrl: "http://127.0.0.1:8201/api/chat"
    });

    expect(fetcher).toHaveBeenCalledWith(
      "http://127.0.0.1:8201/api/chat/conversations/conv%2Fone/memory",
      expect.objectContaining({ method: "GET", cache: "no-store" })
    );
  });

  it("submits only a projection-proven guarded decision to the fixed Next route", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      Response.json({ action_id: "action-1", status: "applied" })
    );

    await resolveRoomMemoryCandidate("candidate-1", "approve", descriptor, {
      fetcher,
      clientActionId: "stable-action"
    });

    expect(fetcher).toHaveBeenCalledWith(
      "/api/room-memory-candidates/candidate-1/resolve",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        body: JSON.stringify({
          client_action_id: "stable-action",
          decision: "approve",
          expected_digest: descriptor.expected_digest,
          expected_revision: 2
        })
      })
    );
  });

  it("rejects stale or cross-candidate descriptors before fetch", async () => {
    const fetcher = vi.fn();

    await expect(resolveRoomMemoryCandidate(
      "candidate-2", "approve", descriptor, { fetcher }
    )).rejects.toMatchObject({
      code: "room_memory_resolve_descriptor_invalid",
      status: 400
    });
    await expect(resolveRoomMemoryCandidate(
      "candidate-1", "approve", { ...descriptor, available: false }, { fetcher }
    )).rejects.toBeInstanceOf(XmuseApiError);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("submits only the guarded rebuild action to its fixed Next route", async () => {
    const fetcher = vi.fn().mockResolvedValue(Response.json({
      schema_version: "room_memory_rebuild_action/v1",
      action_id: "action-1",
      client_action_id: "stable-rebuild",
      status: "requested"
    }));

    await rebuildRoomMemoryIndex(rebuildDescriptor, {
      fetcher,
      clientActionId: "stable-rebuild"
    });

    expect(fetcher).toHaveBeenCalledWith(
      "/api/room-memory/rebuild",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        credentials: "same-origin",
        body: JSON.stringify({
          client_action_id: "stable-rebuild",
          expected_incident_id: "incident-memory-1"
        })
      })
    );
  });

  it("rejects unavailable, pending, and wrong-href rebuild descriptors before fetch", async () => {
    const fetcher = vi.fn();
    await expect(rebuildRoomMemoryIndex({ ...rebuildDescriptor, available: false }, { fetcher }))
      .rejects.toMatchObject({ code: "room_memory_rebuild_descriptor_invalid", status: 400 });
    await expect(rebuildRoomMemoryIndex({ ...rebuildDescriptor, pending: true }, { fetcher }))
      .rejects.toBeInstanceOf(XmuseApiError);
    await expect(rebuildRoomMemoryIndex({
      ...rebuildDescriptor,
      href: "/api/chat/operator/memory-runtime/rebuild-wrong" as typeof rebuildDescriptor.href
    }, { fetcher })).rejects.toBeInstanceOf(XmuseApiError);
    expect(fetcher).not.toHaveBeenCalled();
  });
});
