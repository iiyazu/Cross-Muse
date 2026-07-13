import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { proxyMemoryRuntimeRebuild } from "./memory-runtime-proxy";

const body = {
  client_action_id: "memory-rebuild-1",
  expected_incident_id: "incident-memory-1"
};

function receipt(overrides: Record<string, unknown> = {}) {
  return {
    schema_version: "room_memory_rebuild_action/v1",
    action_id: "mra_0123456789abcdef0123456789abcdef",
    client_action_id: body.client_action_id,
    status: "applied",
    phase: "complete",
    reason_code: null,
    before: { state: "degraded", code: "memoryos_cache_schema_blocked" },
    after: { state: "ready", code: "ready" },
    result: {
      cache_cleared: true,
      bindings_reset: 2,
      deliveries_reopened: 4,
      claimed_attempts_fenced: 1,
      candidates_requeued: 3
    },
    requested_at: "2026-07-12T10:00:00Z",
    applied_at: "2026-07-12T10:00:01Z",
    proof_boundary: "operator_action_receipt_not_room_or_memory_index_authority",
    ...overrides
  };
}

function request(
  payload: unknown = body,
  overrides: {
    method?: string;
    origin?: string;
    host?: string;
    contentType?: string;
    contentLength?: string;
  } = {}
) {
  return new Request("http://localhost:3000/api/room-memory/rebuild", {
    method: overrides.method ?? "POST",
    headers: {
      Host: overrides.host ?? "localhost:3000",
      Origin: overrides.origin ?? "http://localhost:3000",
      "Content-Type": overrides.contentType ?? "application/json",
      ...(overrides.contentLength ? { "Content-Length": overrides.contentLength } : {})
    },
    body: JSON.stringify(payload)
  });
}

beforeEach(() => {
  process.env.XMUSE_OPERATOR_TOKEN = "server-secret";
  process.env.XMUSE_CHAT_API_BASE_URL = "http://127.0.0.1:8201/api/chat";
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  delete process.env.XMUSE_OPERATOR_TOKEN;
  delete process.env.XMUSE_CHAT_API_BASE_URL;
});

describe("fixed MemoryOS derived-index rebuild proxy", () => {
  it("forwards only the fixed guard and reconstructs a browser-safe receipt", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json(receipt({ pid: 42, data_dir: "/secret/path", api_key: "server-secret" }))
    );

    const response = await proxyMemoryRuntimeRebuild(request());

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/memory-runtime/rebuild",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        redirect: "manual",
        headers: {
          "Content-Type": "application/json",
          "X-XMuse-Operator-Token": "server-secret"
        },
        body: JSON.stringify(body)
      })
    );
    const serialized = JSON.stringify(await response.json());
    expect(serialized).toContain("mra_0123456789abcdef0123456789abcdef");
    expect(serialized).not.toContain("server-secret");
    expect(serialized).not.toContain("/secret/path");
    expect(serialized).not.toContain("pid");
  });

  it("rejects method, Origin/Host, JSON type, extra fields, and both 8KiB limits", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyMemoryRuntimeRebuild(request(body, { method: "PUT" }))).status).toBe(405);
    expect((await proxyMemoryRuntimeRebuild(request(body, { origin: "http://evil.invalid" }))).status).toBe(403);
    expect((await proxyMemoryRuntimeRebuild(request(body, { contentType: "text/plain" }))).status).toBe(415);
    expect((await proxyMemoryRuntimeRebuild(request({ ...body, href: "https://evil.invalid" }))).status).toBe(400);
    expect((await proxyMemoryRuntimeRebuild(request(body, { contentLength: "9000" }))).status).toBe(413);
    expect((await proxyMemoryRuntimeRebuild(request({
      ...body,
      expected_incident_id: "x".repeat(8 * 1024)
    }))).status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires the server token and sanitizes conflicts, redirects, and invalid success bodies", async () => {
    delete process.env.XMUSE_OPERATOR_TOKEN;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyMemoryRuntimeRebuild(request())).status).toBe(503);
    process.env.XMUSE_OPERATOR_TOKEN = "server-secret";

    fetchMock.mockResolvedValueOnce(Response.json({
      detail: {
        code: "room_memory_rebuild_incident_conflict",
        message: "/secret/path server-secret"
      }
    }, { status: 409 }));
    const conflict = await proxyMemoryRuntimeRebuild(request());
    expect(conflict.status).toBe(409);
    const conflictText = await conflict.text();
    expect(conflictText).toContain("room_memory_rebuild_incident_conflict");
    expect(conflictText).not.toContain("/secret/path");
    expect(conflictText).not.toContain("server-secret");

    fetchMock.mockResolvedValueOnce(new Response(null, {
      status: 307,
      headers: { Location: "https://evil.invalid" }
    }));
    expect((await proxyMemoryRuntimeRebuild(request())).status).toBe(502);

    fetchMock.mockResolvedValueOnce(Response.json(receipt({ client_action_id: "wrong" })));
    expect((await proxyMemoryRuntimeRebuild(request())).status).toBe(502);
  });

  it.each([
    { action_id: "server-secret" },
    { phase: "server-secret" },
    { reason_code: "/secret/path" },
    { before: { state: "server-secret", code: "ready" } },
    { after: { state: "ready", code: "/secret/path" } },
    { requested_at: "server-secret" },
    { applied_at: "/secret/path" }
  ])("rejects secret-shaped data in allowed receipt fields: %o", async (override) => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      Response.json(receipt(override))
    );

    const response = await proxyMemoryRuntimeRebuild(request());

    expect(response.status).toBe(502);
    const serialized = await response.text();
    expect(serialized).not.toContain("server-secret");
    expect(serialized).not.toContain("/secret/path");
  });

  it("aborts the fixed upstream after thirty seconds", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_input, init) => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), {
          once: true
        });
      })
    );
    const pending = proxyMemoryRuntimeRebuild(request());
    await vi.advanceTimersByTimeAsync(30_000);
    const response = await pending;
    expect(response.status).toBe(504);
    expect(await response.json()).toMatchObject({
      detail: { code: "room_memory_rebuild_upstream_timeout" }
    });
  });
});
