import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { proxyGrantList, proxyGrantRevoke } from "./grant-proxy";

function getRequest(
  query: string,
  overrides: { hostHeader?: string | null; fetchSite?: string; url?: string } = {}
) {
  return new Request(
    overrides.url ?? `http://localhost:3000/api/room-plugin-grants${query}`,
    {
      method: "GET",
      headers: {
        ...(overrides.hostHeader === null ? {} : { Host: overrides.hostHeader ?? "localhost:3000" }),
        ...(overrides.fetchSite ? { "Sec-Fetch-Site": overrides.fetchSite } : {})
      }
    }
  );
}

function revokeRequest(payload: unknown) {
  return new Request("http://localhost:3000/api/room-plugin-grants/grant-1/revoke", {
    method: "POST",
    headers: {
      Host: "localhost:3000",
      Origin: "http://localhost:3000",
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
  vi.useRealTimers();
  delete process.env.XMUSE_OPERATOR_TOKEN;
  delete process.env.XMUSE_CHAT_API_BASE_URL;
});

describe("plugin grant issue route", () => {
  it("does not exist: pairing is terminal-only (T16)", async () => {
    const route = await import("@/app/api/room-plugin-grants/route");
    expect("POST" in route).toBe(false);
    expect(typeof route.GET).toBe("function");
  });
});

describe("plugin grant list proxy", () => {
  it("requires a loopback Host and same-origin fetch metadata", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect(
      (await proxyGrantList(getRequest("?conversation_id=conv-1", { fetchSite: "cross-site" }))).status
    ).toBe(403);
    expect(
      (await proxyGrantList(getRequest("?conversation_id=conv-1", { fetchSite: "same-site" }))).status
    ).toBe(403);
    expect((await proxyGrantList(getRequest("?conversation_id=conv-1"))).status).toBe(403);
    expect(
      (
        await proxyGrantList(
          getRequest("?conversation_id=conv-1", {
            fetchSite: "same-origin",
            hostHeader: "evil.invalid",
            url: "http://evil.invalid/api/room-plugin-grants?conversation_id=conv-1"
          })
        )
      ).status
    ).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a missing, repeated or mixed key and a malformed host without calling upstream", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyGrantList(getRequest("", { fetchSite: "same-origin" }))).status).toBe(400);
    expect(
      (await proxyGrantList(getRequest("?other=1", { fetchSite: "same-origin" }))).status
    ).toBe(400);
    expect(
      (
        await proxyGrantList(
          getRequest("?conversation_id=conv-1&conversation_id=conv-2", {
            fetchSite: "same-origin"
          })
        )
      ).status
    ).toBe(400);
    expect(
      (await proxyGrantList(getRequest("?conversation_id=conv-1&host=claude-code", { fetchSite: "same-origin" }))).status
    ).toBe(400);
    expect(
      (await proxyGrantList(getRequest("?host=Claude%20Code", { fetchSite: "same-origin" }))).status
    ).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards the list read with the server token and no-store", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({
        schema_version: "plugin_grant_list/v2",
        conversation_id: "conv-1",
        grants: []
      })
    );
    const response = await proxyGrantList(
      getRequest("?conversation_id=conv-1", { fetchSite: "same-origin" })
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/plugin-grants?conversation_id=conv-1",
      expect.objectContaining({
        method: "GET",
        cache: "no-store",
        redirect: "manual",
        headers: { "X-XMuse-Operator-Token": "server-secret" }
      })
    );
    expect(await response.text()).not.toContain("server-secret");

    await proxyGrantList(getRequest("?host=claude-code", { fetchSite: "same-origin" }));
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/plugin-grants?host=claude-code",
      expect.objectContaining({ method: "GET" })
    );
  });
});

describe("plugin grant revoke proxy", () => {
  it("forwards exactly the room id to the fixed upstream revoke path", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ grant_id: "grant-1", status: "revoked" })
    );
    const response = await proxyGrantRevoke(revokeRequest({ conversation_id: "conv-1" }), "grant-1");
    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/plugin-grants/grant-1/revoke",
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-XMuse-Operator-Token": "server-secret"
        },
        body: JSON.stringify({ conversation_id: "conv-1" })
      })
    );
  });

  it("rejects an invalid target, extra keys and a missing token", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyGrantRevoke(revokeRequest({ conversation_id: "conv-1" }), " ")).status).toBe(400);
    expect(
      (
        await proxyGrantRevoke(
          revokeRequest({ conversation_id: "conv-1", extra: true }),
          "grant-1"
        )
      ).status
    ).toBe(400);
    delete process.env.XMUSE_OPERATOR_TOKEN;
    expect(
      (await proxyGrantRevoke(revokeRequest({ conversation_id: "conv-1" }), "grant-1")).status
    ).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();

    process.env.XMUSE_OPERATOR_TOKEN = "server-secret";
    fetchMock.mockResolvedValueOnce(
      Response.json(
        { detail: { code: "plugin_grant_unknown", message: "unknown grant" } },
        { status: 404 }
      )
    );
    const unknown = await proxyGrantRevoke(
      revokeRequest({ conversation_id: "conv-1" }),
      "grant-1"
    );
    expect(unknown.status).toBe(404);
    expect(await unknown.json()).toMatchObject({
      detail: { code: "plugin_grant_unknown" }
    });
  });
});
