// Pane tests: every fixture draws a valid tree on terminal and desktop;
// agent text appears only after expand (module detail) or after the person
// presses 查看复核材料 (review patch), only in labelled Text; status,
// toast, command and tool outputs never carry agent strings, ESC or bidi.
import { expect, mock, test } from "claude-code/testing";
import type { Engine, On } from "claude-code/testing";
import * as fx from "./fixtures.generated";
import { normalizeBoard, normalizeSummary } from "../src/api";
import { buildPaneNodes, type PaneNode } from "../src/pane";
import type { XmuseCache } from "../types/index";

const OPTIONS = { options: { pollSeconds: 1 } };
const SURFACES = ["terminal", "desktop"] as const;

const BIDI = new RegExp("[\\u061c\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069]");
const ESC = new RegExp("\\u001b");

function agentStrings(): string[] {
  const p = fx.injection_text.projection as unknown as {
    modules: { title: { text: string } }[];
    events: { data: { summary?: { text: string }; question?: { text: string }; rationale?: { text: string } } }[];
  };
  const out = [p.modules[0].title.text, p.modules[1].title.text];
  for (const e of p.events) {
    if (e.data.summary !== undefined) out.push(e.data.summary.text);
    if (e.data.question !== undefined) out.push(e.data.question.text);
    if (e.data.rationale !== undefined) out.push(e.data.rationale.text);
  }
  return out;
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

async function loadFixture(
  $: Engine,
  on: On,
  name: string,
  statuses: (string | undefined)[],
  toasts: string[],
): Promise<void> {
  const mod = (fx as unknown as Record<string, { summary: unknown; projection: unknown }>)[name];
  if (mod === undefined) throw new Error("unknown fixture " + name);
  const cid = String((mod.summary as { conversation_id: string }).conversation_id);
  mock.store(on, { "binding:/repo": cid });
  const clock = mock.clock(on);
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
    const url = e.url;
    if (url.endsWith("/board/summary")) {
      return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(mod.summary) } };
    }
    if (url.endsWith("/board")) {
      return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(mod.projection) } };
    }
    return { value: { status: 404, ok: false, headers: {}, text: "{}" } };
  });
  await $.session.start({ cwd: "/repo", surface: "terminal", isInteractive: true });
  await $.command.run({ command: "xmuse", args: "" });
  await clock.advance(1000);
  await clock.settle();
}

const FIXTURES = ["empty", "split_pending", "verified", "injection_text", "verification_error", "contract_revised_stale_dependent"] as const;

// Every golden scenario: the six review_* ones plus the twelve older ones.
const REVIEW_FIXTURES = [
  "review_participant_pending",
  "review_operator_pending",
  "review_endorsed",
  "review_objected",
  "review_escalated",
  "review_superseded",
] as const;

const OLD_FIXTURES = [
  "empty",
  "split_pending",
  "lifecycle_mix",
  "verifying_and_waiting",
  "verified",
  "verification_failed_rework",
  "verification_escalated",
  "verification_error",
  "superseded_done",
  "contract_revised_stale_dependent",
  "injection_text",
  "split_approved_via_plugin",
] as const;

const REVIEW_WORDS = /待复核|待你复核|已背书|已驳回|已升级|已验收/;

// Agent-authored review strings from every review golden: verdict summaries
// and finding texts carried by projection review events. None may ever be
// drawn: the mod keeps structured review state only.
function reviewNeedles(): string[] {
  const out: string[] = [];
  for (const name of REVIEW_FIXTURES) {
    const mod = (fx as unknown as Record<string, { projection: unknown }>)[name];
    const p = mod.projection as unknown as {
      events: {
        kind: string;
        data: { summary?: { text: string }; findings?: { text: { text: string } }[] };
      }[];
    };
    for (const e of p.events) {
      if (e.kind !== "review") continue;
      if (e.data.summary !== undefined && e.data.summary.text !== "") out.push(e.data.summary.text);
      for (const f of e.data.findings ?? []) {
        if (f.text.text !== "") out.push(f.text.text);
      }
    }
  }
  return out;
}

async function nodeDump(ui: any): Promise<string[]> {
  const out: string[] = [];
  for (const type of ["Text", "Button", "Link", "Input"]) {
    const nodes = (await ui.findAll({ type })) as unknown[];
    for (const n of nodes) out.push(JSON.stringify(n));
  }
  return out;
}

