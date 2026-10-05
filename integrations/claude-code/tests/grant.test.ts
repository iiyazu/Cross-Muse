// Plugin grant tests: pairing validation, exchange, expiry, digest
// confirm, decision outcomes, revoke and detach. One body run with explicit
// options (pollSeconds 1s). All test hooks register before the first $ call.
// The flows below build contract-shaped payloads inline; the backend golden
// responses (docs/contracts/fixtures/plugin_grant_v1, copied into
// grant_golden.generated.ts by tools/sync_fixtures.py) get their own test.
import { expect, mock, test } from "claude-code/testing";
import type { Engine, On } from "claude-code/testing";
import * as fx from "./fixtures.generated";
import { GRANT_GOLDEN } from "./grant_golden.generated";
import { detailCodeOf, parseExchangePayload } from "../src/grant_api";
import {
  checkConfirmInput,
  confirmPrefixOf,
  grantExpired,
  mapDecisionOutcome,
  remainingMmSs,
  validatePairingCode,
} from "../src/grant_state";

const OPTIONS = { options: { pollSeconds: 1 } };
const SURFACES = ["terminal", "desktop"] as const;

const CID = String((fx.split_pending.summary as { conversation_id: string }).conversation_id);
const PENDING_SPLIT = "split_00000000000000000000000000000018";
const PENDING_DIGEST = "sha256:b4aa5e95346952af898a7b6d28852fc716ec57864501efea4b4b3070849e2f88";
const PENDING_PREFIX = "b4aa5e";

function tokenFor(tag: string): string {
  return "xpg_" + tag + "_" + "A".repeat(43);
}

function exchangeText(cid: string, token: string, expiresAt: string): string {
  return JSON.stringify({
    schema_version: "plugin_grant_exchange/v1",
    grant: {
      grant_id: "grant_test_1",
      conversation_id: cid,
      host: "claude-code",
      scope: "board.split.decide",
      status: "active",
      created_at: "2026-10-05T00:00:00Z",
      activated_at: "2026-10-05T00:00:01Z",
      expires_at: expiresAt,
      revoked_at: null,
      last_used_at: null,
      use_count: 0,
    },
    secret: token,
  });
}

function clone<T>(v: T): T {
  return JSON.parse(JSON.stringify(v)) as T;
}

function summaryFor(cid: string): string {
  const base = clone(fx.split_pending.summary) as Record<string, unknown>;
  base["conversation_id"] = cid;
  return JSON.stringify(base);
}

function projectionFor(cid: string): string {
  const base = clone(fx.split_pending.projection) as Record<string, unknown>;
  base["conversation_id"] = cid;
  return JSON.stringify(base);
}

function paneProps(bodyColumns: number): Record<string, unknown> {
  return {
    title: "xmuse 看板",
    isFocused: false,
    bodyColumns,
    placement: "dock",
    scroll: { offset: 0, bodyRows: 24 },
    view: {},
  };
}

type Post = { url: string; method: string; headers: Record<string, string>; body: string };

