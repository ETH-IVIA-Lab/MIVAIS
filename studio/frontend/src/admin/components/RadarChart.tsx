import type { LikertHeatmap } from "../types";

const R = 130;

function meanOf(cells: number[], scaleMin: number): number {
  let total = 0;
  let count = 0;
  cells.forEach((c, i) => {
    total += c * (scaleMin + i);
    count += c;
  });
  return count ? total / count : 0;
}


export function RadarChart({ heatmap, nRuns }: { heatmap: LikertHeatmap; nRuns: number }) {
  const { items, scale_min: scaleMin, scale_max: scaleMax, cells } = heatmap;
  const n = items.length;
  if (n < 3) return null;
  const scaleRange = scaleMax - scaleMin || 1;
  const means = cells.map((row) => meanOf(row, scaleMin));

  const angleFor = (i: number) => ((-90 + (360 / n) * i) * Math.PI) / 180;
  const points = means
    .map((m, i) => {
      const norm = (m - scaleMin) / scaleRange;
      const r = R * norm;
      const a = angleFor(i);
      return `${(r * Math.cos(a)).toFixed(2)},${(r * Math.sin(a)).toFixed(2)}`;
    })
    .join(" ");

  return (
    <div style={{ display: "flex", gap: 22, alignItems: "flex-start", flexWrap: "wrap" }}>
      <svg viewBox="-150 -160 300 320" style={{ width: 320, height: 340 }} role="img" aria-label="Likert radar">
        {[0.2, 0.4, 0.6, 0.8, 1.0].map((ring) => (
          <circle key={ring} cx={0} cy={0} r={R * ring} fill="none" stroke="var(--line)" strokeWidth={1} />
        ))}
        {items.map((item, i) => {
          const a = angleFor(i);
          return (
            <g key={item.id}>
              <line x1={0} y1={0} x2={R * Math.cos(a)} y2={R * Math.sin(a)} stroke="var(--line)" strokeWidth={1} />
              <text
                x={(R + 16) * Math.cos(a)}
                y={(R + 16) * Math.sin(a)}
                textAnchor="middle"
                dominantBaseline="middle"
                fontSize={10}
                fill="var(--ink-soft)"
              >
                {item.label.length > 14 ? `${item.label.slice(0, 13)}…` : item.label}
              </text>
            </g>
          );
        })}
        <polygon points={points} fill="var(--color-brand-500)" fillOpacity={0.25} stroke="var(--color-brand-600)" strokeWidth={2} />
        {means.map((m, i) => {
          const norm = (m - scaleMin) / scaleRange;
          const r = R * norm;
          const a = angleFor(i);
          return <circle key={i} cx={r * Math.cos(a)} cy={r * Math.sin(a)} r={3} fill="var(--color-brand-600)" />;
        })}
      </svg>
      <div style={{ flex: 1, minWidth: 240 }}>
        <p className="muted small">
          Mean rating per item across {nRuns} respondent{nRuns === 1 ? "" : "s"}, on the {scaleMin}–{scaleMax} scale.
        </p>
        <table className="data compact">
          <thead>
            <tr>
              <th>Item</th>
              <th style={{ textAlign: "right" }}>Mean</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, i) => (
              <tr key={item.id}>
                <td>{item.label}</td>
                <td className="mono" style={{ textAlign: "right" }}>
                  {means[i].toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
