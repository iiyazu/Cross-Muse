import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchRoomSetupOptions } from "@/lib/api";
import type { RoomSetupOptions, RoomSummary } from "@/lib/types";
import { RoomSidebar } from "./room-sidebar";

vi.mock("@/lib/api", () => ({ fetchRoomSetupOptions: vi.fn() }));

const setupOptions: RoomSetupOptions = {
  schema_version: "room_setup_options/v1",
  default_roster_template_id: "builtin.development",
  roster_templates: [
    {
      template_id: "builtin.development",
      display_name: "开发小组",
      description: "默认开发团队",
      participants: [
        { role_id: "role-builder", role: "builder", display_name: "Builder", description: "实现", collaboration_focus: "交付" }
      ]
    },
    {
      template_id: "builtin.heterogeneous-trio",
      display_name: "异构协作小组",
      description: "Claude 主导架构，Antigravity 调研，Codex 复审",
      participants: [
        { role_id: "role-architect", role: "architect", display_name: "架构师", description: "架构", collaboration_focus: "设计", cli_kind: "claude" },
        { role_id: "role-researcher", role: "researcher", display_name: "研究员", description: "调研", collaboration_focus: "证据", cli_kind: "antigravity" },
        { role_id: "role-backend", role: "backend_reviewer", display_name: "后端复审", description: "复核", collaboration_focus: "边界", cli_kind: "codex" }
      ],
      collaboration: { mode: "addressed", lead_role: "architect" },
      available: true,
      unavailable_providers: []
    },
    {
      template_id: "builtin.heterogeneous-duo",
      display_name: "异构双人小组",
      description: "Claude 主导，Antigravity 调研",
      participants: [
        { role_id: "role-product-lead", role: "architect", display_name: "产品负责人", description: "产品判断", collaboration_focus: "综合" }
      ],
      collaboration: { mode: "addressed", lead_role: "architect" },
      available: false,
      unavailable_providers: ["antigravity"]
    }
  ]
};

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

beforeEach(() => {
  vi.mocked(fetchRoomSetupOptions).mockResolvedValue(setupOptions);
});

describe("RoomSidebar", () => {
  it("preserves navigation, unread, draft, stale, and controlled search semantics", async () => {
    const user = userEvent.setup();
    const props = renderSidebar();
    expect(screen.getByRole("complementary", { name: "房间导航" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("房间列表可能已过期：stale");
    expect(screen.getByText("草稿：draft")).toBeInTheDocument();
    expect(screen.getByLabelText("7 条未读更新")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Architecture/ }));
    await user.type(screen.getByRole("searchbox", { name: "搜索房间" }), "arch");
    expect(props.onNavigate).toHaveBeenCalledWith("conv-1");
    expect(props.onQueryChange).toHaveBeenCalled();
  });

  it("renders a controlled create form and forwards its stable request id with a broadcast policy", async () => {
    const user = userEvent.setup();
    const props = renderSidebar({ creating: true, title: "New Room", createRequestId: "stable-create", createError: { message: "retry" } });
    expect(screen.getByRole("alert")).toHaveTextContent("retry");
    expect(await screen.findByText("开发小组")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "创建 Room" }));
    expect(props.onCreate).toHaveBeenCalledWith("New Room", "stable-create", "builtin.development", { mode: "broadcast" });
  });

  it("shows provider badges in the roster preview", async () => {
    renderSidebar({ creating: true });
    expect(await screen.findByText("异构协作小组")).toBeInTheDocument();
    expect(screen.getByLabelText("Claude · permission-gated")).toBeInTheDocument();
    expect(screen.getByLabelText("Antigravity · instructed read-only")).toBeInTheDocument();
    expect(screen.getByLabelText("Codex · sandboxed read-only")).toBeInTheDocument();
  });

  it("applies a template collaboration preset and sends the addressed payload", async () => {
    const user = userEvent.setup();
    const props = renderSidebar({ creating: true, title: "Trio", createRequestId: "req-addressed" });
    await screen.findByText("异构协作小组");
    await user.click(screen.getByRole("radio", { name: /异构协作小组/ }));
    expect(screen.getByRole("radio", { name: /Addressed/ })).toBeChecked();
    expect(screen.getByLabelText("Room lead")).toHaveValue("architect");
    await user.click(screen.getByRole("button", { name: "创建 Room" }));
    expect(props.onCreate).toHaveBeenCalledWith("Trio", "req-addressed", "builtin.heterogeneous-trio", { mode: "addressed", lead_role: "architect" });
  });

  it("sends the selected lead role when Addressed is chosen manually", async () => {
    const user = userEvent.setup();
    const props = renderSidebar({ creating: true, title: "Manual", createRequestId: "req-lead" });
    await screen.findByText("异构协作小组");
    await user.click(screen.getByRole("radio", { name: /异构协作小组/ }));
    await user.selectOptions(screen.getByLabelText("Room lead"), "backend_reviewer");
    await user.click(screen.getByRole("button", { name: "创建 Room" }));
    expect(props.onCreate).toHaveBeenCalledWith("Manual", "req-lead", "builtin.heterogeneous-trio", { mode: "addressed", lead_role: "backend_reviewer" });
  });

  it("keeps broadcast when the selected template has no collaboration preset", async () => {
    const user = userEvent.setup();
    const props = renderSidebar({ creating: true, title: "Reset", createRequestId: "req-reset" });
    await screen.findByText("异构协作小组");
    await user.click(screen.getByRole("radio", { name: /异构协作小组/ }));
    expect(screen.getByRole("radio", { name: /Addressed/ })).toBeChecked();
    await user.click(screen.getByRole("radio", { name: /开发小组/ }));
    expect(screen.getByRole("radio", { name: /Broadcast/ })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "创建 Room" }));
    expect(props.onCreate).toHaveBeenCalledWith("Reset", "req-reset", "builtin.development", { mode: "broadcast" });
  });

  it("disables roster templates whose providers are unavailable and states the reason", async () => {
    renderSidebar({ creating: true });
    const disabled = await screen.findByRole("radio", { name: /异构双人小组/ });
    expect(disabled).toBeDisabled();
    expect(screen.getByText(/不可用：缺少 antigravity/)).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: /异构协作小组/ })).toBeEnabled();
  });
});
