import { expect, test } from "@playwright/test";

test("dashboard navigates every domain without horizontal overflow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Today" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Daily readiness" }).getByRole("button")).toHaveCount(7);
  await expect(page.getByRole("heading", { name: "Waiting for last night’s data" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Summarize with AI" })).toBeVisible();
  await expect(page.locator(".daily-metrics article")).toHaveCount(11);
  await expect(page.getByText(/Past weeks/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.getByRole("link", { name: /Fitness/ }).first().click();
  await expect(page.getByRole("heading", { name: "Fitness", exact: true })).toBeVisible();
  await page.getByRole("combobox", { name: "Date range" }).click();
  await page.getByRole("option", { name: "Week", exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Date range" })).toContainText("Week");

  await page.getByRole("link", { name: /Sleep/ }).first().click();
  await expect(page.getByRole("heading", { name: "Last night" })).toBeVisible();

  await page.getByRole("link", { name: /Nutrition/ }).first().click();
  await expect(page.getByRole("heading", { name: "Nutrition", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("meal photo remains a draft until it is analyzed and confirmed", async ({ page }) => {
  await page.goto("/nutrition");
  await page.locator('input[type="file"]').setInputFiles({
    name: "meal.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
      "base64",
    ),
  });
  await expect(page.getByText("meal.png", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Add photo" }).click();
  await expect(page.getByRole("heading", { name: "Ready to analyze" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Analyze", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Discard" }).click();
  await expect(page.getByText("meal.png", { exact: true })).not.toBeVisible();
});
