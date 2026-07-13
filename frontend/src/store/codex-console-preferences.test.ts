import { describe, expect, it } from "vitest";

import {
  persistCodexConsolePreference,
  readCodexConsolePreference
} from "./codex-console-preferences";

describe("codex console preferences", () => {
  it("stores independent per-participant modes", () => {
    const storage = window.sessionStorage;
    storage.clear();
    persistCodexConsolePreference(storage, "architect", "plan", 1);
    persistCodexConsolePreference(storage, "reviewer", "default", 2);
    expect(readCodexConsolePreference(storage, "architect")).toBe("plan");
    expect(readCodexConsolePreference(storage, "reviewer")).toBe("default");
  });

  it("fails closed for corrupt and future storage", () => {
    const storage = window.sessionStorage;
    storage.setItem("xmuse.codex-console-preferences.v1", "{not-json");
    expect(readCodexConsolePreference(storage, "architect")).toBe("default");
    storage.setItem(
      "xmuse.codex-console-preferences.v1",
      JSON.stringify({ version: 2, participants: { architect: { mode: "plan", updatedAt: 1 } } })
    );
    expect(readCodexConsolePreference(storage, "architect")).toBe("default");
  });

  it("bounds retained preferences", () => {
    const storage = window.sessionStorage;
    storage.clear();
    for (let index = 0; index < 55; index += 1) {
      persistCodexConsolePreference(storage, `participant-${index}`, "plan", index);
    }
    expect(readCodexConsolePreference(storage, "participant-0")).toBe("default");
    expect(readCodexConsolePreference(storage, "participant-54")).toBe("plan");
  });
});
