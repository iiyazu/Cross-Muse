import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testIgnore: ["room-first-real.spec.ts", "room-soak-real.spec.ts"],
  fullyParallel: true,
  retries: 0,
  reporter: "line",
  use: {
    baseURL: "http://127.0.0.1:3210",
    trace: "retain-on-failure"
  },
  projects: [
    { name: "desktop", use: { viewport: { width: 1440, height: 900 } } },
    { name: "desktop-min", use: { viewport: { width: 1280, height: 720 } } },
    { name: "compact-640", use: { viewport: { width: 640, height: 900 } } },
    // 1280×720 at browser 200% zoom exposes roughly a 640×360 CSS viewport.
    { name: "zoom-200", use: { viewport: { width: 640, height: 360 } } }
  ],
  webServer: {
    command: "npm run dev -- --hostname 127.0.0.1 --port 3210",
    url: "http://127.0.0.1:3210",
    reuseExistingServer: true,
    timeout: 120_000
  }
});
