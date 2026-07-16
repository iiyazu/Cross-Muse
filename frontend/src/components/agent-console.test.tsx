import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type {
  RoomCodexActionDescriptor,
  RoomCodexCapabilityId,
  RoomCodexNativeEvent,
  RoomCodexParticipantProjection,
  RoomSkillDecision
} from "@/lib/types";
import { AgentConsole, type AgentConsoleProps } from "./agent-console";

const GUARD = `sha256:${"a".repeat(64)}`;
const capabilityIds: RoomCodexCapabilityId[] = [
  "goal_set",
  "goal_pause",
  "goal_resume",
  "goal_get",
  "goal_clear",
  "settings_update",
  "models_list",
  "console_turn_start",
  "turn_steer",
  "turn_interrupt",
  "compact_start",
  "review_start"
];

function descriptor(
  capabilityId: RoomCodexCapabilityId,
  available = true,
  disabledReason: string | null = null
): RoomCodexActionDescriptor {
  return {
    capability_id: capabilityId,
    available,
    disabled_reason: disabledReason,
    method: "POST",
    href: "/api/action",
    expected_session_guard: GUARD,
    expected_goal_guard: GUARD,
    expected_settings_guard: GUARD,
    expected_turn_guard: GUARD,
    confirmation_required: capabilityId === "goal_set",
  };
}

function participant(
  overrides: Partial<RoomCodexParticipantProjection> = {}
): RoomCodexParticipantProjection {
  return {
    participant: {
      participant_id: "participant-one",
      role: "architect",
      display_name: "Architect",
      status: "active"
    },
    native_snapshot: {
      source: "codex_app_server_projection_cache",
      observed_at: "2026-07-13T01:00:00Z",
      available: true,
      value: {
        schema_version: "room_codex_native_snapshot/v1",
        source: "codex_app_server",
        goal: {
          objective: "Improve xmuse",
          status: "active",
          token_budget: 100_000,
          tokens_used: 12_000,
          time_used_seconds: 75
        },
        settings: { model: "gpt-5.6-terra", effort: "medium" },
        active_turn: true,
        guards: { session: GUARD, goal: GUARD, settings: GUARD, turn: GUARD }
      }
    },
    capabilities: {
      source: "codex_app_server_projection_cache",
      observed_at: "2026-07-13T01:00:00Z",
      available: true,
      value: {
        schema_version: "room_codex_native_capabilities/v1",
        source: "codex_app_server",
        capabilities: capabilityIds.map((capabilityId) => ({
          capability_id: capabilityId,
          native_source: `native/${capabilityId}`,
          availability: "available",
          disabled_reason: null,
          session_guard: GUARD
        })),
        models: [
          {
            id: "terra",
            model: "gpt-5.6-terra",
            is_default: true,
            default_effort: "medium",
            efforts: ["low", "medium", "high"]
          }
        ]
      },
      actions: capabilityIds.map((capabilityId) => descriptor(capabilityId))
    },
    room_bridge: {
      source: "chat.db:room_codex_bridge",
      observed_at: "2026-07-13T01:00:00Z",
      hold: {
        state: "goal_active",
        hold_revision: 2,
        session_guard: GUARD,
        goal_guard: GUARD,
        settings_guard: GUARD,
        active_turn_guard: GUARD,
        reason_code: "codex_goal_active",
        observed_at: "2026-07-13T01:00:00Z",
        updated_at: "2026-07-13T01:00:00Z"
      },
      queue: { unresolved_count: 2, active_attempt_count: 0, root_blocking: true },
      actions: [
        {
          action_id: "action-one",
          control_seq: 1,
          client_action_id: "client-one",
          capability_id: "goal_set",
          status: "applied",
          reason_code: null,
          requested_at: "2026-07-13T01:00:00Z",
          completed_at: "2026-07-13T01:00:01Z",
          updated_at: "2026-07-13T01:00:01Z"
        }
      ]
    },
    history_partial: true,
    omitted_event_count: 3,
    ...overrides
  };
}

