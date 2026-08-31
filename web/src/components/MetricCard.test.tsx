import { render, screen } from "@testing-library/react";
import { MetricCard } from "./MetricCard";
import type { MetricSummary } from "../lib/types";

const metric: MetricSummary = {
  key: "steps",
  label: "Steps",
  value: 8420,
  unit: "steps/day",
  comparison: {
    recent_value: 8420,
    baseline_median: 7800,
    baseline_p10: 6000,
    baseline_p90: 9000,
    difference: 620,
    difference_percent: 7.9,
    baseline_days: 28,
    direction: "within",
    description: "Usual range",
  },
  series: [
    { date: "2026-08-28", value: 8000, covered: true },
    { date: "2026-08-29", value: 8840, covered: true },
  ],
  coverage: {
    covered_days: 2,
    expected_days: 2,
    ratio: 1,
    complete: true,
    message: "2/2 days",
  },
};

test("renders the value without repeating a usual-range comparison", () => {
  render(<MetricCard metric={metric} />);
  expect(screen.getByText("8,420")).toBeInTheDocument();
  expect(screen.queryByText("Usual range")).not.toBeInTheDocument();
});

test("keeps a meaningful change", () => {
  render(<MetricCard metric={{ ...metric, comparison: { ...metric.comparison, description: "620 more than usual" } }} />);
  expect(screen.getByText("620 more than usual")).toBeInTheDocument();
});
