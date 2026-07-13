import { boundedText, exactObject, proxyFixedRoomWrite } from "./fixed-room-proxy";

const CONTROL_STATES = new Set([
  "active",
  "cancel_requested",
  "cancel_pending",
  "cancelled",
  "exhausted"
]);

type RoomControlAction = "cancel" | "retry";

function normalizeControlBody(value: unknown) {
  const body = exactObject(value, [
    "client_action_id",
    "expected_attempt_count",
    "expected_control_seq",
    "expected_state"
  ]);
  if (!body) return null;
  const clientActionId = boundedText(body.client_action_id);
  const expectedState = boundedText(body.expected_state);
  if (
    !clientActionId ||
    !expectedState ||
    !CONTROL_STATES.has(expectedState) ||
    !Number.isSafeInteger(body.expected_attempt_count) ||
    Number(body.expected_attempt_count) < 0 ||
    !Number.isSafeInteger(body.expected_control_seq) ||
    Number(body.expected_control_seq) < 0
  ) return null;
  return {
    client_action_id: clientActionId,
    expected_state: expectedState,
    expected_attempt_count: Number(body.expected_attempt_count),
    expected_control_seq: Number(body.expected_control_seq)
  };
}

export async function proxyRoomControl(
  request: Request,
  observationId: string,
  action: RoomControlAction
): Promise<Response> {
  if (!boundedText(observationId)) {
    return Response.json(
      { detail: { code: "room_control_target_invalid", message: "observation id is invalid" } },
      { status: 400, headers: { "Cache-Control": "no-store" } }
    );
  }
  return proxyFixedRoomWrite({
    request,
    upstreamPath: `operator/room-observations/${encodeURIComponent(observationId)}/${action}`,
    maxBodyBytes: 8 * 1024,
    timeoutMs: 15_000,
    codePrefix: "room_control",
    normalizeBody: normalizeControlBody
  });
}
