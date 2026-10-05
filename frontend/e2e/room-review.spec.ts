import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page, type Route } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

const corsHeaders = {
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
  "Access-Control-Allow-Origin": "http://127.0.0.1:3210",
  "Cache-Control": "no-store",
  "Content-Type": "application/json"
};

const FIXTURE_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");

function readJson(name: string): unknown {
  return JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8"));
}

function withConv(payload: unknown, conversationId: string): unknown {
  const clone = structuredClone(payload) as Record<string, unknown>;
  if (typeof clone.conversation_id === "string") clone.conversation_id = conversationId;
  const projection = clone.projection as Record<string, unknown> | undefined;
  if (projection && typeof projection.conversation_id === "string") {
    projection.conversation_id = conversationId;
  }
  const summary = clone.summary as Record<string, unknown> | undefined;
  if (summary && typeof summary.conversation_id === "string") {
    summary.conversation_id = conversationId;
  }
  return clone;
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, headers: corsHeaders, body: JSON.stringify(body) });
}

async function installReviewFixture(
  page: Page,
  options: { scenario: string; endorsedAfterDecide: boolean }
) {
  let decided = false;
  let decisionBody: unknown = null;
  let decisionUrl: string | null = null;

  const pending = withConv(readJson(`${options.scenario}.json`), "conv-1") as {
    projection: unknown;
    summary: unknown;
  };
  const endorsed = withConv(readJson("review_endorsed.json"), "conv-1") as {
    projection: unknown;
    summary: unknown;
  };
  const reviewDetail = readJson("review_operator_pending.review.json") as Record<string, unknown>;
  reviewDetail.conversation_id = "conv-1";
  const material = readJson("review_operator_pending.material.json");

  await page.route("http://127.0.0.1:8201/api/chat/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders });
      return;
    }
    if (url.pathname === "/api/chat/bootstrap") {
      await json(route, {
        schema_version: "xmuse_bootstrap_projection/v1",
        has_rooms: true,
        codex: { launcher_available: true },
        memory: {
          mode: "auto",
          companion: "installed",
          profile: "full-local",
          runtime: { state: "ready", code: "ready" }
        },
        execution: { profile_id: "xmuse-monorepo/v2", revision: 2, readiness: { state: "ready", ready: true, code: "ready" } },
        recommended_action: "open_room"
      });
      return;
    }
    if (url.pathname === "/api/chat/room-setup-options") {
      await json(route, {
        schema_version: "room_setup_options/v1",
        default_roster_template_id: "builtin.development",
        roster_templates: [],
        review_policies: ["off", "cross_family"]
      });
      return;
    }
    if (url.pathname === "/api/chat/rooms") {
      await json(route, {
        schema_version: "room_list_projection/v1",
        rooms: [
          {
            conversation_id: "conv-1",
            title: "复核审计室",
            status: "settled",
            latest_visible_room_seq: 0,
            latest_visible_item: null,
            participants: [],
            active_turn_count: 0,
            attention_turn_count: 0
          }
        ]
      });
      return;
    }
    if (url.pathname.includes("/conversations/conv-1/room-projection")) {
      await json(route, {
        schema_version: "room_chat_projection/v3",
        event_cursor: 1,
        conversation: { id: "conv-1", title: "复核审计室" },
        status: "settled",
        latest_visible_room_seq: 0,
        participants: [],
        turns: [],
        timeline_items: [],
        page: { has_older: false, has_newer: false }
      });
      return;
    }
    if (url.pathname.endsWith("/events")) {
      await json(route, {
        schema_version: "chat_frontend_events/v1",
        conversation_id: "conv-1",
        after_seq: 0,
        latest_seq: 1,
        has_more: false,
        events: []
      });
      return;
    }
    if (url.pathname === "/api/chat/runtime/operations") {
      await json(route, {
        schema_version: "room_operations_projection/v2",
        generated_at: "2026-10-04T12:00:00Z",
        overall: "healthy",
        runtime: {
          runner: { state: "healthy", code: null },
          mcp: { state: "healthy", code: null },
          host: { state: "healthy", code: null, active_delivery_count: 0, retained_cleanup_count: 0 },
          memory: { enabled: false, state: "disabled", code: null, consecutive_restart_count: 0, next_retry_at: null, last_healthy_at: null }
        },
        counts: { active_delivery: 0, retained_cleanup: 0, recovery_pending: 0, cancel_pending: 0, provider_cleanup_pending: 0, exhausted: 0 },
        incident_total: 0,
        incidents: [],
        actions: {
          recover_runtime: { available: false, method: "POST", href: "/api/chat/operator/room-runtime/recover", expected_incident_id: null, mode: "restart", confirmation_required: true },
          rebuild_memory_index: { available: false, pending: false, status: null, phase: null, method: "POST", href: "/api/chat/operator/memory-runtime/rebuild", expected_incident_id: null, confirmation_required: true }
        }
      });
      return;
    }
    if (url.pathname === "/api/chat/conversations/conv-1/executions") {
      await json(route, {
        schema_version: "room_execution_list_projection/v1",
        projection_only: true,
        proof_boundary: "execution_projection_not_room_or_workspace_authority",
        generated_at: "2026-10-04T12:00:00Z",
        conversation_id: "conv-1",
        policy: {
          mode: "manual",
          revision: 1,
          risk_policy_revision: "room_execution_low_risk/v1",
          kill_switch_enabled: false,
          automatic_execution_available: false,
          automatic_execution_code: "execution_policy_manual",
          updated_at: null,
          actions: { update: { available: false, method: "PUT", href: "/api/chat/operator/conversations/conv-1/execution-policy", expected_revision: 1, allowed_modes: ["manual", "consensus"] } }
        },
        candidate_total: 0,
        candidates: [],
        page: { limit: 20, cursor: null, has_more: false, next_cursor: null }
      });
      return;
    }
    if (url.pathname === "/api/chat/conversations/conv-1/memory") {
      await json(route, {
        schema_version: "room_memory_projection/v1",
        projection_only: true,
        proof_boundary: "memory_projection_not_room_or_memory_index_authority",
        generated_at: "2026-10-04T12:00:00Z",
        conversation_id: "conv-1",
        enabled: false,
        degraded: false,
        runtime: { enabled: false, degraded: false, state: "disabled", code: null, consecutive_restart_count: 0, next_retry_at: null, last_healthy_at: null, started_at: null, updated_at: null },
        binding: { present: false, session_state: null, attachment_state: null, revision: 0, updated_at: null },
        sync: { backlog: 0, pending: 0, processing: 0, failed: 0, conflict: 0, delivered: 0 },
        recent_recalls: [],
        pending_candidate_total: 0,
        pending_candidates: []
      });
      return;
    }
    if (url.pathname === "/api/chat/conversations/conv-1/codex-agents") {
      await json(route, {
        schema_version: "room_codex_projection/v1",
        conversation_id: "conv-1",
        generated_at: "2026-10-04T12:00:00Z",
        projection_only: true,
        proof_boundary: "projection_not_codex_app_server_or_room_authority",
        participants: [],
        native_events: { source: "codex_app_server_projection_cache", projection_available: false, reason_code: null, event_seq_domain: "room_codex_projection_cache", items: [], latest_event_seq: 0, has_older: false, has_newer: false, next_before_event_seq: null, next_after_event_seq: null }
      });
      return;
    }
    if (url.pathname === "/api/chat/conversations/conv-1/board/summary") {
      await json(route, decided && options.endorsedAfterDecide ? endorsed.summary : pending.summary);
      return;
    }
    if (url.pathname === "/api/chat/conversations/conv-1/board") {
      await json(route, decided && options.endorsedAfterDecide ? endorsed.projection : pending.projection);
      return;
    }
    if (url.pathname.includes("/board/reviews/")) {
      await json(route, reviewDetail);
      return;
    }
    await json(route, { detail: { code: "fixture_route_missing", message: url.pathname } }, 404);
  });

  await page.route("**/api/room-board-reviews/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname.endsWith("/material")) {
      await json(route, material);
      return;
    }
    if (request.method() === "POST" && url.pathname.endsWith("/decision")) {
      decisionUrl = request.url();
      decisionBody = request.postDataJSON();
      decided = true;
      await json(route, {});
      return;
    }
    await json(route, { detail: { code: "fixture_route_missing", message: url.pathname } }, 404);
  });

  return {
    getDecisionBody: () => decisionBody,
    getDecisionUrl: () => decisionUrl
  };
}

