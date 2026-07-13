import { defineConfig } from "@playwright/test";

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
    viewport: { width: 1440, height: 900 },
    trace: "off",
    screenshot: "off",
    video: "off"
  },
  projects: [{ name: "real-desktop", use: { viewport: { width: 1440, height: 900 } } }]
});
