import { TYPE_ABBR } from "../types";
import type { ShelfEntry } from "../types";

const AGGREGATES = ["none", "mean", "median", "min", "max", "sum", "count"];
const TIME_UNITS = ["", "year", "quarter", "month", "day", "hours", "minutes", "yearmonth", "yearmonthdate"];

export function ShelfCapsule({
  entry,
  onChange,
  onRemove,
}: {
  entry: ShelfEntry;
  onChange: (patch: Partial<ShelfEntry>) => void;
  onRemove: () => void;
}) {
  const abbr = TYPE_ABBR[entry.type as keyof typeof TYPE_ABBR] ?? "N";
  const isWild = entry.field.startsWith("?");
  const cls = isWild ? "W" : abbr;
  const displayName = entry.field === "*" ? "COUNT(*)" : entry.field;
  const isQ = entry.type === "quantitative";
  const isT = entry.type === "temporal";

  return (
    <span className={`shelf-capsule ${cls}`}>
      <span>{displayName}</span>
      {isQ && entry.field !== "*" && (
        <>
          <select className="agg-select" value={entry.aggregate} onChange={(e) => onChange({ aggregate: e.target.value })}>
            {AGGREGATES.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
          <label className="bin-label">
            <input type="checkbox" className="bin-check" checked={entry.bin} onChange={(e) => onChange({ bin: e.target.checked })} />
            bin
          </label>
        </>
      )}
      {isT && (
        <select className="tu-select" value={entry.timeUnit} onChange={(e) => onChange({ timeUnit: e.target.value })}>
          {TIME_UNITS.map((u) => (
            <option key={u} value={u}>
              {u || "none"}
            </option>
          ))}
        </select>
      )}
      <button type="button" className="remove-btn" title="Remove" onClick={onRemove}>
        ×
      </button>
    </span>
  );
}
