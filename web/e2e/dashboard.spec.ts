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

test("health chat accepts a meal photo and restores the conversation", async ({ page }) => {
  const thumbnail = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
  const uploaded = {
    id: "draft-1", created_at: "2026-08-30T20:00:00Z", expires_at: "2026-08-31T20:00:00Z",
    status: "uploaded", note: null, thumbnail_url: thumbnail, analysis: null,
  };
  let persisted = false;
  await page.addInitScript(() => localStorage.setItem("ambrosia-ai-disclosure", "accepted"));
  await page.route("**/api/assistant/status", (route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({
      provider: "omp", running: true, authenticated: true,
      image_capable_model: true, model: "test-model", login_url: null, reason: null,
    }),
  }));
  await page.route("**/api/assistant/conversation", (route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify(persisted ? {
      thread: { id: "thread-1", provider: "omp", created_at: "2026-08-30T20:00:00Z", title: "My health chat" },
      messages: [
        { id: "user-1", role: "user", text: "How does this fit my training?", image_url: thumbnail, created_at: "2026-08-30T20:01:00Z" },
        { id: "reply-1", role: "assistant", text: "It looks protein-forward. Portion size is uncertain.", image_url: null, created_at: "2026-08-30T20:01:01Z" },
      ],
    } : { thread: null, messages: [] }),
  }));
  await page.route("**/api/assistant/threads", (route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ id: "thread-1" }),
  }));
  await page.route("**/api/nutrition/uploads", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(uploaded) }));
  await page.route("**/api/assistant/threads/thread-1/events?live=true", (route) => route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body: "retry: 60000\nevent: message_completed\ndata: {\"text\":\"It looks protein-forward. Portion size is uncertain.\"}\n\n",
  }));
  await page.route("**/api/assistant/threads/thread-1/turns", (route) => {
    persisted = true;
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ turn_id: "turn-1" }) });
  });
  await page.goto("/nutrition");
  await expect(page.getByRole("heading", { name: "Nutrition", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Analyze a meal" })).toHaveCount(0);
  await page.getByRole("button", { name: "Open health chat" }).click();
  await expect(page.getByRole("heading", { name: "What do you want to know?" })).toBeVisible();
  await page.locator('input[type="file"]').setInputFiles({
    name: "meal.png",
    mimeType: "image/png",
    buffer: Buffer.from(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
      "base64",
    ),
  });
  await expect(page.getByText("meal.png", { exact: true })).toBeVisible();
  await page.getByPlaceholder("Ask about your health").fill("How does this fit my training?");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByText("It looks protein-forward. Portion size is uncertain.")).toBeVisible();
  await expect.poll(() => persisted).toBe(true);
  await page.reload();
  await page.getByRole("button", { name: "Open health chat" }).click();
  await expect(page.getByText("How does this fit my training?")).toBeVisible();
  await expect(page.getByText("It looks protein-forward. Portion size is uncertain.")).toBeVisible();
});
