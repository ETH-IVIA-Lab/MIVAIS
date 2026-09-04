import type { ReactNode } from "react";
import type { FilterSpec, ViewSpec } from "../types";
import { StarIcon } from "./StarIcon";
import { VegaChart } from "./VegaChart";

export function FocusView({
  view,
  dataset,
  bookmarked = false,
  onBookmark,
  popover,
  filters,
}: {
  view: ViewSpec | null;
  dataset: unknown[];
  bookmarked?: boolean;
  onBookmark: () => void;
  popover?: ReactNode;
  filters?: FilterSpec[];
}) {
  return (
    <div className="focus-card" style={{ position: "relative" }}>
      <div className="focus-card-header">
        <span className="focus-card-title">Focus View</span>
        <button className="bookmark-btn" title={bookmarked ? "Remove bookmark" : "Bookmark this view"} onClick={onBookmark}>
          <StarIcon filled={bookmarked} size={18} />
        </button>
      </div>
      <div className="focus-chart">
        <VegaChart
          spec={view}
          dataset={dataset}
          width={450}
          height={300}
          filters={filters}
          emptyText="Drag fields to shelves to create a view"
        />
      </div>
      {popover}
    </div>
  );
}
