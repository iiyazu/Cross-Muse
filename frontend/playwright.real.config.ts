import { defineConfig } from "@playwright/test";

const soakHeaded = process.env.XMUSE_SOAK_HEADED === "1";
const goalMemorySoak = process.env.XMUSE_SOAK_GOAL_MEMORY === "1";

export default defineConfig({
  testDir: "./e2e",
  testMatch: ["room-first-real.spec.ts", "room-soak-real.spec.ts"],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: "line",
  outputDir:
    process.env.XMUSE_SOAK_BROWSER_OUTPUT_DIR ??
    process.env.XMUSE_REAL_OUTPUT_DIR ??
    "/tmp/xmuse-room-first-real-playwright",
  timeout: 10 * 60_000,
  expect: { timeout: 90_000 },
  use: {
    baseURL: process.env.XMUSE_REAL_FRONTEND_URL ?? "http://127.0.0.1:3000",
    headless: !soakHeaded,
    trace: "off",
    screenshot: "off",
    video: "off"
  },
  projects: goalMemorySoak
    ? [
        {
          name: "soak-640x900",
          testMatch: "room-soak-real.spec.ts",
          use: { viewport: { width: 640, height: 900 } }
        },
        {
          name: "soak-1280x720",
          testMatch: "room-soak-real.spec.ts",
          use: { viewport: { width: 1280, height: 720 } }
        },
        {
          name: "soak-1440x900",
          testMatch: "room-soak-real.spec.ts",
          use: { viewport: { width: 1440, height: 900 } }
        }
      ]
    : [{ name: "real-desktop", use: { viewport: { width: 1440, height: 900 } } }]
});
