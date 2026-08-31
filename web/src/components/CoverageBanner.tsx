import { Information } from "@carbon/icons-react";
import type { Coverage, Provenance } from "../lib/types";

export function CoverageBanner({ coverage, provenance }: { coverage: Coverage; provenance: Provenance }) {
  return (
    <div className={`coverage-banner ${coverage.complete ? "coverage-banner--complete" : ""}`}>
      <Information size={18} aria-hidden="true" />
      <div>
        <strong>{Math.round(coverage.ratio * 100)}% data coverage</strong>
        <span>{coverage.message}</span>
      </div>
      <div className="coverage-banner__source">
        {provenance.sources.length ? provenance.sources.join(" · ") : "Waiting for first import"}
      </div>
    </div>
  );
}
