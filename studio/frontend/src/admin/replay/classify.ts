import type { ClassifiedEvent, EventCategory, ReplayCategoryDef, ReplayEvent } from "./types";

export const CAT_COLOR: Record<string, string> = {
  cursor: "var(--ink-muted)",
  ranking: "var(--color-brand-500)",
  chat: "var(--color-mixed-500)",
  agent: "var(--color-agent-600)",
  task: "var(--color-gateway-500)",
  presence: "var(--color-permission-500)",
  state: "var(--ink-muted)",
  other: "var(--ink-muted)",
};

const USER_PALETTE = ["#2563eb", "#0891b2", "#7c3aed", "#be185d", "#0d9488", "#b45309", "#dc2626", "#1d4ed8"];
const CURSOR_PALETTE = ["#7c3aed", "#0891b2", "#be185d", "#b45309", "#047857", "#c2410c", "#1d4ed8", "#9f1239"];
const CATEGORY_PALETTE = ["#2563eb", "#0d9488", "#c026d3", "#ea580c", "#65a30d", "#0891b2", "#be185d", "#7c3aed"];

function hashPalette(name: string, palette: string[]): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return palette[h % palette.length];
}


export const AGENT_NEUTRAL = "var(--ink-muted)";
export function userColor(pid: string): string {
  return hashPalette(pid, USER_PALETTE);
}
export function cursorColor(sid: string): string {
  return hashPalette(sid, CURSOR_PALETTE);
}

export function categoryColor(key: string): string {
  return hashPalette(key, CATEGORY_PALETTE);
}


function buildColorLookup(defs: ReplayCategoryDef[] | undefined): (cat: string) => string {
  const overrides: Record<string, string> = {};
  for (const d of defs || []) if (d.color) overrides[d.key] = d.color;
  return (cat: string) => overrides[cat] || CAT_COLOR[cat] || categoryColor(cat);
}

export function prettyAgent(a: string | undefined): string {
  return (a || "agent").replace(/_/g, " ");
}


const USER_ACT_CAT: Record<string, EventCategory> = {
  cursor_move: "cursor",
  chat_message: "chat",
  publish_bus: "chat",
};
const USER_ACT_LABEL: Record<string, string> = {
  cursor_move: "moved cursor",
  chat_message: "sent a message",
  publish_bus: "published",
};

function classifyOne(ev: ReplayEvent): { cat: EventCategory; label: string; actor?: string } {
  if (ev.type === "cursor_update") return { cat: "cursor", label: "cursor movement" };
  if (ev.type === "agent_action") {
    const m = ev.meta || {};
    const actor = m.actor || "agent";
    let lbl = m.key ? `${prettyAgent(actor)} → ${m.key}` : prettyAgent(actor);
    if (m.value_repr) {
      let vr = String(m.value_repr);
      if (vr.length > 36) vr = `${vr.slice(0, 36)}…`;
      lbl += ` = ${vr}`;
    }
    return { cat: "agent", actor, label: lbl };
  }
  if (ev.type === "user_action") {
    const m = ev.meta || {};
    const cat = USER_ACT_CAT[m.action ?? ""] || "other";
    const who = String(m.actor || "").replace(/^user:/, "").slice(0, 6);
    const base = USER_ACT_LABEL[m.action ?? ""] || (m.action || "action").replace(/_/g, " ");
    return { cat, label: who ? `${base} · ${who}` : base };
  }
  if (ev.type === "bus_message") {
    const m = ev.meta || {};
    const sender = m.sender as string | undefined;
    const topic = (m.topic as string | undefined) || "";
    
    const agentSender = sender && !sender.startsWith("user:") ? sender : undefined;
    if (topic === "chat.message") {
      let text = String(m.text ?? "");
      if (text.length > 36) text = `${text.slice(0, 36)}…`;
      
      return {
        cat: "chat",
        actor: agentSender,
        label: text ? `${prettyAgent(sender)}: ${text}` : `${prettyAgent(sender)} sent a message`,
      };
    }
    if (agentSender) return { cat: "agent", actor: agentSender, label: `${prettyAgent(sender)} → ${topic || "bus"}` };
    return { cat: "chat", label: topic ? `bus · ${topic}` : "bus message" };
  }
  if (ev.type === "connect") return { cat: "presence", label: "user connected" };
  if (ev.type === "disconnect") return { cat: "presence", label: "user disconnected" };
  if (ev.type === "snapshot") return { cat: "state", label: "full snapshot" };
  if (ev.type === "state_update") return { cat: "state", label: "state update" };
  if (ev.source === "studio") return { cat: "task", label: (ev.type || "event").replace(/_/g, " ") };
  return { cat: "other", label: (ev.type || "event").replace(/_/g, " ") };
}


export function classifyTimeline(timeline: ReplayEvent[], categoryDefs?: ReplayCategoryDef[]): ClassifiedEvent[] {
  const colorFor = buildColorLookup(categoryDefs);
  return timeline.map((ev) => {
    const base = classifyOne(ev);
    const cat = ev.taxonomy_category || base.cat;
    const label = (ev.taxonomy_category && ev.taxonomy_label) || base.label;
    const c = { cat, label, actor: base.actor };
    const color = colorFor(cat);
    const filterKeys = c.actor ? [c.cat, `agent:${c.actor}`] : [c.cat];
    return { ...ev, _c: { ...c, filterKeys, color } };
  });
}
