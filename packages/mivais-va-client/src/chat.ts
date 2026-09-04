/**
 * Safe, framework-agnostic parser for the small chat markup dialect used by
 * agent/user chat messages: `[mark:text]` (highlight, also used to trigger a
 * row highlight in host UIs) and `**bold**`. Returns plain segments so
 * consumers (React) render them directly — no HTML strings, no manual
 * escaping needed.
 */
export type ChatSegment =
  | { type: "text"; value: string }
  | { type: "mark"; value: string }
  | { type: "bold"; value: string };

export function parseMarkedText(text: string): ChatSegment[] {
  const segments: ChatSegment[] = [];
  const markParts = text.split(/\[mark:(.*?)\]/g);
  markParts.forEach((part, i) => {
    if (i % 2 === 1) {
      segments.push({ type: "mark", value: part });
      return;
    }
    // Even indices are plain text — further split on **bold** runs.
    const boldParts = part.split(/\*\*(.*?)\*\*/g);
    boldParts.forEach((bp, j) => {
      if (!bp) return;
      segments.push(j % 2 === 1 ? { type: "bold", value: bp } : { type: "text", value: bp });
    });
  });
  return segments;
}

export type ChatLevel = "warning" | "ok" | "info";

/** Strips a leading `[!]`/`[ok]`/`[i]` level marker (used by agent insight messages). */
export function stripLevelPrefix(text: string): { level: ChatLevel | null; text: string } {
  const m = text.match(/^\[(!|ok|i)\]\s*/);
  if (!m) return { level: null, text };
  const level: ChatLevel = m[1] === "!" ? "warning" : m[1] === "ok" ? "ok" : "info";
  return { level, text: text.slice(m[0].length) };
}
