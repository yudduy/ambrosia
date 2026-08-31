import { Information } from "@carbon/icons-react";
import type { Coverage } from "../lib/types";

export function CoverageBanner({ coverage }: { coverage: Coverage }) {
  return (
    <div className={`coverage-banner ${coverage.complete ? "coverage-banner--complete" : ""}`}>
      <Information size={18} aria-hidden="true" />
      <span>{coverage.covered_days}/{coverage.expected_days} days</span>
    </div>
  );
}
