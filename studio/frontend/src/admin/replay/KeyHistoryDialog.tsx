import { useEffect, useRef, useState } from "react";

export interface KeyChange {
  t_ms: number;
  cause: { label: string; color: string };
  from: unknown;
  to: unknown;
}

function fmtT(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(2)}s`;
}

const MAX_DIFF_LINES = 400;

function pretty(v: unknown): string[] {
  if (v === undefined) return ["∅ (unset)"];
  try {
    return JSON.stringify(v, null, 2).split("\n");
  } catch {
    return [String(v)];
  }
}

type DiffLine = { kind: "ctx" | "del" | "add"; text: string };


function lineDiff(a: string[], b: string[]): DiffLine[] {
  if (a.length + b.length > MAX_DIFF_LINES * 2) {
    return [
      ...a.slice(0, MAX_DIFF_LINES).map((text): DiffLine => ({ kind: "del", text })),
      { kind: "ctx", text: "… (truncated)" },
      ...b.slice(0, MAX_DIFF_LINES).map((text): DiffLine => ({ kind: "add", text })),
    ];
  }
  const n = a.length;
  const m = b.length;
  // LCS table
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ kind: "ctx", text: a[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ kind: "del", text: a[i] });
      i++;
    } else {
      out.push({ kind: "add", text: b[j] });
      j++;
    }
  }
  while (i < n) out.push({ kind: "del", text: a[i++] });
  while (j < m) out.push({ kind: "add", text: b[j++] });
  return out;
}


function foldContext(lines: DiffLine[], context = 2): (DiffLine | { kind: "fold"; count: number })[] {
  const keep = new Array(lines.length).fill(false);
  lines.forEach((l, idx) => {
    if (l.kind !== "ctx") {
      for (let k = Math.max(0, idx - context); k <= Math.min(lines.length - 1, idx + context); k++) keep[k] = true;
    }
  });
  const out: (DiffLine | { kind: "fold"; count: number })[] = [];
  let folded = 0;
  lines.forEach((l, idx) => {
    if (keep[idx]) {
      if (folded > 0) {
        out.push({ kind: "fold", count: folded });
        folded = 0;
      }
      out.push(l);
    } else {
      folded++;
    }
  });
  if (folded > 0) out.push({ kind: "fold", count: folded });
  return out;
}


export function KeyHistoryDialog({
  keyName,
  changes,
  onClose,
  onJump,
}: {
  keyName: string;
  changes: KeyChange[];
  onClose: () => void;
  onJump: (t_ms: number) => void;
}) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);


  const [collapsed, setCollapsed] = useState<Set<number>>(new Set());
  function toggle(idx: number) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  }

  return (
    <dialog
      ref={dialogRef}
      className="rp-dialog rp-history-dialog"
      onClick={(e) => e.target === dialogRef.current && onClose()}
      onClose={onClose}
    >
      <header className="rp-dialog-head">
        <h3>
          History of <code className="insp-key">{keyName}</code>
        </h3>
        <span className="muted small">
          {changes.length} change{changes.length === 1 ? "" : "s"}
        </span>
      </header>
      <div className="rp-history-body">
        {changes.length === 0 && <p className="muted small">This key never changed during the session.</p>}
        {changes.map((c, idx) => {
          const isCollapsed = collapsed.has(idx);
          return (
          <section key={idx} className="rp-history-entry">
            <div className="rp-history-meta" onClick={() => toggle(idx)} title={isCollapsed ? "Expand diff" : "Collapse diff"}>
              <button
                type="button"
                className="mono small rp-history-jump"
                title="Jump the playhead here"
                onClick={(e) => {
                  e.stopPropagation();
                  onJump(c.t_ms);
                }}
              >
                {fmtT(c.t_ms)}
              </button>
              <span className="insp-ico" style={{ color: c.cause.color }}>
                ●
              </span>
              <strong className="small">{c.cause.label}</strong>
              <span className="rp-history-toggle">{isCollapsed ? "▸" : "▾"}</span>
            </div>
            {!isCollapsed && (
            <pre className="rp-diff">
              {foldContext(lineDiff(pretty(c.from), pretty(c.to))).map((l, i) =>
                l.kind === "fold" ? (
                  <span key={i} className="fold">
                    ⋯ {l.count} unchanged line{l.count === 1 ? "" : "s"}
                    {"\n"}
                  </span>
                ) : (
                  <span key={i} className={l.kind}>
                    {l.kind === "del" ? "- " : l.kind === "add" ? "+ " : "  "}
                    {l.text}
                    {"\n"}
                  </span>
                ),
              )}
            </pre>
            )}
          </section>
          );
        })}
      </div>
      <footer className="rp-dialog-foot">
        <button type="button" className="button" onClick={onClose}>
          Close
        </button>
      </footer>
    </dialog>
  );
}
