import { useMemo } from "react";
import { userColor } from "./classify";
import type { HeartRateSample, ReplayPayload } from "./types";

const W = 1000;
const BAND_HEIGHT = 20;
const PAD_TOP = 3;
const PAD_BOTTOM = 3;

function userLabel(pid: string, participants: ReplayPayload["participants"]): string {
  const p = participants[pid];
  if (p?.anon_id) return p.role ? `${p.anon_id} · ${p.role}` : p.anon_id;
  return `user ${pid.slice(-4)}`;
}


export function HeartRateStrip({
  samples,
  participants,
  tMax,
  currentT,
}: {
  samples: HeartRateSample[];
  participants: ReplayPayload["participants"];
  tMax: number;
  currentT: number;
}) {
  const byParticipant = useMemo(() => {
    const m = new Map<string, HeartRateSample[]>();
    for (const s of samples) {
      const arr = m.get(s.participant_id);
      if (arr) arr.push(s);
      else m.set(s.participant_id, [s]);
    }
    for (const arr of m.values()) arr.sort((a, b) => a.t_ms - b.t_ms);
    return m;
  }, [samples]);

  const lines = useMemo(() => {
    const innerH = BAND_HEIGHT - PAD_TOP - PAD_BOTTOM;
    return [...byParticipant.entries()].map(([pid, pts]) => {
      const bpms = pts.map((p) => p.bpm);
      const min = Math.min(...bpms);
      const max = Math.max(...bpms);
      const range = Math.max(1, max - min);
      const d = pts
        .map((p, i) => {
          const x = tMax ? (p.t_ms / tMax) * W : 0;
          const y = PAD_TOP + innerH - ((p.bpm - min) / range) * innerH;
          return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(" ");
      return { pid, d, min, max, last: pts[pts.length - 1]?.bpm, color: userColor(pid) };
    });
  }, [byParticipant, tMax]);

  if (lines.length === 0) return null;

  const cursorX = tMax ? (currentT / tMax) * W : 0;

  return (
    <div className="rp-timeline rp-heart-rate">
      <div className="rp-lane-gutter">
        {lines.map((l) => (
          <div key={l.pid} className="rp-lane-row" style={{ height: BAND_HEIGHT }} title={`${userLabel(l.pid, participants)} — ${l.min}–${l.max} bpm`}>
            <span className="rp-lane-ico" style={{ color: l.color }}>
              ♥
            </span>
            <span className="rp-lane-name">
              {userLabel(l.pid, participants)}
              {l.last != null ? ` · ${l.last} bpm` : ""}
            </span>
          </div>
        ))}
      </div>
      <div className="rp-track-col">
        <svg
          viewBox={`0 0 ${W} ${lines.length * BAND_HEIGHT}`}
          preserveAspectRatio="none"
          style={{ width: "100%", height: lines.length * BAND_HEIGHT }}
        >
          {lines.map((l, i) => (
            <g key={l.pid} transform={`translate(0, ${i * BAND_HEIGHT})`}>
              <rect x={0} y={0} width={W} height={BAND_HEIGHT} fill="var(--bg-soft)" opacity={0.5} />
              <path d={l.d} fill="none" stroke={l.color} strokeWidth={1.6} opacity={0.9} />
            </g>
          ))}
          <line x1={cursorX} y1={0} x2={cursorX} y2={lines.length * BAND_HEIGHT} stroke="var(--accent)" strokeWidth={2} />
        </svg>
      </div>
    </div>
  );
}
