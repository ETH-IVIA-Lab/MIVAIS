import { hashUserColor } from "../color.js";
import type { CursorMap } from "../types.js";

export interface CursorOverlayProps {
  cursors: CursorMap;
  ownSessionId: string;
  /** Custom user-color palette; defaults to the library palette. */
  palette?: readonly string[];
  /** DOM id of the overlay container (the CSS hook); default "cursor-overlay". */
  id?: string;
}

/**
 * Renders every OTHER user's live cursor as a pointer + short session-id
 * label, positioned by the normalized (0-1) viewport coordinates the server
 * broadcasts. The host app styles `.cursor-ptr` / `.cursor-label` (typically
 * fixed-position, pointer-events: none, brief left/top transition).
 */
export function CursorOverlay({ cursors, ownSessionId, palette, id = "cursor-overlay" }: CursorOverlayProps) {
  return (
    <div id={id}>
      {Object.entries(cursors).map(([agentId, info]) => {
        const sid = agentId.replace(/^user:/, "");
        if (sid === ownSessionId) return null;
        if (info.x == null || info.y == null) return null;
        const color = hashUserColor(sid, palette);
        return (
          <div
            key={agentId}
            className="cursor-ptr"
            style={{ left: `${(info.x * 100).toFixed(3)}vw`, top: `${(info.y * 100).toFixed(3)}vh` }}
          >
            <svg width="11" height="15" viewBox="0 0 11 15" fill={color} xmlns="http://www.w3.org/2000/svg">
              <path d="M0 0 L0 13 L3.5 9.5 L6 14.5 L8 13.5 L5.5 8.5 L10 8.5 Z" />
            </svg>
            <span className="cursor-label" style={{ background: color }}>
              {sid.slice(0, 4)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** Row-name → session ids currently hovering/dragging/drag-over that row, derived from a CursorMap. */
export function deriveRowCursorState(cursors: CursorMap, ownSessionId: string) {
  const hover: Record<string, string[]> = {};
  const dragging: Record<string, string[]> = {};
  const dragOver: Record<string, string[]> = {};
  Object.entries(cursors).forEach(([agentId, info]) => {
    const sid = agentId.replace(/^user:/, "");
    if (sid === ownSessionId) return;
    if (info.row_name) (hover[info.row_name] ??= []).push(sid);
    if (info.dragging) (dragging[info.dragging] ??= []).push(sid);
    if (info.drag_over) (dragOver[info.drag_over] ??= []).push(sid);
  });
  return { hover, dragging, dragOver };
}
