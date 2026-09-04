/** Minimal RFC-4180-ish CSV parser for the client-side "Open CSV…" import.
 * Handles quoted fields (with "" escapes), CRLF, and numeric coercion.
 * The rows never leave the browser except as a `load_dataset` action into the
 * current room's in-memory world — nothing is persisted server-side. */

const MAX_ROWS = 5000;

function parseLine(line: string): string[] {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (inQuotes) {
      if (c === '"') {
        if (line[i + 1] === '"') {
          cur += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        cur += c;
      }
    } else if (c === '"') {
      inQuotes = true;
    } else if (c === ",") {
      out.push(cur);
      cur = "";
    } else {
      cur += c;
    }
  }
  out.push(cur);
  return out;
}

const NUM_RE = /^-?\d+(\.\d+)?([eE][+-]?\d+)?$/;

export function parseCsv(text: string): Record<string, unknown>[] {
  const lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n").filter((l) => l.trim() !== "");
  if (lines.length < 2) return [];
  const header = parseLine(lines[0]).map((h, i) => h.trim() || `col_${i + 1}`);
  const rows: Record<string, unknown>[] = [];
  for (let li = 1; li < lines.length && rows.length < MAX_ROWS; li++) {
    const cells = parseLine(lines[li]);
    const row: Record<string, unknown> = {};
    header.forEach((h, i) => {
      const raw = (cells[i] ?? "").trim();
      if (raw === "") row[h] = null;
      else if (NUM_RE.test(raw)) row[h] = Number(raw);
      else row[h] = raw;
    });
    rows.push(row);
  }
  return rows;
}
