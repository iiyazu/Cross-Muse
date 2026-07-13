import { boundedText, exactObject, proxyFixedRoomWrite } from "./fixed-room-proxy";

function normalizeRecoverBody(value: unknown) {
  const body = exactObject(value, ["client_action_id", "expected_incident_id"]);
  if (!body) return null;
  const clientActionId = boundedText(body.client_action_id);
  const incidentId = boundedText(body.expected_incident_id);
  return clientActionId && incidentId
    ? { client_action_id: clientActionId, expected_incident_id: incidentId }
    : null;
}

export function proxyRuntimeRecover(request: Request): Promise<Response> {
  return proxyFixedRoomWrite({
    request,
    upstreamPath: "operator/room-runtime/recover",
    maxBodyBytes: 8 * 1024,
    timeoutMs: 30_000,
    codePrefix: "room_runtime_recover",
    normalizeBody: normalizeRecoverBody
  });
}
