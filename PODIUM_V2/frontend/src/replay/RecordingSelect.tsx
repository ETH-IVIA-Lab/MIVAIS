import type { RecordingInfo } from "mivais-va-client";

export function RecordingSelect({
  recordings,
  selected,
  onSelect,
  statusText,
}: {
  recordings: RecordingInfo[];
  selected: string;
  onSelect: (filename: string) => void;
  statusText: string;
}) {
  return (
    <>
      <select id="rec-select" value={selected} onChange={(e) => onSelect(e.target.value)}>
        <option value="">— select a recording —</option>
        {recordings.map((r) => (
          <option key={r.filename} value={r.filename}>
            {r.filename} ({(r.size_bytes / 1024).toFixed(0)} KB, {r.created_at.replace("T", " ").slice(0, 19)})
          </option>
        ))}
      </select>
      <div className="conn" id="replay-status" style={{ marginLeft: 8 }}>
        {statusText}
      </div>
    </>
  );
}
