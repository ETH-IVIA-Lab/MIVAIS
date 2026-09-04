function fmtT(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(2)}s`;
}

export function PlaybackControls({
  playing,
  currentT,
  tMax,
  speed,
  status,
  onJumpStart,
  onStepBack,
  onPlayPause,
  onStepForward,
  onMark,
  onSpeedChange,
}: {
  playing: boolean;
  currentT: number;
  tMax: number;
  speed: number;
  status: string;
  onJumpStart: () => void;
  onStepBack: () => void;
  onPlayPause: () => void;
  onStepForward: () => void;
  onMark?: () => void;
  onSpeedChange: (s: number) => void;
}) {
  return (
    <header className="replay-bar">
      <div className="replay-controls">
        <button type="button" className="button icon-only" title="Jump to start" onClick={onJumpStart}>
          ⏮
        </button>
        <button type="button" className="button icon-only" title="Previous event" onClick={onStepBack}>
          ◀
        </button>
        <button type="button" className="button primary" onClick={onPlayPause}>
          {playing ? "⏸" : "▶"} <span>{playing ? "Pause" : "Play"}</span>
        </button>
        <button type="button" className="button icon-only" title="Next event" onClick={onStepForward}>
          ▶
        </button>
        {onMark && (
          <button type="button" className="btn ghost" title="Drop a marker at the current time" onClick={onMark}>
            🚩 Mark
          </button>
        )}
        <span className="replay-speed">
          <label className="muted small">Speed</label>
          <select value={speed} onChange={(e) => onSpeedChange(Number(e.target.value))}>
            {[0.5, 1, 2, 5, 20].map((s) => (
              <option key={s} value={s}>
                {s}×
              </option>
            ))}
          </select>
        </span>
      </div>
      <div className="replay-status">
        <span className={`status-dot ${status}`} />
        <span className="muted small">{status}</span>
      </div>
      <div className="replay-time">
        <span className="mono">{fmtT(currentT)}</span>
        <span className="muted">/</span>
        <span className="mono muted">{fmtT(tMax)}</span>
      </div>
    </header>
  );
}
