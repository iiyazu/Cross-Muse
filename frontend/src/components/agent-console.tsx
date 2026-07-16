"use client";

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent
} from "react";

import {
  parseCodexConsoleInput,
  type CodexConsoleMode
} from "@/lib/codex-console-command";
import type {
  RoomCodexActionDescriptor,
  RoomCodexActionInput,
  RoomCodexCapabilityId,
  RoomCodexNativeEvent,
  RoomCodexParticipantProjection,
  RoomSkillDecision
} from "@/lib/types";

type ConsoleRequest = RoomCodexActionInput["request"];

export type AgentConsoleProps = {
  participant: RoomCodexParticipantProjection;
  nativeEvents: RoomCodexNativeEvent[];
  /** Durable bundled Skill decisions from the Room projection. Never inferred from provider text. */
  skillDecisions?: RoomSkillDecision[];
  pending: boolean;
  error: string | null;
  localMode: CodexConsoleMode;
  onAction: (
    capabilityId: RoomCodexCapabilityId,
    safeRequest: ConsoleRequest,
    descriptor: RoomCodexActionDescriptor,
    confirmedPendingObservations: boolean
  ) => void | Promise<unknown>;
  onPreferenceChange: (mode: CodexConsoleMode) => void;
  onRefresh?: () => void;
};

type Confirmation = {
  capabilityId: RoomCodexCapabilityId;
  safeRequest: ConsoleRequest;
  descriptor: RoomCodexActionDescriptor;
  trigger: HTMLElement | null;
};

const KNOWN_GOAL_STATUSES = new Set([
  "active",
  "paused",
  "blocked",
  "usageLimited",
  "budgetLimited",
  "complete"
]);

const ACTION_LABELS: Partial<Record<RoomCodexCapabilityId, string>> = {
  goal_set: "新建 Goal",
  goal_get: "刷新 Goal",
  goal_pause: "暂停 Goal",
  goal_resume: "继续 Goal",
  goal_clear: "清除 Goal",
  turn_steer: "Steer 当前 turn",
  turn_interrupt: "打断当前 turn",
  compact_start: "压缩上下文",
  review_start: "审查未提交改动"
};

const CONSOLE_COMMANDS = [
  ["/goal", "查看或设置 Goal"],
  ["/model", "查看或切换 Model"],
  ["/effort", "调整 Effort"],
  ["/plan", "以 Plan 模式发送"],
  ["/steer", "引导当前 turn"],
  ["/interrupt", "打断当前 turn"],
  ["/compact", "压缩上下文"],
  ["/review", "启动代码审查"]
] as const;

function formatNumber(value: number | null | undefined) {
  return typeof value === "number" ? new Intl.NumberFormat("zh-CN").format(value) : "—";
}

function formatDuration(value: number | null | undefined) {
  if (typeof value !== "number") return "—";
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const seconds = value % 60;
  return [hours ? `${hours} 小时` : "", minutes ? `${minutes} 分` : "", `${seconds} 秒`]
    .filter(Boolean)
    .join(" ");
}

function descriptorFor(
  participant: RoomCodexParticipantProjection,
  capabilityId: RoomCodexCapabilityId
) {
  return participant.capabilities.actions.find(
    (descriptor) => descriptor.capability_id === capabilityId
  );
}

function disabledExplanation(
  participant: RoomCodexParticipantProjection,
  capabilityId: RoomCodexCapabilityId
) {
  const native = participant.capabilities.value?.capabilities.find(
    (item) => item.capability_id === capabilityId
  );
  if (native?.availability === "runtime_unsupported") return "当前 Codex runtime 不支持";
  if (native?.availability === "policy_disabled") return "Room 隔离策略未开放此原生能力";
  if (native && native.availability !== "available") return "当前原生会话冲突";
  return descriptorFor(participant, capabilityId)?.disabled_reason ?? "当前状态不可用";
}

