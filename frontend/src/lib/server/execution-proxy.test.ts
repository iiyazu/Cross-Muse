import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  proxyExecutionCandidateDecision,
  proxyExecutionPolicy,
  proxyExecutionRunCancel
} from "./execution-proxy";

const policyBody = {
  client_action_id: "policy-1",
  mode: "consensus",
  expected_revision: 2
};
const decisionBody = {
  client_action_id: "decision-1",
  decision: "execute",
  expected_candidate_digest: "sha256:candidate",
  expected_candidate_revision: 4,
  expected_policy_revision: 2
};
const cancelBody = {
  client_action_id: "cancel-1",
  expected_run_state: "verifying",
  expected_run_revision: 5
};

function request(
  path: string,
  payload: unknown,
  overrides: {
    method?: string;
    origin?: string;
    host?: string;
    contentType?: string;
    contentLength?: string;
  } = {}
) {
  return new Request(`http://localhost:3000${path}`, {
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
  delete process.env.XMUSE_OPERATOR_TOKEN;
  delete process.env.XMUSE_CHAT_API_BASE_URL;
});

describe("fixed exact-patch execution proxies", () => {
  it("forwards policy PUT and action POSTs to fixed paths with the server-only token", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      Response.json({ action_id: "action-1", status: "applied" })
    );

    const policy = await proxyExecutionPolicy(
      request("/api/room-execution-policy/conv-1", policyBody, { method: "PUT" }),
      "conv/one"
    );
    expect(policy.status).toBe(200);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/conversations/conv%2Fone/execution-policy",
      expect.objectContaining({
        method: "PUT",
        cache: "no-store",
        redirect: "manual",
        headers: {
          "Content-Type": "application/json",
          "X-XMuse-Operator-Token": "server-secret"
        },
        body: JSON.stringify(policyBody)
      })
    );

    const decision = await proxyExecutionCandidateDecision(
      request("/api/room-execution-candidates/candidate-1/decision", decisionBody),
      "candidate/one"
    );
    expect(decision.status).toBe(200);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/execution-candidates/candidate%2Fone/decision",
      expect.objectContaining({ method: "POST", body: JSON.stringify(decisionBody) })
    );

    const cancel = await proxyExecutionRunCancel(
      request("/api/room-execution-runs/run-1/cancel", cancelBody),
      "run/one"
    );
    expect(cancel.status).toBe(200);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "http://127.0.0.1:8201/api/chat/operator/execution-runs/run%2Fone/cancel",
      expect.objectContaining({ method: "POST", body: JSON.stringify(cancelBody) })
    );
    expect(cancel.headers.get("cache-control")).toBe("no-store");
  });

  it("rejects method, Origin/Host, content type, body size, ids, hrefs, and extra fields", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect(proxyExecutionPolicy(
      request("/policy", policyBody, { method: "POST" }), "conv-1"
    )).toBeInstanceOf(Response);
    expect((await proxyExecutionPolicy(
      request("/policy", policyBody, { method: "PUT", origin: "http://evil.invalid" }),
      "conv-1"
    )).status).toBe(403);
    expect((await proxyExecutionCandidateDecision(
      request("/decision", decisionBody, { contentType: "text/plain" }), "candidate-1"
    )).status).toBe(415);
    expect((await proxyExecutionCandidateDecision(
      request("/decision", { ...decisionBody, href: "https://evil.invalid" }), "candidate-1"
    )).status).toBe(400);
    expect((await proxyExecutionRunCancel(
      request("/cancel", { ...cancelBody, expected_run_revision: -1 }), "run-1"
    )).status).toBe(400);
    expect((await proxyExecutionPolicy(
      request("/policy", policyBody, { method: "PUT", contentLength: "9000" }), "conv-1"
    )).status).toBe(413);
    expect((await proxyExecutionRunCancel(request("/cancel", cancelBody), " ")).status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("fails closed without token and preserves conflicts without following redirects", async () => {
    delete process.env.XMUSE_OPERATOR_TOKEN;
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect((await proxyExecutionCandidateDecision(
      request("/decision", decisionBody), "candidate-1"
    )).status).toBe(503);
    expect(fetchMock).not.toHaveBeenCalled();

    process.env.XMUSE_OPERATOR_TOKEN = "server-secret";
    fetchMock.mockResolvedValueOnce(
      Response.json({ detail: { code: "room_execution_candidate_revision_conflict" } }, { status: 409 })
    );
    expect((await proxyExecutionCandidateDecision(
      request("/decision", decisionBody), "candidate-1"
    )).status).toBe(409);

    fetchMock.mockResolvedValueOnce(
      new Response(null, { status: 307, headers: { Location: "https://evil.invalid" } })
    );
    const redirect = await proxyExecutionRunCancel(
      request("/cancel", cancelBody), "run-1"
    );
    expect(redirect.status).toBe(502);
    expect(await redirect.json()).toMatchObject({
      detail: { code: "room_execution_cancel_upstream_redirect" }
    });
  });

  it("aborts execution writes at the thirty second deadline", async () => {
    vi.useFakeTimers();
    try {
      vi.spyOn(globalThis, "fetch").mockImplementation(
        (_input, init) => new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
        })
      );
      const pending = proxyExecutionCandidateDecision(
        request("/decision", decisionBody), "candidate-1"
      );
      await vi.advanceTimersByTimeAsync(30_000);
      const response = await pending;
      expect(response.status).toBe(504);
      expect(await response.json()).toMatchObject({
        detail: { code: "room_execution_decision_upstream_timeout" }
      });
    } finally {
      vi.useRealTimers();
    }
  });
});
