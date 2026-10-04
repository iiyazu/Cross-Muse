import fs from "node:fs";
import path from "node:path";
import { describe, expect, it, vi } from "vitest";

import {
  fetchBoardContract,
  fetchRoomBoard,
  fetchRoomBoardSummary,
  normalizeBoardContract,
  normalizeBoardSummary,
  normalizeRoomBoardProjection
} from "./board-api";

const FIXTURE_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");

function fixtures(): Array<{ name: string; payload: Record<string, unknown> }> {
  return fs
    .readdirSync(FIXTURE_DIR)
    .filter((name) => name.endsWith(".json"))
    .map((name) => ({
      name,
      payload: JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8")) as Record<
        string,
        unknown
      >
    }));
}

describe("board API normalizers", () => {
  it("normalizes every golden fixture projection and summary without throwing", () => {
    for (const { name, payload } of fixtures()) {
      expect(() => normalizeRoomBoardProjection(payload.projection), name).not.toThrow();
      expect(() => normalizeBoardSummary(payload.summary), name).not.toThrow();
      const projection = normalizeRoomBoardProjection(payload.projection);
      expect(projection.schema_version).toBe("room_board_projection/v2");
      expect(Array.isArray(projection.modules)).toBe(true);
    }
  });

  it("tolerates unknown enum values and extra fields", () => {
    const { payload } = fixtures().find((item) => item.name === "verified.json")!;
    const raw = JSON.parse(JSON.stringify(payload.projection)) as Record<string, unknown>;
    (raw as Record<string, unknown>).extra_top_level = { unexpected: true };
    const modules = raw.modules as Array<Record<string, unknown>>;
    modules[0].state = "future_state";
    modules[0].lifecycle = "future_lifecycle";
    (modules[0].verification as Record<string, unknown>).status = "future_status";
    (raw.events as Array<Record<string, unknown>>).push({
      seq: 999,
      kind: "future_kind",
      at: "2026-10-04T12:00:00Z",
      module_id: null,
      actor: { kind: "participant", participant_id: "p1" },
      data: { anything: true }
    });
    const projection = normalizeRoomBoardProjection(raw);
    expect(projection.modules[0].state).toBe("unknown");
    expect(projection.modules[0].lifecycle).toBe("unknown");
    expect(projection.modules[0].verification.status).toBe("unknown");
    expect(projection.events.at(-1)?.typedKind).toBe("unknown");
  });

  it("parses Split.actions.decide when present and tolerates its absence", () => {
    const { payload } = fixtures().find((item) => item.name === "split_pending.json")!;
    const without = normalizeRoomBoardProjection(payload.projection);
    expect(without.splits[0].actions).toBeUndefined();
    const raw = JSON.parse(JSON.stringify(payload.projection)) as Record<string, unknown>;
    const split = (raw.splits as Array<Record<string, unknown>>)[0];
    split.actions = {
      decide: {
        available: true,
        method: "POST",
        href: "/api/chat/operator/board-splits/split_1/decision",
        expected_digest: "sha256:abc",
        allowed_decisions: ["approve", "reject"]
      }
    };
    const withDecide = normalizeRoomBoardProjection(raw);
    expect(withDecide.splits[0].actions?.decide?.available).toBe(true);
    expect(withDecide.splits[0].actions?.decide?.allowed_decisions).toEqual([
      "approve",
      "reject"
    ]);
  });

  it("throws a typed error only for an unusable envelope", () => {
    expect(() => normalizeRoomBoardProjection(null)).toThrow();
    expect(() => normalizeRoomBoardProjection("nope")).toThrow();
    expect(() =>
      normalizeRoomBoardProjection({
        schema_version: "room_board_projection/v3",
        conversation_id: "c"
      })
    ).toThrow();
    expect(() => normalizeBoardSummary({ schema_version: "room_board_summary/v2" })).toThrow();
    expect(() => normalizeBoardContract({ schema_version: "room_board_contract/v1" })).toThrow();
  });
});

describe("board API fetchers", () => {
  it("uses no-store GET with encoded ids for board and summary", async () => {
    const summaryPayload = {
      schema_version: "room_board_summary/v1",
      conversation_id: "conv/one",
      server_time: "2026-10-04T12:00:00Z",
      board_seq: 1,
      revision: "1:abc",
      capabilities: { verification: 1, reviews: 0, integrations: 0, lessons: 0 },
      modules_total: 0,
      counts: {
        assigned: 0,
        claimed: 0,
        working: 0,
        blocked: 0,
        ready_for_review: 0,
        done_claimed: 0,
        verifying: 0,
        waiting_for_provider: 0,
        verified: 0,
        verification_failed: 0,
        verification_error: 0
      },
      attention_total: 0,
      attention: []
    };
    const projectionPayload = {
      schema_version: "room_board_projection/v2",
      metrics_version: "board_metrics/v1",
      conversation_id: "conv/one",
      server_time: "2026-10-04T12:00:00Z",
      board_seq: 1,
      revision: "1:abc",
      capabilities: { verification: 1, reviews: 0, integrations: 0, lessons: 0 },
      participants: [],
      modules: [],
      contracts: [],
      splits: [],
      stale_dependents: [],
      attention: [],
      events: []
    };
    const fetcher = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = String(input);
      void _init;
      return Response.json(url.includes("/board/summary") ? summaryPayload : projectionPayload);
    });
    const options = {
      fetcher: fetcher as typeof fetch,
      chatApiBaseUrl: "http://127.0.0.1:8201/api/chat"
    };
    await fetchRoomBoardSummary("conv/one", options);
    await fetchRoomBoard("conv/one", options);
    const calls = fetcher.mock.calls as unknown as Array<[string, RequestInit?]>;
    expect(calls[0][0]).toBe(
      "http://127.0.0.1:8201/api/chat/conversations/conv%2Fone/board/summary"
    );
    expect(calls[1][0]).toBe(
      "http://127.0.0.1:8201/api/chat/conversations/conv%2Fone/board"
    );
    for (const call of calls) {
      expect(call[1]).toMatchObject({ method: "GET", cache: "no-store" });
    }
  });

  it("encodes contract ids and passes the version query", async () => {
    const fetcher = vi.fn(async () =>
      Response.json({
        schema_version: "room_board_contract/v2",
        conversation_id: "conv-1",
        contract_id: "api/one",
        provider_module_id: "alpha",
        kind: "api_schema",
        versions: [],
        version: 2,
        content: { text: "hello", untrusted: true, truncated: false }
      })
    );
    await fetchBoardContract("conv/1", "api/one", {
      fetcher: fetcher as typeof fetch,
      chatApiBaseUrl: "http://127.0.0.1:8201/api/chat",
      version: 2
    });
    const calls = fetcher.mock.calls as unknown as Array<[string, RequestInit?]>;
    expect(calls[0][0]).toBe(
      "http://127.0.0.1:8201/api/chat/conversations/conv%2F1/board/contracts/api%2Fone?version=2"
    );
    expect(calls[0][1]).toMatchObject({ method: "GET", cache: "no-store" });
  });
});
