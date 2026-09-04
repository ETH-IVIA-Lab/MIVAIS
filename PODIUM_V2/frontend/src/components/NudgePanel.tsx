export function NudgePanel({
  numericCols,
  nudges,
  interactive = false,
  onNudge,
}: {
  numericCols: string[];
  nudges: Record<string, -1 | 1 | 0>;
  interactive?: boolean;
  onNudge?: (col: string, dir: -1 | 0 | 1) => void;
}) {
  return (
    <div>
      {numericCols.map((col) => {
        const v = nudges[col] ?? 0;
        return (
          <div key={col} className="nudge-row">
            <span className="n-label">{col}</span>
            <div className="n-btns">
              <button
                type="button"
                className={`n-btn${v === -1 ? " down" : ""}`}
                disabled={!interactive}
                onClick={() => onNudge?.(col, -1)}
              >
                ↓
              </button>
              <button
                type="button"
                className="n-btn"
                disabled={!interactive}
                onClick={() => onNudge?.(col, 0)}
              >
                −
              </button>
              <button
                type="button"
                className={`n-btn${v === 1 ? " up" : ""}`}
                disabled={!interactive}
                onClick={() => onNudge?.(col, 1)}
              >
                ↑
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
