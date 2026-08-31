import { expect, test } from "@playwright/test";

test("dashboard navigates every domain without horizontal overflow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("seven days");
  await expect(page.locator(".metric-card")).toHaveCount(7);
  await expect(page.getByText(/Report archive/)).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  await page.getByRole("link", { name: /Fitness/ }).first().click();
  await expect(page.getByRole("heading", { name: "Fitness", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "7 days" }).click();
  await expect(page.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");

  await page.getByRole("link", { name: /Sleep/ }).first().click();
  await expect(page.getByText(/28-night median/).first()).toBeVisible();
  await expect(page.getByText(/five-minute medians/)).toBeVisible();

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
  await expect(page.getByText("Selected: meal.png")).toBeVisible();
  await page.getByRole("button", { name: "Create private draft" }).click();
  await expect(page.getByRole("heading", { name: "Photo is local and sanitized." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Analyze with AI" })).toBeVisible();
  await page.getByRole("button", { name: "Discard" }).click();
  await expect(page.getByText("Selected: meal.png")).not.toBeVisible();
});
