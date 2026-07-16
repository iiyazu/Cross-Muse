import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { RoomParticipant } from "@/lib/types";
import { identityStyle, RoomHeader, RoomMemberStack } from "./room-header";

function participant(index: number): RoomParticipant {
  return {
    participant_id: `participant-${index}`,
    role: "builder",
    display_name: `Agent ${index}`,
    mention_handle: `@agent-${index}`,
    status: "pending",
    active: true
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
});
