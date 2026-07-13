import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

const INPUT_SCHEMA = "room_soak_browser_input/v1";
const EVIDENCE_SCHEMA = "room_soak_browser_evidence/v1";
const enabled = process.env.XMUSE_SOAK_BROWSER === "1";
const frontendUrl = process.env.XMUSE_SOAK_FRONTEND_URL ?? "";
const inputPath = process.env.XMUSE_SOAK_BROWSER_INPUT_PATH ?? "";
const evidencePath = process.env.XMUSE_SOAK_BROWSER_EVIDENCE_PATH ?? "";

type JsonRecord = Record<string, unknown>;

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

function observeErrors(page: Page): { consoleErrors: number; pageErrors: number } {
  const counts = { consoleErrors: 0, pageErrors: 0 };
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
    if (isXmuseApiUrl(response.url()) && response.status() >= 500) counts.pageErrors += 1;
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

test("refreshes every selected Room without browser errors", async ({ page }) => {
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
      (response) => {
        const url = new URL(response.url());
        return (
          url.pathname.endsWith(
            `/api/chat/conversations/${encodeURIComponent(id)}/room-projection`
          ) && response.request().method() === "GET"
        );
      },
      { timeout: 20_000 }
    );
    expect(idleProjection.status()).toBeLessThan(500);
    refreshes += 1;
  }

  await atomicJson(evidencePath, {
    schema_version: EVIDENCE_SCHEMA,
    refreshes,
    console_errors: counts.consoleErrors,
    page_errors: counts.pageErrors
  });
  expect(counts.consoleErrors).toBe(0);
  expect(counts.pageErrors).toBe(0);
});
