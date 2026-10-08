import {
  chatApiBaseUrl,
  fetchJson,
  XmuseApiError,
  type ApiClientOptions
} from "./api";
import { normalizeBoardGate } from "./board-integration-api";
import type { BoardIntegrationGate } from "./board-integration-types";

const VERIFICATION_SCHEMA = "room_board_verification/v1";

/**
 * §5.2 verification detail: which gates the host ran on a `done` report and how they ended.
 * Web only: `output_tail` is scrubbed agent-reachable output, so host plugins never read it.
 */
export type BoardVerificationDetail = {
  verification_id: string;
  module_id: string;
  status: string;
  reason_code: string | null;
  head_commit: string | null;
  changed_path_count: number;
  gates: BoardIntegrationGate[];
  updated_at: string | null;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function optionalString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

export function normalizeBoardVerificationDetail(payload: unknown): BoardVerificationDetail {
  if (!isRecord(payload) || payload.schema_version !== VERIFICATION_SCHEMA) {
    throw new XmuseApiError({
      code: "room_board_verification_schema_unsupported",
      message: "Board verification response is unusable",
      retryable: false,
      status: 422
    });
  }
  const count = payload.changed_path_count;
  return {
    verification_id: optionalString(payload.verification_id) ?? "",
    module_id: optionalString(payload.module_id) ?? "",
    status: optionalString(payload.status) ?? "unknown",
    reason_code: optionalString(payload.reason_code),
    head_commit: optionalString(payload.head_commit),
    changed_path_count: typeof count === "number" && Number.isSafeInteger(count) && count >= 0 ? count : 0,
    gates: Array.isArray(payload.gates)
      ? payload.gates.flatMap((item) => {
          const gate = normalizeBoardGate(item);
          return gate ? [gate] : [];
        })
      : [],
    updated_at: optionalString(payload.updated_at)
  };
}

export async function fetchBoardVerificationDetail(
  conversationId: string,
  verificationId: string,
  options: ApiClientOptions = {}
): Promise<BoardVerificationDetail> {
  const raw = await fetchJson<unknown>(
    `${chatApiBaseUrl(options)}/conversations/${encodeURIComponent(
      conversationId
    )}/board/verifications/${encodeURIComponent(verificationId)}`,
    { method: "GET", cache: "no-store" },
    options
  );
  return normalizeBoardVerificationDetail(raw);
}