async function bootGrant(
  $: Engine,
  on: On,
  args: {
    binding?: string;
    summaryText?: () => string;
    projectionText?: () => string;
    exchange?: () => { status: number; text: string };
    decide?: (body: unknown) => { status: number; text: string };
    revoke?: () => { status: number; text: string };
    failPosts?: boolean;
  },
): Promise<{
  clock: { advance: (ms: number) => Promise<void>; settle: () => Promise<void>; now: () => number };
  statuses: (string | undefined)[];
  toasts: string[];
  posts: Post[];
  gets: string[];
}> {
  const binding = args.binding ?? CID;
  mock.store(on, { "binding:/repo": binding });
  const clock = mock.clock(on);
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  const posts: Post[] = [];
  const gets: string[] = [];
  on("ui.status", async (_$, e) => {
    statuses.push(e.text);
    return { value: undefined };
  });
  on("ui.toast", async (_$, e) => {
    toasts.push(e.text);
    return { value: undefined };
  });
  on("ui.open", async () => ({ value: { isPlaced: true } }));
  on("session.start", async (_$, e) => ({ cwd: e.cwd }));
  on("command.register", async () => ({ value: { command: "xmuse" } }));
  on("tool.register", async () => ({ value: { tool: "mcp__xmuse__status" } }));
  on("http.fetch", async (_$, e) => {
    const init = (e.init ?? {}) as { method?: string; headers?: Record<string, string>; body?: string };
    const method = init.method ?? "GET";
    if (method === "GET") {
      gets.push(e.url);
      if (e.url.endsWith("/board/summary")) {
        return { value: { status: 200, ok: true, headers: {}, text: args.summaryText?.() ?? summaryFor(binding) } };
      }
      if (e.url.endsWith("/board")) {
        return { value: { status: 200, ok: true, headers: {}, text: args.projectionText?.() ?? projectionFor(binding) } };
      }
      if (e.url.endsWith("/api/chat/rooms")) {
        return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify({ rooms: [] }) } };
      }
      return { value: { status: 404, ok: false, headers: {}, text: "{}" } };
    }
    posts.push({ url: e.url, method, headers: { ...(init.headers ?? {}) }, body: init.body ?? "" });
    if (args.failPosts === true) throw new Error("network down");
    if (e.url.endsWith("/api/chat/plugin/grants/exchange")) {
      const r = args.exchange?.() ?? { status: 401, text: JSON.stringify({ detail: { code: "plugin_pairing_invalid", message: "no" } }) };
      return { value: { status: r.status, ok: r.status >= 200 && r.status < 300, headers: {}, text: r.text } };
    }
    if (e.url.includes("/board-splits/") && e.url.endsWith("/decision")) {
      let body: unknown = null;
      try {
        body = JSON.parse((init.body ?? "") as string);
      } catch {
        body = null;
      }
      const r = args.decide?.(body) ?? { status: 200, text: "{}" };
      return { value: { status: r.status, ok: r.status >= 200 && r.status < 300, headers: {}, text: r.text } };
    }
    if (e.url.endsWith("/api/chat/plugin/grants/revoke")) {
      const r = args.revoke?.() ?? { status: 200, text: "{}" };
      return { value: { status: r.status, ok: r.status >= 200 && r.status < 300, headers: {}, text: r.text } };
    }
    return { value: { status: 404, ok: false, headers: {}, text: "{}" } };
  });
  await $.session.start({ cwd: "/repo", surface: "terminal", isInteractive: true });
  await $.command.run({ command: "xmuse", args: "" });
  await clock.advance(1000);
  await clock.settle();
  return { clock, statuses, toasts, posts, gets };
}

function errorText(code: string): string {
  return JSON.stringify({ detail: { code, message: "structured" } });
}

function treeText(drawn: unknown): string {
  return JSON.stringify(drawn);
}

function buttonLabels(buttons: unknown[]): string[] {
  return buttons.map((b) => {
    const view = b as { props?: Record<string, unknown>; text?: unknown };
    return String(view.props?.["label"] ?? view.text ?? "");
  });
}

// --- pure validation table ---

test("pairing code validation table", OPTIONS, async () => {
  const valid: [string, string][] = [
    ["ABCD-EFGH", "ABCD-EFGH"],
    ["abcd-efgh", "ABCD-EFGH"],
    ["  abcd-efgh  ", "ABCD-EFGH"],
    ["\tabcd-efgh\n", "ABCD-EFGH"],
    ["2345-6789", "2345-6789"],
  ];
  for (const [input, code] of valid) {
    const r = validatePairingCode(input);
    expect(r.ok).toBe(true);
    if (r.ok) expect(r.code).toBe(code);
  }
  const invalid = ["", "ABCD-EFG", "ABCD-EFGHI", "ABCD-EFGI", "ABCD-EFG0", "ABCD-EFGU", "ABCD EFGH", "ABCD-EFGH-X", "abcd_efgh", "ABCD-EFGl"];
  for (const input of invalid) {
    const r = validatePairingCode(input);
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.hint.length).toBeGreaterThan(0);
  }
});

test("confirm prefix and check table", OPTIONS, async () => {
  expect(confirmPrefixOf(PENDING_DIGEST)).toBe(PENDING_PREFIX);
  expect(confirmPrefixOf("sha256:xyz")).toBe(null);
  expect(confirmPrefixOf("nope")).toBe(null);
  expect(checkConfirmInput(PENDING_DIGEST, PENDING_PREFIX).ok).toBe(true);
  expect(checkConfirmInput(PENDING_DIGEST, "  B4AA5E ").ok).toBe(true);
  expect(checkConfirmInput(PENDING_DIGEST, "000000").ok).toBe(false);
  expect(checkConfirmInput(PENDING_DIGEST, "").ok).toBe(false);
  expect(checkConfirmInput("nope", PENDING_PREFIX).ok).toBe(false);
});

