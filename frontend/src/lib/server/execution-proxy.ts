import {
  boundedText,
  exactObject,
  proxyFixedRoomWrite,
  proxyJsonError
} from "./fixed-room-proxy";

const CANDIDATE_DECISIONS = new Set(["execute", "reject"]);
const POLICY_MODES = new Set(["manual", "consensus"]);
const CANCELLABLE_RUN_STATES = new Set([
  "requested",
  "preparing",
  "staging",
  "verifying",
  "ready_to_promote"
]);

function nonnegativeInteger(value: unknown): number | null {
  return Number.isSafeInteger(value) && Number(value) >= 0 ? Number(value) : null;
}

function invalidTarget(codePrefix: string): Response {
  return proxyJsonError(400, `${codePrefix}_target_invalid`, "execution target id is invalid");
}

function invalidMethod(codePrefix: string): Response {
  return proxyJsonError(405, `${codePrefix}_method_invalid`, "HTTP method is not allowed");
}

function normalizePolicyBody(value: unknown) {
  const body = exactObject(value, ["client_action_id", "expected_revision", "mode"]);
  if (!body) return null;
  const clientActionId = boundedText(body.client_action_id);
  const mode = boundedText(body.mode);
  const expectedRevision = nonnegativeInteger(body.expected_revision);
  return clientActionId && mode && POLICY_MODES.has(mode) && expectedRevision !== null
    ? { client_action_id: clientActionId, mode, expected_revision: expectedRevision }
    : null;
}

function normalizeDecisionBody(value: unknown) {
  const body = exactObject(value, [
    "client_action_id",
    "decision",
    "expected_candidate_digest",
    "expected_candidate_revision",
    "expected_policy_revision"
  ]);
  if (!body) return null;
  const clientActionId = boundedText(body.client_action_id);
  const decision = boundedText(body.decision);
  const digest = boundedText(body.expected_candidate_digest);
  const candidateRevision = nonnegativeInteger(body.expected_candidate_revision);
  const policyRevision = nonnegativeInteger(body.expected_policy_revision);
  return clientActionId && decision && CANDIDATE_DECISIONS.has(decision) && digest
    && candidateRevision !== null && policyRevision !== null
    ? {
        client_action_id: clientActionId,
        decision,
        expected_candidate_digest: digest,
        expected_candidate_revision: candidateRevision,
        expected_policy_revision: policyRevision
      }
    : null;
}

function normalizeCancelBody(value: unknown) {
  const body = exactObject(value, [
    "client_action_id",
    "expected_run_revision",
    "expected_run_state"
  ]);
  if (!body) return null;
  const clientActionId = boundedText(body.client_action_id);
  const state = boundedText(body.expected_run_state);
  const revision = nonnegativeInteger(body.expected_run_revision);
  return clientActionId && state && CANCELLABLE_RUN_STATES.has(state) && revision !== null
    ? {
        client_action_id: clientActionId,
        expected_run_state: state,
        expected_run_revision: revision
      }
    : null;
}

export function proxyExecutionPolicy(
  request: Request,
  conversationId: string
): Promise<Response> | Response {
  if (request.method !== "PUT") return invalidMethod("room_execution_policy");
  if (!boundedText(conversationId)) return invalidTarget("room_execution_policy");
  return proxyFixedRoomWrite({
    request,
    upstreamPath: `operator/conversations/${encodeURIComponent(conversationId)}/execution-policy`,
    upstreamMethod: "PUT",
    maxBodyBytes: 8 * 1024,
    timeoutMs: 30_000,
    codePrefix: "room_execution_policy",
    normalizeBody: normalizePolicyBody
  });
}

export function proxyExecutionCandidateDecision(
  request: Request,
  candidateId: string
): Promise<Response> | Response {
  if (request.method !== "POST") return invalidMethod("room_execution_decision");
  if (!boundedText(candidateId)) return invalidTarget("room_execution_decision");
  return proxyFixedRoomWrite({
    request,
    upstreamPath: `operator/execution-candidates/${encodeURIComponent(candidateId)}/decision`,
    maxBodyBytes: 8 * 1024,
    timeoutMs: 30_000,
    codePrefix: "room_execution_decision",
    normalizeBody: normalizeDecisionBody
  });
}

export function proxyExecutionRunCancel(
  request: Request,
  runId: string
): Promise<Response> | Response {
  if (request.method !== "POST") return invalidMethod("room_execution_cancel");
  if (!boundedText(runId)) return invalidTarget("room_execution_cancel");
  return proxyFixedRoomWrite({
    request,
    upstreamPath: `operator/execution-runs/${encodeURIComponent(runId)}/cancel`,
    maxBodyBytes: 8 * 1024,
    timeoutMs: 30_000,
    codePrefix: "room_execution_cancel",
    normalizeBody: normalizeCancelBody
  });
}
