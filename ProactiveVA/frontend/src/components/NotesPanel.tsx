import { useMemo, useState } from "react";
import { useProactive } from "../context";
import { applyMarksHtml, filteredMessages, markupHtml, timeSince } from "../helpers";
import type { Mc3Message, Note } from "../types";

function nameFor(n: Note): string {
  const byAgent = !(n.by || "").startsWith("user:");
  if (byAgent) return "@Assistant";
  const sid = (n.by || "").split(":")[1] || "";
  return "@" + (sid.slice(0, 5) || "Analyst");
}

function avatarFor(n: Note): string {
  const byAgent = !(n.by || "").startsWith("user:");
  if (byAgent) return "A";
  return (n.by || "U").slice(-1).toUpperCase();
}

export function NotesPanel({ dataset }: { dataset: Mc3Message[] }) {
  const { worldState, sendAction } = useProactive();
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [title, setTitle] = useState("");
  const [label, setLabel] = useState("");
  const [flash, setFlash] = useState<string | null>(null);
  
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  const notes = worldState.notes || [];
  const staged = worldState.staged_evidence || [];

  const filtered = useMemo(() => {
    const ql = q.toLowerCase();
    return notes.filter((n) => {
      const byAgent = !(n.by || "").startsWith("user:");
      if (filter === "user" && byAgent) return false;
      if (filter === "agent" && !byAgent) return false;
      if (filter === "flagged" && !(n.comments || []).length) return false;
      if (ql) {
        const blob = (n.title + " " + n.label + " " + (n.comments || []).map((c) => c.comment).join(" ")).toLowerCase();
        if (!blob.includes(ql)) return false;
      }
      return true;
    });
  }, [notes, q, filter]);

  const submitNote = () => {
    const t = title.trim();
    const l = label.trim();
    if (!t && !l) return;
    
    let evidence = staged.slice();
    if (!evidence.length) evidence = (worldState.highlighted_message_ids || []).slice();
    if (!evidence.length)
      evidence = filteredMessages(dataset, worldState)
        .slice(0, 20)
        .map((m) => m.id);
    sendAction({ action: "add_note", title: t, label: l, view: worldState.focused_view || "messages", evidence });
    setTitle("");
    setLabel("");
    setFlash("Note added");
    setTimeout(() => setFlash(null), 1200);
  };

  const showEvidence = (n: Note) => {
    const ids = (n.evidence || []).slice(0, 50);
    sendAction({ action: "highlight_messages", message_ids: ids });
    setTimeout(() => {
      const first = ids[0];
      if (!first) return;
      const row = document.querySelector(`.message-row[data-id="${CSS.escape(first)}"]`);
      if (row) row.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 120);
  };

  return (
    <section className="panel" id="notes">
      <div className="notes-search">
        <input placeholder="Search notes…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="all">All submitters</option>
          <option value="user">Mine only</option>
          <option value="agent">Assistant only</option>
          <option value="flagged">Flagged</option>
        </select>
      </div>
      <div className="body">
        {!filtered.length && (
          <div className="empty-hint">
            {notes.length ? "No notes match the current search." : "No notes yet. Findings appear here."}
          </div>
        )}
        {filtered.map((n) => {
          const byAgent = !(n.by || "").startsWith("user:");
          const allKeywords = (n.comments || []).flatMap((c) => c.keywords || []);
          return (
            <div key={n.id} className={`note${byAgent ? " by-agent" : ""}`}>
              <div className="head">
                <span className="avatar">{avatarFor(n)}</span>
                <span className="who">{nameFor(n)}</span>
                <span className="when">{timeSince(n.timestamp)}</span>
                <span className="trash" title="Delete note" onClick={() => sendAction({ action: "delete_note", id: n.id })}>
                  ×
                </span>
              </div>
              <div className="row">
                <b>View:</b> {n.view || "—"}
              </div>
              <div className="row title">{n.title || "Finding"}</div>
              <div className="row label" dangerouslySetInnerHTML={applyMarksHtml(n.label || "", allKeywords)} />
              {(n.evidence || []).length > 0 && (
                <div className="row">
                  <b>Evidence:</b> {n.evidence!.length} message{n.evidence!.length === 1 ? "" : "s"}
                </div>
              )}
              {(n.comments || []).map((c, i) => {
                const key = `${n.id}:${i}`;
                if (dismissed.has(key)) return null;
                return (
                  <div key={key} className={`comment ${c.type || ""}`}>
                    <div className="head">{(c.type || "note").replace("_", " ")}</div>
                    <div className="body-txt" dangerouslySetInnerHTML={markupHtml(c.comment || "")} />
                    {c.correction && (
                      <div>
                        <b>Suggested correction:</b> <span dangerouslySetInnerHTML={markupHtml(c.correction)} />
                      </div>
                    )}
                    <div className="actions">
                      <button onClick={() => setDismissed((prev) => new Set(prev).add(key))}>Accept</button>
                      <button onClick={() => setDismissed((prev) => new Set(prev).add(key))}>Reject</button>
                    </div>
                  </div>
                );
              })}
              {(n.evidence || []).length > 0 && (
                <div className="actions">
                  <button onClick={() => showEvidence(n)}>Show evidence</button>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className={`stage-bar${staged.length ? "" : " empty"}`}>
        <span>
          {staged.length
            ? `${staged.length} message${staged.length === 1 ? "" : "s"} staged as evidence`
            : "No messages staged — click rows in the Messages list to add"}
        </span>
        {staged.length > 0 && <button onClick={() => sendAction({ action: "clear_staged_evidence" })}>Clear</button>}
      </div>
      <div className="note-form">
        <input
          placeholder="Title (e.g. Fire at Dancing Dolphin)"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <textarea placeholder="Label / details" value={label} onChange={(e) => setLabel(e.target.value)} />
        <button onClick={submitNote}>{flash || "Add note"}</button>
      </div>
    </section>
  );
}
