import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { RoomSummary } from "@/lib/types";
import { RoomSidebar } from "./room-sidebar";

const rooms: RoomSummary[] = [{
  conversation_id: "conv-1",
  title: "Architecture",
  latest_visible_room_seq: 9,
  latest_visible_item: null,
  latest_message: { content: "latest" },
  members: [],
  state: "active",
  active_turn_count: 1,
  attention_turn_count: 0
}];

function renderSidebar(overrides: Partial<React.ComponentProps<typeof RoomSidebar>> = {}) {
  const props: React.ComponentProps<typeof RoomSidebar> = {
    rooms,
    selectedRoomId: "conv-1",
    readCursors: { "conv-1": 2 },
    drafts: { "conv-1": "draft" },
    loading: false,
    loaded: true,
    error: { message: "stale" },
    createPending: false,
    createError: null,
    query: "",
    creating: false,
    title: "",
    createRequestId: null,
    onNavigate: vi.fn(),
    onCreate: vi.fn(async () => true),
    onClose: vi.fn(),
    onQueryChange: vi.fn(),
    onCreatingChange: vi.fn(),
    onTitleChange: vi.fn(),
    ...overrides
  };
  render(<RoomSidebar {...props} />);
  return props;
}

describe("RoomSidebar", () => {
  it("preserves navigation, unread, draft, stale, and controlled search semantics", async () => {
    const user = userEvent.setup();
    const props = renderSidebar();
    expect(screen.getByRole("complementary", { name: "房间导航" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("房间列表可能已过期：stale");
    expect(screen.getByText("草稿：draft")).toBeInTheDocument();
    expect(screen.getByLabelText("有未读更新")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Architecture/ }));
    await user.type(screen.getByRole("searchbox", { name: "搜索房间" }), "arch");
    expect(props.onNavigate).toHaveBeenCalledWith("conv-1");
    expect(props.onQueryChange).toHaveBeenCalled();
  });

  it("renders a controlled create form and forwards its stable request id", async () => {
    const user = userEvent.setup();
    const props = renderSidebar({ creating: true, title: "New Room", createRequestId: "stable-create", createError: { message: "retry" } });
    expect(screen.getByRole("alert")).toHaveTextContent("retry");
    await user.click(screen.getByRole("button", { name: "创建" }));
    expect(props.onCreate).toHaveBeenCalledWith("New Room", "stable-create");
  });
});
