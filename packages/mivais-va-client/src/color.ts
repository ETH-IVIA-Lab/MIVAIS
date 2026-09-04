/** Deterministic per-session color palette, shared by cursors/pills/chat across all apps. */
export const DEFAULT_USER_COLORS = [
  "#7c3aed",
  "#0891b2",
  "#be185d",
  "#b45309",
  "#047857",
  "#c2410c",
  "#1d4ed8",
  "#9f1239",
];

/** Hashes an id (e.g. a session id) into a stable color from the palette. */
export function hashUserColor(id: string, palette: readonly string[] = DEFAULT_USER_COLORS): string {
  let h = 0;
  for (let i = 0; i < id.length; i++) {
    h = (h * 31 + id.charCodeAt(i)) >>> 0;
  }
  return palette[h % palette.length];
}
