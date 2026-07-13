import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RoomInspector, type RoomInspectorProps } from "./room-inspector";

function props(overrides: Partial<RoomInspectorProps> = {}): RoomInspectorProps {
  return {
    modal: false,
    selectedRoomId: "room-1",
    target: null,
    targetReady: true,
    targetVersion: 1,
    operationsSection: <section className="room-operations"><h3>运行与恢复</h3></section>,
    executionSection: <section><h3>执行候选</h3></section>,
    memorySection: <section><h3>长期记忆</h3></section>,
    roomEvidenceSection: <section><h3>活跃成员</h3></section>,
    onClose: vi.fn(),
    onTargetResolved: vi.fn(),
    onTargetMissing: vi.fn(),
    ...overrides
  };
}

describe("RoomInspector", () => {
  it("composes durable domain sections in a stable order without interpreting them", () => {
    const { container } = render(<RoomInspector {...props()} />);
    const inspector = container.querySelector(".room-inspector")!;
    expect(within(inspector as HTMLElement).getAllByRole("heading", { level: 3 }).map(
      (heading) => heading.textContent
    )).toEqual(["运行与恢复", "执行候选", "长期记忆", "活跃成员"]);
    expect(inspector).not.toHaveAttribute("role");
    expect(inspector).not.toHaveAttribute("aria-modal");
  });

  it("traps modal focus, closes on Escape, and restores prior focus on unmount", async () => {
    const user = userEvent.setup();
    const before = document.createElement("button");
    document.body.append(before);
    before.focus();
    const onClose = vi.fn();
    const view = render(
      <RoomInspector
        {...props({
          modal: true,
          onClose,
          roomEvidenceSection: <section><button type="button">末尾动作</button></section>
        })}
      />
    );

    const dialog = screen.getByRole("dialog", { name: "房间检查器" });
    const close = screen.getByRole("button", { name: "关闭检查器" });
    const last = screen.getByRole("button", { name: "末尾动作" });
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(last).toHaveFocus();
    await user.tab();
    expect(close).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();
    expect(dialog).toHaveAttribute("aria-modal", "true");
    view.unmount();
    expect(before).toHaveFocus();
    before.remove();
  });

  it("focuses an observation identified by durable target and resolves it", async () => {
    const onTargetResolved = vi.fn();
    render(
      <RoomInspector
        {...props({
          target: { roomId: "room-1", observationId: "obs-2", incidentId: "incident-1" },
          onTargetResolved,
          roomEvidenceSection: (
            <section>
              <article data-observation-id="obs-1" tabIndex={-1}>one</article>
              <article data-observation-id="obs-2" tabIndex={-1}>two</article>
            </section>
          )
        })}
      />
    );
    await waitFor(() => expect(screen.getByText("two")).toHaveFocus());
    expect(onTargetResolved).toHaveBeenCalledOnce();
  });

  it("falls back to the incident and reports a missing observation only when ready", async () => {
    const onTargetResolved = vi.fn();
    const onTargetMissing = vi.fn();
    const target = { roomId: "room-1", observationId: "missing", incidentId: "incident-2" };
    const view = render(
      <RoomInspector
        {...props({
          target,
          targetReady: false,
          onTargetResolved,
          onTargetMissing,
          operationsSection: (
            <section className="room-operations" tabIndex={-1}>
              <article data-incident-id="incident-2" tabIndex={-1}>incident</article>
            </section>
          )
        })}
      />
    );
    await new Promise((resolve) => requestAnimationFrame(resolve));
    expect(onTargetResolved).not.toHaveBeenCalled();
    expect(onTargetMissing).not.toHaveBeenCalled();

    view.rerender(<RoomInspector {...props({
      target,
      targetReady: true,
      targetVersion: 2,
      onTargetResolved,
      onTargetMissing,
      operationsSection: (
        <section className="room-operations" tabIndex={-1}>
          <article data-incident-id="incident-2" tabIndex={-1}>incident</article>
        </section>
      )
    })} />);
    await waitFor(() => expect(screen.getByText("incident")).toHaveFocus());
    expect(onTargetResolved).toHaveBeenCalledOnce();
    expect(onTargetMissing).toHaveBeenCalledOnce();
  });
});