for (const name of FIXTURES) {
  test(`pane draws ${name} on terminal and desktop`, OPTIONS, async ($, on) => {
    const statuses: (string | undefined)[] = [];
    const toasts: string[] = [];
    await loadFixture($, on, name, statuses, toasts);
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({
        plugin: "xmuse",
        surface,
        component: "Pane",
        requestId: "xmuse",
        props: paneProps(80) as never,
      });
      const drawn = await ui.drawn();
      expect(drawn.type).toBe("Box");
      const header = await ui.find({ type: "Text", text: /看板|离线|未绑定/ });
      void header;
      const anyText = await ui.find({ type: "Text", text: /xmuse|看板/ });
      expect(anyText).toBeDefined();
      const markdowns = await ui.findAll({ type: "Markdown" });
      expect(markdowns).toHaveLength(0);
      await ui.unmount();
    }
  });
}

test("pane works at narrow widths", OPTIONS, async ($, on) => {
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  await loadFixture($, on, "verified", statuses, toasts);
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(24) as never,
    });
    expect((await ui.drawn()).type).toBe("Box");
    await ui.unmount();
  }
});

test("injection agent text hidden until expand, then labelled Text only", OPTIONS, async ($, on) => {
  const needles = agentStrings();
  expect(needles.length).toBeGreaterThan(0);
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  await loadFixture($, on, "injection_text", statuses, toasts);
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(80) as never,
    });
    // State is session-scoped: a previous surface iteration may have left
    // the module expanded. Collapse first so the pre-press check is valid.
    if (await ui.find({ type: "Text", text: /agent 自述/ })) {
      await ui.press({ key: "expand-alpha" });
    }
    for (const n of needles.slice(0, 3)) {
      expect(await ui.find({ type: "Text", text: n.slice(0, 40) })).toBeUndefined();
    }
    expect(await ui.find({ type: "Text", text: /agent 自述/ })).toBeUndefined();
    await ui.press({ key: "expand-alpha" });
    const label = await ui.find({ type: "Text", text: /agent 自述 · 未验证/ });
    expect(label).toBeDefined();
    const shown = await ui.find({ type: "Text", text: needles[0].slice(0, 40) });
    expect(shown).toBeDefined();
    expect(shown?.type).toBe("Text");
    const distinctive = await ui.find({ type: "Text", text: /progress#5\/summary/ });
    expect(distinctive).toBeDefined();
    const markdowns = await ui.findAll({ type: "Markdown" });
    expect(markdowns).toHaveLength(0);
    const links = await ui.findAll({ type: "Link" });
    for (const l of links) expect(l.text).not.toContain(needles[0].slice(0, 40));
    await ui.press({ key: "expand-alpha" });
    await ui.unmount();
  }
  for (const t of statuses) {
    for (const n of needles) expect(String(t)).not.toContain(n);
    expect(BIDI.test(String(t))).toBe(false);
    expect(ESC.test(String(t))).toBe(false);
  }
  for (const t of toasts) {
    for (const n of needles) expect(t).not.toContain(n);
  }
  const status = await $.command.run({ command: "xmuse", args: "status" });
  const called = await $.tool.call({ tool: "mcp__xmuse__status" });
  const result = String((called as unknown as { result?: unknown }).result ?? "");
  for (const n of needles) {
    expect(String(status.text)).not.toContain(n);
    expect(result).not.toContain(n);
  }
  expect(BIDI.test(String(status.text))).toBe(false);
  expect(ESC.test(String(status.text))).toBe(false);
});

test("proposed splits show no web link", OPTIONS, async ($, on) => {
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  await loadFixture($, on, "split_pending", statuses, toasts);
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(80) as never,
    });
    expect(await ui.find({ type: "Text", text: /待审批/ })).toBeDefined();
    expect(await ui.findAll({ type: "Link" })).toHaveLength(0);
    await ui.unmount();
  }
});

