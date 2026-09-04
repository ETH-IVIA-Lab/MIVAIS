import type { Mc3Message, ProactiveWorldState, TimeRange } from "./types";

export type FilterSkip = "hex" | "entity" | "keyword" | "time" | null;


export function filteredMessages(
  dataset: Mc3Message[],
  ws: Partial<ProactiveWorldState>,
  skip: FilterSkip = null,
): Mc3Message[] {
  const hex = ws.selected_hex;
  const ent = ws.selected_entity;
  const kws = (ws.keyword_filter || []).map((k) => k.toLowerCase());
  const tr: TimeRange | null | undefined = ws.time_range;
  return dataset.filter((m) => {
    if (skip !== "hex" && hex && m.hex_id !== hex) return false;
    if (skip !== "entity" && ent && !(m.entities || []).includes(ent)) return false;
    if (skip !== "keyword" && kws.length && !kws.some((k) => (m.message || "").toLowerCase().includes(k)))
      return false;
    if (skip !== "time" && tr && tr.start != null && (m.epoch || 0) < tr.start) return false;
    if (skip !== "time" && tr && tr.end != null && (m.epoch || 0) > tr.end) return false;
    return true;
  });
}

export interface HexStat {
  mb: number;
  cc: number;
  neg: number;
  pos: number;
  neu: number;
  n: number;
  risk: number;
  influence: number;
}


export function hexStats(messages: Mc3Message[]): Record<string, HexStat> {
  const total = messages.length || 1;
  const C = 1.5;
  const stats: Record<string, HexStat> = {};
  for (const m of messages) {
    if (!m.hex_id) continue;
    const s =
      stats[m.hex_id] ||
      (stats[m.hex_id] = { mb: 0, cc: 0, neg: 0, pos: 0, neu: 0, n: 0, risk: 0, influence: 0 });
    s.n += 1;
    if (m.type === "ccdata") s.cc += 1;
    else s.mb += 1;
    if (m.sentiment === "negative") s.neg += 1;
    else if (m.sentiment === "positive") s.pos += 1;
    else s.neu += 1;
  }
  for (const id of Object.keys(stats)) {
    const s = stats[id];
    const negFrac = s.mb > 0 ? s.neg / s.mb : 0;
    s.risk = s.mb * Math.exp(negFrac) + s.cc * C;
    s.influence = s.n / total;
  }
  return stats;
}


const ENTITY_TYPE: Record<string, string> = {
  POK: "org",
  Police: "org",
  Park: "location",
  Fire: "tag",
  Shooting: "tag",
  Standoff: "tag",
  Rally: "tag",
  Medical: "tag",
  Traffic: "tag",
};
export function entityType(id: string): string {
  return ENTITY_TYPE[id] || "tag";
}

export function timeSince(epoch?: number): string {
  if (!epoch) return "";
  const s = Date.now() / 1000 - epoch;
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `about ${m} min${m === 1 ? "" : "s"} ago`;
  const h = Math.floor(m / 60);
  return `${h}h ago`;
}

export function escapeHtml(s: unknown): string {
  if (s == null) return "";
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}


export function markupHtml(s: unknown): { __html: string } {
  let safe = escapeHtml(s);
  safe = safe.replace(
    /\[mark:([^\]]+)\]/g,
    '<b style="background:#fef3c7;padding:0 3px;border-radius:2px">$1</b>',
  );
  return { __html: safe };
}


export function applyMarksHtml(text: string, keywords: string[]): { __html: string } {
  let out = escapeHtml(text || "");
  for (const kw of keywords || []) {
    if (!kw) continue;
    const re = new RegExp("\\b" + kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "\\b", "gi");
    out = out.replace(re, (m) => `<span class="mark-hl">${m}</span>`);
  }
  return { __html: out };
}

export function fmtClock(epoch: number): string {
  return new Date(epoch * 1000).toISOString().slice(11, 16);
}
