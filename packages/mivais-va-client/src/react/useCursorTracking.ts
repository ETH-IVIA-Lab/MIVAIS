import { useEffect } from "react";

/**
 * Wires a global `mousemove`/`mouseleave` listener that reports normalized
 * (0-1) viewport-fraction cursor positions via `sendCursor`. Only touches
 * x/y — the `row_name` a row's own hover handlers last reported is left
 * alone (the server preserves it across x/y-only updates), so plain
 * pointer movement never clobbers which row is currently "hovered".
 */
export function useCursorTracking(sendCursor: (rowName?: string | null, x?: number | null, y?: number | null) => void) {
  useEffect(() => {
    const onMove = (ev: MouseEvent) => {
      sendCursor(undefined, ev.clientX / window.innerWidth, ev.clientY / window.innerHeight);
    };
    const onLeave = () => sendCursor(null, null, null);

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseleave", onLeave);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseleave", onLeave);
    };
  }, [sendCursor]);
}
