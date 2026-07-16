import { expect, test, type Page } from "@playwright/test";
import { createHash, randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

const INPUT_SCHEMA = "room_soak_browser_input/v1";
const LEGACY_EVIDENCE_SCHEMA = "room_soak_browser_evidence/v1";
const EVIDENCE_SCHEMA = "room_soak_browser_evidence/v2";
const EVIDENCE_CONSUMER = "g9_live_goal_memory_soak";
const enabled = process.env.XMUSE_SOAK_BROWSER === "1";
const goalMemorySoak = process.env.XMUSE_SOAK_GOAL_MEMORY === "1";
const frontendUrl = process.env.XMUSE_SOAK_FRONTEND_URL ?? "";
const inputPath = process.env.XMUSE_SOAK_BROWSER_INPUT_PATH ?? "";
const evidencePath = process.env.XMUSE_SOAK_BROWSER_EVIDENCE_PATH ?? "";
const OPAQUE_DIGEST = /^sha256:[0-9a-f]{64}$/;

type JsonRecord = Record<string, unknown>;
type ViewportKey = "640x900" | "1280x720" | "1440x900";
type BrowserCounts = {
  consoleErrors: number;
  pageErrors: number;
  http5xx: number;
};
type ViewportEvidence = {
  width: number;
  height: number;
  room_count: number;
  refresh_count: number;
  console_error_count: number;
  page_error_count: number;
  http_5xx_count: number;
  native_snapshot_count: number;
  native_capabilities_count: number;
  native_event_count: number;
  native_event_kind_count: number;
  history_partial_count: number;
  digest: string;
};

const VIEWPORTS: Record<ViewportKey, { project: string; width: number; height: number }> = {
  "640x900": { project: "soak-640x900", width: 640, height: 900 },
  "1280x720": { project: "soak-1280x720", width: 1280, height: 720 },
  "1440x900": { project: "soak-1440x900", width: 1440, height: 900 }
};

test.skip(!enabled, "real Room soak verification requires XMUSE_SOAK_BROWSER=1");
test.describe.configure({ mode: "serial" });

function record(value: unknown): JsonRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as JsonRecord
    : {};
}

function roomId(value: unknown): string {
  if (typeof value !== "string" || !/^conv_[a-zA-Z0-9_-]{8,200}$/.test(value)) {
    throw new Error("soak_browser_room_id_invalid");
  }
  return value;
}

function fixedLoopbackUrl(raw: string): URL {
  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    throw new Error("soak_browser_frontend_url_invalid");
  }
  if (
    parsed.protocol !== "http:" ||
    !["127.0.0.1", "localhost", "[::1]"].includes(parsed.hostname) ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error("soak_browser_frontend_url_invalid");
  }
  return parsed;
}

