import {
  boundedText,
  exactObject,
  proxyFixedRoomWrite,
  proxyJsonError
} from "./fixed-room-proxy";

const CAPABILITIES = new Set([
  "goal_set",
  "goal_pause",
  "goal_resume",
  "goal_get",
  "goal_clear",
  "settings_update",
  "models_list",
  "console_turn_start",
  "turn_steer",
  "turn_interrupt",
  "compact_start",
  "review_start"
]);

const EMPTY_REQUEST_CAPABILITIES = new Set([
  "goal_pause",
  "goal_resume",
  "goal_get",
  "goal_clear",
  "models_list",
  "turn_interrupt",
  "compact_start"
]);

const OPAQUE_GUARD = /^sha256:[0-9a-f]{64}$/;

function utf8Text(value: unknown, maximum: number): string | null {
  const text = boundedText(value, maximum);
  return text && new TextEncoder().encode(text).byteLength <= maximum ? text : null;
}

function guard(value: unknown, required = false): string | null | undefined {
  if (value === null && !required) return null;
  if (typeof value !== "string" || !OPAQUE_GUARD.test(value)) return undefined;
  return value;
}

function normalizeSafeRequest(capability: string, value: unknown): Record<string, unknown> | null {
  if (EMPTY_REQUEST_CAPABILITIES.has(capability)) return exactObject(value, []);
  if (capability === "goal_set") {
    const request = exactObject(value, ["objective", "token_budget"]);
    if (!request) return null;
    const objective = utf8Text(request.objective, 4096);
    const tokenBudget = request.token_budget;
    return objective && Number.isSafeInteger(tokenBudget)
      && Number(tokenBudget) >= 10_000 && Number(tokenBudget) <= 1_000_000
      ? { objective, token_budget: Number(tokenBudget) }
      : null;
  }
  if (capability === "settings_update") {
    if (!value || typeof value !== "object" || Array.isArray(value)) return null;
    const request = value as Record<string, unknown>;
    const keys = Object.keys(request).sort();
    if (keys.length < 1 || keys.some((key) => key !== "effort" && key !== "model")) return null;
    const model = "model" in request ? utf8Text(request.model, 256) : null;
    const effort = "effort" in request ? utf8Text(request.effort, 64) : null;
    if (("model" in request && !model) || ("effort" in request && (!effort || effort === "ultra"))) {
      return null;
    }
    return {
      ...(model ? { model } : {}),
      ...(effort ? { effort } : {})
    };
  }
  if (capability === "console_turn_start") {
    const request = exactObject(value, ["mode", "text"]);
    if (!request) return null;
    const text = utf8Text(request.text, 4096);
    const mode = request.mode;
    return text && (mode === "default" || mode === "plan") ? { text, mode } : null;
  }
  if (capability === "turn_steer") {
    const request = exactObject(value, ["text"]);
    const text = request ? utf8Text(request.text, 4096) : null;
    return text ? { text } : null;
  }
  if (capability === "review_start") {
    const request = exactObject(value, ["target"]);
    const target = request?.target;
    return target === "uncommitted" || target === "base" || target === "commit"
      ? { target }
      : null;
  }
  return null;
}

function normalizeActionBody(value: unknown) {
  const body = exactObject(value, [
    "capability_id",
    "client_action_id",
    "confirmed_pending_observations",
    "expected_goal_guard",
    "expected_session_guard",
    "expected_settings_guard",
    "expected_turn_guard",
    "request"
  ]);
  if (!body) return null;
  const clientActionId = boundedText(body.client_action_id, 128);
  const capabilityId = boundedText(body.capability_id, 64);
  if (!clientActionId || !capabilityId || !CAPABILITIES.has(capabilityId)) return null;
  if (typeof body.confirmed_pending_observations !== "boolean") return null;
  const expectedSessionGuard = guard(body.expected_session_guard, true);
  const expectedGoalGuard = guard(body.expected_goal_guard);
  const expectedSettingsGuard = guard(body.expected_settings_guard);
  const expectedTurnGuard = guard(body.expected_turn_guard);
  if (
    expectedSessionGuard === undefined ||
    expectedGoalGuard === undefined ||
    expectedSettingsGuard === undefined ||
    expectedTurnGuard === undefined
  ) return null;
  if (
    (["goal_set", "goal_pause", "goal_resume", "goal_clear"].includes(capabilityId)
      && expectedGoalGuard === null) ||
    (capabilityId === "settings_update" && expectedSettingsGuard === null) ||
    (["turn_steer", "turn_interrupt"].includes(capabilityId) && expectedTurnGuard === null)
  ) return null;
  const request = normalizeSafeRequest(capabilityId, body.request);
  if (!request) return null;
  return {
    client_action_id: clientActionId,
    capability_id: capabilityId,
    request,
    expected_session_guard: expectedSessionGuard,
    expected_goal_guard: expectedGoalGuard,
    expected_settings_guard: expectedSettingsGuard,
    expected_turn_guard: expectedTurnGuard,
    confirmed_pending_observations: body.confirmed_pending_observations
  };
}

export function proxyCodexAction(
  request: Request,
  participantId: string
): Promise<Response> | Response {
  if (request.method !== "POST") {
    return proxyJsonError(405, "room_codex_action_method_invalid", "HTTP method is not allowed");
  }
  if (!boundedText(participantId)) {
    return proxyJsonError(400, "room_codex_action_target_invalid", "participant id is invalid");
  }
  return proxyFixedRoomWrite({
    request,
    upstreamPath: `operator/room-participants/${encodeURIComponent(participantId)}/codex-actions`,
    maxBodyBytes: 8 * 1024,
    timeoutMs: 30_000,
    codePrefix: "room_codex_action",
    normalizeBody: normalizeActionBody
  });
}
