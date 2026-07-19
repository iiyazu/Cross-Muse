import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchBootstrap } from "@/lib/api";
import { useRoomStore } from "@/store/room-store";
import { RoomOnboarding } from "./room-onboarding";

vi.mock("@/lib/api", () => ({ fetchBootstrap: vi.fn() }));

const bootstrap = {
  schema_version: "xmuse_bootstrap_projection/v1" as const,
  has_rooms: false,
  codex: { launcher_available: true },
  memory: {
    mode: "auto",
    companion: "missing",
    profile: "unavailable",
    runtime: { state: "disabled", code: "memoryos_companion_missing" }
  },
  execution: {
    profile_id: "xmuse-monorepo/v2",
    revision: 2,
    readiness: { state: "ready", ready: true }
  },
  recommended_action: "install_memory"
};

describe("RoomOnboarding", () => {
  beforeEach(() => {
    vi.mocked(fetchBootstrap).mockResolvedValue(bootstrap);
    useRoomStore.setState({
      onboardingVersion: 1,
      onboardingCompleted: false,
      onboardingDismissed: false,
      onboardingOpen: false
    });
  });

  it("shows safe readiness and copies an instruction without executing installation", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });

    render(<RoomOnboarding mode="start" onCreateRoom={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Codex 已就绪")).toBeInTheDocument());
    expect(screen.getByText("MemoryOS 未安装（可选）")).toBeInTheDocument();
    expect(screen.getByText("Harness 已就绪")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "复制 MemoryOS companion 安装提示" }));
    expect(writeText).toHaveBeenCalledWith(
      "python3.11 xmuse-setup.pyz install-memory --bundle <companion-bundle>"
    );
    expect(await screen.findByText("已复制安装提示")).toBeInTheDocument();
  });

  it("keeps a dismissed empty state actionable and can reopen the readiness guide", async () => {
    const user = userEvent.setup();
    useRoomStore.setState({ onboardingDismissed: true });
    render(<RoomOnboarding mode="start" onCreateRoom={vi.fn()} />);

    expect(screen.getByText("还没有 Room。创建后，每个 Agent 会独立观察共享事实。")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "查看本地能力" }));
    expect(await screen.findByRole("heading", { name: "让多个 Codex Agent 在一个 Room 自然协作" })).toBeInTheDocument();
  });

  it("hides a completed guide until the command palette reopens it", async () => {
    vi.mocked(fetchBootstrap).mockImplementation(() => new Promise(() => undefined));
    useRoomStore.setState({ onboardingCompleted: true });
    const view = render(<RoomOnboarding mode="guide" onCreateRoom={vi.fn()} progress={{ room: true }} />);
    expect(screen.queryByLabelText("首次使用进度")).not.toBeInTheDocument();

    act(() => useRoomStore.getState().openOnboarding());
    view.rerender(<RoomOnboarding mode="guide" onCreateRoom={vi.fn()} progress={{ room: true }} />);
    expect(screen.getByLabelText("首次使用进度").querySelectorAll(".is-done")).toHaveLength(5);
  });
});
