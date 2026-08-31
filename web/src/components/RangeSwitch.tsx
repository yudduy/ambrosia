import type { RangeName } from "../lib/types";

export function RangeSwitch({ value, onChange }: { value: RangeName; onChange: (value: RangeName) => void }) {
  const labels: Record<RangeName, string> = { "7d": "7 days", "28d": "4 weeks", "90d": "3 months" };
  return (
    <div className="range-switch" role="group" aria-label="Date range">
      {(["7d", "28d", "90d"] as RangeName[]).map((range) => (
        <button
          type="button"
          key={range}
          className={range === value ? "active" : ""}
          aria-pressed={range === value}
          onClick={() => onChange(range)}
        >
          {labels[range]}
        </button>
      ))}
    </div>
  );
}
