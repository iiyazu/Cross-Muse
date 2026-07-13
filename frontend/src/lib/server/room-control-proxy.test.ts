import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { proxyRoomControl } from "./room-control-proxy";

const body = {
  client_action_id: "control-1",
  expected_state: "active",
  expected_attempt_count: 2,
  expected_control_seq: 4
};

function request(overrides: { origin?: string; host?: string; contentType?: string; payload?: unknown } = {}) {
  return new Request("http://localhost:3000/api/room-observations/obs-1/cancel", {
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

describe("fixed Room control server proxy", () => {
  it("forwards only validated guards and keeps the operator token server-side", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ status: "succeeded", action_id: "control-1" })
    );

    const response = await proxyRoomControl(request(), "obs/one", "cancel");

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/room-observations/obs%2Fone/cancel",
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
    expect(await response.json()).toMatchObject({ status: "succeeded" });
  });

  it("accepts a loopback Host/Origin when Next normalizes request.url to localhost", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ status: "succeeded", action_id: "control-loopback" })
    );

    const response = await proxyRoomControl(
      request({ host: "127.0.0.1:3000", origin: "http://127.0.0.1:3000" }),
      "obs-1",
      "cancel"
    );

    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("rejects cross-origin, non-JSON, oversized, and malformed payloads before fetch", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyRoomControl(request({ origin: "http://evil.invalid" }), "obs-1", "cancel")).status).toBe(403);
    expect((await proxyRoomControl(request({ origin: "http://evil.example", host: "evil.example" }), "obs-1", "cancel")).status).toBe(403);
    expect((await proxyRoomControl(request({ contentType: "text/plain" }), "obs-1", "cancel")).status).toBe(415);
    expect((await proxyRoomControl(request({ contentType: "application/jsonp" }), "obs-1", "cancel")).status).toBe(415);
    expect((await proxyRoomControl(request({ payload: { ...body, expected_control_seq: -1 } }), "obs-1", "cancel")).status).toBe(400);
    expect((await proxyRoomControl(request({ payload: { ...body, href: "https://evil.invalid" } }), "obs-1", "cancel")).status).toBe(400);
    const oversized = new Request("http://localhost:3000/api/room-observations/obs-1/cancel", {
      method: "POST",
      headers: {
        Host: "localhost:3000",
        Origin: "http://localhost:3000",
        "Content-Type": "application/json",
        "Content-Length": "9000"
      },
      body: "{}"
    });
    expect((await proxyRoomControl(oversized, "obs-1", "cancel")).status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails closed without the server token and preserves upstream conflicts", async () => {
    delete process.env.XMUSE_OPERATOR_TOKEN;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const missing = await proxyRoomControl(request(), "obs-1", "retry");
    expect(missing.status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();

    process.env.XMUSE_OPERATOR_TOKEN = "server-secret";
    fetchMock.mockResolvedValueOnce(
      Response.json(
        { detail: { code: "room_control_seq_conflict", message: "room_control_seq_conflict" } },
        { status: 409 }
      )
    );
    const conflict = await proxyRoomControl(
      request({ payload: { ...body, expected_state: "cancelled" } }),
      "obs-1",
      "retry"
    );
    expect(conflict.status).toBe(409);
    expect(await conflict.json()).toMatchObject({ detail: { code: "room_control_seq_conflict" } });
  });

  it("does not follow an upstream redirect", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 307, headers: { Location: "https://evil.invalid" } })
    );
    const response = await proxyRoomControl(request(), "obs-1", "cancel");
    expect(response.status).toBe(502);
    expect(await response.json()).toMatchObject({ detail: { code: "room_control_upstream_redirect" } });
  });
});
