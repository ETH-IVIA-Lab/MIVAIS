export function timeAgo(ts: string | number | undefined): string {
  if (!ts) return "";
  const seconds = typeof ts === "number" ? ts : Date.parse(ts) / 1000;
  const diff = Math.floor(Date.now() / 1000 - seconds);
  if (diff < 5) return "just now";
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

export function actorColor(actor: string): string {
  if (!actor) return "#e6edf3";
  if (actor.startsWith("user:")) return "#39d3f2";
  if (actor === "svm_ranker") return "#818cf8";
  if (actor === "nl_command") return "#c084fc";
  if (actor === "gateway") return "#f59e0b";
  if (actor === "system") return "#8b949e";
  return "#e6edf3";
}

export function valueDesc(val: unknown): string {
  if (val === null || val === undefined) return "null";
  if (Array.isArray(val)) return `Array[${val.length}]`;
  if (typeof val === "object") return `Object{${Object.keys(val).length}}`;
  if (typeof val === "string") return `"${val.slice(0, 24)}${val.length > 24 ? "…" : ""}"`;
  return String(val);
}
