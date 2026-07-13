import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { proxyRuntimeRecover } from "./runtime-recover-proxy";

const body = {
  client_action_id: "recover-1",
  expected_incident_id: "opaque-incident"
};

function request(overrides: { origin?: string; host?: string; contentType?: string; payload?: unknown } = {}) {
  return new Request("http://localhost:3000/api/room-runtime/recover", {
    method: "POST",
    headers: {
      Host: overrides.host ?? "localhost:3000",
      Origin: overrides.origin ?? "http://localhost:3000",
      "Content-Type": overrides.contentType ?? "application/json"
    },
    body: JSON.stringify(overrides.payload ?? body)
  });
}

beforeEach(() => {
  process.env.XMUSE_OPERATOR_TOKEN = "server-secret";
  process.env.XMUSE_CHAT_API_BASE_URL = "http://127.0.0.1:8201/api/chat";
});

afterEach(() => {
  vi.restoreAllMocks();
  delete process.env.XMUSE_OPERATOR_TOKEN;
  delete process.env.XMUSE_CHAT_API_BASE_URL;
});

describe("fixed Room runtime recovery server proxy", () => {
  it("forwards the exact guard to the fixed upstream with a server-only token", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ action_id: "recover-1", status: "applied" })
    );

    const response = await proxyRuntimeRecover(request());

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/room-runtime/recover",
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
    expect(await response.json()).toMatchObject({ status: "applied" });
  });

  it("accepts a loopback Host/Origin when Next normalizes request.url to localhost", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ action_id: "recover-loopback", status: "applied" })
    );

    const response = await proxyRuntimeRecover(request({
      host: "127.0.0.1:3000",
      origin: "http://127.0.0.1:3000"
    }));

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("rejects cross-origin, non-JSON, oversized, and additional fields before fetch", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyRuntimeRecover(request({ origin: "http://evil.invalid" }))).status).toBe(403);
    expect((await proxyRuntimeRecover(request({ origin: "http://evil.example", host: "evil.example" }))).status).toBe(403);
    expect((await proxyRuntimeRecover(request({ contentType: "text/plain" }))).status).toBe(415);
    expect((await proxyRuntimeRecover(request({ payload: { ...body, href: "https://evil.invalid" } }))).status).toBe(400);
    expect((await proxyRuntimeRecover(request({ payload: { ...body, expected_incident_id: "" } }))).status).toBe(400);
    const oversized = new Request("http://localhost:3000/api/room-runtime/recover", {
      method: "POST",
      headers: {
        Host: "localhost:3000",
        Origin: "http://localhost:3000",
        "Content-Type": "application/json",
        "Content-Length": "9000"
      },
      body: "{}"
    });
    expect((await proxyRuntimeRecover(oversized)).status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails closed without token, preserves conflicts, and rejects redirects", async () => {
    delete process.env.XMUSE_OPERATOR_TOKEN;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyRuntimeRecover(request())).status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();

    process.env.XMUSE_OPERATOR_TOKEN = "server-secret";
    fetchMock.mockResolvedValueOnce(
      Response.json({ detail: { code: "room_runtime_incident_conflict" } }, { status: 409 })
    );
    expect((await proxyRuntimeRecover(request())).status).toBe(409);

    fetchMock.mockResolvedValueOnce(
      new Response(null, { status: 307, headers: { Location: "https://evil.invalid" } })
    );
    const redirect = await proxyRuntimeRecover(request());
    expect(redirect.status).toBe(502);
    expect(await redirect.json()).toMatchObject({
      detail: { code: "room_runtime_recover_upstream_redirect" }
    });
  });

  it("aborts an upstream that exceeds the thirty second recovery deadline", async () => {
    vi.useFakeTimers();
    try {
      vi.spyOn(globalThis, "fetch").mockImplementation(
        (_input, init) => new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
        })
      );
      const pending = proxyRuntimeRecover(request());
      await vi.advanceTimersByTimeAsync(30_000);
      const response = await pending;
      expect(response.status).toBe(504);
      expect(await response.json()).toMatchObject({
        detail: { code: "room_runtime_recover_upstream_timeout" }
      });
    } finally {
      vi.useRealTimers();
    }
  });
});
