import { useEffect, useRef, useState } from "react";

const PRESETS = ["note", "stuck", "aha", "bug", "insight"];

function fmtT(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(2)}s`;
}

export function MarkerDialog({
  open,
  atT,
  quote = "",
  onClose,
  onSubmit,
}: {
  open: boolean;
  atT: number;
  quote?: string;
  onClose: () => void;
  onSubmit: (kind: string, label: string) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [kind, setKind] = useState("note");
  const [label, setLabel] = useState("");

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open) {
      setKind("note");
      setLabel("");
      if (!dialog.open) dialog.showModal();
    } else if (dialog.open) {
      dialog.close();
    }
  }, [open]);

  return (
    <dialog ref={dialogRef} className="rp-dialog" onClick={(e) => e.target === dialogRef.current && onClose()} onClose={onClose}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          onSubmit(kind.trim() || "note", label.trim());
        }}
      >
        <header className="rp-dialog-head">
          <h3>Add marker</h3>
          <span className="muted small">at {fmtT(atT)}</span>
        </header>
        {quote && (
          <blockquote className="marker-quote" style={{ whiteSpace: "normal", margin: "0 0 10px" }}>
            &ldquo;{quote}&rdquo;
          </blockquote>
        )}
        <label className="rp-field">
          <span>Kind</span>
          <div className="rp-kind-presets">
            {PRESETS.map((p) => (
              <button key={p} type="button" onClick={() => setKind(p)}>
                {p}
              </button>
            ))}
          </div>
          <input type="text" value={kind} onChange={(e) => setKind(e.target.value)} autoComplete="off" />
        </label>
        <label className="rp-field">
          <span>
            Label <span className="muted">(optional)</span>
          </span>
          <input type="text" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="What happened here?" autoComplete="off" />
        </label>
        <footer className="rp-dialog-foot">
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="button primary">
            Add marker
          </button>
        </footer>
      </form>
    </dialog>
  );
}
