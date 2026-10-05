import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { proxyGrantIssue, proxyGrantList, proxyGrantRevoke } from "./grant-proxy";

function issueBody(overrides: Record<string, unknown> = {}) {
  return {
    conversation_id: "conv-1",
    host: "claude-code",
    scope: "board.split.decide",
    ttl_seconds: 600,
    ...overrides
  };
}

function postRequest(
  payload: unknown,
  overrides: {
    origin?: string;
    host?: string;
    contentType?: string;
    contentLength?: string;
  } = {}
) {
  return new Request("http://localhost:3000/api/room-plugin-grants", {
    method: "POST",
    headers: {
      Host: overrides.host ?? "localhost:3000",
      Origin: overrides.origin ?? "http://localhost:3000",
      "Content-Type": overrides.contentType ?? "application/json",
      ...(overrides.contentLength ? { "Content-Length": overrides.contentLength } : {})
    },
    body: JSON.stringify(payload)
  });
}

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

function issueResponse() {
  return {
    schema_version: "plugin_grant_issue/v1",
    grant: {
      grant_id: "grant_1",
      conversation_id: "conv-1",
      host: "claude-code",
      scope: "board.split.decide",
      status: "pending",
      created_at: "2026-10-05T12:00:00Z",
      activated_at: null,
      expires_at: "2026-10-05T12:02:00Z",
      revoked_at: null,
      last_used_at: null,
      use_count: 0
    },
    pairing_code: "ABCD-EFGH",
    pairing_expires_at: "2026-10-05T12:02:00Z"
  };
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

describe("plugin grant issue proxy", () => {
  it("forwards the exact body with the server token injected", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json(issueResponse(), { status: 201 })
    );

    const response = await proxyGrantIssue(postRequest(issueBody()));

    expect(response.status).toBe(201);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/plugin-grants",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        redirect: "manual",
        headers: {
          "Content-Type": "application/json",
          "X-XMuse-Operator-Token": "server-secret"
        },
        body: JSON.stringify(issueBody())
      })
    );
    const serialized = await response.text();
    expect(serialized).not.toContain("server-secret");
  });

  it("rejects extra keys and invalid scope, host or ttl values", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyGrantIssue(postRequest(issueBody({ extra: "nope" })))).status).toBe(400);
    expect((await proxyGrantIssue(postRequest(issueBody({ scope: "board.split.approve" })))).status).toBe(400);
    expect((await proxyGrantIssue(postRequest(issueBody({ host: "Claude Code" })))).status).toBe(400);
    expect((await proxyGrantIssue(postRequest(issueBody({ host: "" })))).status).toBe(400);
    expect((await proxyGrantIssue(postRequest(issueBody({ ttl_seconds: 59 })))).status).toBe(400);
    expect((await proxyGrantIssue(postRequest(issueBody({ ttl_seconds: 3601 })))).status).toBe(400);
    expect((await proxyGrantIssue(postRequest(issueBody({ ttl_seconds: 600.5 })))).status).toBe(400);
    expect((await proxyGrantIssue(postRequest(issueBody({ ttl_seconds: "600" })))).status).toBe(400);
    expect((await proxyGrantIssue(postRequest(issueBody(), { origin: "http://evil.invalid" }))).status).toBe(403);
    expect((await proxyGrantIssue(postRequest(issueBody(), { contentType: "text/plain" }))).status).toBe(415);
    expect((await proxyGrantIssue(postRequest(issueBody(), { contentLength: "9000" }))).status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("answers 503 without the server token and passes upstream codes through", async () => {
    delete process.env.XMUSE_OPERATOR_TOKEN;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const missing = await proxyGrantIssue(postRequest(issueBody()));
    expect(missing.status).toBe(503);
    expect(await missing.json()).toMatchObject({
      detail: { code: "operator_auth_not_configured" }
    });
    expect(fetchMock).not.toHaveBeenCalled();

    process.env.XMUSE_OPERATOR_TOKEN = "server-secret";
    fetchMock.mockResolvedValueOnce(
      Response.json(
        { detail: { code: "plugin_grant_host_invalid", message: "bad host" } },
        { status: 422 }
      )
    );
    const invalid = await proxyGrantIssue(postRequest(issueBody()));
    expect(invalid.status).toBe(422);
    expect(await invalid.json()).toMatchObject({
      detail: { code: "plugin_grant_host_invalid" }
    });

    fetchMock.mockResolvedValueOnce(
      new Response(null, { status: 307, headers: { Location: "https://evil.invalid" } })
    );
    const redirect = await proxyGrantIssue(postRequest(issueBody()));
    expect(redirect.status).toBe(502);
    expect(await redirect.text()).not.toContain("server-secret");
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

  it("rejects a missing or repeated conversation_id without calling upstream", async () => {
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
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards the list read with the server token and no-store", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({
        schema_version: "plugin_grant_list/v1",
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
