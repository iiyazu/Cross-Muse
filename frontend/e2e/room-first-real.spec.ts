import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { mkdir } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";

const STATE_SCHEMA = "room_first_real_browser_state/v2";
const EVIDENCE_SCHEMA = "room_first_real_browser_evidence/v2";
const enabled = process.env.XMUSE_REAL_ACCEPTANCE === "1";
const phase = process.env.XMUSE_REAL_PHASE ?? "";
const statePath = process.env.XMUSE_REAL_STATE_PATH ?? "";
const evidencePath = process.env.XMUSE_REAL_EVIDENCE_PATH ?? "";
const screenshotPath = process.env.XMUSE_REAL_SCREENSHOT_PATH ?? "";
const chatApiBaseUrl = process.env.XMUSE_REAL_CHAT_API_BASE_URL ?? "http://127.0.0.1:8201/api/chat";
const operatorTokenSha256 = process.env.XMUSE_REAL_OPERATOR_TOKEN_SHA256 ?? "";
const operatorTokenLength = Number(process.env.XMUSE_REAL_OPERATOR_TOKEN_LENGTH ?? 0);
const NORMAL_PROMPT = "请各自围绕 xmuse Room 的实现方案与风险，给出一句不重复的独立判断；不要修改文件。";
const MENTION_PROMPT = "请各自检查 xmuse 的因果批处理实现，并给出一句新的方案或风险判断；@ 仅影响优先级，不要修改文件。";
const HANDOFF_PROMPT = "这是一次由 Human 明确给出的 directed baton：请各自审计上一轮结论，并用一句话说明下一步方案应如何交接；可选择 handoff，但无需为验收改变真实判断；不要修改文件。";

type JsonRecord = Record<string, unknown>;

type TurnKind = "normal" | "mention" | "handoff";

type TurnEvidence = {
  kind: TurnKind;
  correlation_id: string;
  root_activity_id: string;
  observation_count: number;
  attempt_count: number;
  skill_decision_count: number;
  logical_batch_count: number;
  infrastructure_retry_count: number;
  expected_mention_handle: string | null;
};

type BrowserState = {
  schema_version: typeof STATE_SCHEMA;
  conversation_id: string;
  participant_ids: string[];
  turns: TurnEvidence[];
};

type PhaseEvidence = {
  status: "passed" | "failed";
  room_status?: string;
  participant_count?: number;
  durable_outcome_count?: number;
  skill_evidence_count?: number;
  observation_count?: number;
  attempt_count?: number;
  skill_decision_count?: number;
  turn_count?: number;
  logical_batch_count?: number;
  infrastructure_retry_count?: number;
  batch_evidence_count?: number;
  root_visible_action_count?: number;
  peer_visible_followup_count?: number;
  near_duplicate_pair_count?: number;
  direct_create_unauthorized_status?: number;
  direct_message_unauthorized_status?: number;
  recovery_visible?: boolean;
  identity_preserved?: boolean;
  reason_code?: string;
};

type BrowserEvidence = {
  schema_version: typeof EVIDENCE_SCHEMA;
  conversation_id?: string;
  participant_ids: string[];
  phases: Record<string, PhaseEvidence>;
  console_error_count: number;
  page_error_count: number;
};

test.skip(!enabled, "real Workroom acceptance requires XMUSE_REAL_ACCEPTANCE=1");
test.describe.configure({ mode: "serial" });

function record(value: unknown): JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as JsonRecord)
    : {};
}

