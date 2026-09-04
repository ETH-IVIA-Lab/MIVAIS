import { useState } from "react";
import { ShelfCapsule } from "./ShelfCapsule";
import type { DragField } from "./FieldList";
import type { ShelfEntry } from "../types";

export function ShelfRow({
  label,
  channel,
  entries,
  onDrop,
  onChange,
  onRemove,
  placeholder,
}: {
  label: string;
  channel: string;
  entries: ShelfEntry[];
  onDrop: (channel: string, field: DragField) => void;
  onChange: (target: { channel: string } | { anyIdx: number }, patch: Partial<ShelfEntry>) => void;
  onRemove: (target: { channel: string } | { anyIdx: number }) => void;
  placeholder: string;
}) {
  const [dragOver, setDragOver] = useState(false);
  const occupied = entries.length > 0;

  return (
    <div className="encoding-panel-row">
      <div className="shelf">
        <span className="shelf-label">{label}</span>
        <div
          className={`shelf-drop${occupied ? " occupied" : ""}${dragOver ? " drag-over" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            try {
              const data: DragField = JSON.parse(e.dataTransfer.getData("application/json"));
              onDrop(channel, data);
            } catch {
              /* ignore malformed drop payload */
            }
          }}
        >
          {occupied ? (
            entries.map((entry, i) => (
              <ShelfCapsule
                key={i}
                entry={entry}
                onChange={(patch) => onChange(channel === "any" ? { anyIdx: i } : { channel }, patch)}
                onRemove={() => onRemove(channel === "any" ? { anyIdx: i } : { channel })}
              />
            ))
          ) : (
            <span className="shelf-placeholder">{placeholder}</span>
          )}
        </div>
      </div>
    </div>
  );
}