test("unknown module states render as ?value", OPTIONS, async ($, on) => {
  const board = JSON.parse(JSON.stringify(fx.verified.projection)) as {
    modules: { module_id: string; state: string }[];
  };
  board.modules[0].state = "future_state_xyz";
  const summary = JSON.parse(JSON.stringify(fx.verified.summary)) as { conversation_id: string };
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  mock.store(on, { "binding:/repo": summary.conversation_id });
  const clock = mock.clock(on);
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
    if (e.url.endsWith("/board/summary")) {
      return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(fx.verified.summary) } };
    }
    if (e.url.endsWith("/board")) {
      return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(board) } };
    }
    return { value: { status: 404, ok: false, headers: {}, text: "{}" } };
  });
  await $.session.start({ cwd: "/repo", surface: "terminal", isInteractive: true });
  await $.command.run({ command: "xmuse", args: "" });
  await clock.advance(1000);
  await clock.settle();
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(80) as never,
    });
    expect((await ui.drawn()).type).toBe("Box");
    expect(await ui.find({ type: "Text", text: /\?future_state_xyz/ })).toBeDefined();
    await ui.unmount();
  }
  void statuses;
  void toasts;
});

for (const name of REVIEW_FIXTURES) {
  test(`pane draws ${name} on terminal and desktop`, OPTIONS, async ($, on) => {
    const statuses: (string | undefined)[] = [];
    const toasts: string[] = [];
    await loadFixture($, on, name, statuses, toasts);
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({
        plugin: "xmuse",
        surface,
        component: "Pane",
        requestId: "xmuse",
        props: paneProps(80) as never,
      });
      const drawn = await ui.drawn();
      expect(drawn.type).toBe("Box");
      const header = await ui.find({ type: "Text", text: /看板|离线|未绑定/ });
      void header;
      const markdowns = await ui.findAll({ type: "Markdown" });
      expect(markdowns).toHaveLength(0);
      // No review verdict channel: no Button or Input is added for reviews.
      const buttons = await ui.findAll({ type: "Button" });
      for (const b of buttons) {
        expect(JSON.stringify(b)).not.toMatch(/批准|拒绝/);
      }
      const inputs = await ui.findAll({ type: "Input" });
      expect(inputs).toHaveLength(1);
      await ui.unmount();
    }
  });
}

for (const c of [
  { name: "review_participant_pending", present: ["待复核", "✓ 已验证", "· 待复核"], absent: ["待你复核", "已验收", "已背书", "已驳回", "在 Web 复核"] },
  { name: "review_operator_pending", present: ["待你复核", "已验收", "已背书"], absent: ["已驳回"] },
  { name: "review_endorsed", present: ["已验收", "已背书"], absent: ["待你复核", "已驳回", "在 Web 复核"] },
  { name: "review_objected", present: ["已驳回", "阻塞 1 主要 1 次要 1"], absent: ["已验收", "已背书", "在 Web 复核"] },
  { name: "review_escalated", present: ["待你复核", "· 已升级"], absent: ["已验收", "已背书", "已驳回"] },
] as const) {
  test(`review rows: ${c.name}`, OPTIONS, async ($, on) => {
    const statuses: (string | undefined)[] = [];
    const toasts: string[] = [];
    await loadFixture($, on, c.name, statuses, toasts);
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({
        plugin: "xmuse",
        surface,
        component: "Pane",
        requestId: "xmuse",
        props: paneProps(80) as never,
      });
      for (const want of c.present) {
        expect(await ui.find({ type: "Text", text: new RegExp(want) })).toBeDefined();
      }
      for (const ban of c.absent) {
        expect(await ui.find({ type: "Text", text: new RegExp(ban) })).toBeUndefined();
      }
      await ui.unmount();
    }
  });
}

test("superseded review shows nothing review-specific", OPTIONS, async ($, on) => {
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  await loadFixture($, on, "review_superseded", statuses, toasts);
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(80) as never,
    });
    expect(await ui.find({ type: "Text", text: REVIEW_WORDS })).toBeUndefined();
    expect(await ui.find({ type: "Link", text: /在 Web 复核/ })).toBeUndefined();
    await ui.unmount();
  }
});

test("operator-pending review offers no link and no button without a grant", OPTIONS, async ($, on) => {
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  await loadFixture($, on, "review_operator_pending", statuses, toasts);
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(80) as never,
    });
    expect(await ui.find({ type: "Text", text: /待你复核/ })).toBeDefined();
    expect(await ui.findAll({ type: "Link" })).toHaveLength(0);
    const buttons = await ui.findAll({ type: "Button" });
    for (const b of buttons) {
      expect(JSON.stringify(b)).not.toMatch(/查看复核材料|认可|反对/);
    }
    await ui.unmount();
  }
});

