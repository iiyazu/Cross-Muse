import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchRoomSetupOptions } from "@/lib/api";
import type { RoomSetupOptions } from "@/lib/types";
import { RoomSidebar } from "./room-sidebar";

vi.mock("@/lib/api", () => ({ fetchRoomSetupOptions: vi.fn() }));

function setupOptionsWithReviews(): RoomSetupOptions {
  return {
    schema_version: "room_setup_options/v1",
    default_roster_template_id: "builtin.development",
    roster_templates: [
      {
        template_id: "builtin.development",
        display_name: "开发小组",
        description: "默认",
        participants: [
          { role_id: "r1", role: "builder", display_name: "Builder", description: "d", collaboration_focus: "f" }
        ]
      }
    ],
    review_policies: ["off", "cross_family"]
  };
}

function setupOptionsWithoutReviews(): RoomSetupOptions {
  return {
    schema_version: "room_setup_options/v1",
    default_roster_template_id: "builtin.development",
    roster_templates: [
      {
        template_id: "builtin.development",
        display_name: "开发小组",
        description: "默认",
        participants: [
          { role_id: "r1", role: "builder", display_name: "Builder", description: "d", collaboration_focus: "f" }
        ]
      }
    ]
  };
}

const baseProps = {
  rooms: [] as import("@/lib/types").RoomSummary[],
  selectedRoomId: null,
  readCursors: {},
  drafts: {},
  loading: false,
  loaded: true,
  error: null,
  createPending: false,
  createError: null,
  query: "",
  creating: true,
  title: "Room",
  createRequestId: "req-1",
  onNavigate: vi.fn(),
  onClose: vi.fn(),
  onQueryChange: vi.fn(),
  onCreatingChange: vi.fn(),
  onTitleChange: vi.fn()
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe("create-room review toggle", () => {
  it("hides the toggle without review_policies and sends no review_policy", async () => {
    vi.mocked(fetchRoomSetupOptions).mockResolvedValue(setupOptionsWithoutReviews());
    const onCreate = vi.fn(async () => true);
    render(<RoomSidebar {...baseProps} onCreate={onCreate} />);
    await screen.findByText("开发小组");
    expect(screen.queryByText("跨模型族复核")).toBeNull();
    await (await import("@testing-library/user-event")).default.setup().click(
      screen.getByRole("button", { name: "创建 Room" })
    );
    expect(onCreate).toHaveBeenCalledWith("Room", "req-1", "builtin.development", {
      mode: "broadcast"
    });
  });

  it("shows the toggle only with cross_family and sends it when on", async () => {
    const user = userEvent.setup();
    vi.mocked(fetchRoomSetupOptions).mockResolvedValue(setupOptionsWithReviews());
    const onCreate = vi.fn(async () => true);
    render(<RoomSidebar {...baseProps} onCreate={onCreate} />);
    await screen.findByText("跨模型族复核");
    await user.click(screen.getByRole("button", { name: "创建 Room" }));
    expect(onCreate).toHaveBeenCalledWith("Room", "req-1", "builtin.development", {
      mode: "broadcast"
    });
    await user.click(screen.getByLabelText(/跨模型族复核/));
    await user.click(screen.getByRole("button", { name: "创建 Room" }));
    expect(onCreate).toHaveBeenLastCalledWith("Room", "req-1", "builtin.development", {
      mode: "broadcast",
      review_policy: "cross_family"
    });
  });
});
