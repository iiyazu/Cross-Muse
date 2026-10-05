import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { proxyRoomCreate } from "./room-write-proxy";

function request(payload: unknown) {
  return new Request("http://127.0.0.1:3000/api/rooms", {
    method: "POST",
    headers: {
      Host: "127.0.0.1:3000",
      Origin: "http://127.0.0.1:3000",
      "Content-Type": "application/json"
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
  delete process.env.XMUSE_OPERATOR_TOKEN;
  delete process.env.XMUSE_CHAT_API_BASE_URL;
});

describe("room create review_policy", () => {
  it("forwards cross_family inside collaboration and rejects unknown policies", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ id: "conv-1" }, { status: 201 })
    );
    const ok = await proxyRoomCreate(
      request({
        title: "R",
        client_request_id: "c1",
        roster_template_id: "builtin.development",
        collaboration: { mode: "broadcast", review_policy: "cross_family" }
      })
    );
    expect(ok.status).toBe(201);
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body))).toMatchObject({
      collaboration: { mode: "broadcast", review_policy: "cross_family" }
    });

    const bad = await proxyRoomCreate(
      request({
        title: "R",
        client_request_id: "c2",
        collaboration: { mode: "broadcast", review_policy: "sometimes" }
      })
    );
    expect(bad.status).toBe(400);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("omitting review_policy behaves like today", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ id: "conv-1" }, { status: 201 })
    );
    await proxyRoomCreate(
      request({ title: "R", client_request_id: "c3", collaboration: { mode: "broadcast" } })
    );
    expect(JSON.parse(String(fetchMock.mock.calls[0][1]?.body)).collaboration).toEqual({
      mode: "broadcast"
    });
  });
});
