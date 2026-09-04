import type { FilterSpec, ViewSpec } from "../types";
import { StarIcon } from "./StarIcon";
import { VegaChart } from "./VegaChart";

export function WildcardGallery({
  results,
  dataset,
  onSpecify,
  onBookmark,
  isBookmarked,
  filters,
}: {
  results: ViewSpec[];
  dataset: unknown[];
  onSpecify: (view: ViewSpec) => void;
  onBookmark: (view: ViewSpec) => void;
  isBookmarked?: (view: ViewSpec) => boolean;
  filters?: FilterSpec[];
}) {
  if (!results.length) return null;

  return (
    <div className="wildcard-gallery">
      <div className="wildcard-gallery-title">Wildcard Results</div>
      <div className="wildcard-grid">
        {results.map((spec, i) => (
          <div className="wildcard-card" key={i}>
            <VegaChart spec={spec} dataset={dataset} width={190} height={125} renderer="canvas" lazy compact filters={filters} className="wc-chart" />
            <div className="wc-actions">
              <button type="button" className="action-btn specify" onClick={() => onSpecify(spec)}>
                Specify
              </button>
              <button type="button" className="action-btn bookmark-small" onClick={() => onBookmark(spec)}>
                <StarIcon filled={isBookmarked?.(spec) ?? false} size={13} />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
