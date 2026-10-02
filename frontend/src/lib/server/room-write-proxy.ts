import { boundedText, exactObject, proxyFixedRoomWrite } from "./fixed-room-proxy";

const PARTICIPANT_KEYS = [
  "role",
  "provider_id",
  "profile_id",
  "cli_kind",
  "model",
  "role_template_id",
  "display_name"
];

const PROVIDER_KINDS = ["codex", "claude", "antigravity", "opencode"];
const COLLABORATION_MODES = ["broadcast", "addressed"];

function optionalText(value: unknown, maximum = 200): string | null | undefined {
  if (value === undefined || value === null) return undefined;
  return boundedText(value, maximum);
}

function normalizeParticipant(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const source = value as Record<string, unknown>;
  if (Object.keys(source).some((key) => !PARTICIPANT_KEYS.includes(key))) return null;
  const role = boundedText(source.role);
  const providerId = optionalText(source.provider_id);
  const profileId = optionalText(source.profile_id);
  const cliKind = optionalText(source.cli_kind);
  const model = optionalText(source.model);
  const roleTemplateId = optionalText(source.role_template_id);
  const displayName = optionalText(source.display_name);
  if (
    !role ||
    providerId === null ||
    profileId === null ||
    cliKind === null ||
    model === null ||
    roleTemplateId === null ||
    displayName === null ||
    (providerId !== undefined && !PROVIDER_KINDS.includes(providerId)) ||
    (cliKind !== undefined && !PROVIDER_KINDS.includes(cliKind))
  ) return null;
  return {
    role,
    ...(providerId ? { provider_id: providerId } : {}),
    ...(profileId ? { profile_id: profileId } : {}),
    ...(cliKind ? { cli_kind: cliKind } : {}),
    ...(model ? { model } : {}),
    ...(roleTemplateId ? { role_template_id: roleTemplateId } : {}),
    ...(displayName ? { display_name: displayName } : {})
  };
}

function normalizeCollaboration(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const source = value as Record<string, unknown>;
  if (Object.keys(source).some((key) => key !== "mode" && key !== "lead_role")) return null;
  const mode = boundedText(source.mode, 16);
  const leadRole = optionalText(source.lead_role, 64);
  if (!mode || !COLLABORATION_MODES.includes(mode) || leadRole === null) return null;
  return {
    mode,
    ...(leadRole ? { lead_role: leadRole } : {})
  };
}

function normalizeCreateBody(value: unknown) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const source = value as Record<string, unknown>;
  const allowed = new Set([
    "title",
    "client_request_id",
    "roster_template_id",
    "initial_participants",
    "collaboration"
  ]);
  if (Object.keys(source).some((key) => !allowed.has(key))) return null;
  const title = boundedText(source.title, 200);
  const requestId = boundedText(source.client_request_id);
  const rosterTemplateId = optionalText(source.roster_template_id);
  if (!title || !requestId || rosterTemplateId === null) return null;
  const hasInitial = source.initial_participants !== undefined && source.initial_participants !== null;
  if (rosterTemplateId && hasInitial) return null;
  let participants: ReturnType<typeof normalizeParticipant>[] | undefined;
  if (hasInitial) {
    if (!Array.isArray(source.initial_participants) || !source.initial_participants.length || source.initial_participants.length > 8) return null;
    participants = source.initial_participants.map(normalizeParticipant);
    if (participants.some((item) => item === null)) return null;
  }
  let collaboration: ReturnType<typeof normalizeCollaboration> | undefined;
  if (source.collaboration !== undefined && source.collaboration !== null) {
    collaboration = normalizeCollaboration(source.collaboration);
    if (collaboration === null) return null;
  }
  return {
    title,
    client_request_id: requestId,
    ...(rosterTemplateId ? { roster_template_id: rosterTemplateId } : {}),
    ...(participants ? { initial_participants: participants } : {}),
    ...(collaboration ? { collaboration } : {})
  };
}

function normalizeMessageBody(value: unknown) {
  const body = exactObject(value, ["message", "client_request_id"]);
  if (!body) return null;
  const message = typeof body.message === "string" && body.message.trim() && body.message.length <= 40 * 1024
    ? body.message
    : null;
  const requestId = boundedText(body.client_request_id);
  return message && requestId ? { message, client_request_id: requestId } : null;
}

export function proxyRoomCreate(request: Request): Promise<Response> {
  return proxyFixedRoomWrite({
    request,
    upstreamPath: "conversations",
    maxBodyBytes: 8 * 1024,
    timeoutMs: 10_000,
    codePrefix: "room_create",
    normalizeBody: normalizeCreateBody
  });
}

export function proxyRoomMessage(request: Request, conversationId: string): Promise<Response> {
  if (!boundedText(conversationId)) {
    return Promise.resolve(Response.json(
      { detail: { code: "room_message_target_invalid", message: "conversation id is invalid" } },
      { status: 400, headers: { "Cache-Control": "no-store" } }
    ));
  }
  return proxyFixedRoomWrite({
    request,
    upstreamPath: `threads/${encodeURIComponent(conversationId)}/messages`,
    maxBodyBytes: 40 * 1024,
    timeoutMs: 20_000,
    codePrefix: "room_message",
    normalizeBody: normalizeMessageBody
  });
}
