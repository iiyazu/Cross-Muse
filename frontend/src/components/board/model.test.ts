import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { normalizeBoardSummary, normalizeRoomBoardProjection } from "@/lib/board-api";
import type { RoomBoardProjection, RoomBoardSummary } from "@/lib/board-types";

import { boardOverview, boardVisible, modulePhrase, splitAttention, trustLevel, trustSteps } from "./model";

const FIXTURE_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");

function load(name: string): { projection: RoomBoardProjection; summary: RoomBoardSummary } {
  const raw = JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, `${name}.json`), "utf8")) as Record<string, unknown>;
  return { projection: normalizeRoomBoardProjection(raw.projection), summary: normalizeBoardSummary(raw.summary) };
}

function scenarios(): string[] {
  return fs.readdirSync(FIXTURE_DIR)
    .filter((name) => name.endsWith(".json") && !name.slice(0, -".json".length).includes("."))
    .map((name) => name.slice(0, -".json".length));
}

function moduleOf(projection: RoomBoardProjection, id: string) {
  const found = projection.modules.find((module) => module.module_id === id);
  if (!found) throw new Error(`fixture has no module ${id}`);
  return found;
}

describe("board view model", () => {
  it("counts completion only from accepted and integration only at the current verification, in every fixture", () => {
    for (const name of scenarios()) {
      const { projection, summary } = load(name);
      const overview = boardOverview(projection, summary);
      expect(overview.accepted, name).toBe(summary.accepted_total);
      expect(overview.integrated, name).toBe(summary.integrated_total);
      // The bar is built from the projection and must agree with the server's numbers.
      expect(overview.levels.integrated, name).toBe(summary.integrated_total);
      expect(overview.levels.integrated + overview.levels.accepted, name).toBe(summary.accepted_total);
      expect(overview.segments.length, name).toBe(projection.modules.length);
    }
  });

  it("never marks a module complete unless it is accepted", () => {
    for (const name of scenarios()) {
      for (const entry of load(name).projection.modules) {
        const level = trustLevel(entry);
        expect(level === "accepted" || level === "integrated", `${name}/${entry.module_id}`).toBe(entry.accepted);
      }
    }
  });

  it("draws a claim and a host proof with different glyphs", () => {
    for (const name of scenarios()) {
      const { projection } = load(name);
      for (const entry of projection.modules) {
        const [claim, verify] = trustSteps(entry, projection.capabilities);
        if (entry.lifecycle === "done_claimed") expect(claim.tone, name).toBe("claim");
        if (entry.verification.status === "passed") expect(verify.tone, name).toBe("pass");
        else expect(verify.tone, name).not.toBe("pass");
      }
    }
  });

  it("shows review and integration axes only when the room has those capabilities", () => {
    const off = load("verified").projection;
    expect(off.capabilities.reviews).toBe(0);
    expect(trustSteps(off.modules[0], off.capabilities).map((step) => step.axis)).toEqual(["claim", "verify", "integrate"]);
    const on = load("review_endorsed").projection;
    expect(trustSteps(on.modules[0], on.capabilities).map((step) => step.axis)).toEqual(["claim", "verify", "review", "integrate"]);
    const none = { ...off.capabilities, integrations: 0 };
    expect(trustSteps(off.modules[0], none).map((step) => step.axis)).toEqual(["claim", "verify"]);
  });

  it("keeps a verified-but-objected module out of completion and says why", () => {
    const { projection } = load("review_objected");
    const alpha = moduleOf(projection, "alpha");
    expect(trustLevel(alpha)).toBe("verified");
    const review = trustSteps(alpha, projection.capabilities).find((step) => step.axis === "review");
    expect(review?.tone).toBe("fail");
    // The owner must act on the objection, so the phrase names who, not a completion word.
    expect(modulePhrase(alpha, projection.capabilities)).toMatchObject({ who: "等 Owner", tone: "neutral" });
  });

  it("asks the operator only for operator attention and routes the rest to agents", () => {
    const { projection } = load("review_operator_pending");
    const beta = moduleOf(projection, "beta");
    expect(trustSteps(beta, projection.capabilities).find((step) => step.axis === "review")?.label).toBe("待你复核");
    expect(modulePhrase(beta, projection.capabilities)).toMatchObject({ who: "需要你", tone: "attn" });
    const { mine, agents } = splitAttention(projection.attention);
    expect(mine.map((item) => item.module_id)).toEqual(["beta"]);
    expect(agents).toEqual([]);

    const mixed = load("lifecycle_mix").projection;
    const split = splitAttention(mixed.attention);
    expect(split.mine).toEqual([]);
    expect(split.agents.map((item) => item.kind)).toEqual(["lead"]);
  });

  it("says that a conflicted module that fell back still has its older version in the branch", () => {
    const { projection } = load("integration_fallback_to_incumbent");
    const m1 = moduleOf(projection, "m1");
    expect(trustLevel(m1)).toBe("accepted");
    const integrate = trustSteps(m1, projection.capabilities).find((step) => step.axis === "integrate");
    expect(integrate).toMatchObject({ tone: "fail", label: "冲突" });
    expect(integrate?.detail).toContain("分支中是旧版本");
    expect(trustLevel(moduleOf(projection, "m2"))).toBe("integrated");
  });

  it("does not repeat the completion word for accepted modules", () => {
    const { projection } = load("integration_integrated");
    for (const entry of projection.modules.filter((candidate) => candidate.accepted && candidate.attention.kind === "none")) {
      expect(modulePhrase(entry, projection.capabilities).text).not.toContain("已验收");
    }
  });

  it("hides the board for a room with no verification and no board state", () => {
    const { projection, summary } = load("split_pending");
    expect(boardVisible(projection, summary)).toBe(true);
    const empty = { ...projection, capabilities: { ...projection.capabilities, verification: 0 }, modules: [], splits: [] };
    expect(boardVisible(empty, null)).toBe(false);
    expect(boardVisible(null, null)).toBe(false);
  });
});

describe("rework on the verification step", () => {
  it("says how many rounds of rework came before the first pass, from the contract counter", () => {
    const { projection } = load("review_endorsed");
    const passed = projection.modules.find((module) => module.verification.status === "passed");
    if (!passed) throw new Error("fixture has no verified module");
    const name = () => null;
    const verify = (module: typeof passed) => trustSteps(module, projection.capabilities, name).find((step) => step.axis === "verify");
    expect(verify({ ...passed, counters: { ...passed.counters, rework_rounds: 0 } })?.detail).toBeNull();
    expect(verify({ ...passed, counters: { ...passed.counters, rework_rounds: 2 } })?.detail).toBe("返工 2 次后通过");
  });
});
