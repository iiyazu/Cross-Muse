import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { proxyReviewDecision, proxyReviewMaterial } from "./review-proxy";

const DIGEST = `sha256:${"a".repeat(64)}`;

function decisionBody(overrides: Record<string, unknown> = {}) {
  return {
    conversation_id: "conv-1",
    verdict: "endorse",
    expected_digest: DIGEST,
    summary: "looks good",
    findings: [],
    ...overrides
  };
}

function postRequest(payload: unknown, overrides: { origin?: string; contentType?: string; contentLength?: string } = {}) {
  return new Request("http://localhost:3000/api/room-board-reviews/r1/decision", {
    method: "POST",
    headers: {
      Host: "localhost:3000",
      Origin: overrides.origin ?? "http://localhost:3000",
      "Content-Type": overrides.contentType ?? "application/json",
      ...(overrides.contentLength ? { "Content-Length": overrides.contentLength } : {})
    },
    body: JSON.stringify(payload)
  });
}

function getRequest(query: string, overrides: { hostHeader?: string | null; fetchSite?: string; url?: string } = {}) {
  return new Request(overrides.url ?? `http://localhost:3000/api/room-board-reviews/r1/material${query}`, {
    method: "GET",
    headers: {
      ...(overrides.hostHeader === null ? {} : { Host: overrides.hostHeader ?? "localhost:3000" }),
      ...(overrides.fetchSite ? { "Sec-Fetch-Site": overrides.fetchSite } : {})
    }
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

describe("review material proxy", () => {
  it("forwards the material read with the server token and no-store", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({
        schema_version: "room_board_review_material/v1",
        review_id: "r1",
        verification_id: "v1",
        head_commit: "abc",
        digest: DIGEST,
        patch: { text: "diff", bytes_total: 4, truncated: false, hidden_char_count: 0 }
      })
    );
    const response = await proxyReviewMaterial(
      getRequest("?conversation_id=conv-1", { fetchSite: "same-origin" }),
      "r1"
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/board-reviews/r1/material?conversation_id=conv-1",
      expect.objectContaining({
        method: "GET",
        cache: "no-store",
        redirect: "manual",
        headers: { "X-XMuse-Operator-Token": "server-secret" }
      })
    );
    expect(await response.text()).not.toContain("server-secret");
  });

  it("rejects non-loopback Host, missing fetch metadata, and bad queries", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect(
      (await proxyReviewMaterial(getRequest("?conversation_id=conv-1", { fetchSite: "cross-site" }), "r1"))
        .status
    ).toBe(403);
    expect((await proxyReviewMaterial(getRequest("?conversation_id=conv-1"), "r1")).status).toBe(403);
    expect(
      (
        await proxyReviewMaterial(
          getRequest("?conversation_id=conv-1", {
            fetchSite: "same-origin",
            hostHeader: "evil.invalid",
            url: "http://evil.invalid/api/room-board-reviews/r1/material?conversation_id=conv-1"
          }),
          "r1"
        )
      ).status
    ).toBe(403);
    expect((await proxyReviewMaterial(getRequest("", { fetchSite: "same-origin" }), "r1")).status).toBe(
      400
    );
    expect(
      (await proxyReviewMaterial(getRequest("?other=1", { fetchSite: "same-origin" }), "r1")).status
    ).toBe(400);
    expect((await proxyReviewMaterial(getRequest("?conversation_id=conv-1", { fetchSite: "same-origin" }), " ")).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires the server token and passes upstream detail codes through", async () => {
    delete process.env.XMUSE_OPERATOR_TOKEN;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const missing = await proxyReviewMaterial(
      getRequest("?conversation_id=conv-1", { fetchSite: "same-origin" }),
      "r1"
    );
    expect(missing.status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();

    process.env.XMUSE_OPERATOR_TOKEN = "server-secret";
    fetchMock.mockResolvedValueOnce(
      Response.json({ detail: { code: "room_board_review_unknown", message: "nope" } }, { status: 404 })
    );
    const unknown = await proxyReviewMaterial(
      getRequest("?conversation_id=conv-1", { fetchSite: "same-origin" }),
      "r1"
    );
    expect(unknown.status).toBe(404);
    expect(await unknown.json()).toMatchObject({ detail: { code: "room_board_review_unknown" } });
  });
});

describe("review decision proxy", () => {
  it("forwards the exact body with proxy-set decided_via", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ ok: true }));
    const response = await proxyReviewDecision(postRequest(decisionBody()), "r/1");
    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/board-reviews/r%2F1/decision",
      expect.objectContaining({
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-XMuse-Operator-Token": "server-secret"
        },
        body: JSON.stringify({ ...decisionBody(), decided_via: "web" })
      })
    );
    expect(await response.text()).not.toContain("server-secret");
  });

  it("rejects browser-set decided_via, bad verdicts, digests, and findings", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyReviewDecision(postRequest(decisionBody({ decided_via: "cli" })), "r1")).status).toBe(400);
    expect((await proxyReviewDecision(postRequest(decisionBody({ verdict: "maybe" })), "r1")).status).toBe(400);
    expect((await proxyReviewDecision(postRequest(decisionBody({ expected_digest: "sha256:xyz" })), "r1")).status).toBe(400);
    expect((await proxyReviewDecision(postRequest(decisionBody({ summary: "  " })), "r1")).status).toBe(400);
    expect(
      (
        await proxyReviewDecision(
          postRequest(decisionBody({ verdict: "object", findings: [{ severity: "minor", path: null, text: "nit" }] })),
          "r1"
        )
      ).status
    ).toBe(400);
    expect(
      (
        await proxyReviewDecision(
          postRequest(decisionBody({ findings: [{ severity: "minor", path: "/abs", text: "t" }] })),
          "r1"
        )
      ).status
    ).toBe(400);
    const many = Array.from({ length: 33 }, () => ({ severity: "minor", path: null, text: "t" }));
    expect((await proxyReviewDecision(postRequest(decisionBody({ findings: many })), "r1")).status).toBe(400);
    expect((await proxyReviewDecision(postRequest(decisionBody({ extra: 1 })), "r1")).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects Origin mismatch, wrong content type, and oversize bodies", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect(
      (await proxyReviewDecision(postRequest(decisionBody(), { origin: "http://evil.invalid" }), "r1")).status
    ).toBe(403);
    expect(
      (await proxyReviewDecision(postRequest(decisionBody(), { contentType: "text/plain" }), "r1")).status
    ).toBe(415);
    expect(
      (await proxyReviewDecision(postRequest(decisionBody(), { contentLength: String(65 * 1024) }), "r1")).status
    ).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires the token, preserves 409, and never leaks it", async () => {
    delete process.env.XMUSE_OPERATOR_TOKEN;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyReviewDecision(postRequest(decisionBody()), "r1")).status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();

    process.env.XMUSE_OPERATOR_TOKEN = "server-secret";
    fetchMock.mockResolvedValueOnce(
      Response.json({ detail: { code: "room_board_review_digest_mismatch", message: "stale" } }, { status: 409 })
    );
    const conflict = await proxyReviewDecision(postRequest(decisionBody()), "r1");
    expect(conflict.status).toBe(409);
    expect(await conflict.text()).not.toContain("server-secret");
  });
});