test("grant expiry and countdown", OPTIONS, async () => {
  expect(grantExpired("2999-01-01T00:00:00Z", Date.parse("2026-01-01T00:00:00Z"))).toBe(false);
  expect(grantExpired("2026-01-01T00:00:00Z", Date.parse("2026-01-01T00:00:01Z"))).toBe(true);
  expect(grantExpired("not-a-time", 0)).toBe(true);
  expect(remainingMmSs("2026-01-01T00:10:00Z", Date.parse("2026-01-01T00:00:00Z"))).toBe("10:00");
});

test("decision outcome mapping table", OPTIONS, async () => {
  expect(mapDecisionOutcome(200, null, "approve").toast).toBe("已批准拆分");
  expect(mapDecisionOutcome(200, null, "reject").toast).toBe("已拒绝拆分");
  for (const code of ["room_board_split_decided", "room_board_split_not_proposed"]) {
    const o = mapDecisionOutcome(409, code, "approve");
    expect(o.toast).toBe("拆分已不能决定，已刷新");
    expect(o.refetch).toBe(true);
  }
  const digest = mapDecisionOutcome(409, "room_board_split_digest_mismatch", "reject");
  expect(digest.toast).toBe("拆分已变化，请重新确认");
  expect(digest.refetch).toBe(true);
  const unauth = mapDecisionOutcome(401, "plugin_grant_invalid", "approve");
  expect(unauth.toast).toBe("授权已失效，请在 Web 重新授权");
  expect(unauth.clearGrant).toBe(true);
  for (const status of [403, 404, 415, 422, 429, 500]) {
    const o = mapDecisionOutcome(status, "something", "approve");
    expect(o.toast).toBe("操作失败（" + String(status) + "）");
    expect(o.clearGrant).toBe(false);
  }
  expect(mapDecisionOutcome(0, null, "approve").toast).toBe("操作失败（网络错误）");
});

test("exchange payload parsing keeps active grants only", OPTIONS, async () => {
  const token = tokenFor("parse");
  const good = parseExchangePayload(JSON.parse(exchangeText(CID, token, "2999-01-01T00:00:00Z")));
  expect(good?.token).toBe(token);
  expect(good?.grant.conversationId).toBe(CID);
  const raw = JSON.parse(exchangeText(CID, token, "2999-01-01T00:00:00Z")) as Record<string, unknown>;
  const pending = clone(raw);
  (pending["grant"] as Record<string, unknown>)["status"] = "pending";
  expect(parseExchangePayload(pending)).toBe(null);
  expect(parseExchangePayload({ schema_version: "other", grant: {}, secret: token })).toBe(null);
  expect(parseExchangePayload({ schema_version: "plugin_grant_exchange/v1", grant: (raw["grant"] as object), secret: "bad" })).toBe(null);
  expect(detailCodeOf(JSON.parse(errorText("room_board_split_decided")))).toBe("room_board_split_decided");
  expect(detailCodeOf({})).toBe(null);
});

test("backend golden responses parse the way the mod reads them", OPTIONS, async () => {
  const exchange = parseExchangePayload(GRANT_GOLDEN["exchange"]);
  expect(exchange).not.toBe(null);
  expect(exchange?.grant.conversationId).toBe(GRANT_GOLDEN["exchange"].grant.conversation_id);
  expect(String(exchange?.token).startsWith("xpg_")).toBe(true);
  expect(validatePairingCode(GRANT_GOLDEN["issue"].pairing_code).ok).toBe(true);
  // the pending grant from issue and the revoked grant from revoke never authorize
  expect(parseExchangePayload({ ...GRANT_GOLDEN["exchange"], grant: GRANT_GOLDEN["issue"].grant })).toBe(null);
  expect(parseExchangePayload(GRANT_GOLDEN["plugin_revoke"])).toBe(null);
  // every error golden is named by its code and is read back as that code
  const codes = [
    "plugin_content_type_invalid",
    "plugin_grant_invalid",
    "plugin_origin_forbidden",
    "plugin_pairing_invalid",
    "plugin_pairing_locked",
    "room_board_split_decided",
    "room_board_split_digest_mismatch",
    "room_board_split_not_proposed",
  ];
  for (const code of codes) {
    expect(detailCodeOf(GRANT_GOLDEN[code]), code).toBe(code);
  }
  expect(mapDecisionOutcome(409, detailCodeOf(GRANT_GOLDEN["room_board_split_decided"]), "approve").refetch).toBe(true);
  expect(mapDecisionOutcome(409, detailCodeOf(GRANT_GOLDEN["room_board_split_digest_mismatch"]), "approve").toast).toBe(
    "拆分已变化，请重新确认",
  );
  expect(mapDecisionOutcome(401, detailCodeOf(GRANT_GOLDEN["plugin_grant_invalid"]), "approve").clearGrant).toBe(true);
});

