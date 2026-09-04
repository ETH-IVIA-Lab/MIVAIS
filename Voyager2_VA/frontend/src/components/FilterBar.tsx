import { useMemo, useState } from "react";
import type { DataField, FilterSpec } from "../types";


export function FilterBar({
  fields,
  dataset,
  filters,
  onChange,
}: {
  fields: DataField[];
  dataset: Record<string, unknown>[];
  filters: FilterSpec[];
  onChange: (filters: FilterSpec[]) => void;
}) {
  const [openValues, setOpenValues] = useState<string | null>(null);

  const filterable = fields.filter((f) => !f.is_count && (f.type === "quantitative" || f.type === "nominal"));
  const active = new Set(filters.map((f) => f.field));

  const extents = useMemo(() => {
    const out: Record<string, [number, number]> = {};
    for (const f of filterable) {
      if (f.type !== "quantitative") continue;
      const vals = dataset.map((r) => r[f.field]).filter((v): v is number => typeof v === "number");
      if (vals.length) out[f.field] = [Math.min(...vals), Math.max(...vals)];
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset, fields]);

  const uniques = useMemo(() => {
    const out: Record<string, string[]> = {};
    for (const f of filterable) {
      if (f.type !== "nominal") continue;
      const seen = new Set<string>();
      for (const r of dataset) {
        const v = r[f.field];
        if (v != null) seen.add(String(v));
        if (seen.size > 30) break;
      }
      out[f.field] = [...seen].sort();
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset, fields]);

  function addFilter(fieldName: string) {
    const f = filterable.find((x) => x.field === fieldName);
    if (!f || active.has(fieldName)) return;
    if (f.type === "quantitative") {
      const [min, max] = extents[fieldName] ?? [0, 0];
      onChange([...filters, { field: fieldName, type: "quantitative", min, max }]);
    } else {
      onChange([...filters, { field: fieldName, type: "nominal", values: uniques[fieldName] ?? [] }]);
    }
  }

  function patch(i: number, p: Partial<FilterSpec>) {
    onChange(filters.map((f, idx) => (idx === i ? { ...f, ...p } : f)));
  }

  function remove(i: number) {
    onChange(filters.filter((_, idx) => idx !== i));
  }

  return (
    <div className="filter-bar">
      <span className="filter-bar-label">FILTER</span>
      {filters.map((f, i) => (
        <span className="filter-chip" key={`${f.field}${f.valid ? ":valid" : ""}`}>
          <b>{f.field}</b>
          {f.valid ? (
            <span className="muted-inline">not null</span>
          ) : f.type === "quantitative" ? (
            <>
              <input
                type="number"
                value={f.min ?? ""}
                step="any"
                onChange={(e) => patch(i, { min: e.target.value === "" ? undefined : Number(e.target.value) })}
              />
              –
              <input
                type="number"
                value={f.max ?? ""}
                step="any"
                onChange={(e) => patch(i, { max: e.target.value === "" ? undefined : Number(e.target.value) })}
              />
            </>
          ) : (
            <span className="filter-values">
              <button type="button" onClick={() => setOpenValues(openValues === f.field ? null : f.field)}>
                {(f.values ?? []).length}/{(uniques[f.field] ?? []).length} values ▾
              </button>
              {openValues === f.field && (
                <span className="filter-values-pop">
                  {(uniques[f.field] ?? []).map((v) => {
                    const checked = (f.values ?? []).includes(v);
                    return (
                      <label key={v}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() =>
                            patch(i, {
                              values: checked ? (f.values ?? []).filter((x) => x !== v) : [...(f.values ?? []), v],
                            })
                          }
                        />
                        {v}
                      </label>
                    );
                  })}
                </span>
              )}
            </span>
          )}
          <button type="button" className="filter-remove" title="Remove filter" onClick={() => remove(i)}>
            ×
          </button>
        </span>
      ))}
      <select
        className="filter-add"
        value=""
        onChange={(e) => {
          if (e.target.value) addFilter(e.target.value);
          e.target.value = "";
        }}
      >
        <option value="">+ Add filter…</option>
        {filterable
          .filter((f) => !active.has(f.field))
          .map((f) => (
            <option key={f.field} value={f.field}>
              {f.field}
            </option>
          ))}
      </select>
    </div>
  );
}
