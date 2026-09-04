/**
 * One-way bridge to an embedding MIVAIS Studio harness (a study task page
 * that iframes this VA). Consumed by Studio's participant task page
 * (`useVaEventBridge`) — the wire shape (`source`, `kind`, `event`) must stay
 * exactly as-is. `source` is a constant protocol marker that lets the
 * listener recognize MIVAIS messages among unrelated postMessage traffic;
 * it does not identify the app.
 */

export const HARNESS_SOURCE = "mivais-va";

export interface HarnessEvent {
  type: string;
  [key: string]: unknown;
}

export function relayToHarness(event: HarnessEvent): void {
  try {
    if (typeof window === "undefined") return;
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ source: HARNESS_SOURCE, kind: "va_event", event }, "*");
    }
  } catch {
    /* cross-origin parent without a listener, or no parent — ignore */
  }
}

export function relayAgentsRoster(
  agents: Array<{ id: string; role: string; description?: string }>,
): void {
  try {
    if (typeof window === "undefined") return;
    if (window.parent && window.parent !== window) {
      window.parent.postMessage({ source: HARNESS_SOURCE, kind: "agents", agents }, "*");
    }
  } catch {
    /* ignore */
  }
}
