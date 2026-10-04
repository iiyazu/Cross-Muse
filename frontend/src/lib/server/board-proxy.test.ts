import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { proxyBoardSplitDecision } from "./board-proxy";

const DIGEST = `sha256:${"b".repeat(64)}`;

function body(overrides: Record<string, unknown> = {}) {
  return {
    conversation_id: "conv-1",
    decision: "approve",
    expected_digest: DIGEST,
    ...overrides
  };
}

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
  const upper = (overrides.method ?? "POST").toUpperCase();
  return new Request("http://localhost:3000/api/room-board-splits/split-1/decision", {
    method: overrides.method ?? "POST",
    headers: {
      Host: overrides.host ?? "localhost:3000",
      Origin: overrides.origin ?? "http://localhost:3000",
      "Content-Type": overrides.contentType ?? "application/json",
      ...(overrides.contentLength ? { "Content-Length": overrides.contentLength } : {})
    },
    body: upper === "GET" || upper === "HEAD" ? undefined : JSON.stringify(payload)
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

describe("fixed Room board split decision proxy", () => {
  it("forwards the decision with the server token and proxy-set decided_via", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({ split_id: "split-1", status: "approved" })
    );

    const response = await proxyBoardSplitDecision(request(body()), "split/one");

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/board-splits/split%2Fone/decision",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        redirect: "manual",
        headers: {
          "Content-Type": "application/json",
          "X-XMuse-Operator-Token": "server-secret"
        },
        body: JSON.stringify({ ...body(), decided_via: "web" })
      })
    );
    const serialized = await response.text();
    expect(serialized).not.toContain("server-secret");
  });

  it("rejects a browser-set decided_via and other invalid payloads", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect(
      (await proxyBoardSplitDecision(request(body({ decided_via: "cli" })), "split-1")).status
    ).toBe(400);
    expect(
      (await proxyBoardSplitDecision(request(body({ decision: "maybe" })), "split-1")).status
    ).toBe(400);
    expect(
      (await proxyBoardSplitDecision(request(body({ expected_digest: "sha256:xyz" })), "split-1"))
        .status
    ).toBe(400);
    expect(
      (await proxyBoardSplitDecision(request(body({ extra: "nope" })), "split-1")).status
    ).toBe(400);
    expect(
      (await proxyBoardSplitDecision(request(body(), { method: "GET" }), "split-1")).status
    ).toBe(405);
    expect((await proxyBoardSplitDecision(request(body()), " ")).status).toBe(400);
    expect(
      (await proxyBoardSplitDecision(request(body(), { origin: "http://evil.invalid" }), "split-1"))
        .status
    ).toBe(403);
    expect(
      (await proxyBoardSplitDecision(request(body(), { contentType: "text/plain" }), "split-1"))
        .status
    ).toBe(415);
    expect(
      (await proxyBoardSplitDecision(request(body(), { contentLength: "9000" }), "split-1")).status
    ).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("requires the server token, preserves 409, and never leaks the token", async () => {
    delete process.env.XMUSE_OPERATOR_TOKEN;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyBoardSplitDecision(request(body()), "split-1")).status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();

    process.env.XMUSE_OPERATOR_TOKEN = "server-secret";
    fetchMock.mockResolvedValueOnce(
      Response.json(
        { detail: { code: "room_board_split_digest_mismatch", message: "stale digest" } },
        { status: 409 }
      )
    );
    const conflict = await proxyBoardSplitDecision(request(body()), "split-1");
    expect(conflict.status).toBe(409);
    expect(await conflict.text()).not.toContain("server-secret");

    fetchMock.mockResolvedValueOnce(
      new Response(null, { status: 307, headers: { Location: "https://evil.invalid" } })
    );
    const redirect = await proxyBoardSplitDecision(request(body()), "split-1");
    expect(redirect.status).toBe(502);
    expect(await redirect.text()).not.toContain("server-secret");
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
    const pending = proxyBoardSplitDecision(request(body()), "split-1");
    await vi.advanceTimersByTimeAsync(30_000);
    const response = await pending;
    expect(response.status).toBe(504);
    expect(await response.json()).toMatchObject({
      detail: { code: "room_board_split_decision_upstream_timeout" }
    });
  });
});