async function atomicJson(path: string, payload: unknown): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${path}.${randomUUID()}.tmp`;
  await writeFile(temporary, `${JSON.stringify(payload)}\n`, "utf8");
  await rename(temporary, path);
}

function observeErrors(page: Page): BrowserCounts {
  const counts = { consoleErrors: 0, pageErrors: 0, http5xx: 0 };
  page.on("console", (message) => {
    if (message.type() === "error") counts.consoleErrors += 1;
  });
  page.on("pageerror", () => {
    counts.pageErrors += 1;
  });
  page.on("requestfailed", (request) => {
    if (
      isXmuseApiUrl(request.url()) &&
      request.failure()?.errorText !== "net::ERR_ABORTED"
    ) counts.pageErrors += 1;
  });
  page.on("response", (response) => {
    if (isXmuseApiUrl(response.url()) && response.status() >= 500) counts.http5xx += 1;
  });
  return counts;
}

function isXmuseApiUrl(raw: string): boolean {
  try {
    const url = new URL(raw);
    return (
      ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname) &&
      url.pathname.includes("/api/")
    );
  } catch {
    return false;
  }
}

function viewportForProject(projectName: string): [ViewportKey, { width: number; height: number }] {
  for (const [key, value] of Object.entries(VIEWPORTS) as [ViewportKey, typeof VIEWPORTS[ViewportKey]][]) {
    if (value.project === projectName) return [key, value];
  }
  throw new Error("soak_browser_viewport_project_invalid");
}

function sha256(value: unknown): string {
  const canonical = (item: unknown): unknown => {
    if (Array.isArray(item)) return item.map(canonical);
    if (typeof item === "object" && item !== null) {
      return Object.fromEntries(
        Object.entries(item as JsonRecord)
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([key, child]) => [key, canonical(child)])
      );
    }
    return item;
  };
  return `sha256:${createHash("sha256").update(JSON.stringify(canonical(value)), "utf8").digest("hex")}`;
}

function isRoomApiResponse(raw: string, room: string, suffix: string): boolean {
  try {
    const url = new URL(raw);
    return (
      isXmuseApiUrl(raw) &&
      url.pathname.endsWith(`/api/chat/conversations/${encodeURIComponent(room)}/${suffix}`)
    );
  } catch {
    return false;
  }
}

function validateNativeProjection(value: unknown, room: string): {
  participantCount: number;
  snapshotCount: number;
  capabilitiesCount: number;
  eventCount: number;
  eventKindCount: number;
  historyPartialCount: number;
} {
  const projection = record(value);
  expect(projection.schema_version).toBe("room_codex_projection/v1");
  expect(projection.conversation_id).toBe(room);
  expect(projection.projection_only).toBe(true);
  expect(projection.proof_boundary).toBe("projection_not_codex_app_server_or_room_authority");
  expect(Array.isArray(projection.participants)).toBe(true);
  const participants = (projection.participants as unknown[]).map(record);
  expect(participants.length).toBeGreaterThan(0);
  let snapshotCount = 0;
  let capabilitiesCount = 0;
  let historyPartialCount = 0;
  for (const participant of participants) {
    const identity = record(participant.participant);
    expect(typeof identity.participant_id).toBe("string");

    const snapshot = record(participant.native_snapshot);
    const snapshotValue = record(snapshot.value);
    expect(snapshot.source).toBe("codex_app_server_projection_cache");
    expect(typeof snapshot.observed_at).toBe("string");
    expect(snapshot.available).toBe(true);
    expect(snapshotValue.schema_version).toBe("room_codex_native_snapshot/v1");
    expect(snapshotValue.source).toBe("codex_app_server");
    expect(record(snapshotValue.guards).session).toMatch(OPAQUE_DIGEST);
    snapshotCount += 1;

    const capabilities = record(participant.capabilities);
    const capabilitiesValue = record(capabilities.value);
    expect(capabilities.source).toBe("codex_app_server_projection_cache");
    expect(typeof capabilities.observed_at).toBe("string");
    expect(capabilities.available).toBe(true);
    expect(capabilitiesValue.schema_version).toBe("room_codex_native_capabilities/v1");
    expect(capabilitiesValue.source).toBe("codex_app_server");
    expect(Array.isArray(capabilitiesValue.capabilities)).toBe(true);
    const descriptors = (capabilitiesValue.capabilities as unknown[]).map(record);
    expect(descriptors.length).toBeGreaterThan(0);
    for (const descriptor of descriptors) {
      expect(typeof descriptor.capability_id).toBe("string");
      expect(descriptor.session_guard).toMatch(OPAQUE_DIGEST);
    }
    capabilitiesCount += 1;

    expect(participant.history_partial).toBe(true);
    expect(Number.isSafeInteger(participant.omitted_event_count)).toBe(true);
    expect(Number(participant.omitted_event_count)).toBeGreaterThanOrEqual(0);
    historyPartialCount += 1;
  }
  const nativeEvents = record(projection.native_events);
  const eventItems = Array.isArray(nativeEvents.items) ? nativeEvents.items.map(record) : [];
  expect(nativeEvents.projection_available).toBe(true);
  expect(eventItems.length).toBeGreaterThan(0);
  const eventKinds = new Set(eventItems.map((item) => item.kind).filter((kind): kind is string => typeof kind === "string"));
  for (const requiredKind of ["turn_started", "item_completed", "token_usage_updated", "turn_completed"]) {
    expect(eventKinds.has(requiredKind)).toBe(true);
  }
  return {
    participantCount: participants.length,
    snapshotCount,
    capabilitiesCount,
    eventCount: eventItems.length,
    eventKindCount: eventKinds.size,
    historyPartialCount
  };
}

async function updateEvidence(
  viewportKey: ViewportKey,
  viewport: ViewportEvidence
): Promise<void> {
  let prior: JsonRecord = {};
  if (viewportKey !== "640x900") {
    try {
      prior = record(JSON.parse(await readFile(evidencePath, "utf8")));
    } catch {
      throw new Error("soak_browser_evidence_sequence_invalid");
    }
    if (
      prior.schema_version !== EVIDENCE_SCHEMA ||
      prior.consumer !== EVIDENCE_CONSUMER ||
      prior.headed !== (process.env.XMUSE_SOAK_HEADED === "1")
    ) {
      throw new Error("soak_browser_evidence_sequence_invalid");
    }
  }
  const viewports = {
    ...(viewportKey === "640x900" ? {} : record(prior.viewports)),
    [viewportKey]: viewport
  };
  const headed = process.env.XMUSE_SOAK_HEADED === "1";
  await atomicJson(evidencePath, {
    schema_version: EVIDENCE_SCHEMA,
    consumer: EVIDENCE_CONSUMER,
    headed,
    viewports,
    digest: sha256({ consumer: EVIDENCE_CONSUMER, headed, viewports })
  });
}

test(goalMemorySoak
  ? "refreshes every selected Room and rebuilds native current state"
  : "refreshes every selected Room without browser errors", async ({ page }, testInfo) => {
  if (!inputPath || !evidencePath) throw new Error("soak_browser_paths_missing");
  const base = fixedLoopbackUrl(frontendUrl);
  const input = record(JSON.parse(await readFile(inputPath, "utf8")));
  if (input.schema_version !== INPUT_SCHEMA || !Array.isArray(input.room_ids)) {
    throw new Error("soak_browser_input_invalid");
  }
  const rooms = input.room_ids.map(roomId);
  if (!rooms.length || rooms.length > 12 || new Set(rooms).size !== rooms.length) {
    throw new Error("soak_browser_room_set_invalid");
  }

  if (!goalMemorySoak) {
    const counts = observeErrors(page);
    let refreshes = 0;
    for (const id of rooms) {
      const target = new URL(`/rooms/${encodeURIComponent(id)}`, base);
      await page.goto(target.toString(), { waitUntil: "domcontentloaded" });
      await expect(page.getByRole("log", { name: "房间消息" })).toBeVisible();
      await expect(page.getByRole("region", { name: "当前 Agent 状态" })).toContainText("本轮已收束");
      await page.reload({ waitUntil: "domcontentloaded" });
      await expect(page.getByRole("log", { name: "房间消息" })).toBeVisible();
      await expect(page.getByRole("region", { name: "当前 Agent 状态" })).toContainText("本轮已收束");
      const idleProjection = await page.waitForResponse(
        (response) =>
          response.request().method() === "GET" &&
          isRoomApiResponse(response.url(), id, "room-projection"),
        { timeout: 20_000 }
      );
      expect(idleProjection.status()).toBeLessThan(500);
      refreshes += 1;
    }
    await atomicJson(evidencePath, {
      schema_version: LEGACY_EVIDENCE_SCHEMA,
      refreshes,
      console_errors: counts.consoleErrors,
      page_errors: counts.pageErrors + counts.http5xx
    });
    expect(counts.consoleErrors).toBe(0);
    expect(counts.pageErrors).toBe(0);
    expect(counts.http5xx).toBe(0);
    return;
  }

  const [viewportKey, expectedViewport] = viewportForProject(testInfo.project.name);
  expect(page.viewportSize()).toEqual({
    width: expectedViewport.width,
    height: expectedViewport.height
  });
  const counts = observeErrors(page);
  let refreshes = 0;
  let nativeSnapshotCount = 0;
  let nativeCapabilitiesCount = 0;
  let nativeEventCount = 0;
  let nativeEventKindCount = 0;
  let historyPartialCount = 0;
  for (const id of rooms) {
    const target = new URL(`/rooms/${encodeURIComponent(id)}`, base);
    await page.goto(target.toString(), { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("log", { name: "房间消息" })).toBeVisible();
    await expect(page.getByRole("region", { name: "当前 Agent 状态" })).toContainText("本轮已收束");
    const workbenchToggle = page.getByRole("button", { name: /工作台/ });
    if (await workbenchToggle.getAttribute("aria-expanded") !== "true") {
      await workbenchToggle.click();
    }
    await expect(page.getByRole("tab", { name: "Agent" })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("heading", { name: "Plan / Todo" })).toBeVisible();
    await expect(page.getByRole("log", { name: "Codex 原生事件" }).locator("article")).not.toHaveCount(0);
    const roomProjectionPromise = page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        isRoomApiResponse(response.url(), id, "room-projection"),
      { timeout: 20_000 }
    );
    const nativeProjectionPromise = page.waitForResponse(
      (response) =>
        response.request().method() === "GET" &&
        isRoomApiResponse(response.url(), id, "codex-agents"),
      { timeout: 20_000 }
    );
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(page.getByRole("log", { name: "房间消息" })).toBeVisible();
    await expect(page.getByRole("region", { name: "当前 Agent 状态" })).toContainText("本轮已收束");
    const [idleProjection, nativeProjection] = await Promise.all([
      roomProjectionPromise,
      nativeProjectionPromise
    ]);
    expect(idleProjection.status()).toBeLessThan(500);
    expect(nativeProjection.status()).toBe(200);
    const native = validateNativeProjection(await nativeProjection.json(), id);
    nativeSnapshotCount += native.snapshotCount;
    nativeCapabilitiesCount += native.capabilitiesCount;
    nativeEventCount += native.eventCount;
    nativeEventKindCount += native.eventKindCount;
    historyPartialCount += native.historyPartialCount;
    refreshes += 1;
  }

  const viewportCounts = {
    width: expectedViewport.width,
    height: expectedViewport.height,
    room_count: rooms.length,
    refresh_count: refreshes,
    console_error_count: counts.consoleErrors,
    page_error_count: counts.pageErrors,
    http_5xx_count: counts.http5xx,
    native_snapshot_count: nativeSnapshotCount,
    native_capabilities_count: nativeCapabilitiesCount,
    native_event_count: nativeEventCount,
    native_event_kind_count: nativeEventKindCount,
    history_partial_count: historyPartialCount
  };
  const viewportEvidence: ViewportEvidence = {
    ...viewportCounts,
    digest: sha256(viewportCounts)
  };
  await updateEvidence(viewportKey, viewportEvidence);
  expect(viewportEvidence.room_count).toBe(rooms.length);
  expect(viewportEvidence.refresh_count).toBe(rooms.length);
  expect(viewportEvidence.native_snapshot_count).toBeGreaterThanOrEqual(rooms.length);
  expect(viewportEvidence.native_capabilities_count).toBe(viewportEvidence.native_snapshot_count);
  expect(viewportEvidence.native_event_count).toBeGreaterThan(0);
  expect(viewportEvidence.native_event_kind_count).toBeGreaterThanOrEqual(4);
  expect(viewportEvidence.history_partial_count).toBe(viewportEvidence.native_snapshot_count);
  expect(counts.http5xx).toBe(0);
  expect(counts.consoleErrors).toBe(0);
  expect(counts.pageErrors).toBe(0);
});
