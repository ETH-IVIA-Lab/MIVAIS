import type { ConnectionStatus } from "mivais-va-client";

const LEGEND: Array<[string, string]> = [
  ["#58a6ff", "WorldState"],
  ["#a78bfa", "MessageBus"],
  ["#818cf8", "Agent"],
  ["#39d3f2", "User"],
  ["#f59e0b", "Gateway"],
  ["#3fb950", "AuditLog"],
];

export function TopBar({ status, onReset }: { status: ConnectionStatus; onReset: () => void }) {
  const live = status === "connected";
  return (
    <div id="topbar">
      <h1>
        PODIUM <span>Infrastructure Topology</span>
      </h1>
      <div className="tb-sep" />
      <div id="conn-status">
        <div className={`conn-dot${live ? " live" : ""}`} />
        <span>{live ? "Live" : status === "reconnecting" ? "Reconnecting…" : "Connecting…"}</span>
      </div>
      <div className="legend">
        {LEGEND.map(([color, label]) => (
          <div className="leg" key={label}>
            <div className="leg-dot" style={{ background: color }} />
            {label}
          </div>
        ))}
      </div>
      <div className="tb-sep" />
      <button id="btn-reset" onClick={onReset}>
        ⊙ Reset View
      </button>
      <a href="/" id="dash-link">
        ← Dashboard
      </a>
    </div>
  );
}
