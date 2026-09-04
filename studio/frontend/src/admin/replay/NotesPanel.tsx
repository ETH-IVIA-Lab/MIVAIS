import { useEffect, useState, type FormEvent } from "react";
import { apiGet, apiPost, ApiError } from "../../lib/api";
import type { ReplayNote } from "./types";

function fmtT(ms: number): string {
  return ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(2)}s`;
}

export function NotesPanel({ sessionId, onJump }: { sessionId: string; onJump: (t_ms: number) => void }) {
  const [notes, setNotes] = useState<ReplayNote[]>([]);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const res = await apiGet<{ notes: ReplayNote[] }>(`/api/admin/sessions/${sessionId}/notes`);
      setNotes(res.notes || []);
    } catch {
      // transient
    }
  }

  useEffect(() => {
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    setError(null);
    try {
      const res = await apiPost<{ notes: ReplayNote[] }>(`/api/admin/sessions/${sessionId}/note`, { text: t });
      setText("");
      setNotes(res.notes || []);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    }
  }

  return (
    <section className="card replay-notes" style={{ marginTop: 14 }}>
      <header className="replay-section-head">
        <h2>
          Notes <span className="muted small" style={{ fontWeight: 400 }}>— shared with all users</span>
        </h2>
        <span className="muted small">{notes.length || "none yet"}</span>
      </header>
      <ol className="note-list" style={{ listStyle: "none", padding: 0, margin: 0, maxHeight: 240, overflowY: "auto", display: "flex", flexDirection: "column", gap: 6 }}>
        {notes.length === 0 && (
          <li className="muted small" style={{ padding: "6px 8px" }}>
            No notes yet — be the first.
          </li>
        )}
        {notes.map((n, i) => (
          <li key={i} style={{ padding: "8px 10px", background: "var(--bg-soft)", borderRadius: 8 }}>
            <div style={{ fontSize: "0.76em", color: "var(--ink-muted)" }}>
              <strong>{n.author || "admin"}</strong> · {new Date(n.wall_clock).toLocaleString()}
              {n.t_ms != null && (
                <>
                  {" · "}
                  <a
                    href="#"
                    className="mono"
                    onClick={(e) => {
                      e.preventDefault();
                      onJump(n.t_ms!);
                    }}
                  >
                    {fmtT(n.t_ms)}
                  </a>
                </>
              )}
            </div>
            <div>{n.text}</div>
          </li>
        ))}
      </ol>
      {error && <div className="alert error" style={{ marginTop: 8 }}>{error}</div>}
      <form onSubmit={onSubmit} style={{ display: "flex", gap: 8, marginTop: 10 }}>
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          autoComplete="off"
          placeholder="Add a note for other users… (saved at the current playhead time)"
          style={{ flex: 1 }}
        />
        <button className="button primary" type="submit">
          Send
        </button>
      </form>
    </section>
  );
}
