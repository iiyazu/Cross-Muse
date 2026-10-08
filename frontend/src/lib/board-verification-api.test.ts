import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { normalizeBoardVerificationDetail } from "./board-verification-api";

const FIXTURE = path.resolve(process.cwd(), "../docs/contracts/fixtures/board_v2/verification_failed_rework.verification.json");

describe("board verification detail (§5.2)", () => {
  it("normalizes the golden failed verification with its gate output tail as AgentText", () => {
    const detail = normalizeBoardVerificationDetail(JSON.parse(fs.readFileSync(FIXTURE, "utf8")));
    expect(detail.status).toBe("failed");
    expect(detail.reason_code).toBe("board_verification_gate_failed");
    expect(detail.gates).toHaveLength(1);
    expect(detail.gates[0]?.gate_id).toBe("patch_diff_check");
    expect(detail.gates[0]?.output_tail?.untrusted).toBe(true);
    expect(detail.gates[0]?.output_tail?.text).toContain("Diff check failed");
  });

  it("refuses another schema", () => {
    expect(() => normalizeBoardVerificationDetail({ schema_version: "room_board_verification/v9" })).toThrow();
    expect(() => normalizeBoardVerificationDetail(null)).toThrow();
  });
});
