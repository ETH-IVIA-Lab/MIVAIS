import { cursorColor } from "./classify";
import type { ReplayCursor } from "./types";

export function CursorOverlay({ cursors }: { cursors: Record<string, ReplayCursor> | null }) {
  const live = cursors
    ? Object.entries(cursors).filter(([, c]) => typeof c.x === "number" && typeof c.y === "number")
    : [];

  return (
    <div id="cursor-layer" aria-hidden="true">
      <div
        style={{
          position: "absolute",
          top: 6,
          left: 6,
          zIndex: 10,
          background: "rgba(9,9,11,.75)",
          color: "#fff",
          fontSize: 10,
          fontWeight: 600,
          padding: "3px 7px",
          borderRadius: 5,
          pointerEvents: "none",
        }}
      >
        {live.length ? `${live.length} cursor${live.length > 1 ? "s" : ""}` : "no cursor at this moment"}
      </div>
      {live.map(([actor, c]) => {
        const sid = actor.replace(/^user:/, "");
        const col = cursorColor(sid);
        const label = c.row_name ? String(c.row_name) : sid.slice(0, 6);
        return (
          <div key={actor} className="replay-cursor" style={{ position: "absolute", left: `${(c.x! * 100).toFixed(2)}%`, top: `${(c.y! * 100).toFixed(2)}%`, color: col, zIndex: 8 }}>
            <span
              style={{
                position: "absolute",
                left: -9,
                top: -9,
                width: 22,
                height: 22,
                borderRadius: "50%",
                border: `2px solid ${col}`,
                opacity: 0.6,
              }}
            />
            <svg width={20} height={20} viewBox="0 0 16 16" fill={col} style={{ display: "block", position: "relative" }}>
              <path d="M0 0l5 12 2-5 5-2z" />
            </svg>
            <span className="replay-cursor-tag" style={{ background: col, color: "#fff", fontSize: 10, fontWeight: 600, padding: "2px 5px", borderRadius: 4, whiteSpace: "nowrap", position: "relative" }}>
              {label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
