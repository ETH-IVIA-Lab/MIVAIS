import { useCallback, useMemo, useRef, useState } from "react";
import { LaneGutter } from "./LaneGutter";
import type { ReplayMarker } from "./types";
import { LANE_STEP, type ReplayEngine } from "./useReplayEngine";

const W = 1000;

function Scrubber({ tMax, currentT, onScrub }: { tMax: number; currentT: number; onScrub: (t: number) => void }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [dragging, setDragging] = useState(false);

  const xToT = useCallback(
    (clientX: number): number => {
      const svg = svgRef.current;
      if (!svg) return 0;
      const rect = svg.getBoundingClientRect();
      const frac = rect.width ? Math.max(0, Math.min(1, (clientX - rect.left) / rect.width)) : 0;
      return Math.round(frac * (tMax || 1));
    },
    [tMax],
  );

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragging(true);
    onScrub(xToT(e.clientX));
  };
  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!dragging) return;
    onScrub(xToT(e.clientX));
  };
  const onPointerUp = (e: React.PointerEvent<SVGSVGElement>) => {
    e.currentTarget.releasePointerCapture(e.pointerId);
    setDragging(false);
  };
  const onKeyDown = (e: React.KeyboardEvent<SVGSVGElement>) => {
    const step = e.shiftKey ? 10000 : 1000;
    if (e.key === "ArrowLeft" || e.key === "ArrowDown") onScrub(Math.max(0, currentT - step));
    else if (e.key === "ArrowRight" || e.key === "ArrowUp") onScrub(Math.min(tMax || 0, currentT + step));
    else if (e.key === "Home") onScrub(0);
    else if (e.key === "End") onScrub(tMax || 0);
    else return;
    e.preventDefault();
  };

  const x = tMax ? (currentT / tMax) * W : 0;

  return (
    <svg
      ref={svgRef}
      viewBox={`0 0 ${W} 16`}
      preserveAspectRatio="none"
      className="rp-scrubber-svg"
      role="slider"
      tabIndex={0}
      aria-label="Playhead"
      aria-valuemin={0}
      aria-valuemax={tMax || 0}
      aria-valuenow={currentT}
      aria-valuetext={`${(currentT / 1000).toFixed(1)}s`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onKeyDown={onKeyDown}
    >
      <rect x={0} y={6} width={W} height={4} rx={2} fill="var(--bg-soft)" />
      <rect x={0} y={6} width={x} height={4} rx={2} fill="var(--accent)" />
      <circle cx={x} cy={8} r={6} fill="var(--accent)" stroke="var(--bg-card)" strokeWidth={2} />
    </svg>
  );
}

