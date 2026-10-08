import { expect, test } from "@playwright/test";

// No backend and no mocks: the shell still boots, serves both routes and says it is connecting.
test("the shell boots on / and on a room route without a backend", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("navigation", { name: "房间" }).or(page.getByRole("button", { name: "打开房间列表" }))).toBeVisible();
  await page.goto("/rooms/conv_00000000000000000000000000000001");
  await expect(page.locator("body")).not.toBeEmpty();
});
