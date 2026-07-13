import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { proxyCodexAction } from "./codex-action-proxy";

const guard = (value: string) => `sha256:${value.repeat(64)}`;
const baseBody = {
  client_action_id: "codex-action-1",
  capability_id: "goal_get",
  request: {},
  expected_session_guard: guard("a"),
  expected_goal_guard: guard("b"),
  expected_settings_guard: guard("c"),
  expected_turn_guard: null,
  confirmed_pending_observations: false
};

function request(
  payload: unknown = baseBody,
  overrides: {
    method?: string;
    origin?: string;
    host?: string;
    contentType?: string;
    contentLength?: string;
  } = {}
) {
  return new Request("http://localhost:3000/api/room-participants/participant-1/codex-actions", {
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
  vi.useRealTimers();
  vi.restoreAllMocks();
  delete process.env.XMUSE_OPERATOR_TOKEN;
  delete process.env.XMUSE_CHAT_API_BASE_URL;
});

describe("fixed native Codex action proxy", () => {
  it("forwards the exact validated action to the encoded fixed route", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      Response.json({
        action_id: "action-1",
        status: "requested",
        proof_boundary: "operator_action_receipt_not_codex_or_room_authority"
      })
    );

    const response = await proxyCodexAction(request(), "participant/one");

    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/room-participants/participant%2Fone/codex-actions",
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        redirect: "manual",
        headers: {
          "Content-Type": "application/json",
          "X-XMuse-Operator-Token": "server-secret"
        },
        body: JSON.stringify(baseBody)
      })
    );
  });

  it.each([
    ["goal_set", { objective: "Finish the native goal", token_budget: 10_000 }],
    ["goal_pause", {}],
    ["goal_resume", {}],
    ["goal_get", {}],
    ["goal_clear", {}],
    ["settings_update", { model: "gpt-5.6-sol", effort: "max" }],
    ["models_list", {}],
    ["console_turn_start", { text: "Inspect this", mode: "plan" }],
    ["turn_steer", { text: "Focus on the failing contract" }],
    ["turn_interrupt", {}],
    ["compact_start", {}],
    ["review_start", { target: "uncommitted" }]
  ])("accepts the safe %s request shape", async (capabilityId, safeRequest) => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({}));
    const needsTurnGuard = capabilityId === "turn_steer" || capabilityId === "turn_interrupt";
    const response = await proxyCodexAction(
      request({
        ...baseBody,
        capability_id: capabilityId,
        request: safeRequest,
        expected_turn_guard: needsTurnGuard ? guard("d") : null
      }),
      "participant-1"
    );
    expect(response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it.each([
    [{ ...baseBody, href: "https://evil.invalid" }],
    [{ ...baseBody, capability_id: "raw_rpc" }],
    [{ ...baseBody, expected_session_guard: "thread-private" }],
    [{ ...baseBody, request: { raw_params: {} } }],
    [{ ...baseBody, capability_id: "settings_update", request: { effort: "ultra" } }],
    [{ ...baseBody, capability_id: "goal_set", request: { objective: "x", token_budget: 9_999 } }],
    [{ ...baseBody, capability_id: "console_turn_start", request: { text: "x", mode: "danger" } }],
    [{ ...baseBody, capability_id: "review_start", request: { target: "custom" } }]
  ])("rejects unsafe or non-exact payload %# before fetch", async (payload) => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyCodexAction(request(payload), "participant-1")).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it.each([
    ["goal_set", "expected_goal_guard", { objective: "Ship", token_budget: 10_000 }],
    ["settings_update", "expected_settings_guard", { model: "gpt-5.6-sol" }],
    ["turn_interrupt", "expected_turn_guard", {}]
  ])("rejects %s without its capability guard", async (capabilityId, guardKey, safeRequest) => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const response = await proxyCodexAction(
      request({
        ...baseBody,
        capability_id: capabilityId,
        request: safeRequest,
        [guardKey]: null
      }),
      "participant-1"
    );
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects method, target, Origin/Host, content type, and both advertised and streamed oversize", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyCodexAction(request(baseBody, { method: "PUT" }), "participant-1")).status).toBe(405);
    expect((await proxyCodexAction(request(), " ")).status).toBe(400);
    expect((await proxyCodexAction(request(baseBody, { origin: "http://evil.invalid" }), "participant-1")).status).toBe(403);
    expect((await proxyCodexAction(request(baseBody, { host: "127.0.0.1:3000" }), "participant-1")).status).toBe(403);
    expect((await proxyCodexAction(request(baseBody, { contentType: "text/plain" }), "participant-1")).status).toBe(415);
    expect((await proxyCodexAction(request(baseBody, { contentLength: "9000" }), "participant-1")).status).toBe(413);
    const streamedOversize = {
      ...baseBody,
      capability_id: "console_turn_start",
      request: { text: "x".repeat(8_300), mode: "default" }
    };
    expect((await proxyCodexAction(request(streamedOversize), "participant-1")).status).toBe(413);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails closed without the server token and preserves conflict responses", async () => {
    delete process.env.XMUSE_OPERATOR_TOKEN;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyCodexAction(request(), "participant-1")).status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();

    process.env.XMUSE_OPERATOR_TOKEN = "server-secret";
    fetchMock.mockResolvedValueOnce(
      Response.json({ detail: { code: "codex_native_goal_guard_conflict" } }, { status: 409 })
    );
    const conflict = await proxyCodexAction(request(), "participant-1");
    expect(conflict.status).toBe(409);
    expect(await conflict.json()).toMatchObject({
      detail: { code: "codex_native_goal_guard_conflict" }
    });
  });

  it("rejects upstream redirects and aborts at the thirty second deadline", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(null, { status: 307, headers: { Location: "https://evil.invalid" } })
    );
    const redirect = await proxyCodexAction(request(), "participant-1");
    expect(redirect.status).toBe(502);
    expect(await redirect.json()).toMatchObject({
      detail: { code: "room_codex_action_upstream_redirect" }
    });

    vi.useFakeTimers();
    fetchMock.mockImplementationOnce(
      (_input, init) => new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      })
    );
    const pending = proxyCodexAction(request(), "participant-1");
    await vi.advanceTimersByTimeAsync(30_000);
    const timeout = await pending;
    expect(timeout.status).toBe(504);
    expect(await timeout.json()).toMatchObject({
      detail: { code: "room_codex_action_upstream_timeout" }
    });
  });
});
