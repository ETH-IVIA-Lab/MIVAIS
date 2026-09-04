import { useEffect } from "react";
import { apiPost } from "../../lib/api";

export function useVaEventBridge(iframeUrl: string | null | undefined, onRelayed?: () => void) {
  useEffect(() => {
    if (!iframeUrl) return;
    let vaOrigin: string | null = null;
    try {
      vaOrigin = new URL(iframeUrl).origin;
    } catch {
      vaOrigin = null;
    }

    const handler = async (ev: MessageEvent) => {
      if (vaOrigin && ev.origin !== vaOrigin) return;
      const d = ev.data as
        | { source?: string; kind?: string; event?: { type?: string }; action?: unknown }
        | undefined;
      if (!d || (d.source !== "mivais-va" && d.source !== "podium" && d.source !== "voyager")) return;
      let event: Record<string, unknown> | null = null;
      if (d.kind === "va_event" && d.event && d.event.type) event = d.event;
      else if (d.kind === "user_action" && d.action) event = { type: "user_action", action: d.action };
      if (!event) return;
      try {
        await apiPost("/api/p/va/event", event);
        onRelayed?.();
      } catch {
        // network hiccup — the periodic step poll will catch up
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [iframeUrl, onRelayed]);
}
