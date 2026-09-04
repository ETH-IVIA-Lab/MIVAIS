import type { ReplayMarker } from "./types";

function fmtT(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(2)}s`;
}

export function MarkerList({
  markers,
  onJump,
  onDelete,
}: {
  markers: ReplayMarker[];
  onJump: (t_ms: number) => void;
  onDelete?: (marker_id: string) => void;
}) {
  const sorted = [...markers].sort((a, b) => a.t_ms - b.t_ms);
  return (
    <aside className="replay-events card">
      <header className="replay-section-head">
        <h2>Markers</h2>
        <span className="muted small">{markers.length || "none yet"}</span>
      </header>
      <ol className="marker-list">
        {sorted.length === 0 && (
          <li className="muted small" style={{ padding: "6px 8px" }}>
            {onDelete ? (
              <>
                No markers. Set the playhead and click <strong>Mark</strong> to add one.
              </>
            ) : (
              "No markers."
            )}
          </li>
        )}
        {sorted.map((m) => (
          <li key={m.marker_id} className="marker-item" title={`jump to ${fmtT(m.t_ms)}`} onClick={() => onJump(m.t_ms)}>
            <span className="mono small">{fmtT(m.t_ms)}</span>
            <span className="chip">{m.kind || "note"}</span>
            <span className="marker-label">
              {m.label || <span className="muted">(no label)</span>}
              {m.quote && (
                <span className="marker-quote" title={m.quote}>
                  &ldquo;{m.quote}&rdquo;
                </span>
              )}
            </span>
            {onDelete && (
              <button
                type="button"
                className="marker-del"
                title="Delete marker"
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(m.marker_id);
                }}
              >
                ×
              </button>
            )}
          </li>
        ))}
      </ol>
    </aside>
  );
}
