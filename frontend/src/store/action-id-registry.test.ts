import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearExecutionAction,
  clearMemoryRebuildAction,
  clearRuntimeRecoverAction,
  executionActionId,
  memoryActionId,
  memoryRebuildActionId,
  retainActionIdAfterFailure,
  runtimeRecoverActionId
} from "./action-id-registry";

describe("operator action id registry", () => {
  beforeEach(() => sessionStorage.clear());

  it("replays runtime recovery only while the incident guard matches", () => {
    const create = vi.fn()
      .mockReturnValueOnce("runtime-1")
      .mockReturnValueOnce("runtime-2");

    expect(runtimeRecoverActionId(sessionStorage, "incident-a", create)).toBe("runtime-1");
    expect(runtimeRecoverActionId(sessionStorage, "incident-a", create)).toBe("runtime-1");
    expect(runtimeRecoverActionId(sessionStorage, "incident-b", create)).toBe("runtime-2");
    expect(create).toHaveBeenCalledTimes(2);

    clearRuntimeRecoverAction(sessionStorage, "incident-a");
    expect(runtimeRecoverActionId(sessionStorage, "incident-b", create)).toBe("runtime-2");
  });

  it("reuses fingerprint actions until explicitly cleared", () => {
    const createExecution = vi.fn()
      .mockReturnValueOnce("execution-1")
      .mockReturnValueOnce("execution-2");
    expect(executionActionId(sessionStorage, "same-fingerprint", createExecution)).toBe("execution-1");
    expect(executionActionId(sessionStorage, "same-fingerprint", createExecution)).toBe("execution-1");
    clearExecutionAction(sessionStorage, "same-fingerprint");
    expect(executionActionId(sessionStorage, "same-fingerprint", createExecution)).toBe("execution-2");

    const createMemory = vi.fn().mockReturnValue("memory-1");
    expect(memoryActionId(sessionStorage, "candidate:digest", createMemory)).toBe("memory-1");
    expect(memoryActionId(sessionStorage, "candidate:digest", createMemory)).toBe("memory-1");
    expect(createMemory).toHaveBeenCalledOnce();
  });

  it("keeps rebuild replay bound to the exact incident", () => {
    const create = vi.fn()
      .mockReturnValueOnce("rebuild-1")
      .mockReturnValueOnce("rebuild-2");
    expect(memoryRebuildActionId(sessionStorage, "incident-a", create)).toBe("rebuild-1");
    clearMemoryRebuildAction(sessionStorage, "incident-b");
    expect(memoryRebuildActionId(sessionStorage, "incident-a", create)).toBe("rebuild-1");
    clearMemoryRebuildAction(sessionStorage, "incident-a");
    expect(memoryRebuildActionId(sessionStorage, "incident-a", create)).toBe("rebuild-2");
  });

  it("retains an id only for ambiguous transport failures", () => {
    expect([0, 502, 504].map(retainActionIdAfterFailure)).toEqual([true, true, true]);
    expect([400, 404, 409, 500].map(retainActionIdAfterFailure)).toEqual([false, false, false, false]);
  });

  it("recovers from malformed guarded storage without replaying garbage", () => {
    sessionStorage.setItem("xmuse.room-runtime-recover-action/v1", "not-json");
    expect(runtimeRecoverActionId(sessionStorage, "incident-a", () => "fresh")).toBe("fresh");
  });
});
