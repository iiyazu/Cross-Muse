import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { RoomTurn } from "@/lib/types";
import { RoomTurnStatus } from "./room-turn-status";

const descriptor = {
  available: true,
  href: "/operator/control",
  expected_state: "active" as const,
  expected_attempt_count: 1,
  expected_control_seq: 0
};

const turn: RoomTurn = {
  correlation_id: "corr-1",
  state: "active",
  excluded_stopped_count: 0,
  observation_count: 1,
  attempt_count: 1,
  skill_decision_count: 0,
  participants: [{
    participant_id: "participant-1",
    role: "builder",
    display_name: "Builder",
    status: "noop",
    state: "noop",
    response_count: 1,
    unresolved_count: 1,
    frontier: {
      observation_id: "observation-1",
      actions: { cancel: descriptor, retry: descriptor }
    }
  }]
};

describe("RoomTurnStatus", () => {
  it("keeps honest participant state and forwards projected controls", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const onRetry = vi.fn();
    render(<RoomTurnStatus turn={turn} hiddenCount={2} controlPending={null} onCancel={onCancel} onRetry={onRetry} />);
    expect(screen.getByRole("region", { name: "当前 Agent 状态" })).toBeInTheDocument();
    expect(screen.getByText("另有 2 轮进行中")).toBeInTheDocument();
    expect(screen.getByText("已回应 · 后续未跟答")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "取消 Builder 当前处理" }));
    await user.click(screen.getByRole("button", { name: "重试 Builder 当前 observation" }));
    expect(onCancel).toHaveBeenCalledWith(expect.objectContaining({ observationId: "observation-1", descriptor }));
    expect(onRetry).toHaveBeenCalledWith("observation-1", descriptor);
  });

  it("disables both controls while the observation is pending", () => {
    render(<RoomTurnStatus turn={turn} hiddenCount={0} controlPending={{ observationId: "observation-1", action: "cancel" }} onCancel={vi.fn()} onRetry={vi.fn()} />);
    expect(screen.getByRole("button", { name: "取消 Builder 当前处理" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "重试 Builder 当前 observation" })).toBeDisabled();
  });
});
