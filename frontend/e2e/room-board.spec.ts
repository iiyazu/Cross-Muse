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

async function installBoardFixture(page: Page, scenario: "verified" | "verification_failed_rework" | "split_pending" | "integration_fallback_to_incumbent") {
  const fixtureFile =
    scenario === "verified"
      ? "verified.json"
      : scenario === "split_pending"
        ? "split_pending.json"
        : scenario === "integration_fallback_to_incumbent"
          ? "integration_fallback_to_incumbent.json"
          : "verification_failed_rework.json";
  const { projection, summary } = boardFixture(fixtureFile);
  let integrationDetail: unknown = null;
  if (scenario === "integration_fallback_to_incumbent") {
    integrationDetail = JSON.parse(
      fs.readFileSync(
        path.join(FIXTURE_DIR, "integration_fallback_to_incumbent.integration.json"),
        "utf8"
      )
    );
  }
  const boardProjection =
    scenario === "verified"
      ? withSyntheticDoneClaimed(structuredClone(projection) as Record<string, unknown>)
      : projection;

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
            title: "看板审计室",
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
        conversation: { id: "conv-1", title: "看板审计室" },
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
    if (url.pathname.includes("/board/integrations/")) {
      if (integrationDetail) {
        await json(route, integrationDetail);
        return;
      }
      await json(route, { detail: { code: "fixture_route_missing", message: url.pathname } }, 404);
      return;
    }
    if (url.pathname === "/api/chat/conversations/conv-1/board") {
      await json(route, boardProjection);
      return;
    }
    if (url.pathname.includes("/board/contracts/")) {
      await json(route, {
        schema_version: "room_board_contract/v2",
        conversation_id: "conv-1",
        contract_id: "api.alpha",
        provider_module_id: "alpha",
        kind: "api_schema",
        versions: [
          {
            version: 1,
            digest: "sha256:1",
            author_participant_id: "part-1",
            created_at: "2026-10-04T12:00:00Z",
            rationale: null
          }
        ],
        version: 1,
        content: { text: "type Alpha = { id: string }", untrusted: true, truncated: false }
      });
      return;
    }
    await json(route, { detail: { code: "fixture_route_missing", message: url.pathname } }, 404);
  });
}

function withSyntheticDoneClaimed(projection: Record<string, unknown>): Record<string, unknown> {
  const modules = (projection.modules ?? []) as Array<Record<string, unknown>>;
  const beta = modules.find((item) => item.module_id === "beta");
  if (beta) {
    beta.lifecycle = "done_claimed";
    beta.state = "done_claimed";
    beta.verification = {
      status: "none",
      verification_id: null,
      reason_code: null,
      escalated: false,
      gate_ids: [],
      stacked: [],
      head_commit: null,
      changed_path_count: 0,
      updated_at: null
    };
    (beta.counters as Record<string, unknown>).done_reports = 1;
  }
  return projection;
}

test("board panel distinguishes done_claimed from verified", async ({ page }) => {
  await installBoardFixture(page, "verified");
  await page.goto("/rooms/conv-1");
  await page.getByRole("button", { name: /工作台/ }).click();
  const inspector = page.locator(".room-inspector");
  await inspector.getByRole("tab", { name: "Room" }).click();
  const board = inspector.getByRole("region", { name: "协作看板" });
  await expect(board).toBeVisible();
  // The summary chips and the module badges both carry data-state; the badges are role=status.
  const verified = board.getByRole("status", { name: /^已验证/ }).first();
  const claimed = board.getByRole("status", { name: /^自称完成/ }).first();
  await expect(verified).toHaveAttribute("data-state", "verified");
  await expect(claimed).toHaveAttribute("data-state", "done_claimed");
  expect(await verified.getAttribute("aria-label")).not.toBe(
    await claimed.getAttribute("aria-label")
  );

  for (const theme of ["dark", "light"]) {
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    const results = await new AxeBuilder({ page }).include(".room-board").analyze();
    expect(results.violations, `axe violations in the ${theme} theme`).toEqual([]);
  }
});