// --- engine flows ---

test("exchange request has no Origin and only documented headers", OPTIONS, async ($, on) => {
  const token = tokenFor("headers");
  const env = await bootGrant($, on, {
    exchange: () => ({ status: 200, text: exchangeText(CID, token, "2999-01-01T00:00:00Z") }),
  });
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  const field = await ui.find({ key: "xmuse-pairing" });
  expect(field).toBeDefined();
  const fieldView = field as unknown as { props?: Record<string, unknown>; text?: unknown } | undefined;
  const fieldLabel = String(fieldView?.props?.["label"] ?? fieldView?.text ?? "");
  expect(fieldLabel).toBe("配对码");
  await ui.input({ key: "xmuse-pairing", text: "  abcd-efgh " });
  expect(env.posts).toHaveLength(1);
  const post = env.posts[0];
  expect(post.url.endsWith("/api/chat/plugin/grants/exchange")).toBe(true);
  expect(post.method).toBe("POST");
  expect("Origin" in post.headers).toBe(false);
  expect("origin" in post.headers).toBe(false);
  expect(Object.keys(post.headers)).toHaveLength(1);
  expect(post.headers["Content-Type"]).toBe("application/json");
  const body = JSON.parse(post.body) as Record<string, unknown>;
  expect(Object.keys(body).sort().join(",")).toBe("host,pairing_code");
  expect(body["pairing_code"]).toBe("ABCD-EFGH");
  expect(body["host"]).toBe("claude-code");
  await ui.unmount();
});

test("exchange success authorizes without leaking the token", OPTIONS, async ($, on) => {
  const token = tokenFor("success");
  const env = await bootGrant($, on, {
    exchange: () => ({ status: 200, text: exchangeText(CID, token, "2999-01-01T00:10:00Z") }),
  });
  // The grant lives in module scope plus the shared atom, so one pairing
  // authorizes every surface. Pair once, then verify each surface shows the
  // authorized view with no secret material in the drawn tree.
  const first = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await first.input({ key: "xmuse-pairing", text: "ABCD-EFGH" });
  expect(env.toasts[env.toasts.length - 1]).toContain("已授权");
  await first.unmount();
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ plugin: "xmuse", surface, component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
    const authed = await ui.find({ type: "Text", text: /已授权 · 剩余/ });
    expect(authed).toBeDefined();
    const drawn = await ui.drawn();
    const flat = treeText(drawn);
    expect(flat).not.toContain(token);
    expect(flat).not.toContain("ABCD-EFGH");
    expect(flat).not.toContain("abcd-efgh");
    await ui.unmount();
  }
  for (const t of env.toasts) {
    expect(t).not.toContain(token);
    expect(t).not.toContain("ABCD-EFGH");
  }
});

test("invalid pairing code is rejected locally with no network call", OPTIONS, async ($, on) => {
  const env = await bootGrant($, on, {});
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await ui.input({ key: "xmuse-pairing", text: "ABCD-EFG!" });
  expect(env.posts).toHaveLength(0);
  expect(env.toasts[env.toasts.length - 1]).toContain("配对码格式不对");
  expect(await ui.find({ key: "xmuse-pairing" })).toBeDefined();
  await ui.unmount();
});