test("operator endorses a pending review through the fixed decision route", async ({ page }) => {
  const review = await installReviewFixture(page, {
    scenario: "review_operator_pending",
    endorsedAfterDecide: true
  });
  await page.goto("/rooms/conv-1");
  await page.getByRole("button", { name: /工作台/ }).click();
  const inspector = page.locator(".room-inspector");
  await inspector.getByRole("tab", { name: "Room" }).click();
  const board = inspector.getByRole("region", { name: "协作看板" });
  await expect(board).toBeVisible();
  await expect(board.getByRole("status", { name: /待你复核/ }).first()).toBeVisible();

  await board.getByRole("button", { name: "复核此模块" }).first().click();
  await expect(board.locator("pre").first()).toContainText("<U+202E>");
  await expect(board.getByText(/含 3 个不可见字符/)).toBeVisible();

  await board.getByRole("textbox", { name: /复核结论/ }).fill("补丁与其模块范围一致，予以背书");
  await board.getByRole("button", { name: "提交复核" }).click();

  await expect.poll(() => review.getDecisionBody(), { timeout: 10_000 }).not.toBeNull();
  const body = review.getDecisionBody() as Record<string, unknown>;
  expect(Object.keys(body).sort()).toEqual([
    "conversation_id",
    "expected_digest",
    "findings",
    "summary",
    "verdict"
  ]);
  expect(body).toMatchObject({ conversation_id: "conv-1", verdict: "endorse" });
  expect(review.getDecisionUrl()).toContain("/api/room-board-reviews/");

  await expect(board.getByRole("status", { name: /已背书/ }).first()).toBeVisible({ timeout: 15_000 });
  await expect(board).toContainText("已验收");

  for (const theme of ["dark", "light"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    const results = await new AxeBuilder({ page }).include(".room-board").analyze();
    expect(results.violations, `axe violations in the ${theme} theme`).toEqual([]);
  }
});

test("operator objects to a review with a blocker finding", async ({ page }) => {
  const review = await installReviewFixture(page, {
    scenario: "review_operator_pending",
    endorsedAfterDecide: false
  });
  await page.goto("/rooms/conv-1");
  await page.getByRole("button", { name: /工作台/ }).click();
  const inspector = page.locator(".room-inspector");
  await inspector.getByRole("tab", { name: "Room" }).click();
  const board = inspector.getByRole("region", { name: "协作看板" });
  await expect(board).toBeVisible();

  await board.getByRole("button", { name: "复核此模块" }).first().click();
  await expect(board.locator("pre").first()).toBeVisible();
  await board.getByRole("radio", { name: "异议" }).check();
  await board.getByRole("textbox", { name: /复核结论/ }).fill("补丁越界，需要返工");
  await board.getByRole("button", { name: "添加问题" }).click();
  await board.getByRole("textbox", { name: /问题描述/ }).fill("越界写入了其他模块的路径");
  await board.getByRole("button", { name: "提交复核" }).click();

  await expect.poll(() => review.getDecisionBody(), { timeout: 10_000 }).not.toBeNull();
  const body = review.getDecisionBody() as Record<string, unknown>;
  expect(body).toMatchObject({ conversation_id: "conv-1", verdict: "object" });
  expect((body.findings as Array<Record<string, unknown>>).length).toBeGreaterThan(0);

  for (const theme of ["dark", "light"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    const results = await new AxeBuilder({ page }).include(".room-board").analyze();
    expect(results.violations, `axe violations in the ${theme} theme`).toEqual([]);
  }
});
