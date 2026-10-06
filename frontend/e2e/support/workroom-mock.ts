import fs from "node:fs";
import path from "node:path";
import type { Page, Route } from "@playwright/test";

/**
 * Serves the Chat API from fixtures so the UI specs run without a backend (CI has none).
 * Room, operations, execution and memory payloads were captured from the real chat API
 * (portfolio-notes/tools/board_demo.py); board payloads are the contract's golden fixtures.
 */
export const ROOM_ID = "conv_00000000000000000000000000000001";
const API = "http://127.0.0.1:8201/api/chat";
const BOARD_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");
const ROOM_DIR = path.resolve(process.cwd(), "e2e/fixtures/workroom");

const corsHeaders = {
  "Access-Control-Allow-Headers": "Content-Type, If-None-Match",
  "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
  "Access-Control-Allow-Origin": "http://127.0.0.1:3210",
  "Cache-Control": "no-store",
  "Content-Type": "application/json"
};

type Json = Record<string, unknown>;

function readJson(file: string): Json {
  return JSON.parse(fs.readFileSync(file, "utf8")) as Json;
}

function boardFile(scenario: string, suffix = ""): string {
  return path.join(BOARD_DIR, `${scenario}${suffix}.json`);
}

async function fulfill(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, headers: corsHeaders, body: JSON.stringify(body) });
}

export type Recorded = { url: string; method: string; body: unknown };

export type WorkroomOptions = {
  /** Golden board scenario (docs/contracts/fixtures/board_v2), or null for a room without a board. */
  board?: string | null;
  /** Extra timeline items appended after the captured ones. */
  timeline?: Json[];
  /** Replace the captured runtime operations (healthy by default). */
  operations?: (captured: Json) => Json;
};

/** Synthetic agent speech for timeline specs; ids are fixed so selectors are stable. */
export function agentMessage(seq: number, participantId: string, name: string, content: string, extra: Json = {}): Json {
  return {
    id: `item_${seq}`,
    room_seq: seq,
    kind: "message",
    activity_id: `activity_${seq}`,
    activity_type: "message.posted",
    message_id: `msg_${seq}`,
    actor: { participant_id: participantId, identity: `agent:${participantId}`, role: "builder", display_name: name, kind: "agent" },
    content,
    created_at: `2026-10-06T04:3${seq % 10}:00Z`,
    proof_boundary: "durable_room_activity",
    ...extra
  };
}

export function healthyOperations(captured: Json): Json {
  const runtime = captured.runtime as Json;
  return {
    ...captured,
    overall: "healthy",
    incident_total: 0,
    incidents: [],
    runtime: {
      ...runtime,
      runner: { state: "healthy", code: null },
      mcp: { state: "healthy", code: null },
      host: { ...(runtime.host as Json), state: "healthy", code: null }
    }
  };
}

export async function installWorkroom(page: Page, options: WorkroomOptions = {}): Promise<Recorded[]> {
  const recorded: Recorded[] = [];
  const board = options.board === undefined ? "integration_fallback_to_incumbent" : options.board;
  const roomProjection = readJson(path.join(ROOM_DIR, "room-projection.json"));
  if (options.timeline?.length) {
    roomProjection.timeline_items = [...(roomProjection.timeline_items as Json[]), ...options.timeline];
    roomProjection.latest_visible_room_seq = Math.max(...options.timeline.map((item) => Number(item.room_seq)));
  }
  const capturedOperations = readJson(path.join(ROOM_DIR, "operations.json"));
  const operations = (options.operations ?? healthyOperations)(capturedOperations);
  const boardPayload = board ? readJson(boardFile(board)) : null;

  await page.route(`${API}/**`, async (route) => {
    const request = route.request();
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders });
      return;
    }
    const { pathname } = new URL(request.url());
    const rest = pathname.slice("/api/chat".length);
    const room = `/conversations/${ROOM_ID}`;
    if (rest === "/rooms") return fulfill(route, readJson(path.join(ROOM_DIR, "rooms.json")));
    if (rest === "/room-setup-options") return fulfill(route, readJson(path.join(ROOM_DIR, "setup-options.json")));
    if (rest === "/runtime/operations") return fulfill(route, operations);
    if (rest === `${room}/room-projection`) return fulfill(route, roomProjection);
    if (rest === `${room}/events`) return fulfill(route, { ...readJson(path.join(ROOM_DIR, "events.json")), events: [], has_more: false });
    if (rest === `${room}/executions`) return fulfill(route, readJson(path.join(ROOM_DIR, "executions.json")));
    if (rest === `${room}/memory`) return fulfill(route, readJson(path.join(ROOM_DIR, "memory.json")));
    if (rest === `${room}/board` && boardPayload) return fulfill(route, boardPayload.projection);
    if (rest === `${room}/board/summary` && boardPayload) return fulfill(route, boardPayload.summary);
    if (rest.startsWith(`${room}/board/integrations/`) && board && fs.existsSync(boardFile(board, ".integration"))) {
      return fulfill(route, readJson(boardFile(board, ".integration")));
    }
    if (rest.startsWith(`${room}/board/reviews/`) && board && fs.existsSync(boardFile(board, ".review"))) {
      return fulfill(route, readJson(boardFile(board, ".review")));
    }
    return fulfill(route, { detail: { code: "not_mocked", message: rest } }, 404);
  });

  // Same-origin Next routes (operator decisions, review material, sends).
  await page.route("**/api/room-board-reviews/**", async (route) => {
    const request = route.request();
    if (request.url().includes("/material") && board) return fulfill(route, readJson(boardFile(board, ".material")));
    recorded.push({ url: request.url(), method: request.method(), body: request.postDataJSON() });
    return fulfill(route, { status: "applied" });
  });
  await page.route("**/api/room-board-splits/**", async (route) => {
    const request = route.request();
    recorded.push({ url: request.url(), method: request.method(), body: request.postDataJSON() });
    return fulfill(route, { status: "applied" });
  });
  await page.route("**/api/room-plugin-grants**", async (route) => {
    if (route.request().method() === "GET") return fulfill(route, { schema_version: "plugin_grant_list/v1", conversation_id: ROOM_ID, grants: [] });
    return fulfill(route, { detail: { code: "not_mocked", message: "grant" } }, 404);
  });
  await page.route("**/api/rooms/*/messages", async (route) => {
    const request = route.request();
    const body = request.postDataJSON() as { message: string; client_request_id: string };
    recorded.push({ url: request.url(), method: request.method(), body });
    return fulfill(route, {
      client_request_id: body.client_request_id,
      activity_id: "activity_sent",
      room_activity_seq: 99,
      message: { id: "msg_sent", content: body.message, created_at: "2026-10-06T04:40:00Z" }
    });
  });
  return recorded;
}