test("unknown review status renders as ?value", OPTIONS, async ($, on) => {
  const board = JSON.parse(JSON.stringify(fx.review_participant_pending.projection)) as {
    modules: { module_id: string; review: { status: string } }[];
  };
  board.modules[0].review.status = "future_review_xyz";
  const summary = JSON.parse(JSON.stringify(fx.review_participant_pending.summary)) as { conversation_id: string };
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  mock.store(on, { "binding:/repo": summary.conversation_id });
  const clock = mock.clock(on);
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
    if (e.url.endsWith("/board/summary")) {
      return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(fx.review_participant_pending.summary) } };
    }
    if (e.url.endsWith("/board")) {
      return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(board) } };
    }
    return { value: { status: 404, ok: false, headers: {}, text: "{}" } };
  });
  await $.session.start({ cwd: "/repo", surface: "terminal", isInteractive: true });
  await $.command.run({ command: "xmuse", args: "" });
  await clock.advance(1000);
  await clock.settle();
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(80) as never,
    });
    expect((await ui.drawn()).type).toBe("Box");
    expect(await ui.find({ type: "Text", text: /\?future_review_xyz/ })).toBeDefined();
    await ui.unmount();
  }
  void statuses;
  void toasts;
});

test("missing review fields draw as no review", OPTIONS, async ($, on) => {
  const board = JSON.parse(JSON.stringify(fx.review_participant_pending.projection));
  for (const m of (board as { modules: Record<string, unknown>[] }).modules) delete m["review"];
  const summary = JSON.parse(JSON.stringify(fx.review_participant_pending.summary)) as { conversation_id: string };
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  mock.store(on, { "binding:/repo": summary.conversation_id });
  const clock = mock.clock(on);
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
    if (e.url.endsWith("/board/summary")) {
      return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(fx.review_participant_pending.summary) } };
    }
    if (e.url.endsWith("/board")) {
      return { value: { status: 200, ok: true, headers: {}, text: JSON.stringify(board) } };
    }
    return { value: { status: 404, ok: false, headers: {}, text: "{}" } };
  });
  await $.session.start({ cwd: "/repo", surface: "terminal", isInteractive: true });
  await $.command.run({ command: "xmuse", args: "" });
  await clock.advance(1000);
  await clock.settle();
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(80) as never,
    });
    expect((await ui.drawn()).type).toBe("Box");
    expect(await ui.find({ type: "Text", text: REVIEW_WORDS })).toBeUndefined();
    await ui.unmount();
  }
  void statuses;
  void toasts;
});

for (const name of OLD_FIXTURES) {
  test(`pre-review rows unchanged: ${name}`, OPTIONS, async ($, on) => {
    const statuses: (string | undefined)[] = [];
    const toasts: string[] = [];
    await loadFixture($, on, name, statuses, toasts);
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({
        plugin: "xmuse",
        surface,
        component: "Pane",
        requestId: "xmuse",
        props: paneProps(80) as never,
      });
      expect((await ui.drawn()).type).toBe("Box");
      expect(await ui.find({ type: "Text", text: REVIEW_WORDS })).toBeUndefined();
      expect(await ui.find({ type: "Link", text: /在 Web 复核/ })).toBeUndefined();
      for (const dump of await nodeDump(ui)) {
        expect(dump).not.toContain("board-reviews");
        expect(dump).not.toContain("material");
        expect(dump).not.toContain("decision");
      }
      await ui.unmount();
    }
    void statuses;
    void toasts;
  });
}

