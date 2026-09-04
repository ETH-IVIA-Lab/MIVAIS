import type { FilterDef } from "./useReplayEngine";
import type { ClassifiedEvent } from "./types";

export function CategoryFilters({
  filters,
  visible,
  classified,
  onToggle,
}: {
  filters: FilterDef[];
  visible: Record<string, boolean>;
  classified: ClassifiedEvent[];
  onToggle: (key: string) => void;
}) {
  
  const counts: Record<string, number> = {};
  for (const ev of classified) {
    for (const k of ev._c.filterKeys) counts[k] = (counts[k] || 0) + 1;
  }

  const chip = (f: FilterDef) => {
    const on = visible[f.key] !== false;
    return (
      <button key={f.key} type="button" className={`cat-chip ${on ? "" : "off"}`} title={`Toggle ${f.label}`} onClick={() => onToggle(f.key)}>
        <span className="cat-ico" style={{ color: f.color }}>
          ●
        </span>
        <span>{f.label}</span>
        <span className="cat-n">{counts[f.key] || 0}</span>
      </button>
    );
  };

  const actionChips = filters.filter((f) => f.group === "action");
  const agentChips = filters.filter((f) => f.group === "agent");
  const sysChip = filters.find((f) => f.group === "system");

  return (
    <div className="replay-filters">
      <span className="rp-filter-label">Show</span>
      {actionChips.map(chip)}
      {agentChips.length > 0 && (
        <>
          <span className="rp-filter-sep" />
          <span className="rp-filter-label">Agents</span>
          {agentChips.map(chip)}
        </>
      )}
      <span className="rp-filter-sep" />
      {sysChip && chip(sysChip)}
    </div>
  );
}
