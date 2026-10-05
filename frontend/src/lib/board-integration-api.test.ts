import fs from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";

import { normalizeBoardSummary, normalizeRoomBoardProjection } from "./board-api";
import {
  escapeInvalidIntegrationPath,
  fetchBoardIntegrationDetail,
  normalizeBoardIntegrationDetail,
  normalizeBoardModuleIntegration,
  normalizeBoardSummaryIntegration,
  normalizeRoomIntegration
} from "./board-integration-api";
import { isValidReviewPath } from "./board-review-api";

const FIXTURE_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");

function scenarioNames(): string[] {
  return fs
    .readdirSync(FIXTURE_DIR)
    .filter((name) => name.endsWith(".json") && !name.slice(0, -".json".length).includes("."))
    .map((name) => name.replace(/\.json$/, ""));
}

function scenarioPayload(name: string): { projection: unknown; summary: unknown } {
  return JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, `${name}.json`), "utf8")) as {
    projection: unknown;
    summary: unknown;
  };
}

function integrationPayload(name: string): unknown {
  return JSON.parse(
    fs.readFileSync(path.join(FIXTURE_DIR, `${name}.integration.json`), "utf8")
  ) as unknown;
}

describe("integration detail goldens", () => {
  it("parses every .integration.json golden with known item/gate statuses", () => {
    const files = fs.readdirSync(FIXTURE_DIR).filter((name) => name.endsWith(".integration.json"));
    expect(files.length).toBeGreaterThan(0);
    for (const name of files) {
      const payload = JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8"));
      const detail = normalizeBoardIntegrationDetail(payload);
      expect(detail.schema_version, name).toBe("room_board_integration/v1");
      expect(detail.integration_id, name).toBeTruthy();
      for (const item of detail.items) {
        expect(item.status, `${name}:${item.module_id}`).not.toBe("unknown");
        expect(item.statusRaw, `${name}:${item.module_id}`).toBeNull();
        expect(item.role, `${name}:${item.module_id}`).not.toBe("unknown");
        for (const conflict of item.conflicts) {
          expect(isValidReviewPath(conflict.path), `${name}:${conflict.path}`).toBe(true);
        }
      }
      for (const gate of detail.gates) {
        expect(gate.status, `${name}:${gate.gate_id}`).not.toBe("unknown");
        expect(gate.statusRaw, `${name}:${gate.gate_id}`).toBeNull();
      }
    }
  });

  it("keeps integration data on every scenario projection and summary", () => {
    for (const name of scenarioNames()) {
      const { projection, summary } = scenarioPayload(name);
      const parsed = normalizeRoomBoardProjection(projection);
      expect(parsed.integration, name).toBeTruthy();
      for (const boardModule of parsed.modules) {
        expect(boardModule.integration, `${name}:${boardModule.module_id}`).toBeTruthy();
      }
      const parsedSummary = normalizeBoardSummary(summary);
      expect(typeof parsedSummary.integrated_total, name).toBe("number");
      expect(parsedSummary.integration, name).toBeTruthy();
    }
  });

  it("matches the fallback scenario: m1 conflicted at an older integrated version", () => {
    const { projection, summary } = scenarioPayload("integration_fallback_to_incumbent");
    const parsed = normalizeRoomBoardProjection(projection);
    const m1 = parsed.modules.find((item) => item.module_id === "m1")!;
    expect(m1.integration.status).toBe("conflicted");
    expect(m1.integration.integrated_verification_id).toBeTruthy();
    expect(m1.integration.integrated_verification_id).not.toBe(m1.verification.verification_id);
    expect(m1.integration.conflict_path_count).toBe(1);
    const parsedSummary = normalizeBoardSummary(summary);
    expect(parsedSummary.accepted_total).toBe(3);
    expect(parsedSummary.integrated_total).toBe(2);
  });
});

