import { useEffect, useRef } from "react";
import type { ClassifiedEvent } from "./types";

function fmtT(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(2)}s`;
}

export function EventStream({
  classified,
  visible,
  currentIndex,
  activeTaskLabel,
  onSelect,
}: {
  classified: ClassifiedEvent[];
  visible: Record<string, boolean>;
  currentIndex: number;
  activeTaskLabel: string | null;
  onSelect: (t_ms: number) => void;
}) {
  const scrollerRef = useRef<HTMLOListElement>(null);
  const activeRef = useRef<HTMLLIElement>(null);

  const SPAN = 60;
  const lo = Math.max(0, currentIndex - SPAN);
  const hi = Math.min(classified.length, currentIndex + SPAN);
  const rows: { ev: ClassifiedEvent; i: number }[] = [];
  for (let i = lo; i < hi; i++) {
    const ev = classified[i];
    if (!ev._c.filterKeys.every((k) => visible[k] !== false)) continue;
    rows.push({ ev, i });
  }

  useEffect(() => {
    const scroller = scrollerRef.current;
    const active = activeRef.current;
    if (!scroller || !active) return;
    const sr = scroller.getBoundingClientRect();
    const ar = active.getBoundingClientRect();
    const delta = ar.top - sr.top - (scroller.clientHeight / 2 - ar.height / 2);
    if (Math.abs(delta) > 1) scroller.scrollTop += delta;
  }, [currentIndex]);

  return (
    <aside className="replay-events card" style={{height: "100%"}}>
      <header className="replay-section-head">
        <h2>Events &amp; agent interactions</h2>
        <span className="muted small">{activeTaskLabel ? `task: ${activeTaskLabel}` : "—"}</span>
      </header>
      <ol className="event-stream" ref={scrollerRef}>
        {rows.length === 0 && (
          <li className="muted small" style={{ padding: "6px 8px" }}>
            No events match the current filters.
          </li>
        )}
        {rows.map(({ ev, i }) => {
          const active = i === currentIndex;
          return (
            <li
              key={i}
              ref={active ? activeRef : undefined}
              className={`event-item cat-${ev._c.cat} ${active ? "active" : ""}`}
              style={{ borderLeft: `3px solid ${ev._c.color}` }}
              onClick={() => onSelect(ev.t_ms)}
            >
              <span className="mono small">{fmtT(ev.t_ms)}</span>
              <span className="ev-ico" style={{ color: ev._c.color }}>
                ●
              </span>
              <span className="ev-label">{ev._c.label}</span>
              {ev.task_id && <span className="event-task">{ev.task_id}</span>}
            </li>
          );
        })}
      </ol>
    </aside>
  );
}
