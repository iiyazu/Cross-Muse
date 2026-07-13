import { describe, expect, it, vi } from "vitest";

import {
  cancelRoomExecutionRun,
  decideRoomExecutionCandidate,
  fetchRoomExecutionCandidate,
  fetchRoomExecutions,
  updateRoomExecutionPolicy
} from "./api";
import type {
  RoomExecutionCancelDescriptor,
  RoomExecutionDecisionDescriptor,
  RoomExecutionPolicyUpdateDescriptor
} from "./types";

const policyDescriptor: RoomExecutionPolicyUpdateDescriptor = {
  available: true,
  method: "PUT",
  href: "/api/chat/operator/conversations/conv%2Fone/execution-policy",
  expected_revision: 2,
  allowed_modes: ["manual", "consensus"]
};
const decisionDescriptor: RoomExecutionDecisionDescriptor = {
  available: true,
  method: "POST",
  href: "/api/chat/operator/execution-candidates/candidate%2Fone/decision",
  expected_candidate_digest: "sha256:candidate",
  expected_candidate_revision: 4,
  expected_policy_revision: 2
};
const cancelDescriptor: RoomExecutionCancelDescriptor = {
  available: true,
  method: "POST",
  href: "/api/chat/operator/execution-runs/run%2Fone/cancel",
  expected_run_state: "verifying",
  expected_run_revision: 5
};

describe("Room execution API client", () => {
  it("reads only the bounded list and explicitly selected exact diff", async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return Response.json(url.includes("execution-candidates")
        ? {
            schema_version: "room_execution_candidate_projection/v1",
            candidate: { candidate_id: "candidate-1", unified_diff: "diff --git" }
          }
        : {
            schema_version: "room_execution_list_projection/v1",
            conversation_id: "conv-1",
            candidates: []
          });
    });

    await fetchRoomExecutions("conv/one", {
      fetcher: fetcher as typeof fetch,
      chatApiBaseUrl: "http://127.0.0.1:8201/api/chat",
      limit: 99
    });
    await fetchRoomExecutionCandidate("candidate/one", {
      fetcher: fetcher as typeof fetch,
      chatApiBaseUrl: "http://127.0.0.1:8201/api/chat"
    });

    expect(fetcher.mock.calls[0][0]).toBe(
      "http://127.0.0.1:8201/api/chat/conversations/conv%2Fone/executions?limit=50"
    );
    expect(fetcher.mock.calls[1][0]).toBe(
      "http://127.0.0.1:8201/api/chat/execution-candidates/candidate%2Fone"
    );
  });

  it("sends exact guarded bodies only through fixed same-origin routes", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      Response.json({ action_id: "action", status: "applied" })
    );
    const options = { fetcher: fetcher as typeof fetch, clientActionId: "stable-action" };

    await updateRoomExecutionPolicy("conv/one", "consensus", policyDescriptor, options);
    await decideRoomExecutionCandidate("candidate/one", "execute", decisionDescriptor, options);
    await cancelRoomExecutionRun("run/one", cancelDescriptor, options);

    expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
      "/api/room-execution-policy/conv%2Fone",
      "/api/room-execution-candidates/candidate%2Fone/decision",
      "/api/room-execution-runs/run%2Fone/cancel"
    ]);
    expect(fetcher.mock.calls[0][1]).toMatchObject({
      method: "PUT",
      cache: "no-store",
      credentials: "same-origin",
      body: JSON.stringify({
        client_action_id: "stable-action",
        mode: "consensus",
        expected_revision: 2
      })
    });
    expect(fetcher.mock.calls[1][1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({
        client_action_id: "stable-action",
        decision: "execute",
        expected_candidate_digest: "sha256:candidate",
        expected_candidate_revision: 4,
        expected_policy_revision: 2
      })
    });
    expect(fetcher.mock.calls[2][1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({
        client_action_id: "stable-action",
        expected_run_state: "verifying",
        expected_run_revision: 5
      })
    });
  });

  it("rejects forged, unavailable, and mismatched descriptors before fetch", async () => {
    const fetcher = vi.fn();
    await expect(updateRoomExecutionPolicy(
      "conv/one",
      "consensus",
      { ...policyDescriptor, href: "https://evil.invalid" },
      { fetcher: fetcher as typeof fetch }
    )).rejects.toMatchObject({ code: "room_execution_policy_descriptor_invalid" });
    await expect(decideRoomExecutionCandidate(
      "candidate/one",
      "execute",
      { ...decisionDescriptor, available: false },
      { fetcher: fetcher as typeof fetch }
    )).rejects.toMatchObject({ code: "room_execution_decision_descriptor_invalid" });
    await expect(cancelRoomExecutionRun(
      "run/one",
      { ...cancelDescriptor, href: "/api/chat/operator/execution-runs/another/cancel" },
      { fetcher: fetcher as typeof fetch }
    )).rejects.toMatchObject({ code: "room_execution_cancel_descriptor_invalid" });
    expect(fetcher).not.toHaveBeenCalled();
  });
});