describe("integration normalizers", () => {
  it("falls back to the none values when the module object is missing", () => {
    expect(normalizeBoardModuleIntegration(undefined).status).toBe("none");
    expect(normalizeBoardModuleIntegration(null).status).toBe("none");
    expect(normalizeBoardModuleIntegration({}).status).toBe("unknown");
  });

  it("keeps unknown enum values instead of throwing", () => {
    const moduleIntegration = normalizeBoardModuleIntegration({ status: "future_status" });
    expect(moduleIntegration.status).toBe("unknown");
    expect(moduleIntegration.statusRaw).toBe("future_status");

    const roomIntegration = normalizeRoomIntegration({
      green_head_commit: null,
      latest: {
        integration_id: "job-1",
        status: "future_job",
        reason_code: null,
        module_count: 1,
        finished_at: null
      }
    });
    expect(roomIntegration.latest?.status).toBe("unknown");
    expect(roomIntegration.latest?.statusRaw).toBe("future_job");

    expect(normalizeRoomIntegration(undefined)).toEqual({
      green_head_commit: null,
      latest: null
    });
    expect(normalizeBoardSummaryIntegration(undefined)).toEqual({
      status: null,
      statusRaw: null,
      green_head_commit: null
    });

    const detail = normalizeBoardIntegrationDetail({
      schema_version: "room_board_integration/v1",
      conversation_id: "conv-1",
      integration_id: "job-1",
      status: "future_job",
      reason_code: null,
      green_head_commit: null,
      result_commit: null,
      items: [
        {
          module_id: "m1",
          verification_id: "v1",
          order: 1,
          role: "future_role",
          status: "future_item",
          applied_verification_id: null,
          conflicts: [],
          conflicts_total: 0
        }
      ],
      gates: [
        {
          gate_id: "g1",
          status: "future_gate",
          exit_code: null,
          reason_code: null,
          output_tail: null
        }
      ],
      attempt_count: 0,
      created_at: "2026-10-04T12:00:00Z",
      finished_at: null
    });
    expect(detail.status).toBe("unknown");
    expect(detail.statusRaw).toBe("future_job");
    expect(detail.items[0].role).toBe("unknown");
    expect(detail.items[0].status).toBe("unknown");
    expect(detail.gates[0].status).toBe("unknown");
  });

  it("rejects a wrong integration schema with a typed 422 error", () => {
    expect(() => normalizeBoardIntegrationDetail(null)).toThrow();
    expect(() =>
      normalizeBoardIntegrationDetail({ schema_version: "room_board_integration/v2" })
    ).toThrow();
  });

  it("sanitizes output tails as untrusted agent text", () => {
    const detail = normalizeBoardIntegrationDetail({
      schema_version: "room_board_integration/v1",
      conversation_id: "conv-1",
      integration_id: "job-1",
      status: "gate_failed",
      reason_code: "board_integration_gate_failed",
      green_head_commit: null,
      result_commit: null,
      items: [],
      gates: [
        {
          gate_id: "g1",
          status: "failed",
          exit_code: 1,
          reason_code: "execution_gate_failed",
          output_tail: { text: "oops‪tail", untrusted: true, truncated: false }
        }
      ],
      attempt_count: 1,
      created_at: "2026-10-04T12:00:00Z",
      finished_at: "2026-10-04T12:00:00Z"
    });
    const tail = detail.gates[0].output_tail!;
    expect(tail.untrusted).toBe(true);
    expect(tail.text).not.toContain("‪");
    expect(tail.text).toContain("oops");
  });

  it("escapes rejected code units of invalid paths as <U+XXXX>", () => {
    expect(escapeInvalidIntegrationPath("docs/a.txt")).toBe("docs/a.txt");
    expect(escapeInvalidIntegrationPath("src/‪b.py")).toBe("src/<U+202A>b.py");
    expect(escapeInvalidIntegrationPath("a\\b")).toBe("a<U+005C>b");
    expect(isValidReviewPath("src/‪b.py")).toBe(false);
  });

  it("fetches integration detail through the public read path", async () => {
    const payload = integrationPayload("integration_fallback_to_incumbent");
    const fetcher = vi.fn(async () => Response.json(payload));
    const detail = await fetchBoardIntegrationDetail("conv/1", "job/1", {
      fetcher: fetcher as typeof fetch,
      chatApiBaseUrl: "http://127.0.0.1:8201/api/chat"
    });
    expect(detail.schema_version).toBe("room_board_integration/v1");
    const calls = fetcher.mock.calls as unknown as Array<[string, RequestInit?]>;
    expect(calls[0][0]).toBe(
      "http://127.0.0.1:8201/api/chat/conversations/conv%2F1/board/integrations/job%2F1"
    );
    expect(calls[0][1]).toMatchObject({ method: "GET", cache: "no-store" });
  });
});
