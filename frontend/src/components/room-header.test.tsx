import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { RoomParticipant } from "@/lib/types";
import { identityStyle, RoomHeader, RoomMemberStack } from "./room-header";

function participant(index: number, cliKind?: string): RoomParticipant {
  return {
    participant_id: `participant-${index}`,
    role: "builder",
    display_name: `Agent ${index}`,
    mention_handle: `@agent-${index}`,
    status: "pending",
    active: true,
    cli_kind: cliKind ?? null
  };
}

describe("RoomHeader", () => {
  it("keeps stable identity colors and bounds the member stack", () => {
    expect(identityStyle("participant-1")).toEqual(identityStyle("participant-1"));
    render(<RoomMemberStack participants={Array.from({ length: 6 }, (_, index) => participant(index))} label="成员" />);
    expect(screen.getByLabelText("成员").querySelectorAll(".room-avatar")).toHaveLength(5);
    expect(screen.getByText("+2")).toBeInTheDocument();
  });

  it("preserves header controls, ARIA, alert, and callbacks", async () => {
    const user = userEvent.setup();
    const onToggleNavigation = vi.fn();
    const onToggleInspector = vi.fn();
    const onToggleTheme = vi.fn();
    render(<RoomHeader title="Natural Room" syncState="synced" syncLabel="已同步" participants={[participant(1)]} navigationOpen inspectorOpen={false} operationsAlert={{ className: "has-alert", label: "运行时阻塞", glyph: "!" }} theme="dark" onToggleNavigation={onToggleNavigation} onToggleInspector={onToggleInspector} onToggleTheme={onToggleTheme} />);

    expect(screen.getByRole("heading", { name: "Natural Room" })).toBeInTheDocument();
    expect(screen.getByText("已同步")).toHaveClass("state-synced");
    expect(screen.getByLabelText("运行时阻塞")).toHaveTextContent("!");
    expect(screen.getByRole("button", { name: /工作台/ })).toHaveAttribute("aria-expanded", "false");
    await user.click(screen.getByRole("button", { name: "关闭房间栏" }));
    await user.click(screen.getByRole("button", { name: /工作台/ }));
    await user.click(screen.getByRole("button", { name: "切换主题" }));
    expect(onToggleNavigation).toHaveBeenCalledOnce();
    expect(onToggleInspector).toHaveBeenCalledOnce();
    expect(onToggleTheme).toHaveBeenCalledOnce();
  });

  it("shows provider badges on member avatars and the collaboration chip", () => {
    render(
      <RoomHeader
        title="Trio"
        syncState="synced"
        syncLabel="已同步"
        participants={[participant(1, "claude"), participant(2, "antigravity"), participant(3, "codex")]}
        collaboration={{ mode: "addressed", lead_participant_id: "participant-1" }}
        navigationOpen
        inspectorOpen={false}
        operationsAlert={null}
        theme="dark"
        onToggleNavigation={vi.fn()}
        onToggleInspector={vi.fn()}
        onToggleTheme={vi.fn()}
      />
    );
    expect(screen.getByTitle("Agent 1 · Claude · permission-gated")).toBeInTheDocument();
    expect(screen.getByTitle("Agent 2 · Antigravity · instructed read-only")).toBeInTheDocument();
    const chip = screen.getByText("Addressed · lead Agent 1");
    expect(chip).toHaveAttribute("title", "Addressed：仅被 @ 提及的 Agent 会观察；未提及时发给 lead");
  });

  it("labels broadcast collaboration without a lead", () => {
    render(
      <RoomHeader
        title="All"
        syncState="synced"
        syncLabel="已同步"
        participants={[participant(1)]}
        collaboration={{ mode: "broadcast", lead_participant_id: null }}
        navigationOpen
        inspectorOpen={false}
        operationsAlert={null}
        theme="dark"
        onToggleNavigation={vi.fn()}
        onToggleInspector={vi.fn()}
        onToggleTheme={vi.fn()}
      />
    );
    expect(screen.getByText("Broadcast · 全员观察")).toBeInTheDocument();
  });
});
