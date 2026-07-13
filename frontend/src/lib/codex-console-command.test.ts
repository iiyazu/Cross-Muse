import { describe, expect, it } from "vitest";

import { parseCodexConsoleInput } from "./codex-console-command";

describe("Codex Console alias parser", () => {
  it("turns ordinary text into one native console turn using the local preference", () => {
    expect(parseCodexConsoleInput("  inspect the failing test  ", "plan")).toEqual({
      kind: "action",
      capabilityId: "console_turn_start",
      safeRequest: { text: "inspect the failing test", mode: "plan" }
    });
  });

  it("keeps parameterless plan/default choices local", () => {
    expect(parseCodexConsoleInput("/plan")).toEqual({ kind: "preference", mode: "plan" });
    expect(parseCodexConsoleInput("/DEFAULT")).toEqual({ kind: "preference", mode: "default" });
    expect(parseCodexConsoleInput("/plan make a bounded plan")).toEqual({
      kind: "action",
      capabilityId: "console_turn_start",
      safeRequest: { text: "make a bounded plan", mode: "plan" }
    });
  });

  it("maps goal aliases only to closed native capabilities", () => {
    expect(parseCodexConsoleInput("/goal")).toMatchObject({ capabilityId: "goal_get" });
    expect(parseCodexConsoleInput("/goal pause")).toMatchObject({ capabilityId: "goal_pause" });
    expect(parseCodexConsoleInput("/goal resume")).toMatchObject({ capabilityId: "goal_resume" });
    expect(parseCodexConsoleInput("/goal clear")).toMatchObject({ capabilityId: "goal_clear" });
    expect(parseCodexConsoleInput("/goal ship the console")).toEqual({
      kind: "action",
      capabilityId: "goal_set",
      safeRequest: { objective: "ship the console", token_budget: 100_000 }
    });
    expect(parseCodexConsoleInput("/goal --budget 25000 ship it")).toEqual({
      kind: "action",
      capabilityId: "goal_set",
      safeRequest: { objective: "ship it", token_budget: 25_000 }
    });
  });

  it.each([
    ["/model gpt-5.6", "settings_update", { model: "gpt-5.6" }],
    ["/model", "models_list", {}],
    ["/effort high", "settings_update", { effort: "high" }],
    ["/steer focus on the guard", "turn_steer", { text: "focus on the guard" }],
    ["/interrupt", "turn_interrupt", {}],
    ["/compact", "compact_start", {}],
    ["/review", "review_start", { target: "uncommitted" }],
    ["/review base", "review_start", { target: "base" }],
    ["/status", "goal_get", {}]
  ])("maps %s to %s", (input, capabilityId, safeRequest) => {
    expect(parseCodexConsoleInput(String(input))).toEqual({
      kind: "action",
      capabilityId,
      safeRequest
    });
  });

  it.each([
    "/rpc thread/delete",
    "/unknown",
    "/interrupt now",
    "/compact now",
    "/steer",
    "/effort ultra",
    "/effort very high",
    "/review custom",
    "/status now",
    "/goal --budget 25000",
    "/goal --budget 9 unsafe"
  ])("fails closed for unsupported input %s", (input) => {
    expect(parseCodexConsoleInput(input).kind).toBe("error");
  });

  it("does not turn empty input into an action", () => {
    expect(parseCodexConsoleInput(" \n ")).toEqual({ kind: "empty" });
  });
});