for (const name of [...REVIEW_FIXTURES, ...OLD_FIXTURES] as const) {
  test(`no review summary or finding text in ${name}`, OPTIONS, async ($, on) => {
    const needles = reviewNeedles();
    expect(needles.length).toBeGreaterThan(0);
    const statuses: (string | undefined)[] = [];
    const toasts: string[] = [];
    await loadFixture($, on, name, statuses, toasts);
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({
        plugin: "xmuse",
        surface,
        component: "Pane",
        requestId: "xmuse",
        props: paneProps(80) as never,
      });
      // Expanded detail must stay free of review text too. Toggle every
      // module once per surface: the first surface expands, the second
      // collapses, so both states are checked across the two iterations.
      for (const mod of ["alpha", "beta", "frontend", "sidecar", "m-assigned", "m-blocked", "m-claimed", "m-ready", "m-working"]) {
        try {
          await ui.press({ key: "expand-" + mod });
        } catch {
          // module absent in this scenario: ignore
        }
      }
      for (const n of needles) {
        // 120 chars: the injection fixture reuses the review texts'
        // opening words, so short prefixes would collide across kinds.
        expect(await ui.find({ type: "Text", text: n.slice(0, 120) })).toBeUndefined();
      }
      for (const dump of await nodeDump(ui)) {
        expect(dump).not.toContain("board-reviews");
        expect(dump).not.toContain("material");
        expect(dump).not.toContain("decision");
      }
      await ui.unmount();
    }
    for (const t of statuses) {
      for (const n of needles) expect(String(t)).not.toContain(n);
    }
    for (const t of toasts) {
      for (const n of needles) expect(t).not.toContain(n);
    }
    const status = await $.command.run({ command: "xmuse", args: "status" });
    const called = await $.tool.call({ tool: "mcp__xmuse__status" });
    const result = String((called as unknown as { result?: unknown }).result ?? "");
    for (const n of needles) {
      expect(String(status.text)).not.toContain(n);
      expect(result).not.toContain(n);
    }
  });
}

// ------------------------------------------------------- integration (M2b)

const INTEGRATION_PANE_SCENARIOS = [
  "integration_conflicted",
  "integration_dependency_upgrade",
  "integration_error",
  "integration_fallback_to_incumbent",
  "integration_gate_failed",
  "integration_integrated",
  "integration_pending_running",
  "review_endorsed_integrated",
] as const;

for (const name of INTEGRATION_PANE_SCENARIOS) {
  test(`pane draws ${name} without paths or job ids`, OPTIONS, async ($, on) => {
    const statuses: (string | undefined)[] = [];
    const toasts: string[] = [];
    await loadFixture($, on, name, statuses, toasts);
    for (const surface of SURFACES) {
      const ui = await $.ui.mount({
        plugin: "xmuse",
        surface,
        component: "Pane",
        requestId: "xmuse",
        props: paneProps(80) as never,
      });
      expect((await ui.drawn()).type).toBe("Box");
      const dumps = await nodeDump(ui);
      for (const dump of dumps) {
        expect(dump).not.toContain("boardintegration_");
        expect(dump).not.toContain("docs/");
        expect(dump).not.toContain("expected Hello, Ada!");
        expect(dump).not.toContain("board/integrations");
      }
      await ui.unmount();
    }
    for (const t of statuses) {
      expect(String(t)).not.toContain("boardintegration_");
    }
    const status = await $.command.run({ command: "xmuse", args: "status" });
    expect(String(status.text)).not.toContain("boardintegration_");
  });
}

test("pane fallback row and room line", OPTIONS, async ($, on) => {
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  await loadFixture($, on, "integration_fallback_to_incumbent", statuses, toasts);
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(80) as never,
    });
    expect(await ui.find({ type: "Text", text: /集成冲突 1 路径·分支为旧版本/ })).toBeDefined();
    expect(await ui.find({ type: "Text", text: /已验证 3 · 已集成 2/ })).toBeDefined();
    expect(await ui.find({ type: "Text", text: /集成分支 8d191a5e/ })).toBeDefined();
    await ui.unmount();
  }
});

test("pane gate_failed suspect row and lead label", OPTIONS, async ($, on) => {
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  await loadFixture($, on, "integration_gate_failed", statuses, toasts);
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(80) as never,
    });
    expect(await ui.find({ type: "Text", text: /门禁失败·嫌疑/ })).toBeDefined();
    expect(await ui.find({ type: "Text", text: /集成门禁失败/ })).toBeDefined();
    await ui.unmount();
  }
});

test("pane error operator label has no job id target", OPTIONS, async ($, on) => {
  const statuses: (string | undefined)[] = [];
  const toasts: string[] = [];
  await loadFixture($, on, "integration_error", statuses, toasts);
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({
      plugin: "xmuse",
      surface,
      component: "Pane",
      requestId: "xmuse",
      props: paneProps(80) as never,
    });
    expect(await ui.find({ type: "Text", text: /集成异常（宿主自动重试）/ })).toBeDefined();
    const dumps = await nodeDump(ui);
    for (const dump of dumps) expect(dump).not.toContain("boardintegration_");
    await ui.unmount();
  }
});

// ------------------------------------------------- review pane nodes (MWC v1)

