import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { proxyMemoryCandidateResolve } from "./memory-proxy";

const body = {
  client_action_id: "memory-action-1",
  decision: "approve",
  expected_digest: `sha256:${"a".repeat(64)}`,
  expected_revision: 2
};

function request(
  payload: unknown,
  overrides: {
    method?: string;
    origin?: string;
    host?: string;
    contentType?: string;
    contentLength?: string;
  } = {}
) {
  return new Request("http://localhost:3000/api/room-memory-candidates/candidate-1/resolve", {
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

describe("fixed Room memory candidate proxy", () => {
  it("forwards only the fixed route with server token and no-store", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ action_id: "memory-action-1", status: "applied" })
    );

    const response = await proxyMemoryCandidateResolve(request(body), "candidate/one");

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/memory-candidates/candidate%2Fone/resolve",
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
  });

  it("rejects method, Origin/Host, JSON type, 8KiB, target, and extra fields", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect(proxyMemoryCandidateResolve(request(body, { method: "PUT" }), "candidate-1"))
      .toBeInstanceOf(Response);
    expect((await proxyMemoryCandidateResolve(
      request(body, { origin: "http://evil.invalid" }), "candidate-1"
    )).status).toBe(403);
    expect((await proxyMemoryCandidateResolve(
      request(body, { contentType: "text/plain" }), "candidate-1"
    )).status).toBe(415);
    expect((await proxyMemoryCandidateResolve(
      request({ ...body, archive_id: "forbidden" }), "candidate-1"
    )).status).toBe(400);
    expect((await proxyMemoryCandidateResolve(
      request(body, { contentLength: "9000" }), "candidate-1"
    )).status).toBe(413);
    expect((await proxyMemoryCandidateResolve(request(body), " ")).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires token and preserves 409 without following redirects", async () => {
    delete process.env.XMUSE_OPERATOR_TOKEN;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyMemoryCandidateResolve(request(body), "candidate-1")).status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();

    process.env.XMUSE_OPERATOR_TOKEN = "server-secret";
    fetchMock.mockResolvedValueOnce(
      Response.json(
        { detail: { code: "room_memory_candidate_guard_mismatch" } },
        { status: 409 }
      )
    );
    expect((await proxyMemoryCandidateResolve(request(body), "candidate-1")).status).toBe(409);
    fetchMock.mockResolvedValueOnce(
      new Response(null, { status: 307, headers: { Location: "https://evil.invalid" } })
    );
    expect((await proxyMemoryCandidateResolve(request(body), "candidate-1")).status).toBe(502);
  });

  it("aborts the fixed write at thirty seconds", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation(
      (_input, init) => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), {
          once: true
        });
      })
    );
    const pending = proxyMemoryCandidateResolve(request(body), "candidate-1");
    await vi.advanceTimersByTimeAsync(30_000);
    const response = await pending;
    expect(response.status).toBe(504);
    expect(await response.json()).toMatchObject({
      detail: { code: "room_memory_resolve_upstream_timeout" }
    });
  });
});
