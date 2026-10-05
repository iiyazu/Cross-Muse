import { describe, expect, it } from "vitest";

import {
  emptyRoomIntegration,
  emptySummaryIntegration,
  noneModuleIntegration
} from "./board-integration-types";

describe("integration type defaults", () => {
  it("reports the none values for a module with no candidate", () => {
    expect(noneModuleIntegration()).toEqual({
      status: "none",
      statusRaw: null,
      integration_id: null,
      verification_id: null,
      integrated_verification_id: null,
      reason_code: null,
      conflict_path_count: 0,
      gate_ids: [],
      updated_at: null
    });
  });

  it("reports an empty room integration before the first job", () => {
    expect(emptyRoomIntegration()).toEqual({ green_head_commit: null, latest: null });
  });

  it("reports an empty summary integration when nothing finished", () => {
    expect(emptySummaryIntegration()).toEqual({
      status: null,
      statusRaw: null,
      green_head_commit: null
    });
  });
});
