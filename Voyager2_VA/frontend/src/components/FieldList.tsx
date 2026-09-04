import { TYPE_ABBR } from "../types";
import type { DataField } from "../types";

export interface DragField {
  field: string;
  type: string;
  isCount?: boolean;
}

const GROUPS: Array<{ label: string; type: DataField["type"] }> = [
  { label: "Quantitative", type: "quantitative" },
  { label: "Nominal", type: "nominal" },
  { label: "Temporal", type: "temporal" },
  { label: "Ordinal", type: "ordinal" },
];

function setDragData(ev: React.DragEvent, data: DragField) {
  ev.dataTransfer.setData("application/json", JSON.stringify(data));
  ev.dataTransfer.effectAllowed = "copy";
}

export function FieldList({
  fields,
  onAutoAssign,
}: {
  fields: DataField[];
  onAutoAssign: (field: string, type: string, abbr: string) => void;
}) {
  const countField = fields.find((f) => f.is_count);

  return (
    <div className="panel-left-body">
      {GROUPS.map(({ label, type }) => {
        const group = fields.filter((f) => !f.is_count && f.type === type);
        if (!group.length) return null;
        const abbr = TYPE_ABBR[type];
        return (
          <div className="field-group" key={type}>
            <div className="field-group-label">{label}</div>
            {group.map((f) => (
              <div
                key={f.field}
                className="field-pill"
                draggable
                onDragStart={(e) => setDragData(e, { field: f.field, type: f.type })}
              >
                <span className={`dot ${abbr}`} />
                <span className="name" title={f.field}>
                  {f.field}
                </span>
                <button
                  type="button"
                  className="add-btn"
                  title="Add to best shelf"
                  onClick={() => onAutoAssign(f.field, f.type, abbr)}
                >
                  +
                </button>
              </div>
            ))}
          </div>
        );
      })}

      {countField && (
        <div className="field-group">
          <div className="field-group-label">Count</div>
          <div
            className="field-pill"
            draggable
            onDragStart={(e) => setDragData(e, { field: "*", type: "quantitative", isCount: true })}
          >
            <span className="dot Q" />
            <span className="name">COUNT (*)</span>
            <button type="button" className="add-btn" title="Add to best shelf" onClick={() => onAutoAssign("*", "quantitative", "Q")}>
              +
            </button>
          </div>
        </div>
      )}

      <div className="field-group">
        <div className="field-group-label">Wildcards</div>
        {(["Quantitative", "Nominal", "Temporal"] as const).map((t) => {
          const type = t.toLowerCase() as DataField["type"];
          const abbr = TYPE_ABBR[type];
          return (
            <div
              key={t}
              className="wildcard-pill"
              draggable
              onDragStart={(e) => setDragData(e, { field: `?${abbr}`, type })}
            >
              ? {t}
            </div>
          );
        })}
      </div>
    </div>
  );
}
