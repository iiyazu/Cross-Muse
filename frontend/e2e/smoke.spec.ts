import { expect, test } from "@playwright/test";

// Keeps the frontend-e2e check meaningful while the presentation layer is rebuilt: the app
// builds, boots and serves its routes. Real Room flows return with the new UI.
test("the shell serves the placeholder on / and on a room route", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("presentation-reset")).toBeVisible();
  await page.goto("/rooms/conv_00000000000000000000000000000001");
  await expect(page.getByTestId("presentation-reset")).toBeVisible();
});
