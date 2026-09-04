import { CameraIcon } from "./icons";
import type { Lane } from "./types";
import { LANE_STEP } from "./useReplayEngine";

export function LaneGutter({
  lanes,
  watchingKey,
  dimmedKeys,
}: {
  lanes: Lane[];
  watchingKey?: string | null;
  dimmedKeys?: Set<string>;
}) {
  return (
    <div className="rp-lane-gutter">
      {lanes.map((l) => {
        const watching = !!watchingKey && l.key === watchingKey;
        const dimmed = !!dimmedKeys?.has(l.key);
        return (
          <div
            key={l.key}
            className={`rp-lane-row ${watching ? "watching" : ""}`}
            style={{ height: LANE_STEP, opacity: dimmed ? 0.45 : 1 }}
            title={
              watching
                ? `${l.label} — you are watching this participant's recording`
                : dimmed
                  ? `${l.label} — VA not on screen at the playhead`
                  : l.label
            }
          >
            <span className="rp-lane-ico" style={{ color: dimmed ? "var(--ink-muted)" : l.color }}>
              ●
            </span>
            <span className="rp-lane-name">{l.label}</span>
            {watching && (
              <span
                className="rp-lane-cam"
                role="img"
                aria-label="currently watching this participant"
                style={{ marginLeft: 6, display: "inline-flex", color: l.color }}
              >
                <CameraIcon />
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