const MWC_REVIEW_ID = "boardreview_0000000000000000000000000000002e";
const MWC_REVIEW_DIGEST = "sha256:2df9fdc1871ddcd97c6d419b27d5e4f10c6dd82ade419d6c431f080d81fa0db5";
const MWC_CID = String(
  (fx.review_operator_pending.summary as { conversation_id: string }).conversation_id,
);

function mwcCache(
  grant: XmuseCache["grant"],
  extra?: { confirming?: XmuseCache["confirming"]; material?: XmuseCache["material"] },
): XmuseCache {
  const summary = normalizeSummary(fx.review_operator_pending.summary);
  const board = normalizeBoard(fx.review_operator_pending.projection);
  if (summary === null || board === null) throw new Error("bad review fixture");
  return {
    binding: MWC_CID,
    cwd: "/repo",
    summary,
    board,
    summaryEtag: null,
    boardEtag: null,
    lastPollAt: null,
    offline: false,
    baselined: true,
    seenAttention: [],
    seenStates: {},
    failCount: 0,
    nextRetryAt: 0,
    paneOpen: true,
    expanded: {},
    grant,
    confirming: extra?.confirming ?? null,
    material: extra?.material ?? null,
    formEpoch: 0,
  };
}

const MWC_GRANT = {
  grantId: "grant_test_1",
  expiresAt: "2999-01-01T00:00:00Z",
  conversationIds: [MWC_CID],
  scopes: ["room.create", "room.message", "board.split.decide", "board.review.decide"],
};

function nodeTexts(nodes: PaneNode[]): string[] {
  return nodes.filter((n) => n.type === "text").map((n) => (n as { text: string }).text);
}

function nodeKeys(nodes: PaneNode[]): string[] {
  return nodes.filter((n) => n.type !== "text").map((n) => (n as { key: string }).key);
}

function nodeLabels(nodes: PaneNode[]): string[] {
  return nodes
    .filter((n) => n.type === "button" || n.type === "input")
    .map((n) => (n as { label: string }).label);
}

test("granted operator-pending review offers the material button, never a link", OPTIONS, async () => {
  const nodes = buildPaneNodes(mwcCache({ ...MWC_GRANT }), Date.parse("2026-01-01T00:00:00Z"));
  expect(nodeKeys(nodes)).toContain("xmuse-material-" + MWC_REVIEW_ID);
  expect(nodes.some((n) => n.type === "link")).toBe(false);
  for (const l of nodeLabels(nodes)) expect(l).not.toContain("boardreview_");
});

test("pairing copy points at the terminal", OPTIONS, async () => {
  const cache = mwcCache(null);
  cache.binding = null;
  cache.summary = null;
  cache.board = null;
  const texts = nodeTexts(buildPaneNodes(cache, Date.parse("2026-01-01T00:00:00Z")));
  expect(texts.some((t) => t.includes("xmuse-workroom pair"))).toBe(true);
  expect(texts.some((t) => t.includes("Web"))).toBe(false);
});

test("review buttons need the review scope on this room", OPTIONS, async () => {
  const noScope = buildPaneNodes(
    mwcCache({ ...MWC_GRANT, scopes: ["board.split.decide"] }),
    Date.parse("2026-01-01T00:00:00Z"),
  );
  expect(nodeKeys(noScope).some((k) => k.startsWith("xmuse-material-"))).toBe(false);
  const otherRoom = buildPaneNodes(
    mwcCache({ ...MWC_GRANT, conversationIds: ["conv_other_room"] }),
    Date.parse("2026-01-01T00:00:00Z"),
  );
  expect(nodeKeys(otherRoom).some((k) => k.startsWith("xmuse-material-"))).toBe(false);
  const participant = buildPaneNodes(
    mwcCache({ ...MWC_GRANT }),
    Date.parse("2026-01-01T00:00:00Z"),
  );
  // participant-pending alpha offers no button, operator-pending beta does
  expect(nodeKeys(participant).filter((k) => k.startsWith("xmuse-material-"))).toEqual([
    "xmuse-material-" + MWC_REVIEW_ID,
  ]);
});

