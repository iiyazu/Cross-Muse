import { describe, expect, it } from "vitest";

import { currentPanelLink, panelLinkFromSearch, panelSearch } from "./panel-link";

describe("panel deep links", () => {
  it("round-trips every detail view through the query string", () => {
    for (const view of [
      { kind: "module", moduleId: "auth/api" },
      { kind: "split", splitId: "split_1" },
      { kind: "integration", integrationId: "int_1" },
      { kind: "execution", candidateId: "cand_1" },
      { kind: "contract", contractId: "ctr_1", version: 3 },
      { kind: "contract", contractId: "ctr_2" }
    ] as const) {
      expect(panelLinkFromSearch(panelSearch(view)).view).toEqual(view);
    }
    expect(panelSearch({ kind: "board" })).toBe("");
  });

  it("opens a review on its module, and ignores empty, oversized or unknown keys", () => {
    expect(panelLinkFromSearch("?review=m1")).toEqual({ view: { kind: "module", moduleId: "m1" }, reviewModuleId: "m1" });
    expect(panelLinkFromSearch("?module=%20%20").view).toBeNull();
    expect(panelLinkFromSearch(`?module=${"x".repeat(201)}`).view).toBeNull();
    expect(panelLinkFromSearch("?tab=board").view).toBeNull();
    expect(panelLinkFromSearch("?contract=c&v=-1").view).toEqual({ kind: "contract", contractId: "c" });
  });

  it("applies only to the Room in the address", () => {
    expect(currentPanelLink("conv_a", "/rooms/conv_a", "?module=m1").view).toEqual({ kind: "module", moduleId: "m1" });
    expect(currentPanelLink("conv_a", "/rooms/conv_b", "?module=m1").view).toBeNull();
    expect(currentPanelLink("conv_a", "/", "?module=m1").view).toBeNull();
  });
});
