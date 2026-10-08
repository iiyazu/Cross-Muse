import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { agentMessage, installWorkroom, ROOM_ID } from "./support/workroom-mock";

const ROOM_URL = `/rooms/${ROOM_ID}`;

async function axeClean(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(results.violations.map((violation) => `${violation.id}: ${violation.nodes.map((node) => node.target.join(" ")).join(", ")}`)).toEqual([]);
}

async function openPanel(page: Page) {
  await page.getByRole("button", { name: /^工作面板/ }).click();
  return page.getByRole("dialog", { name: "工作面板" }).or(page.getByRole("complementary", { name: "工作面板" }));
}

test.describe("room", () => {
  test("shows the timeline, sends a message and stays axe-clean in both themes", async ({ page }) => {
    const recorded = await installWorkroom(page, {
      timeline: [agentMessage(2, "part_00000000000000000000000000000002", "Agent 0", "已拆分为 **3** 个模块，见看板。")]
    });
    await page.goto(ROOM_URL);
    await expect(page.getByRole("heading", { level: 1, name: "board room" })).toBeVisible();
    const log = page.getByRole("log", { name: "房间消息" });
    await expect(log).toContainText("kickoff");
    await expect(log.getByText("3", { exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "当前 Agent 状态" })).toBeVisible();

    await page.getByLabel("发送消息").fill("请先发布契约");
    await page.getByRole("button", { name: "发送", exact: true }).click();
    await expect.poll(() => recorded.filter((entry) => entry.url.endsWith("/messages")).length).toBe(1);
    expect(recorded[0].body).toMatchObject({ message: "请先发布契约" });

    await axeClean(page);
    await page.emulateMedia({ colorScheme: "dark" });
    await page.reload();
    await expect(log).toContainText("kickoff");
    await axeClean(page);
  });
});

test.describe("board", () => {
  test("counts only accepted work and explains an integration fallback", async ({ page }) => {
    await installWorkroom(page, { board: "integration_fallback_to_incumbent" });
    await page.goto(ROOM_URL);
    const strip = page.getByRole("button", { name: /^看板：3 个模块，3 个已验收，2 个已集成/ });
    await expect(strip).toBeVisible();

    const panel = await openPanel(page);
    const modules = panel.getByRole("region", { name: "模块" });
    await expect(modules.getByRole("button", { name: /^模块 m1/ })).toContainText("集成冲突待处理");
    await expect(modules.getByRole("button", { name: /^模块 m2/ })).toContainText("已进入集成分支");

    await modules.getByRole("button", { name: /^模块 m1/ }).click();
    const ladder = panel.getByRole("list", { name: "信任链" });
    await expect(ladder).toContainText("宿主验证");
    await expect(ladder).toContainText("分支中是旧版本");
    await expect(panel.getByText("复核", { exact: true })).toHaveCount(0);

    await panel.getByRole("button", { name: "集成详情" }).click();
    await expect(panel).toContainText("已回退到旧版本");
    await panel.getByRole("button", { name: "返回" }).click();
    await panel.getByRole("button", { name: "返回" }).click();
    await expect(panel.getByRole("region", { name: "完成度" })).toBeVisible();
    await axeClean(page);
  });

  test("approves a split with its digest", async ({ page }) => {
    const recorded = await installWorkroom(page, { board: "split_pending" });
    await page.goto(ROOM_URL);
    const panel = await openPanel(page);
    const decisions = panel.getByRole("region", { name: "待你处理" });
    await decisions.getByRole("button", { name: "查看拆分" }).click();
    await panel.getByRole("button", { name: "批准拆分" }).click();
    await expect.poll(() => recorded.length).toBe(1);
    expect(recorded[0].url).toContain("/api/room-board-splits/");
    expect(JSON.stringify(recorded[0].body)).toContain("sha256:");
  });

  test("binds an operator review to the material it shows", async ({ page }) => {
    const recorded = await installWorkroom(page, { board: "review_operator_pending" });
    await page.goto(ROOM_URL);
    const panel = await openPanel(page);
    await panel.getByRole("region", { name: "待你处理" }).getByRole("button", { name: "开始复核" }).click();
    const dialog = page.getByRole("dialog", { name: "复核模块 beta" });
    await expect(dialog.getByLabel("待复核的补丁")).toContainText("<U+202E>");
    await dialog.getByPlaceholder("你看了什么、为什么这么判断").fill("看过，只改了 beta。");
    await dialog.getByRole("button", { name: "提交背书" }).click();
    await expect.poll(() => recorded.length).toBe(1);
    expect(recorded[0].body).toMatchObject({
      verdict: "endorse",
      expected_digest: "sha256:2df9fdc1871ddcd97c6d419b27d5e4f10c6dd82ade419d6c431f080d81fa0db5"
    });
  });

  test("keeps agent-authored text out of titles, labels and the document title", async ({ page }) => {
    await installWorkroom(page, { board: "injection_text" });
    await page.goto(ROOM_URL);
    const panel = await openPanel(page);
    await expect(panel.getByRole("region", { name: "模块" })).toBeVisible();
    const leaked = await page.evaluate(() => {
      const texts = [...document.querySelectorAll("[data-agent-text]")].map((node) => node.textContent ?? "").filter((text) => text.length > 8);
      const attributes = [...document.querySelectorAll("*")].flatMap((element) =>
        ["title", "aria-label", "aria-description", "alt"].map((name) => element.getAttribute(name) ?? "")
      );
      return texts.filter((text) => {
        const probe = text.replace(/^Agent 自述[：· 未经宿主核实]*/, "").slice(0, 16);
        return probe.length > 6 && (attributes.some((value) => value.includes(probe)) || document.title.includes(probe));
      });
    });
    expect(leaked).toEqual([]);
  });
});

