import type { RangeName } from "../lib/types";

export function RangeSwitch({ value, onChange }: { value: RangeName; onChange: (value: RangeName) => void }) {
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
          {range.replace("d", " days")}
        </button>
      ))}
    </div>
  );
}

