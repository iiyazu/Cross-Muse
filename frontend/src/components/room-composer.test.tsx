import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { RoomParticipant } from "@/lib/types";
import { RoomComposer } from "./room-composer";

const participants: RoomParticipant[] = [
  {
    participant_id: "part-builder",
    role: "builder",
    display_name: "Builder",
    mention_handle: "@builder",
    status: "active",
    active: true
  },
  {
    participant_id: "part-init",
    role: "init",
    display_name: "Init",
    mention_handle: "@init",
    status: "active",
    active: true
  }
];

function ControlledComposer({ onSend }: { onSend: (value: string) => Promise<unknown> }) {
  const [draft, setDraft] = useState("");
  return (
    <RoomComposer
      draft={draft}
      onDraftChange={setDraft}
      onSend={onSend}
      participants={participants}
      roomId="conv-1"
    />
  );
}

describe("RoomComposer", () => {
  it("offers only active non-init Agents and inserts the server mention handle", async () => {
    const user = userEvent.setup();
    render(<ControlledComposer onSend={vi.fn()} />);
    const input = screen.getByLabelText("发送消息");
    await user.type(input, "请 @bu");
    expect(screen.getByRole("option", { name: /Builder/ })).toBeInTheDocument();
    expect(screen.queryByText("Init")).not.toBeInTheDocument();
    await user.keyboard("{Enter}");
    expect(input).toHaveValue("请 @builder ");
    expect(screen.getByText(/@ 只提高关注优先级/)).toBeInTheDocument();
  });

  it("does not submit Enter during IME composition and uses Shift+Enter for a newline", () => {
    const onSend = vi.fn(async () => undefined);
    render(<ControlledComposer onSend={onSend} />);
    const input = screen.getByLabelText("发送消息");
    fireEvent.change(input, { target: { value: "中文输入" } });
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("中文输入");
  });

  it("does not choose an open Mention option when IME Enter confirms composition", async () => {
    const user = userEvent.setup();
    const onSend = vi.fn(async () => undefined);
    render(<ControlledComposer onSend={onSend} />);
    const input = screen.getByLabelText("发送消息");
    await user.type(input, "请 @bu");
    expect(screen.getByRole("option", { name: /Builder/ })).toBeInTheDocument();

    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: "Enter" });

    expect(input).toHaveValue("请 @bu");
    expect(screen.getByRole("option", { name: /Builder/ })).toBeInTheDocument();
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input);
  });
});