function eventSummary(event: RoomCodexNativeEvent) {
  switch (event.kind) {
    case "goal_updated":
      return `Goal 状态更新：${event.status ?? "未知"}`;
    case "goal_cleared":
      return "Goal 已清除";
    case "settings_updated":
      return `设置更新：${event.model ?? "当前模型"} · ${event.effort ?? "默认 effort"}`;
    case "turn_started":
      return "Codex turn 已开始";
    case "turn_completed":
      return `Codex turn 已结束${event.status ? ` · ${event.status}` : ""}`;
    case "plan_updated":
      return `计划更新 · ${formatNumber(event.step_count)} 步`;
    case "diff_updated":
      return `Diff 更新 · ${formatNumber(event.file_count)} 文件 · +${formatNumber(event.addition_count)} / −${formatNumber(event.deletion_count)}`;
    case "context_compacted":
      return "上下文已压缩";
    case "item_started":
    case "item_completed":
      return `${event.item_type ?? "Codex item"} ${event.kind === "item_started" ? "开始" : "完成"}`;
    default:
      return event.kind ? `原生事件：${event.kind}` : "未知原生事件";
  }
}

const SAFE_TOOL_TYPES: Record<string, string> = {
  commandExecution: "命令执行",
  fileChange: "文件变更",
  mcpToolCall: "MCP 工具",
  dynamicToolCall: "动态工具",
  enteredReviewMode: "进入审查模式",
  exitedReviewMode: "退出审查模式"
};

function toolLabel(itemType: string | null | undefined) {
  return (itemType && SAFE_TOOL_TYPES[itemType]) || "工具活动";
}

function planCounts(steps: Array<{ step: string; status: string }>) {
  return steps.reduce(
    (counts, step) => {
      const status = step.status.toLowerCase();
      if (status === "completed" || status === "complete" || status === "done") counts.completed += 1;
      else if (status === "in_progress" || status === "in-progress" || status === "active") counts.active += 1;
      else counts.pending += 1;
      return counts;
    },
    { completed: 0, active: 0, pending: 0 }
  );
}

function confirmationCopy(confirmation: Confirmation, hasPendingObservations: boolean) {
  if (confirmation.capabilityId === "turn_interrupt") {
    return {
      title: "打断当前 Codex turn？",
      body: "未完成的原生 turn 会被中断；Room 的耐久 observation 不会被伪造为已完成。",
      confirm: "确认打断"
    };
  }
  if (confirmation.capabilityId === "goal_clear") {
    return {
      title: "清除当前 Goal？",
      body: "这会清除 Codex 原生 Goal 状态，不会删除 Room 消息或耐久结果。",
      confirm: "确认清除"
    };
  }
  return {
    title: "启动新的 Codex Goal？",
    body: hasPendingObservations
      ? "该 Agent 仍有待处理的 Room observation。其他 Agent 可完成根回应；此 Agent 的后续同轮跟进会等待 Goal 释放。"
      : "该 Agent 将进入 Goal 模式；新的 Console turn 和 Room observation 会按原生 Goal 状态等待。",
    confirm: "确认启动 Goal"
  };
}