export function Timeline({
  engine,
  markers,
  onScrub,
  onMarkerClick,
}: {
  engine: ReplayEngine;
  markers: ReplayMarker[];
  onScrub: (t: number) => void;
  onMarkerClick: (t: number) => void;
}) {
  const { visibleEvents, lanes, laneIndex, laneOf, absentSpans, svgHeight, currentT, tMax, videoMode, activeVideo, videoGaps } = engine;
  const laneYC = (key: string) => (laneIndex[key] ?? 0) * LANE_STEP + LANE_STEP / 2;

  const watchingKey = videoMode && activeVideo?.participant_id ? `user:${activeVideo.participant_id}` : null;

  const dimmedKeys = useMemo(() => {
    const s = new Set<string>();
    for (const l of lanes) {
      if ((absentSpans[l.key] || []).some((sp) => currentT >= sp.t0 && currentT <= sp.t1)) s.add(l.key);
    }
    return s;
  }, [lanes, absentSpans, currentT]);

  const density = useMemo(() => {
    const N = 60;
    const buckets = new Array(N).fill(0);
    const bucketMs = Math.max(1, Math.ceil(tMax / N));
    for (const ev of visibleEvents) {
      const idx = Math.min(N - 1, Math.floor(ev.t_ms / bucketMs));
      buckets[idx] += 1;
    }
    const max = Math.max(...buckets, 1);
    return buckets.map((n) => (n / max) * 100);
  }, [visibleEvents, tMax]);

  const cursorX = tMax ? (currentT / tMax) * W : 0;

  return (
    <div className="rp-timeline">
      <LaneGutter lanes={lanes} watchingKey={watchingKey} dimmedKeys={dimmedKeys} />
      <div className="rp-track-col">
        <svg viewBox={`0 0 ${W} ${svgHeight}`} preserveAspectRatio="none" style={{ width: "100%", height: svgHeight }}>
          {lanes.map((l) => {
            const y = laneYC(l.key);
            return <rect key={l.key} x={0} y={y - 4} width={W} height={8} rx={3} fill="var(--bg-soft)" />;
          })}
          
          {lanes.flatMap((l) =>
            (absentSpans[l.key] || []).map((s, i) => {
              const x0 = tMax ? (s.t0 / tMax) * W : 0;
              const x1 = tMax ? (s.t1 / tMax) * W : 0;
              const y = laneYC(l.key);
              return (
                <rect
                  key={`${l.key}-absent-${i}`}
                  x={x0}
                  y={y - 8}
                  width={Math.max(1, x1 - x0)}
                  height={16}
                  rx={3}
                  fill="var(--ink-muted)"
                  opacity={0.16}
                >
                  <title>{`${l.label} — ${s.reason}`}</title>
                </rect>
              );
            }),
          )}
          {visibleEvents.map((ev, i) => {
            const y = laneYC(laneOf(ev));
            const x = tMax ? (ev.t_ms / tMax) * W : 0;
            return <line key={i} x1={x} y1={y - 7} x2={x} y2={y + 7} stroke={ev._c.color} strokeWidth={1.4} opacity={0.9} />;
          })}
          <g>
            {markers.map((m, i) => {
              const x = tMax ? (m.t_ms / tMax) * W : 0;
              return (
                <g key={i} transform={`translate(${x}, 0)`} style={{ cursor: "pointer" }} onClick={() => onMarkerClick(m.t_ms)}>
                  <line x1={0} y1={0} x2={0} y2={svgHeight} stroke="var(--color-marker)" strokeWidth={2} strokeDasharray="3 2" />
                  <polygon points="0,0 10,4 0,8" fill="var(--color-marker)" />
                  <title>
                    {m.label || m.kind || "marker"} — t={m.t_ms}ms · {m.author || "?"}
                  </title>
                </g>
              );
            })}
          </g>
          
          {videoMode &&
            videoGaps.map((g, i) => {
              const x0 = tMax ? (g.t0 / tMax) * W : 0;
              const x1 = tMax ? (g.t1 / tMax) * W : 0;
              return (
                <rect
                  key={`gap-${i}`}
                  x={x0}
                  y={0}
                  width={Math.max(1, x1 - x0)}
                  height={svgHeight}
                  fill="url(#rp-gap-hatch)"
                >
                  <title>No video recorded here ({Math.round((g.t1 - g.t0) / 1000)}s)</title>
                </rect>
              );
            })}
          <defs>
            <pattern id="rp-gap-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <rect width="6" height="6" fill="var(--ink-muted)" opacity={0.07} />
              <line x1="0" y1="0" x2="0" y2="6" stroke="var(--ink-muted)" strokeWidth="2" opacity={0.18} />
            </pattern>
          </defs>
          <line x1={cursorX} y1={0} x2={cursorX} y2={svgHeight} stroke="var(--accent)" strokeWidth={2} />
        </svg>
        <div className="replay-scrubber">
          <Scrubber tMax={tMax} currentT={currentT} onScrub={onScrub} />
          <div className="replay-density">
            {density.map((h, i) => (
              <span key={i} className="density-bar" style={{ height: `${h}%` }} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
