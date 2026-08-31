import { expect, test } from "vitest";
import { tooltipMarkup } from "./TrendChart";

test("formats chart tooltips as a date and metric", () => {
  const html = tooltipMarkup(
    { unit: "hr/night" },
    { date: new Date(2026, 7, 7, 12), value: 7.8666666667 },
  );

  expect(html).toContain("Aug 7");
  expect(html).toContain("7.9 <small>hr/night</small>");
  expect(html).not.toContain("x-value");
  expect(html).not.toContain("Group");
});