test.describe("deep links", () => {
  test("a module link opens the panel on that module and the address follows the panel", async ({ page }) => {
    await installWorkroom(page, { board: "integration_fallback_to_incumbent" });
    await page.goto(`${ROOM_URL}?module=m1`);
    const panel = page.getByRole("dialog", { name: "工作面板" }).or(page.getByRole("complementary", { name: "工作面板" }));
    await expect(panel.getByRole("list", { name: "信任链" })).toContainText("分支中是旧版本");
    await panel.getByRole("button", { name: "集成详情" }).click();
    await expect(page).toHaveURL(/\?integration=/);
    await panel.getByRole("button", { name: "返回" }).click();
    await expect(page).toHaveURL(/\?module=m1$/);
    await page.reload();
    await expect(panel.getByRole("list", { name: "信任链" })).toBeVisible();
  });

  test("a review link opens the operator review while it is still pending", async ({ page }) => {
    await installWorkroom(page, { board: "review_operator_pending" });
    await page.goto(`${ROOM_URL}?review=beta`);
    await expect(page.getByRole("dialog", { name: "复核模块 beta" })).toBeVisible();
  });

  test("a review link to a decided review shows the module, not a dialog", async ({ page }) => {
    await installWorkroom(page, { board: "review_endorsed" });
    await page.goto(`${ROOM_URL}?review=beta`);
    const panel = page.getByRole("dialog", { name: "工作面板" }).or(page.getByRole("complementary", { name: "工作面板" }));
    await expect(panel.getByRole("list", { name: "信任链" })).toBeVisible();
    await expect(page.getByRole("dialog", { name: /^复核模块/ })).toHaveCount(0);
  });
});

test.describe("narrow window", () => {
  test.skip(({ viewport }) => (viewport?.width ?? 0) >= 1280, "the dock is a sheet only below 1280px");

  test("opens the work panel as a sheet and returns focus when it closes", async ({ page }) => {
    await installWorkroom(page, { board: "integration_fallback_to_incumbent" });
    await page.goto(ROOM_URL);
    const trigger = page.getByRole("button", { name: /^工作面板/ });
    await trigger.click();
    await expect(page.getByRole("dialog", { name: "工作面板" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "工作面板" })).toBeHidden();
    await expect(trigger).toBeFocused();
  });
});
