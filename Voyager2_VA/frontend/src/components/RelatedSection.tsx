import { useState } from "react";
import type { FilterSpec, ViewSpec } from "../types";
import { StarIcon } from "./StarIcon";
import { VegaChart } from "./VegaChart";

const DEFAULT_SHOW = 4;

export function RelatedSection({
  title,
  specs,
  dataset,
  onSpecify,
  onBookmark,
  isBookmarked,
  filters,
}: {
  title: string;
  specs: ViewSpec[];
  dataset: unknown[];
  onSpecify: (view: ViewSpec) => void;
  onBookmark: (view: ViewSpec) => void;
  isBookmarked?: (view: ViewSpec) => boolean;
  filters?: FilterSpec[];
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? specs : specs.slice(0, DEFAULT_SHOW);

  return (
    <div className="related-section">
      <div className="related-section-header" onClick={() => setCollapsed((c) => !c)}>
        <span className={`arrow${collapsed ? " collapsed" : ""}`}>&#9660;</span>
        {title}
        <span className="badge">{specs.length}</span>
      </div>
      <div className={`related-section-body${collapsed ? " collapsed" : ""}`}>
        {specs.length === 0 ? (
          <div style={{ color: "var(--text-secondary)", fontSize: 12, padding: 8 }}>No suggestions yet.</div>
        ) : (
          <>
            {visible.map((spec, i) => (
              <div className="related-card" key={i}>
                {spec._title && (
                  <div className="related-card-title" title={spec._title}>
                    {spec._title}
                  </div>
                )}
                <VegaChart spec={spec} dataset={dataset} width={290} height={165} renderer="canvas" lazy compact filters={filters} className="chart-container" />
                <div className="related-card-actions">
                  <button type="button" className="action-btn specify" onClick={() => onSpecify(spec)}>
                    Specify
                  </button>
                  <button type="button" className="action-btn bookmark-small" onClick={() => onBookmark(spec)}>
                    <StarIcon filled={isBookmarked?.(spec) ?? false} size={13} />
                  </button>
                </div>
              </div>
            ))}
            {specs.length > DEFAULT_SHOW && (
              <button
                type="button"
                style={{
                  width: "100%",
                  padding: 6,
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius)",
                  background: "var(--bg-page)",
                  cursor: "pointer",
                  fontSize: 11,
                  color: "var(--text-secondary)",
                  marginTop: 4,
                }}
                onClick={() => setExpanded((e) => !e)}
              >
                {expanded ? "Show less" : `Show all ${specs.length} views`}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  );
}
