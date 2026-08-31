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
    description: "Within your recent personal range.",
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
    message: "All 2 days are covered.",
  },
};

test("renders the value, personal comparison, and coverage", () => {
  render(<MetricCard metric={metric} />);
  expect(screen.getByText("8,420")).toBeInTheDocument();
  expect(screen.getByText("Within your recent personal range.")).toBeInTheDocument();
  expect(screen.getByLabelText("All 2 days are covered.")).toBeInTheDocument();
});