test("expiry drops the grant and restores the pairing view", OPTIONS, async ($, on) => {
  const token = tokenFor("expiry");
  let expiresAt = "2999-01-01T00:00:00Z";
  const env = await bootGrant($, on, {
    exchange: () => ({ status: 200, text: exchangeText(CID, token, expiresAt) }),
  });
  expiresAt = new Date(env.clock.now() + 2000).toISOString();
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await ui.input({ key: "xmuse-pairing", text: "ABCD-EFGH" });
  expect(await ui.find({ type: "Text", text: /已授权 · 剩余/ })).toBeDefined();
  await env.clock.advance(5000);
  await env.clock.settle();
  expect(await ui.find({ key: "xmuse-pairing" })).toBeDefined();
  expect(await ui.find({ type: "Text", text: /已授权 · 剩余/ })).toBeUndefined();
  const buttons = await ui.findAll({ type: "Button" });
  expect(buttonLabels(buttons).filter((l) => ["批准", "拒绝"].includes(l))).toHaveLength(0);
  await ui.unmount();
});

test("approve with digest confirm sends the exact decision body", OPTIONS, async ($, on) => {
  const token = tokenFor("approve");
  const env = await bootGrant($, on, {
    exchange: () => ({ status: 200, text: exchangeText(CID, token, "2999-01-01T00:00:00Z") }),
    decide: (body) => {
      const b = body as Record<string, unknown>;
      expect(Object.keys(b).sort()).toEqual(["conversation_id", "decision", "expected_digest"]);
      expect(b["conversation_id"]).toBe(CID);
      expect(b["expected_digest"]).toBe(PENDING_DIGEST);
      return { status: 200, text: "{}" };
    },
  });
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await ui.input({ key: "xmuse-pairing", text: "ABCD-EFGH" });
  await ui.press({ key: "xmuse-approve-" + PENDING_SPLIT });
  expect(await ui.find({ key: "xmuse-confirm" })).toBeDefined();
  expect(env.posts.filter((p) => p.url.includes("/board-splits/"))).toHaveLength(0);
  await ui.input({ key: "xmuse-confirm", text: "000000" });
  expect(env.toasts[env.toasts.length - 1]).toContain("摘要不匹配");
  expect(env.posts.filter((p) => p.url.includes("/board-splits/"))).toHaveLength(0);
  await ui.press({ key: "xmuse-approve-" + PENDING_SPLIT });
  await ui.input({ key: "xmuse-confirm", text: PENDING_PREFIX });
  const decided = env.posts.filter((p) => p.url.includes("/board-splits/"));
  expect(decided).toHaveLength(1);
  expect(decided[0].url.endsWith("/api/chat/plugin/board-splits/" + PENDING_SPLIT + "/decision")).toBe(true);
  expect(decided[0].headers["Authorization"]).toBe("Bearer " + token);
  expect(JSON.parse(decided[0].body)["decision"]).toBe("approve");
  expect(env.toasts[env.toasts.length - 1]).toBe("已批准拆分");
  expect(env.gets.some((u) => u.endsWith("/board"))).toBe(true);
  const flat = treeText(await ui.drawn());
  expect(flat).not.toContain(token);
  await ui.unmount();
});

test("reject maps to the reject toast", OPTIONS, async ($, on) => {
  const token = tokenFor("reject");
  const env = await bootGrant($, on, {
    exchange: () => ({ status: 200, text: exchangeText(CID, token, "2999-01-01T00:00:00Z") }),
    decide: () => ({ status: 200, text: "{}" }),
  });
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await ui.input({ key: "xmuse-pairing", text: "ABCD-EFGH" });
  await ui.press({ key: "xmuse-reject-" + PENDING_SPLIT });
  await ui.input({ key: "xmuse-confirm", text: PENDING_PREFIX });
  expect(env.posts.filter((p) => p.url.includes("/board-splits/"))).toHaveLength(1);
  expect(env.toasts[env.toasts.length - 1]).toBe("已拒绝拆分");
  await ui.unmount();
});

test("already-decided splits refetch and toast the refresh label", OPTIONS, async ($, on) => {
  // One engine per test: mock.* must be registered before the first $ call,
  // so a second bootGrant in the same test is rejected. Drive both reason
  // codes through a single boot with a mutable responder instead.
  const token = tokenFor("decided");
  let code = "room_board_split_decided";
  const env = await bootGrant($, on, {
    exchange: () => ({ status: 200, text: exchangeText(CID, token, "2999-01-01T00:00:00Z") }),
    decide: () => ({ status: 409, text: errorText(code) }),
  });
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await ui.input({ key: "xmuse-pairing", text: "ABCD-EFGH" });
  for (code of ["room_board_split_decided", "room_board_split_not_proposed"]) {
    const getsBefore = env.gets.length;
    await ui.press({ key: "xmuse-approve-" + PENDING_SPLIT });
    await ui.input({ key: "xmuse-confirm", text: PENDING_PREFIX });
    expect(env.toasts[env.toasts.length - 1]).toBe("拆分已不能决定，已刷新");
    expect(env.gets.length).toBeGreaterThan(getsBefore);
  }
  await ui.unmount();
});