test("material block labels the patch untrusted and keeps ids out of labels", OPTIONS, async () => {
  const nodes = buildPaneNodes(
    mwcCache(
      { ...MWC_GRANT },
      { material: { reviewId: MWC_REVIEW_ID, digest: MWC_REVIEW_DIGEST, text: "PATCH-MWC-XYZ +return to_decimal(x);", truncated: true } },
    ),
    Date.parse("2026-01-01T00:00:00Z"),
  );
  const texts = nodeTexts(nodes);
  expect(texts.some((t) => t.includes("复核材料 · agent 撰写，未验证"))).toBe(true);
  expect(texts.some((t) => t.includes("PATCH-MWC-XYZ"))).toBe(true);
  const keys = nodeKeys(nodes);
  for (const k of ["xmuse-endorse-" + MWC_REVIEW_ID, "xmuse-object-" + MWC_REVIEW_ID, "xmuse-close-material"]) {
    expect(keys).toContain(k);
  }
  expect(keys).not.toContain("xmuse-material-" + MWC_REVIEW_ID);
  for (const l of nodeLabels(nodes)) {
    expect(l).not.toContain("boardreview_");
    expect(l).not.toContain("PATCH-MWC-XYZ");
  }
});

test("material keeps the patch's lines and sanitizes each one", OPTIONS, async () => {
  const patch = "diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n-old\n+new\x1b[31m red\n+‮flip";
  const nodes = buildPaneNodes(
    mwcCache({ ...MWC_GRANT }, { material: { reviewId: MWC_REVIEW_ID, digest: MWC_REVIEW_DIGEST, text: patch, truncated: false } }),
    Date.parse("2026-01-01T00:00:00Z"),
  );
  const texts = nodeTexts(nodes);
  for (const line of ["diff --git a/x b/x", "--- a/x", "+++ b/x", "-old"]) expect(texts).toContain(line);
  for (const t of texts) {
    expect(t).not.toContain("\n");
    expect(t).not.toContain("\x1b");
    expect(t).not.toContain("‮");
  }
});

test("pairing copy names the bound room for a re-pair", OPTIONS, async () => {
  const cache = mwcCache(null);
  const texts = nodeTexts(buildPaneNodes(cache, Date.parse("2026-01-01T00:00:00Z")));
  expect(texts.some((t) => t.includes("xmuse-workroom pair --room " + MWC_CID))).toBe(true);
});

test("a live grant that leaves the bound room out says so and takes a new code", OPTIONS, async () => {
  const at = Date.parse("2026-01-01T00:00:00Z");
  const otherRoom = buildPaneNodes(mwcCache({ ...MWC_GRANT, conversationIds: ["conv_other_room"] }), at);
  const texts = nodeTexts(otherRoom);
  expect(texts.some((t) => t.startsWith("已授权（不含当前房间）"))).toBe(true);
  expect(texts.some((t) => t.startsWith("已授权 · "))).toBe(false);
  expect(texts.some((t) => t.includes("xmuse-workroom pair --room " + MWC_CID))).toBe(true);
  expect(nodeKeys(otherRoom)).toContain("xmuse-pairing");
  expect(nodeKeys(otherRoom)).toContain("xmuse-revoke");

  const covered = buildPaneNodes(mwcCache({ ...MWC_GRANT }), at);
  expect(nodeTexts(covered).some((t) => t.startsWith("已授权 · "))).toBe(true);
  expect(nodeKeys(covered)).not.toContain("xmuse-pairing");
});

test("object without a reason asks for the reason first", OPTIONS, async () => {
  const nodes = buildPaneNodes(
    mwcCache(
      { ...MWC_GRANT },
      { confirming: { kind: "review", splitId: "", reviewId: MWC_REVIEW_ID, decision: "object", reason: null } },
    ),
    Date.parse("2026-01-01T00:00:00Z"),
  );
  expect(nodeKeys(nodes)).toContain("xmuse-review-reason");
  expect(nodeKeys(nodes)).not.toContain("xmuse-confirm");
});

test("endorse and reasoned object ask for the digest guard", OPTIONS, async () => {
  for (const confirming of [
    { kind: "review", splitId: "", reviewId: MWC_REVIEW_ID, decision: "endorse", reason: null },
    { kind: "review", splitId: "", reviewId: MWC_REVIEW_ID, decision: "object", reason: "小数精度不对" },
  ]) {
    const nodes = buildPaneNodes(mwcCache({ ...MWC_GRANT }, { confirming }), Date.parse("2026-01-01T00:00:00Z"));
    expect(nodeKeys(nodes)).toContain("xmuse-confirm");
    expect(nodeKeys(nodes)).toContain("xmuse-cancel-confirm");
    expect(nodeKeys(nodes)).not.toContain("xmuse-review-reason");
  }
});