function list(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function requiredString(value: unknown, name: string): string {
  if (typeof value !== "string" || !value.trim()) throw new Error(`${name}_missing`);
  return value.trim();
}

async function readJson(path: string): Promise<JsonRecord> {
  return record(JSON.parse(await readFile(path, "utf8")));
}

async function writeJson(path: string, payload: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.${randomUUID()}.tmp`;
  await writeFile(temporary, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  await rename(temporary, path);
}

async function readState(): Promise<BrowserState> {
  const payload = await readJson(statePath);
  expect(payload.schema_version).toBe(STATE_SCHEMA);
  const participants = list(payload.participant_ids).map((item) => requiredString(item, "participant_id"));
  expect(participants).toHaveLength(4);
  expect(new Set(participants).size).toBe(4);
  const turns = list(payload.turns).map(record).map((turn) => ({
    kind: requiredString(turn.kind, "turn_kind") as TurnKind,
    correlation_id: requiredString(turn.correlation_id, "turn_correlation_id"),
    root_activity_id: requiredString(turn.root_activity_id, "turn_root_activity_id"),
    observation_count: Number(turn.observation_count),
    attempt_count: Number(turn.attempt_count),
    skill_decision_count: Number(turn.skill_decision_count),
    logical_batch_count: Number(turn.logical_batch_count),
    infrastructure_retry_count: Number(turn.infrastructure_retry_count),
    expected_mention_handle:
      typeof turn.expected_mention_handle === "string" ? turn.expected_mention_handle : null
  }));
  expect(turns.map((turn) => turn.kind)).toEqual(["normal", "mention", "handoff"]);
  expect(turns).toHaveLength(3);
  for (const turn of turns) {
    expect(Number.isSafeInteger(turn.observation_count)).toBe(true);
    expect(Number.isSafeInteger(turn.attempt_count)).toBe(true);
    expect(Number.isSafeInteger(turn.skill_decision_count)).toBe(true);
    expect(Number.isSafeInteger(turn.logical_batch_count)).toBe(true);
    expect(Number.isSafeInteger(turn.infrastructure_retry_count)).toBe(true);
  }
  return {
    schema_version: STATE_SCHEMA,
    conversation_id: requiredString(payload.conversation_id, "conversation_id"),
    participant_ids: participants,
    turns
  };
}

async function updateEvidence(
  currentPhase: string,
  phaseEvidence: PhaseEvidence,
  counts: { consoleErrors: number; pageErrors: number },
  state?: BrowserState
): Promise<void> {
  let prior: JsonRecord = {};
  try {
    prior = await readJson(evidencePath);
  } catch {
    // The first phase owns creation.
  }
  const phases = record(prior.phases);
  const participantIds = state?.participant_ids ?? list(prior.participant_ids).filter(
    (item): item is string => typeof item === "string"
  );
  const payload: BrowserEvidence = {
    schema_version: EVIDENCE_SCHEMA,
    conversation_id: state?.conversation_id ?? (typeof prior.conversation_id === "string" ? prior.conversation_id : undefined),
    participant_ids: participantIds,
    phases: { ...phases, [currentPhase]: phaseEvidence } as Record<string, PhaseEvidence>,
    console_error_count: Number(prior.console_error_count ?? 0) + counts.consoleErrors,
    page_error_count: Number(prior.page_error_count ?? 0) + counts.pageErrors
  };
  await writeJson(evidencePath, payload);
}

function observeBrowserErrors(page: Page) {
  const counts = { consoleErrors: 0, pageErrors: 0 };
  const diagnostics: string[] = [];
  page.on("console", (message) => {
    diagnostics.push(message.text());
    if (message.type() === "error") counts.consoleErrors += 1;
  });
  page.on("pageerror", (error) => {
    diagnostics.push(error.message);
    counts.pageErrors += 1;
  });
  return { counts, diagnostics };
}

function containsOperatorToken(value: string): boolean {
  if (!operatorTokenSha256 || !Number.isInteger(operatorTokenLength) || operatorTokenLength < 16) {
    throw new Error("operator_token_digest_contract_invalid");
  }
  if (value.length < operatorTokenLength) return false;
  for (let index = 0; index <= value.length - operatorTokenLength; index += 1) {
    const candidate = value.slice(index, index + operatorTokenLength);
    if (createHash("sha256").update(candidate, "utf8").digest("hex") === operatorTokenSha256) {
      return true;
    }
  }
  return false;
}

async function assertOperatorTokenAbsent(page: Page, diagnostics: string[]): Promise<void> {
  const browserSurface = await page.evaluate(() => ({
    html: document.documentElement.outerHTML,
    urls: [
      window.location.href,
      ...performance.getEntriesByType("resource").map((entry) => entry.name)
    ]
  }));
  expect(containsOperatorToken(browserSurface.html)).toBe(false);
  expect(browserSurface.urls.some(containsOperatorToken)).toBe(false);
  expect(diagnostics.some(containsOperatorToken)).toBe(false);
}

async function sameOriginJson(page: Page, path: string, body: JsonRecord) {
  return page.evaluate(
    async ({ requestPath, requestBody }) => {
      const response = await fetch(requestPath, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestBody)
      });
      let payload: unknown = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }
      return { status: response.status, payload };
    },
    { requestPath: path, requestBody: body }
  );
}

async function fetchProjection(request: APIRequestContext, conversationId: string): Promise<JsonRecord> {
  const response = await request.get(
    `${chatApiBaseUrl}/conversations/${encodeURIComponent(conversationId)}/room-projection`
  );
  expect(response.status()).toBe(200);
  const projection = record(await response.json());
  expect(projection.schema_version).toBe("room_chat_projection/v3");
  return projection;
}

function normalizeReply(value: unknown): string {
  return String(value ?? "")
    .normalize("NFKC")
    .toLocaleLowerCase()
    .replace(/[\p{P}\p{S}\s]+/gu, "");
}

function trigramDice(left: string, right: string): number {
  if (left === right) return left ? 1 : 0;
  if (left.length < 3 || right.length < 3) return 0;
  const grams = (value: string) => {
    const counts = new Map<string, number>();
    for (let index = 0; index <= value.length - 3; index += 1) {
      const gram = value.slice(index, index + 3);
      counts.set(gram, (counts.get(gram) ?? 0) + 1);
    }
    return counts;
  };
  const leftGrams = grams(left);
  const rightGrams = grams(right);
  let overlap = 0;
  for (const [gram, count] of leftGrams) {
    overlap += Math.min(count, rightGrams.get(gram) ?? 0);
  }
  const leftCount = [...leftGrams.values()].reduce((sum, value) => sum + value, 0);
  const rightCount = [...rightGrams.values()].reduce((sum, value) => sum + value, 0);
  return (2 * overlap) / (leftCount + rightCount);
}

function isNearDuplicate(left: unknown, right: unknown): boolean {
  const normalizedLeft = normalizeReply(left);
  const normalizedRight = normalizeReply(right);
  if (!normalizedLeft || !normalizedRight) return false;
  if (normalizedLeft === normalizedRight) return true;
  return Math.min(normalizedLeft.length, normalizedRight.length) >= 16
    && trigramDice(normalizedLeft, normalizedRight) >= 0.92;
}

function turnByCorrelation(projection: JsonRecord, correlationId: string): JsonRecord {
  const turn = list(projection.turns)
    .map(record)
    .find((candidate) => candidate.correlation_id === correlationId);
  if (!turn) throw new Error("expected_turn_missing");
  return turn;
}

function settledSummary(projection: JsonRecord, correlationId: string) {
  const turn = turnByCorrelation(projection, correlationId);
  const participants = list(turn.participants).map(record);
  const durableOutcomes = participants.filter((participant) => Object.keys(record(participant.latest_outcome)).length > 0);
  const selectedSkillEvidence = participants.filter(
    (participant) => Object.keys(record(participant.root_skill_decision)).length > 0
  );
  const participantIds = new Set(
    participants.map((participant) => requiredString(participant.participant_id, "participant_id"))
  );
  const timelineItems = list(projection.timeline_items)
    .map(record)
    .filter((item) => item.correlation_id === correlationId);
  const rootItem = timelineItems.find((item) => item.activity_id === turn.root_activity_id);
  if (!rootItem) throw new Error("turn_root_timeline_item_missing");
  const visibleActions = timelineItems.filter((item) => {
    const participantId = record(item.actor).participant_id;
    return typeof participantId === "string" && participantIds.has(participantId);
  });
  const rootVisibleActions = visibleActions.filter((item) => item.context_only_tail !== true);
  const peerVisibleFollowups = visibleActions.filter((item) => item.context_only_tail === true);
  const nearDuplicatePairs: Array<[string, string]> = [];
  for (const participantId of participantIds) {
    const actions = visibleActions.filter(
      (item) => record(item.actor).participant_id === participantId
    );
    for (let left = 0; left < actions.length; left += 1) {
      for (let right = left + 1; right < actions.length; right += 1) {
        if (isNearDuplicate(actions[left].content, actions[right].content)) {
          nearDuplicatePairs.push([
            requiredString(actions[left].activity_id, "duplicate_left_activity_id"),
            requiredString(actions[right].activity_id, "duplicate_right_activity_id")
          ]);
        }
      }
    }
  }
  const peerBatchCount = durableOutcomes.filter(
    (participant) => record(participant.latest_outcome).phase === "peer"
  ).length;
  const logicalBatchCount = participants.length + peerBatchCount;
  const attemptCount = Number(turn.attempt_count ?? 0);
  return {
    status: String(turn.status ?? ""),
    participants,
    durableOutcomes,
    selectedSkillEvidence,
    rootItem,
    visibleActions,
    rootVisibleActions,
    peerVisibleFollowups,
    nearDuplicatePairs,
    logicalBatchCount,
    infrastructureRetryCount: Math.max(0, attemptCount - logicalBatchCount),
    observationCount: Number(turn.observation_count ?? 0),
    attemptCount,
    skillDecisionCount: Number(turn.skill_decision_count ?? 0),
    correlationId: requiredString(turn.correlation_id, "root_correlation_id"),
    rootActivityId: requiredString(turn.root_activity_id, "root_activity_id")
  };
}

async function waitForNewSettledTurn(
  request: APIRequestContext,
  conversationId: string,
  priorCorrelations: Set<string>
): Promise<{ projection: JsonRecord; correlationId: string }> {
  let latest: JsonRecord = {};
  let correlationId = "";
  await expect.poll(
    async () => {
      latest = await fetchProjection(request, conversationId);
      const candidate = list(latest.turns)
        .map(record)
        .reverse()
        .find((turn) => (
          typeof turn.correlation_id === "string"
          && !priorCorrelations.has(turn.correlation_id)
        ));
      if (!candidate) {
        return {
          status: "",
          participantCount: 0,
          outcomeCount: 0,
          unresolvedCount: 0
        };
      }
      correlationId = requiredString(candidate.correlation_id, "new_turn_correlation_id");
      const participants = list(candidate.participants).map(record);
      return {
        status: String(candidate.status ?? ""),
        participantCount: participants.length,
        outcomeCount: participants.filter(
          (participant) => Object.keys(record(participant.latest_outcome)).length > 0
        ).length,
        unresolvedCount: participants.reduce(
          (sum, participant) => sum + Number(participant.unresolved_count ?? 0),
          0
        )
      };
    },
    { timeout: 8 * 60_000, intervals: [1_000, 2_000, 5_000] }
  ).toEqual({ status: "settled", participantCount: 4, outcomeCount: 4, unresolvedCount: 0 });
  return { projection: latest, correlationId: requiredString(correlationId, "settled_correlation_id") };
}

function assertBatchEvidence(outcome: JsonRecord): void {
  expect(requiredString(outcome.batch_id, "batch_id")).toMatch(/^observation_batch_/);
  expect(["root", "peer"]).toContain(outcome.phase);
  const memberCount = Number(outcome.member_count ?? 0);
  expect(memberCount).toBeGreaterThanOrEqual(1);
  expect(memberCount).toBeLessThanOrEqual(16);
  expect(Number(outcome.attempt_count ?? 0)).toBeGreaterThanOrEqual(1);
  const refs = list(outcome.member_activity_refs).map(record);
  expect(refs).toHaveLength(memberCount);
  expect(new Set(refs.map((item) => requiredString(item.activity_id, "batch_member_activity_id"))).size)
    .toBe(memberCount);
  const coverage = record(outcome.coverage);
  expect(coverage.mode).toBe("batch");
  expect(Number(coverage.included_member_count ?? 0)).toBe(memberCount);
  expect(Number(coverage.omitted_member_count ?? 0)).toBe(0);
  if (outcome.phase === "root") {
    expect(memberCount).toBe(1);
    expect(outcome.context_only_tail).toBe(false);
  } else if (typeof outcome.produced_activity_id === "string") {
    // Only a visible peer follow-up creates a context-only tail activity.
    // noop/defer legitimately completes the same peer batch without one.
    expect(outcome.context_only_tail).toBe(true);
  }
}

function assertTurnEvidence(
  projection: JsonRecord,
  correlationId: string,
  expectedMentionHandle: string | null
) {
  const summary = settledSummary(projection, correlationId);
  expect(summary.status).toBe("settled");
  expect(summary.participants).toHaveLength(4);
  expect(summary.durableOutcomes).toHaveLength(4);
  expect(summary.observationCount).toBeGreaterThanOrEqual(4);
  expect(summary.logicalBatchCount).toBeGreaterThanOrEqual(4);
  expect(summary.logicalBatchCount).toBeLessThanOrEqual(8);
  expect(summary.attemptCount).toBeGreaterThanOrEqual(summary.logicalBatchCount);
  expect(summary.skillDecisionCount).toBe(summary.attemptCount);

  const expectedObservationCount = 4 + summary.durableOutcomes.reduce((count, participant) => {
    const outcome = record(participant.latest_outcome);
    return count + (outcome.phase === "peer" ? Number(outcome.member_count ?? 0) : 0);
  }, 0);
  expect(summary.observationCount).toBe(expectedObservationCount);

  for (const participant of summary.participants) {
    const outcome = record(participant.latest_outcome);
    assertBatchEvidence(outcome);
    const participantId = requiredString(participant.participant_id, "participant_id");
    expect(summary.rootVisibleActions.filter(
      (item) => record(item.actor).participant_id === participantId
    ).length).toBeLessThanOrEqual(1);
    expect(summary.peerVisibleFollowups.filter(
      (item) => record(item.actor).participant_id === participantId
    ).length).toBeLessThanOrEqual(1);
  }

  const byRole = new Map(
    summary.participants.map((participant) => [String(participant.role), participant])
  );
  expect(record(byRole.get("architect")?.root_skill_decision).skill_id)
    .toBe("implementation-planning");
  expect(record(byRole.get("review")?.root_skill_decision).skill_id)
    .toBe("evidence-review");
  expect(summary.selectedSkillEvidence).toHaveLength(2);
  expect(summary.nearDuplicatePairs).toHaveLength(0);

  const mentions = list(summary.rootItem.mentions).map((item) => requiredString(item, "mention"));
  expect(mentions).toEqual(expectedMentionHandle ? [expectedMentionHandle] : []);
  for (const action of summary.visibleActions.filter((item) => item.kind === "handoff")) {
    expect(list(action.target_participant_ids).length).toBeGreaterThan(0);
    expect(list(action.handoff_targets).length).toBe(list(action.target_participant_ids).length);
  }
  return summary;
}

async function sendAndSettle(
  page: Page,
  request: APIRequestContext,
  conversationId: string,
  prompt: string,
  kind: TurnKind,
  expectedMentionHandle: string | null,
  completedTurns: TurnEvidence[]
): Promise<{ projection: JsonRecord; evidence: TurnEvidence }> {
  const priorCorrelations = new Set(completedTurns.map((turn) => turn.correlation_id));
  await page.getByLabel("发送消息").fill(prompt);
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await expect(page.getByRole("log", { name: "房间消息" })).toContainText(prompt.slice(0, 24));
  const settled = await waitForNewSettledTurn(request, conversationId, priorCorrelations);
  const summary = assertTurnEvidence(
    settled.projection,
    settled.correlationId,
    expectedMentionHandle
  );
  return {
    projection: settled.projection,
    evidence: {
      kind,
      correlation_id: summary.correlationId,
      root_activity_id: summary.rootActivityId,
      observation_count: summary.observationCount,
      attempt_count: summary.attemptCount,
      skill_decision_count: summary.skillDecisionCount,
      logical_batch_count: summary.logicalBatchCount,
      infrastructure_retry_count: summary.infrastructureRetryCount,
      expected_mention_handle: expectedMentionHandle
    }
  };
}

async function openRoom(page: Page, state: BrowserState): Promise<void> {
  await page.goto(`/rooms/${encodeURIComponent(state.conversation_id)}`);
  await expect(page.getByRole("heading", { name: /Room-first acceptance/ })).toBeVisible({ timeout: 30_000 });
}

async function recoverRuntime(page: Page, state: BrowserState): Promise<void> {
  await openRoom(page, state);
  await page.getByRole("button", { name: "成员与状态" }).click();
  const inspector = page.getByRole("complementary", { name: "房间检查器" });
  await expect(inspector.getByRole("region", { name: "运行与恢复" })).toBeVisible();
  const recover = inspector.getByRole("button", { name: /恢复 Room Runtime|启动 Room Runtime/ });
  await expect(recover).toBeVisible({ timeout: 90_000 });
  await recover.click();
  const dialog = page.getByRole("alertdialog");
  await expect(dialog).toContainText("未完成工作将由耐久 observation attempt");
  await dialog.getByRole("button", { name: "确认中断并恢复" }).click();
  const operations = inspector.getByRole("region", { name: "运行与恢复" });
  await expect(operations).toContainText("Runner正常", { timeout: 90_000 });
  await expect(operations).toContainText("Room MCP正常", { timeout: 90_000 });
}

test("production Room-first acceptance phase", async ({ page, request }) => {
  expect(["conversation", "recover-runner", "recover-mcp", "verify"]).toContain(phase);
  expect(statePath).not.toBe("");
  expect(evidencePath).not.toBe("");
  const observed = observeBrowserErrors(page);
  let state: BrowserState | undefined;
  let phaseEvidence: PhaseEvidence = { status: "failed", reason_code: "phase_assertion_failed" };
  try {
    if (phase === "conversation") {
      await page.goto("/");
      const suffix = randomUUID().slice(0, 8);
      const created = await sameOriginJson(page, "/api/rooms", {
        title: `Room-first acceptance ${suffix}`,
        client_request_id: `real-room-${suffix}`,
        roster_template_id: "builtin.development"
      });
      expect(created.status).toBe(201);
      const room = record(created.payload);
      const conversationId = requiredString(room.id, "conversation_id");
      const participants = list(room.participants).map(record);
      expect(participants).toHaveLength(4);
      const participantIds = participants.map((participant) => requiredString(participant.participant_id, "participant_id"));
      expect(new Set(participantIds).size).toBe(4);
      expect(participants.map((participant) => participant.role)).toEqual([
        "architect",
        "execute",
        "review",
        "critic"
      ]);
      expect(participants.every(
        (participant) => record(participant.persona_snapshot).schema_version === "persona_snapshot/v1"
      )).toBe(true);

      const directCreate = await request.post(`${chatApiBaseUrl}/conversations`, {
        data: { title: `Unauthorized acceptance ${suffix}`, client_request_id: `unauthorized-${suffix}` }
      });
      expect(directCreate.status()).toBe(401);
      const directMessage = await request.post(
        `${chatApiBaseUrl}/threads/${encodeURIComponent(conversationId)}/messages`,
        {
          data: {
            message: "This direct write must remain unauthorized.",
            client_request_id: `unauthorized-message-${suffix}`
          }
        }
      );
      expect(directMessage.status()).toBe(401);

      await page.goto(`/rooms/${encodeURIComponent(conversationId)}`);
      await expect(page.getByRole("heading", { name: `Room-first acceptance ${suffix}` })).toBeVisible();
      const initialProjection = await fetchProjection(request, conversationId);
      const projectedParticipants = list(initialProjection.participants).map(record);
      expect(projectedParticipants).toHaveLength(4);
      const architect = projectedParticipants.find((participant) => participant.role === "architect");
      const reviewer = projectedParticipants.find((participant) => participant.role === "review");
      const architectHandle = requiredString(architect?.mention_handle, "architect_mention_handle");
      const reviewerHandle = requiredString(reviewer?.mention_handle, "reviewer_mention_handle");
      const turns: TurnEvidence[] = [];

      const normal = await sendAndSettle(
        page,
        request,
        conversationId,
        NORMAL_PROMPT,
        "normal",
        null,
        turns
      );
      turns.push(normal.evidence);
      const mentioned = await sendAndSettle(
        page,
        request,
        conversationId,
        `${architectHandle} ${MENTION_PROMPT}`,
        "mention",
        architectHandle,
        turns
      );
      turns.push(mentioned.evidence);
      const handedOff = await sendAndSettle(
        page,
        request,
        conversationId,
        `${reviewerHandle} ${HANDOFF_PROMPT}`,
        "handoff",
        reviewerHandle,
        turns
      );
      turns.push(handedOff.evidence);
      expect(new Set(turns.map((turn) => turn.correlation_id)).size).toBe(3);

      state = {
        schema_version: STATE_SCHEMA,
        conversation_id: conversationId,
        participant_ids: participantIds,
        turns
      };
      await writeJson(statePath, state);
      await page.reload();
      await expect(page.getByRole("region", { name: "当前 Agent 状态" })).toContainText("本轮已收束");
      const refreshedProjection = await fetchProjection(request, conversationId);
      const refreshed = turns.map((turn) => {
        const summary = assertTurnEvidence(
          refreshedProjection,
          turn.correlation_id,
          turn.expected_mention_handle
        );
        expect(summary.rootActivityId).toBe(turn.root_activity_id);
        expect(summary.observationCount).toBe(turn.observation_count);
        expect(summary.attemptCount).toBe(turn.attempt_count);
        expect(summary.skillDecisionCount).toBe(turn.skill_decision_count);
        expect(summary.logicalBatchCount).toBe(turn.logical_batch_count);
        expect(summary.participants.map((participant) => participant.participant_id).sort()).toEqual(
          [...participantIds].sort()
        );
        return summary;
      });
      const aggregate = {
        durableOutcomes: refreshed.reduce((sum, summary) => sum + summary.durableOutcomes.length, 0),
        skillDecisions: turns.reduce((sum, turn) => sum + turn.skill_decision_count, 0),
        observations: turns.reduce((sum, turn) => sum + turn.observation_count, 0),
        attempts: turns.reduce((sum, turn) => sum + turn.attempt_count, 0),
        logicalBatches: turns.reduce((sum, turn) => sum + turn.logical_batch_count, 0),
        retries: turns.reduce((sum, turn) => sum + turn.infrastructure_retry_count, 0),
        batchEvidence: refreshed.reduce((sum, summary) => sum + summary.durableOutcomes.length, 0),
        rootActions: refreshed.reduce((sum, summary) => sum + summary.rootVisibleActions.length, 0),
        peerActions: refreshed.reduce((sum, summary) => sum + summary.peerVisibleFollowups.length, 0),
        duplicates: refreshed.reduce((sum, summary) => sum + summary.nearDuplicatePairs.length, 0)
      };
      phaseEvidence = {
        status: "passed",
        room_status: "settled",
        participant_count: 4,
        turn_count: 3,
        durable_outcome_count: aggregate.durableOutcomes,
        skill_evidence_count: aggregate.skillDecisions,
        observation_count: aggregate.observations,
        attempt_count: aggregate.attempts,
        skill_decision_count: aggregate.skillDecisions,
        logical_batch_count: aggregate.logicalBatches,
        infrastructure_retry_count: aggregate.retries,
        batch_evidence_count: aggregate.batchEvidence,
        root_visible_action_count: aggregate.rootActions,
        peer_visible_followup_count: aggregate.peerActions,
        near_duplicate_pair_count: aggregate.duplicates,
        direct_create_unauthorized_status: directCreate.status(),
        direct_message_unauthorized_status: directMessage.status()
      };
    } else if (phase === "recover-runner" || phase === "recover-mcp") {
      state = await readState();
      await recoverRuntime(page, state);
      phaseEvidence = { status: "passed", recovery_visible: true };
    } else {
      const verifiedState = await readState();
      state = verifiedState;
      await openRoom(page, verifiedState);
      const projection = await fetchProjection(request, verifiedState.conversation_id);
      const summaries = verifiedState.turns.map((turn) => {
        const summary = assertTurnEvidence(
          projection,
          turn.correlation_id,
          turn.expected_mention_handle
        );
        expect(summary.rootActivityId).toBe(turn.root_activity_id);
        expect(summary.observationCount).toBe(turn.observation_count);
        expect(summary.attemptCount).toBe(turn.attempt_count);
        expect(summary.skillDecisionCount).toBe(turn.skill_decision_count);
        expect(summary.logicalBatchCount).toBe(turn.logical_batch_count);
        expect(summary.infrastructureRetryCount).toBe(turn.infrastructure_retry_count);
        expect(summary.participants.map((participant) => participant.participant_id).sort()).toEqual(
          [...verifiedState.participant_ids].sort()
        );
        return summary;
      });
      await page.reload();
      await expect(page.getByRole("region", { name: "当前 Agent 状态" })).toContainText("本轮已收束");
      const timeline = page.getByRole("log", { name: "房间消息" });
      await expect(timeline).toContainText(NORMAL_PROMPT.slice(0, 24));
      await expect(timeline).toContainText(MENTION_PROMPT.slice(0, 24));
      await expect(timeline).toContainText(HANDOFF_PROMPT.slice(0, 24));
      await page.screenshot({ path: screenshotPath, fullPage: true });
      const aggregate = {
        durableOutcomes: summaries.reduce((sum, summary) => sum + summary.durableOutcomes.length, 0),
        skillDecisions: verifiedState.turns.reduce((sum, turn) => sum + turn.skill_decision_count, 0),
        observations: verifiedState.turns.reduce((sum, turn) => sum + turn.observation_count, 0),
        attempts: verifiedState.turns.reduce((sum, turn) => sum + turn.attempt_count, 0),
        logicalBatches: verifiedState.turns.reduce((sum, turn) => sum + turn.logical_batch_count, 0),
        retries: verifiedState.turns.reduce((sum, turn) => sum + turn.infrastructure_retry_count, 0),
        batchEvidence: summaries.reduce((sum, summary) => sum + summary.durableOutcomes.length, 0),
        rootActions: summaries.reduce((sum, summary) => sum + summary.rootVisibleActions.length, 0),
        peerActions: summaries.reduce((sum, summary) => sum + summary.peerVisibleFollowups.length, 0),
        duplicates: summaries.reduce((sum, summary) => sum + summary.nearDuplicatePairs.length, 0)
      };
      phaseEvidence = {
        status: "passed",
        room_status: "settled",
        participant_count: 4,
        turn_count: 3,
        durable_outcome_count: aggregate.durableOutcomes,
        skill_evidence_count: aggregate.skillDecisions,
        observation_count: aggregate.observations,
        attempt_count: aggregate.attempts,
        skill_decision_count: aggregate.skillDecisions,
        logical_batch_count: aggregate.logicalBatches,
        infrastructure_retry_count: aggregate.retries,
        batch_evidence_count: aggregate.batchEvidence,
        root_visible_action_count: aggregate.rootActions,
        peer_visible_followup_count: aggregate.peerActions,
        near_duplicate_pair_count: aggregate.duplicates,
        identity_preserved: true
      };
    }
    await assertOperatorTokenAbsent(page, observed.diagnostics);
  } finally {
    await updateEvidence(phase, phaseEvidence, observed.counts, state);
  }
});
