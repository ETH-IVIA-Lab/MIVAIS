import type { WorldStateDelta } from "./useReplayEngine";

function fmtT(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(2)}s`;
}

function fmtVal(v: unknown): string {
  if (v === null || v === undefined) return "∅";
  let s = typeof v === "object" ? JSON.stringify(v) : String(v);
  if (s.length > 90) s = `${s.slice(0, 90)}…`;
  return s;
}

export function Inspector({
  currentT,
  changeAtCurrent,
  state,
  changedKeys,
  onKeyClick,
}: {
  currentT: number;
  changeAtCurrent: WorldStateDelta | null;
  state: Record<string, unknown> | null;
  changedKeys: Set<string>;
  onKeyClick?: (key: string) => void;
}) {
  return (
    <aside className="replay-events card rp-inspector" style={{height: "100%"}}>
      <header className="replay-section-head">
        <h2>Inspector</h2>
        <span className="muted small mono">{fmtT(currentT)}</span>
      </header>
      <div>
        {changeAtCurrent ? (
          <>
            <div className="insp-head">
              <span className="insp-ico" style={{ color: changeAtCurrent.cause.color }}>
                ●
              </span>
              <strong>{changeAtCurrent.cause.label}</strong>&nbsp;changed&nbsp;
              <span className="muted">
                {Object.keys(changeAtCurrent.delta).length} key{Object.keys(changeAtCurrent.delta).length > 1 ? "s" : ""}
              </span>
            </div>
            <ul className="insp-delta">
              {Object.entries(changeAtCurrent.delta).map(([k, v]) => (
                <li key={k}>
                  <code
                    className={`insp-key${onKeyClick ? " clickable" : ""}`}
                    title="Show the full change history of this key"
                    onClick={() => onKeyClick?.(k)}
                  >
                    {k}
                  </code>
                  <span className="insp-from">{fmtVal(v.from)}</span>
                  <span className="insp-arrow">→</span>
                  <span className="insp-to">{fmtVal(v.to)}</span>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="muted small">No world-state change yet at this point.</p>
        )}
      </div>
      <div className="insp-state-head">World state at this moment</div>
      <div className="insp-state">
        {state ? (
          Object.entries(state)
            .filter(([k]) => k !== "dataset")
            .map(([k, v]) => (
              <div key={k} className={`insp-row ${changedKeys.has(k) ? "changed" : ""}`}>
                <code
                  className={`insp-key${onKeyClick ? " clickable" : ""}`}
                  title="Show the full change history of this key"
                  onClick={() => onKeyClick?.(k)}
                >
                  {k}
                </code>
                <span className="insp-val">{fmtVal(v)}</span>
              </div>
            ))
        ) : (
          <p className="muted small">No world state captured (video-only replay).</p>
        )}
      </div>
    </aside>
  );
}