test("board panel surfaces failed gates and rework rounds", async ({ page }) => {
  await installBoardFixture(page, "verification_failed_rework");
  await page.goto("/rooms/conv-1");
  await page.getByRole("button", { name: /工作台/ }).click();
  const inspector = page.locator(".room-inspector");
  await inspector.getByRole("tab", { name: "Room" }).click();
  const board = inspector.getByRole("region", { name: "协作看板" });
  await expect(board).toBeVisible();
  await expect(
    board.getByRole("status", { name: /^验证失败/ }).first()
  ).toHaveAttribute("data-state", "verification_failed");
  await expect(board).toContainText("patch_diff_check");
  await expect(board).toContainText("返工");
});

test("board panel shows integration chip, totals and conflict detail", async ({ page }) => {
  await installBoardFixture(page, "integration_fallback_to_incumbent");
  await page.goto("/rooms/conv-1");
  await page.getByRole("button", { name: /工作台/ }).click();
  const inspector = page.locator(".room-inspector");
  await inspector.getByRole("tab", { name: "Room" }).click();
  const board = inspector.getByRole("region", { name: "协作看板" });
  await expect(board).toBeVisible();
  // m1 conflicted at an older integrated version: honest chip text, never 已集成.
  const m1 = board.getByRole("article", { name: "模块 m1" });
  await expect(m1).toContainText("集成冲突 · 1 个路径");
  await expect(m1).toContainText("分支中是旧版本");
  // Reviews are off here, so the summary line counts verified alongside integrated.
  await expect(board).toContainText("已验证 3");
  await expect(board).toContainText("已集成 2");
  await m1.getByText("集成详情").click();
  await expect(m1).toContainText("docs/b.txt");
});

test("board panel approves a proposed split through the fixed decision route", async ({ page }) => {
  await installBoardFixture(page, "split_pending");
  let decided = false;
  let decisionUrl: string | null = null;
  let decisionBody: unknown = null;
  await page.route(
    (url) =>
      url.hostname === "127.0.0.1" &&
      (url.pathname === "/api/chat/conversations/conv-1/board" ||
        url.pathname === "/api/chat/conversations/conv-1/board/summary"),
    async (route) => {
      const { projection, summary } = boardFixture(
        decided ? "split_approved_via_plugin.json" : "split_pending.json"
      );
      const url = new URL(route.request().url());
      await json(
        route,
        url.pathname.endsWith("/board/summary") ? summary : projection
      );
    }
  );
  await page.route("**/api/room-board-splits/*/decision", async (route) => {
    const request = route.request();
    decisionUrl = request.url();
    decisionBody = request.postDataJSON();
    decided = true;
    await json(route, {});
  });

  await page.goto("/rooms/conv-1");
  await page.getByRole("button", { name: /工作台/ }).click();
  const inspector = page.locator(".room-inspector");
  await inspector.getByRole("tab", { name: "Room" }).click();
  const board = inspector.getByRole("region", { name: "协作看板" });
  await expect(board).toBeVisible();
  // The proposal sits in a collapsed card; the attention row's jump button opens it.
  await board.getByRole("button", { name: "查看拆分" }).click();
  await board.getByRole("button", { name: "批准拆分" }).click();
  const dialog = board.getByRole("alertdialog");
  await expect(dialog).toContainText("批准后将创建章程");
  await dialog.getByRole("button", { name: "确认" }).click();

  await expect
    .poll(() => decisionBody, { timeout: 10_000 })
    .not.toBeNull();
  expect(decisionUrl).toContain("/api/room-board-splits/");
  expect(decisionUrl).toContain("/decision");
  expect(decisionBody).toBeTruthy();
  expect(Object.keys(decisionBody as Record<string, unknown>).sort()).toEqual([
    "conversation_id",
    "decision",
    "expected_digest"
  ]);
  expect(decisionBody).toMatchObject({ conversation_id: "conv-1", decision: "approve" });
  await expect(board).toContainText("插件（claude-code）");
  await expect(board.getByRole("button", { name: "批准拆分" })).toHaveCount(0);
});
