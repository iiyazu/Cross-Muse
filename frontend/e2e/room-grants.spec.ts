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

function boardFixture(name: string): { projection: unknown; summary: unknown } {
  const payload = JSON.parse(
    fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8")
  ) as { projection: unknown; summary: unknown };
  return { projection: payload.projection, summary: payload.summary };
}

async function json(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, headers: corsHeaders, body: JSON.stringify(body) });
}

function grantPayload(status: string, revokedAt: string | null = null) {
  return {
    grant_id: "grant-1",
    conversation_id: "conv-1",
    host: "claude-code",
    scope: "board.split.decide",
    status,
    created_at: "2026-10-04T12:00:00Z",
    activated_at: status === "pending" ? null : "2026-10-04T12:01:00Z",
    expires_at: "2026-10-04T13:01:00Z",
    revoked_at: revokedAt,
    last_used_at: null,
    use_count: 0
  };
}

async function installGrantsFixture(page: Page) {
  const { projection, summary } = boardFixture("split_pending.json");
  let grantStatus = "pending";
  let issueBody: unknown = null;
  let issueCount = 0;

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
        roster_templates: []
      });
      return;
    }
    if (url.pathname === "/api/chat/rooms") {
      await json(route, {
        schema_version: "room_list_projection/v1",
        rooms: [
          {
            conversation_id: "conv-1",
            title: "授权审计室",
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
        conversation: { id: "conv-1", title: "授权审计室" },
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
      await json(route, summary);
      return;
    }
    if (url.pathname === "/api/chat/conversations/conv-1/board") {
      await json(route, projection);
      return;
    }
    await json(route, { detail: { code: "fixture_route_missing", message: url.pathname } }, 404);
  });

  await page.route("**/api/room-plugin-grants**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname === "/api/room-plugin-grants") {
      issueBody = request.postDataJSON();
      issueCount += 1;
      const pairingExpiresAt = new Date(Date.now() + 120_000).toISOString();
      await json(route, {
        schema_version: "plugin_grant_issue/v1",
        grant: grantPayload("pending"),
        pairing_code: "ABCD-EFGH",
        pairing_expires_at: pairingExpiresAt
      }, 201);
      return;
    }
    if (request.method() === "GET" && url.pathname === "/api/room-plugin-grants") {
      await json(route, {
        schema_version: "plugin_grant_list/v1",
        conversation_id: "conv-1",
        grants: [grantPayload(grantStatus, grantStatus === "revoked" ? new Date().toISOString() : null)]
      });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/room-plugin-grants/grant-1/revoke") {
      grantStatus = "revoked";
      await json(route, grantPayload("revoked", new Date().toISOString()));
      return;
    }
    await json(route, { detail: { code: "fixture_route_missing", message: url.pathname } }, 404);
  });

  return {
    flipToActive() { grantStatus = "active"; },
    getIssueBody: () => issueBody,
    getIssueCount: () => issueCount
  };
}

test("plugin grant panel issues, pairs, and revokes through the fixed routes", async ({ page }) => {
  const grants = await installGrantsFixture(page);
  await page.goto("/rooms/conv-1");
  await page.getByRole("button", { name: /工作台/ }).click();
  const inspector = page.locator(".room-inspector");
  await inspector.getByRole("tab", { name: "Room" }).click();
  const board = inspector.getByRole("region", { name: "协作看板" });
  await expect(board).toBeVisible();

  const section = board.locator("details.room-grants");
  await expect(section.locator("summary")).toContainText("插件授权");
  // The section is collapsed by default; open it explicitly.
  await section.locator("summary").click();
  await expect(board).toContainText("授权后，插件只能批准或拒绝待审批拆分，到期自动失效。");

  await board.getByRole("button", { name: "生成配对码" }).click();
  await expect(board.getByText("ABCD-EFGH")).toBeVisible();
  await expect(
    board.getByText("在插件窗格里输入此码，120 秒内有效，只能使用一次")
  ).toBeVisible();
  await expect(board.getByText(/配对码剩余/)).toBeVisible();
  await expect(board.getByRole("status", { name: /待配对/ }).first()).toBeVisible();

  expect(grants.getIssueCount()).toBe(1);
  expect(grants.getIssueBody()).toBeTruthy();
  expect(Object.keys(grants.getIssueBody() as Record<string, unknown>).sort()).toEqual([
    "conversation_id",
    "host",
    "scope",
    "ttl_seconds"
  ]);
  expect(grants.getIssueBody()).toMatchObject({
    conversation_id: "conv-1",
    host: "claude-code",
    scope: "board.split.decide",
    ttl_seconds: 600
  });

  // The mocked list flips to active on the next 5 s poll: the code disappears.
  grants.flipToActive();
  await expect(board.getByText("ABCD-EFGH")).toHaveCount(0, { timeout: 15_000 });
  await expect(board.getByRole("status", { name: /已授权/ }).first()).toBeVisible();

  await board.getByRole("button", { name: /撤销/ }).first().click();
  await expect(board.getByRole("status", { name: /已撤销/ }).first()).toBeVisible({ timeout: 15_000 });

  for (const theme of ["dark", "light"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    const results = await new AxeBuilder({ page }).include(".room-grants").analyze();
    expect(results.violations, `axe violations in the ${theme} theme`).toEqual([]);
  }
});
