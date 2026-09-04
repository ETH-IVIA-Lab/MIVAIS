import { CHANNELS } from "../types";
import type { ShelfEntry } from "../types";
import type { DragField } from "./FieldList";
import { ShelfRow } from "./ShelfRow";

const MARKS = ["auto", "point", "bar", "line", "area", "tick", "rect"];

export function EncodingPanel({
  mark,
  shelves,
  anyFields,
  onMarkChange,
  onDrop,
  onChange,
  onRemove,
}: {
  mark: string;
  shelves: Record<string, ShelfEntry | null>;
  anyFields: ShelfEntry[];
  onMarkChange: (mark: string) => void;
  onDrop: (channel: string, field: DragField) => void;
  onChange: (target: { channel: string } | { anyIdx: number }, patch: Partial<ShelfEntry>) => void;
  onRemove: (target: { channel: string } | { anyIdx: number }) => void;
}) {
  return (
    <div className="encoding-panel">
      <div className="mark-selector">
        <label>Mark</label>
        <select value={mark} onChange={(e) => onMarkChange(e.target.value)}>
          {MARKS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>
      <div>
        {CHANNELS.map((ch) => (
          <ShelfRow
            key={ch}
            label={ch}
            channel={ch}
            entries={shelves[ch] ? [shelves[ch] as ShelfEntry] : []}
            onDrop={onDrop}
            onChange={onChange}
            onRemove={onRemove}
            placeholder="Drop a field here"
          />
        ))}
        <ShelfRow
          label="any"
          channel="any"
          entries={anyFields}
          onDrop={onDrop}
          onChange={onChange}
          onRemove={onRemove}
          placeholder="Drop a field here (unspecified channel)"
        />
      </div>
    </div>
  );
}
