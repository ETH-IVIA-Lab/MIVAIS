function fmtTime(ms: number): string {
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return `${m}:${String(s % 60).padStart(2, "0")}`;
}

export function PlaybackControls({
  playing,
  currentT,
  totalT,
  speed,
  eventCount,
  disabled,
  onTogglePlay,
  onRestart,
  onSpeedChange,
}: {
  playing: boolean;
  currentT: number;
  totalT: number;
  speed: number;
  eventCount: number;
  disabled: boolean;
  onTogglePlay: () => void;
  onRestart: () => void;
  onSpeedChange: (speed: number) => void;
}) {
  return (
    <div id="ctrl-row">
      <button className="ctrl-btn primary" id="play-btn" onClick={onTogglePlay} disabled={disabled}>
        {playing ? "⏸ Pause" : "▶ Play"}
      </button>
      <button className="ctrl-btn" onClick={onRestart} title="Restart">
        ⏮
      </button>
      <span className="ctrl-label">Speed:</span>
      <select className="speed-select" value={speed} onChange={(e) => onSpeedChange(Number(e.target.value))}>
        {[0.5, 1, 2, 5, 10].map((s) => (
          <option key={s} value={s}>
            {s}×
          </option>
        ))}
      </select>
      <span className="ctrl-time">
        {fmtTime(currentT)} / {fmtTime(totalT)}
      </span>
      <span style={{ marginLeft: "auto", fontSize: 10, color: "var(--muted)" }}>{eventCount > 0 ? `${eventCount} events` : ""}</span>
    </div>
  );
}