test("digest mismatch asks for a fresh confirm", OPTIONS, async ($, on) => {
  const token = tokenFor("changed");
  const env = await bootGrant($, on, {
    exchange: () => ({ status: 200, text: exchangeText(CID, token, "2999-01-01T00:00:00Z") }),
    decide: () => ({ status: 409, text: errorText("room_board_split_digest_mismatch") }),
  });
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await ui.input({ key: "xmuse-pairing", text: "ABCD-EFGH" });
  await ui.press({ key: "xmuse-approve-" + PENDING_SPLIT });
  await ui.input({ key: "xmuse-confirm", text: PENDING_PREFIX });
  expect(env.toasts[env.toasts.length - 1]).toBe("拆分已变化，请重新确认");
  await ui.unmount();
});

test("401 clears the grant", OPTIONS, async ($, on) => {
  const token = tokenFor("invalid");
  const env = await bootGrant($, on, {
    exchange: () => ({ status: 200, text: exchangeText(CID, token, "2999-01-01T00:00:00Z") }),
    decide: () => ({ status: 401, text: errorText("plugin_grant_invalid") }),
  });
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await ui.input({ key: "xmuse-pairing", text: "ABCD-EFGH" });
  await ui.press({ key: "xmuse-approve-" + PENDING_SPLIT });
  await ui.input({ key: "xmuse-confirm", text: PENDING_PREFIX });
  expect(env.toasts[env.toasts.length - 1]).toBe("授权已失效，请在 Web 重新授权");
  expect(await ui.find({ key: "xmuse-pairing" })).toBeDefined();
  expect(await ui.find({ type: "Text", text: /已授权 · 剩余/ })).toBeUndefined();
  await ui.unmount();
});

test("error statuses map to the generic failure label with the code number", OPTIONS, async ($, on) => {
  // Same single-engine constraint as above: one boot, mutable status.
  const token = tokenFor("fail403");
  let status = 403;
  const env = await bootGrant($, on, {
    exchange: () => ({ status: 200, text: exchangeText(CID, token, "2999-01-01T00:00:00Z") }),
    decide: () => ({ status, text: errorText("x") }),
  });
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await ui.input({ key: "xmuse-pairing", text: "ABCD-EFGH" });
  for (status of [403, 404, 415, 422]) {
    await ui.press({ key: "xmuse-approve-" + PENDING_SPLIT });
    await ui.input({ key: "xmuse-confirm", text: PENDING_PREFIX });
    expect(env.toasts[env.toasts.length - 1]).toBe("操作失败（" + String(status) + "）");
  }
  await ui.unmount();
});

test("network failure maps to the generic failure label", OPTIONS, async ($, on) => {
  const token = tokenFor("netfail");
  const env = await bootGrant($, on, {
    exchange: () => ({ status: 200, text: exchangeText(CID, token, "2999-01-01T00:00:00Z") }),
    decide: () => {
      throw new Error("unreachable");
    },
  });
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await ui.input({ key: "xmuse-pairing", text: "ABCD-EFGH" });
  await ui.press({ key: "xmuse-approve-" + PENDING_SPLIT });
  await ui.input({ key: "xmuse-confirm", text: PENDING_PREFIX });
  expect(env.toasts[env.toasts.length - 1]).toContain("操作失败");
  await ui.unmount();
});

test("revoke button drops the grant best-effort", OPTIONS, async ($, on) => {
  const token = tokenFor("revoke");
  const env = await bootGrant($, on, {
    exchange: () => ({ status: 200, text: exchangeText(CID, token, "2999-01-01T00:00:00Z") }),
    revoke: () => ({ status: 200, text: "{}" }),
  });
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await ui.input({ key: "xmuse-pairing", text: "ABCD-EFGH" });
  await ui.press({ key: "xmuse-revoke" });
  const revoked = env.posts.filter((p) => p.url.endsWith("/api/chat/plugin/grants/revoke"));
  expect(revoked).toHaveLength(1);
  expect(revoked[0].headers["Authorization"]).toBe("Bearer " + token);
  expect(revoked[0].body).toBe("{}");
  expect(await ui.find({ key: "xmuse-pairing" })).toBeDefined();
  await ui.unmount();
});

