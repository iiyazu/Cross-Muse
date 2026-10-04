import {
  boundedText,
  exactObject,
  proxyFixedRoomWrite,
  proxyJsonError
} from "./fixed-room-proxy";

const DECISIONS = new Set(["approve", "reject"]);
const DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;

function normalizeDecisionBody(value: unknown) {
  const body = exactObject(value, ["conversation_id", "decision", "expected_digest"]);
  if (!body) return null;
  const conversationId = boundedText(body.conversation_id);
  const decision = boundedText(body.decision);
  const expectedDigest = boundedText(body.expected_digest, 128);
  return conversationId && decision && DECISIONS.has(decision) && expectedDigest
      && DIGEST_PATTERN.test(expectedDigest)
    ? {
        conversation_id: conversationId,
        decision,
        expected_digest: expectedDigest,
        decided_via: "web"
      }
    : null;
}

export function proxyBoardSplitDecision(
  request: Request,
  splitId: string
): Promise<Response> | Response {
  if (request.method !== "POST") {
    return proxyJsonError(
      405,
      "room_board_split_decision_method_invalid",
      "HTTP method is not allowed"
    );
  }
  if (!boundedText(splitId)) {
    return proxyJsonError(
      400,
      "room_board_split_decision_target_invalid",
      "board split id is invalid"
    );
  }
  return proxyFixedRoomWrite({
    request,
    upstreamPath: `operator/board-splits/${encodeURIComponent(splitId)}/decision`,
    maxBodyBytes: 8 * 1024,
    timeoutMs: 30_000,
    codePrefix: "room_board_split_decision",
    normalizeBody: normalizeDecisionBody
  });
}
