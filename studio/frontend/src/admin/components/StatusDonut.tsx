import type { StatusBreakdownEntry } from "../types";

const COLORS: Record<string, string> = {
  completed: "var(--success)",
  running: "var(--accent)",
  spawning: "var(--warn)",
  lobby: "var(--color-brand-500)",
  pending: "var(--ink-muted)",
  failed: "var(--error)",
  abandoned: "var(--error)",
  interrupted: "var(--warn)",
};

const SIZE = 120;
const RADIUS = 50;
const CIRC = 2 * Math.PI * RADIUS;

export function StatusDonut({ data }: { data: StatusBreakdownEntry[] }) {
  const total = data.reduce((s, d) => s + d.count, 0);
  if (!total) return <p className="muted small">No sessions yet.</p>;

  let offset = 0;
  const segments = data.map((d) => {
    const frac = d.count / total;
    const dash = frac * CIRC;
    const seg = {
      color: COLORS[d.status] ?? "var(--ink-muted)",
      dasharray: `${dash} ${CIRC - dash}`,
      dashoffset: -offset,
    };
    offset += dash;
    return seg;
  });

  return (
    <div className="donut-wrap">
      <svg width={150} height={150} viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label="Session status breakdown">
        <circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none" stroke="var(--bg-soft)" strokeWidth={18} />
        {segments.map((seg, i) => (
          <circle
            key={i}
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke={seg.color}
            strokeWidth={18}
            strokeDasharray={seg.dasharray}
            strokeDashoffset={seg.dashoffset}
            transform={`rotate(-90 ${SIZE / 2} ${SIZE / 2})`}
          />
        ))}
      </svg>
      <ul className="donut-legend">
        {data.map((d) => (
          <li key={d.status}>
            <span className="dot" style={{ background: COLORS[d.status] ?? "var(--ink-muted)" }} />
            <span>{d.status}</span>
            <span className="muted">{d.count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
