import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import type { RoomParticipant } from "@/lib/types";

import { Composer, mentionAt } from "./composer";

const participants: RoomParticipant[] = [
  { participant_id: "p1", role: "builder", display_name: "Claude Builder", mention_handle: "@builder", status: "settled", active: true, cli_kind: "claude" },
  { participant_id: "p2", role: "reviewer", display_name: "OpenCode Reviewer", mention_handle: "@reviewer", status: "settled", active: true, cli_kind: "opencode" }
];

function Harness({ onSend }: { onSend: (content: string) => Promise<unknown> }) {
  const [draft, setDraft] = useState("");
  return (
    <Composer
      collaboration={null}
      draft={draft}
      leadName={null}
      onDraftChange={setDraft}
      onSend={onSend}
      participants={participants}
      roomId="room-1"
    />
  );
}

describe("Composer", () => {
  it("sends on Enter, keeps Shift+Enter for a new line", () => {
    const onSend = vi.fn().mockResolvedValue(null);
    render(<Harness onSend={onSend} />);
    const input = screen.getByLabelText("发送消息");
    fireEvent.change(input, { target: { value: "hello", selectionStart: 5 } });
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).toHaveBeenCalledWith("hello");
  });

  it("does not send while an IME composition is in progress", () => {
    const onSend = vi.fn().mockResolvedValue(null);
    render(<Harness onSend={onSend} />);
    const input = screen.getByLabelText("发送消息");
    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "ni", selectionStart: 2 } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
  });

  it("completes an @ mention with the participant's handle", () => {
    render(<Harness onSend={vi.fn()} />);
    const input = screen.getByLabelText("发送消息") as HTMLTextAreaElement;
    fireEvent.change(input, { target: { value: "@rev", selectionStart: 4 } });
    expect(screen.getByRole("listbox", { name: "可以 @ 的 Agent" })).toBeInTheDocument();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(input.value).toBe("@reviewer ");
  });

  it("finds a mention token only at a word start", () => {
    expect(mentionAt("hi @bu", 6)).toEqual({ start: 3, query: "bu" });
    expect(mentionAt("mail@x", 6)).toBeNull();
  });
});
