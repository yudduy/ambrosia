import { Dropdown } from "@carbon/react";
import type { RangeName } from "../lib/types";

const ranges: Array<{ id: RangeName; label: string }> = [
  { id: "7d", label: "Week" },
  { id: "28d", label: "4 weeks" },
  { id: "90d", label: "3 months" },
];

export function RangeSwitch({ value, onChange }: { value: RangeName; onChange: (value: RangeName) => void }) {
  return (
    <div className="range-switch">
      <Dropdown
        id="date-range"
        aria-label="Date range"
        titleText="Date range"
        hideLabel
        label="Choose range"
        items={ranges}
        itemToString={(item) => item?.label ?? ""}
        selectedItem={ranges.find((range) => range.id === value)}
        size="sm"
        autoAlign
        onChange={({ selectedItem }) => selectedItem && onChange(selectedItem.id)}
      />
    </div>
  );
}