test("detach revokes and drops the grant even when revoke fails", OPTIONS, async ($, on) => {
  const token = tokenFor("detach");
  const env = await bootGrant($, on, {
    exchange: () => ({ status: 200, text: exchangeText(CID, token, "2999-01-01T00:00:00Z") }),
    revoke: () => ({ status: 500, text: "boom" }),
  });
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await ui.input({ key: "xmuse-pairing", text: "ABCD-EFGH" });
  expect(await ui.find({ type: "Text", text: /已授权 · 剩余/ })).toBeDefined();
  const detached = await $.command.run({ command: "xmuse", args: "detach" });
  expect(detached.text).toBe("xmuse 已解绑");
  expect(env.posts.filter((p) => p.url.endsWith("/api/chat/plugin/grants/revoke"))).toHaveLength(1);
  expect(await ui.find({ key: "xmuse-pairing" })).toBeDefined();
  const flat = treeText(await ui.drawn());
  expect(flat).not.toContain(token);
  await ui.unmount();
});

test("two splits decide one after the other with their own digests", OPTIONS, async ($, on) => {
  const secondId = "split_2_approve_after_first";
  const secondDigest = "sha256:" + "c".repeat(64);
  const token = tokenFor("two");
  const seenDigests: string[] = [];
  let decidedFirst = false;
  const baseProjection = clone(fx.split_pending.projection) as Record<string, unknown>;
  const env = await bootGrant($, on, {
    exchange: () => ({ status: 200, text: exchangeText(CID, token, "2999-01-01T00:00:00Z") }),
    projectionText: () => {
      const p = clone(baseProjection) as { conversation_id: string; splits: Record<string, unknown>[] };
      p["conversation_id"] = CID;
      const first = clone(p["splits"][0]) as Record<string, unknown>;
      const second = clone(p["splits"][0]) as Record<string, unknown>;
      second["split_id"] = secondId;
      second["digest"] = secondDigest;
      (second["actions"] as Record<string, Record<string, unknown>>)["decide"]["expected_digest"] = secondDigest;
      p["splits"] = decidedFirst ? [{ ...first, status: "approved" }, second] : [first, second];
      return JSON.stringify(p);
    },
    decide: (body) => {
      const b = body as Record<string, unknown>;
      seenDigests.push(String(b["expected_digest"] ?? ""));
      decidedFirst = true;
      return { status: 200, text: "{}" };
    },
  });
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await ui.input({ key: "xmuse-pairing", text: "ABCD-EFGH" });
  await ui.press({ key: "xmuse-approve-" + PENDING_SPLIT });
  await ui.input({ key: "xmuse-confirm", text: PENDING_PREFIX });
  expect(env.toasts[env.toasts.length - 1]).toBe("已批准拆分");
  await ui.press({ key: "xmuse-approve-" + secondId });
  expect(await ui.find({ key: "xmuse-confirm" })).toBeDefined();
  await ui.input({ key: "xmuse-confirm", text: "cccccc" });
  expect(env.toasts[env.toasts.length - 1]).toBe("已批准拆分");
  expect(seenDigests).toHaveLength(2);
  expect(seenDigests[0]).toBe(PENDING_DIGEST);
  expect(seenDigests[1]).toBe(secondDigest);
  await ui.unmount();
});

test("a grant for another room hides the decision buttons", OPTIONS, async ($, on) => {
  const token = tokenFor("other");
  const env = await bootGrant($, on, {
    binding: CID,
    exchange: () => ({ status: 200, text: exchangeText("conv_other_room", token, "2999-01-01T00:00:00Z") }),
  });
  void env;
  const ui = await $.ui.mount({ plugin: "xmuse", surface: "terminal", component: "Pane", requestId: "xmuse", props: paneProps(80) as never });
  await ui.input({ key: "xmuse-pairing", text: "ABCD-EFGH" });
  const buttons = await ui.findAll({ type: "Button" });
  const labels = buttonLabels(buttons);
  expect(labels.includes("批准")).toBe(false);
  expect(labels.includes("拒绝")).toBe(false);
  expect(await ui.find({ type: "Text", text: /待审批/ })).toBeDefined();
  await ui.unmount();
});
