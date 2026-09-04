import { useRef } from "react";
import type { RecordedEvent } from "./usePlayback";

export function Timeline({ events, totalT, currentT, onSeekPct }: { events: RecordedEvent[]; totalT: number; currentT: number; onSeekPct: (pct: number) => void }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const pct = totalT > 0 ? (currentT / totalT) * 100 : 0;

  const seekFromClientX = (clientX: number) => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (!rect) return;
    const p = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    onSeekPct(p);
  };

  const onMouseDown = (e: React.MouseEvent) => {
    seekFromClientX(e.clientX);
    const onMove = (ev: MouseEvent) => seekFromClientX(ev.clientX);
    const onUp = () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  return (
    <div id="timeline-wrap" ref={wrapRef} onMouseDown={onMouseDown}>
      <div id="timeline-track">
        <div id="timeline-fill" style={{ width: `${pct}%` }} />
      </div>
      <div id="timeline-thumb" style={{ left: `${pct}%` }} />
      {totalT > 0 &&
        events.map((ev, i) => <div key={i} className={`tl-marker ${ev.type}`} style={{ left: `${((ev.t / totalT) * 100).toFixed(3)}%` }} />)}
    </div>
  );
}
