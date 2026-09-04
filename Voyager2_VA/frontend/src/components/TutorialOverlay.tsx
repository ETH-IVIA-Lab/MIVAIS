export function TutorialOverlay({ open, onDismiss }: { open: boolean; onDismiss: () => void }) {
  return (
    <div
      className={`bookmark-overlay${open ? " open" : ""}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onDismiss();
      }}
    >
      <div className="bookmark-panel" style={{ maxWidth: 600 }}>
        <div className="bookmark-panel-header">
          <h2>How to use Voyager 2</h2>
          <button className="bookmark-close" onClick={onDismiss}>
            ×
          </button>
        </div>
        <div style={{ padding: 16, fontSize: 13, lineHeight: 1.8, color: "var(--text)" }}>
          <p>
            <strong>Voyager 2</strong> is a mixed-initiative visual analytics system. It blends manual chart creation with automated
            recommendations.
          </p>

          <h3 style={{ margin: "16px 0 8px", fontSize: 14 }}>Three ways to explore:</h3>

          <p>
            <strong>1. Manual specification</strong> — Drag a field from the left panel onto an encoding shelf (x, y, color, size, ...)
            in the center. Or click the <strong>+</strong> button on any field to auto-assign it to the best shelf. The system renders
            your chart immediately.
          </p>

          <p>
            <strong>2. Related views (right panel)</strong> — When you have a focus chart, the system proactively suggests:
          </p>
          <ul style={{ margin: "4px 0 8px 20px" }}>
            <li>
              <strong>Summaries</strong> — aggregate versions (mean, histogram) of your current view
            </li>
            <li>
              <strong>Field suggestions</strong> — your chart with one extra field added
            </li>
            <li>
              <strong>Alt. encodings</strong> — same data, different visual design (transpose, color vs facet, etc.)
            </li>
          </ul>
          <p>
            Click <strong>Specify</strong> on any suggestion to make it your new focus chart.
          </p>

          <p>
            <strong>3. Wildcards</strong> — Drag a wildcard field (e.g. "? Quantitative") onto a shelf. The system generates a gallery
            of all valid charts for that placeholder. Great for systematic exploration.
          </p>

          <h3 style={{ margin: "16px 0 8px", fontSize: 14 }}>Other features:</h3>
          <ul style={{ margin: "4px 0 8px 20px" }}>
            <li>
              Star icon to <strong>bookmark</strong> any chart with notes
            </li>
            <li>
              <strong>Undo/Redo</strong> (Ctrl+Z / Ctrl+Y)
            </li>
            <li>Aggregate, bin, and time unit controls on each shelf</li>
            <li>Mark type selector (point, bar, line, area, tick)</li>
          </ul>

          <p style={{ marginTop: 12, color: "var(--text-secondary)" }}>
            When no chart is specified, the right panel shows <strong>univariate summaries</strong> — distributions of every field in
            the dataset. Start by clicking a summary to explore it.
          </p>

          <button
            style={{
              marginTop: 16,
              padding: "8px 20px",
              background: "var(--blue)",
              color: "white",
              border: "none",
              borderRadius: "var(--radius)",
              cursor: "pointer",
              fontSize: 13,
              fontWeight: 600,
            }}
            onClick={onDismiss}
          >
            Start exploring
          </button>
        </div>
      </div>
    </div>
  );
}