function handleDialogKeyDown(
  event: KeyboardEvent<HTMLDivElement>,
  close: () => void
) {
  if (event.key === "Escape") {
    event.preventDefault();
    close();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = [...event.currentTarget.querySelectorAll<HTMLElement>(
    "button:not(:disabled):not([tabindex='-1']), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled)"
  )];
  if (!focusable.length) {
    event.preventDefault();
    return;
  }
  const first = focusable[0];
  const last = focusable.at(-1)!;
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

function ParticipantAgentConsole({
  participant,
  nativeEvents,
  skillDecisions = [],
  pending,
  error,
  localMode,
  onAction,
  onPreferenceChange,
  onRefresh
}: AgentConsoleProps) {
  const [draft, setDraft] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null);
  const [detailEvent, setDetailEvent] = useState<RoomCodexNativeEvent | null>(null);
  const [goalEditorOpen, setGoalEditorOpen] = useState(false);
  const [goalObjective, setGoalObjective] = useState("");
  const [goalBudget, setGoalBudget] = useState("100000");
  const composingRef = useRef(false);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const cancelConfirmRef = useRef<HTMLButtonElement>(null);
  const closeDetailRef = useRef<HTMLButtonElement>(null);
  const detailTriggerRef = useRef<HTMLElement | null>(null);

  const snapshot = participant.native_snapshot.value;
  const capabilities = participant.capabilities.value;
  const goal = snapshot?.goal;
  const unknownGoalStatus = Boolean(goal && !KNOWN_GOAL_STATUSES.has(goal.status));
  const queue = participant.room_bridge.queue;
  const hasPendingObservations = queue.unresolved_count > 0;
  const participantEvents = useMemo(
    () => nativeEvents.filter((event) => event.participant_id === participant.participant.participant_id),
    [nativeEvents, participant.participant.participant_id]
  );
  const latestUsage = [...participantEvents]
    .reverse()
    .find((event) => event.kind === "token_usage_updated" && event.usage)?.usage;
  const logEvents = participantEvents
    .filter((event) => event.kind !== "token_usage_updated")
    .slice(-40);
  const latestPlan = [...participantEvents]
    .reverse()
    .find((event) => event.kind === "plan_updated" && event.steps?.length);
  const planSteps = latestPlan?.steps ?? [];
  const planSummary = planCounts(planSteps);
  const toolEvents = participantEvents
    .filter((event) =>
      (event.kind === "item_started" || event.kind === "item_completed") &&
      Boolean(event.item_type && SAFE_TOOL_TYPES[event.item_type])
    )
    .slice(-12)
    .reverse();
  const activityEvents = participantEvents
    .filter((event) => ["goal_updated", "goal_cleared", "context_compacted", "turn_started", "turn_completed"].includes(event.kind ?? ""))
    .slice(-8)
    .reverse();

  useEffect(() => {
    if (!confirmation) return;
    const previousFocus = confirmation.trigger;
    cancelConfirmRef.current?.focus();
    return () => previousFocus?.focus();
  }, [confirmation]);

  useEffect(() => {
    if (!detailEvent) return;
    const previousFocus = detailTriggerRef.current;
    closeDetailRef.current?.focus();
    return () => previousFocus?.focus();
  }, [detailEvent]);

  async function invoke(
    capabilityId: RoomCodexCapabilityId,
    safeRequest: ConsoleRequest,
    trigger: HTMLElement | null
  ) {
    setLocalError(null);
    const descriptor = descriptorFor(participant, capabilityId);
    if (!descriptor || !descriptor.available || (unknownGoalStatus && capabilityId.startsWith("goal_"))) {
      setLocalError(disabledExplanation(participant, capabilityId));
      return;
    }
    if (capabilityId === "goal_set" || capabilityId === "goal_clear" || capabilityId === "turn_interrupt") {
      setConfirmation({ capabilityId, safeRequest, descriptor, trigger });
      return;
    }
    await onAction(capabilityId, safeRequest, descriptor, false);
  }

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (pending) return;
    const result = parseCodexConsoleInput(draft, localMode);
    if (result.kind === "empty") return;
    if (result.kind === "error") {
      setLocalError(
        result.code === "codex_console_command_unknown"
          ? "未知命令；这里只接受列出的 Codex 原生能力别名"
          : "命令参数无效"
      );
      return;
    }
    if (result.kind === "preference") {
      onPreferenceChange(result.mode);
      setDraft("");
      setLocalError(null);
      return;
    }
    const descriptor = descriptorFor(participant, result.capabilityId);
    if (!descriptor || !descriptor.available || (unknownGoalStatus && result.capabilityId.startsWith("goal_"))) {
      await invoke(result.capabilityId, result.safeRequest, document.activeElement as HTMLElement | null);
      return;
    }
    setDraft("");
    await invoke(result.capabilityId, result.safeRequest, document.activeElement as HTMLElement | null);
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey) return;
    if (event.nativeEvent.isComposing || composingRef.current) return;
    event.preventDefault();
    void submit();
  }

  function closeConfirmation() {
    if (!pending) setConfirmation(null);
  }

  function submitGoal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const objective = goalObjective.trim();
    const tokenBudget = Number(goalBudget);
    if (!objective || !Number.isSafeInteger(tokenBudget) || tokenBudget < 10_000 || tokenBudget > 1_000_000) {
      setLocalError("Goal 需要明确目标，token 预算应在 10,000–1,000,000 之间");
      return;
    }
    void invoke(
      "goal_set",
      { objective, token_budget: tokenBudget },
      event.currentTarget.querySelector<HTMLButtonElement>("button[type='submit']")
    );
  }

  const goalStatusLabel = unknownGoalStatus
    ? `未知状态（${String(goal?.status)}）`
    : goal?.status ?? "未设置";

  const selectedModel = snapshot?.settings.model ?? "";
  const selectedEffort = snapshot?.settings.effort ?? "";
  const models = capabilities?.models ?? [];
  const selectedModelKnown = !selectedModel || models.some((model) => model.model === selectedModel);
  const selectedModelEntry = models.find((model) => model.model === selectedModel);
  const efforts = selectedModelEntry?.efforts ?? [];
  const selectedEffortKnown = !selectedEffort || efforts.includes(selectedEffort);
  const confirmCopy = confirmation
    ? confirmationCopy(confirmation, hasPendingObservations)
    : null;

  return (
    <section className="agent-console" aria-labelledby="agent-console-title">
      <header className="agent-console__header">
        <div>
          <span className="agent-console__eyebrow">Agent Console</span>
          <h3 id="agent-console-title">{participant.participant.display_name}</h3>
          <p>{participant.participant.role} · {participant.participant.status}</p>
        </div>
        {onRefresh ? <button type="button" onClick={onRefresh} disabled={pending}>刷新状态</button> : null}
      </header>

      <section className="agent-console__source" aria-labelledby="codex-native-title">
        <div className="agent-console__section-heading">
          <h4 id="codex-native-title">Codex 原生状态</h4>
          <span className="agent-console__source-badge">派生投影 · {participant.history_partial ? "部分历史" : "完整缓存窗口"}</span>
        </div>
        {!participant.native_snapshot.available || !snapshot ? (
          <p className="agent-console__notice" role="status">原生 snapshot 暂不可用，操作将保持关闭。</p>
        ) : (
          <>
            <dl className="agent-console__facts">
              <div><dt>Goal</dt><dd>{goalStatusLabel}</dd></div>
              <div><dt>预算</dt><dd>{formatNumber(goal?.token_budget)} tokens</dd></div>
              <div><dt>已用</dt><dd>{formatNumber(goal?.tokens_used)} tokens</dd></div>
              <div><dt>耗时</dt><dd>{formatDuration(goal?.time_used_seconds)}</dd></div>
              <div><dt>当前 turn</dt><dd>{snapshot.active_turn ? "进行中" : "空闲"}</dd></div>
              <div><dt>Console 模式</dt><dd>{localMode === "plan" ? "Plan（仅本机偏好）" : "Default（仅本机偏好）"}</dd></div>
            </dl>
            {goal?.objective ? <p className="agent-console__objective"><strong>目标：</strong>{goal.objective}</p> : null}
            {unknownGoalStatus ? (
              <p className="agent-console__notice" role="status">未来 Goal 状态无法安全解释，Goal 操作已关闭。</p>
            ) : null}

            <div className="agent-console__settings">
              <label>
                模型
                <select
                  aria-label="Codex 模型"
                  disabled={pending || !descriptorFor(participant, "settings_update")?.available}
                  value={selectedModel}
                  onChange={(event) => void invoke("settings_update", { model: event.target.value }, event.currentTarget)}
                >
                  {!selectedModelKnown ? <option value={selectedModel}>{selectedModel}（不可用）</option> : null}
                  {!selectedModel ? <option value="">未报告</option> : null}
                  {models.map((model) => <option value={model.model} key={model.id}>{model.model}{model.is_default ? "（默认）" : ""}</option>)}
                </select>
              </label>
              <label>
                Effort
                <select
                  aria-label="Codex effort"
                  disabled={pending || !descriptorFor(participant, "settings_update")?.available || !selectedModelEntry}
                  value={selectedEffort}
                  onChange={(event) => void invoke("settings_update", { effort: event.target.value }, event.currentTarget)}
                >
                  {!selectedEffortKnown ? <option value={selectedEffort}>{selectedEffort}（不可用）</option> : null}
                  {!selectedEffort ? <option value="">未报告</option> : null}
                  {efforts.map((effort) => <option value={effort} key={effort}>{effort}</option>)}
                </select>
              </label>
            </div>

            <div className="agent-console__actions" aria-label="Codex 原生操作">
              {(Object.keys(ACTION_LABELS) as RoomCodexCapabilityId[]).map((capabilityId) => {
                const descriptor = descriptorFor(participant, capabilityId);
                const request: ConsoleRequest = capabilityId === "review_start" ? { target: "uncommitted" } : {};
                const disabled = pending || !descriptor?.available || (unknownGoalStatus && capabilityId.startsWith("goal_"));
                return (
                  <button
                    className={`agent-console__action action-${capabilityId} ${capabilityId === "turn_interrupt" && snapshot?.active_turn ? "is-prominent" : ""}`}
                    key={capabilityId}
                    type="button"
                    disabled={disabled}
                    title={disabled ? disabledExplanation(participant, capabilityId) : undefined}
                    onClick={(event) => {
                      if (capabilityId === "goal_set") {
                        setGoalEditorOpen(true);
                        setLocalError(null);
                        return;
                      }
                      if (capabilityId === "turn_steer") {
                        setDraft("/steer ");
                        requestAnimationFrame(() => composerRef.current?.focus());
                        return;
                      }
                      void invoke(capabilityId, request, event.currentTarget);
                    }}
                  >
                    {ACTION_LABELS[capabilityId]}
                  </button>
                );
              })}
            </div>
            {goalEditorOpen ? (
              <form className="agent-console__goal-editor" onSubmit={submitGoal}>
                <div className="agent-console__section-heading">
                  <strong>新建 Codex Goal</strong>
                  <button onClick={() => setGoalEditorOpen(false)} type="button">取消</button>
                </div>
                <label>
                  Objective
                  <textarea
                    aria-label="Goal objective"
                    autoFocus
                    disabled={pending}
                    maxLength={4_000}
                    onChange={(event) => setGoalObjective(event.target.value)}
                    rows={3}
                    value={goalObjective}
                  />
                </label>
                <label>
                  Token 预算
                  <input
                    aria-label="Goal token 预算"
                    disabled={pending}
                    max={1_000_000}
                    min={10_000}
                    onChange={(event) => setGoalBudget(event.target.value)}
                    step={1_000}
                    type="number"
                    value={goalBudget}
                  />
                </label>
                <button className="room-primary-button" disabled={pending || !goalObjective.trim()} type="submit">继续确认</button>
              </form>
            ) : null}
            {capabilities?.capabilities.some((item) => item.availability !== "available") ? (
              <ul className="agent-console__availability" aria-label="不可用的 Codex 原生能力">
                {capabilities.capabilities.filter((item) => item.availability !== "available").map((item) => (
                  <li key={item.capability_id}>
                    <strong>{item.capability_id}</strong>：{item.availability === "runtime_unsupported"
                      ? "当前 Codex runtime 不支持"
                      : item.availability === "policy_disabled"
                        ? "Room 隔离策略未开放"
                        : "当前原生会话冲突"}
                  </li>
                ))}
              </ul>
            ) : null}

            <dl className="agent-console__tokens" aria-label="Token 用量（不会实时播报）">
              <div><dt>总 tokens</dt><dd>{formatNumber(latestUsage?.total.total_tokens)}</dd></div>
              <div><dt>输入</dt><dd>{formatNumber(latestUsage?.total.input_tokens)}</dd></div>
              <div><dt>输出</dt><dd>{formatNumber(latestUsage?.total.output_tokens)}</dd></div>
              <div><dt>上下文窗口</dt><dd>{formatNumber(latestUsage?.model_context_window)}</dd></div>
            </dl>

            <section className="agent-console__work-activity" aria-labelledby="agent-work-activity-title">
              <div className="agent-console__section-heading">
                <h4 id="agent-work-activity-title">工作活动</h4>
                <span className="agent-console__source-badge">Codex 派生事件</span>
              </div>

              <section className="agent-console__activity-card" aria-labelledby="agent-plan-title">
                <div className="agent-console__activity-heading">
                  <h5 id="agent-plan-title">Plan / Todo</h5>
                  {planSteps.length ? (
                    <span>{planSummary.completed}/{planSteps.length} 完成{planSummary.active ? ` · ${planSummary.active} 进行中` : ""}</span>
                  ) : <span>暂无计划</span>}
                </div>
                {planSteps.length ? (
                  <ol className="agent-console__plan-list">
                    {planSteps.map((step, index) => {
                      const status = step.status.toLowerCase();
                      const completed = status === "completed" || status === "complete" || status === "done";
                      const active = status === "in_progress" || status === "in-progress" || status === "active";
                      return (
                        <li className={completed ? "is-complete" : active ? "is-active" : ""} key={`${index}-${step.step}`}>
                          <span aria-hidden="true">{completed ? "✓" : active ? "•" : "○"}</span>
                          <span>{step.step}</span>
                          <small>{completed ? "完成" : active ? "进行中" : "待处理"}</small>
                        </li>
                      );
                    })}
                  </ol>
                ) : <p className="agent-console__empty">Codex 尚未报告 Plan。</p>}
              </section>

              <section className="agent-console__activity-card" aria-labelledby="agent-tools-title">
                <div className="agent-console__activity-heading">
                  <h5 id="agent-tools-title">工具活动</h5>
                  <span>{toolEvents.length ? `${toolEvents.length} 项安全摘要` : "暂无活动"}</span>
                </div>
                {toolEvents.length ? (
                  <ul className="agent-console__tool-list">
                    {toolEvents.map((event) => (
                      <li key={`${event.participant_seq}-${event.event_seq}`}>
                        <span className="agent-console__tool-icon" aria-hidden="true">{event.kind === "item_completed" ? "✓" : "…"}</span>
                        <span>
                          <strong>{toolLabel(event.item_type)}</strong>
                          <small>{event.kind === "item_completed" ? "已完成" : "进行中"}{typeof event.duration_ms === "number" ? ` · ${event.duration_ms} ms` : ""}{typeof event.exit_code === "number" ? ` · exit ${event.exit_code}` : ""}</small>
                        </span>
                        {event.item_type === "fileChange" && typeof event.file_count === "number" ? <small>{event.file_count} 文件</small> : null}
                      </li>
                    ))}
                  </ul>
                ) : <p className="agent-console__empty">当前没有可显示的工具活动。</p>}
                <p className="agent-console__proof">仅显示安全类别与摘要；命令、参数、输出和路径不会进入浏览器。</p>
              </section>

              <section className="agent-console__activity-card" aria-labelledby="agent-skills-title">
                <div className="agent-console__activity-heading">
                  <h5 id="agent-skills-title">Skills</h5>
                  <span>{skillDecisions.length ? `${skillDecisions.length} 项 durable decision` : "本轮暂无"}</span>
                </div>
                {skillDecisions.length ? (
                  <ul className="agent-console__skill-list">
                    {skillDecisions.map((decision) => (
                      <li key={`${decision.skill_id}:${decision.version}:${decision.context_status}`}>
                        <strong>{decision.skill_id}</strong>
                        <span>v{decision.version} · {decision.context_status === "submitted" ? "已提交上下文" : "已选择"}</span>
                        <small>{decision.selection_reason}</small>
                      </li>
                    ))}
                  </ul>
                ) : <p className="agent-console__empty">没有可展示的 bundled Skill decision。</p>}
                <p className="agent-console__proof">Skills 来自 Room durable projection，不由 provider 文本推断。</p>
              </section>

              <section className="agent-console__activity-card" aria-labelledby="agent-activity-title">
                <div className="agent-console__activity-heading">
                  <h5 id="agent-activity-title">Goal / Turn / Context</h5>
                  <span>{activityEvents.length ? `${activityEvents.length} 条摘要` : "暂无"}</span>
                </div>
                {activityEvents.length ? (
                  <ul className="agent-console__activity-list">
                    {activityEvents.map((event) => <li key={`${event.participant_seq}-${event.event_seq}`}><span>{eventSummary(event)}</span><small>{event.observed_at ?? "时间未知"}</small></li>)}
                  </ul>
                ) : <p className="agent-console__empty">暂无 Goal、turn 或上下文活动。</p>}
              </section>
            </section>
          </>
        )}

        <div className="agent-console__log" role="log" aria-live="polite" aria-relevant="additions" aria-label="Codex 原生事件">
          {logEvents.length ? logEvents.map((nativeEvent) => (
            <article className="agent-console__event" key={`${nativeEvent.participant_seq}-${nativeEvent.event_seq}`}>
              <button
                type="button"
                aria-label={`${eventSummary(nativeEvent)} · 事件 ${nativeEvent.event_seq}`}
                onClick={(event) => {
                  detailTriggerRef.current = event.currentTarget;
                  setDetailEvent(nativeEvent);
                }}
              >
                <span>{eventSummary(nativeEvent)}</span>
                <small>{nativeEvent.observed_at ?? "时间未知"}</small>
              </button>
            </article>
          )) : <p>暂无可显示的原生事件。</p>}
          {participant.omitted_event_count ? <p>更早的 {participant.omitted_event_count} 项事件已省略。</p> : null}
        </div>
      </section>

      <details className="agent-console__bridge-disclosure">
        <summary>Room observation 与高级证据</summary>
      <section className="agent-console__source" aria-labelledby="room-bridge-title">
        <div className="agent-console__section-heading">
          <h4 id="room-bridge-title">xmuse Room Bridge</h4>
          <span className="agent-console__source-badge">chat.db 耐久事实</span>
        </div>
        <dl className="agent-console__facts">
          <div><dt>Hold</dt><dd>{participant.room_bridge.hold?.state ?? "未知"}</dd></div>
          <div><dt>待处理 observation</dt><dd>{queue.unresolved_count}</dd></div>
          <div><dt>active attempt</dt><dd>{queue.active_attempt_count}</dd></div>
          <div><dt>根阶段阻塞</dt><dd>{queue.root_blocking ? "是" : "否"}</dd></div>
        </dl>
        {queue.root_blocking ? (
          <p className="agent-console__notice" role="status">其他 Agent 可完成根回应；后续同轮跟进正在等待此 Agent。</p>
        ) : null}
        <ol className="agent-console__bridge-actions" aria-label="最近 Room Bridge 动作">
          {participant.room_bridge.actions.slice(0, 8).map((action) => (
            <li key={action.action_id}>
              <span>{action.capability_id}</span>
              <strong>{action.status ?? "未知"}</strong>
              {action.reason_code ? <small>{action.reason_code}</small> : null}
            </li>
          ))}
        </ol>
        <p className="agent-console__proof">Bridge 的 applied 仅证明动作账本已应用，不替代 Codex 原生 Goal 或 settings snapshot。</p>
      </section>
      </details>

      <form className="agent-console__composer" onSubmit={submit}>
        <label htmlFor={`agent-console-input-${participant.participant.participant_id}`}>发送给 {participant.participant.display_name} 的单 Agent Codex Console</label>
        <label className="agent-console__mode">
          本次普通文本模式
          <select
            aria-label="Console 默认模式"
            value={localMode}
            disabled={pending}
            onChange={(event) => onPreferenceChange(event.target.value as CodexConsoleMode)}
          >
            <option value="default">Default</option>
            <option value="plan">Plan</option>
          </select>
        </label>
        <textarea
          ref={composerRef}
          id={`agent-console-input-${participant.participant.participant_id}`}
          aria-label={`给 ${participant.participant.display_name} 的 Console 输入`}
          value={draft}
          disabled={pending}
          rows={3}
          placeholder="输入普通文本，或 /goal、/plan、/steer、/review…"
          onChange={(event) => setDraft(event.target.value)}
          onCompositionStart={() => { composingRef.current = true; }}
          onCompositionEnd={() => { composingRef.current = false; }}
          onKeyDown={handleComposerKeyDown}
        />
        {draft.trimStart().startsWith("/") ? (
          <div className="agent-console__command-menu" role="listbox" aria-label="可用 Codex 命令">
            {CONSOLE_COMMANDS.filter(([command]) => command.startsWith(draft.trim().split(/\s/, 1)[0])).map(([command, description]) => (
              <button aria-selected="false" key={command} onClick={() => { setDraft(`${command} `); requestAnimationFrame(() => composerRef.current?.focus()); }} role="option" type="button"><strong>{command}</strong><span>{description}</span></button>
            ))}
          </div>
        ) : null}
        <div className="agent-console__composer-footer">
          <span>不会作为 Room 发言 · Enter 发送 · 当前 {localMode}</span>
          <button type="submit" disabled={pending || !draft.trim()}>{pending ? "处理中…" : "发送"}</button>
        </div>
        <p className="agent-console__aliases">可用别名：/goal /model /effort /plan /default /steer /interrupt /compact /review /status</p>
      </form>

      {(localError || error) ? <p className="agent-console__error" role="alert">{localError ?? error}</p> : null}

      {confirmation && confirmCopy ? (
        <div className="agent-console__dialog-layer" onKeyDown={(event) => handleDialogKeyDown(event, closeConfirmation)}>
          <button className="agent-console__scrim" type="button" tabIndex={-1} aria-label="关闭确认" disabled={pending} onClick={closeConfirmation} />
          <div className="agent-console__dialog" role="alertdialog" aria-modal="true" aria-labelledby="agent-console-confirm-title">
            <h4 id="agent-console-confirm-title">{confirmCopy.title}</h4>
            <p>{confirmCopy.body}</p>
            <div className="agent-console__dialog-actions">
              <button ref={cancelConfirmRef} type="button" disabled={pending} onClick={closeConfirmation}>返回</button>
              <button
                type="button"
                disabled={pending}
                onClick={async () => {
                  await onAction(
                    confirmation.capabilityId,
                    confirmation.safeRequest,
                    confirmation.descriptor,
                    confirmation.descriptor.confirmation_required
                  );
                  setConfirmation(null);
                }}
              >{confirmCopy.confirm}</button>
            </div>
          </div>
        </div>
      ) : null}

      {detailEvent ? (
        <div className="agent-console__dialog-layer" onKeyDown={(event) => handleDialogKeyDown(event, () => setDetailEvent(null))}>
          <button className="agent-console__scrim" type="button" tabIndex={-1} aria-label="关闭事件详情" onClick={() => setDetailEvent(null)} />
          <div className="agent-console__dialog agent-console__dialog--wide" role="dialog" aria-modal="true" aria-labelledby="agent-console-detail-title">
            <div className="agent-console__section-heading">
              <h4 id="agent-console-detail-title">Codex 原生事件详情</h4>
              <button ref={closeDetailRef} type="button" onClick={() => setDetailEvent(null)}>关闭</button>
            </div>
            <p>{eventSummary(detailEvent)}</p>
            {detailEvent.explanation ? <p>{detailEvent.explanation}</p> : null}
            {detailEvent.steps?.length ? (
              <ol>{detailEvent.steps.map((step, index) => <li key={`${index}-${step.step}`}><strong>{step.status}</strong> · {step.step}</li>)}</ol>
            ) : null}
            {detailEvent.text ? <pre>{detailEvent.text}</pre> : null}
            {detailEvent.truncated ? <p className="agent-console__notice">该事件为有界摘要，部分内容已省略。</p> : null}
          </div>
        </div>
      ) : null}
    </section>
  );
}

/**
 * Key the controlled console to its durable participant identity. Agent switches therefore
 * cannot leak an unsent draft, open confirmation, or event detail into another Agent.
 */
export function AgentConsole(props: AgentConsoleProps) {
  return (
    <ParticipantAgentConsole
      key={props.participant.participant.participant_id}
      {...props}
    />
  );
}