function events(participantId = "participant-one"): RoomCodexNativeEvent[] {
  return [
    {
      event_seq: 1,
      participant_seq: 1,
      participant_id: participantId,
      observed_at: "2026-07-13T01:00:00Z",
      kind: "token_usage_updated",
      usage: {
        last: {
          cached_input_tokens: 1,
          input_tokens: 2,
          output_tokens: 3,
          reasoning_output_tokens: 4,
          total_tokens: 9
        },
        total: {
          cached_input_tokens: 10,
          input_tokens: 20,
          output_tokens: 30,
          reasoning_output_tokens: 40,
          total_tokens: 90
        },
        model_context_window: 128_000
      }
    },
    {
      event_seq: 2,
      participant_seq: 2,
      participant_id: participantId,
      observed_at: "2026-07-13T01:00:01Z",
      kind: "plan_updated",
      step_count: 2,
      status_counts: { completed: 1, in_progress: 1 },
      steps: [
        { step: "Inspect", status: "completed" },
        { step: "Implement", status: "in_progress" }
      ],
      truncated: true
    },
    {
      event_seq: 3,
      participant_seq: 3,
      participant_id: participantId,
      observed_at: "2026-07-13T01:00:02Z",
      kind: "diff_updated",
      file_count: 2,
      addition_count: 9,
      deletion_count: 1
    },
    {
      event_seq: 4,
      participant_seq: 4,
      participant_id: participantId,
      observed_at: "2026-07-13T01:00:03Z",
      kind: "context_compacted"
    }
  ];
}

function props(overrides: Partial<AgentConsoleProps> = {}): AgentConsoleProps {
  return {
    participant: participant(),
    nativeEvents: events(),
    pending: false,
    error: null,
    localMode: "default",
    onAction: vi.fn(),
    onPreferenceChange: vi.fn(),
    onRefresh: vi.fn(),
    ...overrides
  };
}

