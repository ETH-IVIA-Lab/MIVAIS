import type { TimeseriesPoint } from "../types";

const WIDTH = 600;
const HEIGHT = 220;
const PAD = 12;

function buildPath(values: number[], max: number): string {
  if (values.length < 2) return "";
  const stepX = (WIDTH - PAD * 2) / (values.length - 1);
  return values
    .map((v, i) => {
      const x = PAD + i * stepX;
      const y = HEIGHT - PAD - (max > 0 ? (v / max) * (HEIGHT - PAD * 2) : 0);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}


export function TimeseriesChart({ data }: { data: TimeseriesPoint[] }) {
  if (!data.length) return <p className="muted small">No data yet.</p>;
  const max = Math.max(1, ...data.map((d) => d.total));
  const totalLine = buildPath(
    data.map((d) => d.total),
    max,
  );
  const completedLine = buildPath(
    data.map((d) => d.completed),
    max,
  );
  const areaPath = `${totalLine} L${(WIDTH - PAD).toFixed(1)},${HEIGHT - PAD} L${PAD},${HEIGHT - PAD} Z`;

  return (
    <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" role="img" aria-label="Sessions over time" style={{ width: "100%", height: 220 }}>
      <path d={areaPath} fill="var(--accent)" fillOpacity={0.07} />
      <path d={totalLine} fill="none" stroke="var(--ink)" strokeWidth={2} strokeLinejoin="round" />
      <path d={completedLine} fill="none" stroke="var(--success)" strokeWidth={2} strokeDasharray="4 3" strokeLinejoin="round" />
    </svg>
  );
}
