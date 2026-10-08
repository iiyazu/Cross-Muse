import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  boardAttentionReasonLabel,
  boardEventKindLabel,
  boardLifecycleLabel,
  boardReasonLabel,
  boardStateLabel,
  boardVerificationStatusLabel
} from "./board-labels";

const FIXTURE_DIR = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2");

function loadProjections(): Array<Record<string, unknown>> {
  return fs
    .readdirSync(FIXTURE_DIR)
    // `<scenario>.review.json` and friends are detail goldens, not scenarios.
    .filter((name) => name.endsWith(".json") && !name.slice(0, -".json".length).includes("."))
    .map(
      (name) =>
        (
          JSON.parse(fs.readFileSync(path.join(FIXTURE_DIR, name), "utf8")) as Record<
            string,
            unknown
          >
        ).projection as Record<string, unknown>
    );
}

describe("board labels", () => {
  it("labels every state, lifecycle and verification status in the fixtures", () => {
    const states = new Set<string>();
    const lifecycles = new Set<string>();
    const statuses = new Set<string>();
    const attentionCodes = new Set<string>();
    const eventKinds = new Set<string>();
    for (const projection of loadProjections()) {
      for (const entry of (projection.modules ?? []) as Array<Record<string, unknown>>) {
        if (typeof entry.state === "string") states.add(entry.state);
        if (typeof entry.lifecycle === "string") lifecycles.add(entry.lifecycle);
        const verification = entry.verification as Record<string, unknown> | undefined;
        if (typeof verification?.status === "string") statuses.add(verification.status);
        const attention = entry.attention as Record<string, unknown> | undefined;
        if (typeof attention?.reason_code === "string") attentionCodes.add(attention.reason_code);
        if (typeof verification?.reason_code === "string") attentionCodes.add(verification.reason_code);
      }
      for (const item of (projection.attention ?? []) as Array<Record<string, unknown>>) {
        if (typeof item.reason_code === "string") attentionCodes.add(item.reason_code);
      }
      for (const event of (projection.events ?? []) as Array<Record<string, unknown>>) {
        if (typeof event.kind === "string") eventKinds.add(event.kind);
        const data = event.data as Record<string, unknown> | undefined;
        if (typeof data?.reason_code === "string") attentionCodes.add(data.reason_code);
      }
    }
    for (const state of states) {
      const label = boardStateLabel(state);
      expect(label, state).toBeTruthy();
      expect(label, state).not.toBe(state);
    }
    for (const lifecycle of lifecycles) {
      const label = boardLifecycleLabel(lifecycle);
      expect(label, lifecycle).toBeTruthy();
      expect(label, lifecycle).not.toBe(lifecycle);
    }
    for (const status of statuses) {
      const label = boardVerificationStatusLabel(status);
      expect(label, status).toBeTruthy();
      expect(label, status).not.toBe(status);
    }
    for (const code of attentionCodes) {
      const label = boardAttentionReasonLabel(code);
      expect(label, code).toBeTruthy();
      expect(label, code).not.toBe(code);
      expect(label, code).not.toContain(code);
    }
    for (const kind of eventKinds) {
      const label = boardEventKindLabel(kind);
      expect(label, kind).toBeTruthy();
      expect(label, kind).not.toBe(kind);
    }
  });

  it("labels the execution gate code that integration gate results carry", () => {
    expect(boardReasonLabel("execution_gate_failed")).toBe("门禁未通过");
  });

  it("labels every gate and job-level execution code, and keeps new ones in the family", () => {
    for (const code of [
      "execution_gate_timeout",
      "execution_gate_memory_limit",
      "execution_gate_process_limit",
      "execution_gate_scratch_limit",
      "execution_gate_resource_probe_failed",
      "execution_cancelled",
      "execution_git_metadata_invalid",
      "execution_sandbox_unavailable",
      "execution_gate_profile_marker_invalid",
      "execution_toolchain_capability_drift",
      "execution_repo_busy"
    ]) {
      const label = boardReasonLabel(code);
      expect(label, code).not.toContain(code);
      expect(label, code).not.toContain("未知原因");
    }
    expect(boardReasonLabel("execution_future_thing")).toBe("执行环境问题（execution_future_thing）");
  });

  it("renders unknown codes through the explicit unknown path", () => {
    expect(boardReasonLabel("some_future_code")).toBe("未知原因（some_future_code）");
    expect(boardAttentionReasonLabel("future_attention")).toBe("未知原因（future_attention）");
    expect(boardEventKindLabel("future_kind")).toBe("未知事件（future_kind）");
    expect(boardStateLabel("future_state")).toBe("未知状态");
  });
});

describe("decided_via labels", () => {
  it("names known sources and shows any other value as a fixed word", async () => {
    const { boardDecidedViaLabel } = await import("./board-labels");
    expect(boardDecidedViaLabel("web")).toBe("网页");
    expect(boardDecidedViaLabel("plugin:claude-code")).toBe("Claude Code 插件");
    expect(boardDecidedViaLabel("plugin:<img src=x>")).toBe("插件");
    expect(boardDecidedViaLabel("telegram")).toBe("未知来源");
    expect(boardDecidedViaLabel(null)).toBeNull();
  });
});