describe("AgentConsole", () => {
  it("renders controls only from descriptors and keeps native and bridge evidence distinct", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    const view = participant();
    view.capabilities.actions = view.capabilities.actions.map((item) =>
      item.capability_id === "compact_start"
        ? descriptor("compact_start", false, "codex_native_state_conflict")
        : item
    );
    render(<AgentConsole {...props({ participant: view, onAction })} />);

    expect(screen.getByRole("heading", { name: "Codex 原生状态" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "xmuse Room Bridge" })).toBeInTheDocument();
    expect(screen.getByText("Improve xmuse")).toBeInTheDocument();
    expect(screen.getByText("12,000 tokens")).toBeInTheDocument();
    expect(screen.getByText("1 分 15 秒")).toBeInTheDocument();
    expect(screen.getByText("其他 Agent 可完成根回应；后续同轮跟进正在等待此 Agent。")).toBeInTheDocument();
    expect(screen.getByText(/applied 仅证明动作账本已应用/)).toBeInTheDocument();
    expect(screen.getByLabelText("Token 用量（不会实时播报）")).toHaveTextContent("128,000");
    expect(screen.getByRole("button", { name: "压缩上下文" })).toBeDisabled();
    expect(screen.getByRole("heading", { name: "Plan / Todo" })).toBeInTheDocument();
    expect(screen.getByText("1/2 完成 · 1 进行中")).toBeInTheDocument();
    expect(screen.getByText("Inspect")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "工具活动" })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Codex effort"), "high");
    expect(onAction).toHaveBeenCalledWith(
      "settings_update",
      { effort: "high" },
      expect.objectContaining({ capability_id: "settings_update" }),
      false
    );

    await user.click(screen.getByText(/计划更新/));
    const dialog = screen.getByRole("dialog", { name: "Codex 原生事件详情" });
    expect(within(dialog).getByText(/Implement/)).toBeInTheDocument();
    expect(within(dialog).getByText(/部分内容已省略/)).toBeInTheDocument();
  });

  it("renders safe Codex work activity and durable bundled Skills without provider details", () => {
    const skill: RoomSkillDecision = {
      skill_id: "implementation-planning",
      version: "1",
      content_sha256: GUARD,
      selection_reason: "命中 planning 关键词",
      matched_terms: ["plan"],
      context_status: "submitted"
    };
    const nativeEvents = [
      ...events(),
      {
        event_seq: 5,
        participant_seq: 5,
        participant_id: "participant-one",
        observed_at: "2026-07-13T01:00:04Z",
        kind: "item_started",
        item_type: "mcpToolCall"
      },
      {
        event_seq: 6,
        participant_seq: 6,
        participant_id: "participant-one",
        observed_at: "2026-07-13T01:00:05Z",
        kind: "item_completed",
        item_type: "mcpToolCall",
        duration_ms: 1000,
        exit_code: 0,
        text: "provider output must not render"
      },
      {
        event_seq: 7,
        participant_seq: 7,
        participant_id: "participant-one",
        observed_at: "2026-07-13T01:00:06Z",
        kind: "item_started",
        item_type: "enteredReviewMode"
      },
      {
        event_seq: 8,
        participant_seq: 8,
        participant_id: "participant-one",
        observed_at: "2026-07-13T01:00:07Z",
        kind: "item_completed",
        item_type: "exitedReviewMode"
      }
    ] satisfies RoomCodexNativeEvent[];
    render(<AgentConsole {...props({ nativeEvents, skillDecisions: [skill] })} />);

    expect(screen.getAllByText("MCP 工具")).toHaveLength(2);
    expect(screen.getByText("已完成 · 1000 ms · exit 0")).toBeInTheDocument();
    expect(screen.getByText("implementation-planning")).toBeInTheDocument();
    expect(screen.getByText(/已提交上下文/)).toBeInTheDocument();
    expect(screen.getByText("进入审查模式")).toBeInTheDocument();
    expect(screen.getByText("退出审查模式")).toBeInTheDocument();
    expect(screen.queryByText("provider output must not render")).not.toBeInTheDocument();
  });

  it("keeps repeated native event summaries distinguishable to assistive technology", () => {
    const repeated = [
      ...events(),
      {
        event_seq: 7,
        participant_seq: 7,
        participant_id: "participant-one",
        observed_at: "2026-07-13T01:00:06Z",
        kind: "plan_updated",
        step_count: 2,
        status_counts: { completed: 1, in_progress: 1 },
        steps: [{ step: "Inspect", status: "completed" }]
      }
    ] satisfies RoomCodexNativeEvent[];
    render(<AgentConsole {...props({ nativeEvents: repeated })} />);

    const labels = screen
      .getAllByRole("button", { name: /计划更新/ })
      .map((button) => button.getAttribute("aria-label"));
    expect(labels).toEqual(
      expect.arrayContaining(["计划更新 · 2 步 · 事件 2", "计划更新 · 2 步 · 事件 7"])
    );
  });

  it("submits ordinary text and aliases, preserves Shift+Enter, and ignores IME Enter", async () => {
    const onAction = vi.fn();
    const onPreferenceChange = vi.fn();
    render(<AgentConsole {...props({ onAction, onPreferenceChange })} />);
    const input = screen.getByLabelText("给 Architect 的 Console 输入");

    fireEvent.change(input, { target: { value: "中文输入" } });
    fireEvent.compositionStart(input);
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onAction).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input);
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(onAction).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onAction).toHaveBeenCalledWith(
      "console_turn_start",
      { text: "中文输入", mode: "default" },
      expect.objectContaining({ capability_id: "console_turn_start" }),
      false
    );

    fireEvent.change(input, { target: { value: "/plan" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onPreferenceChange).toHaveBeenCalledWith("plan");

    fireEvent.change(input, { target: { value: "/unknown anything" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("alert")).toHaveTextContent("未知命令");
  });

  it("confirms goal changes and interrupt, reports pending observations, and restores focus", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<AgentConsole {...props({ onAction })} />);
    const input = screen.getByLabelText("给 Architect 的 Console 输入");

    await user.type(input, "/goal --budget 20000 Ship the console");
    await user.keyboard("{Enter}");
    const dialog = screen.getByRole("alertdialog", { name: "启动新的 Codex Goal？" });
    expect(dialog).toHaveTextContent("仍有待处理的 Room observation");
    expect(within(dialog).getByRole("button", { name: "返回" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "确认启动 Goal" }));
    expect(onAction).toHaveBeenCalledWith(
      "goal_set",
      { objective: "Ship the console", token_budget: 20_000 },
      expect.objectContaining({ capability_id: "goal_set" }),
      true
    );
    await waitFor(() => expect(input).toHaveFocus());

    const interrupt = screen.getByRole("button", { name: "打断当前 turn" });
    await user.click(interrupt);
    expect(screen.getByRole("alertdialog", { name: "打断当前 Codex turn？" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "返回" }));
    expect(interrupt).toHaveFocus();
  });

  it("authors a Goal through bounded structured fields", async () => {
    const user = userEvent.setup();
    const onAction = vi.fn();
    render(<AgentConsole {...props({ onAction })} />);

    await user.click(screen.getByRole("button", { name: "新建 Goal" }));
    await user.type(screen.getByLabelText("Goal objective"), "Stabilize the Room shell");
    await user.clear(screen.getByLabelText("Goal token 预算"));
    await user.type(screen.getByLabelText("Goal token 预算"), "42000");
    await user.click(screen.getByRole("button", { name: "继续确认" }));
    await user.click(screen.getByRole("button", { name: "确认启动 Goal" }));

    expect(onAction).toHaveBeenCalledWith(
      "goal_set",
      { objective: "Stabilize the Room shell", token_budget: 42_000 },
      expect.objectContaining({ capability_id: "goal_set" }),
      true
    );
  });

  it("fails closed for a future Goal status", () => {
    const view = participant();
    if (!view.native_snapshot.value?.goal) throw new Error("fixture goal missing");
    view.native_snapshot.value.goal.status = "futureRunning" as never;
    render(<AgentConsole {...props({ participant: view })} />);

    expect(screen.getByText("未知状态（futureRunning）")).toBeInTheDocument();
    expect(screen.getByText(/未来 Goal 状态无法安全解释/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "暂停 Goal" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "刷新 Goal" })).toBeDisabled();
  });

  it("distinguishes runtime unsupported from policy-disabled controls", () => {
    const view = participant();
    const nativeCapabilities = view.capabilities.value?.capabilities ?? [];
    view.capabilities.value!.capabilities = nativeCapabilities.map((item) => {
      if (item.capability_id === "compact_start") {
        return { ...item, availability: "runtime_unsupported", disabled_reason: "runtime_old" };
      }
      if (item.capability_id === "review_start") {
        return { ...item, availability: "policy_disabled", disabled_reason: "room_isolation" };
      }
      return item;
    });
    view.capabilities.actions = view.capabilities.actions.map((item) =>
      ["compact_start", "review_start"].includes(item.capability_id)
        ? { ...item, available: false }
        : item
    );
    render(<AgentConsole {...props({ participant: view })} />);

    expect(screen.getByRole("button", { name: "压缩上下文" })).toHaveAttribute(
      "title",
      "当前 Codex runtime 不支持"
    );
    expect(screen.getByRole("button", { name: "审查未提交改动" })).toHaveAttribute(
      "title",
      "Room 隔离策略未开放此原生能力"
    );
    expect(screen.queryByPlaceholderText(/RPC/)).not.toBeInTheDocument();
  });

  it("resets local draft and detail when the selected Agent changes", async () => {
    const user = userEvent.setup();
    const first = participant();
    const rendered = render(<AgentConsole {...props({ participant: first })} />);
    const input = screen.getByLabelText("给 Architect 的 Console 输入");
    await user.type(input, "private draft");
    await user.click(screen.getByText(/计划更新/));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    const second = participant({
      participant: {
        participant_id: "participant-two",
        role: "reviewer",
        display_name: "Reviewer",
        status: "active"
      }
    });
    rendered.rerender(
      <AgentConsole {...props({ participant: second, nativeEvents: events("participant-two") })} />
    );

    await waitFor(() => expect(screen.getByLabelText("给 Reviewer 的 Console 输入")).toHaveValue(""));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Reviewer" })).toBeInTheDocument();
  });
});
