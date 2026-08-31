import { expect, test } from "@playwright/test";

test("dashboard navigates every domain without horizontal overflow", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Today" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Daily readiness" }).getByRole("button")).toHaveCount(7);
  await expect(page.locator(".readiness-panel--empty h2")).toHaveText(
    /Building your baseline|Waiting for last night's sleep data|No sleep data came through last night/,
  );
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

test("meal photo is analyzed in one action and waits for confirmation", async ({ page }) => {
  const thumbnail = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
  const uploaded = {
    id: "draft-1", created_at: "2026-08-30T20:00:00Z", expires_at: "2026-08-31T20:00:00Z",
    status: "uploaded", note: "Chicken bowl after the gym", thumbnail_url: thumbnail, analysis: null,
  };
  const analyzed = {
    ...uploaded,
    status: "ready",
    analysis: {
      description: "Chicken rice bowl", meal_type: "meal",
      calories: { low: 600, high: 750 }, protein_g: { low: 40, high: 55 },
      carbs_g: { low: 65, high: 90 }, fat_g: { low: 14, high: 24 },
      sodium_mg: { low: 700, high: 1100 }, ingredients: ["chicken", "rice", "vegetables"],
      confidence: 0.76, uncertainty_note: "Portion size cannot be confirmed from the photo.",
    },
  };
  await page.route("**/api/nutrition/uploads", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(uploaded) }));
  await page.route("**/api/nutrition/drafts/draft-1/**", (route) => {
    const body = route.request().url().endsWith("/analyze") ? analyzed : { ...analyzed, status: "confirmed" };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
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
  await page.getByLabel("Meal note").fill("Chicken bowl after the gym");
  await page.getByRole("button", { name: "Analyze meal" }).click();
  await expect(page.getByRole("heading", { name: "Estimate" })).toBeVisible();
  await expect(page.locator('input[value="Chicken rice bowl"]')).toBeVisible();
  await page.getByRole("button", { name: "Save meal" }).click();
  await expect(page.getByRole("heading", { name: "Analyze a meal" })).toBeVisible();
});
