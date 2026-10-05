import { describe, expect, it } from "vitest";

import {
  boardIntegrationChipText,
  boardIntegrationErrorShowsCode,
  boardIntegrationErrorText,
  boardIntegrationGateStatusLabel,
  boardIntegrationItemStatusLabel,
  boardIntegrationJobStatusLabel,
  boardIntegrationRoleLabel,
  boardIntegrationSecondaryText,
  boardIntegrationStatusLabel
} from "./board-integration-labels";

describe("integration labels", () => {
  it("words every module status without colour alone", () => {
    expect(boardIntegrationStatusLabel("pending")).toBe("排队集成");
    expect(boardIntegrationStatusLabel("running")).toBe("集成中");
    expect(boardIntegrationStatusLabel("integrated")).toBe("已集成");
    expect(boardIntegrationStatusLabel("waiting")).toBe("等待依赖集成");
    expect(boardIntegrationStatusLabel("conflicted")).toBe("集成冲突");
    expect(boardIntegrationStatusLabel("gate_failed")).toBe("门禁失败");
    expect(boardIntegrationStatusLabel("error")).toBe("集成异常");
  });

  it("words every job status for the summary line", () => {
    expect(boardIntegrationJobStatusLabel("pending")).toBe("排队");
    expect(boardIntegrationJobStatusLabel("running")).toBe("进行中");
    expect(boardIntegrationJobStatusLabel("conflicted")).toBe("集成冲突");
    expect(boardIntegrationJobStatusLabel("gate_failed")).toBe("门禁失败");
    expect(boardIntegrationJobStatusLabel("error")).toBe("异常");
  });

  it("words every item and role status", () => {
    expect(boardIntegrationItemStatusLabel("applied")).toBe("已应用");
    expect(boardIntegrationItemStatusLabel("fell_back")).toBe("已回退到旧版本");
    expect(boardIntegrationItemStatusLabel("conflicted")).toBe("冲突");
    expect(boardIntegrationItemStatusLabel("waiting")).toBe("等待依赖");
    expect(boardIntegrationItemStatusLabel("not_applied")).toBe("未执行");
    expect(boardIntegrationRoleLabel("incumbent")).toBe("在先");
    expect(boardIntegrationRoleLabel("newcomer")).toBe("新加入");
    expect(boardIntegrationGateStatusLabel("passed")).toBe("已通过");
    expect(boardIntegrationGateStatusLabel("failed")).toBe("未通过");
  });

  it("degrades unknown values to ? <raw>", () => {
    expect(boardIntegrationStatusLabel("unknown", "future_status")).toBe("? future_status");
    expect(boardIntegrationJobStatusLabel("unknown", "future_job")).toBe("? future_job");
    expect(boardIntegrationItemStatusLabel("unknown", "future_item")).toBe("? future_item");
    expect(boardIntegrationRoleLabel("unknown", "future_role")).toBe("? future_role");
    expect(boardIntegrationGateStatusLabel("unknown", "future_gate")).toBe("? future_gate");
  });

  it("writes honest chip text, never 已集成 for a fallback", () => {
    expect(
      boardIntegrationChipText({ status: "conflicted", statusRaw: null, conflict_path_count: 2 })
    ).toBe("集成冲突 · 2 个路径");
    expect(
      boardIntegrationChipText({ status: "gate_failed", statusRaw: null, conflict_path_count: 0 })
    ).toBe("门禁失败 · 嫌疑");
    expect(
      boardIntegrationChipText({ status: "error", statusRaw: null, conflict_path_count: 0 })
    ).toContain("宿主会自动重试");
    expect(
      boardIntegrationChipText({ status: "unknown", statusRaw: "future", conflict_path_count: 0 })
    ).toBe("? future");
  });

  it("says what the branch holds, not who caused a failure", () => {
    expect(
      boardIntegrationSecondaryText({
        status: "conflicted",
        verification_id: "v-new",
        integrated_verification_id: "v-old"
      })
    ).toBe("分支中是旧版本");
    expect(
      boardIntegrationSecondaryText({
        status: "conflicted",
        verification_id: "v-new",
        integrated_verification_id: null
      })
    ).toBe("未进入集成分支");
    expect(
      boardIntegrationSecondaryText({
        status: "gate_failed",
        verification_id: "v-new",
        integrated_verification_id: null
      })
    ).toBe("未进入集成分支");
    expect(
      boardIntegrationSecondaryText({
        status: "integrated",
        verification_id: "v-same",
        integrated_verification_id: "v-same"
      })
    ).toBeNull();
  });

  it("maps integration fetch errors without leaking developer messages", () => {
    expect(boardIntegrationErrorText("room_board_integration_unknown")).toBe("集成记录不存在");
    expect(boardIntegrationErrorShowsCode("room_board_integration_unknown")).toBe(false);
    expect(boardIntegrationErrorText("something_else")).toBe("操作失败，请重试");
    expect(boardIntegrationErrorShowsCode("something_else")).toBe(true);
  });
});
